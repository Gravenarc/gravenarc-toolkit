# SPDX-License-Identifier: GPL-3.0-or-later
# Состояние сессии: последний мазок, снимок вершин до него, метка (marker), запомненная маска.
# Хранится только в памяти (до закрытия Blender / открытия другого файла).

import time

import bpy
import numpy as np
from bpy.app.handlers import persistent


class StrokeRecord:
    """Путь мазка: пиксели 3D-вида + нажим пера + сохранённый вид, чтобы повторить его после поворота камеры."""

    def __init__(self, obj_name, mode, region, rv3d):
        from .common import view_key
        self.obj_name = obj_name
        self.mode = mode                      # 'NORMAL' или 'INVERT' (мазок с Ctrl)
        self.points = []                      # [(x, y)] в пикселях области 3D-вида
        self.pressure = []                    # нажим пера 0..1 (мышь = 1)
        self.view_key = view_key(region, rv3d)
        self.persp = rv3d.perspective_matrix.copy()
        self.size = (region.width, region.height)
        self.created = time.time()
        self.kind = "stroke"                  # stroke / replay / line

    def add(self, x, y, pressure):
        p = float(pressure) if pressure and pressure > 0.0 else 1.0
        if self.points:
            lx, ly = self.points[-1]
            if (x - lx) ** 2 + (y - ly) ** 2 < 0.25:   # стоим на месте — обновляем только нажим
                self.pressure[-1] = max(self.pressure[-1], p)
                return
        self.points.append((float(x), float(y)))
        self.pressure.append(p)

    def median_pressure(self):
        return float(np.median(self.pressure)) if self.pressure else 1.0


class _State:
    def __init__(self):
        self.clear()

    def clear(self):
        self.recording = None        # StrokeRecord, который пишется прямо сейчас
        self.last = None             # последний завершённый мазок
        self.before = None           # позиции вершин перед последним мазком (np.ndarray)
        self.before_obj = None       # (имя объекта, имя меша)
        self.replace_ok = False      # последнее действие — мазок, его можно заменить (Replace)
        self.marker = None
        self.marker_obj = None
        self.marker_time = 0.0
        self.saved_masks = {}        # имя меша -> маска (np.ndarray)
        self.last_elements = None    # точки последнего повтора (для Live Strength)
        self.last_mode = 'NORMAL'


STATE = _State()


def obj_key(ob):
    return (ob.name, ob.data.name, len(ob.data.vertices))


def take_before(ob):
    """Снимок позиций вершин перед мазком (для Mask Last и безопасного Replace)."""
    from .common import get_positions
    try:
        STATE.before = get_positions(ob.data)
        STATE.before_obj = obj_key(ob)
    except Exception:
        STATE.before = None
        STATE.before_obj = None


def before_for(ob):
    if STATE.before is None or STATE.before_obj != obj_key(ob):
        return None
    return STATE.before


@persistent
def on_load(_dummy=None):
    STATE.clear()

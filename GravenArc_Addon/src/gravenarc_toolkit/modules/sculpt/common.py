# SPDX-License-Identifier: GPL-3.0-or-later
# Общие функции скульпт-модуля: настройки, кисть, вьюпорт, лучи, снимки вершин.

import math

import bpy
import numpy as np
from mathutils import Vector
from bpy_extras import view3d_utils

# Пакет расширения целиком (bl_ext.<repo>.gravenarc_toolkit) — для настроек и папки пользователя.
ROOT_PACKAGE = __package__.rsplit(".modules.", 1)[0]


def prefs():
    """Настройки скульпт-модуля (GA_SculptPrefs) или None, если аддон не включён."""
    addon = bpy.context.preferences.addons.get(ROOT_PACKAGE)
    if addon is None or addon.preferences is None:
        return None
    return getattr(addon.preferences, "sculpt", None)


# ---------------------------------------------------------------- кисть

BRUSH_TOOLS = {"builtin.brush"}   # + все builtin_brush.* (Paint, Mask, Draw Face Sets)


def is_brush_tool(context):
    tools = getattr(context.workspace, "tools", None)
    if tools is None:
        return False
    tool = tools.from_space_view3d_mode('SCULPT', create=False)
    if tool is None:
        return True   # инструмент ещё не выбирался — по умолчанию это кисть
    return tool.idname in BRUSH_TOOLS or tool.idname.startswith("builtin_brush.")


def paint_brush(context):
    """(paint, brush, unified_settings) для Sculpt Mode."""
    paint = context.tool_settings.sculpt
    return paint, paint.brush, paint.unified_paint_settings


def strength_owner(context):
    """Где реально хранится сила: в общих настройках (Unified) или в самой кисти."""
    paint, brush, ups = paint_brush(context)
    return ups if ups.use_unified_strength else brush


def size_owner(context):
    paint, brush, ups = paint_brush(context)
    return ups if ups.use_unified_size else brush


def size_locked_scene(context):
    """True — размер кисти задан в единицах сцены (Radius Unit = Scene), иначе в пикселях."""
    owner = size_owner(context)
    return owner.use_locked_size == 'SCENE'


def brush_diameter_px(context, region, rv3d, world_point):
    """Диаметр кисти в пикселях экрана в точке world_point."""
    owner = size_owner(context)
    if owner.use_locked_size != 'SCENE':
        return float(owner.size)
    d_bu = owner.unprojected_size
    if world_point is None or rv3d is None:
        return 50.0
    right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    a = view3d_utils.location_3d_to_region_2d(region, rv3d, world_point)
    b = view3d_utils.location_3d_to_region_2d(region, rv3d, world_point + right * d_bu)
    if a is None or b is None:
        return 50.0
    return max(1.0, (b - a).length)


# ---------------------------------------------------------------- вьюпорт

def view3d_window(context):
    """(area, region, rv3d) — 3D-вид и его основная область (WINDOW).
    Работает и при нажатии кнопки на панели N (там context.region — это панель)."""
    areas = []
    if context.area is not None and context.area.type == 'VIEW_3D':
        areas.append(context.area)
    screen = context.screen
    if screen is not None:
        others = [a for a in screen.areas if a.type == 'VIEW_3D' and a not in areas]
        others.sort(key=lambda a: a.width * a.height, reverse=True)
        areas += others
    for area in areas:
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is not None:
            return area, region, area.spaces.active.region_3d
    return None, None, None


def view_key(region, rv3d):
    """Отпечаток вида: если он не изменился, 2D-координаты мазка можно брать как есть."""
    m = rv3d.perspective_matrix
    return (region.width, region.height) + tuple(round(v, 5) for row in m for v in row)


def fresh_depsgraph(context, ob):
    """Depsgraph с актуальной формой модели. В Sculpt Mode Blender не обновляет «вычисленную» копию
    меша после каждого мазка, и луч попадал бы в старую поверхность. Помечаем объект на пересчёт.
    С Dyntopo / Multires не трогаем (дорого и небезопасно) — там положение приблизительное."""
    dyntopo, multires = sculpt_limits(ob)
    if not (dyntopo or multires):
        ob.update_tag(refresh={'DATA'})
    return context.evaluated_depsgraph_get()


def raycast_local(context, region, rv3d, ob, xy, depsgraph=None):
    """Точка на поверхности объекта под пикселем xy, в координатах объекта (или None)."""
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, xy)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, xy)
    return raycast_world_ray(context, ob, origin, direction, depsgraph)


def raycast_world_ray(context, ob, origin, direction, depsgraph=None):
    mi = ob.matrix_world.inverted_safe()
    o = mi @ Vector(origin)
    d = (mi.to_3x3() @ Vector(direction)).normalized()
    if depsgraph is None:
        depsgraph = context.evaluated_depsgraph_get()
    try:
        hit, loc, _nor, _idx = ob.ray_cast(o, d, depsgraph=depsgraph)
    except (RuntimeError, ValueError):
        return None
    return loc.copy() if hit else None


def unproject_with_matrix(persp_matrix, width, height, xy):
    """Луч (origin, direction) из пикселя xy для СОХРАНЁННОГО вида (вид мог смениться)."""
    inv = persp_matrix.inverted_safe()
    nx = 2.0 * xy[0] / max(1, width) - 1.0
    ny = 2.0 * xy[1] / max(1, height) - 1.0
    near = inv @ Vector((nx, ny, -1.0, 1.0))
    far = inv @ Vector((nx, ny, 1.0, 1.0))
    if abs(near.w) < 1e-12 or abs(far.w) < 1e-12:
        return None
    a = near.xyz / near.w
    b = far.xyz / far.w
    d = b - a
    if d.length < 1e-12:
        return None
    return a, d.normalized()


# ---------------------------------------------------------------- ограничения

def sculpt_limits(ob):
    """(dyntopo, multires): включён ли Dyntopo и есть ли Multires со скульпт-уровнем > 0."""
    if ob is None or ob.type != 'MESH':
        return False, False
    dyntopo = bool(getattr(ob, "use_dynamic_topology_sculpting", False))
    multires = any(m.type == 'MULTIRES' and m.show_viewport and m.sculpt_levels > 0 for m in ob.modifiers)
    return dyntopo, multires


# ---------------------------------------------------------------- вершины и маска

def get_positions(me):
    a = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.attributes["position"].data.foreach_get("vector", a)
    return a.reshape(-1, 3)


def get_mask(me):
    """Маска Sculpt Mode как массив (0 — нет маски, 1 — полностью замаскировано)."""
    attr = me.attributes.get(".sculpt_mask")
    n = len(me.vertices)
    if attr is None or attr.domain != 'POINT' or attr.data_type != 'FLOAT':
        return np.zeros(n, dtype=np.float32)
    a = np.empty(n, dtype=np.float32)
    attr.data.foreach_get("value", a)
    return a


def bbox_diagonal(positions):
    if len(positions) == 0:
        return 1.0
    return float(np.linalg.norm(positions.max(axis=0) - positions.min(axis=0))) or 1.0


def tag_redraw(context):
    screen = context.screen
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def ensure_sculpt_mode():
    """После undo/переключений вернуть Sculpt Mode, если Blender из него вышел."""
    if bpy.context.mode != 'SCULPT':
        ob = bpy.context.active_object
        if ob is not None and ob.type == 'MESH':
            bpy.ops.object.mode_set(mode='SCULPT')


def strength_scale(factor):
    """Множитель силы кисти для «Repeat Strength». У большинства кистей лепки эффект ~ сила²,
    поэтому берём корень: Repeat Strength 2 ≈ вдвое выше, 0.5 ≈ вдвое ниже."""
    return math.sqrt(abs(factor))

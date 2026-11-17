# SPDX-License-Identifier: GPL-3.0-or-later
# Часть 1: запись мазка, повтор (Replay / Replace, Shift+R), Repeat Strength, Live Strength,
# Часть 2: прямая линия от конца прошлого мазка до курсора (Alt+L).
#
# Как записывается мазок: на ЛКМ в Sculpt Mode стоит наш оператор gravenarc.stroke_watch.
# Он ничего не «съедает» (PASS_THROUGH) — обычный мазок Blender идёт как всегда, — только
# запоминает начало и сразу (таймером) запускает невидимый gravenarc.stroke_recorder,
# который слушает движения мыши и нажим пера до отпускания кнопки.
# Повтор — это bpy.ops.sculpt.brush_stroke(stroke=[...]) по записанному пути текущей кистью.

import functools
import math
import time

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty
from bpy.types import Operator
from bpy_extras import view3d_utils

from . import common
from .common import prefs
from .state import STATE, StrokeRecord, before_for, take_before

MAX_DABS = 4000


# ---------------------------------------------------------------- геометрия пути

def resample(points, pressure, step):
    """Равномерные точки вдоль пути каждые step пикселей (как Spacing у кисти)."""
    if len(points) < 2:
        return list(points), list(pressure)
    out = [points[0]]
    outp = [pressure[0]]
    need = step
    for i in range(1, len(points)):
        ax, ay = points[i - 1]
        bx, by = points[i]
        seg = math.hypot(bx - ax, by - ay)
        if seg <= 1e-9:
            continue
        pos = 0.0
        while seg - pos >= need:
            pos += need
            t = pos / seg
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
            outp.append(pressure[i - 1] + (pressure[i] - pressure[i - 1]) * t)
            need = step
        need -= seg - pos
    last = points[-1]
    if math.hypot(out[-1][0] - last[0], out[-1][1] - last[1]) > step * 0.3:
        out.append(last)
        outp.append(pressure[-1])
    return out, outp


def path_length(points):
    return sum(math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
               for i in range(1, len(points)))


def path_in_view(context, rec, region, rv3d, ob, points=None, pressure=None):
    """Путь мазка в пикселях ТЕКУЩЕГО вида. Если вид повернули — переносим через поверхность модели."""
    points = rec.points if points is None else points
    pressure = rec.pressure if pressure is None else pressure
    if common.view_key(region, rv3d) == rec.view_key:
        return list(points), list(pressure)
    dg = common.fresh_depsgraph(context, ob)
    out, outp = [], []
    mw = ob.matrix_world
    for xy, p in zip(points, pressure):
        ray = common.unproject_with_matrix(rec.persp, rec.size[0], rec.size[1], xy)
        if ray is None:
            continue
        loc = common.raycast_world_ray(context, ob, ray[0], ray[1], dg)
        if loc is None:
            continue
        s = view3d_utils.location_3d_to_region_2d(region, rv3d, mw @ loc)
        if s is None:
            continue
        out.append((s.x, s.y))
        outp.append(p)
    return out, outp


def build_elements(context, region, rv3d, ob, points, pressure):
    """Точки мазка для sculpt.brush_stroke: шаг по Spacing текущей кисти, место — луч на модель."""
    if not points:
        return []
    dg = common.fresh_depsgraph(context, ob)
    first = None
    for xy in points:
        first = common.raycast_local(context, region, rv3d, ob, xy, dg)
        if first is not None:
            break
    if first is None:
        return []
    _paint, brush, _ups = common.paint_brush(context)
    diam = common.brush_diameter_px(context, region, rv3d, ob.matrix_world @ first)
    step = max(1.0, diam * brush.spacing / 100.0)
    length = path_length(points)
    if length / step > MAX_DABS:
        step = length / MAX_DABS
    pts, prs = resample(points, pressure, step)
    elems = []
    t = 0.0
    for (x, y), p in zip(pts, prs):
        loc = common.raycast_local(context, region, rv3d, ob, (x, y), dg)
        if loc is None:
            continue
        elems.append({
            "name": "", "location": loc, "mouse": (x, y), "mouse_event": (x, y),
            "pressure": max(0.0, min(1.0, p)), "size": diam, "time": t,
            "is_start": not elems, "x_tilt": 0.0, "y_tilt": 0.0,
        })
        t += 0.01
    return elems


# ---------------------------------------------------------------- выполнение мазка

def run_stroke(context, area, region, elems, mode, factor):
    """Провести мазок текущей кистью. factor — Repeat Strength (минус = инверсия)."""
    if not elems or factor == 0.0:
        return False
    owner = common.strength_owner(context)
    s0 = owner.strength
    m = mode
    if factor < 0.0:
        m = 'INVERT' if mode == 'NORMAL' else 'NORMAL'
    owner.strength = min(10.0, s0 * common.strength_scale(factor))
    try:
        with context.temp_override(area=area, region=region):
            bpy.ops.sculpt.brush_stroke(stroke=elems, mode=m)
    finally:
        common.strength_owner(bpy.context).strength = s0
    return True


def undo_last_stroke(context):
    """Отменить последний мазок (Ctrl+Z). Проверяем по снимку вершин, что отменили именно мазок;
    если нет — возвращаем как было (Redo) и сообщаем False."""
    ob = context.active_object
    before = before_for(ob)
    dyntopo, _multires = common.sculpt_limits(ob)
    if not bpy.ops.ed.undo.poll():
        return False
    bpy.ops.ed.undo()
    common.ensure_sculpt_mode()
    ob = bpy.context.active_object
    if before is not None and not dyntopo and ob is not None and len(ob.data.vertices) == len(before):
        cur = common.get_positions(ob.data)
        tol = 1e-5 * common.bbox_diagonal(before)
        if float(np.abs(cur - before).max(initial=0.0)) > tol:
            if bpy.ops.ed.redo.poll():
                bpy.ops.ed.redo()
                common.ensure_sculpt_mode()
            return False
    return True


def _sculpt_poll(context):
    ob = context.active_object
    return context.mode == 'SCULPT' and ob is not None and ob.type == 'MESH'


# ---------------------------------------------------------------- запись мазка

def _start_recorder(window, screen, area, region):
    try:
        if STATE.recording is None:
            return None
        with bpy.context.temp_override(window=window, screen=screen, area=area, region=region):
            bpy.ops.gravenarc.stroke_recorder('INVOKE_DEFAULT')
    except Exception as ex:   # окно закрыли и т.п. — мазок просто не запишется
        print("[GravenArc] stroke recorder:", ex)
        STATE.recording = None
    return None


class GRAVENARC_OT_stroke_watch(Operator):
    """Запоминает начало мазка и пропускает клик дальше — к обычной кисти Blender"""
    bl_idname = "gravenarc.stroke_watch"
    bl_label = "Record Stroke (GravenArc)"
    bl_description = "Records the brush stroke path so it can be replayed with Shift+R. Does not change the stroke"
    bl_options = {'INTERNAL'}

    mode: EnumProperty(items=[('NORMAL', "Normal", ""), ('INVERT', "Invert", "")], default='NORMAL')

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def invoke(self, context, event):
        try:
            region = context.region
            rv3d = context.region_data
            if region is not None and region.type == 'WINDOW' and rv3d is not None and common.is_brush_tool(context):
                ob = context.active_object
                p = prefs()
                if p is None or p.track_changes:
                    take_before(ob)
                rec = StrokeRecord(ob.name, self.mode, region, rv3d)
                rec.add(event.mouse_region_x, event.mouse_region_y, event.pressure)
                STATE.recording = rec
                bpy.app.timers.register(
                    functools.partial(_start_recorder, context.window, context.screen, context.area, region),
                    first_interval=0.0)
        except Exception as ex:
            print("[GravenArc] stroke watch:", ex)
        return {'PASS_THROUGH'}


class GRAVENARC_OT_stroke_recorder(Operator):
    """Невидимый слушатель: пишет путь и нажим, всё пропускает дальше"""
    bl_idname = "gravenarc.stroke_recorder"
    bl_label = "Stroke Recorder (GravenArc)"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if STATE.recording is None:
            return {'CANCELLED'}
        self._t0 = time.monotonic()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        rec = STATE.recording
        if rec is None:
            return {'FINISHED', 'PASS_THROUGH'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            rec.add(event.mouse_region_x, event.mouse_region_y, event.pressure)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            rec.add(event.mouse_region_x, event.mouse_region_y, event.pressure)
            self._finish(rec)
            return {'FINISHED', 'PASS_THROUGH'}
        elif event.type in {'ESC', 'WINDOW_DEACTIVATE'} or time.monotonic() - self._t0 > 600:
            self._finish(rec)
            return {'FINISHED', 'PASS_THROUGH'}
        return {'PASS_THROUGH'}

    @staticmethod
    def _finish(rec):
        STATE.recording = None
        if rec.points:
            STATE.last = rec
            STATE.last_elements = None
            STATE.replace_ok = True


# ---------------------------------------------------------------- Replay / Replace

def _check_last(self, context):
    """Последний мазок для активного объекта, иначе None (с сообщением)."""
    rec = STATE.last
    ob = context.active_object
    if rec is None:
        self.report({'WARNING'}, "No stroke recorded yet: make a stroke with the Left Mouse button first")
        return None
    if rec.obj_name != ob.name:
        self.report({'WARNING'}, f"The last stroke was made on '{rec.obj_name}', not on the active object")
        return None
    if not common.is_brush_tool(context):
        self.report({'WARNING'}, "Select a brush tool first (toolbar on the left, or Shift+Space)")
        return None
    return rec


class GRAVENARC_OT_replay_stroke(Operator):
    bl_idname = "gravenarc.replay_stroke"
    bl_label = "Replay Last Stroke"
    bl_description = ("Repeat the last stroke with the CURRENT brush and Repeat Strength. "
                      "With 'Replace Previous Stroke' the old stroke is undone first. Hotkey: Shift+R")
    bl_options = {'REGISTER'}

    action: EnumProperty(
        name="Action",
        items=[('AUTO', "As Set", "Use the 'Replace Previous Stroke' checkbox"),
               ('ADD', "Add on Top", "Draw the stroke again on top"),
               ('REPLACE', "Replace", "Undo the last stroke and draw it again")],
        default='AUTO', options={'SKIP_SAVE'})
    live: BoolProperty(name="Live Strength", default=True, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    # -- один повтор; возвращает True, если мазок нарисован
    def replay(self, context):
        p = prefs()
        rec = _check_last(self, context)
        if rec is None:
            return False
        area, region, rv3d = common.view3d_window(context)
        if region is None:
            self.report({'WARNING'}, "No 3D Viewport found")
            return False
        ob = context.active_object
        dyntopo, multires = common.sculpt_limits(ob)
        replace = self.action == 'REPLACE' or (self.action == 'AUTO' and p is not None and p.replace_previous)
        note = ""
        if replace and not STATE.replace_ok:
            replace = False
            note = " (nothing to replace: the last action was not a stroke, added on top)"
        if replace:
            if not undo_last_stroke(context):
                replace = False
                note = " (could not undo the old stroke safely, added on top)"
        ob = context.active_object
        if not replace and (p is None or p.track_changes):
            take_before(ob)
        pts, prs = path_in_view(context, rec, region, rv3d, ob)
        elems = build_elements(context, region, rv3d, ob, pts, prs)
        if not elems:
            if replace and bpy.ops.ed.redo.poll():   # вернуть отменённый мазок
                bpy.ops.ed.redo()
                common.ensure_sculpt_mode()
            self.report({'WARNING'}, "The stroke path is not over the model in this view")
            return False
        factor = p.repeat_strength if p is not None else 1.0
        drawn = run_stroke(context, area, region, elems, rec.mode, factor)
        STATE.last_elements = elems
        STATE.last_mode = rec.mode
        STATE.replace_ok = drawn
        self._drawn = drawn
        self._area, self._region = area, region
        self._factor = factor
        warn = " Dyntopo/Multires: position may be approximate." if (dyntopo or multires) else ""
        what = "Replaced" if replace else "Replayed"
        self.report({'WARNING'} if warn else {'INFO'}, f"{what} stroke, strength ×{factor:.2f}{note}{warn}")
        return True

    def execute(self, context):
        return {'FINISHED'} if self.replay(context) else {'CANCELLED'}

    def invoke(self, context, event):
        if not self.replay(context):
            return {'CANCELLED'}
        p = prefs()
        if not (self.live and p is not None and p.live_strength):
            return {'FINISHED'}
        # --- Live Strength: тянем мышь влево-вправо
        self._x0 = event.mouse_x
        self._f0 = self._factor
        self._target = self._factor
        self._applied = self._factor
        self._speed = (p.drag_speed if p else 1.0)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        self._header(context)
        return {'RUNNING_MODAL'}

    def _header(self, context):
        text = (f"Live Strength ×{self._target:+.2f}   ← weaker · stronger →   "
                f"LMB / Enter = apply · RMB / Esc = back to ×{self._f0:+.2f}")
        if self._area is not None:
            self._area.header_text_set(text)
        if context.workspace is not None:
            context.workspace.status_text_set("Live Strength: move the mouse left / right")

    def _apply(self, context, factor):
        """Перерисовать мазок с новой силой: отменить прошлый вариант и провести снова."""
        if self._drawn:
            if not undo_last_stroke(context):
                self.report({'WARNING'}, "Live Strength stopped: the undo history changed")
                return False
        self._drawn = run_stroke(bpy.context, self._area, self._region, STATE.last_elements, STATE.last_mode, factor)
        STATE.replace_ok = self._drawn
        self._applied = factor
        return True

    def _end(self, context):
        context.window_manager.event_timer_remove(self._timer)
        if self._area is not None:
            self._area.header_text_set(None)
        if context.workspace is not None:
            context.workspace.status_text_set(None)
        common.tag_redraw(context)

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            f = self._f0 + (event.mouse_x - self._x0) / 300.0 * self._speed
            f = max(-2.0, min(2.0, round(f / 0.05) * 0.05))
            if f != self._target:
                self._target = f
                self._header(context)
        elif event.type == 'TIMER':
            if self._target != self._applied:
                if not self._apply(context, self._target):
                    self._end(context)
                    return {'FINISHED'}
        elif event.value == 'PRESS' and event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'SPACE'}:
            if self._target != self._applied:
                self._apply(context, self._target)
            self._end(context)
            self.report({'INFO'}, f"Stroke strength ×{self._applied:+.2f}")
            return {'FINISHED'}
        elif event.value == 'PRESS' and event.type in {'RIGHTMOUSE', 'ESC'}:
            if self._applied != self._f0:
                self._apply(context, self._f0)
            self._end(context)
            return {'CANCELLED'}
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}   # вращать/приближать вид можно
        return {'RUNNING_MODAL'}


# ---------------------------------------------------------------- прямая линия (Alt+L)

class GRAVENARC_OT_straight_line(Operator):
    bl_idname = "gravenarc.straight_line"
    bl_label = "Straight Line to Cursor"
    bl_description = ("Like Shift+click in Photoshop: a straight stroke with the current brush from the end of "
                      "the last stroke to the mouse cursor. Put the mouse over the model and press Alt+L")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    target: FloatVectorProperty(size=2, options={'HIDDEN', 'SKIP_SAVE'})
    use_target: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if context.region is None or context.region.type != 'WINDOW' or context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Put the mouse over the model in the 3D Viewport and press Alt+L")
            return {'CANCELLED'}
        self.target = (event.mouse_region_x, event.mouse_region_y)
        self.use_target = True
        return self.execute(context)

    def execute(self, context):
        if not self.use_target:
            self.report({'WARNING'}, "Put the mouse over the model in the 3D Viewport and press Alt+L")
            return {'CANCELLED'}
        rec = _check_last(self, context)
        if rec is None:
            return {'CANCELLED'}
        area, region, rv3d = common.view3d_window(context)
        if region is None:
            return {'CANCELLED'}
        ob = context.active_object
        start_pts, _ = path_in_view(context, rec, region, rv3d, ob, rec.points[-1:], rec.pressure[-1:])
        if not start_pts:
            self.report({'WARNING'}, "The end of the last stroke is not visible in this view")
            return {'CANCELLED'}
        start = start_pts[0]
        target = (float(self.target[0]), float(self.target[1]))
        pressure = rec.median_pressure()
        p = prefs()
        if p is None or p.track_changes:
            take_before(ob)
        elems = build_elements(context, region, rv3d, ob, [start, target], [pressure, pressure])
        if len(elems) < 1:
            self.report({'WARNING'}, "The line does not touch the model")
            return {'CANCELLED'}
        run_stroke(context, area, region, elems, rec.mode, 1.0)
        line = StrokeRecord(ob.name, rec.mode, region, rv3d)
        line.points = [start, target]
        line.pressure = [pressure, pressure]
        line.kind = "line"
        STATE.last = line
        STATE.last_elements = elems
        STATE.last_mode = rec.mode
        STATE.replace_ok = True
        dyntopo, multires = common.sculpt_limits(ob)
        if dyntopo or multires:
            self.report({'WARNING'}, "Straight line drawn. Dyntopo/Multires: position may be approximate")
        return {'FINISHED'}


CLASSES = (
    GRAVENARC_OT_stroke_watch,
    GRAVENARC_OT_stroke_recorder,
    GRAVENARC_OT_replay_stroke,
    GRAVENARC_OT_straight_line,
)

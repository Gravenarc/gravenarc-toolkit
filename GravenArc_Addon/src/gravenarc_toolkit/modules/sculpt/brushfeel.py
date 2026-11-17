# SPDX-License-Identifier: GPL-3.0-or-later
# Часть 2: кисть «как в Photoshop».
#   Alt+ПКМ + тянуть: влево-вправо — размер, вверх-вниз — жёсткость (или сила, см. настройки).
#   Во время перетаскивания на месте курсора рисуется круг-превью.
#   Сглаживание мазка (Stabilize Stroke) — вкл/выкл горячей клавишей Shift+S.

import math

import bpy
from bpy.types import Operator

from . import common
from .common import prefs

SEGMENTS = 72
DEAD_ZONE = 6          # пикселей до выбора направления (Lock to One Direction)


def _circle(cx, cy, r, n=SEGMENTS):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def _draw_preview(op, _context):
    """Круг-превью: внешний — размер кисти, внутренний — жёсткость (где начинается спад)."""
    try:
        import blf
        import gpu
        from gpu_extras.batch import batch_for_shader
    except ImportError:
        return
    cx, cy = op.anchor
    r = op.radius_px()
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    vp = gpu.state.viewport_get()
    shader.bind()
    shader.uniform_float("viewportSize", (vp[2], vp[3]))

    def ring(radius, width, color):
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": _circle(cx, cy, radius)})
        shader.uniform_float("lineWidth", width)
        shader.uniform_float("color", color)
        batch.draw(shader)

    ring(r, 4.0, (0.0, 0.0, 0.0, 0.55))           # тёмная подложка — видно на светлой модели
    ring(r, 2.0, (1.0, 1.0, 1.0, 0.95))
    inner = r * op.value_hardness()
    if inner > 1.5:
        ring(inner, 1.5, (1.0, 0.62, 0.2, 0.9))    # оранжевый — твёрдая часть кисти
    ring(2.0, 2.0, (1.0, 1.0, 1.0, 0.9))          # точка в центре

    font = 0
    blf.size(font, 14)
    lines = [f"Size {op.size_text()}", op.vertical_text()]
    y = cy + r + 12
    for text in reversed(lines):
        w, h = blf.dimensions(font, text)
        blf.color(font, 0.0, 0.0, 0.0, 0.8)
        blf.position(font, cx - w / 2 + 1, y - 1, 0)
        blf.draw(font, text)
        blf.color(font, 1.0, 1.0, 1.0, 1.0)
        blf.position(font, cx - w / 2, y, 0)
        blf.draw(font, text)
        y += h + 6
    gpu.state.blend_set('NONE')


class GRAVENARC_OT_brush_drag(Operator):
    bl_idname = "gravenarc.brush_drag"
    bl_label = "Brush Size / Hardness Drag"
    bl_description = ("Photoshop-style: hold Alt+Right Mouse and drag. Left/right = brush size, "
                      "up/down = hardness (or strength, see settings). Release to apply, Esc to cancel")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return context.mode == 'SCULPT' and ob is not None and context.tool_settings.sculpt.brush is not None

    # ---- значения
    def radius_px(self):
        return max(1.0, self.d_px / 2.0)

    def value_hardness(self):
        return self.hardness if self.vertical == 'HARDNESS' else self.hardness0

    def size_text(self):
        if self.scene_locked:
            return f"{self.unproj:.3g} (scene units)"
        return f"{self.d_px:.0f} px"

    def vertical_text(self):
        if self.vertical == 'HARDNESS':
            return f"Hardness {self.hardness * 100:.0f}%"
        return f"Strength {self.strength:.2f}"

    # ---- запуск
    def invoke(self, context, event):
        paint, brush, _ups = common.paint_brush(context)
        # Трафарет (Stencil) использует Alt+ПКМ сам — уступаем ему
        slot = getattr(brush, "texture_slot", None)
        if brush.texture is not None and slot is not None and slot.map_mode == 'STENCIL':
            return {'PASS_THROUGH'}
        if context.region is None or context.region.type != 'WINDOW':
            return {'PASS_THROUGH'}
        p = prefs()
        self.vertical = p.drag_vertical if p else 'HARDNESS'
        self.lock_axis = p.drag_lock_axis if p else True
        self.speed = p.drag_speed if p else 1.0
        self.axis = None
        self.anchor = (event.mouse_region_x, event.mouse_region_y)
        self.start = (event.mouse_x, event.mouse_y)

        self.size_owner = common.size_owner(context)
        self.str_owner = common.strength_owner(context)
        self.scene_locked = self.size_owner.use_locked_size == 'SCENE'
        self.size0 = self.size_owner.size
        self.unproj0 = self.size_owner.unprojected_size
        self.hardness0 = brush.hardness
        self.strength0 = self.str_owner.strength
        self.hardness = self.hardness0
        self.strength = self.strength0
        self.unproj = self.unproj0
        # Диаметр в пикселях (для размера «в единицах сцены» — по точке под курсором)
        rv3d = context.region_data
        hit = None
        ob = context.active_object
        if ob is not None and ob.type == 'MESH' and rv3d is not None:
            loc = common.raycast_local(context, context.region, rv3d, ob, self.anchor)
            hit = ob.matrix_world @ loc if loc is not None else None
        if self.scene_locked:
            if hit is None:
                hit = context.scene.cursor.location.copy()
            self.d0_px = common.brush_diameter_px(context, context.region, rv3d, hit)
        else:
            self.d0_px = float(self.size0)
        self.d_px = self.d0_px

        self.show_brush0 = paint.show_brush
        paint.show_brush = False                      # прячем родной круг кисти — рисуем свой
        self._handle = bpy.types.SpaceView3D.draw_handler_add(_draw_preview, (self, None), 'WINDOW', 'POST_PIXEL')
        context.window.cursor_modal_set('CROSSHAIR')
        context.window_manager.modal_handler_add(self)
        self._status(context)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _status(self, context):
        if context.workspace is not None:
            what = "hardness" if self.vertical == 'HARDNESS' else "strength"
            context.workspace.status_text_set(
                f"Brush: ← → size · ↑ ↓ {what} · release Right Mouse / LMB = apply · Esc = cancel")

    # ---- применение
    def _apply_values(self, context):
        if self.scene_locked:
            self.unproj = max(1e-4, self.unproj0 * self.d_px / max(1.0, self.d0_px))
            self.size_owner.unprojected_size = self.unproj
        else:
            self.size_owner.size = int(round(max(1.0, min(5000.0, self.d_px))))
        if self.vertical == 'HARDNESS':
            common.paint_brush(context)[1].hardness = self.hardness
        else:
            self.str_owner.strength = self.strength

    def _restore(self, context):
        self.size_owner.size = self.size0
        self.size_owner.unprojected_size = self.unproj0
        common.paint_brush(context)[1].hardness = self.hardness0
        self.str_owner.strength = self.strength0

    def _finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        context.tool_settings.sculpt.show_brush = self.show_brush0
        context.window.cursor_modal_restore()
        if context.workspace is not None:
            context.workspace.status_text_set(None)
        common.tag_redraw(context)

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            dx = (event.mouse_x - self.start[0]) * self.speed
            dy = (event.mouse_y - self.start[1]) * self.speed
            if self.lock_axis and self.axis is None and max(abs(dx), abs(dy)) > DEAD_ZONE:
                self.axis = 'X' if abs(dx) >= abs(dy) else 'Y'
            if self.lock_axis:
                if self.axis != 'X':
                    dx = 0.0
                if self.axis != 'Y':
                    dy = 0.0
            self.d_px = max(1.0, self.d0_px + dx)
            self.hardness = max(0.0, min(1.0, self.hardness0 + dy / 300.0))
            self.strength = max(0.0, min(10.0, self.strength0 + dy / 300.0))
            self._apply_values(context)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if (event.type == 'RIGHTMOUSE' and event.value == 'RELEASE') or \
                (event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'SPACE'} and event.value == 'PRESS'):
            self._apply_values(context)
            self._finish(context)
            return {'FINISHED'}
        if event.type == 'ESC' and event.value == 'PRESS':
            self._restore(context)
            self._finish(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class GRAVENARC_OT_toggle_smoothing(Operator):
    bl_idname = "gravenarc.toggle_smoothing"
    bl_label = "Toggle Stroke Smoothing"
    bl_description = ("Turn stroke smoothing (Stabilize Stroke, like Smoothing in Photoshop) on or off "
                      "for the current brush. Hotkey: Shift+S")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT' and context.tool_settings.sculpt.brush is not None

    def execute(self, context):
        brush = context.tool_settings.sculpt.brush
        brush.use_smooth_stroke = not brush.use_smooth_stroke
        if brush.use_smooth_stroke:
            self.report({'INFO'}, f"Stroke smoothing ON: radius {brush.smooth_stroke_radius} px, "
                                  f"factor {brush.smooth_stroke_factor:.2f}")
        else:
            self.report({'INFO'}, "Stroke smoothing OFF")
        return {'FINISHED'}


class GRAVENARC_OT_smoothing_preset(Operator):
    bl_idname = "gravenarc.smoothing_preset"
    bl_label = "Smoothing Preset"
    bl_description = "Quick smoothing amount for the current brush, like the Smoothing % in Photoshop"
    bl_options = {'REGISTER'}

    percent: bpy.props.IntProperty(name="Smoothing %", default=50, min=0, max=100)

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT' and context.tool_settings.sculpt.brush is not None

    def execute(self, context):
        brush = context.tool_settings.sculpt.brush
        t = self.percent / 100.0
        if t <= 0.0:
            brush.use_smooth_stroke = False
        else:
            brush.use_smooth_stroke = True
            brush.smooth_stroke_radius = int(round(10 + 140 * t))      # 10..150 px
            brush.smooth_stroke_factor = 0.5 + 0.45 * t                 # 0.50..0.95
        self.report({'INFO'}, f"Smoothing {self.percent}%")
        return {'FINISHED'}


CLASSES = (
    GRAVENARC_OT_brush_drag,
    GRAVENARC_OT_toggle_smoothing,
    GRAVENARC_OT_smoothing_preset,
)

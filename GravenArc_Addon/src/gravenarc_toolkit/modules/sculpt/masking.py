# SPDX-License-Identifier: GPL-3.0-or-later
# Часть 1: операции с маской Sculpt Mode.
#   Mask Last Stroke (Alt+R), Set Marker / Mask Since Marker, Remember / Recall Mask,
#   Separate Masked / Delete Masked, Delete Hidden, Reset Settings.
#
# Маска — это атрибут меша «.sculpt_mask» (0..1 на вершину). Мы пишем его прямо в Sculpt Mode.
# Чтобы Ctrl+Z отменял нашу маску одним шагом, перед записью вызываем стандартную заливку маски
# (paint.mask_flood_fill) — она кладёт в историю undo старую маску, — и сразу пишем свою.
# С Multires маска живёт на уровнях подразделения, с Dyntopo — в BMesh: там эти функции не работают.

import time

import bmesh
import bpy
import numpy as np
from bpy.props import EnumProperty
from bpy.types import Operator

from . import common
from .common import prefs
from .props import RESET_PROPS
from .state import STATE, before_for, obj_key

MASK_ATTR = ".sculpt_mask"


def _sculpt_poll(context):
    ob = context.active_object
    return context.mode == 'SCULPT' and ob is not None and ob.type == 'MESH'


def _refuse_limits(self, ob, allow_dyntopo=False):
    """Сообщение и True, если функция не работает с Dyntopo / Multires."""
    dyntopo, multires = common.sculpt_limits(ob)
    if multires:
        self.report({'WARNING'}, "Not available with Multires: its mask lives on the subdivision levels. "
                                 "Apply or remove the Multires modifier first")
        return True
    if dyntopo and not allow_dyntopo:
        self.report({'WARNING'}, "Not available with Dyntopo: the vertex list changes with every stroke. "
                                 "Turn Dyntopo off (Ctrl+D) or use Voxel Remesh")
        return True
    return False


def write_mask(context, values):
    """Записать маску активному объекту в Sculpt Mode (с шагом undo)."""
    ob = context.active_object
    if bpy.ops.paint.mask_flood_fill.poll():
        bpy.ops.paint.mask_flood_fill(mode='VALUE', value=1.0)   # шаг undo со старой маской
    ob = bpy.context.active_object
    me = ob.data
    attr = me.attributes.get(MASK_ATTR)
    if attr is None:
        attr = me.attributes.new(MASK_ATTR, 'FLOAT', 'POINT')
    attr.data.foreach_set("value", np.ascontiguousarray(values, dtype=np.float32))
    me.update()
    p = prefs()
    if p is not None and p.refresh_reenter:
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='SCULPT')
    common.tag_redraw(context)
    STATE.replace_ok = False


def _changed(positions_now, positions_before):
    tol = 1e-6 * common.bbox_diagonal(positions_before)
    d = np.linalg.norm(positions_now - positions_before, axis=1)
    return d > tol


class GRAVENARC_OT_mask_last(Operator):
    bl_idname = "gravenarc.mask_last"
    bl_label = "Mask Last Stroke"
    bl_description = "Mask the area that the last stroke changed (protect it from the next strokes). Hotkey: Alt+R"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def execute(self, context):
        ob = context.active_object
        if _refuse_limits(self, ob):
            return {'CANCELLED'}
        before = before_for(ob)
        if before is None:
            p = prefs()
            if p is not None and not p.track_changes:
                self.report({'WARNING'}, "Turn on 'Track Changed Area' in the GravenArc settings")
            else:
                self.report({'WARNING'}, "No stroke on this object yet (or the mesh changed since)")
            return {'CANCELLED'}
        changed = _changed(common.get_positions(ob.data), before)
        if not changed.any():
            self.report({'WARNING'}, "The last stroke did not move any vertex")
            return {'CANCELLED'}
        write_mask(context, changed.astype(np.float32))
        self.report({'INFO'}, f"Masked {int(changed.sum()):,} vertices changed by the last stroke")
        return {'FINISHED'}


class GRAVENARC_OT_set_marker(Operator):
    bl_idname = "gravenarc.set_marker"
    bl_label = "Set Marker"
    bl_description = "Remember the current shape. Later 'Mask Since Marker' masks everything changed after this moment"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def execute(self, context):
        ob = context.active_object
        if _refuse_limits(self, ob):
            return {'CANCELLED'}
        STATE.marker = common.get_positions(ob.data)
        STATE.marker_obj = obj_key(ob)
        STATE.marker_time = time.time()
        self.report({'INFO'}, "Marker set. Sculpt, then press 'Mask Since Marker'")
        return {'FINISHED'}


class GRAVENARC_OT_mask_since_marker(Operator):
    bl_idname = "gravenarc.mask_since_marker"
    bl_label = "Mask Since Marker"
    bl_description = "Mask everything that changed since 'Set Marker'"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def execute(self, context):
        ob = context.active_object
        if _refuse_limits(self, ob):
            return {'CANCELLED'}
        if STATE.marker is None or STATE.marker_obj != obj_key(ob):
            self.report({'WARNING'}, "No marker on this object: press 'Set Marker' first")
            return {'CANCELLED'}
        changed = _changed(common.get_positions(ob.data), STATE.marker)
        if not changed.any():
            self.report({'WARNING'}, "Nothing changed since the marker")
            return {'CANCELLED'}
        write_mask(context, changed.astype(np.float32))
        self.report({'INFO'}, f"Masked {int(changed.sum()):,} vertices changed since the marker")
        return {'FINISHED'}


class GRAVENARC_OT_remember_mask(Operator):
    bl_idname = "gravenarc.remember_mask"
    bl_label = "Remember Mask"
    bl_description = "Remember the current mask (until Blender is closed) to bring it back later with 'Recall Mask'"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def execute(self, context):
        ob = context.active_object
        if _refuse_limits(self, ob):
            return {'CANCELLED'}
        mask = common.get_mask(ob.data)
        STATE.saved_masks[ob.data.name] = mask.copy()
        n = int((mask > 0.5).sum())
        self.report({'INFO'}, f"Mask remembered ({n:,} masked vertices)" if n else "Remembered an empty mask")
        return {'FINISHED'}


class GRAVENARC_OT_recall_mask(Operator):
    bl_idname = "gravenarc.recall_mask"
    bl_label = "Recall Mask"
    bl_description = "Bring back the mask saved with 'Remember Mask' (replaces the current mask)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def execute(self, context):
        ob = context.active_object
        if _refuse_limits(self, ob):
            return {'CANCELLED'}
        saved = STATE.saved_masks.get(ob.data.name)
        if saved is None:
            self.report({'WARNING'}, "No remembered mask for this object: press 'Remember Mask' first")
            return {'CANCELLED'}
        if len(saved) != len(ob.data.vertices):
            self.report({'WARNING'}, "The mesh topology changed (remesh / subdivide), the remembered mask no longer fits")
            return {'CANCELLED'}
        write_mask(context, saved)
        self.report({'INFO'}, "Mask recalled")
        return {'FINISHED'}


# ---------------------------------------------------------------- геометрия: отделить / удалить

def _face_flags(me, vert_values):
    """Значение на грань = среднее по её вершинам."""
    nf = len(me.polygons)
    starts = np.empty(nf, dtype=np.int32)
    totals = np.empty(nf, dtype=np.int32)
    me.polygons.foreach_get("loop_start", starts)
    me.polygons.foreach_get("loop_total", totals)
    corner_verts = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", corner_verts)
    if nf == 0:
        return np.zeros(0, dtype=np.float32)
    sums = np.add.reduceat(vert_values[corner_verts], starts)
    return sums / np.maximum(totals, 1)


def _delete_faces(me, face_bool):
    idx = np.flatnonzero(face_bool)
    if len(idx) == 0:
        return 0
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in idx], context='FACES')
    bm.to_mesh(me)
    bm.free()
    me.update()
    return len(idx)


class _ObjectModeOp:
    """Выйти в Object Mode, изменить меш, вернуться в Sculpt Mode."""

    def run_in_object_mode(self, context, fn):
        was_sculpt = context.mode == 'SCULPT'
        bpy.ops.object.mode_set(mode='OBJECT')
        try:
            return fn(bpy.context.active_object)
        finally:
            if was_sculpt:
                bpy.ops.object.mode_set(mode='SCULPT')
            STATE.replace_ok = False
            common.tag_redraw(context)


class GRAVENARC_OT_separate_masked(Operator, _ObjectModeOp):
    bl_idname = "gravenarc.separate_masked"
    bl_label = "Separate Masked"
    bl_description = "Move the masked part (faces with mask over 50%) into a new object"
    bl_options = {'REGISTER'}   # шаги undo создают сами переключения режимов

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def execute(self, context):
        if _refuse_limits(self, context.active_object, allow_dyntopo=True):
            return {'CANCELLED'}
        result = {}

        def work(ob):
            me = ob.data
            faces = _face_flags(me, common.get_mask(me)) >= 0.5
            if not faces.any():
                result["msg"] = "Nothing is masked: paint a mask first (Mask brush, B box, Ctrl+LMB lasso)"
                return
            if faces.all():
                result["msg"] = "Everything is masked: nothing would stay in the original object"
                return
            new_me = me.copy()
            new_ob = ob.copy()
            new_ob.data = new_me
            new_ob.name = ob.name + "_Masked"
            for coll in ob.users_collection:
                coll.objects.link(new_ob)
            n = _delete_faces(me, faces)
            _delete_faces(new_me, ~faces)
            a = new_me.attributes.get(MASK_ATTR)
            if a is not None:
                new_me.attributes.remove(a)
            new_ob.select_set(False)
            result["ok"] = f"Separated {n:,} faces into '{new_ob.name}'"

        self.run_in_object_mode(context, work)
        if "ok" not in result:
            self.report({'WARNING'}, result.get("msg", "Nothing done"))
            return {'CANCELLED'}
        self.report({'INFO'}, result["ok"])
        return {'FINISHED'}


class GRAVENARC_OT_delete_masked(Operator, _ObjectModeOp):
    bl_idname = "gravenarc.delete_masked"
    bl_label = "Delete Masked"
    bl_description = "Delete the masked part of the model (faces with mask over 50%)"
    bl_options = {'REGISTER'}   # шаги undo создают сами переключения режимов

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="Delete masked geometry?",
                                                     confirm_text="Delete")

    def execute(self, context):
        if _refuse_limits(self, context.active_object, allow_dyntopo=True):
            return {'CANCELLED'}
        result = {}

        def work(ob):
            me = ob.data
            faces = _face_flags(me, common.get_mask(me)) >= 0.5
            if not faces.any():
                result["msg"] = "Nothing is masked"
                return
            if faces.all():
                result["msg"] = "Everything is masked: that would delete the whole model"
                return
            result["n"] = _delete_faces(me, faces)

        self.run_in_object_mode(context, work)
        if "n" not in result:
            self.report({'WARNING'}, result.get("msg", "Nothing done"))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Deleted {result['n']:,} masked faces")
        return {'FINISHED'}


class GRAVENARC_OT_delete_hidden(Operator, _ObjectModeOp):
    bl_idname = "gravenarc.delete_hidden"
    bl_label = "Delete Hidden"
    bl_description = "Delete the geometry hidden in Sculpt Mode (H / Shift+H / box hide). Alt+H shows everything back"
    bl_options = {'REGISTER'}   # шаги undo создают сами переключения режимов

    @classmethod
    def poll(cls, context):
        return _sculpt_poll(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="Delete hidden geometry?",
                                                     confirm_text="Delete")

    def execute(self, context):
        if _refuse_limits(self, context.active_object, allow_dyntopo=True):
            return {'CANCELLED'}
        result = {}

        def work(ob):
            me = ob.data
            attr = me.attributes.get(".hide_poly")
            if attr is None:
                result["msg"] = "Nothing is hidden"
                return
            hidden = np.zeros(len(me.polygons), dtype=bool)
            attr.data.foreach_get("value", hidden)
            if not hidden.any():
                result["msg"] = "Nothing is hidden"
                return
            if hidden.all():
                result["msg"] = "Everything is hidden: press Alt+H to show it first"
                return
            result["n"] = _delete_faces(me, hidden)

        self.run_in_object_mode(context, work)
        if "n" not in result:
            self.report({'WARNING'}, result.get("msg", "Nothing done"))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Deleted {result['n']:,} hidden faces")
        return {'FINISHED'}


class GRAVENARC_OT_sculpt_reset_settings(Operator):
    bl_idname = "gravenarc.sculpt_reset_settings"
    bl_label = "Reset Settings"
    bl_description = "Put all GravenArc sculpt settings back to their defaults (brush presets are kept)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        p = prefs()
        if p is None:
            return {'CANCELLED'}
        for name in RESET_PROPS:
            p.property_unset(name)
        self.report({'INFO'}, "GravenArc sculpt settings reset")
        return {'FINISHED'}


CLASSES = (
    GRAVENARC_OT_mask_last,
    GRAVENARC_OT_set_marker,
    GRAVENARC_OT_mask_since_marker,
    GRAVENARC_OT_remember_mask,
    GRAVENARC_OT_recall_mask,
    GRAVENARC_OT_separate_masked,
    GRAVENARC_OT_delete_masked,
    GRAVENARC_OT_delete_hidden,
    GRAVENARC_OT_sculpt_reset_settings,
)

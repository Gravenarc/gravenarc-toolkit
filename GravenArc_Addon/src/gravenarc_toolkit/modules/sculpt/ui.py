# SPDX-License-Identifier: GPL-3.0-or-later
# Панели N → GravenArc в Sculpt Mode:
#   «Sculpt: Repeat & Mask»   — Часть 1
#   «Sculpt: Photoshop Brush» — Часть 2 (Alt+ПКМ, прямая линия, сглаживание)
#   «Sculpt: Brush Presets»   — папки кистей

import time

import bpy
from bpy.types import Panel

from . import common, presets
from .common import prefs
from .keymaps import HOTKEYS, hotkey_text
from .state import STATE, obj_key


def _hk(idname):
    t = hotkey_text(idname)
    return f"  ({t})" if t else ""


class _Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GravenArc"

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'


def _limits_box(layout, ob):
    dyntopo, multires = common.sculpt_limits(ob)
    if not (dyntopo or multires):
        return
    box = layout.box()
    box.alert = True
    col = box.column(align=True)
    if dyntopo:
        col.label(text="Dyntopo is on:", icon='ERROR')
        col.label(text="  Mask Last / Marker / Remember don't work")
        col.label(text="  Replay & Line: position approximate")
    if multires:
        col.label(text="Multires modifier:", icon='ERROR')
        col.label(text="  mask tools don't work (mask is on levels)")
        col.label(text="  Replay & Line: position approximate")


class GRAVENARC_PT_sculpt_stroke(_Base, Panel):
    bl_label = "Sculpt: Repeat & Mask"
    bl_idname = "GRAVENARC_PT_sculpt_stroke"

    def draw(self, context):
        layout = self.layout
        p = prefs()
        ob = context.active_object
        _limits_box(layout, ob)

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("gravenarc.replay_stroke", text="Replay Stroke" + _hk("gravenarc.replay_stroke"),
                     icon='FILE_REFRESH')
        if p is not None:
            col = layout.column(align=True)
            col.prop(p, "replace_previous")
            col.prop(p, "repeat_strength", slider=True)
            col.prop(p, "live_strength")
        rec = STATE.last
        if rec is not None and ob is not None and rec.obj_name == ob.name:
            kind = {"line": "line", "stroke": "stroke"}.get(rec.kind, "stroke")
            inv = ", Ctrl (inverted)" if rec.mode == 'INVERT' else ""
            layout.label(text=f"Last {kind}: {len(rec.points)} points{inv}", icon='CHECKMARK')
        else:
            layout.label(text="Make a stroke (LMB), then Shift+R", icon='INFO')

        layout.separator()
        layout.label(text="Mask", icon='MOD_MASK')
        col = layout.column(align=True)
        col.operator("gravenarc.mask_last", text="Mask Last Stroke" + _hk("gravenarc.mask_last"), icon='SELECT_SET')
        row = col.row(align=True)
        row.operator("gravenarc.set_marker", icon='BOOKMARKS')
        row.operator("gravenarc.mask_since_marker", text="Mask Since Marker")
        if STATE.marker is not None and ob is not None and STATE.marker_obj == obj_key(ob):
            col.label(text="Marker set at " + time.strftime("%H:%M:%S", time.localtime(STATE.marker_time)),
                      icon='TIME')
        row = col.row(align=True)
        row.operator("gravenarc.remember_mask", icon='PINNED')
        row.operator("gravenarc.recall_mask", icon='RECOVER_LAST')
        if ob is not None and ob.data.name in STATE.saved_masks:
            col.label(text="A mask is remembered for this object", icon='CHECKMARK')

        layout.label(text="Geometry", icon='MESH_DATA')
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("gravenarc.separate_masked", icon='MOD_EXPLODE')
        row.operator("gravenarc.delete_masked", icon='TRASH')
        col.operator("gravenarc.delete_hidden", icon='HIDE_ON')

        layout.separator()
        if p is not None:
            layout.prop(p, "refresh_reenter")
        layout.operator("gravenarc.sculpt_reset_settings", icon='LOOP_BACK')


class GRAVENARC_PT_sculpt_brushfeel(_Base, Panel):
    bl_label = "Sculpt: Photoshop Brush"
    bl_idname = "GRAVENARC_PT_sculpt_brushfeel"

    def draw(self, context):
        layout = self.layout
        p = prefs()
        brush = context.tool_settings.sculpt.brush

        box = layout.box()
        drag = hotkey_text("gravenarc.brush_drag") or "Alt Right Mouse"
        box.label(text=f"Size & {('Hardness' if not p or p.drag_vertical == 'HARDNESS' else 'Strength')}: "
                       f"hold {drag}, drag", icon='MOUSE_RMB_DRAG')
        if p is not None:
            box.row().prop(p, "drag_vertical", expand=True)
            box.prop(p, "drag_lock_axis")

        box = layout.box()
        line = hotkey_text("gravenarc.straight_line") or "Alt L"
        box.label(text=f"Straight line: mouse over model, {line}", icon='IPO_LINEAR')
        box.label(text="From the end of the last stroke to the cursor")

        box = layout.box()
        if brush is None:
            box.label(text="No active brush")
            return
        smooth = hotkey_text("gravenarc.toggle_smoothing")
        box.prop(brush, "use_smooth_stroke", text="Smoothing" + (f"  ({smooth})" if smooth else ""))
        col = box.column(align=True)
        col.active = brush.use_smooth_stroke
        col.prop(brush, "smooth_stroke_radius", text="Radius", slider=True)
        col.prop(brush, "smooth_stroke_factor", text="Factor", slider=True)
        row = box.row(align=True)
        for pct in (0, 25, 50, 75, 100):
            row.operator("gravenarc.smoothing_preset", text=f"{pct}%").percent = pct


class GRAVENARC_PT_brush_presets(_Base, Panel):
    bl_label = "Sculpt: Brush Presets"
    bl_idname = "GRAVENARC_PT_brush_presets"

    def draw(self, context):
        layout = self.layout
        p = prefs()
        large = p.large_previews if p is not None else False

        row = layout.row(align=True)
        row.operator("gravenarc.preset_folder_add", icon='NEWFOLDER')
        if p is not None:
            row.prop(p, "large_previews", text="", icon='IMAGE_DATA')
        row.operator("gravenarc.preset_open_dir", text="", icon='FILE_FOLDER')

        cur, brush = presets.current_reference(context)
        if brush is not None:
            layout.label(text="Active: " + brush.name, icon='BRUSH_DATA')

        fl = presets.folders()
        if not fl:
            layout.label(text="No folders yet: press New Folder", icon='INFO')
        for i, f in enumerate(fl):
            box = layout.box()
            head = box.row(align=True)
            exp = f.get("expanded", True)
            op = head.operator("gravenarc.preset_folder_toggle", text=f"{f['name']}  ({len(f['brushes'])})",
                               icon='DISCLOSURE_TRI_DOWN' if exp else 'DISCLOSURE_TRI_RIGHT', emboss=False)
            op.folder = i
            add = head.operator("gravenarc.preset_add_current", text="", icon='ADD')
            add.folder = i
            sub = head.row(align=True)
            sub.scale_x = 0.9
            up = sub.operator("gravenarc.preset_folder_move", text="", icon='TRIA_UP')
            up.folder, up.direction = i, -1
            dn = sub.operator("gravenarc.preset_folder_move", text="", icon='TRIA_DOWN')
            dn.folder, dn.direction = i, 1
            sub.operator("gravenarc.preset_folder_rename", text="", icon='SORTALPHA').folder = i
            sub.operator("gravenarc.preset_folder_remove", text="", icon='X').folder = i
            if not exp:
                continue
            if not f["brushes"]:
                box.label(text="Empty: pick a brush, then press +", icon='INFO')
                continue
            if large:
                grid = box.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=False, align=False)
                for j, e in enumerate(f["brushes"]):
                    col = grid.column(align=True)
                    icon = presets.get_icon(e)
                    if icon:
                        col.template_icon(icon_value=icon, scale=4.0)
                    r = col.row(align=True)
                    op = r.operator("gravenarc.preset_activate", text=e["name"], depress=presets.is_active(context, e))
                    op.folder, op.index = i, j
                    rm = r.operator("gravenarc.preset_remove", text="", icon='X')
                    rm.folder, rm.index = i, j
            else:
                col = box.column(align=True)
                for j, e in enumerate(f["brushes"]):
                    r = col.row(align=True)
                    icon = presets.get_icon(e)
                    kw = {"icon_value": icon} if icon else {"icon": 'BRUSH_DATA'}
                    op = r.operator("gravenarc.preset_activate", text=e["name"],
                                    depress=presets.is_active(context, e), **kw)
                    op.folder, op.index = i, j
                    rm = r.operator("gravenarc.preset_remove", text="", icon='X')
                    rm.folder, rm.index = i, j


class GRAVENARC_PT_sculpt_hotkeys(_Base, Panel):
    bl_label = "Sculpt Hotkeys"
    bl_parent_id = "GRAVENARC_PT_sculpt_stroke"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        for idname, _key, _mods, _props, label in HOTKEYS:
            row = col.row()
            row.label(text=label)
            row.label(text=hotkey_text(idname) or "—")
        self.layout.label(text="Change: Preferences › Add-ons › GravenArc", icon='PREFERENCES')


CLASSES = (
    GRAVENARC_PT_sculpt_stroke,
    GRAVENARC_PT_sculpt_hotkeys,
    GRAVENARC_PT_sculpt_brushfeel,
    GRAVENARC_PT_brush_presets,
)

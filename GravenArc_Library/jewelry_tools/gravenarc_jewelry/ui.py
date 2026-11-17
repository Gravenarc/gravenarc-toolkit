# SPDX-License-Identifier: GPL-3.0-or-later
# Панель N › GravenArc и пай-меню (Shift+Alt+J в Object Mode).
import bpy
from bpy.props import EnumProperty, FloatProperty, StringProperty

from . import core


class GVJewelryProps(bpy.types.PropertyGroup):
    metal: EnumProperty(name="Сплав", items=[(k, l, f"{d} г/см³") for k, l, d in core.METALS], default='AG925')
    shrink: FloatProperty(name="Усадка, %", default=1.75, min=0, max=10)
    draft: FloatProperty(name="Уклон, °", default=2.0, min=0, max=15)
    min_wall: FloatProperty(name="Мин. стенка, мм", default=0.5, min=0.1, max=5)
    last_volume: FloatProperty(default=-1.0)
    last_warn: StringProperty(default="")
    last_size: StringProperty(default="")
    last_check: StringProperty(default="")


class _Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GravenArc"


class GV_PT_main(_Base, bpy.types.Panel):
    bl_label = "Ювелирка"
    bl_idname = "GV_PT_main"

    def draw(self, context):
        lay = self.layout
        us = context.scene.unit_settings
        if abs(core.mm_per_bu(context) - 1.0) > 1e-6:
            lay.label(text="Сцена не в мм!", icon='ERROR')
        lay.operator("gravenarc.scene_mm", icon='DRIVER_DISTANCE')
        lay.prop(context.scene.gv_jewelry, "metal")
        lay.operator("gravenarc.mark_metal", icon='MATERIAL')


class GV_PT_gems(_Base, bpy.types.Panel):
    bl_label = "Камни и касты"
    bl_parent_id = "GV_PT_main"

    def draw(self, context):
        lay = self.layout
        col = lay.column(align=True)
        col.operator("gravenarc.gem_add", icon='MESH_ICOSPHERE')
        col.operator("gravenarc.gem_cutters", icon='MOD_BOOLEAN')
        r = col.row(align=True)
        r.operator("gravenarc.gem_heads", text="Крапаны", icon='OUTLINER_OB_POINTCLOUD').kind = 'PRONG'
        r.operator("gravenarc.gem_heads", text="Глухая", icon='MESH_CYLINDER').kind = 'BEZEL'
        ob = context.active_object
        if core.is_gem(ob):
            box = lay.box()
            box.label(text=f"{ob['gv_gem']} {ob['gv_gem_L']:g}×{ob['gv_gem_W']:g} мм · {ob.get('gv_carat', 0):.3f} ct")


class GV_PT_layout(_Base, bpy.types.Panel):
    bl_label = "Раскладка"
    bl_parent_id = "GV_PT_main"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("gravenarc.pave", icon='LIGHTPROBE_VOLUME')
        col.operator("gravenarc.gems_on_curve", icon='CURVE_DATA')
        col.operator("gravenarc.polar_array", icon='PHYSICS')


class GV_PT_ring(_Base, bpy.types.Panel):
    bl_label = "Кольцо"
    bl_parent_id = "GV_PT_main"

    def draw(self, context):
        lay = self.layout
        col = lay.column(align=True)
        col.operator("gravenarc.ring_shank", icon='MESH_TORUS')
        col.operator("gravenarc.ring_measure", icon='DRIVER_DISTANCE')
        col.operator("gravenarc.ring_resize", icon='FULLSCREEN_ENTER')
        col.operator("gravenarc.flow_ring", icon='MOD_CURVE')
        col.operator("gravenarc.engrave_text", icon='FONT_DATA')
        p = context.scene.gv_jewelry
        if p.last_size:
            lay.label(text=p.last_size)


class GV_PT_cast(_Base, bpy.types.Panel):
    bl_label = "Литьё и вес"
    bl_parent_id = "GV_PT_main"

    def draw(self, context):
        lay = self.layout
        p = context.scene.gv_jewelry
        col = lay.column(align=True)
        col.operator("gravenarc.weight", icon='SORTSIZE')
        if p.last_volume >= 0:
            box = lay.box()
            v = p.last_volume
            box.label(text=f"Объём {v:.1f} мм³ · смола {v / 1000:.2f} мл")
            for k, l, d in core.METALS:
                if k == 'RESIN':
                    continue
                row = box.row()
                row.label(text=l)
                row.label(text=f"{v * d / 1000:.2f} г")
                if k == p.metal:
                    row.label(text="", icon='CHECKMARK')
            if p.last_warn:
                box.label(text=p.last_warn[:120], icon='ERROR')
        lay.separator()
        r = lay.row(align=True)
        r.prop(p, "draft")
        r.prop(p, "min_wall")
        r = lay.row(align=True)
        r.operator("gravenarc.casting_check", icon='MOD_MASK')
        r.operator("gravenarc.check_off", text="", icon='HIDE_ON')
        if p.last_check:
            lay.label(text=p.last_check[:120])
        r = lay.row(align=True)
        r.prop(p, "shrink")
        r.operator("gravenarc.shrink", text="Усадка", icon='FULLSCREEN_ENTER')
        col = lay.column(align=True)
        col.operator("gravenarc.make_solid", icon='MOD_BOOLEAN')
        col.operator("gravenarc.report", icon='TEXT')


class GV_MT_pie(bpy.types.Menu):
    bl_label = "GravenArc Ювелирка"
    bl_idname = "GV_MT_pie"

    def draw(self, context):
        pie = self.layout.menu_pie()
        pie.operator("gravenarc.gem_add", icon='MESH_ICOSPHERE')                      # ←
        pie.operator("gravenarc.weight", icon='SORTSIZE')                            # →
        pie.operator("gravenarc.casting_check", icon='MOD_MASK')                     # ↓
        pie.operator("gravenarc.ring_shank", icon='MESH_TORUS')                      # ↑
        pie.operator("gravenarc.pave", icon='LIGHTPROBE_VOLUME')                       # ↖
        pie.operator("gravenarc.gems_on_curve", icon='CURVE_DATA')                   # ↗
        pie.operator("gravenarc.gem_heads", text="Касты", icon='OUTLINER_OB_POINTCLOUD')  # ↙
        pie.operator("gravenarc.engrave_text", icon='FONT_DATA')                     # ↘


CLASSES = (GVJewelryProps, GV_PT_main, GV_PT_gems, GV_PT_layout, GV_PT_ring, GV_PT_cast, GV_MT_pie)


def menu_add(self, context):
    self.layout.separator()
    self.layout.operator("gravenarc.gem_add", icon='MESH_ICOSPHERE')
    self.layout.operator("gravenarc.ring_shank", icon='MESH_TORUS')

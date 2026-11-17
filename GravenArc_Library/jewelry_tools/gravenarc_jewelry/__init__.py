# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc Jewelry Tools — ювелирные инструменты в духе Rhino/RhinoGold для Blender 5.2 LTS.
bl_info = {  # для установки как обычного аддона (.zip) в старом формате
    "name": "GravenArc Jewelry Tools",
    "author": "GravenArc",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "3D Viewport › N › GravenArc; Shift+Alt+J — пай-меню",
    "category": "Mesh",
}

if "bpy" in locals():
    import importlib
    for _m in (core, gems, ring, layout, analysis, ops, ui):  # noqa: F821
        importlib.reload(_m)
else:
    from . import core, gems, ring, layout, analysis, ops, ui

import bpy

_keymaps = []
_registered = []


def _classes():
    return ui.CLASSES[:1] + ops.CLASSES + ui.CLASSES[1:]


def register():
    # В составе GravenArc Toolkit оператор «Сцена в миллиметрах» уже есть — не дублируем.
    for c in _classes():
        if c is ops.GV_OT_scene_mm and hasattr(bpy.types, "GRAVENARC_OT_scene_mm"):
            continue
        bpy.utils.register_class(c)
        _registered.append(c)
    bpy.types.Scene.gv_jewelry = bpy.props.PointerProperty(type=ui.GVJewelryProps)
    bpy.types.VIEW3D_MT_add.append(ui.menu_add)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Object Mode", space_type='EMPTY')
        kmi = km.keymap_items.new("wm.call_menu_pie", 'J', 'PRESS', shift=True, alt=True)
        kmi.properties.name = "GV_MT_pie"
        _keymaps.append((km, kmi))


def unregister():
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    bpy.types.VIEW3D_MT_add.remove(ui.menu_add)
    del bpy.types.Scene.gv_jewelry
    while _registered:
        bpy.utils.unregister_class(_registered.pop())

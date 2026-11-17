# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc Sculpt — повтор мазка, маски, кисть «как в Photoshop», папки пресетов кистей.
# Подключается из главного __init__.py (список _OPTIONAL_MODULES).
# Настройки (GA_SculptPrefs) регистрирует главный модуль — они часть настроек аддона.

import bpy

from . import brushfeel, keymaps, masking, presets, state, stroke, ui

CLASSES = (*stroke.CLASSES, *masking.CLASSES, *brushfeel.CLASSES, *presets.CLASSES, *ui.CLASSES)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    presets.register()
    keymaps.register()
    if state.on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(state.on_load)


def unregister():
    if state.on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(state.on_load)
    keymaps.unregister()
    presets.unregister()
    state.STATE.clear()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

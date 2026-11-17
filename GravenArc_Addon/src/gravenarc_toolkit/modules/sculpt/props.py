# SPDX-License-Identifier: GPL-3.0-or-later
# Настройки скульпт-инструментов GravenArc. Хранятся в настройках аддона
# (Preferences → Add-ons → GravenArc Toolkit), а не в файле сцены.
# Интерфейс — на английском, комментарии — на русском.

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty


class GA_SculptPrefs(bpy.types.PropertyGroup):
    # --- Часть 1: повтор мазка
    replace_previous: BoolProperty(
        name="Replace Previous Stroke",
        description=("On: Replay undoes the last stroke and draws it again with the current brush and "
                     "Repeat Strength. Off: the replayed stroke is added on top"),
        default=False,
    )
    repeat_strength: FloatProperty(
        name="Repeat Strength",
        description=("Strength of the replayed stroke compared to the brush strength. "
                     "1 = same, 2 = about twice as strong, 0 = nothing, negative = inverted (dig in instead of build up)"),
        default=1.0, min=-2.0, max=2.0, step=5, precision=2,
    )
    live_strength: BoolProperty(
        name="Live Strength after Replay",
        description=("After Replay, move the mouse left/right to change the strength with a live preview. "
                     "LMB / Enter = apply, RMB / Esc = back to Repeat Strength"),
        default=True,
    )
    refresh_reenter: BoolProperty(
        name="Refresh by Re-entering Sculpt Mode",
        description=("After mask operations leave and re-enter Sculpt Mode so the viewport is surely up to date. "
                     "Slower; adds Sculpt Mode steps to the undo history"),
        default=False,
    )
    track_changes: BoolProperty(
        name="Track Changed Area",
        description=("Remember vertex positions at the start of each stroke so Mask Last Stroke and "
                     "safe Replace work. Turn off only for very heavy meshes"),
        default=True,
    )

    # --- Часть 2: кисть как в Photoshop
    drag_vertical: EnumProperty(
        name="Vertical Drag",
        description="What dragging up/down with Alt+Right Mouse changes",
        items=[
            ('HARDNESS', "Hardness", "Up = harder edge, down = softer (like Photoshop)"),
            ('STRENGTH', "Strength", "Up = stronger, down = weaker"),
        ],
        default='HARDNESS',
    )
    drag_lock_axis: BoolProperty(
        name="Lock to One Direction",
        description=("Alt+Right Mouse drag changes only size OR the vertical value, whichever way you move first. "
                     "Off = both at once, exactly like Photoshop"),
        default=True,
    )
    drag_speed: FloatProperty(
        name="Drag Speed",
        description="Sensitivity of the Alt+Right Mouse drag",
        default=1.0, min=0.1, max=5.0,
    )
    large_previews: BoolProperty(
        name="Large Previews",
        description="Show big brush previews in the Brush Presets panel",
        default=False,
    )


# Какие настройки сбрасывает кнопка Reset Settings (все, кроме внешнего вида панели пресетов)
RESET_PROPS = ("replace_previous", "repeat_strength", "live_strength", "refresh_reenter", "track_changes",
               "drag_vertical", "drag_lock_axis", "drag_speed")


def draw_prefs(prefs_sculpt, layout):
    """Блок в Preferences → Add-ons → GravenArc Toolkit."""
    p = prefs_sculpt
    box = layout.box()
    box.label(text="Sculpt: Stroke Tools", icon='SCULPTMODE_HLT')
    col = box.column()
    col.prop(p, "replace_previous")
    col.prop(p, "repeat_strength", slider=True)
    col.prop(p, "live_strength")
    col.prop(p, "refresh_reenter")
    col.prop(p, "track_changes")
    box = layout.box()
    box.label(text="Sculpt: Photoshop-style Brush", icon='BRUSH_DATA')
    col = box.column()
    col.prop(p, "drag_vertical")
    col.prop(p, "drag_lock_axis")
    col.prop(p, "drag_speed")
    col.prop(p, "large_previews")
    box.operator("gravenarc.sculpt_reset_settings", icon='LOOP_BACK')

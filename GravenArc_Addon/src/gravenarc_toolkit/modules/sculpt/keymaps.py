# SPDX-License-Identifier: GPL-3.0-or-later
# Горячие клавиши скульпт-модуля. Все — в карте «Sculpt» (работают только в Sculpt Mode над 3D-видом).
# Их можно поменять: Preferences → Keymap → поиск «GravenArc» / Sculpt, или в настройках аддона.
#
# Проверено по карте клавиш Blender 5.2 (blender_default.py, Emulate 3 Button Mouse включён):
#   Shift+R     — в Sculpt Mode свободна; вне 3D-вида и в других режимах остаётся «Repeat Last» (screen.repeat_last)
#   Alt+R       — свободна в Sculpt Mode
#   Alt+ПКМ     — в Sculpt Mode только у кисти с текстурой-трафаретом (Stencil): тогда мы её пропускаем
#   Alt+L       — свободна
#   Shift+S     — в Blender 5.2 уже «вкл/выкл Stabilize Stroke»; мы делаем то же самое + подсказка
# ЛКМ / Ctrl+ЛКМ — не занимаем: наш «наблюдатель» мазка пропускает клик дальше обычной кисти.

import bpy

KEYMAP = "Sculpt"

# (оператор, клавиша, модификаторы, свойства, подпись)
HOTKEYS = (
    ("gravenarc.replay_stroke", 'R', {"shift": True}, {}, "Replay / Replace Last Stroke"),
    ("gravenarc.mask_last", 'R', {"alt": True}, {}, "Mask Last Stroke"),
    ("gravenarc.brush_drag", 'RIGHTMOUSE', {"alt": True}, {}, "Brush Size / Hardness (drag)"),
    ("gravenarc.straight_line", 'L', {"alt": True}, {}, "Straight Line to Cursor"),
    ("gravenarc.toggle_smoothing", 'S', {"shift": True}, {}, "Toggle Stroke Smoothing"),
)

WATCHERS = (
    ("gravenarc.stroke_watch", 'LEFTMOUSE', {}, {"mode": 'NORMAL'}),
    ("gravenarc.stroke_watch", 'LEFTMOUSE', {"ctrl": True}, {"mode": 'INVERT'}),
)

_items = []


def register():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:   # Blender запущен без интерфейса
        return
    km = kc.keymaps.new(name=KEYMAP, space_type='EMPTY')
    for idname, key, mods, props in WATCHERS:
        kmi = km.keymap_items.new(idname, key, 'PRESS', **mods)
        for k, v in props.items():
            setattr(kmi.properties, k, v)
        _items.append((km, kmi))
    for idname, key, mods, props, _label in HOTKEYS:
        kmi = km.keymap_items.new(idname, key, 'PRESS', **mods)
        for k, v in props.items():
            setattr(kmi.properties, k, v)
        _items.append((km, kmi))


def unregister():
    for km, kmi in _items:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _items.clear()


def user_item(idname):
    """Действующая (с учётом правок пользователя) клавиша оператора в Sculpt Mode."""
    kc = bpy.context.window_manager.keyconfigs.user
    km = kc.keymaps.get(KEYMAP) if kc else None
    if km is None:
        return None, None
    for kmi in km.keymap_items:
        if kmi.idname == idname:
            return km, kmi
    return km, None


def hotkey_text(idname):
    _km, kmi = user_item(idname)
    if kmi is None or not kmi.active:
        return ""
    try:
        return kmi.to_string()
    except Exception:
        return ""


def draw_prefs(layout):
    """Список клавиш с возможностью поменять — в Preferences → Add-ons → GravenArc Toolkit."""
    box = layout.box()
    box.label(text="Sculpt Hotkeys (click a key to change it)", icon='KEYINGSET')
    kc = bpy.context.window_manager.keyconfigs.user
    try:
        import rna_keymap_ui
    except ImportError:
        rna_keymap_ui = None
    col = box.column()
    for idname, _key, _mods, _props, label in HOTKEYS:
        km, kmi = user_item(idname)
        if kmi is None or rna_keymap_ui is None:
            col.label(text=f"{label}: not found — re-enable the add-on", icon='ERROR')
            continue
        col.context_pointer_set("keymap", km)
        rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)
    box.label(text="Also in Preferences › Keymap: search 'GravenArc' or open 'Sculpt'", icon='INFO')

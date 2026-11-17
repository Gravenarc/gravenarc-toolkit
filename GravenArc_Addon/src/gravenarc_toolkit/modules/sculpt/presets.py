# SPDX-License-Identifier: GPL-3.0-or-later
# Часть 2: папки пресетов кистей (как Brush Presets в Photoshop).
#
# Папки хранятся в файле brush_presets.json в личной папке расширения
# (bpy.utils.extension_path_user) — она не зависит от сцены и переживает обновление аддона.
# В папке лежат ССЫЛКИ на кисти-ассеты Blender 5: Essentials, свои библиотеки (Preferences →
# File Paths → Asset Libraries, в т.ч. GravenArc) и локальные (из текущего .blend).
# Превью кисти копируется в previews/*.png при добавлении — чтобы показывать его всегда.

import hashlib
import json
import os

import bpy
import numpy as np
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from . import common

FILE_NAME = "brush_presets.json"
DEFAULT_FOLDERS = ("Relief", "Ornament", "Shanks")

_data = None          # {"version": 1, "folders": [{"name", "expanded", "brushes": [...]}]}
_previews = None      # bpy.utils.previews коллекция


# ---------------------------------------------------------------- хранение

def user_dir():
    try:
        return bpy.utils.extension_path_user(common.ROOT_PACKAGE, create=True)
    except (ValueError, RuntimeError):   # запуск не как расширение (разработка)
        path = os.path.join(bpy.utils.user_resource('CONFIG'), "gravenarc_toolkit")
        os.makedirs(path, exist_ok=True)
        return path


def data_path():
    return os.path.join(user_dir(), FILE_NAME)


def preview_dir():
    path = os.path.join(user_dir(), "previews")
    os.makedirs(path, exist_ok=True)
    return path


def load():
    global _data
    path = data_path()
    data = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as ex:
            print("[GravenArc] brush presets: cannot read", path, ex)
            # повреждённый файл не затираем молча — сохраняем копию
            try:
                os.replace(path, path + ".broken")
            except OSError:
                pass
    if not isinstance(data, dict) or not isinstance(data.get("folders"), list):
        data = {"version": 1, "folders": [{"name": n, "expanded": True, "brushes": []} for n in DEFAULT_FOLDERS]}
    for f in data["folders"]:
        f.setdefault("expanded", True)
        f.setdefault("brushes", [])
    _data = data
    return data


def data():
    return _data if _data is not None else load()


def save():
    path = data_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data(), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def folders():
    return data()["folders"]


def _folder(index):
    fl = folders()
    return fl[index] if 0 <= index < len(fl) else None


# ---------------------------------------------------------------- превью

def get_icon(entry):
    """icon_id превью кисти (или 0)."""
    global _previews
    name = entry.get("icon") or ""
    if not name:
        return 0
    if _previews is None:
        import bpy.utils.previews
        _previews = bpy.utils.previews.new()
    if name in _previews:
        return _previews[name].icon_id
    path = os.path.join(preview_dir(), name)
    if not os.path.exists(path):
        return 0
    return _previews.load(name, path, 'IMAGE').icon_id


def _save_preview(brush, key):
    """Сохранить превью кисти в PNG; вернуть имя файла или ''."""
    try:
        pv = brush.preview
        if pv is None:
            pv = brush.preview_ensure()
        w, h = pv.image_size
        if w == 0 or h == 0:
            return ""
        px = np.empty(w * h * 4, dtype=np.float32)
        pv.image_pixels_float.foreach_get(px)
        if px.max(initial=0.0) <= 0.0:
            return ""
        name = key + ".png"
        img = bpy.data.images.new("GA_brush_preview_tmp", w, h, alpha=True)
        try:
            img.pixels.foreach_set(px)
            img.filepath_raw = os.path.join(preview_dir(), name)
            img.file_format = 'PNG'
            img.save()
        finally:
            bpy.data.images.remove(img)
        if _previews is not None and name in _previews:
            del _previews[name]   # перечитать новую картинку
        return name
    except Exception as ex:
        print("[GravenArc] brush preview:", ex)
        return ""


def entry_key(e):
    return hashlib.sha1(f"{e['type']}|{e.get('lib', '')}|{e['rel']}".encode("utf-8")).hexdigest()[:16]


def current_reference(context):
    """Ссылка на активную кисть Sculpt Mode как запись пресета (или None)."""
    paint = context.tool_settings.sculpt
    brush = paint.brush
    ref = paint.brush_asset_reference
    if brush is None or ref is None or not ref.relative_asset_identifier:
        return None, brush
    e = {
        "name": brush.name,
        "type": ref.asset_library_type,
        "lib": ref.asset_library_identifier,
        "rel": ref.relative_asset_identifier,
    }
    return e, brush


def is_active(context, e):
    ref = context.tool_settings.sculpt.brush_asset_reference
    return (ref is not None and ref.relative_asset_identifier == e["rel"]
            and ref.asset_library_type == e["type"] and ref.asset_library_identifier == e.get("lib", ""))


def library_label(e):
    if e["type"] == 'ESSENTIALS':
        return "Essentials"
    if e["type"] == 'LOCAL':
        return "this .blend file"
    return e.get("lib") or "custom library"


# ---------------------------------------------------------------- операторы

class GRAVENARC_OT_preset_folder_add(Operator):
    bl_idname = "gravenarc.preset_folder_add"
    bl_label = "New Folder"
    bl_description = "Create a new brush preset folder"
    bl_options = {'REGISTER', 'INTERNAL'}

    name: StringProperty(name="Name", default="New Folder")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, title="New Brush Folder")

    def execute(self, context):
        name = self.name.strip() or "New Folder"
        folders().append({"name": name, "expanded": True, "brushes": []})
        save()
        return {'FINISHED'}


class GRAVENARC_OT_preset_folder_rename(Operator):
    bl_idname = "gravenarc.preset_folder_rename"
    bl_label = "Rename Folder"
    bl_description = "Rename this folder"
    bl_options = {'REGISTER', 'INTERNAL'}

    folder: IntProperty(options={'HIDDEN'})
    name: StringProperty(name="Name")

    def invoke(self, context, event):
        f = _folder(self.folder)
        if f is None:
            return {'CANCELLED'}
        self.name = f["name"]
        return context.window_manager.invoke_props_dialog(self, title="Rename Folder")

    def execute(self, context):
        f = _folder(self.folder)
        if f is None or not self.name.strip():
            return {'CANCELLED'}
        f["name"] = self.name.strip()
        save()
        return {'FINISHED'}


class GRAVENARC_OT_preset_folder_remove(Operator):
    bl_idname = "gravenarc.preset_folder_remove"
    bl_label = "Delete Folder"
    bl_description = "Delete this folder (the brushes themselves stay in their libraries)"
    bl_options = {'REGISTER', 'INTERNAL'}

    folder: IntProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        f = _folder(self.folder)
        if f is None:
            return {'CANCELLED'}
        return context.window_manager.invoke_confirm(self, event, title=f"Delete folder '{f['name']}'?",
                                                     confirm_text="Delete")

    def execute(self, context):
        if _folder(self.folder) is None:
            return {'CANCELLED'}
        folders().pop(self.folder)
        save()
        return {'FINISHED'}


class GRAVENARC_OT_preset_folder_move(Operator):
    bl_idname = "gravenarc.preset_folder_move"
    bl_label = "Move Folder"
    bl_description = "Move this folder up or down"
    bl_options = {'REGISTER', 'INTERNAL'}

    folder: IntProperty(options={'HIDDEN'})
    direction: IntProperty(default=-1, options={'HIDDEN'})

    def execute(self, context):
        fl = folders()
        j = self.folder + self.direction
        if _folder(self.folder) is None or not 0 <= j < len(fl):
            return {'CANCELLED'}
        fl[self.folder], fl[j] = fl[j], fl[self.folder]
        save()
        return {'FINISHED'}


class GRAVENARC_OT_preset_folder_toggle(Operator):
    bl_idname = "gravenarc.preset_folder_toggle"
    bl_label = "Open / Close Folder"
    bl_description = "Show or hide the brushes in this folder"
    bl_options = {'INTERNAL'}

    folder: IntProperty(options={'HIDDEN'})

    def execute(self, context):
        f = _folder(self.folder)
        if f is None:
            return {'CANCELLED'}
        f["expanded"] = not f.get("expanded", True)
        save()
        return {'FINISHED'}


class GRAVENARC_OT_preset_add_current(Operator):
    bl_idname = "gravenarc.preset_add_current"
    bl_label = "Add Current Brush"
    bl_description = "Add the active sculpt brush to this folder"
    bl_options = {'REGISTER', 'INTERNAL'}

    folder: IntProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def execute(self, context):
        f = _folder(self.folder)
        if f is None:
            self.report({'WARNING'}, "Create a folder first")
            return {'CANCELLED'}
        e, brush = current_reference(context)
        if e is None:
            self.report({'WARNING'}, "This brush is not an asset yet: Brush menu › Save as Asset, then add it")
            return {'CANCELLED'}
        key = entry_key(e)
        for old in f["brushes"]:
            if entry_key(old) == key:
                self.report({'INFO'}, f"'{e['name']}' is already in '{f['name']}'")
                return {'CANCELLED'}
        e["icon"] = _save_preview(brush, key)
        f["brushes"].append(e)
        f["expanded"] = True
        save()
        if e["type"] == 'LOCAL':
            self.report({'WARNING'}, f"Added '{e['name']}'. It is a local brush: it works only in this .blend file")
        else:
            self.report({'INFO'}, f"Added '{e['name']}' to '{f['name']}'")
        return {'FINISHED'}


class GRAVENARC_OT_preset_activate(Operator):
    bl_idname = "gravenarc.preset_activate"
    bl_label = "Use Brush"
    bl_description = "Make this brush active"
    bl_options = {'REGISTER', 'INTERNAL'}

    folder: IntProperty(options={'HIDDEN'})
    index: IntProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, context, props):
        f = _folder(props.folder)
        if f is None or not 0 <= props.index < len(f["brushes"]):
            return "Make this brush active"
        e = f["brushes"][props.index]
        return f"Use brush '{e['name']}' (from {library_label(e)})"

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def execute(self, context):
        f = _folder(self.folder)
        if f is None or not 0 <= self.index < len(f["brushes"]):
            return {'CANCELLED'}
        e = f["brushes"][self.index]
        try:
            bpy.ops.brush.asset_activate(asset_library_type=e["type"], asset_library_identifier=e.get("lib", ""),
                                         relative_asset_identifier=e["rel"])
        except RuntimeError:
            where = library_label(e)
            hint = " (open the .blend file it was added from)" if e["type"] == 'LOCAL' else \
                " (check Preferences › File Paths › Asset Libraries)" if e["type"] == 'CUSTOM' else ""
            self.report({'WARNING'}, f"Brush '{e['name']}' not found in {where}{hint}")
            return {'CANCELLED'}
        return {'FINISHED'}


class GRAVENARC_OT_preset_remove(Operator):
    bl_idname = "gravenarc.preset_remove"
    bl_label = "Remove from Folder"
    bl_description = "Remove this brush from the folder (the brush itself is not deleted)"
    bl_options = {'REGISTER', 'INTERNAL'}

    folder: IntProperty(options={'HIDDEN'})
    index: IntProperty(options={'HIDDEN'})

    def execute(self, context):
        f = _folder(self.folder)
        if f is None or not 0 <= self.index < len(f["brushes"]):
            return {'CANCELLED'}
        f["brushes"].pop(self.index)
        save()
        return {'FINISHED'}


class GRAVENARC_OT_preset_open_dir(Operator):
    bl_idname = "gravenarc.preset_open_dir"
    bl_label = "Open Presets Folder"
    bl_description = "Open the folder where brush folders are stored (brush_presets.json) — handy for a backup"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        save()
        bpy.ops.wm.path_open(filepath=user_dir())
        return {'FINISHED'}


CLASSES = (
    GRAVENARC_OT_preset_folder_add,
    GRAVENARC_OT_preset_folder_rename,
    GRAVENARC_OT_preset_folder_remove,
    GRAVENARC_OT_preset_folder_move,
    GRAVENARC_OT_preset_folder_toggle,
    GRAVENARC_OT_preset_add_current,
    GRAVENARC_OT_preset_activate,
    GRAVENARC_OT_preset_remove,
    GRAVENARC_OT_preset_open_dir,
)


def register():
    load()


def unregister():
    global _previews, _data
    if _previews is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_previews)
        _previews = None
    _data = None

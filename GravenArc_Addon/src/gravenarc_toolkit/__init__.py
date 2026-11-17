# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc Toolkit — расширение для Blender 5.2 LTS+.
#
# При включении регистрирует библиотеку ассетов «GravenArc» (кисти, альфы,
# шаблоны) на папку library/ внутри расширения; при выключении — убирает её.
# Панель: 3D Viewport → N → вкладка GravenArc.
#
# Дополнительные модули (например, ювелирные инструменты) кладутся
# подпакетами в modules/<имя>/ с функциями register()/unregister() —
# они подключаются автоматически, см. _OPTIONAL_MODULES.

import importlib
import os

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel

from .modules.sculpt import props as sculpt_props

LIBRARY_NAME = "GravenArc"
LIBRARY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library")

# Подпакеты, которые подключаются, только если они есть в сборке.
_OPTIONAL_MODULES = ("sculpt", "jewelry")
_loaded_modules = []


# ---------------------------------------------------------------- библиотека

def _norm(path):
    return os.path.normcase(os.path.normpath(bpy.path.abspath(path))) if path else ""


def find_library():
    """Наша библиотека в Preferences (по папке, а не только по имени)."""
    target = _norm(LIBRARY_DIR)
    for lib in bpy.context.preferences.filepaths.asset_libraries:
        if _norm(lib.path) == target:
            return lib
    return None


def _addon_prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def ensure_library():
    libs = bpy.context.preferences.filepaths.asset_libraries
    lib = find_library()
    if lib is None:
        # Старая запись «GravenArc» с другой папкой (прошлая установка) — заменяем.
        for old in list(libs):
            if old.name == LIBRARY_NAME:
                libs.remove(old)
        lib = libs.new(name=LIBRARY_NAME, directory=LIBRARY_DIR)
    lib.name = LIBRARY_NAME
    lib.enabled = True
    prefs = _addon_prefs()
    _set_import_method(lib, prefs.import_method if prefs else 'APPEND')
    return lib


def _set_import_method(lib, method):
    # Набор вариантов зависит от версии Blender (в 5.2: LINK / APPEND / PACK).
    for m in (method, 'APPEND'):
        try:
            lib.import_method = m
            return
        except TypeError:
            continue


def remove_library():
    libs = bpy.context.preferences.filepaths.asset_libraries
    lib = find_library()
    if lib is not None:
        libs.remove(lib)


# ---------------------------------------------------------------- настройки

def _update_import_method(self, context):
    lib = find_library()
    if lib is not None:
        _set_import_method(lib, self.import_method)


class GRAVENARC_AP_prefs(AddonPreferences):
    bl_idname = __package__

    import_method: bpy.props.EnumProperty(
        name="Импорт ассетов",
        description="Как ассеты GravenArc попадают в ваш файл при перетаскивании",
        items=[
            ('APPEND', "Append", "Копия ассета в ваш файл — можно редактировать (рекомендуется)"),
            ('LINK', "Link", "Ссылка на файл библиотеки (не редактируется, файл должен оставаться на месте)"),
            ('PACK', "Pack", "Ссылка, упакованная внутрь вашего .blend"),
        ],
        default='APPEND',
        update=_update_import_method,
    )

    # Настройки скульпт-инструментов (повтор мазка, кисть «как в Photoshop»)
    sculpt: PointerProperty(type=sculpt_props.GA_SculptPrefs)

    def draw(self, context):
        layout = self.layout
        lib = find_library()
        col = layout.column()
        col.label(text="Библиотека ассетов: " + ("подключена" if lib else "не подключена"),
                  icon='CHECKMARK' if lib else 'ERROR')
        col.label(text=LIBRARY_DIR, icon='FILE_FOLDER')
        col.prop(self, "import_method")
        layout.separator()
        sculpt_props.draw_prefs(self.sculpt, layout)
        try:
            from .modules.sculpt import keymaps as sculpt_keymaps
            sculpt_keymaps.draw_prefs(layout)
        except Exception as ex:   # модуль не подключился — покажем причину, а не пустоту
            layout.label(text=f"Sculpt hotkeys unavailable: {ex}", icon='ERROR')


# ---------------------------------------------------------------- операторы

class GRAVENARC_OT_reregister_library(Operator):
    bl_idname = "gravenarc.reregister_library"
    bl_label = "Подключить библиотеку заново"
    bl_description = "Заново добавить библиотеку ассетов GravenArc в Preferences → File Paths"
    bl_options = {'REGISTER'}

    def execute(self, context):
        ensure_library()
        _refresh_asset_browsers(context)
        self.report({'INFO'}, "Библиотека GravenArc подключена")
        return {'FINISHED'}


class GRAVENARC_OT_scene_mm(Operator):
    bl_idname = "gravenarc.scene_mm"
    bl_label = "Сцена в миллиметрах"
    bl_description = ("Metric, Unit Scale 0.001, Length = Millimeters, Mass = Grams: 1 единица Blender = 1 мм "
                      "(так сделаны все кисти и шаблоны GravenArc)")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        us = context.scene.unit_settings
        us.system = 'METRIC'
        us.scale_length = 0.001
        us.length_unit = 'MILLIMETERS'
        us.mass_unit = 'GRAMS'   # ювелирный вес — в граммах
        for area in context.screen.areas if context.screen else ():
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.clip_start = 0.01   # 0,01 мм
                        space.clip_end = 10000.0  # 10 м
        self.report({'INFO'}, "Сцена: 1 единица = 1 мм")
        return {'FINISHED'}


def _refresh_asset_browsers(context):
    wm = context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == 'FILE_BROWSER' and area.ui_type == 'ASSETS':
                area.tag_redraw()
    try:
        bpy.ops.asset.library_refresh()
    except Exception:
        pass


class GRAVENARC_OT_open_assets(Operator):
    bl_idname = "gravenarc.open_assets"
    bl_label = "Открыть Asset Browser"
    bl_description = ("Показать библиотеку GravenArc в Asset Browser. Если его нет на экране — "
                      "откроется отдельное окно")
    bl_options = {'REGISTER'}

    catalog: StringProperty(name="Каталог", default="", options={'SKIP_SAVE'},
                            description="UUID каталога, который открыть (пусто — вся библиотека)")

    def execute(self, context):
        ensure_library()
        area = None
        # Уже открытый Asset Browser — в любом окне Blender
        for win in context.window_manager.windows:
            for a in win.screen.areas:
                if a.type == 'FILE_BROWSER' and a.ui_type == 'ASSETS':
                    area = a
                    break
            if area:
                break
        if area is None:
            # Новое окно-копия текущей области, переключаем его в Asset Browser.
            before = set(context.window_manager.windows[:])
            with context.temp_override(area=context.area):
                bpy.ops.wm.window_new()
            new = [w for w in context.window_manager.windows if w not in before]
            if new:
                area = new[0].screen.areas[0]
                area.ui_type = 'ASSETS'
        if area is None:
            self.report({'WARNING'}, "Откройте Asset Browser вручную (Shift+F1) и выберите GravenArc")
            return {'CANCELLED'}
        _point_browser(area, self.catalog)
        return {'FINISHED'}


def _set_params(area, catalog):
    """True, если библиотека выставлена. У только что созданного окна params появляются
    не сразу (после первой перерисовки), поэтому вызывается ещё и из таймера."""
    try:
        for space in area.spaces:
            if space.type != 'FILE_BROWSER':
                continue
            params = space.params
            if params is None or not hasattr(params, "asset_library_reference"):
                return False
            if params.asset_library_reference != LIBRARY_NAME:
                params.asset_library_reference = LIBRARY_NAME
            if catalog and hasattr(params, "catalog_id") and params.catalog_id != catalog:
                params.catalog_id = catalog
            area.tag_redraw()
            return params.asset_library_reference == LIBRARY_NAME
    except (ReferenceError, TypeError, AttributeError):
        return True   # окно закрыли или API другое — больше не пытаемся
    return False


def _point_browser(area, catalog):
    if _set_params(area, catalog):
        return
    tries = [0]

    def retry():
        tries[0] += 1
        if _set_params(area, catalog) or tries[0] > 30:
            return None
        return 0.1
    bpy.app.timers.register(retry, first_interval=0.1)


CATALOG_TEMPLATES = "72a06f5c-5671-5f2c-bcd0-a2ad68fa7eab"   # GravenArc/Templates
CATALOG_JEWELRY = "1130a6fb-39f1-5d8c-a099-d9b63812af23"     # GravenArc/Jewelry


class GRAVENARC_OT_brushes(Operator):
    bl_idname = "gravenarc.brushes"
    bl_label = "Кисти"
    bl_description = ("Перейти в Sculpt Mode для выделенной модели и показать кисти GravenArc (GA …). "
                      "Потом их всегда можно открыть клавишами Shift+Space")
    bl_options = {'REGISTER'}

    def execute(self, context):
        ensure_library()
        ob = context.active_object
        if ob is None or ob.type != 'MESH':
            self.report({'WARNING'}, "Сначала выделите модель (кликните по ней), потом нажмите «Кисти»")
            return {'CANCELLED'}
        if context.mode != 'SCULPT':
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='SCULPT')
        area = context.area if context.area and context.area.type == 'VIEW_3D' else None
        region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
        try:
            if region is not None:
                with context.temp_override(area=area, region=region):
                    bpy.ops.wm.call_asset_shelf_popover('INVOKE_DEFAULT', name="VIEW3D_AST_brush_sculpt")
        except Exception:
            pass   # полка кистей всё равно внизу вида и по Shift+Space
        self.report({'INFO'}, "Кисти: слева в списке выберите GravenArc › Brushes (или Shift+Space)")
        return {'FINISHED'}


class GRAVENARC_OT_open_doc(Operator):
    bl_idname = "gravenarc.open_doc"
    bl_label = "Открыть инструкцию"
    bl_description = "Открыть инструкцию во внешней программе (Open the guide in an external app)"
    bl_options = {'REGISTER'}

    path: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        full = os.path.join(LIBRARY_DIR, self.path)
        if not os.path.exists(full):
            self.report({'ERROR'}, "Файл не найден: " + full)
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=full)
        return {'FINISHED'}


# ---------------------------------------------------------------- панель

DOCS = (  # (подпись, русская инструкция, английская инструкция, иконка)
    ("Кисти", "brushes/README_ru.md", "brushes/README_en.md", 'BRUSH_DATA'),
    ("Альфы", "alphas/README.md", "alphas/README_en.md", 'TEXTURE'),
    ("Шаблоны", "templates/README.md", "templates/README_en.md", 'MESH_TORUS'),
    ("Ювелирка", "jewelry/README_ru.md", "jewelry/README_en.md", 'MESH_ICOSPHERE'),
    ("Скульпт", "sculpt_tools/README_ru.md", "sculpt_tools/README_en.md", 'SCULPTMODE_HLT'),
)


class GRAVENARC_PT_main(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GravenArc"
    bl_label = "GravenArc Toolkit"

    def draw(self, context):
        layout = self.layout
        lib = find_library()

        box = layout.box()
        if lib is not None and lib.enabled:
            box.label(text="Библиотека подключена", icon='CHECKMARK')
        else:
            box.label(text="Библиотека не подключена", icon='ERROR')
        box.operator("gravenarc.reregister_library", icon='FILE_REFRESH')

        if context.mode not in {'OBJECT', 'SCULPT'}:
            warn = layout.box()
            warn.alert = True
            warn.label(text="Сейчас режим редактирования", icon='ERROR')
            warn.label(text="Tab — вернуться в Object Mode")

        col = layout.column(align=True)
        col.scale_y = 1.3
        op = col.operator("gravenarc.open_assets", text="Шаблоны", icon='ASSET_MANAGER')
        op.catalog = CATALOG_TEMPLATES
        op = col.operator("gravenarc.open_assets", text="Камни и касты (ассеты)", icon='MESH_ICOSPHERE')
        op.catalog = CATALOG_JEWELRY
        col.operator("gravenarc.brushes", icon='BRUSH_DATA')
        col.separator()
        col.operator("gravenarc.scene_mm", icon='DRIVER_DISTANCE')

        us = context.scene.unit_settings
        mm_ok = us.system == 'METRIC' and abs(us.scale_length - 0.001) < 1e-9
        layout.label(text="1 BU = 1 мм" if mm_ok else "Сцена не в мм — нажмите кнопку выше",
                     icon='CHECKMARK' if mm_ok else 'INFO')


class GRAVENARC_PT_help(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GravenArc"
    bl_label = "Подсказки"
    bl_parent_id = "GRAVENARC_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Кисти и альфы: Sculpt Mode →")
        col.label(text="    полка ассетов внизу / Shift+Space")
        col.label(text="Шаблоны: Asset Browser (Shift+F1)")
        col.label(text="    → перетащить во вьюпорт")
        col.label(text="Ювелирка: панель «Ювелирка» ниже,")
        col.label(text="    пай-меню Shift+Alt+J")
        col.label(text="Повтор мазка, маски, кисть как в PS:")
        col.label(text="    Sculpt Mode → панели «Sculpt: …»")
        layout.separator()
        col = layout.column(align=True)
        for label, path_ru, path_en, icon in DOCS:
            if not os.path.exists(os.path.join(LIBRARY_DIR, path_ru)):
                continue
            row = col.row(align=True)
            row.operator("gravenarc.open_doc", text="Инструкция: " + label, icon=icon).path = path_ru
            if os.path.exists(os.path.join(LIBRARY_DIR, path_en)):
                row.operator("gravenarc.open_doc", text="EN").path = path_en


# ---------------------------------------------------------------- регистрация

classes = (
    GRAVENARC_AP_prefs,
    GRAVENARC_OT_reregister_library,
    GRAVENARC_OT_scene_mm,
    GRAVENARC_OT_open_assets,
    GRAVENARC_OT_brushes,
    GRAVENARC_OT_open_doc,
    GRAVENARC_PT_main,
    GRAVENARC_PT_help,
)


def _register_optional_modules():
    for name in _OPTIONAL_MODULES:
        if not os.path.isdir(os.path.join(os.path.dirname(__file__), "modules", name)):
            continue
        try:
            mod = importlib.import_module(f"{__package__}.modules.{name}")
            mod.register()
            _loaded_modules.append(mod)
        except Exception as ex:  # модуль не должен ломать основное расширение
            print(f"[GravenArc] модуль {name} не подключён: {ex}")


def _unregister_optional_modules():
    while _loaded_modules:
        mod = _loaded_modules.pop()
        try:
            mod.unregister()
        except Exception as ex:
            print(f"[GravenArc] ошибка выключения модуля {mod.__name__}: {ex}")


def register():
    bpy.utils.register_class(sculpt_props.GA_SculptPrefs)   # до настроек аддона — они на неё ссылаются
    for cls in classes:
        bpy.utils.register_class(cls)
    ensure_library()
    _register_optional_modules()


def unregister():
    _unregister_optional_modules()
    remove_library()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(sculpt_props.GA_SculptPrefs)

# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc Blender Toolkit — альфы -> кисти-ассеты (Blender 5.2 LTS)
"""
Собирает alphas/GravenArc_Alphas.blend: по одной скульпт-кисти на каждую
карту высот из alphas/maps/*.png (+ одноимённый .json от svg2alpha.py).
Кисти помечаются как ассеты и раскладываются по каталогам GravenArc/Alphas/...

Запуск без интерфейса:
    blender -b --factory-startup --python alphas/tools/make_alpha_brushes.py
Или в Blender: Scripting -> Open -> этот файл -> Alt+P (Run Script).

Сцена должна быть в мм так, что 1 Blender unit = 1 мм
(Scene Properties -> Units: Unit Scale 0.001, Length = Millimeters).
Тогда размер кисти в сцене = реальный размер орнамента в мм.
"""
import json
import sys
import uuid
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent if "__file__" in globals() else None
if HERE is None or not (HERE.parent / "maps").is_dir():
    # запуск из текстового редактора Blender: ищем рядом с открытым .py
    txt = bpy.context.space_data.text if bpy.context.space_data else None
    HERE = Path(bpy.path.abspath(txt.filepath)).parent if txt else Path.cwd()

ALPHAS = HERE.parent
LIBRARY = ALPHAS.parent                    # корень GravenArc_Library
MAPS = ALPHAS / "maps"
OUT_BLEND = ALPHAS / "GravenArc_Alphas.blend"
CATS = LIBRARY / "blender_assets.cats.txt"
PREFIX = "GA Alpha · "


def catalog_uuid(path: str) -> str:
    # детерминированный UUID: одинаковый при каждой пересборке
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "gravenarc-toolkit:" + path))


def ensure_catalogs(paths):
    """Дописывает недостающие каталоги (и их родителей), ничего не удаляя."""
    full = set()
    for p in paths:
        parts = p.split("/")
        full.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    text = CATS.read_text(encoding="utf-8") if CATS.exists() else ""
    have = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and ":" in line \
                and not line.startswith("VERSION"):
            u, path, *_ = line.split(":")
            have[path] = u
    add = []
    for p in sorted(full):
        if p not in have:
            have[p] = catalog_uuid(p)
            add.append(f"{have[p]}:{p}:{p.replace('/', '-')}")
    if add:
        if not text:
            text = ("# This is an Asset Catalog Definition file for Blender.\n"
                    "#\n# Empty lines and lines starting with `#` will be ignored.\n"
                    "# The first non-ignored line should be the version indicator.\n"
                    "# Other lines are of the format \"UUID:catalog/path/for/assets:simple catalog name\"\n\n"
                    "VERSION 1\n\n")
        elif not text.endswith("\n"):
            text += "\n"
        CATS.write_text(text + "\n".join(add) + "\n", encoding="utf-8")
    return have


def set_preview(brush, png: Path):
    if not png.exists():
        return
    img = bpy.data.images.load(str(png), check_existing=False)
    w, h = img.size
    px = list(img.pixels)
    img_prev = brush.preview_ensure()
    img_prev.image_size = (w, h)
    img_prev.image_pixels_float = px
    bpy.data.images.remove(img)


def make_brush(meta: dict, png: Path, cat_uuid: str):
    name = PREFIX + meta.get("title", meta["name"])
    old = bpy.data.brushes.get(name)
    if old:
        bpy.data.brushes.remove(old)

    img = bpy.data.images.load(str(png), check_existing=True)
    img.name = "GA_" + meta["name"]
    img.colorspace_settings.name = "Non-Color"   # высота, не цвет
    img.pack()

    tex = bpy.data.textures.get("GA_" + meta["name"]) or \
        bpy.data.textures.new("GA_" + meta["name"], type="IMAGE")
    tex.image = img
    tiled = meta.get("tile", "none") != "none"
    tex.extension = "REPEAT" if tiled else "CLIP"
    tex.use_interpolation = True
    tex.use_fake_user = True

    b = bpy.data.brushes.new(name, mode="SCULPT")
    b.sculpt_brush_type = "DRAW"
    b.texture = tex
    ts = b.texture_slot
    ts.map_mode = "AREA_PLANE"            # штамп ложится по плоскости поверхности
    b.curve_distance_falloff_preset = "CONSTANT"   # спад даёт сама альфа
    b.use_locked_size = "SCENE"           # размер в мм сцены, а не в пикселях
    b.unprojected_size = float(max(meta["size_mm"]))
    b.strength = 0.5
    b.use_original_normal = True
    b.sculpt_plane = "AREA"
    if tiled:
        # бордюр: ведём линией, текстура поворачивается по ходу штриха
        b.stroke_method = "SPACE"
        b.use_scene_spacing = "SCENE"
        b.spacing = 100                    # шаг = ширине тайла
        ts.use_rake = True
    else:
        # штамп: Drag Dot — тянем, крутим, отпускаем
        b.stroke_method = "DRAG_DOT"

    b["gravenarc"] = json.dumps(meta, ensure_ascii=False)  # метаданные в кисти
    b.asset_mark()
    ad = b.asset_data
    ad.catalog_id = cat_uuid
    ad.author = "GravenArc"
    ad.license = "GPL-3.0-or-later"
    ad.description = (f"{meta['size_mm'][0]}×{meta['size_mm'][1]} мм, рельеф "
                      f"{meta['depth_mm']} мм, уклон {meta['draft_deg']}°. "
                      f"Источник: {meta['source']}")
    for tag in ("GravenArc", "alpha", "jewelry", meta.get("profile", "")):
        if tag:
            ad.tags.new(tag, skip_if_exists=True)
    set_preview(b, png.with_name(meta["name"] + "_preview.png"))
    return b


def enter_sculpt_mode():
    """Режим Area Plane доступен в RNA только из Sculpt Mode —
    временно входим в него на вспомогательном объекте."""
    ob = bpy.context.active_object
    if ob and ob.mode == "SCULPT":
        return None
    me = bpy.data.meshes.new("_ga_tmp")
    tmp = bpy.data.objects.new("_ga_tmp", me)
    bpy.context.scene.collection.objects.link(tmp)
    prev_mode = ob.mode if ob else "OBJECT"
    if ob and ob.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = tmp
    bpy.ops.object.mode_set(mode="SCULPT")
    return tmp, ob, prev_mode


def leave_sculpt_mode(state):
    if not state:
        return
    tmp, ob, prev_mode = state
    bpy.ops.object.mode_set(mode="OBJECT")
    me = tmp.data
    bpy.data.objects.remove(tmp)
    bpy.data.meshes.remove(me)
    if ob:
        bpy.context.view_layer.objects.active = ob
        if prev_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=prev_mode)


def main():
    if bpy.app.background:
        bpy.ops.wm.read_factory_settings(use_empty=True)   # чистый файл
    metas = []
    for js in sorted(MAPS.glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        png = MAPS / f"{meta['name']}.png"
        if png.exists():
            metas.append((meta, png))
    if not metas:
        print("Нет карт в", MAPS, "— сначала запустите svg2alpha.py")
        return 1
    cats = ensure_catalogs(m.get("catalog", "GravenArc/Alphas") for m, _ in metas)
    state = enter_sculpt_mode()
    try:
        for meta, png in metas:
            b = make_brush(meta, png, cats[meta.get("catalog", "GravenArc/Alphas")])
            print("кисть:", b.name)
    finally:
        leave_sculpt_mode(state)
    # мм-сцена, чтобы при открытии файла всё было в правильных единицах
    us = bpy.context.scene.unit_settings
    us.system = "METRIC"
    us.scale_length = 0.001
    us.length_unit = "MILLIMETERS"
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT_BLEND), compress=True)
    print("сохранено:", OUT_BLEND)
    return 0


if __name__ == "__main__":
    rc = main()
    if bpy.app.background:
        sys.exit(rc)

# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc Blender Toolkit: генератор библиотеки кистей в стиле ZBrush.
# Blender 5.2 LTS.
#
# Запуск (из терминала):
#   blender -b --factory-startup --python make_brushes.py -- [КОРЕНЬ_БИБЛИОТЕКИ]
# По умолчанию корень = папка над tools/ (то есть GravenArc_Library/).
# Результат:
#   <корень>/brushes/GravenArc_Brushes.blend   (кисти-ассеты)
#   <корень>/blender_assets.cats.txt            (каталоги; дописывает, не стирает чужие)
#
# Единицы: в файле сцена настроена как 1 BU = 1 мм (Unit Scale 0.001, Length = Millimeters).
# Кисти с "мм" в имени работают в размере сцены (Radius Unit = Scene), их диаметр задан в мм.

import bpy
import os
import sys
import uuid
import math

LIB_VERSION = "1.0.0"
AUTHOR = "GravenArc"
LICENSE = "GPL-3.0-or-later"
BLEND_NAME = "GravenArc_Brushes.blend"
CATS_FILE = "blender_assets.cats.txt"
NS = uuid.UUID("6f1c2a52-7d0e-4b8e-9a3f-0a7c5e1b2d40")  # фиксированное пространство имён для UUID каталогов

# ---------------------------------------------------------------------------
# Каталоги (путь -> подпись). UUID получается из пути, поэтому стабилен между запусками.
CATALOGS = {
    "GravenArc/Brushes/Build":   "Набор массы",
    "GravenArc/Brushes/Carve":   "Резка и гравировка",
    "GravenArc/Brushes/Flatten": "Плоскости и полировка",
    "GravenArc/Brushes/Smooth":  "Сглаживание",
    "GravenArc/Brushes/Move":    "Перемещение и форма",
    "GravenArc/Brushes/Mask":    "Маски",
}


def cat_uuid(path):
    return str(uuid.uuid5(NS, path))


# ---------------------------------------------------------------------------
# Кривые спада (x: 0 = центр, 1 = край; y: сила). Используются как CUSTOM-кривая.
CURVES = {
    # узкий острый пик: прорезь как у Dam Standard
    "dam":      [(0.0, 1.0), (0.08, 0.72), (0.22, 0.30), (0.45, 0.08), (1.0, 0.0)],
    # «столик» с мягким краем: Clay Buildup / hPolish
    "plateau":  [(0.0, 1.0), (0.55, 0.97), (0.80, 0.55), (1.0, 0.0)],
    # почти постоянная сила с коротким спадом: Trim / Flatten
    "hard":     [(0.0, 1.0), (0.80, 1.0), (0.93, 0.45), (1.0, 0.0)],
    # гладкий колокол: Move, Inflate
    "bell":     [(0.0, 1.0), (0.25, 0.88), (0.50, 0.50), (0.75, 0.12), (1.0, 0.0)],
    # линейный: Standard
    "linear":   [(0.0, 1.0), (1.0, 0.0)],
    # ровная гравировальная канавка (с плоским дном)
    "groove":   [(0.0, 1.0), (0.35, 0.95), (0.60, 0.45), (0.85, 0.06), (1.0, 0.0)],
}

# ---------------------------------------------------------------------------
# Описание кистей. Ключи, кроме служебных (name/zb/cat/desc/tags/curve/icon/mm), —
# это свойства bpy.types.Brush и присваиваются как есть.
BRUSHES = [
    # ---------------- Набор массы
    dict(name="GA Clay Buildup", zb="Clay Buildup", cat="Build", curve="plateau", icon="build",
         desc="Квадратные мазки глины, быстрый набор формы. Аналог ZBrush Clay Buildup.",
         sculpt_brush_type='CLAY_STRIPS', strength=0.55, tip_roundness=0.0, hardness=0.35,
         spacing=7, plane_offset=0.0, normal_radius_factor=1.0, area_radius_factor=1.0,
         use_pressure_strength=True, use_pressure_size=False, size=90),
    dict(name="GA Clay", zb="Clay", cat="Build", curve="bell", icon="build",
         desc="Мягкая глина по плоскости, заполняет впадины. Аналог ZBrush Clay.",
         sculpt_brush_type='CLAY', strength=0.45, spacing=8, use_pressure_strength=True, size=80),
    dict(name="GA Standard", zb="Standard", cat="Build", curve="linear", icon="build",
         desc="Базовое выдавливание по нормали. Аналог ZBrush Standard.",
         sculpt_brush_type='DRAW', strength=0.5, spacing=8, use_pressure_strength=True, size=60),
    dict(name="GA Inflate", zb="Inflat", cat="Build", curve="bell", icon="build",
         desc="Раздувает объём во все стороны. Аналог ZBrush Inflat.",
         sculpt_brush_type='INFLATE', strength=0.4, spacing=8, size=80),
    dict(name="GA Layer", zb="Layer", cat="Build", curve="hard", icon="build",
         desc="Наращивает ровный слой фиксированной высоты (рельеф, бортики). Аналог ZBrush Layer.",
         sculpt_brush_type='LAYER', strength=0.6, height=0.08, use_persistent=True, spacing=6, size=60),
    dict(name="GA Blob", zb="Blob", cat="Build", curve="bell", icon="build",
         desc="Шарообразный набор: зернь, капли, бусины. Аналог ZBrush Inflat/Blob.",
         sculpt_brush_type='BLOB', strength=0.5, crease_pinch_factor=0.5, spacing=8, size=50),

    # ---------------- Резка и гравировка
    dict(name="GA Dam Standard", zb="Dam_Standard", cat="Carve", curve="dam", icon="carve",
         desc="Острая прорезь с поджатием краёв: складки, линии, швы. Аналог ZBrush Dam_Standard. Alt — выпуклый гребень.",
         sculpt_brush_type='CREASE', direction='SUBTRACT', strength=0.55, crease_pinch_factor=0.75,
         spacing=5, use_pressure_strength=True, use_smooth_stroke=True,
         smooth_stroke_radius=30, smooth_stroke_factor=0.75, size=30),
    dict(name="GA Orb Cracks", zb="Orb_Cracks", cat="Carve", curve="dam", icon="carve",
         desc="Тонкая трещина/риска без поджатия краёв. Аналог Orb_Cracks.",
         sculpt_brush_type='DRAW_SHARP', direction='SUBTRACT', strength=0.6, spacing=4,
         use_smooth_stroke=True, smooth_stroke_radius=40, smooth_stroke_factor=0.85, size=20),
    dict(name="GA Pinch", zb="Pinch", cat="Carve", curve="bell", icon="carve",
         desc="Стягивает поверхность к центру мазка, заостряет рёбра. Аналог ZBrush Pinch.",
         sculpt_brush_type='PINCH', strength=0.5, spacing=8, size=50),
    dict(name="GA Groove 0.5 mm", zb="Dam_Standard (мм)", cat="Carve", curve="groove", icon="carve", mm=0.5,
         desc="Гравировальная канавка шириной 0,5 мм в размере сцены (не зависит от зума). Минимум для литья в песок.",
         sculpt_brush_type='DRAW_SHARP', direction='SUBTRACT', strength=0.5, spacing=3,
         use_smooth_stroke=True, smooth_stroke_radius=35, smooth_stroke_factor=0.85),
    dict(name="GA Groove 1.0 mm", zb="Dam_Standard (мм)", cat="Carve", curve="groove", icon="carve", mm=1.0,
         desc="Канавка шириной 1 мм в размере сцены: контуры орнамента, разделение элементов.",
         sculpt_brush_type='DRAW_SHARP', direction='SUBTRACT', strength=0.5, spacing=3,
         use_smooth_stroke=True, smooth_stroke_radius=35, smooth_stroke_factor=0.85),
    dict(name="GA Bead 0.8 mm", zb="Inflat (мм)", cat="Build", curve="bell", icon="build", mm=0.8,
         desc="Зернь/бусина диаметром ~0,8 мм в размере сцены. Ставьте точками (метод Dots).",
         sculpt_brush_type='BLOB', strength=0.7, crease_pinch_factor=0.6, stroke_method='DOTS', spacing=100),

    # ---------------- Плоскости и полировка
    dict(name="GA hPolish", zb="hPolish", cat="Flatten", curve="plateau", icon="flat",
         desc="Жёсткая полировка: срезает бугры и заполняет ямки, даёт чёткие фаски. Аналог ZBrush hPolish.",
         sculpt_brush_type='PLANE', plane_height=1.0, plane_depth=1.0, strength=0.6,
         tip_roundness=0.0, hardness=0.6, spacing=6, area_radius_factor=1.0, use_original_plane=False,
         use_pressure_strength=True, size=80),
    dict(name="GA Trim Dynamic", zb="TrimDynamic", cat="Flatten", curve="hard", icon="flat",
         desc="Срезает выступы по динамической плоскости, оставляя впадины. Аналог ZBrush Trim Dynamic.",
         sculpt_brush_type='PLANE', plane_height=1.0, plane_depth=0.0, strength=0.7,
         tip_roundness=0.0, hardness=0.5, spacing=6, area_radius_factor=0.6,
         use_pressure_strength=True, size=80),
    dict(name="GA Flatten", zb="Flatten", cat="Flatten", curve="hard", icon="flat",
         desc="Выравнивает к средней плоскости под кистью. Аналог ZBrush Flatten.",
         sculpt_brush_type='PLANE', plane_height=1.0, plane_depth=1.0, strength=0.5,
         use_original_plane=True, spacing=7, size=80),
    dict(name="GA Fill", zb="Fill", cat="Flatten", curve="bell", icon="flat",
         desc="Заполняет впадины до плоскости, не трогая выступы.",
         sculpt_brush_type='PLANE', plane_height=0.0, plane_depth=1.0, strength=0.5, spacing=7, size=80),
    dict(name="GA Planar Cut", zb="Planar", cat="Flatten", curve="hard", icon="flat",
         desc="Две плоскости под углом: острые грани, огранка, рёбра. Аналог ZBrush Planar/Trim Adaptive.",
         sculpt_brush_type='MULTIPLANE_SCRAPE', strength=0.8, spacing=6, size=70,
         use_multiplane_scrape_dynamic=True),

    # ---------------- Сглаживание
    dict(name="GA Smooth", zb="Smooth", cat="Smooth", curve="bell", icon="smooth",
         desc="Обычное сглаживание (работает и как Shift из любой кисти).",
         sculpt_brush_type='SMOOTH', strength=0.5, spacing=8, size=80),
    dict(name="GA Smooth Surface", zb="SmoothPeaks/Stronger", cat="Smooth", curve="bell", icon="smooth",
         desc="Сглаживает поверхность, сохраняя общий объём (режим Surface).",
         sculpt_brush_type='SMOOTH', smooth_deform_type='SURFACE', strength=0.6, spacing=8, size=80),

    # ---------------- Перемещение и форма
    dict(name="GA Move", zb="Move", cat="Move", curve="bell", icon="move",
         desc="Тянет участок сетки. Аналог ZBrush Move.",
         sculpt_brush_type='GRAB', strength=1.0, size=150),
    dict(name="GA Move Topological", zb="Move Topological", cat="Move", curve="bell", icon="move",
         desc="Тянет только связанную сетку: не цепляет соседний лепесток/стенку.",
         sculpt_brush_type='GRAB', strength=1.0, use_connected_only=True, size=150),
    dict(name="GA Move Elastic", zb="Move Elastic", cat="Move", curve="bell", icon="move",
         desc="Упругое перемещение без разрывов формы. Аналог ZBrush Move Elastic.",
         sculpt_brush_type='ELASTIC_DEFORM', elastic_deform_type='GRAB', strength=1.0, size=150),
    dict(name="GA Snakehook", zb="SnakeHook", cat="Move", curve="bell", icon="move",
         desc="Вытягивает отростки: завитки, усики, листья. Аналог ZBrush SnakeHook.",
         sculpt_brush_type='SNAKE_HOOK', strength=1.0, crease_pinch_factor=0.3, size=60),
    dict(name="GA Nudge", zb="Move (Nudge)", cat="Move", curve="bell", icon="move",
         desc="Сдвигает поверхность вдоль себя, не меняя высоты.",
         sculpt_brush_type='NUDGE', strength=0.5, size=80),

    # ---------------- Маски
    dict(name="GA Mask Pen", zb="MaskPen", cat="Mask", curve="hard", icon="mask",
         desc="Рисует маску с жёстким краем. Ctrl — стереть маску.",
         sculpt_brush_type='MASK', strength=1.0, size=40),
]

SERVICE_KEYS = {"name", "zb", "cat", "desc", "tags", "curve", "icon", "mm"}

# диаметр в мм, если пользователь переключит кисть в размер сцены
SCENE_MM_DEFAULT = {"Build": 3.0, "Carve": 1.0, "Flatten": 4.0,
                    "Smooth": 4.0, "Move": 10.0, "Mask": 2.0}

ICON_COLORS = {
    "build":  (0.93, 0.65, 0.33),
    "carve":  (0.85, 0.35, 0.30),
    "flat":   (0.45, 0.70, 0.90),
    "smooth": (0.55, 0.80, 0.55),
    "move":   (0.75, 0.55, 0.90),
    "mask":   (0.70, 0.70, 0.70),
}


# ---------------------------------------------------------------------------
def set_curve(brush, pts):
    brush.curve_distance_falloff_preset = 'CUSTOM'
    cmap = brush.curve_distance_falloff
    curve = cmap.curves[0]
    while len(curve.points) > 2:
        curve.points.remove(curve.points[1])
    curve.points[0].location = pts[0]
    curve.points[-1].location = pts[-1]
    for x, y in pts[1:-1]:
        curve.points.new(x, y)
    for p in curve.points:
        p.handle_type = 'AUTO'
    cmap.update()


def curve_value(pts, x):
    """Линейная интерполяция по точкам (только для рисования иконки)."""
    x = min(max(x, 0.0), 1.0)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 + (y1 - y0) * t
    return pts[-1][1]


def draw_icon(brush, pts, color, invert, mm):
    """Иконка 128x128: профиль кисти (сечение мазка) на тёмном фоне."""
    n = 128
    prev = brush.preview_ensure()
    prev.image_size = (n, n)
    px = [0.0] * (n * n * 4)
    bg = (0.13, 0.13, 0.14)
    base = 0.42 if invert else 0.30  # уровень «поверхности»
    amp = 0.40
    for j in range(n):
        y = j / (n - 1)
        for i in range(n):
            xn = abs((i / (n - 1)) * 2.0 - 1.0) / 0.85  # центр иконки = центр кисти
            h = curve_value(pts, xn) * amp
            surf = base - h if invert else base + h
            k = (j * n + i) * 4
            if y <= surf:
                shade = 0.65 + 0.35 * y / max(surf, 1e-3)
                px[k:k + 4] = [color[0] * shade, color[1] * shade, color[2] * shade, 1.0]
            else:
                px[k:k + 4] = [bg[0], bg[1], bg[2], 1.0]
    # отметка «мм»: светлая полоса снизу
    if mm:
        for j in range(0, 6):
            for i in range(10, n - 10):
                k = (j * n + i) * 4
                px[k:k + 4] = [0.95, 0.95, 0.95, 1.0]
    prev.image_pixels_float = px


def setup_scene_mm(scene):
    us = scene.unit_settings
    us.system = 'METRIC'
    us.scale_length = 0.001
    us.length_unit = 'MILLIMETERS'
    scene.render.fps = 30


def build(root):
    # чистый файл: только кисти, без куба/камеры/света
    for coll in (bpy.data.brushes, bpy.data.objects, bpy.data.meshes,
                 bpy.data.cameras, bpy.data.lights):
        for idb in list(coll):
            coll.remove(idb)
    setup_scene_mm(bpy.context.scene)

    # Некоторые свойства (например direction = SUBTRACT) Blender разрешает
    # только когда активен режим скульпта, поэтому временно входим в него.
    tmp_me = bpy.data.meshes.new("_ga_tmp")
    tmp_ob = bpy.data.objects.new("_ga_tmp", tmp_me)
    bpy.context.scene.collection.objects.link(tmp_ob)
    bpy.context.view_layer.objects.active = tmp_ob
    bpy.ops.object.mode_set(mode='SCULPT')

    made = []
    for spec in BRUSHES:
        b = bpy.data.brushes.new(spec["name"], mode='SCULPT')
        props = {k: v for k, v in spec.items() if k not in SERVICE_KEYS}
        # тип кисти задаём первым: от него зависят остальные поля
        b.sculpt_brush_type = props.pop("sculpt_brush_type")
        for k, v in props.items():
            if not hasattr(b, k):
                raise AttributeError(f"{spec['name']}: у Brush нет свойства {k!r}")
            setattr(b, k, v)
        if spec.get("mm"):
            b.use_locked_size = 'SCENE'
            b.unprojected_size = float(spec["mm"])  # диаметр в BU = мм
        else:
            # размер «на экране», но если переключить Radius Unit на Scene —
            # получится разумный диаметр в мм для ювелирной детали
            b.unprojected_size = SCENE_MM_DEFAULT[spec["cat"]]
        pts = CURVES[spec["curve"]]
        set_curve(b, pts)
        invert = getattr(b, "direction", 'ADD') == 'SUBTRACT'
        draw_icon(b, pts, ICON_COLORS[spec["icon"]], invert, spec.get("mm"))

        b.use_fake_user = True
        b.asset_mark()
        ad = b.asset_data
        ad.author = AUTHOR
        ad.license = LICENSE
        ad.copyright = AUTHOR
        ad.description = spec["desc"] + f" (ZBrush: {spec['zb']}; GravenArc Toolkit {LIB_VERSION})"
        cat_path = "GravenArc/Brushes/" + spec["cat"]
        ad.catalog_id = cat_uuid(cat_path)
        for t in ["GravenArc", "ZBrush-style", spec["zb"], spec["cat"]] + spec.get("tags", []):
            if t not in ad.tags:
                ad.tags.new(t, skip_if_exists=True)
        if spec.get("mm"):
            ad.tags.new("mm", skip_if_exists=True)
        made.append(b)

    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(tmp_ob)
    bpy.data.meshes.remove(tmp_me)

    # Объёмные иконки (шар из «красного воска» с настоящим мазком), как в ZBrush.
    # Если рендер недоступен — останутся схематичные иконки-профили.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import brush_icons
        icons = brush_icons.render_icons(BRUSHES, CURVES, os.path.join(bpy.app.tempdir or "/tmp", "ga_icons"))
        brush_icons.contact_sheet(list(icons.values()), list(icons.keys()),
                                  os.path.join(root, "brushes", "brushes_preview.png"))
    except Exception as ex:
        print("[GravenArc] объёмные иконки не отрисованы:", ex)

    out_dir = os.path.join(root, "brushes")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, BLEND_NAME)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    write_catalogs(root)
    print(f"[GravenArc] сохранено {len(made)} кистей -> {out}")
    return out


def write_catalogs(root):
    """Дописывает недостающие каталоги в общий blender_assets.cats.txt, не трогая чужие строки."""
    path = os.path.join(root, CATS_FILE)
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    if not lines:
        lines = [
            "# This is an Asset Catalog Definition file for Blender.",
            "#",
            "# Empty lines and lines starting with `#` will be ignored.",
            "# The first non-ignored line should be the version indicator.",
            '# Other lines are of the format "UUID:catalog/path/for/assets:simple catalog name"',
            "",
            "VERSION 1",
            "",
        ]
    existing_ids = {l.split(":", 1)[0] for l in lines if l and not l.startswith("#") and ":" in l}
    existing_paths = {l.split(":")[1] for l in lines if l.count(":") >= 2 and not l.startswith("#")}
    wanted = {"GravenArc": "GravenArc", "GravenArc/Brushes": "Кисти GravenArc"}
    wanted.update({p: f"GravenArc-{p.rsplit('/', 1)[1]}" for p in CATALOGS})
    added = 0
    for p, simple in wanted.items():
        cid = cat_uuid(p)
        if cid in existing_ids or p in existing_paths:
            continue
        lines.append(f"{cid}:{p}:{simple}")
        added += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    print(f"[GravenArc] каталоги: добавлено {added} -> {path}")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if argv:
        root = os.path.abspath(argv[0])
    else:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    build(root)


if __name__ == "__main__":
    main()

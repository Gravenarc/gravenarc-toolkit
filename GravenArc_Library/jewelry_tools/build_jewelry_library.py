# SPDX-License-Identifier: GPL-3.0-or-later
"""Сборка библиотеки ассетов GravenArc/Jewelry из кода аддона gravenarc_jewelry.

Запуск (из папки jewelry_tools):
    blender -b --factory-startup --python build_jewelry_library.py
    blender -b --factory-startup --python build_jewelry_library.py -- --no-previews

Результат:
    GravenArc_Jewelry.blend   — камни, вырезы, крапановые и глухие касты (ассеты)
    jewelry_preview.png       — лист-превью
    demo/GravenArc_Jewelry_Demo.blend, demo/demo_render.png — демо: кольцо с овалом, паве, дорожка
    ../blender_assets.cats.txt        — дописываются каталоги GravenArc/Jewelry/...
"""
import math
import os
import sys
import uuid

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gravenarc_jewelry as GJ  # noqa: E402
from gravenarc_jewelry import core, gems, ring, layout  # noqa: E402

LIB_ROOT = os.path.dirname(HERE)
OUT_DIR = HERE
CATS = {
    "GravenArc/Jewelry": "Ювелирные инструменты",
    "GravenArc/Jewelry/Gems": "Камни",
    "GravenArc/Jewelry/Cutters": "Вырезы под камни",
    "GravenArc/Jewelry/Heads": "Крапановые касты",
    "GravenArc/Jewelry/Bezels": "Глухие касты",
}
_NS = uuid.UUID("6a1f0c2e-9b7d-4c1e-8f3a-2d5b6e7c8a90")  # тот же namespace, что у шаблонов


def cat_uuid(path):
    return str(uuid.uuid5(_NS, path))


def write_catalogs(path):
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else [
        "# This is an Asset Catalog Definition file for Blender.", "#", "VERSION 1", ""]
    have = {ln.split(":")[1] for ln in lines if ln and not ln.startswith(("#", "VERSION")) and ln.count(":") >= 2}
    added = []
    for p in CATS:
        if p not in have:
            lines.append(f"{cat_uuid(p)}:{p}:{p.replace('/', '-')}")
            added.append(p)
    if added:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return added


def mark(idb, cat, desc, tags):
    idb.asset_mark()
    ad = idb.asset_data
    ad.catalog_id = cat_uuid(cat)
    ad.description = desc
    ad.author = "GravenArc"
    ad.license = "GPL-3.0-or-later"
    for t in tags:
        ad.tags.new(t, skip_if_exists=True)


def sz(L, W):
    return f"{L:g}" if abs(L - W) < 1e-6 else f"{L:g}x{W:g}"


def build(ctx, previews=True):
    core.set_mm_scene(ctx)
    scene = ctx.scene
    lib = bpy.data.collections.new("GV_Library")
    scene.collection.children.link(lib)
    assets = []  # (id, obj_for_preview)

    gem_list = [
        ('ROUND', 1.0), ('ROUND', 1.2), ('ROUND', 1.3), ('ROUND', 1.8), ('OVAL', 5, 7), ('PRINCESS', 3),
        ('PEAR', 4, 6), ('PEAR', 5, 8), ('MARQUISE', 3, 6), ('MARQUISE', 4, 8), ('HEART', 5), ('HEART', 6),
        ('CUSHION', 5), ('CUSHION', 6), ('TRILLION', 5), ('TRILLION', 6), ('EMERALD', 4, 6), ('EMERALD', 5, 7),
        ('ASSCHER', 5), ('ASSCHER', 6), ('BAGUETTE', 2, 4), ('BAGUETTE', 2.5, 5),
        ('CAB_ROUND', 6), ('CAB_ROUND', 8), ('CAB_OVAL', 6, 8), ('CAB_OVAL', 8, 10),
    ]
    for item in gem_list:
        cut, W = item[0], item[1]
        L = item[2] if len(item) > 2 else W
        ob = gems.new_gem(ctx, cut, L, W, 'DIAMOND', None, lib, name=f"GA_Gem_{cut.title()}_{sz(L, W)}")
        mark(ob, "GravenArc/Jewelry/Gems",
             f"{gems.CUTS[cut]['label']} {sz(L, W)} мм, ≈{ob['gv_carat']:.3f} ct (бриллиант). Центр рундиста в начале "
             f"координат, площадка вверх. Свойства gv_gem* понимают инструменты GravenArc (вырезы, касты, отчёт).",
             ["камень", gems.CUTS[cut]['label'].split(" ")[0].lower(), f"{sz(L, W)} мм"])
        assets.append(ob)

    cutter_list = [('ROUND', d, d, 20.0) for d in (1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0)] + [
        ('ROUND', 4, 4, 0.0), ('ROUND', 5, 5, 0.0), ('OVAL', 7, 5, 0.0), ('PEAR', 8, 5, 0.0),
        ('MARQUISE', 8, 4, 0.0), ('EMERALD', 7, 5, 0.0), ('PRINCESS', 4, 4, 0.0)]
    for cut, L, W, flare in cutter_list:
        me = gems.cutter_mesh(ctx, cut, L, W, 0.05, 1.5, flare, 0.55, 1.5)
        ob = core.link_object(ctx, f"GA_Cutter_{cut.title()}_{sz(L, W)}" + ("_Pave" if flare else ""), me, lib)
        gems.style_cutter(ob)
        ob.display_type = 'SOLID'
        mark(ob, "GravenArc/Jewelry/Cutters",
             f"Вырез под {gems.CUTS[cut]['label'].lower()} {sz(L, W)} мм: посадка по рундисту (+0,05 мм), конус "
             f"по павильону, отверстие 55% под калетой" + (f", раскрытие {flare:g}° для паве" if flare else "") +
             ". Использовать в Boolean › Difference.", ["вырез", "cutter", f"{sz(L, W)} мм"])
        assets.append(ob)

    metal = GJ.ops.metal_material('AU750Y')
    heads = [('ROUND', 5, 5, 4), ('ROUND', 6, 6, 4), ('ROUND', 6.5, 6.5, 6), ('OVAL', 8, 6, 4), ('PEAR', 8, 5, 5),
             ('MARQUISE', 10, 5, 6), ('PRINCESS', 5, 5, 4), ('EMERALD', 7, 5, 4), ('HEART', 6, 6, 3),
             ('TRILLION', 6, 6, 3), ('CUSHION', 6, 6, 4)]
    bezels = [('ROUND', 6, 6), ('OVAL', 8, 6), ('PEAR', 8, 5), ('MARQUISE', 10, 5), ('EMERALD', 7, 5),
              ('HEART', 6, 6), ('CUSHION', 6, 6), ('PRINCESS', 5, 5), ('CAB_ROUND', 8, 8), ('CAB_OVAL', 10, 8)]
    for kind, items in (('PRONG', heads), ('BEZEL', bezels)):
        for it in items:
            cut, L, W = it[:3]
            name = f"GA_{'Head' if kind == 'PRONG' else 'Bezel'}_{cut.title()}_{sz(L, W)}" + (
                f"_{it[3]}pr" if kind == 'PRONG' else "")
            col = bpy.data.collections.new(name)
            lib.children.link(col)
            g = gems.new_gem(ctx, cut, L, W, 'DIAMOND', None, col, name=name + "_Gem")
            if kind == 'PRONG':
                bm = gems.build_prong_head_bm(cut, L, W, prongs=it[3], prong_d=max(0.7, round(0.13 * W, 2)))
            else:
                bm = gems.build_bezel_bm(cut, L, W)
            h = gems.bm_to_object(ctx, bm, name + "_Metal", col, smooth=(kind == 'PRONG'))
            h.data.materials.append(metal)
            h["gv_metal"] = True
            h.parent = g
            cme = gems.cutter_mesh(ctx, cut, L, W, 0.05, 1.5, 0.0, 0.55, 1.5)
            c = core.link_object(ctx, name + "_Cutter", cme, col)
            gems.style_cutter(c)
            c.parent = g
            c.hide_viewport = False
            what = "Крапановая каста" if kind == 'PRONG' else "Глухая каста"
            mark(col, "GravenArc/Jewelry/Heads" if kind == 'PRONG' else "GravenArc/Jewelry/Bezels",
                 f"{what} под {gems.CUTS[cut]['label'].lower()} {sz(L, W)} мм" +
                 (f", {it[3]} крапанов, галерея" if kind == 'PRONG' else ", стенка 0,7, уклон 2°, полка 0,35") +
                 ". В комплекте: камень, металл, вырез (каркас). При перетаскивании снимите «Instance» "
                 "в панели последней операции, чтобы получить редактируемые объекты.",
                 ["каста", "крапаны" if kind == 'PRONG' else "глухая", f"{sz(L, W)} мм"])
            assets.append(col)
    return assets


def layout_grid(objs_cols, spacing=14.0, per_row=10):
    placed = []
    for i, a in enumerate(objs_cols):
        x, y = (i % per_row) * spacing, -(i // per_row) * spacing
        if isinstance(a, bpy.types.Object):
            a.location = (x, y, 0)
        else:
            for o in a.objects:
                if o.parent is None:
                    o.location = (x, y, 0)
        placed.append(a)
    return placed


def setup_render(scene, w, h, samples=24):
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new("GV_World")
    world.color = (0.86, 0.88, 0.93)
    try:
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[0].default_value = (0.80, 0.83, 0.90, 1)
    except Exception:
        pass
    scene.world = world
    for name, rot, e in (("GV_Key", (0.7, 0.2, 0.9), 4.0), ("GV_Fill", (-0.8, 0.1, -2.4), 1.8)):
        ld = bpy.data.lights.new(name, 'SUN')
        ld.energy = e
        lo = bpy.data.objects.new(name, ld)
        lo.rotation_euler = rot
        scene.collection.objects.link(lo)
    cam_d = bpy.data.cameras.new("GV_Cam")
    cam_d.type = 'ORTHO'
    cam = bpy.data.objects.new("GV_Cam", cam_d)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def frame(cam, objs, direction=Vector((0.35, -1.0, 1.1)), pad=1.08):
    pts = []
    for o in objs:
        pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    center = sum(pts, Vector()) / len(pts)
    d = direction.normalized()
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    inv = cam.rotation_euler.to_matrix().inverted()
    pr = [inv @ (p - center) for p in pts]
    sx = max(p.x for p in pr) - min(p.x for p in pr)
    sy = max(p.y for p in pr) - min(p.y for p in pr)
    mid = Vector(((max(p.x for p in pr) + min(p.x for p in pr)) / 2, (max(p.y for p in pr) + min(p.y for p in pr)) / 2, 0))
    center = center + cam.rotation_euler.to_matrix() @ mid
    scene = bpy.context.scene
    aspect = scene.render.resolution_x / scene.render.resolution_y
    cam.data.ortho_scale = max(sx, sy * aspect) * pad
    cam.location = center + d * 500
    cam.data.clip_end = 2000


def solid_look():
    """Простые материалы для превью: стекловидные камни плохо читаются при 24 сэмплах."""
    for m in bpy.data.materials:
        if m.name.startswith("GV Gem"):
            b = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
            if b:
                (b.inputs.get("Transmission Weight") or b.inputs["Transmission"]).default_value = 0.0
                b.inputs["Base Color"].default_value = (0.62, 0.78, 0.95, 1)
                b.inputs["Roughness"].default_value = 0.25
        if m.name == "GV Cutter":
            m.use_nodes = True
            b = m.node_tree.nodes.get("Principled BSDF")
            b.inputs["Base Color"].default_value = (0.95, 0.35, 0.2, 1)


def asset_previews(assets, size=160):
    scene = bpy.context.scene
    cam = scene.camera
    old = (scene.render.resolution_x, scene.render.resolution_y, scene.cycles.samples)
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.cycles.samples = 12
    tmp = os.path.join(bpy.app.tempdir or "/tmp", "gv_jprev.png")
    allobs = [o for o in scene.objects if o.type == 'MESH']
    n = 0
    for a in assets:
        obs = [a] if isinstance(a, bpy.types.Object) else list(a.objects)
        for o in allobs:
            o.hide_render = o not in obs
        for o in obs:
            if o.get("gv_cutter") and not isinstance(a, bpy.types.Object):
                o.hide_render = True
        frame(cam, [o for o in obs if not o.hide_render] or obs, pad=1.15)
        scene.render.filepath = tmp
        try:
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(tmp, check_existing=False)
            prev = a.preview_ensure()
            prev.image_size = (size, size)
            prev.image_pixels_float[:] = list(img.pixels)
            bpy.data.images.remove(img)
            n += 1
        except Exception as e:
            print("preview failed", a.name, e)
    for o in allobs:
        o.hide_render = bool(o.get("gv_cutter")) and o.parent is not None
    scene.render.resolution_x, scene.render.resolution_y, scene.cycles.samples = old
    return n


def reset():
    try:
        GJ.unregister()
    except Exception:
        pass
    bpy.ops.wm.read_factory_settings(use_empty=True)
    GJ.register()


def build_demo(ctx, out_png, out_blend):
    """Демо: кольцо RU17 с овалом на крапанах, дорожка камней по плечам, гравировка внутри; кулон с паве."""
    reset()
    ctx = bpy.context
    core.set_mm_scene(ctx)
    O = bpy.ops.gravenarc
    O.ring_shank(size_value=17, profile='COMFORT', w_top=5.0, w_bot=2.6, t_top=2.0, t_bot=1.5)
    shank = ctx.active_object
    # камень сверху
    ctx.scene.cursor.location = (0, 12, 0)
    ctx.scene.cursor.rotation_euler = (0, 0, 0)
    O.gem_add(cut='OVAL', size=6, length=8, height=1.6, head='PRONG', make_cutter=True)
    gem = ctx.active_object
    # дорожка по плечам: дуга-кривая по наружной поверхности
    R = 8.5 + 1.95
    for sgn in (-1, 1):
        cu = bpy.data.curves.new("Shoulder", 'CURVE')
        cu.dimensions = '3D'
        sp = cu.splines.new('POLY')
        angs = [math.radians(a) for a in range(25, 76, 5)]
        sp.points.add(len(angs) - 1)
        for p, a in zip(sp.points, angs):
            p.co = (sgn * R * math.sin(a), R * math.cos(a), 0, 1)
        co = bpy.data.objects.new("Shoulder", cu)
        ctx.collection.objects.link(co)
        for o in ctx.selected_objects:
            o.select_set(False)
        shank.select_set(True)
        co.select_set(True)
        ctx.view_layer.objects.active = co
        O.gems_on_curve(size=1.6, size_end=1.2, grade='LINEAR', gap=0.15, orient='SURFACE', height=-0.32,
                        prongs=False, cutters=True)
        co.hide_render = True
    for o in ctx.selected_objects:
        o.select_set(False)
    shank.select_set(True)
    ctx.view_layer.objects.active = shank
    O.engrave_text(text="GravenArc", place='IN', height=1.4, depth=0.3, boolean=True)
    GJ.ops.add_boolean(shank, bpy.data.collections["GV Cutters"])
    # кулон-диск с паве
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=9, depth=2.2, location=(26, 0, 0))
    disc = ctx.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.object.mode_set(mode='OBJECT')
    for p in disc.data.polygons:
        p.select = p.normal.z > 0.9
    disc.data.materials.append(GJ.ops.metal_material('AU750Y'))
    O.pave(size=1.3, gap=0.15, beads=True, cutters=True, boolean=True)
    shank.data.materials.clear()
    shank.data.materials.append(GJ.ops.metal_material('AU750Y'))
    bpy.ops.wm.save_as_mainfile(filepath=out_blend)
    # рендер
    cam = setup_render(ctx.scene, 1400, 800, 32)
    solid_look()
    vis = [o for o in ctx.scene.objects if o.type == 'MESH' and not o.hide_render]
    for o in ctx.scene.objects:
        if o.get("gv_cutter"):
            o.hide_render = True
    frame(cam, [o for o in vis if not o.get("gv_cutter")], Vector((0.25, -1.0, 0.9)), 1.05)
    ctx.scene.render.filepath = out_png
    bpy.ops.render.render(write_still=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    previews = "--no-previews" not in argv
    os.makedirs(OUT_DIR, exist_ok=True)
    reset()
    ctx = bpy.context
    assets = build(ctx, previews)
    layout_grid(assets)
    cam = setup_render(ctx.scene, 1600, 1100, 24)
    solid_look()
    n_prev = asset_previews(assets) if previews else 0
    for o in ctx.scene.objects:
        if o.get("gv_cutter") and o.parent is not None:
            o.hide_render = True
    frame(cam, [o for o in ctx.scene.objects if o.type == 'MESH' and not o.hide_render],
          Vector((0.0, -0.55, 1.0)), 1.04)
    ctx.scene.render.filepath = os.path.join(OUT_DIR, "jewelry_preview.png")
    bpy.ops.render.render(write_still=True)
    out = os.path.join(OUT_DIR, "GravenArc_Jewelry.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    added = write_catalogs(os.path.join(LIB_ROOT, "blender_assets.cats.txt"))
    print(f"GV: ассетов {len(assets)}, превью {n_prev}, каталогов добавлено {added}")
    if "--no-demo" not in argv:
        os.makedirs(os.path.join(OUT_DIR, "demo"), exist_ok=True)
        build_demo(ctx, os.path.join(OUT_DIR, "demo", "demo_render.png"),
                   os.path.join(OUT_DIR, "demo", "GravenArc_Jewelry_Demo.blend"))
        print("GV: демо готово")


if __name__ == "__main__":
    main()

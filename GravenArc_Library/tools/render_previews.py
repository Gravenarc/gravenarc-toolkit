# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc: студийные превью для готовых .blend-библиотек (шаблоны, ювелирка)
# и витринные листы с подписями.
#
#   blender -b --factory-startup --python render_previews.py -- templates
#   blender -b --factory-startup --python render_previews.py -- jewelry
# Потом витрина (обычный Python с Pillow):
#   python3 showcase_sheet.py ... (вызывается автоматически, если есть python3 с Pillow)

import json
import os
import subprocess
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import studio  # noqa: E402

TEMPLATE_LOOK = {"Шинки": "gold", "Кольца": "gold", "Касты": "gold", "Кулоны": "silver",
                 "Камни-болванки": "diamond", "Проволока и скань": "silver"}
TOP = Vector((0.35, -0.7, 1.0))
RING = Vector((0.45, -1.0, 0.5))          # кольца — пониже, видно профиль и толщину


def _sheet(pairs, out, title, subtitle, cols, cell):
    lst = os.path.join(bpy.app.tempdir or "/tmp", "ga_sheet.json")
    with open(lst, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False)
    code = ("import json,sys;sys.path.insert(0,%r);import showcase_sheet as s;from PIL import Image;"
            "p=json.load(open(%r,encoding='utf-8'));"
            "s.build([(Image.open(a),b) for a,b in p],%r,%r,%r,cols=%d,cell=%d)") % (
        HERE, lst, out, title, subtitle, cols, cell)
    for py in ("python3", "python"):
        try:
            subprocess.run([py, "-c", code], check=True)
            print("[GravenArc] витрина:", out)
            return True
        except Exception:
            continue
    print("[GravenArc] нет Python с Pillow — витрина не собрана")
    return False


def nice(name):
    return name.replace("GA_", "").replace("_", " ")


def templates():
    path = os.path.join(ROOT, "templates", "GravenArc_Templates.blend")
    bpy.ops.wm.open_mainfile(filepath=path)
    objs = sorted([o for o in bpy.data.objects if o.asset_data],
                  key=lambda o: (o.asset_data.catalog_simple_name, o.name))
    order = ["Шинки", "Кольца", "Кулоны", "Касты", "Камни-болванки", "Проволока и скань",
             "Основы для лепки", "Болванки персонажей", "Органика", "Геометрия", "Hard Surface"]
    objs.sort(key=lambda o: (order.index(o.get("gv_category")) if o.get("gv_category") in order else 99, o.name))
    scene = studio.new_scene(256, 48)
    out_dir = os.path.join(bpy.app.tempdir or "/tmp", "ga_tpl")
    res = {}
    for o in objs:
        cat = o.get("gv_category")
        look = TEMPLATE_LOOK.get(cat, "wax")
        ring = cat in ("Шинки", "Кольца")
        flat = not ring and cat in ("Камни-болванки", "Проволока и скань") or o.dimensions.z < 0.25 * max(o.dimensions.x, o.dimensions.y)
        res.update(studio.render_ids(scene, [(o, [o], look)], out_dir, direction=RING if ring else TOP if flat else studio.DIRECTION))
        print("[GravenArc] превью", o.name)
    studio.cleanup(scene)
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
    _rm1(path)
    pairs = [(res[o.name], nice(o.name)) for o in objs if o.name in res]
    _sheet(pairs, os.path.join(ROOT, "templates", "preview_sheet.png"), "Templates",
           f"{len(pairs)} ready-made bases in millimetres: shanks, rings, pendants, settings, gems, wire, sculpt bases",
           10, 200)


def jewelry():
    path = os.path.join(ROOT, "jewelry_tools", "GravenArc_Jewelry.blend")
    bpy.ops.wm.open_mainfile(filepath=path)
    assets = [o for o in bpy.data.objects if o.asset_data] + [c for c in bpy.data.collections if c.asset_data]
    kind = lambda a: ("1" if a.name.startswith("GA_Gem") else "2" if a.name.startswith("GA_Head")
                      else "3" if a.name.startswith("GA_Bezel") else "4")
    assets.sort(key=lambda a: (kind(a), a.name))
    scene = studio.new_scene(256, 48)
    out_dir = os.path.join(bpy.app.tempdir or "/tmp", "ga_jew")
    res = {}
    for a in assets:
        if isinstance(a, bpy.types.Object):
            if a.get("gv_cutter"):
                looks, objs, d = "keep", [a], studio.DIRECTION
            else:
                looks, objs, d = "diamond", [a], TOP
        else:
            objs = [o for o in a.all_objects if not o.get("gv_cutter") and o.type == 'MESH']
            looks = {o: ("diamond" if o.get("gv_gem") else "gold") for o in objs}
            d = studio.DIRECTION
        if objs and objs[0].get("gv_cutter"):
            # вырез: полупрозрачный красный «каркас» читается плохо — показываем телом
            m = studio.material("cutter")
            b = m.node_tree.nodes.get("Principled BSDF")
            b.inputs["Base Color"].default_value = (0.5, 0.03, 0.02, 1)
            b.inputs["Roughness"].default_value = 0.35
            b.inputs["Coat Weight"].default_value = 0.4
            looks = "cutter"
        res.update(studio.render_ids(scene, [(a, objs, looks)], out_dir, direction=d))
        print("[GravenArc] превью", a.name)
    studio.cleanup(scene)
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
    _rm1(path)
    pairs = [(res[a.name], nice(a.name)) for a in assets if a.name in res]
    _sheet(pairs, os.path.join(ROOT, "jewelry_tools", "jewelry_preview.png"), "Jewelry",
           f"{len(pairs)} assets: 13 gem cuts, cutters, prong heads and bezels in 18K gold",
           10, 200)


def _rm1(path):
    if os.path.exists(path + "1"):
        os.remove(path + "1")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["templates", "jewelry"]
    for what in argv:
        globals()[what]()

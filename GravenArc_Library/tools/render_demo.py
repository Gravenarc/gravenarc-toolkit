# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc: витринный рендер демо ювелирных инструментов (кольцо + кулон с паве).
#   blender -b --factory-startup --python render_demo.py
# Берёт jewelry_tools/demo/GravenArc_Jewelry_Demo.blend (его строит build_jewelry_library.py),
# пишет jewelry_tools/demo/demo_render.png.

import os
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import studio  # noqa: E402
from render_previews import _sheet  # noqa: E402

SIZE = 1000


def looks(objs):
    d = {}
    for o in objs:
        if o.get("gv_gem"):
            d[o] = "diamond"
        elif o.name.startswith("Prongs"):
            d[o] = "silver"            # крапаны белого золота — как в классике
        else:
            d[o] = "gold"
    return d


def _turn(objs, angle):
    """Повернуть корневые объекты вокруг X (кольцо «встаёт» камнем вверх: +Y -> +Z)."""
    R = Matrix.Rotation(angle, 4, 'X')
    for o in objs:
        o.matrix_world = R @ o.matrix_world
    bpy.context.view_layer.update()


def main():
    demo = os.path.join(ROOT, "jewelry_tools", "demo")
    bpy.ops.wm.open_mainfile(filepath=os.path.join(demo, "GravenArc_Jewelry_Demo.blend"))
    vis = [o for o in bpy.data.objects if o.type == 'MESH' and not o.hide_render and not o.get("gv_cutter")]
    disc = bpy.data.objects.get("Cylinder")
    pend = [o for o in vis if o is disc or o.name.startswith("Pave")]
    ring = [o for o in vis if o not in pend]
    scene = studio.new_scene(SIZE, 128)
    tmp = os.path.join(bpy.app.tempdir or "/tmp", "ga_demo")
    shots = []
    # кольцо ставим вертикально камнем вверх и смотрим спереди-сбоку: каста, дорожка на плечах, шинка
    roots = [o for o in bpy.data.objects if o.parent is None and o not in pend and o.type != 'CAMERA']
    _turn(roots, 1.5708)
    r = studio.render_ids(scene, [(ring[0], ring, looks(ring))], tmp, set_previews=False,
                          direction=Vector((0.75, -1.0, 0.4)), pad=1.1)
    _turn(roots, -1.5708)
    shots.append((list(r.values())[0], "Ring RU 17: 8×6 oval in prongs, graded stones on the shoulders"))
    r = studio.render_ids(scene, [(disc, pend, looks(pend))], tmp, set_previews=False,
                          direction=Vector((0.25, -0.55, 1.0)), pad=1.1)
    shots.append((list(r.values())[0], f"Pavé pendant: {len(pend) - 1} stones packed in one click"))
    studio.cleanup(scene)
    _sheet(shots, os.path.join(demo, "demo_render.png"), "Jewelry Tools",
           "Built entirely with GravenArc tools in Blender 5.2: shank by size, gem + prongs, gems on curve, pavé, cutters",
           2, 640)


if __name__ == "__main__":
    main()

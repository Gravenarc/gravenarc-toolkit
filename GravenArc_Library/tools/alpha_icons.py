# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc: превью alpha-кистей как настоящий оттиск — серебряная пластина
# с рельефом из карты высот, рендер Cycles. Картинка становится превью кисти
# и сохраняется в maps/<имя>_preview.png (+ крупная maps/<имя>_render.png).
#
# Запуск (после svg2alpha.py и make_alpha_brushes.py):
#   blender -b --factory-startup --python alpha_icons.py -- [КОРЕНЬ_БИБЛИОТЕКИ]

import json
import math
import os
import sys
from pathlib import Path

import bpy
import numpy as np

SIZE = 512
GRID = 480
SAMPLES = 48
EXAGGERATE = 2.2      # рельеф 0,3–0,4 мм на пластине 14 мм почти не виден — усиливаем для превью
SILVER = (0.93, 0.92, 0.90)


def _load_height(png):
    img = bpy.data.images.load(str(png), check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, img.channels)
    bpy.data.images.remove(img)
    return px[..., 0]                       # снизу вверх, как в Blender


def _bilinear(a, ny, nx):
    h, w = a.shape
    ys = np.linspace(0, h - 1, ny)
    xs = np.linspace(0, w - 1, nx)
    y0 = np.floor(ys).astype(int); y1 = np.minimum(y0 + 1, h - 1); fy = (ys - y0)[:, None]
    x0 = np.floor(xs).astype(int); x1 = np.minimum(x0 + 1, w - 1); fx = (xs - x0)[None, :]
    top = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx
    bot = a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def _plate_mesh(H, sx, sy, depth, base=0.12):
    """Пластина sx×sy (единицы сцены) с рельефом H∈[0,1] сверху и бортиком толщиной base."""
    ny, nx = H.shape
    X, Y = np.meshgrid(np.linspace(-sx / 2, sx / 2, nx), np.linspace(-sy / 2, sy / 2, ny))
    Z = H * depth
    top = np.stack([X, Y, Z], -1).reshape(-1, 3)
    idx = np.arange(nx * ny).reshape(ny, nx)
    faces = [np.stack([idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(),
                       idx[1:, 1:].ravel(), idx[1:, :-1].ravel()], 1)]
    # периметр -> низ
    ring = np.concatenate([idx[0, :], idx[1:, -1], idx[-1, -2::-1], idx[-2:0:-1, 0]])
    bot = top[ring].copy()
    bot[:, 2] = -base
    nb = len(top)
    bidx = nb + np.arange(len(ring))
    side = np.stack([ring, np.roll(ring, -1), np.roll(bidx, -1), bidx], 1)
    faces.append(side[:, ::-1])
    verts = np.concatenate([top, bot])
    me = bpy.data.meshes.new("_ga_plate")
    me.from_pydata(verts.tolist(), [], np.concatenate(faces).tolist() + [bidx[::-1].tolist()])
    me.update()
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), dtype=bool))
    try:
        me.set_sharp_from_angle(angle=math.radians(50))
    except AttributeError:
        pass
    return me


def _silver():
    mat = bpy.data.materials.new("_ga_silver")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao.inputs["Distance"].default_value = 0.08
    ramp = nt.nodes.new("ShaderNodeValToRGB")          # чернение в углублениях, как у старого серебра
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (0.16, 0.15, 0.14, 1)
    ramp.color_ramp.elements[1].position = 0.92
    ramp.color_ramp.elements[1].color = (*SILVER, 1)
    nt.links.new(ao.outputs["AO"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.3
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def setup_scene():
    scene = bpy.data.scenes.new("_ga_alpha")
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
    except TypeError:
        pass
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Punchy'
    world = bpy.data.worlds.new("_ga_world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.42, 0.43, 0.46, 1)
    bg.inputs[1].default_value = 0.22
    scene.world = world
    # софтбоксы: металл живёт отражениями
    for name, loc, size, e in (("_ga_key", (-2.2, -2.0, 3.2), 2.6, 520),
                               ("_ga_fill", (2.6, -1.0, 2.0), 3.0, 110),
                               ("_ga_top", (0.6, 2.4, 3.4), 2.0, 260)):
        ld = bpy.data.lights.new(name, 'AREA')
        ld.shape = 'RECTANGLE'
        ld.size, ld.size_y = size, size * 0.6
        ld.energy = e
        lo = bpy.data.objects.new(name, ld)
        lo.location = loc
        d = -np.array(loc)
        lo.rotation_euler = (math.atan2(math.hypot(d[0], d[1]), -d[2]), 0, math.atan2(d[1], d[0]) + math.pi / 2)
        scene.collection.objects.link(lo)
    cam_d = bpy.data.cameras.new("_ga_cam")
    cam_d.type = 'ORTHO'
    cam = bpy.data.objects.new("_ga_cam", cam_d)
    tilt = math.radians(28)
    cam.location = (0, -6 * math.sin(tilt), 6 * math.cos(tilt))
    cam.rotation_euler = (tilt, 0, 0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def render_alpha(scene, mat, png, meta, out_png, size=SIZE):
    H = _load_height(png)
    tiled = meta.get("tile", "none") != "none"
    w_mm, h_mm = meta["size_mm"]
    if tiled:                       # бордюр: три повтора, видно, что стык бесшовный
        H = np.tile(H, (1, 3))
        w_mm *= 3
    s = 2.0 / max(w_mm, h_mm)       # длинная сторона = 2 единицы
    sx, sy = w_mm * s, h_mm * s
    nx = GRID if sx >= sy else int(GRID * sx / sy)
    ny = GRID if sy >= sx else int(GRID * sy / sx)
    if tiled:
        nx = int(GRID * 1.6)
        ny = int(nx * sy / sx)
    Hs = _bilinear(H, ny, nx)
    depth = meta["depth_mm"] * s * EXAGGERATE
    me = _plate_mesh(Hs, sx, sy, depth, base=0.06 if tiled else 0.1)
    me.materials.append(mat)
    ob = bpy.data.objects.new("_ga_plate", me)
    scene.collection.objects.link(ob)
    scene.camera.data.ortho_scale = max(sx, sy * 1.05) * 1.08
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.filepath = str(out_png)
    bpy.ops.render.render(write_still=True, scene=scene.name)
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    return out_png


def _set_preview(brush, png):
    img = bpy.data.images.load(str(png), check_existing=False)
    prev = brush.preview_ensure()
    prev.image_size = tuple(img.size)
    prev.image_pixels_float = list(img.pixels)
    bpy.data.images.remove(img)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    here = Path(__file__).resolve().parent
    root = Path(argv[0]).resolve() if argv else here.parent
    alphas = root / "alphas"
    blend = alphas / "GravenArc_Alphas.blend"
    if blend.exists():
        bpy.ops.wm.open_mainfile(filepath=str(blend))
    scene = setup_scene()
    mat = _silver()
    done = []
    for js in sorted((alphas / "maps").glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        png = js.with_suffix(".png")
        big = render_alpha(scene, mat, png, meta, alphas / "maps" / f"{meta['name']}_render.png", 512)
        # превью кисти 256 px: уменьшаем крупный рендер (меньше шума, чем отдельный рендер)
        img = bpy.data.images.load(str(big), check_existing=False)
        img.scale(256, 256)
        small = alphas / "maps" / f"{meta['name']}_preview.png"
        img.filepath_raw = str(small)
        img.file_format = 'PNG'
        img.save()
        bpy.data.images.remove(img)
        for b in bpy.data.brushes:
            g = b.get("gravenarc")
            if g and json.loads(g).get("name") == meta["name"]:
                _set_preview(b, small)
        done.append((meta["name"], meta.get("title", meta["name"])))
        print("[GravenArc] alpha preview", meta["name"])
    bpy.data.scenes.remove(scene)
    if blend.exists():
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=True)
        b1 = Path(str(blend) + "1")
        if b1.exists():
            b1.unlink()
    print("[GravenArc] готово:", done)


if __name__ == "__main__":
    main()

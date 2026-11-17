# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc: объёмные иконки кистей в стиле ZBrush/Blender.
# Для каждой кисти строится «глиняная» пластина с характерным мазком
# (выдавливание, прорезь, срез плоскостью, сглаживание, вытягивание…)
# и рендерится в Cycles. Картинка становится превью кисти-ассета.
#
# Запуск отдельно (перерисовать иконки в готовом файле кистей):
#   blender -b --factory-startup --python brush_icons.py -- [КОРЕНЬ_БИБЛИОТЕКИ]
# make_brushes.py вызывает его сам после сборки кистей.

import math
import os
import sys

import bpy
import numpy as np

SIZE = 256          # размер иконки, px
GRID = 200          # разрешение пластины
SAMPLES = 24

CLAY = (0.42, 0.12, 0.075)     # «красный воск», как MatCap Red Wax (линейные цвета)
MASK_COL = (0.10, 0.10, 0.11)


# ------------------------------------------------------------------ геометрия мазков

def _curve(pts, x):
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    return np.interp(np.clip(x, 0, 1), xs, ys)


def _path(n=240):
    t = np.linspace(-0.78, 0.78, n)
    return np.stack([t, 0.26 * np.sin(t * math.pi * 1.1)], axis=1)


def _dist_to_path(X, Y, path):
    P = np.stack([X.ravel(), Y.ravel()], axis=1)
    d = np.full(P.shape[0], 1e9)
    s = np.zeros(P.shape[0])        # знак: с какой стороны от линии
    along = np.zeros(P.shape[0])
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        ab = b - a
        L2 = ab @ ab
        u = np.clip(((P - a) @ ab) / L2, 0, 1)
        q = a + u[:, None] * ab
        di = np.linalg.norm(P - q, axis=1)
        m = di < d
        d[m] = di[m]
        cr = ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])
        s[m] = np.sign(cr[m])
        along[m] = (i + u[m]) / (len(path) - 1)
    return d.reshape(X.shape), s.reshape(X.shape), along.reshape(X.shape)


def _bumps(X, Y, seed=3, n=26, amp=0.05):
    rng = np.random.default_rng(seed)
    z = np.zeros_like(X)
    for _ in range(n):
        cx, cy = rng.uniform(-0.9, 0.9, 2)
        r = rng.uniform(0.08, 0.2)
        z += amp * rng.uniform(0.4, 1.0) * np.exp(-((X - cx) ** 2 + (Y - cy) ** 2) / (r * r))
    return z


def _blur(z, k=6):
    out = z.copy()
    for _ in range(k):
        out[1:-1, 1:-1] = (out[1:-1, 1:-1] * 4 + out[:-2, 1:-1] + out[2:, 1:-1] + out[1:-1, :-2] + out[1:-1, 2:]) / 8
    return out


def _square_to_disc(a, b, rad=1.0):
    """Концентрическое отображение Ширли–Чиу: квадрат -> круг без складок."""
    r = np.where(np.abs(a) > np.abs(b), a, b)
    with np.errstate(divide='ignore', invalid='ignore'):
        phi = np.where(np.abs(a) > np.abs(b), (math.pi / 4) * (b / a), (math.pi / 2) - (math.pi / 4) * (a / b))
    phi = np.nan_to_num(phi)
    return rad * r * np.cos(phi), rad * r * np.sin(phi)


def stroke_field(spec, curves):
    """Высоты пластины GRID×GRID и маска (0..1) для кисти."""
    n = GRID
    lin = np.linspace(-1, 1, n)
    A, B = np.meshgrid(lin, lin)
    X, Y = _square_to_disc(A, B, 0.985)                        # сетка, вписанная в круг (шар-иконка)
    base = np.zeros_like(X)
    z = base.copy()
    mask = np.zeros_like(X)
    path = _path()
    d, sgn, along = _dist_to_path(X, Y, path)
    kind = spec["sculpt_brush_type"]
    pts = curves[spec["curve"]]
    sub = spec.get("direction") == 'SUBTRACT'
    name = spec["name"]
    extra = []

    if kind in ('DRAW', 'CLAY', 'CLAY_STRIPS', 'INFLATE', 'LAYER'):
        R = {'DRAW': 0.13, 'CLAY': 0.16, 'CLAY_STRIPS': 0.15, 'INFLATE': 0.2, 'LAYER': 0.14}[kind]
        f = _curve(pts, d / R)
        h = {'DRAW': 0.09, 'CLAY': 0.07, 'CLAY_STRIPS': 0.08, 'INFLATE': 0.11, 'LAYER': 0.06}[kind]
        if kind == 'CLAY_STRIPS':  # квадратные «кирпичики» мазков
            f = np.minimum(1, f * 1.25) * (0.85 + 0.15 * (np.cos(along * 2 * math.pi * 9) > 0))
        if kind == 'LAYER':
            f = np.clip(f * 2.2, 0, 1)
        if kind == 'INFLATE':
            f = f ** 0.7
        z = z + h * f
    elif kind == 'BLOB':
        mm = spec.get("mm")
        r = 0.09 if mm else 0.13
        step = r * 2.3
        dist_total = 0
        centers = [path[0]]
        for i in range(1, len(path)):
            dist_total += np.linalg.norm(path[i] - path[i - 1])
            if dist_total >= step:
                centers.append(path[i])
                dist_total = 0
        for c in centers:
            dd = np.sqrt((X - c[0]) ** 2 + (Y - c[1]) ** 2) / r
            z = np.maximum(z, base + r * 0.95 * np.sqrt(np.clip(1 - dd ** 2, 0, 1)))
    elif kind == 'CREASE':      # Dam Standard: острая прорезь, края поджаты
        R = 0.12
        f = _curve(pts, d / R)
        z = z - 0.075 * f + 0.012 * np.exp(-((d - R * 0.55) / (R * 0.25)) ** 2)
    elif kind == 'DRAW_SHARP':  # тонкая риска / канавка
        mm = spec.get("mm")
        R = 0.05 if not mm else (0.045 if mm < 0.8 else 0.075)
        f = _curve(pts, d / R)
        z = z - (0.05 if not mm else 0.045) * f
    elif kind == 'PINCH':       # гребень, стянутый в острое ребро
        R = 0.2
        t = np.clip(1 - d / R, 0, 1)
        z = z + 0.08 * t ** 2.6
    elif kind == 'PLANE':
        bumpy = base + _bumps(X, Y, 3, 34, 0.06)
        R = 0.2
        f = np.clip(_curve(pts, d / R) * 1.4, 0, 1)
        band = d < R * 0.7
        level = float(np.median(bumpy[band]))
        if spec.get("plane_depth", 1.0) == 0.0:      # Trim: только срезать
            target = np.minimum(bumpy, level)
        elif spec.get("plane_height", 1.0) == 0.0:   # Fill: только заполнять
            target = np.maximum(bumpy, level + 0.01)
        else:
            target = np.full_like(bumpy, level)
        z = bumpy * (1 - f) + target * f
    elif kind == 'MULTIPLANE_SCRAPE':
        bumpy = base + _bumps(X, Y, 5, 30, 0.05)
        R = 0.22
        top = float(np.percentile(bumpy[d < R], 70))
        chisel = top - 0.55 * d
        f = np.clip(_curve(pts, d / R) * 1.5, 0, 1)
        z = np.where(d < R, np.minimum(bumpy, chisel) * f + bumpy * (1 - f), bumpy)
    elif kind == 'SMOOTH':
        bumpy = base + _bumps(X, Y, 7, 70, 0.045) + _bumps(X, Y, 11, 120, 0.012)
        smooth = _blur(bumpy, 40 if spec.get("smooth_deform_type") == 'SURFACE' else 25)
        R = 0.3
        f = np.clip(_curve(pts, d / R) * 1.6, 0, 1)
        z = bumpy * (1 - f) + _blur(base, 2) * f
    elif kind in ('GRAB', 'ELASTIC_DEFORM'):
        cx, cy = -0.15, 0.0
        sx = 0.5 if kind == 'ELASTIC_DEFORM' else 0.33
        # «язык» глины, вытянутый вправо-вверх
        u = (X - cx) * 0.8 + (Y - cy) * 0.6
        v = -(X - cx) * 0.6 + (Y - cy) * 0.8
        tongue = np.exp(-((u - 0.18) / (sx + 0.1)) ** 2 - (v / (0.22 + 0.12 * np.clip(-u, 0, 1))) ** 2)
        z = z + 0.32 * tongue * np.clip(0.6 + u, 0, 1.4)
        if spec.get("use_connected_only"):   # тянется только своя часть: чёткая граница
            z = np.where(X < -0.5, base + 0.02 * np.exp(-((Y) / 0.3) ** 2), z)
            z = z - 0.04 * np.exp(-((X + 0.5) / 0.02) ** 2)
    elif kind == 'SNAKE_HOOK':
        extra.append('horn')
    elif kind == 'NUDGE':
        R = 0.25
        f = _curve(pts, d / R)
        z = z + 0.05 * f * np.sin(along * math.pi * 10)
    elif kind == 'MASK':
        R = 0.14
        mask = np.clip(_curve(pts, d / R) * 1.6, 0, 1)
    if sub and kind == 'DRAW':
        z = 2 * base - z
    return X, Y, z, mask, extra


# ------------------------------------------------------------------ сцена и рендер

def _mesh_from_field(X, Y, Z, mask):
    """Поле высот -> передняя полусфера радиуса 1, смещённая по нормали."""
    n = X.shape[0]
    Zs = np.sqrt(np.clip(1 - X ** 2 - Y ** 2, 0, 1))
    N = np.stack([X, Y, Zs], axis=-1)
    edge = np.clip((0.985 - np.sqrt(X ** 2 + Y ** 2)) / 0.12, 0, 1)   # у силуэта мазок гаснет
    P = N * (1 + (Z * edge)[..., None])
    verts = P.reshape(-1, 3)
    idx = np.arange(n * n).reshape(n, n)
    a = idx[:-1, :-1].ravel()
    b = idx[:-1, 1:].ravel()
    c = idx[1:, 1:].ravel()
    d = idx[1:, :-1].ravel()
    faces = np.stack([a, b, c, d], axis=1)
    me = bpy.data.meshes.new("_ga_icon")
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.ravel())
    me.loops.add(len(faces) * 4)
    me.loops.foreach_set("vertex_index", faces.ravel())
    me.polygons.add(len(faces))
    me.polygons.foreach_set("loop_start", np.arange(0, len(faces) * 4, 4))
    me.polygons.foreach_set("loop_total", np.full(len(faces), 4))
    me.update()
    me.polygons.foreach_set("use_smooth", np.ones(len(faces), dtype=bool))
    col = me.color_attributes.new("ga_mask", 'FLOAT_COLOR', 'POINT')
    m = mask.ravel()
    rgba = np.empty((len(m), 4))
    for k in range(3):
        rgba[:, k] = CLAY[k] * (1 - m) + MASK_COL[k] * m
    rgba[:, 3] = 1
    col.data.foreach_set("color", rgba.ravel())
    me.update()
    return me


def _clay_material():
    mat = bpy.data.materials.get("_ga_clay") or bpy.data.materials.new("_ga_clay")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "ga_mask"
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.38
    try:
        bsdf.inputs["Specular IOR Level"].default_value = 0.6
        bsdf.inputs["Coat Weight"].default_value = 0.25
        bsdf.inputs["Coat Roughness"].default_value = 0.2
    except KeyError:
        pass
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _horn(bm_name="_ga_horn"):
    """Отросток для Snakehook: изогнутый сужающийся рог, растущий из шара."""
    import bmesh
    from mathutils import Vector
    bm = bmesh.new()
    rings = []
    steps, segs = 32, 20
    b = Vector((-0.25, -0.15, 0.0))
    b.z = math.sqrt(1 - b.x ** 2 - b.y ** 2) - 0.05
    n0 = Vector((b.x, b.y, b.z + 0.05)).normalized()
    prev = None
    for i in range(steps + 1):
        t = i / steps
        c = b + n0 * (0.75 * t) + Vector((0.75, 0.35, 0)) * (t ** 2) * 0.9
        r = 0.2 * (1 - t) ** 1.1 + 0.015
        tang = (n0 * 0.75 + Vector((0.75, 0.35, 0)) * 1.8 * t * 0.9).normalized()
        side = tang.cross(Vector((0, 0, 1)))
        if side.length < 1e-6:
            side = Vector((1, 0, 0))
        side.normalize()
        up = tang.cross(side).normalized()
        rings.append([bm.verts.new(c + (side * math.cos(a) + up * math.sin(a)) * r)
                      for a in (2 * math.pi * k / segs for k in range(segs))])
    for ra, rb in zip(rings, rings[1:]):
        for k in range(segs):
            bm.faces.new((ra[k], ra[(k + 1) % segs], rb[(k + 1) % segs], rb[k]))
    bm.faces.new(rings[-1])
    me = bpy.data.meshes.new(bm_name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    col = me.color_attributes.new("ga_mask", 'FLOAT_COLOR', 'POINT')
    col.data.foreach_set("color", [*CLAY, 1.0] * len(me.vertices))
    return me


def _mm_badge(scene):
    cu = bpy.data.curves.new("_ga_mm", 'FONT')
    cu.body = "mm"
    cu.size = 0.28
    cu.align_x = 'RIGHT'
    ob = bpy.data.objects.new("_ga_mm", cu)
    mat = bpy.data.materials.new("_ga_mm_mat")
    mat.use_nodes = True
    e = mat.node_tree.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (1, 1, 1, 1)
    e.inputs["Strength"].default_value = 1.5
    mat.node_tree.links.new(e.outputs[0], mat.node_tree.nodes["Material Output"].inputs["Surface"])
    cu.materials.append(mat)
    scene.collection.objects.link(ob)
    return ob


def setup_scene():
    scene = bpy.data.scenes.new("_ga_icons")
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new("_ga_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.6, 0.62, 0.68, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.45
    scene.world = world
    for name, rot, e in (("_ga_key", (0.62, -0.5, 0.3), 3.4), ("_ga_rim", (-0.9, 0.0, 3.4), 1.4)):
        ld = bpy.data.lights.new(name, 'SUN')
        ld.energy = e
        ld.angle = 0.25
        lo = bpy.data.objects.new(name, ld)
        lo.rotation_euler = rot
        scene.collection.objects.link(lo)
    cam_d = bpy.data.cameras.new("_ga_cam")
    cam_d.type = 'ORTHO'
    cam_d.ortho_scale = 2.32
    cam = bpy.data.objects.new("_ga_cam", cam_d)
    cam.location = (0.0, -1.6, 5.0)
    cam.rotation_euler = (math.atan2(1.6, 5.0), 0, 0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def render_icons(brush_specs, curves, out_dir=None):
    """Рендерит иконку для каждой кисти (по спецификации из make_brushes.BRUSHES),
    записывает её в превью кисти. Возвращает {имя: путь к png}."""
    scene = setup_scene()
    mat = _clay_material()
    tmp = bpy.app.tempdir or "/tmp"
    out_dir = out_dir or tmp
    os.makedirs(out_dir, exist_ok=True)
    result = {}
    for spec in brush_specs:
        X, Y, Z, mask, extra = stroke_field(spec, curves)
        me = _mesh_from_field(X, Y, Z, mask)
        me.materials.append(mat)
        ob = bpy.data.objects.new("_ga_tile", me)
        scene.collection.objects.link(ob)
        objs = [ob]
        if 'horn' in extra:
            hm = _horn()
            hm.materials.append(mat)
            ho = bpy.data.objects.new("_ga_horn", hm)
            scene.collection.objects.link(ho)
            objs.append(ho)
        badge = None
        if spec.get("mm"):
            badge = _mm_badge(scene)
            badge.location = (1.0, -0.95, 1.2)
            badge.rotation_euler = (math.atan2(1.6, 5.0), 0, 0)
            objs.append(badge)
        path = os.path.join(out_dir, "icon_" + spec["name"].replace(" ", "_").replace(".", "") + ".png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True, scene=scene.name)
        result[spec["name"]] = path
        br = bpy.data.brushes.get(spec["name"])
        if br is not None:
            img = bpy.data.images.load(path, check_existing=False)
            prev = br.preview_ensure()
            prev.image_size = (SIZE, SIZE)
            prev.image_pixels_float = list(img.pixels)
            bpy.data.images.remove(img)
        for o in objs:
            data = o.data
            bpy.data.objects.remove(o)
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)
        print("[GravenArc] icon", spec["name"])
    # чистка
    for o in list(scene.collection.objects):
        d = o.data
        bpy.data.objects.remove(o)
    bpy.data.scenes.remove(scene)
    for m in [m for m in bpy.data.materials if m.name.startswith("_ga_")]:
        bpy.data.materials.remove(m)
    for w in [w for w in bpy.data.worlds if w.name.startswith("_ga_")]:
        bpy.data.worlds.remove(w)
    for c in [c for c in bpy.data.cameras if c.name.startswith("_ga_")]:
        bpy.data.cameras.remove(c)
    for l in [l for l in bpy.data.lights if l.name.startswith("_ga_")]:
        bpy.data.lights.remove(l)
    return result


def contact_sheet(paths, names, out_png, cols=5, cell=256, label_h=34):
    """Лист-превью всех иконок с подписями (рендер через композитинг не нужен — рисуем numpy)."""
    rows = math.ceil(len(paths) / cols)
    W, H = cols * cell, rows * (cell + label_h)
    sheet = np.zeros((H, W, 4), dtype=np.float32)
    sheet[..., :3] = 0.16
    sheet[..., 3] = 1
    for i, (p, nm) in enumerate(zip(paths, names)):
        img = bpy.data.images.load(p, check_existing=False)
        px = np.array(img.pixels[:], dtype=np.float32).reshape(cell, cell, 4)
        bpy.data.images.remove(img)
        r, c = divmod(i, cols)
        y0 = H - (r + 1) * (cell + label_h) + label_h
        x0 = c * cell
        a = px[..., 3:4]
        sheet[y0:y0 + cell, x0:x0 + cell, :3] = px[..., :3] * a + sheet[y0:y0 + cell, x0:x0 + cell, :3] * (1 - a)
    img = bpy.data.images.new("_ga_sheet", W, H, alpha=False)
    img.pixels = sheet.ravel()
    img.filepath_raw = out_png
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import make_brushes as MB
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    root = os.path.abspath(argv[0]) if argv else os.path.abspath(os.path.join(here, ".."))
    blend = os.path.join(root, "brushes", MB.BLEND_NAME)
    bpy.ops.wm.open_mainfile(filepath=blend)
    res = render_icons(MB.BRUSHES, MB.CURVES, os.path.join(bpy.app.tempdir or "/tmp", "ga_icons"))
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True)
    print("[GravenArc] иконок:", len(res))


if __name__ == "__main__":
    main()

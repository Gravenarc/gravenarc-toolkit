# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc: общая «фотостудия» для превью ассетов и витринных рендеров.
# Тёмный студийный фон с градиентом (металлу есть что отражать), три софтбокса,
# AgX, шумодав, фирменные материалы: золото 750, серебро 925, бриллиант, красный воск.
#
#   import studio
#   scene = studio.new_scene(size=256)          # отдельная сцена, ничего не трогает
#   studio.render_ids(scene, items, out_dir)    # items: [(ID, [objects], look)]

import math
import os

import bpy
from mathutils import Vector

LOOKS = ("gold", "silver", "wax", "diamond", "keep")
DIRECTION = Vector((0.55, -1.0, 0.85))   # 3/4 сверху-спереди, как в каталогах украшений


# ------------------------------------------------------------------ материалы

def _principled(name):
    m = bpy.data.materials.get(name)
    if m:
        return m, None
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, m.node_tree.nodes.get("Principled BSDF")


def material(look):
    name = "_GA_Studio_" + look
    m, b = _principled(name)
    if b is None:
        return m
    if look == "gold":
        b.inputs["Base Color"].default_value = (1.0, 0.70, 0.30, 1)
        b.inputs["Metallic"].default_value = 1.0
        b.inputs["Roughness"].default_value = 0.14
        m.diffuse_color = (1.0, 0.70, 0.30, 1)
    elif look == "silver":
        b.inputs["Base Color"].default_value = (0.95, 0.94, 0.92, 1)
        b.inputs["Metallic"].default_value = 1.0
        b.inputs["Roughness"].default_value = 0.16
    elif look == "wax":
        b.inputs["Base Color"].default_value = (0.26, 0.028, 0.014, 1)
        b.inputs["Roughness"].default_value = 0.4
        b.inputs["Coat Weight"].default_value = 0.25
        b.inputs["Coat Roughness"].default_value = 0.2
        b.inputs["Subsurface Weight"].default_value = 0.08
        b.inputs["Subsurface Radius"].default_value = (0.6, 0.15, 0.08)
    elif look == "diamond":
        b.inputs["Base Color"].default_value = (1, 1, 1, 1)
        b.inputs["Roughness"].default_value = 0.0
        b.inputs["IOR"].default_value = 2.42
        b.inputs["Transmission Weight"].default_value = 1.0
    return m


def apply_look(ob, look):
    """Материал на уровне объекта (данные меша не трогаем)."""
    if look == "keep" or ob.type not in {'MESH', 'CURVE', 'FONT', 'SURFACE'}:
        return
    mat = material(look)
    if not ob.material_slots:            # у кривых без материала — своя копия данных
        ob.data = ob.data.copy()
        ob["_ga_tmpdata"] = True
        ob.data.materials.append(mat)
        return
    for s in ob.material_slots:
        s.link = 'OBJECT'
        s.material = mat


# ------------------------------------------------------------------ сцена

def _world():
    w = bpy.data.worlds.get("_GA_Studio") or bpy.data.worlds.new("_GA_Studio")
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    # Generated у мира = направление взгляда: пол тёмный, горизонт светлый, верх средний
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    cr = ramp.color_ramp
    cr.elements[0].position = 0.3
    cr.elements[0].color = (0.2, 0.195, 0.19, 1)
    cr.elements[1].position = 0.52
    cr.elements[1].color = (0.75, 0.74, 0.72, 1)
    e = cr.elements.new(0.8)
    e.color = (0.22, 0.22, 0.24, 1)
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.35
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return w


def new_scene(size=256, samples=64, transparent=True, name="_GA_Studio"):
    scene = bpy.data.scenes.new(name)
    us = scene.unit_settings
    us.system, us.scale_length, us.length_unit = 'METRIC', 0.001, 'MILLIMETERS'
    r = scene.render
    r.engine = 'CYCLES'
    r.resolution_x = r.resolution_y = size
    r.film_transparent = transparent
    c = scene.cycles
    c.device = 'CPU'
    c.samples = samples
    c.use_denoising = True
    c.max_bounces = 16
    c.transmission_bounces = 12
    c.glossy_bounces = 8
    c.transparent_max_bounces = 8
    c.caustics_reflective = c.caustics_refractive = False
    scene.view_settings.view_transform = 'AgX'
    try:
        scene.view_settings.look = 'AgX - Punchy'
    except TypeError:
        pass
    scene.world = _world()
    for nm, d, size_l, e in (("_GA_Key", (-0.6, -0.8, 0.9), 1.0, 1.0),
                             ("_GA_Fill", (1.0, -0.4, 0.35), 1.4, 0.35),
                             ("_GA_Top", (0.2, 0.7, 1.0), 0.8, 0.7)):
        ld = bpy.data.lights.new(nm, 'AREA')
        ld.shape = 'RECTANGLE'
        ld["ga_rel"] = (size_l, e)
        lo = bpy.data.objects.new(nm, ld)
        lo["ga_dir"] = d
        scene.collection.objects.link(lo)
    cam_d = bpy.data.cameras.new("_GA_Cam")
    cam_d.type = 'ORTHO'
    cam = bpy.data.objects.new("_GA_Cam", cam_d)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene


def frame(scene, objs, direction=DIRECTION, pad=1.12):
    """Камера и софтбоксы под габарит объектов (свет масштабируется вместе с размером)."""
    pts = []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    center = sum(pts, Vector()) / len(pts)
    d = direction.normalized()
    cam = scene.camera
    rot = (-d).to_track_quat('-Z', 'Y').to_matrix()
    cam.rotation_euler = rot.to_euler()
    inv = rot.inverted()
    pr = [inv @ (p - center) for p in pts]
    xs, ys, zs = [p.x for p in pr], [p.y for p in pr], [p.z for p in pr]
    sx, sy = max(xs) - min(xs), max(ys) - min(ys)
    center = center + rot @ Vector(((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, 0))
    aspect = scene.render.resolution_x / scene.render.resolution_y
    span = max(sx, sy * aspect, 1e-3)
    cam.data.ortho_scale = span * pad
    dist = (max(zs) - min(zs)) + span * 4 + 10
    cam.location = center + d * dist
    cam.data.clip_start = 0.01
    cam.data.clip_end = dist * 3
    R = max(sx, sy, max(zs) - min(zs)) * 0.5 + 1e-3
    for lo in scene.objects:
        if lo.type == 'LIGHT' and "ga_dir" in lo:
            ld = Vector(lo["ga_dir"]).normalized()
            lo.location = center + ld * R * 4
            lo.rotation_euler = (-ld).to_track_quat('-Z', 'Y').to_euler()
            s, e = lo.data["ga_rel"]
            lo.data.size = R * 3 * s
            lo.data.size_y = R * 2 * s
            lo.data.energy = e * 260 * (R * 4) ** 2 / 4    # постоянная освещённость при любом масштабе


def render_to(scene, path):
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True, scene=scene.name)
    return path


def set_preview(idb, png):
    img = bpy.data.images.load(png, check_existing=False)
    prev = idb.preview_ensure()
    prev.image_size = tuple(img.size)
    prev.image_pixels_float = list(img.pixels)
    bpy.data.images.remove(img)


def _proxy(scene, ob, look):
    """Копия объекта в студийной сцене (данные общие, модификаторы копируются)."""
    p = ob.copy()
    p.parent = None
    p.matrix_world = ob.matrix_world.copy()
    p.hide_render = False
    p.hide_viewport = False
    for c in list(p.users_collection):
        c.objects.unlink(p)
    scene.collection.objects.link(p)
    apply_look(p, look)
    return p


def render_ids(scene, items, out_dir, set_previews=True, direction=DIRECTION, pad=1.12):
    """items: [(ID для превью, [исходные объекты], look или {obj: look})]. Возвращает {имя: png}."""
    os.makedirs(out_dir, exist_ok=True)
    res = {}
    for idb, objs, look in items:
        proxies = []
        for o in objs:
            lk = look.get(o, "keep") if isinstance(look, dict) else look
            proxies.append(_proxy(scene, o, lk))
        frame(scene, proxies, direction, pad)
        png = os.path.join(out_dir, "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in idb.name) + ".png")
        try:
            render_to(scene, png)
            if set_previews:
                set_preview(idb, png)
            res[idb.name] = png
        except Exception as ex:   # превью необязательны
            print("[GravenArc] превью не получилось:", idb.name, ex)
        for p in proxies:
            tmp = p.data if p.get("_ga_tmpdata") else None
            bpy.data.objects.remove(p)
            if tmp is not None and tmp.users == 0:
                getattr(bpy.data, "meshes" if isinstance(tmp, bpy.types.Mesh) else "curves").remove(tmp)
    return res


def cleanup(scene):
    for o in list(scene.collection.objects):
        d = o.data
        bpy.data.objects.remove(o)
        if isinstance(d, (bpy.types.Light, bpy.types.Camera)):
            (bpy.data.lights if isinstance(d, bpy.types.Light) else bpy.data.cameras).remove(d)
    bpy.data.scenes.remove(scene)
    for m in [m for m in bpy.data.materials if m.name.startswith("_GA_Studio") and m.users == 0]:
        bpy.data.materials.remove(m)
    w = bpy.data.worlds.get("_GA_Studio")
    if w and w.users == 0:
        bpy.data.worlds.remove(w)

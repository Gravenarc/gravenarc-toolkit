# SPDX-License-Identifier: GPL-3.0-or-later
# Кольцо: шинка по размеру, ресайз, замер, обтекание вокруг кольца (Flow), гравировка текстом.
# Соглашение (как в шаблонах GravenArc): ось кольца — Z, верх кольца (место для касты) — +Y.
import math

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import core

PROFILES = [
    ('FLAT', "Плоская", "Прямоугольник со скруглёнными кромками"),
    ('HALFROUND', "Полукруглая (D)", "Плоская внутри, полукруглая снаружи"),
    ('COMFORT', "Комфорт", "Выпуклая и внутри, и снаружи — удобная посадка"),
    ('COURT', "Овальная (court)", "Мягкий овал"),
    ('KNIFE', "Нож (гребень)", "Снаружи грань-гребень по центру"),
]
_PROF = {  # p — показатель суперэллипса наружной стороны, e — толщина у кромки (доля t), ci — выпуклость внутри
    'FLAT': (10.0, 0.0, 0.0),
    'HALFROUND': (2.0, 0.25, 0.0),
    'COMFORT': (2.5, 0.35, 0.12),
    'COURT': (3.0, 0.30, 0.08),
    'KNIFE': (1.0, 0.30, 0.0),
}


def section(profile, w, t, draft_deg=2.0, m=24):
    """Сечение шинки: [(dr, z)], dr — от номинального внутреннего радиуса наружу."""
    p, e, ci = _PROF[profile]
    tg = math.tan(math.radians(draft_deg))
    us = [-math.cos(math.pi * k / (m - 1)) for k in range(m)]
    outer, inner = [], []
    for u in us:
        z = u * w / 2
        dr_out = e * t + (t - e * t) * max(0.0, 1 - abs(u) ** p) ** (1 / p) - abs(z) * tg
        dr_in = ci * t * u * u + abs(z) * tg
        dr_out = max(dr_out, dr_in + 0.05)
        outer.append((dr_out, z))
        inner.append((dr_in, z))
    return outer + inner[::-1][1:-1]


def build_shank_bm(d_in, profile='COMFORT', w_top=4.0, w_bot=2.5, t_top=1.8, t_bot=1.4,
                   taper=1.0, draft_deg=2.0, n=192, m=24):
    R = d_in / 2
    bm = bmesh.new()
    rings = []
    for i in range(n):
        phi = 2 * math.pi * i / n
        b = ((1 + math.cos(phi)) / 2) ** taper
        w = w_bot + (w_top - w_bot) * b
        t = t_bot + (t_top - t_bot) * b
        sec = section(profile, w, t, draft_deg, m)
        s, c = math.sin(phi), math.cos(phi)
        rings.append([bm.verts.new(((R + dr) * s, (R + dr) * c, z)) for dr, z in sec])
    k = len(rings[0])
    for i in range(n):
        a, b2 = rings[i], rings[(i + 1) % n]
        for j in range(k):
            bm.faces.new((a[j], a[(j + 1) % k], b2[(j + 1) % k], b2[j]))
    core.fix_normals(bm)
    return bm


# ---------------------------------------------------------------- замер и ресайз

def measure_inner_d(context, ob):
    """Внутренний Ø (мм) в самом узком месте: минимум радиуса вершин относительно оси Z объекта."""
    dg = context.evaluated_depsgraph_get()
    oe = ob.evaluated_get(dg)
    me = oe.to_mesh()
    k = core.mm_per_bu(context)
    sc = ob.matrix_world.to_scale()
    rmin = min((math.hypot(v.co.x * sc.x, v.co.y * sc.y) for v in me.vertices), default=0.0)
    oe.to_mesh_clear()
    return 2 * rmin * k


def resize_ring(context, ob, d_new, d_old=None):
    """Радиальный ресайз: все точки сдвигаются на ΔR — ширина и толщина шинки сохраняются
    (в отличие от масштаба S)."""
    k = core.mm_per_bu(context)
    if d_old is None:
        d_old = float(ob.get("gv_inner_d_mm", 0)) or measure_inner_d(context, ob)
    dR = (d_new - d_old) / 2 / k
    me = ob.data
    for v in me.vertices:
        r = math.hypot(v.co.x, v.co.y)
        if r > 1e-9:
            f = (r + dR) / r
            v.co.x *= f
            v.co.y *= f
    me.update()
    for ch in ob.children:  # касты/камни, привязанные к кольцу, едут радиально
        loc = ch.location
        r = math.hypot(loc.x, loc.y)
        if r > 1e-9:
            f = (r + dR) / r
            ch.location.x *= f
            ch.location.y *= f
    ob["gv_inner_d_mm"] = d_new
    ob["gv_size_ru"] = round(d_new * 2) / 2
    return d_old


# ---------------------------------------------------------------- обтекание (Flow) вокруг кольца

def slice_x(bm, step):
    """Нарезать сетку плоскостями x = const с шагом step, чтобы изгиб был гладким."""
    if step <= 0 or not bm.verts:
        return
    xs = [v.co.x for v in bm.verts]
    x0, x1 = min(xs), max(xs)
    x = x0 + step
    while x < x1:
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(x, 0, 0), plane_no=(1, 0, 0))
        x += step


def wrap_bm(bm, R, angle_deg=0.0, inward=False, mirror=False):
    """Плоский узор (XY, высота по Z, мм) -> на окружность радиуса R вокруг оси Z.
    x — дуга (без растяжения на радиусе R), y — вдоль оси кольца, z — по радиусу
    (наружу; при inward=True — внутрь, к пальцу)."""
    a0 = math.radians(angle_deg)
    for v in bm.verts:
        x, y, z = v.co
        if mirror:
            x = -x
        th = a0 + x / R
        r = R - z if inward else R + z
        v.co = Vector((r * math.sin(th), r * math.cos(th), y))
    core.fix_normals(bm)


def surface_radius(context, ring_ob, angle_deg, z_mm, inner=True):
    """Радиус поверхности кольца (мм) в направлении angle (0° = верх +Y) на высоте z.
    inner=True — внутренняя поверхность, иначе наружная."""
    bm = core.mesh_world_bm(context, ring_ob, apply_modifiers=False)  # без вырезов/гравировки
    inv = (Matrix.Scale(core.mm_per_bu(context), 4) @ ring_ob.matrix_world @
           Matrix.Scale(1 / core.mm_per_bu(context), 4)).inverted()
    bm.transform(inv)  # в локальные мм
    tree = BVHTree.FromBMesh(bm)
    a = math.radians(angle_deg)
    d = Vector((math.sin(a), math.cos(a), 0))
    if inner:
        hit = tree.ray_cast(Vector((0, 0, z_mm)), d, 1e4)
        r = hit[3] if hit[0] is not None else None
    else:
        hit = tree.ray_cast(Vector((0, 0, z_mm)) + d * 1e3, -d, 2e3)
        r = 1e3 - hit[3] if hit[0] is not None else None
    bm.free()
    if r is not None and r <= 0:
        r = None
    return r


def text_bm(context, text, size_mm, depth_mm, font_path="", spacing=1.0, z_from=0.0):
    """Текст -> сетка в мм: XY по центру, по Z от z_from до z_from + depth."""
    cu = bpy.data.curves.new("GV_Text_tmp", 'FONT')
    cu.body = text
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    cu.size = 1.0
    cu.space_character = spacing
    cu.extrude = 0.5
    if font_path:
        try:
            cu.font = bpy.data.fonts.load(bpy.path.abspath(font_path), check_existing=True)
        except Exception as ex:  # шрифт не найден — останется встроенный
            print("GravenArc: font load failed", ex)
    ob = bpy.data.objects.new("GV_Text_tmp", cu)
    context.scene.collection.objects.link(ob)
    dg = context.evaluated_depsgraph_get()
    oe = ob.evaluated_get(dg)
    me = oe.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    oe.to_mesh_clear()
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    if not bm.verts:
        return bm
    # высота заглавной ≈ 0.7 от size в Blender — нормируем по реальной высоте строки
    ys = [v.co.y for v in bm.verts]
    h = max(ys) - min(ys) or 1.0
    s = size_mm / h
    cx = (max(v.co.x for v in bm.verts) + min(v.co.x for v in bm.verts)) / 2
    cy = (max(ys) + min(ys)) / 2
    for v in bm.verts:
        v.co = Vector(((v.co.x - cx) * s, (v.co.y - cy) * s, z_from + (v.co.z + 0.5) * depth_mm))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    core.fix_normals(bm)
    return bm

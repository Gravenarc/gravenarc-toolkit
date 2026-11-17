# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc Blender Toolkit — генератор библиотеки шаблонов (Blender 5.2 LTS+).
#
# Запуск без интерфейса (создаёт и сохраняет .blend рядом со скриптом):
#   blender -b --factory-startup -P generate_templates.py
#   blender -b --factory-startup -P generate_templates.py -- --draft 1.5 --ring-sizes 15,16,17
#
# Запуск из Blender: вкладка Scripting -> Open -> Alt+P.
#   Шаблоны добавятся в текущую сцену (сохраните файл сами: Ctrl+S).
#
# Все размеры в миллиметрах (1 единица Blender = 1 мм, Unit Scale = 0.001).
# Литьё в песок (Delft clay): у литейных заготовок уклоны от плоскости разъёма,
# нет поднутрений, стенки/перемычки >= 0,5 мм; усадка — опция --apply-shrink.

import argparse
import json
import math
import os
import sys
import uuid

import bpy
import bmesh
from mathutils import Vector, noise
from mathutils.bvhtree import BVHTree
from mathutils.geometry import delaunay_2d_cdt

# ================================================================ параметры

DEFAULTS = dict(
    draft_deg=2.0,          # литейный уклон от плоскости разъёма, °
    shrink_pct=1.75,        # усадка металла, % (1,5–2 %)
    apply_shrink=False,     # True: литейные заготовки увеличиваются на 1/(1-усадка)
    min_wall=0.5,           # минимальная стенка/перемычка, мм
    ring_sizes="16,17,18,19,20",   # шинки (размер RU = внутренний Ø, мм)
    signet_sizes="18,20",          # печатки и кольца-основы
    pitch=0.45,             # шаг сетки плоских заготовок, мм
    previews=True,          # рендер превью ассетов (Cycles CPU, только в -b режиме)
    author="GravenArc",
    license="CC-BY-4.0",
)

CATALOG_ROOT = "GravenArc/Templates"
# ключ: (папка каталога, коллекция/название по-русски, литейная проверка)
CATALOGS = {
    "geometry":    ("Geometry",        "Геометрия",            False),
    "hardsurface": ("Hard Surface",    "Hard Surface",         False),
    "shanks":      ("Jewelry/Shanks",  "Шинки",                True),
    "rings":       ("Jewelry/Rings",   "Кольца",               True),
    "pendants":    ("Jewelry/Pendants", "Кулоны",              True),
    "settings":    ("Jewelry/Settings", "Касты",               True),
    "gems":        ("Jewelry/Gems",    "Камни-болванки",       False),
    "wire":        ("Jewelry/Wire",    "Проволока и скань",    False),
    "bases":       ("Sculpt Bases",    "Основы для лепки",     True),
    "characters":  ("Characters",      "Болванки персонажей",  False),
    "organic":     ("Organic",         "Органика",             False),
}
_NS = uuid.UUID("6a1f0c2e-9b7d-4c1e-8f3a-2d5b6e7c8a90")   # UUID каталогов стабильны


def catalog_uuid(path):
    return str(uuid.uuid5(_NS, path))


def catalog_path(key):
    return f"{CATALOG_ROOT}/{CATALOGS[key][0]}"


def ring_size_table(d):
    """Внутренний диаметр, мм -> RU (=Ø), EU (=длина окружности), US."""
    return dict(ru=d, eu=round(math.pi * d, 1), us=round((d - 11.63) / 0.8128, 2))


# ================================================================ сцена

def setup_scene(scene):
    us = scene.unit_settings
    us.system = 'METRIC'
    us.scale_length = 0.001
    us.length_unit = 'MILLIMETERS'
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.clip_start = 0.01
                    space.clip_end = 10000.0


def get_material(name, col, metallic=0.6, rough=0.4):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = col
    mat.roughness = rough
    mat.metallic = metallic
    if mat.node_tree:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = col
            bsdf.inputs["Roughness"].default_value = rough
            bsdf.inputs["Metallic"].default_value = metallic
    return mat


def get_collection(parent, name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        parent.children.link(col)
    return col


# ================================================================ 2D-утилиты

def spow(x, e):
    return math.copysign(abs(x) ** e, x)


def smoothstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def circ(t):
    """Четверть окружности 0->1 (скругление кромки)."""
    t = min(max(t, 0.0), 1.0)
    return math.sqrt(1.0 - (1.0 - t) ** 2)


def loop_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return a / 2


def ccw(pts):
    return list(pts) if loop_area(pts) > 0 else list(pts)[::-1]


def resample_loop(pts, step):
    n = len(pts)
    segs, total = [], 0.0
    for i in range(n):
        a, b = Vector(pts[i]), Vector(pts[(i + 1) % n])
        segs.append((a, b, (b - a).length))
        total += segs[-1][2]
    count = max(12, int(round(total / step)))
    out, acc, si = [], 0.0, 0
    for k in range(count):
        target = k * total / count
        while si < n - 1 and acc + segs[si][2] < target:
            acc += segs[si][2]
            si += 1
        a, b, L = segs[si]
        t = 0.0 if L == 0 else (target - acc) / L
        p = a.lerp(b, min(max(t, 0.0), 1.0))
        out.append((p.x, p.y))
    return out


def rounded_polygon(corners, radius, seg=10):
    n = len(corners)
    rs = radius if isinstance(radius, (list, tuple)) else [radius] * n
    out = []
    for i in range(n):
        p0, p1, p2 = Vector(corners[i - 1]), Vector(corners[i]), Vector(corners[(i + 1) % n])
        r = rs[i]
        if r <= 0:
            out.append((p1.x, p1.y))
            continue
        d1, d2 = (p0 - p1).normalized(), (p2 - p1).normalized()
        ang = math.acos(max(-1.0, min(1.0, d1.dot(d2))))
        tlen = min(r / math.tan(ang / 2), (p0 - p1).length * 0.49, (p2 - p1).length * 0.49)
        r = tlen * math.tan(ang / 2)
        a, b = p1 + d1 * tlen, p1 + d2 * tlen
        c = p1 + (d1 + d2).normalized() * (r / math.sin(ang / 2))
        a0 = math.atan2((a - c).y, (a - c).x)
        a1 = math.atan2((b - c).y, (b - c).x)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for k in range(seg + 1):
            t = a0 + da * k / seg
            out.append((c.x + r * math.cos(t), c.y + r * math.sin(t)))
    return out


def ellipse(rx, ry, n=96, cx=0.0, cy=0.0):
    return [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]


def stadium(cx, y0, y1, r, n=24):
    """Вертикальный «стадион» от y0 до y1 шириной 2r."""
    pts = [(cx + r * math.cos(math.pi * i / n), y1 + r * math.sin(math.pi * i / n)) for i in range(n + 1)]
    pts += [(cx - r * math.cos(math.pi * i / n), y0 - r * math.sin(math.pi * i / n)) for i in range(n + 1)]
    return ccw(pts)


def blunt_tip(pts, tip, cut=2.2, r=1.0):
    """Скругляет острый кончик контура (в песке острия не проливаются)."""
    tip = Vector(tip)
    keep = [p for p in pts if (Vector(p) - tip).length > cut]
    i = min(range(len(pts)), key=lambda k: (Vector(pts[k]) - tip).length)
    # вставляем вершину-кончик на место выкинутых точек
    j = next(k for k in range(len(keep)) if pts.index(keep[k]) > i) if any(pts.index(q) > i for q in keep) else len(keep)
    poly = keep[:j] + [tuple(tip)] + keep[j:]
    rs = [0.0] * len(poly)
    rs[j] = r
    return rounded_polygon(poly, rs, 12)


def point_in_poly(x, y, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi:
            inside = not inside
        j = i
    return inside


def dist_to_segs(x, y, segs):
    best = 1e18
    for ax, ay, bx, by in segs:
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        px, py = ax + t * dx - x, ay + t * dy - y
        d = px * px + py * py
        if d < best:
            best = d
    return math.sqrt(best)


def loop_segs(pts):
    n = len(pts)
    return [(pts[i][0], pts[i][1], pts[(i + 1) % n][0], pts[(i + 1) % n][1]) for i in range(n)]


# ================================================================ литьё

def apply_draft(bm, draft_deg, parting_z):
    """Литейный уклон: почти вертикальные поверхности сдвигаются внутрь
    пропорционально расстоянию от плоскости разъёма (отверстия — расширяются)."""
    if draft_deg <= 0:
        return
    tan_a = math.tan(math.radians(draft_deg))
    bm.normal_update()
    moves = []
    for v in bm.verts:
        nh = Vector((v.normal.x, v.normal.y, 0.0))
        L = nh.length
        if L > 1e-6:
            dirv = nh / L
            # «ровная» толщина на углах: каждая боковая грань получает полный уклон
            dots = [Vector((f.normal.x, f.normal.y, 0)).normalized().dot(dirv)
                    for f in v.link_faces if Vector((f.normal.x, f.normal.y)).length > 0.5]
            k = 1.0 / max(0.5, min(dots)) if dots else 1.0
            moves.append((v, -dirv * abs(v.co.z - parting_z) * tan_a * min(1.0, L * 2.0) * k))
    for v, m in moves:
        v.co += m
    bm.normal_update()


def shrink_factor(pct):
    return 1.0 / (1.0 - pct / 100.0)


def check_casting(me, draft_deg, parting_z, min_wall, two_sided=True):
    """(мин. стенка, мм; тонких граней; граней-поднутрений или None).
    Толщина — луч внутрь от каждой грани; поднутрение — грань выше разъёма,
    смотрящая вниз/вбок без уклона (и зеркально ниже разъёма)."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm)
    fverts = [frozenset(v.index for v in f.verts) for f in bm.faces]
    lim = math.sin(math.radians(draft_deg * 0.75))
    min_t, thin, under = 1e9, 0, 0
    for f in bm.faces:
        c, n = f.calc_center_median(), f.normal
        loc, hn, idx, dist = tree.ray_cast(c - n * 1e-4, -n, 100.0)
        if loc is not None and hn.dot(-n) > 0.2 and not (fverts[idx] & fverts[f.index]):
            min_t = min(min_t, dist)
            if dist < min_wall - 1e-3:
                thin += 1
        if draft_deg <= 0:
            continue
        zs = [v.co.z - parting_z for v in f.verts]
        if min(zs) < -1e-4 and max(zs) > 1e-4:
            continue                      # грань лежит на линии разъёма
        dz = c.z - parting_z
        if dz > 0.02 and n.z < lim:
            under += 1
        elif dz < -0.02 and (not two_sided or n.z > -lim):
            under += 1
    bm.free()
    return (round(min_t, 3) if min_t < 1e8 else None), thin, (under if draft_deg > 0 else None)


# ================================================================ построители мешей

def bm_ring_sweep(r_in, sec, n_around=128, n_sec=40, t_fn=None, w_fn=None, clamp_y=None):
    """Шинка вокруг оси Z: сечение — два полу-суперэллипса (внутр./наруж.).
    sec: t толщина, w ширина, ti доля внутренней половины, pi/po «квадратность»."""
    bm = bmesh.new()
    rows = []
    for i in range(n_around):
        th = 2 * math.pi * i / n_around
        t = t_fn(th) if t_fn else sec["t"]
        w = w_fn(th) if w_fn else sec["w"]
        ti, b = sec["ti"] * t, w / 2
        to = t - ti
        row = []
        for k in range(n_sec):
            ph = -math.pi / 2 + 2 * math.pi * k / n_sec
            c, s = math.cos(ph), math.sin(ph)
            p, h = (sec["po"], to) if c >= 0 else (sec["pi"], ti)
            u = ti + h * spow(c, 2 / p)
            v = b * spow(s, 2 / p)
            r = r_in + u
            x, y = r * math.cos(th), r * math.sin(th)
            if clamp_y is not None and y > clamp_y:
                y = clamp_y
            row.append(bm.verts.new((x, y, v)))
        rows.append(row)
    for i in range(n_around):
        a, b2 = rows[i], rows[(i + 1) % n_around]
        for k in range(n_sec):
            k2 = (k + 1) % n_sec
            bm.faces.new((a[k], b2[k], b2[k2], a[k2]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def bm_plate(regions, holes=(), pitch=0.45, two_sided=False, blend=0.8):
    """Плоская заготовка из 2D-контуров. regions = [(контур, z(d)), ...] —
    объединение; первый контур главный (например, тело кулона, затем ушко).
    d — расстояние до внешней кромки; спинка плоская (z=0) или зеркальная."""
    rloops = [ccw(resample_loop(o, pitch)) for o, _ in regions]
    hloops = [ccw(resample_loop(h, pitch)) for h in holes]
    loops = rloops + hloops
    all_segs = [s for lp in loops for s in loop_segs(lp)]
    pts, edges, base = [], [], 0
    for lp in loops:
        pts += lp
        edges += [(base + i, base + (i + 1) % len(lp)) for i in range(len(lp))]
        base += len(lp)

    def inside(x, y):
        return any(point_in_poly(x, y, lp) for lp in rloops) and not any(point_in_poly(x, y, h) for h in hloops)

    xs = [p[0] for lp in rloops for p in lp]
    ys = [p[1] for lp in rloops for p in lp]
    y, row = min(ys) + pitch * 0.5, 0
    while y < max(ys):
        x = min(xs) + pitch * (0.5 + 0.5 * (row % 2))
        while x < max(xs):
            if inside(x, y) and dist_to_segs(x, y, all_segs) > pitch * 0.55:
                pts.append((x, y))
            x += pitch
        y += pitch * 0.866
        row += 1
    vco, _, faces, *_ = delaunay_2d_cdt([Vector(p) for p in pts], edges, [], 0, 1e-6, False)
    tris = []
    for f in faces:
        P = [(vco[i].x, vco[i].y) for i in f]
        cx, cy = sum(p[0] for p in P) / 3, sum(p[1] for p in P) / 3
        if inside(cx, cy):
            tris.append(tuple(f) if loop_area(P) > 0 else (f[2], f[1], f[0]))
    ecount = {}
    for a, b, c in tris:
        for e in ((a, b), (b, c), (c, a)):
            k = tuple(sorted(e))
            ecount[k] = ecount.get(k, 0) + 1
    bnd = [k for k, n in ecount.items() if n == 1]
    bsegs = [(vco[a].x, vco[a].y, vco[b].x, vco[b].y) for a, b in bnd]
    bverts = {i for e in bnd for i in e}
    signed = [(lp, loop_segs(lp)) for lp in rloops]

    def height(x, y, d):
        z = regions[-1][1](d)
        for (lp, segs), (_, zf) in list(zip(signed, regions))[-2::-1]:
            sd = dist_to_segs(x, y, segs) * (1 if point_in_poly(x, y, lp) else -1)
            w = smoothstep(-blend, blend, sd)
            z = z * (1 - w) + zf(d) * w
        return z

    bm = bmesh.new()
    top, bot, mid = {}, {}, {}
    for i, p in enumerate(vco):
        d = 0.0 if i in bverts else dist_to_segs(p.x, p.y, bsegs)
        z = height(p.x, p.y, d)
        top[i] = bm.verts.new((p.x, p.y, z))
        bot[i] = bm.verts.new((p.x, p.y, -z if two_sided else 0.0))
        if two_sided and i in bverts:
            mid[i] = bm.verts.new((p.x, p.y, 0.0))
    for a, b, c in tris:
        bm.faces.new((top[a], top[b], top[c]))
        bm.faces.new((bot[c], bot[b], bot[a]))
    for a, b in bnd:
        if two_sided:
            bm.faces.new((top[a], top[b], mid[b], mid[a]))
            bm.faces.new((mid[a], mid[b], bot[b], bot[a]))
        else:
            bm.faces.new((top[a], top[b], bot[b], bot[a]))
    for v in [v for v in bm.verts if not v.link_faces]:
        bm.verts.remove(v)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def bm_revolve(profile, segs=96, closed=True):
    """Тело вращения вокруг Z. profile — [(r, z)]; closed=True — замкнутое
    сечение (трубка/каста); False — открытый профиль от оси до оси."""
    bm = bmesh.new()
    rings = []
    for (r, z) in profile:
        if r < 1e-6:
            rings.append([bm.verts.new((0, 0, z))])
        else:
            rings.append([bm.verts.new((r * math.cos(2 * math.pi * i / segs), r * math.sin(2 * math.pi * i / segs), z))
                          for i in range(segs)])
    pairs = list(zip(rings, rings[1:] + ([rings[0]] if closed else [])))
    for A, B in pairs:
        for i in range(segs):
            j = (i + 1) % segs
            if len(A) == 1:
                bm.faces.new((A[0], B[j], B[i]))
            elif len(B) == 1:
                bm.faces.new((A[i], A[j], B[0]))
            else:
                bm.faces.new((A[i], A[j], B[j], B[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def bm_quad_sphere(radius, cuts=12, scale=(1, 1, 1)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    for v in bm.verts:
        p = Vector([math.tan(c * math.pi / 4) for c in v.co]).normalized() * radius
        v.co = Vector((p.x * scale[0], p.y * scale[1], p.z * scale[2]))
    return bm


def bm_box_lattice(xs, ys, zs):
    """Коробка с заданными линиями сетки (опорные рёбра для Subdivision)."""
    bm = bmesh.new()
    cache = {}

    def V(x, y, z):
        k = (round(x, 5), round(y, 5), round(z, 5))
        if k not in cache:
            cache[k] = bm.verts.new(k)
        return cache[k]

    for axis in range(3):
        L = [xs, ys, zs]
        a, b = [L[i] for i in range(3) if i != axis]
        for side in (L[axis][0], L[axis][-1]):
            for i in range(len(a) - 1):
                for j in range(len(b) - 1):
                    q = []
                    for (u, v) in ((a[i], b[j]), (a[i + 1], b[j]), (a[i + 1], b[j + 1]), (a[i], b[j + 1])):
                        c = [0, 0, 0]
                        c[axis] = side
                        idx = [k for k in range(3) if k != axis]
                        c[idx[0]], c[idx[1]] = u, v
                        q.append(V(*c))
                    bm.faces.new(q)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def support_lines(size, s, cuts=0):
    h = size / 2
    inner = [(-h + s) + (size - 2 * s) * i / (cuts + 1) for i in range(cuts + 2)]
    return [-h] + inner + [h]


def bm_rounded_box(sx, sy, sz, r, seg=3):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts[:])
    bmesh.ops.bevel(bm, geom=bm.edges[:] + bm.verts[:], offset=r, offset_type='OFFSET',
                    segments=seg, profile=0.5, affect='EDGES', clamp_overlap=True)
    return bm


def bm_hull(points, dissolve=True):
    bm = bmesh.new()
    for p in points:
        bm.verts.new(p)
    bmesh.ops.convex_hull(bm, input=bm.verts[:])
    for v in [v for v in bm.verts if not v.link_faces]:
        bm.verts.remove(v)
    if dissolve:
        bmesh.ops.dissolve_limit(bm, angle_limit=0.001, verts=bm.verts[:], edges=bm.edges[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def bm_tube(path, radii, segs=24, cap_start=True, cap_end=True):
    """Трубка по ломаной с переменным радиусом (параллельный перенос рамок).
    Радиус 0 на конце — острый кончик."""
    path = [Vector(p) for p in path]
    n = len(path)
    tangents = []
    for i in range(n):
        t = (path[min(i + 1, n - 1)] - path[max(i - 1, 0)]).normalized()
        tangents.append(t)
    up = Vector((0, 0, 1)) if abs(tangents[0].z) < 0.9 else Vector((1, 0, 0))
    nrm = tangents[0].cross(up).normalized()
    bm = bmesh.new()
    rings = []
    for i in range(n):
        if i > 0:
            nrm = (nrm - tangents[i] * nrm.dot(tangents[i])).normalized()
        bnm = tangents[i].cross(nrm)
        r = radii[i]
        if r < 1e-6:
            rings.append([bm.verts.new(path[i])])
            continue
        rings.append([bm.verts.new(path[i] + (nrm * math.cos(2 * math.pi * k / segs) +
                                              bnm * math.sin(2 * math.pi * k / segs)) * r) for k in range(segs)])
    for A, B in zip(rings, rings[1:]):
        for k in range(segs):
            j = (k + 1) % segs
            if len(B) == 1:
                bm.faces.new((A[k], A[j], B[0]))
            elif len(A) == 1:
                bm.faces.new((A[0], B[j], B[k]))
            else:
                bm.faces.new((A[k], A[j], B[j], B[k]))
    for ring, flag, p in ((rings[0], cap_start, path[0]), (rings[-1], cap_end, path[-1])):
        if flag and len(ring) > 1:
            c = bm.verts.new(p)
            for k in range(segs):
                bm.faces.new((ring[k], ring[(k + 1) % segs], c))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def bm_from_modifiers(nodes, edges, radii=None, mods=(), faces=()):
    """Меш из скелета (Skin) и/или модификаторов — с применением."""
    me = bpy.data.meshes.new("_tmp")
    me.from_pydata(nodes, edges, list(faces))
    o = bpy.data.objects.new("_tmp", me)
    bpy.context.scene.collection.objects.link(o)
    for kind, opts in mods:
        m = o.modifiers.new(kind, kind)
        for k, v in opts.items():
            setattr(m, k, v)
        if kind == 'SKIN' and radii:
            data = me.skin_vertices[0].data
            for i, r in enumerate(radii):
                data[i].radius = r
            data[0].use_root = True
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    bm = bmesh.new()
    bm.from_mesh(ev.to_mesh())
    ev.to_mesh_clear()
    bpy.data.objects.remove(o)
    bpy.data.meshes.remove(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def skin(nodes, edges, radii, levels=2):
    return bm_from_modifiers(nodes, edges, radii, mods=(("SKIN", {}), ("SUBSURF", dict(levels=levels))))


# ================================================================ библиотека

class Library:
    def __init__(self, cfg, root_col):
        self.cfg = cfg
        self.root = root_col
        self.mat = get_material("GV_Template", (0.62, 0.66, 0.72, 1.0), metallic=0.25, rough=0.45)
        self.mat_gem = get_material("GV_Gem", (0.75, 0.88, 1.0, 1.0), metallic=0.0, rough=0.05)
        self.report = []
        self.xcur = {}

    def _place(self, key, obj):
        w = obj.dimensions.x
        x = self.xcur.get(key, 0.0)
        self.xcur[key] = x + w + 8.0
        row = list(CATALOGS).index(key)
        obj.location = (x + w / 2, -row * 70.0, 0.0)

    def add(self, key, name, bm, desc, tags, parting_z=0.0, two_sided=True, props=None,
            smooth=True, modifiers=(), mat=None, cast=None):
        cfg = self.cfg
        cast = CATALOGS[key][2] if cast is None else cast
        if cast:
            apply_draft(bm, cfg.draft_deg, parting_z)
            if cfg.apply_shrink:
                k = shrink_factor(cfg.shrink_pct)
                bmesh.ops.scale(bm, vec=(k, k, k), verts=bm.verts[:])
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        bm.free()
        return self._finish(key, name, me, desc, tags, parting_z, two_sided, props, smooth, modifiers, mat, cast)

    def add_curve(self, key, name, curve, desc, tags, props=None):
        return self._finish(key, name, curve, desc, tags, 0.0, True, props, False, (), None, False)

    def _finish(self, key, name, data, desc, tags, parting_z, two_sided, props, smooth, modifiers, mat, cast):
        cfg = self.cfg
        is_mesh = isinstance(data, bpy.types.Mesh)
        if is_mesh and smooth:
            data.shade_smooth()
        data.materials.append(mat or self.mat)
        obj = bpy.data.objects.new(name, data)
        get_collection(self.root, CATALOGS[key][1]).objects.link(obj)
        for kind, opts in modifiers:
            m = obj.modifiers.new(kind, kind)
            for k, v in opts.items():
                setattr(m, k, v)
        self._place(key, obj)

        obj["gv_category"] = CATALOGS[key][1]
        if cast:
            obj["gv_parting_z_mm"] = parting_z
            obj["gv_draft_deg"] = cfg.draft_deg
            obj["gv_shrink_applied_pct"] = cfg.shrink_pct if cfg.apply_shrink else 0.0
        for k, v in (props or {}).items():
            obj[k] = v

        mw = thin = under = None
        if is_mesh and not modifiers:
            mw, thin, under = check_casting(data, cfg.draft_deg if cast else 0.0, parting_z, cfg.min_wall, two_sided)
            if mw is not None:
                obj["gv_min_wall_mm"] = mw
            if cast:
                obj["gv_undercut_faces"] = under or 0

        obj.asset_mark()
        ad = obj.asset_data
        ad.catalog_id = catalog_uuid(catalog_path(key))
        ad.description = desc
        ad.author = cfg.author
        try:
            ad.license = cfg.license
        except AttributeError:
            pass
        for t in list(tags) + ["GravenArc", "мм"]:
            ad.tags.new(t, skip_if_exists=True)
        self.report.append(dict(name=name, category=CATALOGS[key][1], cast=cast,
                                dims_mm=[round(d, 2) for d in obj.dimensions],
                                min_wall_mm=mw, thin_faces=thin if cast else None, undercut_faces=under))
        return obj


# ================================================================ Геометрия

def build_geometry(lib):
    k = "geometry"
    phi = (1 + 5 ** 0.5) / 2

    def norm(pts, R):
        return [Vector(p).normalized() * R for p in pts]

    lib.add(k, "Geo_Cube_10", bm_rounded_box(10, 10, 10, 0.3), "Куб 10×10×10 мм, кромки R0,3. Ориентир размера.", ["куб"], smooth=False)
    lib.add(k, "Geo_Sphere_D10", bm_quad_sphere(5.0, 12), "Сфера Ø10 мм, квадратная топология (без полюсов).", ["сфера"])
    lib.add(k, "Geo_Cylinder_D10x10", bm_revolve([(0, 0), (5, 0), (5, 10), (0, 10)], 64, closed=False),
            "Цилиндр Ø10 × 10 мм.", ["цилиндр"], smooth=False)
    lib.add(k, "Geo_Cone_D10x10", bm_revolve([(0, 0), (5, 0), (0, 10)], 64, closed=False),
            "Конус Ø10, высота 10 мм.", ["конус"], smooth=False)
    lib.add(k, "Geo_Torus_D12x2", bm_revolve([(5 + math.cos(a * math.pi / 16), math.sin(a * math.pi / 16)) for a in range(32)], 96),
            "Тор: наружный Ø12, сечение Ø2.", ["тор"])
    lib.add(k, "Geo_Tetrahedron_R5", bm_hull(norm([(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)], 5)),
            "Тетраэдр, радиус описанной сферы 5 мм.", ["многогранник", "тетраэдр"], smooth=False)
    lib.add(k, "Geo_Octahedron_R5", bm_hull(norm([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)], 5)),
            "Октаэдр, радиус 5 мм (вершина вверх).", ["многогранник", "октаэдр"], smooth=False)
    ico = [(0, s1, s2 * phi) for s1 in (-1, 1) for s2 in (-1, 1)]
    ico = ico + [(b, c, a) for a, b, c in ico] + [(c, a, b) for a, b, c in ico]
    lib.add(k, "Geo_Icosahedron_R5", bm_hull(norm(ico, 5)), "Икосаэдр, радиус 5 мм.", ["многогранник", "икосаэдр"], smooth=False)
    dod = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    for s1 in (-1, 1):
        for s2 in (-1, 1):
            dod += [(0, s1 / phi, s2 * phi), (s1 / phi, s2 * phi, 0), (s2 * phi, 0, s1 / phi)]
    lib.add(k, "Geo_Dodecahedron_R5", bm_hull(norm(dod, 5)), "Додекаэдр, радиус 5 мм.", ["многогранник", "додекаэдр"], smooth=False)
    lib.add(k, "Geo_HexPrism_10x5", bm_revolve([(0, 0), (5, 0), (5, 5), (0, 5)], 6, closed=False),
            "Шестигранная призма 10 мм (по углам) × 5 мм.", ["призма", "шестигранник"], smooth=False)
    lib.add(k, "Geo_Pyramid_10x8", bm_hull([(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0), (0, 0, 8)]),
            "Пирамида: основание 10×10, высота 8 мм.", ["пирамида"], smooth=False)
    lib.add(k, "Geo_Hemisphere_D10", bm_revolve([(0, 0)] + [(5 * math.cos(a * math.pi / 32), 5 * math.sin(a * math.pi / 32)) for a in range(17)], 64, closed=False),
            "Полусфера Ø10 мм, плоское основание.", ["полусфера"])


# ================================================================ Hard Surface

def build_hardsurface(lib):
    k = "hardsurface"
    sub = (("SUBSURF", dict(levels=2, render_levels=3)),)
    lib.add(k, "HS_Cube_Support_10", bm_box_lattice(support_lines(10, 0.4, 2), support_lines(10, 0.4, 2), support_lines(10, 0.4, 2)),
            "Куб 10 мм с опорными рёбрами 0,4 мм + Subdivision: чёткие скруглённые кромки.", ["куб", "subd"],
            modifiers=sub)
    lib.add(k, "HS_Panel_Support_20x12x2", bm_box_lattice(support_lines(20, 0.3, 3), support_lines(12, 0.3, 2), support_lines(2, 0.2)),
            "Пластина 20×12×2 с опорными рёбрами + Subdivision.", ["пластина", "subd"], modifiers=sub)
    prof = [(0, 0), (4.6, 0), (4.85, 0), (5, 0.15), (5, 0.4), (5, 9.6), (5, 9.85), (4.85, 10), (4.6, 10), (0, 10)]
    lib.add(k, "HS_Cylinder_Support_D10x10", bm_revolve(prof, 32, closed=False),
            "Цилиндр Ø10×10 с опорными рёбрами у торцов + Subdivision.", ["цилиндр", "subd"], modifiers=sub)
    tube = [(3.0, 0), (5, 0), (5, 10), (3.0, 10)]
    lib.add(k, "HS_Tube_D10_Wall2", bm_revolve(tube, 64), "Труба Ø10, стенка 2, длина 10 мм.", ["труба"], smooth=False,
            modifiers=(("BEVEL", dict(width=0.2, segments=2, limit_method='ANGLE')),))
    caps = bm_quad_sphere(2.5, 10)
    for v in caps.verts:
        v.co.z += 5 if v.co.z > 1e-6 else (-5 if v.co.z < -1e-6 else 0)
    lib.add(k, "HS_Capsule_D5x15", caps, "Капсула Ø5 × 15 мм.", ["капсула"])
    # шестерня
    teeth, ro, rr = 16, 10.0, 8.6
    gear = []
    for i in range(teeth):
        a0 = 2 * math.pi * i / teeth
        da = 2 * math.pi / teeth
        for f, r in ((0.0, rr), (0.18, rr), (0.30, ro), (0.62, ro), (0.74, rr)):
            gear.append((r * math.cos(a0 + f * da), r * math.sin(a0 + f * da)))
    zg = lambda d: 0.9 + 0.25 * circ(d / 0.25)
    lib.add(k, "HS_Gear_16T_D20", bm_plate([(gear, zg)], [ellipse(2.5, 2.5, 48)] + [ellipse(1.6, 1.6, 32, 5.2 * math.cos(a * math.pi / 2), 5.2 * math.sin(a * math.pi / 2)) for a in range(4)],
                                           pitch=0.35, two_sided=True),
            "Шестерёнка 16 зубьев, Ø20, толщина 2,3 мм, ось Ø5 и 4 окна — стимпанк/механика.", ["шестерня", "стимпанк"], smooth=False)
    hexo = [(6 * math.cos(a * math.pi / 3 + math.pi / 6), 6 * math.sin(a * math.pi / 3 + math.pi / 6)) for a in range(6)]
    lib.add(k, "HS_HexNut_M6", bm_plate([(rounded_polygon(hexo, 0.4, 4), lambda d: 1.8 + 0.4 * circ(d / 0.4))], [ellipse(3, 3, 48)], 0.3, two_sided=True),
            "Гайка-шестигранник 12 мм под ключ, отверстие Ø6, высота 4,4 мм.", ["гайка"], smooth=False)
    lib.add(k, "HS_Bevel_Box_10x6x4", bm_rounded_box(10, 6, 4, 0.6, 4), "Брусок 10×6×4 с фаской-скруглением R0,6.", ["брусок"])


# ================================================================ Шинки и кольца

SHANK_PROFILES = {
    "Flat":      dict(ru="Плоская",     t=1.6, w=4.0, ti=0.5,  pi=6.0, po=6.0),
    "HalfRound": dict(ru="Полукруглая", t=1.8, w=3.0, ti=0.18, pi=8.0, po=2.0),
    "Comfort":   dict(ru="Комфорт",     t=1.8, w=4.0, ti=0.25, pi=2.2, po=4.0),
    "Court":     dict(ru="Овальная",    t=1.8, w=3.5, ti=0.35, pi=2.0, po=2.0),
}


def build_shanks(lib):
    for size in lib.cfg.ring_size_list:
        st = ring_size_table(size)
        for key, p in SHANK_PROFILES.items():
            lib.add("shanks", f"Shank_{key}_RU{size:g}", bm_ring_sweep(size / 2, p),
                    f"Шинка «{p['ru']}», размер {size:g} (Ø внутр. {size:g} мм; EU {st['eu']}, US {st['us']}). "
                    f"Ширина {p['w']} мм, толщина {p['t']} мм. Ось Z, разъём по середине ширины.",
                    ["шинка", p["ru"].lower(), f"размер {size:g}"],
                    props=dict(gv_size_ru=size, gv_inner_d_mm=size, gv_profile=p["ru"]))


def _top_falloff(th, v0, v1, spread):
    d = abs((th - math.pi / 2 + math.pi) % (2 * math.pi) - math.pi)
    return v0 + (v1 - v0) * math.cos(min(d / spread, 1.0) * math.pi / 2) ** 2


def build_rings(lib):
    variants = [
        ("Signet_Oval", "Печатка овальная: площадка ~11×9 мм под гравировку/рельеф.",
         dict(t=1.8, w=3.0, ti=0.3, pi=2.2, po=3.0), (1.8, 4.0, 1.25), (3.0, 11.0, 1.0), 3.3, ["печатка"]),
        ("Signet_Round", "Печатка с круглой площадкой ~10 мм.",
         dict(t=1.8, w=3.0, ti=0.3, pi=2.2, po=4.0), (1.8, 4.2, 1.0), (3.0, 12.0, 0.75), 3.6, ["печатка"]),
        ("SculptBase", "Массивная основа-перстень под лепку: утолщение сверху до 5 мм, ширина до 9 мм.",
         dict(t=1.8, w=3.5, ti=0.3, pi=2.2, po=2.0), (1.8, 5.0, 1.6), (3.5, 9.0, 1.7), None, ["основа", "лепка"]),
        ("TopPad", "Тонкая шинка с плоской площадкой ~8 мм — под накладку, касту или рельеф.",
         dict(t=1.5, w=2.2, ti=0.3, pi=2.2, po=3.0), (1.5, 3.0, 0.6), (2.2, 8.0, 0.55), 2.8, ["площадка"]),
    ]
    for size in lib.cfg.signet_size_list:
        st = ring_size_table(size)
        r_in = size / 2
        for name, desc, sec, tp, wp, clamp, tags in variants:
            bm = bm_ring_sweep(r_in, sec, n_around=192,
                               t_fn=lambda th, tp=tp: _top_falloff(th, *tp),
                               w_fn=lambda th, wp=wp: _top_falloff(th, *wp),
                               clamp_y=(r_in + clamp) if clamp else None)
            lib.add("rings", f"Ring_{name}_RU{size:g}", bm,
                    f"{desc} Размер {size:g} (EU {st['eu']}, US {st['us']}). Ось Z, верх кольца — в +Y.",
                    ["кольцо", f"размер {size:g}"] + tags, props=dict(gv_size_ru=size, gv_inner_d_mm=size))


# ================================================================ Кулоны

def build_pendants(lib):
    P = lib.cfg.pitch

    def pillow(h_side, h_top, R):
        return lambda d: h_side + h_top * circ(d / R)

    def medallion(h_side=0.8, rim_top=2.2, rr=0.8, rw=2.0, floor=1.3):
        def z(d):
            zr = h_side + (rim_top - h_side) * circ(d / rr)
            s = smoothstep(rw - 0.45, rw + 0.45, d)
            return zr * (1 - s) + floor * s
        return z

    drop = [(8.0 * math.sin(t) * math.sin(t / 2), 13.0 * math.cos(t)) for t in (2 * math.pi * i / 160 for i in range(160))]
    drop = blunt_tip(drop, (0.0, 13.0), cut=2.5, r=1.2)
    cross = rounded_polygon([(-3, 13), (3, 13), (2.2, 3.2), (11, 4), (11, -2), (2.2, -1.2), (3.2, -15),
                             (-3.2, -15), (-2.2, -1.2), (-11, -2), (-11, 4), (-2.2, 3.2)],
                            [1.2, 1.2, 0.6, 1.2, 1.2, 0.6, 1.2, 1.2, 0.6, 1.2, 1.2, 0.6], 8)
    shield = rounded_polygon([(-9, 12), (9, 12), (9, -2), (0, -14), (-9, -2)], [1.5, 1.5, 3.0, 1.5, 3.0], 12)
    rect = rounded_polygon([(-9, -13), (9, -13), (9, 13), (-9, 13)], 3.0, 12)
    rhomb = rounded_polygon([(0, -14), (9, 0), (0, 14), (-9, 0)], 1.5, 10)
    heart = [(16 * math.sin(t) ** 3 * 0.62, (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) * 0.62)
             for t in (2 * math.pi * i / 200 for i in range(200))]
    heart = blunt_tip(heart, min(heart, key=lambda p: p[1]), cut=2.2, r=1.0)
    octa = rounded_polygon([(11 * math.cos(a * math.pi / 4 + math.pi / 8), 11 * math.sin(a * math.pi / 4 + math.pi / 8)) for a in range(8)], 1.0, 6)

    items = [
        ("Circle_D20", ellipse(10, 10, 160), pillow(1.0, 1.2, 4.0), False, "Круглый Ø20, мягкий купол.", ["круг"]),
        ("Oval_18x24", ellipse(9, 12, 160), pillow(1.0, 1.4, 5.0), False, "Овал 18×24, купол.", ["овал"]),
        ("Drop_16x26", drop, pillow(1.0, 1.4, 4.5), False, "Капля 16×26, острие к ушку.", ["капля"]),
        ("Heart_20x18", heart, pillow(1.0, 1.4, 4.5), False, "Сердце ~20×18, купол; ушко между «половинками».", ["сердце"]),
        ("Shield_18x26", shield, pillow(1.2, 0.6, 0.9), False, "Щит 18×26, плоский верх — под гравировку/рельеф.", ["щит", "гравировка"]),
        ("Rect_18x26", rect, pillow(1.2, 0.6, 0.9), False, "Прямоугольник 18×26 R3, плоский верх — под гравировку.", ["прямоугольник", "гравировка"]),
        ("Rhomb_18x28", rhomb, pillow(1.0, 1.2, 4.0), False, "Ромб 18×28, купол.", ["ромб"]),
        ("Octagon_D22", octa, pillow(1.2, 0.6, 0.9), False, "Восьмиугольник 22 мм, плоский верх — под орнамент.", ["восьмиугольник"]),
        ("Cross_22x28", cross, pillow(1.0, 0.8, 1.5), False, "Крест с расширенными концами 22×28 — основа под армянский орнамент.", ["крест", "армянский"]),
        ("Medallion_D24", ellipse(12, 12, 192), medallion(), False, "Медальон Ø24 с бортиком 2 мм, поле 1,3 мм — под рельеф и альфы.", ["медальон", "бортик"]),
        ("Oval_TwoSided_18x24", ellipse(9, 12, 160), pillow(0.5, 1.2, 5.0), True, "Двусторонний овал 18×24.", ["овал", "двусторонний"]),
    ]
    for name, outline, zf, two, desc, tags in items:
        top_y = max(p[1] for p in outline)
        # ушко по центру: опускаем до тела (у сердца — до выемки)
        y_center_top = max(p[1] for p in resample_loop(outline, 0.2) if abs(p[0]) < 1.0)
        bail = stadium(0.0, y_center_top - 1.5, top_y + 1.3, 2.3)
        hole = ellipse(1.0, 1.0, 40, 0.0, top_y + 1.3)
        bz = (lambda d: 0.6 + 0.4 * circ(d / 0.5)) if two else (lambda d: 0.9 + 0.6 * circ(d / 0.6))
        bm = bm_plate([(outline, zf), (bail, bz)], [hole], P, two_sided=two)
        lib.add("pendants", f"Pendant_{name}", bm,
                desc + " Ушко с отверстием Ø2 мм по оси Z (выходит из формы без стержня). " +
                ("Разъём по середине толщины." if two else "Плоская спинка на плоскости разъёма Z=0."),
                ["кулон"] + tags, two_sided=two, props=dict(gv_two_sided=two))


# ================================================================ Касты и камни

def build_settings(lib):
    for D in (3, 4, 5, 6, 8):
        r = D / 2
        wall = 0.6 if D <= 5 else 0.7
        h = 2.6 if D <= 4 else 3.2
        # стенка у основания толще: после уклона вверху остаётся ровно wall
        ro = r + 0.05 + wall + 2 * h * math.tan(math.radians(lib.cfg.draft_deg))
        seat = h - (0.9 if D <= 4 else 1.2)
        prof = [(r - 0.35, 0.0), (ro, 0.0), (ro, h), (r + 0.05, h), (r + 0.05, seat), (r - 0.35, seat)]
        lib.add("settings", f"Bezel_Round_D{D}", bm_revolve(prof, 96),
                f"Глухая каста для круглого камня Ø{D} мм: стенка {wall} мм вверху (толще к основанию из-за уклона), высота {h} мм, "
                f"ободок-посадка 0,35 мм на высоте {seat:.1f} мм. Разъём по нижней грани.",
                ["каста", "глухая", f"Ø{D}"], two_sided=False, smooth=False,
                props=dict(gv_stone_d_mm=D))


def round_brilliant(D, table=0.57, crown_deg=34.5, pav_deg=40.75, girdle=0.03, sx=1.0, sy=1.0):
    R = D / 2
    g = girdle * D / 2
    hc = (R - R * table) * math.tan(math.radians(crown_deg))
    hp = R * math.tan(math.radians(pav_deg))
    pts = []
    for i in range(32):
        a = 2 * math.pi * i / 32
        pts += [(R * math.cos(a), R * math.sin(a), g), (R * math.cos(a), R * math.sin(a), -g)]
    for i in range(8):
        a = 2 * math.pi * i / 8 + math.pi / 8
        pts.append((R * table * math.cos(a), R * table * math.sin(a), g + hc))
        b = 2 * math.pi * i / 8
        rc = R * (table + (1 - table) * 0.55)
        pts.append((rc * math.cos(b), rc * math.sin(b), g + hc * 0.45))
        rp = R * 0.55
        pts.append((rp * math.cos(b), rp * math.sin(b), -g - hp * 0.45 - 0.0))
    pts.append((0, 0, -g - hp))
    return bm_hull([(x * sx, y * sy, z) for x, y, z in pts]), g + hc + g + hp


def build_gems(lib):
    for D in (1.5, 2, 3, 4, 5, 6, 8, 10):
        bm, H = round_brilliant(D)
        lib.add("gems", f"Gem_Round_D{D:g}", bm,
                f"Камень-болванка «круг» (бриллиантовая огранка, упрощ.) Ø{D:g} мм, высота ~{H:.2f} мм. "
                "Для подбора каст и посадок, не для литья.", ["камень", "круг", f"Ø{D:g}"],
                smooth=False, mat=lib.mat_gem, props=dict(gv_stone_d_mm=D))
    for a, b in ((6, 4), (8, 6), (10, 8)):
        bm, H = round_brilliant(b, sx=a / b)
        lib.add("gems", f"Gem_Oval_{a}x{b}", bm, f"Камень-болванка «овал» {a}×{b} мм.", ["камень", "овал"],
                smooth=False, mat=lib.mat_gem)
    for s in (4, 5, 6):
        h = s / 2
        t = h * 0.75
        pts = [(x * h, y * h, z) for x in (-1, 1) for y in (-1, 1) for z in (0.06, -0.06)]
        pts += [(x * t, y * t, s * 0.18) for x in (-1, 1) for y in (-1, 1)]
        pts += [(0, 0, -s * 0.7)]
        lib.add("gems", f"Gem_Princess_{s}", bm_hull(pts), f"Камень-болванка «принцесса» {s}×{s} мм.",
                ["камень", "принцесса"], smooth=False, mat=lib.mat_gem)


# ================================================================ Проволока и скань (кривые)

def make_curve(name, splines, bevel_r, cyclic=False):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_mode = 'ROUND'
    cu.bevel_depth = bevel_r
    cu.bevel_resolution = 4
    cu.use_fill_caps = True
    cu.resolution_u = 12
    for pts in splines:
        sp = cu.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        for p, co in zip(sp.points, pts):
            p.co = (co[0], co[1], co[2], 1.0)
        sp.use_cyclic_u = cyclic
    return cu


def build_wire(lib):
    k = "wire"
    lib.add_curve(k, "Wire_Straight_D0.8x20", make_curve("w", [[(x, 0, 0.4) for x in (-10, 10)]], 0.4),
                  "Проволока Ø0,8 мм, 20 мм (кривая: форма редактируется Tab, толщина — Data › Geometry › Bevel).",
                  ["проволока"])
    lib.add_curve(k, "Wire_Ring_D10_W0.8", make_curve("w", [[(5 * math.cos(a * math.pi / 32), 5 * math.sin(a * math.pi / 32), 0.4) for a in range(64)]], 0.4, True),
                  "Кольцо из проволоки Ø0,8, диаметр 10 мм.", ["проволока", "кольцо"])
    spiral = [((0.6 + 0.9 * t / (2 * math.pi)) * math.cos(t), (0.6 + 0.9 * t / (2 * math.pi)) * math.sin(t), 0.3)
              for t in (i * 0.1 for i in range(int(4.5 * 2 * math.pi / 0.1)))]
    lib.add_curve(k, "Filigree_Spiral_D0.6", make_curve("w", [spiral], 0.3),
                  "Спираль скани Ø0,6 мм (4,5 витка, шаг 0,9 мм).", ["скань", "спираль"])
    scroll = []
    for t in (i * 0.08 for i in range(int(3 * math.pi / 0.08))):
        r = 0.5 + 0.55 * t
        scroll.append((r * math.cos(t) - 3.0, r * math.sin(t), 0.3))
    scroll = scroll[::-1] + [(-x, -y, z) for x, y, z in scroll]
    lib.add_curve(k, "Filigree_SScroll_D0.6", make_curve("w", [scroll], 0.3),
                  "S-завиток скани Ø0,6 мм.", ["скань", "завиток"])
    tw = []
    for s in (0, math.pi):
        tw.append([(x * 0.05 - 10, 0.3 * math.cos(x * 0.05 * 2 * math.pi / 2.5 + s), 0.6 + 0.3 * math.sin(x * 0.05 * 2 * math.pi / 2.5 + s)) for x in range(401)])
    lib.add_curve(k, "Wire_Twisted_2x0.6", make_curve("w", tw, 0.3),
                  "Витой жгут из 2 проволок Ø0,6, шаг 2,5 мм, длина 20 мм.", ["проволока", "жгут", "витая"])
    zig = [((i - 10) * 1.0, 0.8 * (1 if i % 2 else -1), 0.3) for i in range(21)]
    lib.add_curve(k, "Filigree_Zigzag_D0.6", make_curve("w", [zig], 0.3), "Зигзаг скани Ø0,6, шаг 1 мм.", ["скань", "зигзаг"])
    print("  (кривые-проволока: литейная проверка не выполняется, см. толщину Bevel)")


# ================================================================ Основы для лепки

def _concentric_disk(R, h, n=60):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=n, y_segments=n, size=1.0)
    for v in bm.verts:
        x, y = v.co.x, v.co.y
        m = max(abs(x), abs(y))
        L = math.hypot(x, y)
        if L > 1e-9:
            f = m / L
            # смягчаем: в центре — квадратная сетка, к краю — окружность
            f = 1.0 + (f - 1.0) * m ** 1.5
            v.co.x, v.co.y = x * f * R, y * f * R
        v.co.z = h
    res = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
    vs = [e for e in res["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=vs, vec=(0, 0, -h))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def _cabochon(rx, ry, h, girdle=0.6):
    bm = bm_quad_sphere(1.0, 16)
    for v in bm.verts:
        z = v.co.z
        v.co = Vector((v.co.x * rx, v.co.y * ry, girdle + z * (h - girdle) if z >= 0 else 0.0))
    return bm


def _slab(sx, sy, h, step=0.25):
    xs = [-sx / 2 + sx * i / int(sx / step) for i in range(int(sx / step) + 1)]
    ys = [-sy / 2 + sy * i / int(sy / step) for i in range(int(sy / step) + 1)]
    bm = bm_box_lattice(xs, ys, [0.0, h])
    return bm


def build_bases(lib):
    k = "bases"
    lib.add(k, "Base_Slab_30x20x2", _slab(30, 20, 2.0), "Плитка 30×20×2 мм, сетка 0,25 мм сверху — для рельефа, альф и проверки кистей. Плоская спинка.",
            ["плитка", "рельеф", "альфа"], two_sided=False, smooth=False)
    lib.add(k, "Base_Disk_D25x2", _concentric_disk(12.5, 2.0), "Круглая плитка Ø25×2 мм, квадратная топология сверху — под медальон/печать.",
            ["плитка", "рельеф", "круг"], two_sided=False)
    lib.add(k, "Base_Sphere_D12", bm_quad_sphere(6.0, 24), "Сфера Ø12 высокой плотности под лепку. Разъём по экватору.", ["сфера", "лепка"])
    lib.add(k, "Base_Cabochon_Oval_14x10", _cabochon(7, 5, 4.0), "Кабошон 14×10, высота 4 мм, поясок 0,6 мм. Плоское дно.",
            ["кабошон", "лепка"], two_sided=False)
    lib.add(k, "Base_Cabochon_Round_D12", _cabochon(6, 6, 4.0), "Кабошон Ø12, высота 4 мм, поясок 0,6 мм. Плоское дно.",
            ["кабошон", "лепка"], two_sided=False)
    lib.add(k, "Base_Bead_Oval_10x14", bm_quad_sphere(1.0, 20, (5, 7, 5)), "Овальная бусина 10×14×10 (без отверстия). Разъём по середине.",
            ["бусина", "лепка"])
    leaf = [(6.0 * math.sin(t) * (1 - 0.15 * math.cos(t)) * abs(math.sin(t)) ** 0.25, -14.0 * math.cos(t))
            for t in (2 * math.pi * i / 120 for i in range(120))]
    lib.add(k, "Base_Leaf_12x28", bm_plate([(leaf, lambda d: 0.7 + 1.1 * circ(d / 3.5))], (), 0.4),
            "Листок 12×28 под лепку прожилок; плоская спинка.", ["лист", "лепка"], two_sided=False)
    petal = [(5.0 * math.sin(t) * (0.6 + 0.4 * (1 - math.cos(t)) / 2), -8.0 * math.cos(t)) for t in (2 * math.pi * i / 100 for i in range(100))]
    lib.add(k, "Base_Petal_10x16", bm_plate([(petal, lambda d: 0.6 + 0.6 * circ(d / 2.5))], (), 0.35),
            "Лепесток 10×16 — для цветов и розеток; плоская спинка.", ["лепесток", "цветок"], two_sided=False)


# ================================================================ Болванки персонажей

def mirror_nodes(center, side):
    """center: [(co, r)], side: [(co, r)] для +X; возвращает узлы с зеркалом."""
    nodes, radii = [], []
    for co, r in center:
        nodes.append(co)
        radii.append(r)
    idx = {}
    for s in (1, -1):
        for i, (co, r) in enumerate(side):
            idx[(s, i)] = len(nodes)
            nodes.append((co[0] * s, co[1], co[2]))
            radii.append(r)
    return nodes, radii, idx


def build_characters(lib):
    k = "characters"
    # человек 60 мм (масштаб миниатюры/фигурки), A-поза, лицом в -Y
    center = [((0, 0, 31), (4.0, 2.9)), ((0, 0, 36), (3.5, 2.5)), ((0, 0, 42), (4.4, 2.9)),
              ((0, 0, 48), (1.5, 1.5)), ((0, -0.3, 52.5), (3.3, 3.8)), ((0, 0.2, 56.5), (3.2, 3.6))]
    side = [((5.6, 0, 46), (1.7, 1.7)), ((10.5, 0.4, 39), (1.3, 1.3)), ((14.5, 0, 32.5), (0.95, 0.7)),
            ((15.8, -0.2, 28.5), (1.2, 0.5)),
            ((3.0, 0, 29.5), (2.5, 2.6)), ((3.4, 0, 17), (1.8, 1.8)), ((3.6, 0.6, 3), (1.2, 1.3)), ((3.6, -3.3, 0.9), (1.2, 0.8))]
    nodes, radii, ix = mirror_nodes(center, side)
    edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]
    for s in (1, -1):
        a = [ix[(s, i)] for i in range(8)]
        edges += [(2, a[0]), (a[0], a[1]), (a[1], a[2]), (a[2], a[3]), (0, a[4]), (a[4], a[5]), (a[5], a[6]), (a[6], a[7])]
    lib.add(k, "Char_Human_60mm", skin(nodes, edges, radii, 2),
            "Болванка фигуры человека 60 мм (миниатюра), A-поза, лицом к -Y. Для лепки: Ctrl+R вокселем или Dyntopo.",
            ["человек", "фигура", "болванка"])
    # голова 24 мм
    hn = [(0, 0.8, 0), (0, 0.8, 4.5), (0, -0.6, 8.5), (0, 0.2, 13.5), (0, 0.6, 17.5), (0, -3.2, 9.5)]
    hr = [(3.0, 3.0), (2.8, 2.8), (3.8, 4.0), (6.0, 6.6), (5.4, 6.0), (1.3, 1.0)]
    lib.add(k, "Char_Head_24mm", skin(hn, [(0, 1), (1, 2), (2, 3), (3, 4), (2, 5)], hr, 3),
            "Болванка головы с шеей, высота ~24 мм, лицо к -Y (выступ подбородка/носа).", ["голова", "портрет", "болванка"])
    # кисть руки 20 мм, ладонь вниз, пальцы к +Y
    hn = [(0, 0, 0), (0, 4.5, 0)]
    hr = [(2.6, 1.3), (3.8, 1.4)]
    e = [(0, 1)]
    for fx, L in ((-2.7, 0.85), (-0.9, 1.0), (0.9, 0.95), (2.6, 0.75)):
        base = len(hn)
        segs = [(fx, 8.3, 0), (fx * 1.05, 8.3 + 3.2 * L, 0), (fx * 1.08, 8.3 + 5.6 * L, 0), (fx * 1.1, 8.3 + 7.4 * L, 0)]
        hn += segs
        hr += [(0.85, 0.75), (0.75, 0.65), (0.65, 0.55), (0.55, 0.45)]
        e += [(1, base), (base, base + 1), (base + 1, base + 2), (base + 2, base + 3)]
    base = len(hn)
    hn += [(-3.2, 2.5, 0), (-5.2, 5.0, 0), (-6.4, 7.2, 0), (-7.0, 9.0, 0)]
    hr += [(1.2, 1.0), (0.95, 0.85), (0.8, 0.7), (0.65, 0.55)]
    e += [(1, base), (base, base + 1), (base + 1, base + 2), (base + 2, base + 3)]
    lib.add(k, "Char_Hand_20mm", skin(hn, e, hr, 2), "Болванка кисти руки ~20 мм, ладонь вниз, пальцы к +Y.",
            ["рука", "кисть", "болванка"])
    # четвероногое 40 мм, морда к +X
    center = [((-12, 0, 14), (3.3, 3.0)), ((0, 0, 15), (3.6, 3.4)), ((10, 0, 14.5), (4.0, 3.8)),
              ((15, 0, 20), (2.2, 2.2)), ((18.5, 0, 23), (2.9, 2.7)), ((23, 0, 21.5), (1.4, 1.3)),
              ((-16, 0, 16), (1.0, 1.0)), ((-21, 0, 18.5), (0.5, 0.5))]
    side = [((10, 2.8, 11), (1.6, 1.6)), ((10.5, 3.0, 5.5), (1.1, 1.1)), ((11, 3.0, 0.9), (1.0, 1.0)), ((12.6, 3.0, 0.7), (1.0, 0.8)),
            ((-12, 2.8, 11), (2.0, 2.0)), ((-13.5, 3.0, 6.5), (1.2, 1.2)), ((-12, 3.0, 0.9), (1.0, 1.0)), ((-10.6, 3.0, 0.7), (1.0, 0.8)),
            ((18.2, 1.8, 25.5), (0.7, 0.4)), ((17.4, 2.0, 27.5), (0.3, 0.2))]
    nodes, radii, ix = mirror_nodes(center, [((x, y, z), r) for (x, y, z), r in side])
    # зеркалим по Y, а не по X
    nodes = [(n[0], n[1], n[2]) for n in nodes]
    for (s, i), j in ix.items():
        x, y, z = side[i][0]
        nodes[j] = (x, y * s, z)
    edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (0, 6), (6, 7)]
    for s in (1, -1):
        a = [ix[(s, i)] for i in range(10)]
        edges += [(2, a[0]), (a[0], a[1]), (a[1], a[2]), (a[2], a[3]),
                  (0, a[4]), (a[4], a[5]), (a[5], a[6]), (a[6], a[7]), (4, a[8]), (a[8], a[9])]
    lib.add(k, "Char_Quadruped_45mm", skin(nodes, edges, radii, 2),
            "Болванка четвероногого (собака/конь/лев) ~45 мм, морда к +X.", ["животное", "четвероногое", "болванка"])
    # птица 30 мм
    bn = [(0, 0, 8), (5, 0, 9.5), (8.5, 0, 12.5), (10.8, 0, 12.2), (-6, 0, 8.5), (-10, 0, 9)]
    br = [(3.6, 3.0), (2.6, 2.4), (2.4, 2.2), (0.7, 0.5), (1.8, 0.6), (2.6, 0.3)]
    lib.add(k, "Char_Bird_30mm", skin(bn, [(0, 1), (1, 2), (2, 3), (0, 4), (4, 5)], br, 2),
            "Болванка птицы ~30 мм (без крыльев и лап — долепить), клюв к +X.", ["птица", "болванка"])


# ================================================================ Органика

def build_organic(lib):
    k = "organic"
    path = [(6 * (1 - t * 0.55) * math.cos(t * 4.2), 6 * (1 - t * 0.55) * math.sin(t * 4.2), t * 14) for t in (i / 60 for i in range(61))]
    lib.add(k, "Org_Horn_Spiral_20mm", bm_tube(path, [2.4 * (1 - t / 60) ** 0.9 for t in range(61)], 24),
            "Спиральный рог/завиток, основание Ø4,8, высота ~14 мм.", ["рог", "спираль"])
    path = [(math.sin(t * 0.25) * 3.0 * t / 25, t, (1 - math.cos(t * 0.12)) * 3.0) for t in (i * 0.5 for i in range(51))]
    lib.add(k, "Org_Tentacle_25mm", bm_tube(path, [1.6 * (1 - i / 50) ** 0.8 for i in range(51)], 20),
            "Щупальце/стебель 25 мм, сужение к кончику.", ["щупальце", "стебель"])
    path = [(t, 3 * math.sin(t * 0.35), 0.0) for t in (i * 0.5 for i in range(81))]
    rad = [0.8 + 0.6 * math.sin(min(i / 6, 1) * math.pi / 2) if i < 76 else 1.4 * (80 - i) / 4 for i in range(81)]
    rad[0], rad[1], rad[2] = 1.6, 1.8, 1.6
    lib.add(k, "Org_Snake_40mm", bm_tube(path, rad, 20), "Змея-болванка 40 мм с утолщением головы.", ["змея"])
    rock = bm_quad_sphere(5.0, 16)
    for v in rock.verts:
        n = noise.fractal(v.co * 0.25, 0.6, 2.0, 4) * 0.9 + noise.noise(v.co * 0.6) * 0.3
        v.co = v.co * (1 + 0.12 * n)
        v.co.z *= 0.7
    lib.add(k, "Org_Stone_10mm", rock, "Камень-валун ~10 мм, неровная форма — для природных композиций.", ["камень", "валун"])
    lib.add(k, "Org_Drop_3D_8x12", bm_revolve([(0, 0)] + [(4 * math.sin(t) * (1 - 0.0 * t) * (math.sin(t / 2) ** 0.6), 6 - 6 * math.cos(t) * 1.0)
                                                         for t in (math.pi * i / 40 for i in range(1, 40))] + [(0, 12)], 48, closed=False),
            "Объёмная капля 8×12 мм (тело вращения).", ["капля"])
    bm = bm_quad_sphere(1.0, 14)
    for v in bm.verts:
        x, y, z = v.co
        v.co = Vector((x * 3.5, y * 7 * (1 - 0.25 * x), z * 1.6 * (1 - 0.6 * abs(y))))
    lib.add(k, "Org_Shell_Bean_7x14", bm, "Боб/семя/ракушка-основа 7×14 мм.", ["семя", "ракушка"])


# ================================================================ каталоги и превью

def write_catalogs(cats_file):
    """Дописывает недостающие каталоги в общий blender_assets.cats.txt (не перезаписывает)."""
    existing, lines = set(), []
    if os.path.exists(cats_file):
        with open(cats_file, encoding="utf-8") as f:
            lines = f.read().splitlines()
        for ln in lines:
            if ln and not ln.startswith("#") and ":" in ln and not ln.startswith("VERSION"):
                existing.add(ln.split(":", 1)[1].split(":", 1)[0])
    else:
        lines = ["# This is an Asset Catalog Definition file for Blender.", "#",
                 "# Empty lines and lines starting with `#` will be ignored.",
                 "# The first non-ignored line should be the version indicator.",
                 '# Other lines are of the format "UUID:catalog/path/for/assets:simple catalog name"', "",
                 "VERSION 1", ""]
    paths = ["GravenArc", CATALOG_ROOT, f"{CATALOG_ROOT}/Jewelry"] + [catalog_path(k) for k in CATALOGS]
    added = []
    for p in paths:
        if p not in existing:
            lines.append(f"{catalog_uuid(p)}:{p}:{p.replace('/', '-')}")
            added.append(p)
    if added:
        with open(cats_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return added


def render_previews(objs, size=192):
    scene = bpy.data.scenes.new("_GV_Preview")
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.film_transparent = True
    world = bpy.data.worlds.new("_GV_World")
    world.color = (0.9, 0.92, 0.98)
    scene.view_settings.view_transform = 'Standard'
    scene.world = world
    cam_data = bpy.data.cameras.new("_GV_Cam")
    cam_data.type = 'ORTHO'
    cam = bpy.data.objects.new("_GV_Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    for name, rot, energy in (("_GV_Key", (0.6, 0.3, 0.9), 4.5), ("_GV_Rim", (-0.9, 0.0, 3.6), 2.5)):
        ld = bpy.data.lights.new(name, 'SUN')
        ld.energy = energy
        lo = bpy.data.objects.new(name, ld)
        lo.rotation_euler = rot
        scene.collection.objects.link(lo)
    tmp = os.path.join(bpy.app.tempdir or "/tmp", "gv_prev.png")
    done = 0
    for obj in objs:
        prx = bpy.data.objects.new("_GV_P", obj.data)
        for m in obj.modifiers:
            nm = prx.modifiers.new(m.name, m.type)
            for attr in ("levels", "width", "segments", "limit_method"):
                if hasattr(m, attr):
                    setattr(nm, attr, getattr(m, attr))
        scene.collection.objects.link(prx)
        bb = [Vector(c) for c in obj.bound_box]
        center = sum(bb, Vector()) / 8
        direction = Vector((0.6, -1.0, 0.8)).normalized()
        cam.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
        # размер кадра по проекции габаритов на плоскость камеры
        inv = cam.rotation_euler.to_matrix().inverted()
        pr = [inv @ (b - center) for b in bb]
        span = max(max(p.x for p in pr) - min(p.x for p in pr), max(p.y for p in pr) - min(p.y for p in pr))
        cam.location = center + direction * (span * 5 + 20)
        cam_data.ortho_scale = span * 1.15
        cam_data.clip_end = span * 20 + 200
        scene.render.filepath = tmp
        try:
            bpy.ops.render.render(write_still=True, scene=scene.name)
            img = bpy.data.images.load(tmp, check_existing=False)
            prev = obj.preview_ensure()
            prev.image_size = (size, size)
            prev.image_pixels_float[:] = list(img.pixels)
            bpy.data.images.remove(img)
            done += 1
        except Exception as e:  # превью необязательны
            print("preview failed:", obj.name, e)
        bpy.data.objects.remove(prx)
    for o in list(scene.collection.objects):
        bpy.data.objects.remove(o)
    bpy.data.scenes.remove(scene)
    return done


# ================================================================ main

STEPS = ["geometry", "hardsurface", "shanks", "rings", "pendants", "settings", "gems", "wire",
         "bases", "characters", "organic"]


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description="GravenArc templates generator")
    ap.add_argument("--out", default=None, help="путь к .blend (по умолчанию рядом со скриптом)")
    ap.add_argument("--cats", default=None, help="blender_assets.cats.txt (по умолчанию — в папке выше, корень библиотеки)")
    ap.add_argument("--draft", dest="draft_deg", type=float, default=DEFAULTS["draft_deg"])
    ap.add_argument("--shrink", dest="shrink_pct", type=float, default=DEFAULTS["shrink_pct"])
    ap.add_argument("--apply-shrink", action="store_true", default=DEFAULTS["apply_shrink"])
    ap.add_argument("--min-wall", type=float, default=DEFAULTS["min_wall"])
    ap.add_argument("--ring-sizes", default=DEFAULTS["ring_sizes"])
    ap.add_argument("--signet-sizes", default=DEFAULTS["signet_sizes"])
    ap.add_argument("--pitch", type=float, default=DEFAULTS["pitch"])
    ap.add_argument("--no-previews", dest="previews", action="store_false", default=DEFAULTS["previews"])
    ap.add_argument("--author", default=DEFAULTS["author"])
    ap.add_argument("--license", default=DEFAULTS["license"])
    ap.add_argument("--only", default=",".join(STEPS), help="категории через запятую: " + ",".join(STEPS))
    cfg = ap.parse_args(argv)
    cfg.ring_size_list = [float(s) for s in cfg.ring_sizes.split(",") if s.strip()]
    cfg.signet_size_list = [float(s) for s in cfg.signet_sizes.split(",") if s.strip()]
    if cfg.min_wall < 0.5:
        print("ВНИМАНИЕ: перемычки тоньше 0,5 мм в песке обычно не проливаются.")
    return cfg


def main():
    cfg = parse_args()
    here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() and os.path.exists(__file__) else os.getcwd()
    background = bpy.app.background
    scene = bpy.context.scene
    if background:
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o)
    setup_scene(scene)
    root = get_collection(scene.collection, "GravenArc Templates")
    lib = Library(cfg, root)
    for key in cfg.only.split(","):
        globals()["build_" + key.strip()](lib)
        print(f"[GravenArc] готово: {key}")

    objs = [o for o in root.all_objects if o.asset_data]
    if cfg.previews and background:
        n = render_previews(objs)
        print(f"[GravenArc] превью: {n}/{len(objs)}")

    cats = cfg.cats or os.path.join(os.path.dirname(here), "blender_assets.cats.txt")
    added = write_catalogs(cats)
    print("[GravenArc] каталоги добавлены:", added or "все уже были")

    with open(os.path.join(here, "templates_report.json"), "w", encoding="utf-8") as f:
        json.dump(dict(draft_deg=cfg.draft_deg, shrink_pct=cfg.shrink_pct, apply_shrink=cfg.apply_shrink,
                       min_wall_mm=cfg.min_wall, items=lib.report), f, ensure_ascii=False, indent=1)
    bad = [r for r in lib.report if r["cast"] and (r["thin_faces"] or r["undercut_faces"])]
    print(f"[GravenArc] шаблонов: {len(lib.report)}, литейных с замечаниями: {len(bad)}")
    for r in bad:
        print("   ", r["name"], "тонких граней:", r["thin_faces"], "поднутрений:", r["undercut_faces"], "мин. стенка:", r["min_wall_mm"])

    if background:
        out = cfg.out or os.path.join(here, "GravenArc_Templates.blend")
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out), compress=True)
        print("[GravenArc] сохранено:", out)


if __name__ == "__main__":
    main()

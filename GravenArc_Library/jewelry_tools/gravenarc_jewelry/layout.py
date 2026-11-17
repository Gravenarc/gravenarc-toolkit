# SPDX-License-Identifier: GPL-3.0-or-later
# Раскладка камней: паве по поверхности, камни по кривой, общие крапаны, корнеры (зёрна).
# Все расчёты — в мировых координатах, в мм.
import math
import random

import bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from . import core


def gem_matrix(center_mm, normal, tangent=None, k=1.0):
    """Матрица камня: Z = нормаль, X — вдоль tangent (если задан). k — мм на единицу Blender."""
    z = normal.normalized()
    if tangent is None or abs(tangent.normalized().dot(z)) > 0.99:
        tangent = Vector((1, 0, 0)) if abs(z.x) < 0.9 else Vector((0, 1, 0))
    x = (tangent - z * tangent.dot(z)).normalized()
    y = z.cross(x)
    M = Matrix((x, y, z)).transposed().to_4x4()
    M.translation = center_mm / k
    return M


# ---------------------------------------------------------------- паве

class Region:
    """Область поверхности для паве: треугольники (мм), BVH, граница."""

    def __init__(self, bm_world, only_selected):
        bm = bm_world
        faces = [f for f in bm.faces if (f.select or not only_selected)]
        if only_selected and not faces:
            faces = list(bm.faces)
        fset = set(faces)
        self.tris, verts, polys = [], [], []
        vidx = {}
        for f in faces:
            ids = []
            for v in f.verts:
                if v not in vidx:
                    vidx[v] = len(verts)
                    verts.append(v.co.copy())
                ids.append(vidx[v])
            polys.append(ids)
            for i in range(1, len(ids) - 1):
                self.tris.append((verts[ids[0]], verts[ids[i]], verts[ids[i + 1]]))
        self.bvh = BVHTree.FromPolygons(verts, polys)
        self.area = sum(((b - a).cross(c - a)).length / 2 for a, b, c in self.tris)
        # граница области: рёбра, у которых только одна грань внутри области
        bpts = []
        for f in faces:
            for e in f.edges:
                n_in = sum(1 for g in e.link_faces if g in fset)
                if n_in == 1:
                    a, b = e.verts[0].co, e.verts[1].co
                    L = (b - a).length
                    steps = max(1, int(L / 0.1))
                    for s in range(steps + 1):
                        bpts.append(a.lerp(b, s / steps))
        self.border = KDTree(max(1, len(bpts)))
        for i, p in enumerate(bpts):
            self.border.insert(p, i)
        self.border.balance()
        self.has_border = bool(bpts)
        self.cum = []
        acc = 0.0
        for a, b, c in self.tris:
            acc += ((b - a).cross(c - a)).length / 2
            self.cum.append(acc)

    def random_point(self, rnd):
        import bisect
        x = rnd.random() * self.cum[-1]
        i = min(bisect.bisect_left(self.cum, x), len(self.tris) - 1)
        a, b, c = self.tris[i]
        u, v = rnd.random(), rnd.random()
        if u + v > 1:
            u, v = 1 - u, 1 - v
        return a + (b - a) * u + (c - a) * v

    def border_dist(self, p):
        if not self.has_border:
            return 1e9
        return self.border.find(p)[2]

    def nearest(self, p):
        loc, nrm, idx, d = self.bvh.find_nearest(p)
        return loc, nrm


def _pave_once(region, spacing, margin, seed=1, relax_iters=4, front_tol=0.94):
    """Центры камней на поверхности: «наращивание фронта» — от затравки по 6 направлениям
    с шагом spacing (почти шестиугольная укладка и на кривых поверхностях), затем
    добивка случайными точками и лёгкая релаксация."""
    rnd = random.Random(seed)
    pts, nrms = [], []
    cell = spacing
    grid = {}

    def key(p):
        return (int(math.floor(p.x / cell)), int(math.floor(p.y / cell)), int(math.floor(p.z / cell)))

    def free(p, tol=0.995):
        kx, ky, kz = key(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for j in grid.get((kx + dx, ky + dy, kz + dz), ()):
                        if (pts[j] - p).length < spacing * tol:
                            return False
        return True

    def add(p, n):
        grid.setdefault(key(p), []).append(len(pts))
        pts.append(p)
        nrms.append(n)

    def ok(p, tol=0.995):
        return region.border_dist(p) >= margin * tol and free(p, tol)

    # затравка: среди случайных точек — самая далёкая от края (с вариантом по seed)
    cands = [region.random_point(rnd) for _ in range(300)]
    cands.sort(key=lambda p: -region.border_dist(p))
    seeds = [p for p in cands[:30]]
    s0 = seeds[rnd.randrange(len(seeds))] if seed else seeds[0]
    q, n = region.nearest(s0)
    if q is None or region.border_dist(q) < margin:
        return []
    add(q, n.normalized())
    front = [(0, None)]
    while front:
        i, parent_dir = front.pop(0)
        p, n = pts[i], nrms[i]
        if parent_dir is None:
            t = n.orthogonal().normalized()
        else:
            t = (parent_dir - n * parent_dir.dot(n)).normalized()
            if t.length < 1e-6:
                t = n.orthogonal().normalized()
        b = n.cross(t)
        for kdir in range(6):
            a = math.pi / 3 * kdir
            d = t * math.cos(a) + b * math.sin(a)
            c = p + d * spacing
            for _ in range(3):  # проекция и поправка шага на кривизне
                c, cn = region.nearest(c)
                if c is None:
                    break
                v = c - p
                if v.length < 1e-9:
                    break
                c = p + v.normalized() * spacing
            if c is None:
                continue
            c, cn = region.nearest(c)
            if c is None or (c - p).length < spacing * 0.9:
                continue
            if ok(c, front_tol):  # на кривизне шаг решётки чуть меньше — добирает релаксация
                add(c, cn.normalized())
                front.append((len(pts) - 1, (c - p).normalized()))

    def relax(iters):
        for _ in range(iters):
            kd = KDTree(max(1, len(pts)))
            for i, p in enumerate(pts):
                kd.insert(p, i)
            kd.balance()
            new = []
            for i, p in enumerate(pts):
                push = Vector()
                for q2, j, dd in kd.find_range(p, spacing * 1.03):
                    if j != i and dd > 1e-9:
                        push += (p - q2).normalized() * (spacing * 1.03 - dd)
                if region.has_border:
                    bq, _, bd = region.border.find(p)
                    if bd < margin * 1.03 and bd > 1e-9:
                        push += (p - bq).normalized() * (margin * 1.03 - bd)
                q2, n2 = region.nearest(p + push * 0.5)
                new.append((q2, n2) if q2 is not None else (p, nrms[i]))
            for i, (q2, n2) in enumerate(new):
                pts[i], nrms[i] = q2, n2.normalized()
            grid.clear()
            for i, p in enumerate(pts):
                grid.setdefault(key(p), []).append(i)

    if front_tol < 0.99:
        relax(8)
    # добивка пустот у краёв и на стыках фронтов
    for _ in range(relax_iters):
        for _ in range(int(region.area / (spacing * spacing) * 15) + 50):
            p = region.random_point(rnd)
            if ok(p):
                q2, n2 = region.nearest(p)
                add(q2, n2.normalized())
        relax(6)
    # чистка
    order = sorted(range(len(pts)), key=lambda i: -region.border_dist(pts[i]))
    keep = []
    for i in order:
        p = pts[i]
        if region.border_dist(p) < margin * 0.97:
            continue
        if all((p - q2).length >= spacing * 0.98 for q2 in keep):
            keep.append(p)
    return keep


def pave_points(region, spacing, margin, seed=1, tries=4):
    """Лучшая из нескольких раскладок (по числу камней)."""
    best = []
    for t in range(tries):
        for tol in (0.995, 0.94):
            pts = _pave_once(region, spacing, margin, seed * 101 + t, 4, tol)
            if len(pts) > len(best):
                best = pts
    return best


def triangles_between(points, max_d):
    """Тройки соседних камней (для зёрен-корнеров между ними)."""
    kd = KDTree(max(1, len(points)))
    for i, p in enumerate(points):
        kd.insert(p, i)
    kd.balance()
    nb = [set(j for _, j, d in kd.find_range(p, max_d) if j != i) for i, p in enumerate(points)]
    tris = set()
    for i in range(len(points)):
        for j in nb[i]:
            if j <= i:
                continue
            for k in nb[i] & nb[j]:
                if k > j:
                    tris.add((i, j, k))
    return tris


# ---------------------------------------------------------------- кривая

def curve_polyline(context, ob):
    """Точки кривой/ломаной (мм, мир) по порядку и признак замкнутости."""
    k = core.mm_per_bu(context)
    M = Matrix.Scale(k, 4) @ ob.matrix_world
    cyclic = False
    if ob.type == 'CURVE':
        if ob.data.splines:
            cyclic = ob.data.splines[0].use_cyclic_u
    dg = context.evaluated_depsgraph_get()
    oe = ob.evaluated_get(dg)
    me = oe.to_mesh()
    verts = [M @ v.co for v in me.vertices]
    adj = {i: [] for i in range(len(verts))}
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    oe.to_mesh_clear()
    if not verts:
        return [], False
    if ob.type == 'MESH' or any(len(v) > 0 for v in adj.values()):
        ends = [i for i, n in adj.items() if len(n) == 1]
        start = ends[0] if ends else 0
        if ob.type == 'MESH':
            cyclic = not ends
        order, prev, cur = [start], None, start
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in order[-2:]]
            nxt = [n for n in nxt if n != start or len(order) < 3]
            if not nxt or nxt[0] == start:
                break
            prev, cur = cur, nxt[0]
            if cur in order:
                break
            order.append(cur)
        verts = [verts[i] for i in order]
    return verts, cyclic


def arc_sampler(pts, cyclic):
    segs = list(zip(pts, pts[1:] + ([pts[0]] if cyclic else [])))
    lens = [(b - a).length for a, b in segs]
    total = sum(lens)

    def at(s):
        s = s % total if cyclic else max(0.0, min(total, s))
        acc = 0.0
        for (a, b), L in zip(segs, lens):
            if acc + L >= s:
                f = 0.0 if L < 1e-12 else (s - acc) / L
                return a.lerp(b, min(1.0, max(0.0, f))), (b - a).normalized() if L > 1e-12 else Vector((1, 0, 0))
            acc += L
        a, b = segs[-1]
        return b, (b - a).normalized()

    return total, at


def stations_on_curve(total, cyclic, d0, d1, gap, mode='NONE', fit=True):
    """Позиции (s) и размеры камней вдоль длины total.
    mode: NONE — один размер d0; LINEAR — от d0 к d1; CENTER — d0 по краям, d1 в центре."""
    def size_at(u):
        if mode == 'LINEAR':
            return d0 + (d1 - d0) * u
        if mode == 'CENTER':
            return d0 + (d1 - d0) * (1 - abs(2 * u - 1))
        return d0

    if mode == 'NONE':
        pitch = d0 + gap
        n = int((total + (0 if cyclic else gap)) // pitch)
        if n < 1:
            return []
        if fit:
            pitch = total / n if cyclic else (total - d0) / max(1, n - 1)
            start = 0.0 if cyclic else d0 / 2
            if not cyclic and n == 1:
                start = total / 2
        else:
            used = n * d0 + (n - (0 if cyclic else 1)) * gap
            start = (total - used) / 2 + d0 / 2 if not cyclic else 0.0
        return [(start + i * pitch, d0) for i in range(n)]
    # градуировка: подбираем последовательно
    res = []
    s = size_at(0) / 2
    while True:
        d = size_at(s / total)
        if s + d / 2 > total + 1e-6:
            break
        res.append((s, d))
        dn = size_at(min(1.0, (s + d + gap) / total))
        s += d / 2 + gap + dn / 2
    if fit and res:  # равномерно растянуть остаток
        extra = total - (res[-1][0] + res[-1][1] / 2)
        n = len(res)
        if n > 1:
            res = [(s + extra * i / (n - 1), d) for i, (s, d) in enumerate(res)]
        else:
            res = [(total / 2, res[0][1])]
    return res

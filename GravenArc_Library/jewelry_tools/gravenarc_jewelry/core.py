# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc Jewelry Tools — общие функции: единицы, размеры колец, плотности, построение сеток.
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

# ---------------------------------------------------------------- единицы

def mm_per_bu(context=None):
    """Сколько мм в одной единице Blender (при Unit Scale 0.001 — ровно 1)."""
    scene = (context or bpy.context).scene
    us = scene.unit_settings
    if us.system == 'NONE':
        return 1.0
    return us.scale_length * 1000.0


def bu(mm, context=None):
    """мм -> единицы Blender."""
    return mm / mm_per_bu(context)


# ---------------------------------------------------------------- размеры колец
# RU: размер = внутренний Ø, мм. EU (ISO 8653): длина окружности, мм.
# US/CA: Ø = 11.63 + 0.8128·US. UK/AU: A = 37.8 мм по окружности, шаг 1.25 мм на букву.

SIZE_SYSTEMS = [
    ('RU', "RU / ГОСТ (Ø мм)", "Российский размер = внутренний диаметр в мм"),
    ('EU', "EU / ISO (окружность)", "Европейский размер = длина внутренней окружности в мм"),
    ('US', "US / CA", "Американский размер, Ø = 11.63 + 0.8128·US"),
    ('UK', "UK / AU (буквы)", "Британский размер: A … Z, Z+1 …; половинки: N½ = N.5"),
    ('DIAM', "Диаметр, мм", "Внутренний диаметр напрямую"),
]

UK_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def uk_to_index(text):
    t = text.strip().upper().replace("½", ".5").replace(" 1/2", ".5").replace("1/2", ".5")
    if not t:
        raise ValueError("пустой размер")
    if t[0] in UK_LETTERS:
        idx = UK_LETTERS.index(t[0])
        rest = t[1:]
        if rest.startswith("+"):
            idx += float(rest[1:] or 1)
        elif rest:
            idx += float(rest) if rest.startswith(".") else float(rest)
        return idx
    return float(t)


def index_to_uk(idx):
    i = int(math.floor(idx + 1e-6))
    half = (idx - i) >= 0.25
    if i < 26:
        s = UK_LETTERS[max(i, 0)]
    else:
        s = f"Z+{i - 25}"
    return s + ("½" if half else "")


def size_to_diameter(system, value):
    """value: число (float) или строка для UK. Возвращает внутренний Ø, мм."""
    if system in ('RU', 'DIAM'):
        return float(value)
    if system == 'EU':
        return float(value) / math.pi
    if system == 'US':
        return 11.63 + 0.8128 * float(value)
    if system == 'UK':
        idx = uk_to_index(value) if isinstance(value, str) else float(value)
        return (37.8 + 1.25 * idx) / math.pi
    raise ValueError(system)


def diameter_to_sizes(d):
    return {
        'RU': round(d * 2) / 2,
        'DIAM': d,
        'EU': math.pi * d,
        'US': (d - 11.63) / 0.8128,
        'UK': index_to_uk((math.pi * d - 37.8) / 1.25),
    }


def sizes_text(d):
    s = diameter_to_sizes(d)
    return (f"Ø {d:.2f} мм · RU {s['RU']:g} · EU {s['EU']:.1f} · "
            f"US {s['US']:.2f} · UK {s['UK']}")


# ---------------------------------------------------------------- плотности, г/см³ (= мг/мм³)

METALS = [
    ('AU999', "Золото 999", 19.32),
    ('AU750Y', "Золото 750 жёлтое", 15.45),
    ('AU750W', "Золото 750 белое", 15.60),
    ('AU585R', "Золото 585 красное", 13.50),
    ('AU585W', "Золото 585 белое", 13.10),
    ('AU375', "Золото 375", 11.50),
    ('AG925', "Серебро 925", 10.36),
    ('AG999', "Серебро 999", 10.49),
    ('PT950', "Платина 950", 20.70),
    ('PD950', "Палладий 950", 12.10),
    ('BRONZE', "Бронза", 8.80),
    ('BRASS', "Латунь", 8.50),
    ('CU', "Медь", 8.96),
    ('TI', "Титан", 4.51),
    ('RESIN', "Смола / воск (печать)", 1.10),
]
METAL_DENSITY = {k: d for k, _, d in METALS}

GEM_MATERIALS = [
    ('DIAMOND', "Бриллиант / алмаз", 3.52, (0.95, 0.97, 1.0)),
    ('MOISSANITE', "Муассанит", 3.22, (0.95, 0.97, 0.92)),
    ('CZ', "Фианит (CZ)", 5.80, (0.97, 0.97, 1.0)),
    ('RUBY', "Рубин", 4.00, (0.80, 0.02, 0.10)),
    ('SAPPHIRE', "Сапфир", 4.00, (0.05, 0.15, 0.75)),
    ('EMERALD', "Изумруд", 2.72, (0.05, 0.60, 0.25)),
    ('GARNET', "Гранат", 3.90, (0.45, 0.02, 0.06)),
    ('AMETHYST', "Аметист / кварц", 2.65, (0.55, 0.25, 0.80)),
    ('TOPAZ', "Топаз", 3.53, (0.35, 0.70, 0.95)),
    ('SPINEL', "Шпинель", 3.60, (0.85, 0.20, 0.45)),
    ('AQUAMARINE', "Аквамарин", 2.70, (0.55, 0.85, 0.95)),
    ('CITRINE', "Цитрин", 2.65, (0.95, 0.70, 0.15)),
]
GEM_DENSITY = {k: d for k, _, d, _ in GEM_MATERIALS}
GEM_COLOR = {k: c for k, _, _, c in GEM_MATERIALS}

# ---------------------------------------------------------------- плоские кривые (контуры)

def resample_closed(pts, n, start_index=0):
    """Равномерно по длине пересэмплировать замкнутую ломаную, начиная с pts[start_index]."""
    pts = pts[start_index:] + pts[:start_index]
    m = len(pts)
    seg = [(pts[(i + 1) % m] - pts[i]).length for i in range(m)]
    total = sum(seg)
    out, acc, i = [], 0.0, 0
    for k in range(n):
        target = total * k / n
        while acc + seg[i] < target and i < m - 1:
            acc += seg[i]
            i += 1
        f = 0.0 if seg[i] == 0 else (target - acc) / seg[i]
        out.append(pts[i].lerp(pts[(i + 1) % m], f))
    return out


def polyline_normals(pts):
    """Внешние нормали замкнутого CCW-контура в XY."""
    n = len(pts)
    res = []
    for i in range(n):
        t = (pts[(i + 1) % n] - pts[i - 1])
        t.z = 0
        if t.length < 1e-12:
            res.append(Vector((1, 0, 0)))
            continue
        t.normalize()
        res.append(Vector((t.y, -t.x, 0)))
    return res


def point_at_angle(pts, ang, L, W):
    """Точка контура в направлении ang (в нормированных координатах x/L, y/W —
    так 45° попадает в угол прямоугольника)."""
    d = Vector((math.cos(ang) * L, math.sin(ang) * W, 0))
    best, best_t = None, 1e18
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        e = b - a
        den = d.x * (-e.y) - d.y * (-e.x)
        if abs(den) < 1e-12:
            continue
        # a + e*u = d*t
        t = (a.x * (-e.y) - a.y * (-e.x)) / den
        u = (d.x * a.y - d.y * a.x) / den
        if t > 0 and -1e-9 <= u <= 1 + 1e-9 and t < best_t:
            best_t, best = t, a + e * u
    if best is None:
        best = Vector((L / 2 * math.cos(ang), W / 2 * math.sin(ang), 0))
    return Vector((best.x, best.y, 0))


# ---------------------------------------------------------------- bmesh-построители

def bridge_rings(bm, ra, rb, ta=None, tb=None, flip=False):
    """Соединить два замкнутых кольца вершин (могут иметь разное число точек).
    ta/tb — параметры 0..1 вдоль кольца (по умолчанию равномерно)."""
    na, nb = len(ra), len(rb)
    ta = ta or [i / na for i in range(na)]
    tb = tb or [i / nb for i in range(nb)]
    faces = []
    if na == nb and ta == tb:
        for i in range(na):
            q = [ra[i], ra[(i + 1) % na], rb[(i + 1) % nb], rb[i]]
            faces.append(q)
    else:
        i = j = 0
        while i < na or j < nb:
            ca, cb = ra[i % na], rb[j % nb]
            na_t = ta[(i + 1) % na] + (1.0 if i + 1 >= na else 0.0)
            nb_t = tb[(j + 1) % nb] + (1.0 if j + 1 >= nb else 0.0)
            if j >= nb or (i < na and na_t <= nb_t):
                faces.append([ca, ra[(i + 1) % na], cb])
                i += 1
            else:
                faces.append([ca, rb[(j + 1) % nb], cb])
                j += 1
    out = []
    for f in faces:
        if flip:
            f = f[::-1]
        if len(set(f)) >= 3:
            try:
                out.append(bm.faces.new(f))
            except ValueError:
                pass
    return out


def cap_ring(bm, ring, z_up=True, center=None):
    """Закрыть кольцо: n-угольником или веером к центральной вершине."""
    vs = ring if z_up else ring[::-1]
    if center is None:
        try:
            return [bm.faces.new(vs)]
        except ValueError:
            return []
    c = bm.verts.new(center)
    res = []
    n = len(vs)
    for i in range(n):
        try:
            res.append(bm.faces.new((vs[i], vs[(i + 1) % n], c)))
        except ValueError:
            pass
    return res


def _untangle(path, ring, iters=12):
    """Смещённый контур у острых углов (сердце, груша, маркиз) заворачивается петлёй и
    даёт самопересечение стенки. Схлопываем «вывернутые» участки в одну точку
    (число вершин не меняется — кольца профиля остаются согласованными)."""
    n = len(path)
    for _ in range(iters):
        bad = [((ring[(i + 1) % n] - ring[i]).dot(path[(i + 1) % n] - path[i]) <= 0) for i in range(n)]
        if not any(bad):
            return
        seen = set()
        for i in range(n):
            if not bad[i] or i in seen:
                continue
            # участок подряд вывернутых сегментов i..j (по кругу)
            j = i
            while bad[(j + 1) % n] and (j + 1) % n != i:
                j += 1
            s0 = i
            while bad[(s0 - 1) % n] and (s0 - 1) % n != i:
                s0 -= 1
            idx = [(k % n) for k in range(s0, j + 2)]
            seen.update(k % n for k in range(s0, j + 1))
            # расширяем на соседей: точка схлопывания — среднее с захватом краёв
            idx = [(s0 - 1) % n] + idx + [(j + 2) % n]
            c = sum((ring[k] for k in idx), Vector()) / len(idx)
            for k in idx:
                ring[k] = c.copy()


def sweep_profile(bm, path, profile, closed_path=True, normals=None, up=Vector((0, 0, 1))):
    """Протянуть замкнутый 2D-профиль [(offset_по_нормали, z)] вдоль контура path (XY, CCW).
    Возвращает список колец."""
    normals = normals or polyline_normals(path)
    cols = []
    for o, z in profile:
        ring = [p + nrm * o + up * z for p, nrm in zip(path, normals)]
        if closed_path and abs(o) > 1e-9:
            _untangle(path, ring)
        cols.append(ring)
    rings = [[bm.verts.new(cols[k][i]) for k in range(len(profile))] for i in range(len(path))]
    m = len(profile)
    np_ = len(path)
    rng = range(np_) if closed_path else range(np_ - 1)
    for i in rng:
        a, b = rings[i], rings[(i + 1) % np_]
        for k in range(m):
            try:
                bm.faces.new((a[k], a[(k + 1) % m], b[(k + 1) % m], b[k]))
            except ValueError:
                pass
    if not closed_path:
        cap_ring(bm, rings[0])
        cap_ring(bm, rings[-1], z_up=False)
    return rings


def add_tube(bm, a, b, r, segs=12, cap_a=True, cap_b=True, sphere_b=False):
    """Цилиндр от a до b радиусом r; sphere_b — скруглённый (шаровой) конец."""
    axis = (b - a)
    L = axis.length
    if L < 1e-9:
        return
    q = axis.normalized().to_track_quat('Z', 'Y')
    M = q.to_matrix()
    ra, rb = [], []
    for i in range(segs):
        ang = 2 * math.pi * i / segs
        off = M @ Vector((math.cos(ang) * r, math.sin(ang) * r, 0))
        ra.append(bm.verts.new(a + off))
        rb.append(bm.verts.new(b + off))
    bridge_rings(bm, ra, rb)
    if cap_a:
        cap_ring(bm, ra, z_up=False)
    if sphere_b:
        prev = rb
        rings_n = max(3, segs // 4)
        for k in range(1, rings_n):
            phi = (math.pi / 2) * k / rings_n
            ring = []
            for i in range(segs):
                ang = 2 * math.pi * i / segs
                off = M @ Vector((math.cos(ang) * r * math.cos(phi), math.sin(ang) * r * math.cos(phi),
                                  r * math.sin(phi)))
                ring.append(bm.verts.new(b + off))
            bridge_rings(bm, prev, ring)
            prev = ring
        cap_ring(bm, prev, center=b + M @ Vector((0, 0, r)))
    elif cap_b:
        cap_ring(bm, rb)


def add_sphere(bm, c, r, segs=12):
    ret = bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=max(6, segs // 2), radius=r)
    bmesh.ops.translate(bm, verts=ret['verts'], vec=c)


def islands(bm):
    """Связные куски сетки (списки граней)."""
    seen, res = set(), []
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        stack, part = [f0], []
        seen.add(f0.index)
        while stack:
            f = stack.pop()
            part.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        res.append(part)
    return res


def fix_normals(bm):
    """Нормали наружу для каждого куска отдельно (по знаку объёма)."""
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for part in islands(bm):
        vol = 0.0
        for f in part:
            vs = [v.co for v in f.verts]
            for i in range(1, len(vs) - 1):
                vol += vs[0].dot(vs[i].cross(vs[i + 1])) / 6.0
        if vol < 0:
            bmesh.ops.reverse_faces(bm, faces=part)


def volume(bm):
    """Сумма |объёмов| кусков (для перекрывающихся деталей — верхняя оценка)."""
    bm.faces.index_update()
    tot = 0.0
    for part in islands(bm):
        vol = 0.0
        for f in part:
            vs = [v.co for v in f.verts]
            for i in range(1, len(vs) - 1):
                vol += vs[0].dot(vs[i].cross(vs[i + 1])) / 6.0
        tot += abs(vol)
    return tot


def finish_bm(bm, name, smooth=False):
    fix_normals(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = smooth
    return me


def link_object(context, name, me, collection=None, matrix=None):
    ob = bpy.data.objects.new(name, me)
    (collection or context.collection).objects.link(ob)
    if matrix is not None:
        ob.matrix_world = matrix
    return ob


def ensure_collection(context, name, parent=None, hide_render=False):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or context.scene.collection).children.link(col)
    col.hide_render = hide_render
    return col


def mesh_world_bm(context, ob, apply_modifiers=True):
    """bmesh объекта в мировых координатах, в мм (с учётом модификаторов)."""
    dg = context.evaluated_depsgraph_get()
    oe = ob.evaluated_get(dg) if apply_modifiers else ob
    me = oe.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    oe.to_mesh_clear()
    k = mm_per_bu(context)
    bm.transform(Matrix.Scale(k, 4) @ ob.matrix_world)
    return bm


def is_gem(ob):
    return ob is not None and ob.get("gv_gem") is not None


def set_mm_scene(context):
    s = context.scene
    s.unit_settings.system = 'METRIC'
    s.unit_settings.scale_length = 0.001
    s.unit_settings.length_unit = 'MILLIMETERS'
    s.unit_settings.mass_unit = 'GRAMS'
    for area in getattr(context.screen, "areas", []) if context.screen else []:
        if area.type == 'VIEW_3D':
            for sp in area.spaces:
                if sp.type == 'VIEW_3D':
                    sp.clip_start = 0.01
                    sp.clip_end = 10000
                    sp.overlay.grid_scale = 1.0

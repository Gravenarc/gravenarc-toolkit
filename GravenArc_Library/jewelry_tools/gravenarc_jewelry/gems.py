# SPDX-License-Identifier: GPL-3.0-or-later
# Камни (огранки), вырезы под камни (cutters), крапановые касты и глухие касты.
# Всё строится в миллиметрах; камень лежит площадкой вверх (+Z), центр рундиста — в начале координат.
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import core

# ---------------------------------------------------------------- контуры рундиста (плотные, CCW, старт на +X)

def _ellipse(L, W, n=720):
    return [Vector((L / 2 * math.cos(2 * math.pi * i / n), W / 2 * math.sin(2 * math.pi * i / n), 0)) for i in range(n)]


def _superellipse(L, W, p=3.0, n=720):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        c, s = math.cos(t), math.sin(t)
        x = L / 2 * math.copysign(abs(c) ** (2 / p), c)
        y = W / 2 * math.copysign(abs(s) ** (2 / p), s)
        pts.append(Vector((x, y, 0)))
    return pts


def _marquise(L, W, n=720):
    R = (L * L + W * W) / (4 * W)
    c = R - W / 2
    a0 = math.atan2(c, L / 2)
    half = n // 2
    up = []
    for i in range(half):
        a = a0 + (math.pi - 2 * a0) * i / half
        up.append(Vector((R * math.cos(a), R * math.sin(a) - c, 0)))
    return up + [Vector((-p.x, -p.y, 0)) for p in up]


def _pear(L, W, n=720):
    r = W / 2
    C = Vector((-L / 2 + r, 0, 0))
    T = Vector((L / 2, 0, 0))
    d = (T - C).length
    al = math.acos(min(1.0, r / d))
    tan_up = C + Vector((r * math.cos(al), r * math.sin(al), 0))
    nl = n // 4
    pts = []
    # от острия к верхней точке касания — слегка выпуклая «щека»
    side = (tan_up - T)
    nrm = Vector((-side.y, side.x, 0)).normalized()
    for i in range(nl):
        u = i / nl
        pts.append(T + side * u + nrm * (0.07 * W * math.sin(math.pi * u)))
    na = n - 2 * nl
    for i in range(na):
        a = al + (2 * math.pi - 2 * al) * i / na
        pts.append(C + Vector((r * math.cos(a), r * math.sin(a), 0)))
    tan_dn = Vector((tan_up.x, -tan_up.y, 0))
    side2 = (T - tan_dn)
    nrm2 = Vector((-side2.y, side2.x, 0)).normalized()
    for i in range(nl):
        u = i / nl
        pts.append(tan_dn + side2 * u + nrm2 * (0.07 * W * math.sin(math.pi * u)))
    return _fit_box(pts, L, W)


def _heart(L, W, n=720):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append(Vector((y, -x, 0)))  # ложбинка на +X, острие на -X
    return _fit_box(pts, L, W)


def _trillion(L, W, n=720):
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        # треугольник в полярных координатах + выпуклость сторон
        k = math.cos(math.pi / 3) / math.cos(((a + math.pi / 3) % (2 * math.pi / 3)) - math.pi / 3)
        r = 0.62 * k + 0.38 * (0.5 + 0.5 * k)
        pts.append(Vector((r * math.cos(a), r * math.sin(a), 0)))
    return _fit_box(pts, L, W)


def _fit_box(pts, L, W):
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    sx, sy = L / (max(xs) - min(xs)), W / (max(ys) - min(ys))
    return [Vector(((p.x - cx) * sx, (p.y - cy) * sy, 0)) for p in pts]


def _rect_poly(L, W, c=0.0, subdiv=1):
    """Прямоугольник с фасками c, CCW, первая вершина на +X. subdiv — деление сторон."""
    a, b = L / 2, W / 2
    if c > 0:
        corners = [(a, 0), (a, b - c), (a - c, b), (0, b), (-a + c, b), (-a, b - c), (-a, 0),
                   (-a, -b + c), (-a + c, -b), (0, -b), (a - c, -b), (a, -b + c)]
    else:
        corners = [(a, 0), (a, b), (0, b), (-a, b), (-a, 0), (-a, -b), (0, -b), (a, -b)]
    pts = []
    m = len(corners)
    for i in range(m):
        p, q = Vector((*corners[i], 0)), Vector((*corners[(i + 1) % m], 0))
        for k in range(subdiv):
            pts.append(p.lerp(q, k / subdiv))
    return pts


# kind: 'brilliant' — гладкий контур, бриллиантовая огранка; 'poly' — многоугольник с бриллиантовым низом;
#       'step' — ступенчатая (изумрудная); 'cab' — кабошон.
# пропорции — доли ширины W: table — площадка (доля контура), crown/girdle/pav — высоты.
CUTS = {
    'ROUND':    dict(label="Круг (бриллиант Кр57)", kind='brilliant', ratio=1.0, table=0.57, crown=0.15, girdle=0.03, pav=0.43, k=4, off=0.5),
    'OVAL':     dict(label="Овал", kind='brilliant', ratio=1.4, table=0.55, crown=0.14, girdle=0.03, pav=0.45, k=4, off=0.5),
    'PEAR':     dict(label="Груша (капля)", kind='brilliant', ratio=1.6, table=0.55, crown=0.14, girdle=0.03, pav=0.45, k=5, off=0.0),
    'MARQUISE': dict(label="Маркиз (навет)", kind='brilliant', ratio=2.0, table=0.55, crown=0.14, girdle=0.03, pav=0.45, k=6, off=0.0),
    'HEART':    dict(label="Сердце", kind='brilliant', ratio=1.0, table=0.55, crown=0.14, girdle=0.03, pav=0.45, k=3, off=0.5),
    'CUSHION':  dict(label="Кушон", kind='brilliant', ratio=1.0, table=0.55, crown=0.14, girdle=0.03, pav=0.48, k=4, off=0.5),
    'TRILLION': dict(label="Триллион", kind='brilliant', ratio=1.0, table=0.60, crown=0.12, girdle=0.03, pav=0.40, k=3, off=0.0),
    'PRINCESS': dict(label="Принцесса (квадрат)", kind='poly', ratio=1.0, table=0.70, crown=0.10, girdle=0.03, pav=0.62, k=4, off=0.5),
    'EMERALD':  dict(label="Изумрудная (октагон)", kind='step', ratio=1.4, table=0.65, crown=0.12, girdle=0.03, pav=0.50, k=4, off=0.5, chamfer=0.18),
    'ASSCHER':  dict(label="Ашер (квадрат-ступень)", kind='step', ratio=1.0, table=0.62, crown=0.13, girdle=0.03, pav=0.52, k=4, off=0.5, chamfer=0.24),
    'BAGUETTE': dict(label="Багет", kind='step', ratio=2.0, table=0.65, crown=0.12, girdle=0.03, pav=0.45, k=4, off=0.5, chamfer=0.0),
    'CAB_ROUND': dict(label="Кабошон круглый", kind='cab', ratio=1.0, table=0.0, crown=0.40, girdle=0.04, pav=0.06, k=4, off=0.5),
    'CAB_OVAL':  dict(label="Кабошон овальный", kind='cab', ratio=1.33, table=0.0, crown=0.40, girdle=0.04, pav=0.06, k=4, off=0.5),
}

CUT_ITEMS = [(k, v['label'], "") for k, v in CUTS.items()]


def dense_outline(cut, L, W):
    if cut in ('ROUND', 'OVAL', 'CAB_ROUND', 'CAB_OVAL'):
        return _ellipse(L, W)
    if cut == 'CUSHION':
        return _superellipse(L, W, 3.2)
    if cut == 'PEAR':
        return _pear(L, W)
    if cut == 'MARQUISE':
        return _marquise(L, W)
    if cut == 'HEART':
        return _heart(L, W)
    if cut == 'TRILLION':
        return _trillion(L, W)
    if cut == 'PRINCESS':
        return _rect_poly(L, W, 0.0, subdiv=2)
    spec = CUTS[cut]
    return _rect_poly(L, W, spec.get('chamfer', 0.0) * min(L, W), subdiv=1)


def outline(cut, L, W, n=32, offset=0.0):
    """Контур рундиста: n точек (для 'step'/'poly' — вершины многоугольника, n игнорируется)."""
    dense = dense_outline(cut, L, W)
    if CUTS[cut]['kind'] in ('step', 'poly'):
        return dense
    two = core.resample_closed(dense, n * 2)
    return two[1::2] if offset else two[0::2]


def girdle_point(cut, L, W, ang):
    return core.point_at_angle(dense_outline(cut, L, W), ang, L, W)


# ---------------------------------------------------------------- камень

def _ring(bm, pts, z, sx, sy):
    return [bm.verts.new((p.x * sx, p.y * sy, z)) for p in pts]


def gem_dims(cut, L, W):
    s = CUTS[cut]
    g, c, p = s['girdle'] * W, s['crown'] * W, s['pav'] * W
    return dict(girdle=g, crown=c, pav=p, table=s['table'],
                z_table=g / 2 + c, z_gtop=g / 2, z_gbot=-g / 2, z_culet=-g / 2 - p)


def build_gem_bm(cut, L, W, n=32):
    s = CUTS[cut]
    d = gem_dims(cut, L, W)
    g, c, p, tb = d['girdle'], d['crown'], d['pav'], d['table']
    bm = bmesh.new()
    kind = s['kind']
    if kind == 'brilliant':
        n = max(16, (n // 8) * 8)
        nt = n // 4
        layers = [  # (pts, t-список, z, scale)
            (outline(cut, L, W, nt, 0), [i / nt for i in range(nt)], g / 2 + c, tb),
            (outline(cut, L, W, n // 2, 1), [(i + .5) / (n // 2) for i in range(n // 2)], g / 2 + c * 0.5, 1 - (1 - tb) * 0.5),
            (outline(cut, L, W, n, 0), [i / n for i in range(n)], g / 2, 1.0),
            (outline(cut, L, W, n, 0), [i / n for i in range(n)], -g / 2, 1.0),
            (outline(cut, L, W, n // 2, 1), [(i + .5) / (n // 2) for i in range(n // 2)], -g / 2 - p * 0.5, 0.5),
        ]
        rings = [(_ring(bm, pts, z, sc, sc), t) for pts, t, z, sc in layers]
        cap_ring_pts = None
    elif kind == 'poly':
        pts = outline(cut, L, W)
        tt = [i / len(pts) for i in range(len(pts))]
        spec = [(g / 2 + c, tb), (g / 2 + c * 0.5, 1 - (1 - tb) * 0.5), (g / 2, 1), (-g / 2, 1), (-g / 2 - p * 0.5, 0.5)]
        rings = [(_ring(bm, pts, z, sc, sc), tt) for z, sc in spec]
    elif kind == 'step':
        pts = outline(cut, L, W)
        tt = [i / len(pts) for i in range(len(pts))]
        keel = max(0.03, (L - W) / L) if L > W else 0.03
        spec = [(g / 2 + c, tb, tb), (g / 2 + c * 0.5, (1 + tb) / 2, (1 + tb) / 2), (g / 2, 1, 1), (-g / 2, 1, 1),
                (-g / 2 - p * 0.35, 0.74, 0.70), (-g / 2 - p * 0.7, 0.45, 0.38), (-g / 2 - p, keel, 0.03)]
        rings = [(_ring(bm, pts, z, sx, sy), tt) for z, sx, sy in spec]
    else:  # cab
        n = max(16, n)
        pts = outline(cut, L, W, n, 0)
        tt = [i / n for i in range(n)]
        rings = [(_ring(bm, pts, -g / 2 - p, 0.96, 0.96), tt), (_ring(bm, pts, -g / 2, 1, 1), tt), (_ring(bm, pts, g / 2, 1, 1), tt)]
        steps = 6
        for k in range(1, steps):
            phi = (math.pi / 2) * k / steps
            rings.append((_ring(bm, pts, g / 2 + c * math.sin(phi), math.cos(phi), math.cos(phi)), tt))
        rings.reverse()  # сверху вниз, как у огранок
    for (ra, ta), (rb, tb_) in zip(rings, rings[1:]):
        core.bridge_rings(bm, ra, rb, ta, tb_)
    top = rings[0][0]
    bottom = rings[-1][0]
    if kind == 'cab':
        core.cap_ring(bm, top, center=Vector((0, 0, g / 2 + c)))
        core.cap_ring(bm, bottom, z_up=False)
    else:
        core.cap_ring(bm, top)
        if kind == 'step':
            core.cap_ring(bm, bottom, z_up=False)
        else:
            core.cap_ring(bm, bottom, z_up=False, center=Vector((0, 0, d['z_culet'])))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    core.fix_normals(bm)
    return bm


def carat(volume_mm3, material='DIAMOND'):
    return volume_mm3 * core.GEM_DENSITY.get(material, 3.52) / 1000.0 * 5.0


# ---------------------------------------------------------------- вырез (cutter) под камень

def build_cutter_bm(cut, L, W, clearance=0.05, top=1.5, flare_deg=0.0, hole=0.55, hole_depth=1.5, n=32):
    d = gem_dims(cut, L, W)
    g, p = d['girdle'], d['pav']
    kind = CUTS[cut]['kind']
    pts = outline(cut, L, W, n, 0)
    tt = [i / len(pts) for i in range(len(pts))]
    bm = bmesh.new()

    def ring(z, s, extra):
        sx = (L * s + 2 * extra) / L
        sy = (W * s + 2 * extra) / W
        return _ring(bm, pts, z, sx, sy)

    zt = d['z_table'] + top
    seat_z = -g / 2 - p * (1 - hole) if kind != 'cab' else -g / 2 - p
    rings = [
        ring(zt, 1.0, clearance + top * math.tan(math.radians(flare_deg))),
        ring(g / 2, 1.0, clearance),
        ring(-g / 2, 1.0, clearance),
        ring(seat_z, hole, clearance),
        ring(d['z_culet'] - hole_depth, hole, clearance),
    ]
    for a, b in zip(rings, rings[1:]):
        core.bridge_rings(bm, a, b, tt, tt)
    core.cap_ring(bm, rings[0])
    core.cap_ring(bm, rings[-1], z_up=False)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    core.fix_normals(bm)
    return bm


# ---------------------------------------------------------------- крапановая каста (корона)

def build_prong_head_bm(cut, L, W, prongs=4, prong_d=0.8, offset=None, tip=0.35, base_depth=0.8,
                        base_scale=0.55, galleries=1, gallery_d=0.7, base_ring=True, segs=12):
    """Крапаны: от основания (под калетой) к рундисту и выше, кончики-шарики.
    tip — насколько кончик заходит на коронку (доля высоты коронки)."""
    spec = CUTS[cut]
    d = gem_dims(cut, L, W)
    off = spec['off'] if offset is None else offset
    r = prong_d / 2
    bm = bmesh.new()
    z_base = d['z_culet'] - base_depth
    dense = dense_outline(cut, L, W)
    tops = []
    for i in range(prongs):
        ang = 2 * math.pi * (i + off) / prongs
        gp = core.point_at_angle(dense, ang, L, W)
        out = gp.normalized() if gp.length > 1e-9 else Vector((1, 0, 0))
        mid = gp + out * (r * 0.55)
        top = mid + Vector((0, 0, d['z_gtop'] + d['crown'] * tip))
        mid.z = 0.0
        bot = gp * base_scale
        bot.z = z_base
        core.add_tube(bm, bot, mid, r, segs)
        core.add_sphere(bm, mid, r, segs)
        core.add_tube(bm, mid, top, r, segs, sphere_b=True)
        tops.append((gp, out))
    # галереи (обвязки) — кольца по контуру между рундистом и основанием
    path0 = core.resample_closed(dense, 64)
    nrm0 = core.polyline_normals(path0)
    gr = gallery_d / 2
    circle = [(gr * math.cos(2 * math.pi * k / 8), gr * math.sin(2 * math.pi * k / 8)) for k in range(8)]
    levels = []
    for gi in range(galleries):
        f = (gi + 1) / (galleries + 1) if galleries > 1 else 0.45
        levels.append(f)
    if base_ring:
        levels.append(1.0)
    for f in levels:
        z = d['z_gbot'] * (1 - f) + (z_base + gr) * f
        s = 1.0 * (1 - f) + base_scale * f
        path = [Vector((p.x * s, p.y * s, z)) for p in path0]
        core.sweep_profile(bm, path, [(r * 0.55 * (1 - f) + o, zz) for o, zz in circle], normals=nrm0)
    core.fix_normals(bm)
    return bm


# ---------------------------------------------------------------- глухая каста (bezel) по форме камня

def build_bezel_bm(cut, L, W, wall=0.7, clearance=0.05, lip=0.5, ledge=0.35, below=None, draft_deg=2.0, n=64):
    """Стенка вокруг рундиста: lip — высота над рундистом (мм), ledge — ширина опорной полки,
    below — глубина под рундистом (по умолчанию 85% павильона)."""
    d = gem_dims(cut, L, W)
    dense = dense_outline(cut, L, W)
    path = core.resample_closed(dense, n) if CUTS[cut]['kind'] not in ('step', 'poly') else \
        core.resample_closed(dense, max(n, len(dense) * 4))
    z_top = d['z_gtop'] + lip
    z_bot = d['z_gbot'] - (d['pav'] * 0.85 if below is None else below)
    tg = math.tan(math.radians(draft_deg))
    h = z_top - z_bot
    prof = [
        (clearance + (z_top - d['z_gbot']) * tg, z_top),   # внутр. верх (раскрыт вверх — без поднутрения)
        (clearance, d['z_gbot']),                          # полка
        (clearance - ledge, d['z_gbot'] - 0.05),
        (clearance - ledge, z_bot),
        (clearance + wall + h * tg, z_bot),                # наружу — уклон к верху
        (clearance + wall, z_top),
    ]
    bm = bmesh.new()
    core.sweep_profile(bm, [Vector((p.x, p.y, 0)) for p in path], prof)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    core.fix_normals(bm)
    return bm


# ---------------------------------------------------------------- объекты

def gem_material(material):
    name = f"GV Gem {material.title()}"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    col = core.GEM_COLOR.get(material, (0.95, 0.97, 1.0))
    mat.diffuse_color = (*col, 0.85)
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (*col, 1)
            bsdf.inputs["Roughness"].default_value = 0.0
            bsdf.inputs["IOR"].default_value = 2.42 if material == 'DIAMOND' else 1.77
            tw = bsdf.inputs.get("Transmission Weight") or bsdf.inputs.get("Transmission")
            if tw:
                tw.default_value = 1.0
    except Exception:
        pass
    return mat


def helper_material(name, color):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = color
    return mat


def bm_to_object(context, bm, name, collection=None, matrix=None, smooth=False):
    k = 1.0 / core.mm_per_bu(context)
    if abs(k - 1.0) > 1e-9:
        bmesh.ops.scale(bm, vec=(k, k, k), verts=bm.verts)
    me = core.finish_bm(bm, name, smooth)
    return core.link_object(context, name, me, collection, matrix)


def gem_mesh(context, cut, L, W, material='DIAMOND', n=32):
    """Сетка камня (общая для повторов): name кодирует параметры, чтобы паве делило одну сетку."""
    key = f"GV_Gem_{cut}_{L:g}x{W:g}_{n}"
    me = bpy.data.meshes.get(key)
    if me is None:
        bm = build_gem_bm(cut, L, W, n)
        vol = abs(bm.calc_volume())
        k = 1.0 / core.mm_per_bu(context)
        bmesh.ops.scale(bm, vec=(k, k, k), verts=bm.verts)
        me = core.finish_bm(bm, key)
        me["gv_volume_mm3"] = vol
    if not me.materials:
        me.materials.append(gem_material(material))
    return me


def tag_gem(ob, cut, L, W, material, me):
    ob["gv_gem"] = cut
    ob["gv_gem_L"] = L
    ob["gv_gem_W"] = W
    ob["gv_gem_material"] = material
    ob["gv_carat"] = round(carat(me.get("gv_volume_mm3", 0.0), material), 4)


def new_gem(context, cut, L, W, material='DIAMOND', matrix=None, collection=None, n=32, name=None):
    me = gem_mesh(context, cut, L, W, material, n)
    nm = name or (f"Gem_{cut.title()}_{L:g}x{W:g}" if L != W else f"Gem_{cut.title()}_{L:g}")
    ob = core.link_object(context, nm, me, collection, matrix)
    tag_gem(ob, cut, L, W, material, me)
    return ob


def gem_params(ob):
    return ob["gv_gem"], float(ob["gv_gem_L"]), float(ob["gv_gem_W"]), ob.get("gv_gem_material", 'DIAMOND')


def cutter_mesh(context, cut, L, W, clearance, top, flare, hole, hole_depth, n=32):
    key = f"GV_Cutter_{cut}_{L:g}x{W:g}_{clearance:g}_{top:g}_{flare:g}_{hole:g}_{hole_depth:g}"
    me = bpy.data.meshes.get(key)
    if me is None:
        bm = build_cutter_bm(cut, L, W, clearance, top, flare, hole, hole_depth, n)
        k = 1.0 / core.mm_per_bu(context)
        bmesh.ops.scale(bm, vec=(k, k, k), verts=bm.verts)
        me = core.finish_bm(bm, key)
        me.materials.append(helper_material("GV Cutter", (1.0, 0.25, 0.1, 0.35)))
    return me


def style_cutter(ob):
    ob.display_type = 'WIRE'
    ob.hide_render = True
    ob["gv_cutter"] = True

# SPDX-License-Identifier: GPL-3.0-or-later
# Вес металла, проверка стенок, уклонов и поднутрений для литья в песок, отчёт по камням.
import math
from collections import OrderedDict

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import core

COL_OK = (0.80, 0.80, 0.80, 1.0)
COL_DRAFT = (1.00, 0.80, 0.05, 1.0)
COL_UNDERCUT = (0.95, 0.10, 0.10, 1.0)
COL_THIN = (0.20, 0.35, 1.00, 1.0)


def metal_info(context, ob):
    """Объём (мм³) и диагностика сетки объекта с модификаторами."""
    bm = core.mesh_world_bm(context, ob)
    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    bm.faces.index_update()
    n_parts = len(core.islands(bm))
    vol = core.volume(bm)
    bm.free()
    return dict(volume=vol, non_manifold=non_manifold, parts=n_parts)


def weights(volume_mm3):
    return [(key, label, volume_mm3 * dens / 1000.0) for key, label, dens in core.METALS]


# ---------------------------------------------------------------- проверка для литья

def _check_target(context, ob):
    """Если есть модификаторы — проверяем копию с применёнными модификаторами
    (индексы граней исходной сетки иначе не совпадают)."""
    if not ob.modifiers:
        return ob, False
    dg = context.evaluated_depsgraph_get()
    oe = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(oe)
    name = ob.name + "_Check"
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old)
    cp = bpy.data.objects.new(name, me)
    for col in ob.users_collection:
        col.objects.link(cp)
    cp.matrix_world = ob.matrix_world.copy()
    ob.hide_set(True)
    return cp, True


def casting_check(context, ob, min_wall=0.5, draft_deg=2.0, parting_z=None, mode='TWO', check_draft=True,
                  check_thin=True, use_prop=True):
    """Красит грани атрибутом GV_Check и выделяет проблемные.
    Красный — поднутрение (форма не снимется / песок заперт), жёлтый — уклон меньше нормы,
    синий — стенка тоньше min_wall. Возвращает (объект, словарь счётчиков)."""
    target, copied = _check_target(context, ob)
    k = core.mm_per_bu(context)
    me = target.data
    bm = bmesh.new()
    bm.from_mesh(me)
    from mathutils import Matrix
    bm.transform(Matrix.Scale(k, 4) @ target.matrix_world)
    bm.normal_update()
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    if parting_z is None:
        pz = ob.get("gv_parting_z_mm") if use_prop else None
        if pz is not None:
            parting_z = (target.matrix_world @ Vector((0, 0, float(pz) / k))).z * k
        else:
            zs = [v.co.z for v in bm.verts]
            parting_z = (min(zs) + max(zs)) / 2 if mode == 'TWO' else min(zs)
    sin_d = math.sin(math.radians(draft_deg))
    eps = 1e-3
    status = []
    cnt = OrderedDict(undercut=0, draft=0, thin=0, ok=0)
    area = OrderedDict(undercut=0.0, draft=0.0, thin=0.0)
    thin_min = None
    for f in bm.faces:
        c = f.calc_center_median()
        n = f.normal
        st = 'ok'
        if check_draft:
            side = 1.0 if (mode == 'ONE' or c.z >= parting_z) else -1.0
            on_plane = abs(c.z - parting_z) < 1e-3 and abs(n.z) > 0.999
            nz = n.z * side
            zs_f = [v.co.z for v in f.verts]
            # грань касается линии разъёма: там касательная вертикальна по определению — не ошибка
            at_line = mode == 'TWO' and min(zs_f) - 1e-3 <= parting_z <= max(zs_f) + 1e-3
            if at_line and nz > -1e-4:
                on_plane = True
            if not on_plane:
                if nz < -1e-4:
                    st = 'undercut'
                elif nz < sin_d - 1e-4:
                    st = 'draft'
                if st != 'undercut' and nz > -1e-4:
                    hit = tree.ray_cast(c + n * eps + Vector((0, 0, side * eps)), Vector((0, 0, side)), 1e4)
                    if hit[0] is not None and hit[2] != f.index:
                        st = 'undercut'
        if check_thin and st == 'ok' or (check_thin and st == 'draft'):
            hit = tree.ray_cast(c - n * eps, -n, min_wall * 4)
            if hit[0] is not None and hit[3] + eps < min_wall:
                st = 'thin'
                thin_min = hit[3] + eps if thin_min is None else min(thin_min, hit[3] + eps)
        status.append(st)
        cnt[st] += 1
        if st != 'ok':
            area[st] += f.calc_area()
    bm.free()
    # запись цвета
    attr = me.color_attributes.get("GV_Check")
    if attr is None or attr.domain != 'FACE':
        if attr is not None:
            me.color_attributes.remove(attr)
        attr = me.color_attributes.new("GV_Check", 'BYTE_COLOR', 'FACE')
    colors = dict(ok=COL_OK, draft=COL_DRAFT, undercut=COL_UNDERCUT, thin=COL_THIN)
    flat = []
    for st in status:
        flat.extend(colors[st])
    attr.data.foreach_set("color", flat)
    me.color_attributes.active_color = attr
    for p, st in zip(me.polygons, status):
        p.select = st != 'ok'
    me.update()
    target["gv_check"] = dict(cnt)
    return target, dict(counts=dict(cnt), area={k2: round(v, 2) for k2, v in area.items()},
                        parting_z=parting_z, thin_min=thin_min, copied=copied)


def show_check_colors(context, on=True):
    for area in context.screen.areas if context.screen else []:
        if area.type == 'VIEW_3D':
            for sp in area.spaces:
                if sp.type == 'VIEW_3D':
                    if on:
                        sp.shading.type = 'SOLID'
                        sp.shading.color_type = 'VERTEX'  # в интерфейсе — «Attribute»
                    else:
                        sp.shading.color_type = 'MATERIAL'


# ---------------------------------------------------------------- отчёт

def gem_report(context, metal_key='AG925'):
    groups = OrderedDict()
    for ob in context.scene.objects:
        if not core.is_gem(ob):
            continue
        key = (ob["gv_gem"], float(ob["gv_gem_L"]), float(ob["gv_gem_W"]), ob.get("gv_gem_material", 'DIAMOND'))
        g = groups.setdefault(key, dict(count=0, ct=float(ob.get("gv_carat", 0.0))))
        g['count'] += 1
    metal = []
    for ob in context.scene.objects:
        if ob.type == 'MESH' and ob.get("gv_metal") and not ob.hide_get():
            info = metal_info(context, ob)
            metal.append((ob.name, info['volume']))
    lines = ["GravenArc — отчёт по изделию", ""]
    lines.append("КАМНИ")
    lines.append("Огранка;Размер, мм;Материал;Кол-во;ct/шт;ct всего")
    tot_n = 0
    tot_ct = 0.0
    from .gems import CUTS
    mats = {k: lbl for k, lbl, _, _ in core.GEM_MATERIALS}
    for (cut, L, W, mat), g in groups.items():
        size = f"{L:g}" if abs(L - W) < 1e-6 else f"{L:g}x{W:g}"
        ct_all = g['ct'] * g['count']
        tot_n += g['count']
        tot_ct += ct_all
        lines.append(f"{CUTS[cut]['label']};{size};{mats.get(mat, mat)};{g['count']};{g['ct']:.3f};{ct_all:.3f}")
    lines.append(f"ИТОГО камней;;;{tot_n};;{tot_ct:.3f}")
    lines.append("")
    lines.append("МЕТАЛЛ (объекты с отметкой «металл»)")
    dens = core.METAL_DENSITY[metal_key]
    label = dict((k2, l2) for k2, l2, _ in core.METALS)[metal_key]
    lines.append(f"Объект;Объём, мм³;{label}, г")
    vol_all = 0.0
    for name, vol in metal:
        vol_all += vol
        lines.append(f"{name};{vol:.1f};{vol * dens / 1000:.2f}")
    lines.append(f"ИТОГО;{vol_all:.1f};{vol_all * dens / 1000:.2f}")
    return "\n".join(lines), tot_n, tot_ct, vol_all

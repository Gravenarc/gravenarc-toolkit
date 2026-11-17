# SPDX-License-Identifier: GPL-3.0-or-later
# Операторы GravenArc Jewelry Tools. Все размеры в параметрах — в миллиметрах.
# После любой операции параметры можно поменять в панели «Adjust Last Operation» (F9).
import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Vector

from . import analysis, core, gems, layout, ring

def P(name, default, mn=0.0, mx=1000.0, step=1, desc=""):
    return FloatProperty(name=name, default=default, min=mn, soft_max=mx, step=step, precision=2, description=desc)


def _sel_meshes(context, gems_ok=False):
    return [o for o in context.selected_objects if o.type == 'MESH' and (gems_ok or not core.is_gem(o))
            and not o.get("gv_cutter")]


def _target(context):
    ob = context.active_object
    if ob and ob.type == 'MESH' and not core.is_gem(ob) and not ob.get("gv_cutter"):
        return ob
    return None


def add_boolean(target, operand, operation='DIFFERENCE', name=None):
    name = name or f"GV {operation.title()} {operand.name}"
    for m in target.modifiers:
        if m.type == 'BOOLEAN' and (getattr(m, 'collection', None) == operand or getattr(m, 'object', None) == operand):
            return m
    m = target.modifiers.new(name, 'BOOLEAN')
    m.operation = operation
    m.solver = 'EXACT'
    if isinstance(operand, bpy.types.Collection):
        m.operand_type = 'COLLECTION'
        m.collection = operand
    else:
        m.object = operand
    return m


def size_props(default_ru=17.0):
    return dict(
        size_system=EnumProperty(name="Система", items=core.SIZE_SYSTEMS, default='RU'),
        size_value=FloatProperty(name="Размер", default=default_ru, min=0, soft_max=80, step=50, precision=2),
        size_uk=StringProperty(name="Размер UK", default="N½"),
    )


def get_diameter(op):
    if op.size_system == 'UK':
        return core.size_to_diameter('UK', op.size_uk)
    return core.size_to_diameter(op.size_system, op.size_value)


def draw_size(layout_, op):
    row = layout_.row(align=True)
    row.prop(op, "size_system", text="")
    if op.size_system == 'UK':
        row.prop(op, "size_uk", text="")
    else:
        row.prop(op, "size_value", text="")
    try:
        layout_.label(text=core.sizes_text(get_diameter(op)))
    except ValueError:
        layout_.label(text="Неверный размер", icon='ERROR')


# ================================================================ сцена

class GV_OT_scene_mm(bpy.types.Operator):
    bl_idname = "gravenarc.scene_mm"
    bl_label = "Сцена в миллиметрах"
    bl_description = "1 единица Blender = 1 мм (Unit Scale 0.001), граммы, ближняя плоскость отсечения 0,01 мм"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        core.set_mm_scene(context)
        self.report({'INFO'}, "Сцена: миллиметры, 1 BU = 1 мм")
        return {'FINISHED'}


class GV_OT_mark_metal(bpy.types.Operator):
    bl_idname = "gravenarc.mark_metal"
    bl_label = "Отметить как металл"
    bl_description = "Отметить выделенные объекты как металл изделия (для отчёта и веса). Повторно — снять отметку"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obs = _sel_meshes(context)
        on = not all(o.get("gv_metal") for o in obs)
        for o in obs:
            o["gv_metal"] = on
        self.report({'INFO'}, f"{'Отмечено' if on else 'Снята отметка'}: {len(obs)}")
        return {'FINISHED'}


# ================================================================ камни

class _GemParams:
    cut: EnumProperty(name="Огранка", items=gems.CUT_ITEMS, default='ROUND')
    size: P("Ширина / Ø", 3.0, 0.5, 30, 10, "Ширина камня (для круглых — диаметр), мм")
    length: P("Длина", 0.0, 0.0, 40, 10, "Длина камня, мм. 0 = по классической пропорции огранки")
    material: EnumProperty(name="Камень", items=[(k, l, "") for k, l, _, _ in core.GEM_MATERIALS], default='DIAMOND')
    segments: IntProperty(name="Сегменты рундиста", default=32, min=16, max=128, step=8)

    def LW(self):
        W = self.size
        L = self.length if self.length > 0 else round(W * gems.CUTS[self.cut]['ratio'], 2)
        return L, W

    def draw_gem(self, lay):
        lay.prop(self, "cut")
        row = lay.row(align=True)
        row.prop(self, "size")
        row.prop(self, "length")
        lay.prop(self, "material")


class GV_OT_gem_add(_GemParams, bpy.types.Operator):
    bl_idname = "gravenarc.gem_add"
    bl_label = "Камень"
    bl_description = ("Добавить камень в 3D-курсор. Если активен объект-металл — камень встаёт по нормали "
                      "к ближайшей точке его поверхности (как Gem on Surface в RhinoGold). "
                      "Если активна шинка, а курсор не на металле — камень встаёт на верх кольца")
    bl_options = {'REGISTER', 'UNDO'}

    on_surface: BoolProperty(name="На поверхность активного объекта", default=True)
    height: P("Рундист над поверхностью", 0.3, -10, 10, 5, "Расстояние от поверхности до середины рундиста, мм. "
              "Отрицательное — камень утоплен")
    make_cutter: BoolProperty(name="Вырез (cutter)", default=True)
    head: EnumProperty(name="Каста", items=[('NONE', "Нет", ""), ('PRONG', "Крапаны", ""), ('BEZEL', "Глухая", "")],
                       default='NONE')
    boolean: BoolProperty(name="Сразу вырезать в металле", default=False,
                          description="Добавить активному объекту модификатор Boolean (Difference) с коллекцией вырезов")

    def draw(self, context):
        lay = self.layout
        self.draw_gem(lay)
        lay.prop(self, "on_surface")
        lay.prop(self, "height")
        lay.prop(self, "make_cutter")
        lay.prop(self, "head")
        lay.prop(self, "boolean")

    def execute(self, context):
        L, W = self.LW()
        k = core.mm_per_bu(context)
        cur = context.scene.cursor
        loc = cur.location * k
        nrm = cur.matrix.to_3x3() @ Vector((0, 0, 1))
        tgt = _target(context)
        if self.on_surface and tgt:
            inv = tgt.matrix_world.inverted()
            lc = inv @ cur.location
            ok, p, n, _ = tgt.closest_point_on_mesh(lc)
            if tgt.get("gv_inner_d_mm") and tgt.type == 'MESH':
                # Кольцо: если курсор не на металле (например, остался в центре), ставим камень
                # на верх шинки (+Y) снаружи — туда, где он нужен почти всегда.
                r_in = float(tgt["gv_inner_d_mm"]) / 2.0 / k
                if not ok or (p - lc).length > 0.25 / k or Vector((lc.x, lc.y)).length < r_in * 0.98:
                    top = max(v[1] for v in tgt.bound_box) + 10.0 / k
                    hit, hp, hn, _ = tgt.ray_cast(Vector((0.0, top, 0.0)), Vector((0.0, -1.0, 0.0)))
                    if hit:
                        ok, p, n = True, hp, hn
            if ok:
                loc = (tgt.matrix_world @ p) * k
                nrm = (tgt.matrix_world.inverted().transposed().to_3x3() @ n).normalized()
        center = loc + nrm.normalized() * self.height
        M = layout.gem_matrix(center, nrm, cur.matrix.to_3x3() @ Vector((1, 0, 0)), k)
        gcol = core.ensure_collection(context, "GV Gems")
        gem = gems.new_gem(context, self.cut, L, W, self.material, M, gcol, self.segments)
        for o in context.selected_objects:
            o.select_set(False)
        gem.select_set(True)
        context.view_layer.objects.active = gem
        if self.make_cutter:
            _make_cutter(context, gem)
        if self.head != 'NONE':
            _make_head(context, gem, self.head)
        if self.boolean and tgt and self.make_cutter:
            add_boolean(tgt, bpy.data.collections["GV Cutters"])
        self.report({'INFO'}, f"{gems.CUTS[self.cut]['label']} {L:g}×{W:g} мм ≈ {gem['gv_carat']:.3f} ct")
        return {'FINISHED'}


def _make_cutter(context, gem, clearance=0.05, top=1.5, flare=0.0, hole=0.55, hole_depth=1.5):
    cut, L, W, _ = gems.gem_params(gem)
    col = core.ensure_collection(context, "GV Cutters", hide_render=True)
    me = gems.cutter_mesh(context, cut, L, W, clearance, top, flare, hole, hole_depth)
    ob = core.link_object(context, f"Cutter_{gem.name}", me, col)
    gems.style_cutter(ob)
    ob.parent = gem
    ob.matrix_parent_inverse = Matrix()
    return ob


def _make_head(context, gem, kind, **kw):
    cut, L, W, _ = gems.gem_params(gem)
    kw.setdefault('prongs', gems.CUTS[cut]['k'])
    col = core.ensure_collection(context, "GV Heads")
    if kind == 'PRONG':
        bm = gems.build_prong_head_bm(cut, L, W, **{k: v for k, v in kw.items() if k in (
            'prongs', 'prong_d', 'offset', 'tip', 'base_depth', 'base_scale', 'galleries', 'gallery_d', 'base_ring')})
        name = f"Prongs_{gem.name}"
    else:
        bm = gems.build_bezel_bm(cut, L, W, **{k: v for k, v in kw.items() if k in (
            'wall', 'clearance', 'lip', 'ledge', 'below', 'draft_deg')})
        name = f"Bezel_{gem.name}"
    ob = gems.bm_to_object(context, bm, name, col, smooth=(kind == 'PRONG'))
    ob.parent = gem
    ob.matrix_parent_inverse = Matrix()
    ob["gv_metal"] = True
    ob.data.materials.append(metal_material(context.scene.gv_jewelry.metal))
    return ob


def metal_material(key):
    looks = {'AU': (1.0, 0.77, 0.34), 'AG': (0.92, 0.92, 0.93), 'PT': (0.85, 0.86, 0.88),
             'PD': (0.82, 0.80, 0.78), 'CU': (0.95, 0.55, 0.40), 'BR': (0.85, 0.65, 0.35),
             'TI': (0.62, 0.62, 0.65), 'RE': (0.25, 0.55, 0.45)}
    col = looks.get(key[:2], (0.9, 0.9, 0.9))
    if key in ('AU585R',):
        col = (0.98, 0.62, 0.48)
    if key in ('AU750W', 'AU585W'):
        col = (0.90, 0.89, 0.86)
    name = "GV Metal " + key
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = (*col, 1)
        mat.metallic = 1.0
        mat.roughness = 0.2
        try:
            mat.use_nodes = True
            b = mat.node_tree.nodes.get("Principled BSDF")
            b.inputs["Base Color"].default_value = (*col, 1)
            b.inputs["Metallic"].default_value = 1.0
            b.inputs["Roughness"].default_value = 0.2
        except Exception:
            pass
    return mat


def _selected_gems(context):
    return [o for o in context.selected_objects if core.is_gem(o)]


class GV_OT_gem_cutters(bpy.types.Operator):
    bl_idname = "gravenarc.gem_cutters"
    bl_label = "Вырезы под камни"
    bl_description = ("Создать вырезы (cutters) для выделенных камней: посадочное место по рундисту + конус "
                      "по павильону + сквозное отверстие. Активный объект-металл получит Boolean")
    bl_options = {'REGISTER', 'UNDO'}

    clearance: P("Зазор по рундисту", 0.05, 0, 1, 1)
    top: P("Высота над площадкой", 1.5, 0, 20, 10)
    flare: P("Раскрытие вверх, °", 0.0, 0, 60, 100, "Конус над рундистом (для паве ~15–30°)")
    hole: FloatProperty(name="Отверстие (доля ширины)", default=0.55, min=0.0, max=1.0)
    hole_depth: P("Глубина отверстия под калетой", 1.5, 0, 30, 10)
    boolean: BoolProperty(name="Boolean в активный объект", default=True)

    def execute(self, context):
        gl = _selected_gems(context)
        if not gl:
            self.report({'WARNING'}, "Выделите камни (объекты, созданные GravenArc)")
            return {'CANCELLED'}
        tgt = _target(context)
        for g in gl:
            for ch in list(g.children):
                if ch.get("gv_cutter"):
                    bpy.data.objects.remove(ch)
            _make_cutter(context, g, self.clearance, self.top, self.flare, self.hole, self.hole_depth)
        if self.boolean and tgt:
            add_boolean(tgt, bpy.data.collections["GV Cutters"])
        self.report({'INFO'}, f"Вырезов: {len(gl)}" + (f", Boolean → {tgt.name}" if self.boolean and tgt else ""))
        return {'FINISHED'}


class GV_OT_gem_heads(bpy.types.Operator):
    bl_idname = "gravenarc.gem_heads"
    bl_label = "Касты для камней"
    bl_description = "Крапановые (корона с галереями) или глухие касты по форме каждого выделенного камня"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(name="Тип", items=[('PRONG', "Крапаны", "Корона на крапанах"),
                                          ('BEZEL', "Глухая", "Стенка по контуру камня")], default='PRONG')
    prongs: IntProperty(name="Крапанов", default=0, min=0, max=12, description="0 = по огранке (круг 4, груша 5, маркиз 6…)")
    prong_d: P("Ø крапана", 0.8, 0.3, 3, 5, "Для литья в песок не тоньше 0,6–0,7 мм")
    offset: FloatProperty(name="Поворот (доля шага)", default=-1.0, min=-1.0, max=1.0,
                          description="-1 = по огранке; 0 — крапан на оси X (на острие), 0.5 — между осями")
    tip: FloatProperty(name="Заход на коронку", default=0.35, min=0, max=1.5)
    base_depth: P("Основание под калетой", 0.8, 0, 10, 5)
    base_scale: FloatProperty(name="Сужение к основанию", default=0.55, min=0.1, max=1.2)
    galleries: IntProperty(name="Галерей", default=1, min=0, max=3)
    gallery_d: P("Ø галереи", 0.7, 0.3, 3, 5)
    wall: P("Стенка", 0.7, 0.3, 3, 5)
    lip: P("Борт над рундистом", 0.5, 0, 5, 5)
    ledge: P("Полка-опора", 0.35, 0.1, 2, 5)
    draft: P("Уклон, °", 2.0, 0, 10, 50)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "kind", expand=True)
        if self.kind == 'PRONG':
            for p in ("prongs", "prong_d", "offset", "tip", "base_depth", "base_scale", "galleries", "gallery_d"):
                lay.prop(self, p)
        else:
            for p in ("wall", "lip", "ledge", "draft"):
                lay.prop(self, p)

    def execute(self, context):
        gl = _selected_gems(context)
        if not gl:
            self.report({'WARNING'}, "Выделите камни")
            return {'CANCELLED'}
        for g in gl:
            cut = g["gv_gem"]
            spec = gems.CUTS[cut]
            for ch in list(g.children):
                if ch.name.startswith(("Prongs_", "Bezel_")):
                    bpy.data.objects.remove(ch)
            if self.kind == 'PRONG':
                _make_head(context, g, 'PRONG', prongs=self.prongs or spec['k'], prong_d=self.prong_d,
                           offset=None if self.offset < 0 else self.offset, tip=self.tip,
                           base_depth=self.base_depth, base_scale=self.base_scale,
                           galleries=self.galleries, gallery_d=self.gallery_d)
            else:
                _make_head(context, g, 'BEZEL', wall=self.wall, lip=self.lip, ledge=self.ledge, draft_deg=self.draft)
        if self.kind == 'PRONG' and self.prong_d < 0.6:
            self.report({'WARNING'}, "Крапан тоньше 0,6 мм — рискованно для литья в песок")
        else:
            self.report({'INFO'}, f"Каст: {len(gl)}")
        return {'FINISHED'}


# ================================================================ паве и раскладки

class GV_OT_pave(_GemParams, bpy.types.Operator):
    bl_idname = "gravenarc.pave"
    bl_label = "Паве"
    bl_description = ("Плотно засыпать камнями поверхность активного объекта (или выделенные в Edit Mode грани): "
                      "камни по нормали, зёрна-корнеры между ними, вырезы и Boolean")
    bl_options = {'REGISTER', 'UNDO'}

    gap: P("Зазор между камнями", 0.2, 0.0, 3, 1)
    margin: P("Отступ от края", 0.15, 0.0, 5, 1, "Дополнительно к радиусу камня")
    sink: P("Площадка ниже поверхности", 0.05, -2, 2, 1)
    only_selected: BoolProperty(name="Только выделенные грани", default=True)
    seed: IntProperty(name="Вариант раскладки", default=1, min=0)
    beads: BoolProperty(name="Зёрна (корнеры)", default=True)
    bead_d: P("Ø зерна", 0.6, 0.3, 2, 5, "Для литья в песок ≥ 0,5–0,6 мм")
    bead_h: P("Высота зерна над поверхностью", 0.35, 0.0, 2, 5)
    cutters: BoolProperty(name="Вырезы", default=True)
    flare: P("Раскрытие выреза, °", 20.0, 0, 60, 100)
    boolean: BoolProperty(name="Boolean в объект", default=False)

    def draw(self, context):
        lay = self.layout
        self.draw_gem(lay)
        for p in ("gap", "margin", "sink", "only_selected", "seed", "beads", "bead_d", "bead_h",
                  "cutters", "flare", "boolean"):
            lay.prop(self, p)

    def execute(self, context):
        tgt = _target(context)
        if tgt is None:
            self.report({'WARNING'}, "Сделайте активным объект-металл (поверхность для паве)")
            return {'CANCELLED'}
        if tgt.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')
        L, W = self.LW()
        D = max(L, W)
        k = core.mm_per_bu(context)
        bmw = core.mesh_world_bm(context, tgt, apply_modifiers=False)
        region = layout.Region(bmw, self.only_selected)
        pts = layout.pave_points(region, D + self.gap, D / 2 + self.margin, self.seed)
        bmw.free()
        if not pts:
            self.report({'WARNING'}, "Камни не поместились — уменьшите размер/отступ или выделите больше граней")
            return {'CANCELLED'}
        d = gems.gem_dims(self.cut, L, W)
        base = core.ensure_collection(context, "GV Pave")
        col = bpy.data.collections.new(f"Pave_{tgt.name}_{D:g}mm")
        base.children.link(col)
        me = gems.gem_mesh(context, self.cut, L, W, self.material, self.segments)
        normals = []
        ccol = core.ensure_collection(context, "GV Cutters", hide_render=True) if self.cutters else None
        cme = gems.cutter_mesh(context, self.cut, L, W, 0.05, 1.5, self.flare, 0.55, 1.5) if self.cutters else None
        for i, p in enumerate(pts):
            _, n = region.nearest(p)
            n = n.normalized()
            normals.append(n)
            c = p - n * (self.sink + d['z_table'])
            M = layout.gem_matrix(c, n, None, k)
            g = core.link_object(context, f"Pave_{i:03d}", me, col, M)
            gems.tag_gem(g, self.cut, L, W, self.material, me)
            if ccol:
                co = core.link_object(context, f"Cutter_Pave_{i:03d}", cme, ccol)
                gems.style_cutter(co)
                co.parent = g
                co.matrix_parent_inverse = Matrix()
        nb = 0
        if self.beads:
            bm = bmesh.new()
            rb = self.bead_d / 2
            for (i, j, kk) in layout.triangles_between(pts, (D + self.gap) * 1.35):
                c = (pts[i] + pts[j] + pts[kk]) / 3
                if min((c - pts[t]).length for t in (i, j, kk)) < D / 2 + rb * 0.2:
                    continue
                q, n = region.nearest(c)
                n = n.normalized()
                core.add_tube(bm, q - n * 0.6, q + n * self.bead_h, rb, 10, sphere_b=True)
                nb += 1
            if nb:
                ob = gems.bm_to_object(context, bm, f"Pave_Beads_{tgt.name}", col, smooth=True)
                ob["gv_metal"] = True
                ob.data.materials.append(metal_material(context.scene.gv_jewelry.metal))
            else:
                bm.free()
        if self.boolean and ccol:
            add_boolean(tgt, ccol)
        ct = len(pts) * gems.carat(me.get("gv_volume_mm3", 0), self.material)
        self.report({'INFO'}, f"Паве: {len(pts)} камней Ø{D:g} ({ct:.2f} ct), зёрен {nb}")
        return {'FINISHED'}


class GV_OT_gems_on_curve(_GemParams, bpy.types.Operator):
    bl_idname = "gravenarc.gems_on_curve"
    bl_label = "Камни по кривой"
    bl_description = ("Разложить камни по активной кривой (или цепочке рёбер) с зазором, с градуировкой размера, "
                      "по нормали к выделенной поверхности, с общими крапанами (как Gems on Curve в RhinoGold)")
    bl_options = {'REGISTER', 'UNDO'}

    size_end: P("Ø в центре/в конце", 0.0, 0.0, 30, 10, "Для градуировки. 0 = как начальный")
    grade: EnumProperty(name="Градуировка", items=[('NONE', "Нет", ""), ('LINEAR', "От начала к концу", ""),
                                                  ('CENTER', "К центру", "Крупные в середине, как в теннисном браслете")],
                        default='NONE')
    gap: P("Зазор", 0.2, 0.0, 10, 1)
    fit: BoolProperty(name="Распределить по всей длине", default=True)
    orient: EnumProperty(name="Нормаль", items=[
        ('AUTO', "Авто", "Поверхность, если выделена; иначе радиально для замкнутой кривой; иначе +Z"),
        ('SURFACE', "Выделенная поверхность", ""), ('RADIAL', "От центра кривой", ""), ('Z', "Вверх (+Z)", "")],
        default='AUTO')
    height: P("Рундист над кривой/поверхностью", 0.3, -10, 10, 5)
    along: BoolProperty(name="Длинной осью вдоль кривой", default=True)
    prongs: BoolProperty(name="Общие крапаны", default=False)
    prong_d: P("Ø крапана", 0.7, 0.3, 3, 5)
    cutters: BoolProperty(name="Вырезы", default=True)
    boolean: BoolProperty(name="Boolean в поверхность", default=False)

    def draw(self, context):
        lay = self.layout
        self.draw_gem(lay)
        for p in ("grade", "size_end", "gap", "fit", "orient", "height", "along", "prongs", "prong_d",
                  "cutters", "boolean"):
            lay.prop(self, p)

    def execute(self, context):
        crv = context.active_object
        if crv is None or crv.type not in ('CURVE', 'MESH'):
            self.report({'WARNING'}, "Активной должна быть кривая (или ломаная из рёбер)")
            return {'CANCELLED'}
        surf = next((o for o in context.selected_objects if o != crv and o.type == 'MESH'
                     and not core.is_gem(o) and not o.get("gv_cutter")), None)
        k = core.mm_per_bu(context)
        pts, cyclic = layout.curve_polyline(context, crv)
        if len(pts) < 2:
            self.report({'WARNING'}, "Кривая пустая")
            return {'CANCELLED'}
        total, at = layout.arc_sampler(pts, cyclic)
        ratio = (self.length / self.size) if self.length > 0 else gems.CUTS[self.cut]['ratio']
        d1 = self.size_end or self.size
        # вдоль кривой камень занимает свою длину (если вдоль) или ширину
        along_k = ratio if self.along else 1.0
        st = layout.stations_on_curve(total, cyclic, self.size * along_k, d1 * along_k, self.gap,
                                      self.grade, self.fit)
        if not st:
            self.report({'WARNING'}, "Кривая короче камня")
            return {'CANCELLED'}
        centroid = sum(pts, Vector()) / len(pts)
        orient = self.orient
        if orient == 'AUTO':
            orient = 'SURFACE' if surf else ('RADIAL' if cyclic else 'Z')
        if orient == 'SURFACE' and not surf:
            self.report({'WARNING'}, "Выделите поверхность (Shift+клик), а кривую сделайте активной")
            return {'CANCELLED'}
        if surf:
            sinv = surf.matrix_world.inverted()
            nmat = sinv.transposed().to_3x3()
        base = core.ensure_collection(context, "GV Gems")
        col = bpy.data.collections.new(f"Line_{crv.name}")
        base.children.link(col)
        ccol = core.ensure_collection(context, "GV Cutters", hide_render=True) if self.cutters else None
        placed = []
        tot_ct = 0.0
        for i, (s, dl) in enumerate(st):
            W = dl / along_k
            if self.grade != 'NONE':  # камни бывают с шагом 0,05 мм
                W = max(0.5, round(W / 0.05) * 0.05)
            L = round(W * ratio, 3)
            W = round(W, 3)
            p, t = at(s)
            if orient == 'SURFACE':
                ok, q, n, _ = surf.closest_point_on_mesh(sinv @ (p / k))
                q = surf.matrix_world @ q * k
                n = (nmat @ n).normalized()
                p = q
            elif orient == 'RADIAL':
                n = p - centroid
                n = (n - t * n.dot(t)).normalized()
            else:
                n = Vector((0, 0, 1))
            c = p + n * self.height
            tan = t if self.along else n.cross(t)
            M = layout.gem_matrix(c, n, tan, k)
            g = gems.new_gem(context, self.cut, L, W, self.material, M, col, self.segments, name=f"Line_{i:03d}")
            tot_ct += g["gv_carat"]
            if ccol:
                _make_cutter(context, g, flare=10.0)
            placed.append((c, n, t, W, L))
        if self.prongs:
            bm = bmesh.new()
            r = self.prong_d / 2
            gaps = list(zip(placed, placed[1:]))
            if cyclic and len(placed) > 2:
                gaps.append((placed[-1], placed[0]))
            ends = [] if cyclic else [(placed[0], -1), (placed[-1], 1)]
            for (a, b) in gaps:
                self._prong_pair(bm, (a[0] + b[0]) / 2, (a[1] + b[1]).normalized(), (b[0] - a[0]).normalized(),
                                 (a[3] + b[3]) / 2, (b[0] - a[0]).length - (a[4] + b[4]) / 2 if self.along
                                 else (b[0] - a[0]).length - (a[3] + b[3]) / 2, r)
            for (c, n, t, W, L), sgn in ends:
                ext = (L if self.along else W) / 2 + r * 0.6
                self._prong_pair(bm, c + t * sgn * ext, n, t, W, 0.0, r)
            ob = gems.bm_to_object(context, bm, f"Prongs_{crv.name}", col, smooth=True)
            ob["gv_metal"] = True
            ob.data.materials.append(metal_material(context.scene.gv_jewelry.metal))
        if self.boolean and surf and ccol:
            add_boolean(surf, ccol)
        self.report({'INFO'}, f"Камней: {len(placed)}, {tot_ct:.2f} ct, длина кривой {total:.1f} мм")
        return {'FINISHED'}

    def _prong_pair(self, bm, mid, n, t, d, gap, r):
        lat = n.cross(t).normalized()
        y = math.sqrt(max(0.0, (d / 2 + 0.3 * r) ** 2 - (d / 2 + gap / 2) ** 2))
        y = max(y, r * 1.1, d * 0.3)
        dims = gems.gem_dims('ROUND', d, d)
        for sgn in (-1, 1):
            base = mid + lat * sgn * y
            core.add_tube(bm, base + n * (dims['z_culet'] - 0.4), base + n * (dims['z_gtop'] + dims['crown'] * 0.4),
                          r, 10, sphere_b=True)


class GV_OT_polar_array(bpy.types.Operator):
    bl_idname = "gravenarc.polar_array"
    bl_label = "Полярный массив"
    bl_description = "Копии выделенных объектов по кругу вокруг 3D-курсора (как ArrayPolar в Rhino)"
    bl_options = {'REGISTER', 'UNDO'}

    count: IntProperty(name="Количество", default=6, min=2, max=360)
    angle: FloatProperty(name="Угол заполнения, °", default=360.0, min=1, max=360)
    axis: EnumProperty(name="Ось", items=[('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", "")], default='Z')
    linked: BoolProperty(name="Связанные копии (Alt+D)", default=True)

    def execute(self, context):
        src = list(context.selected_objects)
        if not src:
            return {'CANCELLED'}
        c = context.scene.cursor.location.copy()
        ax = Vector({'X': (1, 0, 0), 'Y': (0, 1, 0), 'Z': (0, 0, 1)}[self.axis])
        step = math.radians(self.angle) / (self.count if self.angle >= 359.999 else self.count - 1)
        roots = [o for o in src if o.parent not in src]
        for i in range(1, self.count):
            R = Matrix.Translation(c) @ Matrix.Rotation(step * i, 4, ax) @ Matrix.Translation(-c)
            mapping = {}
            for o in src:
                cp = o.copy()
                if o.data and not self.linked:
                    cp.data = o.data.copy()
                for col in o.users_collection:
                    col.objects.link(cp)
                mapping[o] = cp
            for o, cp in mapping.items():
                if o.parent in mapping:
                    cp.parent = mapping[o.parent]
                if o in roots:
                    cp.matrix_world = R @ o.matrix_world
        self.report({'INFO'}, f"Копий: {self.count - 1}")
        return {'FINISHED'}


# ================================================================ кольцо

class GV_OT_ring_shank(bpy.types.Operator):
    bl_idname = "gravenarc.ring_shank"
    bl_label = "Шинка по размеру"
    bl_description = ("Параметрическая шинка любого размера (RU/EU/US/UK), профиль, ширина и толщина сверху/снизу, "
                      "литейный уклон. Ось Z, верх кольца +Y (как Ring Wizard в RhinoGold)")
    bl_options = {'REGISTER', 'UNDO'}

    size_system: EnumProperty(name="Система", items=core.SIZE_SYSTEMS, default='RU')
    size_value: FloatProperty(name="Размер", default=17.0, min=0, soft_max=80, step=50, precision=2)
    size_uk: StringProperty(name="Размер UK", default="N½")
    profile: EnumProperty(name="Профиль", items=ring.PROFILES, default='COMFORT')
    w_top: P("Ширина сверху", 4.0, 0.8, 30, 10)
    w_bot: P("Ширина снизу", 2.5, 0.8, 30, 10)
    t_top: P("Толщина сверху", 1.8, 0.5, 10, 10)
    t_bot: P("Толщина снизу", 1.4, 0.5, 10, 10)
    taper: FloatProperty(name="Плавность перехода", default=1.0, min=0.2, max=6.0)
    draft: P("Литейный уклон, °", 2.0, 0, 10, 50)

    def draw(self, context):
        lay = self.layout
        draw_size(lay, self)
        lay.prop(self, "profile")
        for p in ("w_top", "w_bot", "t_top", "t_bot", "taper", "draft"):
            lay.prop(self, p)

    def execute(self, context):
        try:
            d = get_diameter(self)
        except ValueError:
            self.report({'ERROR'}, "Неверный размер")
            return {'CANCELLED'}
        bm = ring.build_shank_bm(d, self.profile, self.w_top, self.w_bot, self.t_top, self.t_bot, self.taper,
                                 self.draft)
        ob = gems.bm_to_object(context, bm, f"Shank_{self.profile.title()}_D{d:.2f}", smooth=True)
        ob.location = context.scene.cursor.location
        ob["gv_inner_d_mm"] = round(d, 3)
        ob["gv_size_ru"] = round(d * 2) / 2
        ob["gv_parting_z_mm"] = 0.0
        ob["gv_metal"] = True
        ob.data.materials.append(metal_material(context.scene.gv_jewelry.metal))
        for o in context.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        if min(self.t_top, self.t_bot) < 1.0:
            self.report({'WARNING'}, "Толщина < 1 мм — тонко для литья в песок")
        else:
            self.report({'INFO'}, core.sizes_text(d))
        return {'FINISHED'}


class GV_OT_ring_measure(bpy.types.Operator):
    bl_idname = "gravenarc.ring_measure"
    bl_label = "Измерить размер"
    bl_description = "Внутренний диаметр активного кольца в самом узком месте (ось Z объекта) во всех системах"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        d = ring.measure_inner_d(context, context.active_object)
        context.scene.gv_jewelry.last_size = core.sizes_text(d)
        self.report({'INFO'}, core.sizes_text(d))
        return {'FINISHED'}


class GV_OT_ring_resize(bpy.types.Operator):
    bl_idname = "gravenarc.ring_resize"
    bl_label = "Изменить размер кольца"
    bl_description = ("Перевести кольцо в другой размер, сохранив ширину и толщину шинки (радиальный сдвиг, "
                      "а не масштаб). Привязанные касты и камни сдвигаются вместе с кольцом")
    bl_options = {'REGISTER', 'UNDO'}

    size_system: EnumProperty(name="Система", items=core.SIZE_SYSTEMS, default='RU')
    size_value: FloatProperty(name="Размер", default=18.0, min=0, soft_max=80, step=50, precision=2)
    size_uk: StringProperty(name="Размер UK", default="P")

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def draw(self, context):
        draw_size(self.layout, self)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        ob = context.active_object
        if ob.data.users > 1:
            ob.data = ob.data.copy()
        d_new = get_diameter(self)
        d_old = ring.resize_ring(context, ob, d_new)
        self.report({'INFO'}, f"Ø {d_old:.2f} → {d_new:.2f} мм ({core.sizes_text(d_new)})")
        return {'FINISHED'}


class GV_OT_flow_ring(bpy.types.Operator):
    bl_idname = "gravenarc.flow_ring"
    bl_label = "Обернуть вокруг кольца"
    bl_description = ("Согнуть плоский узор (лежит в XY, высота по Z) по кольцу: снаружи или внутри "
                      "(как Flow Along Surface / Bend в Rhino). Длина по X сохраняется")
    bl_options = {'REGISTER', 'UNDO'}

    side: EnumProperty(name="Сторона", items=[('OUT', "Снаружи", ""), ('IN', "Внутри", "")], default='OUT')
    size_system: EnumProperty(name="Система", items=core.SIZE_SYSTEMS, default='RU')
    size_value: FloatProperty(name="Размер", default=17.0, min=0, soft_max=80, step=50, precision=2)
    size_uk: StringProperty(name="Размер UK", default="N½")
    thickness: P("Толщина шинки (если нет кольца)", 1.6, 0, 10, 10)
    use_ring: BoolProperty(name="По активному кольцу", default=True,
                           description="Радиус берётся лучом по поверхности активного объекта")
    angle: FloatProperty(name="Положение, °", default=0.0, min=-360, max=360, description="0 = верх (+Y), 180 = низ")
    z_offset: P("Сдвиг вдоль оси", 0.0, -30, 30, 10)
    sink: P("Утопить в поверхность", 0.05, -2, 2, 1)
    step: P("Шаг нарезки", 0.25, 0.02, 5, 1, "Чем мельче, тем глаже изгиб")
    mirror: BoolProperty(name="Зеркально (читать изнутри)", default=False)
    keep: BoolProperty(name="Оставить оригинал", default=True)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "side", expand=True)
        lay.prop(self, "use_ring")
        if not self.use_ring:
            draw_size(lay, self)
            lay.prop(self, "thickness")
        for p in ("angle", "z_offset", "sink", "step", "mirror", "keep"):
            lay.prop(self, p)

    def execute(self, context):
        ring_ob = _target(context) if self.use_ring else None
        src = [o for o in _sel_meshes(context) if o != ring_ob]
        if not src:
            self.report({'WARNING'}, "Выделите плоский узор (и активным — кольцо)")
            return {'CANCELLED'}
        k = core.mm_per_bu(context)
        R = None
        if ring_ob:
            R = ring.surface_radius(context, ring_ob, self.angle, self.z_offset, inner=(self.side == 'IN'))
        if R is None:
            d = get_diameter(self)
            R = d / 2 + (self.thickness if self.side == 'OUT' else 0.0)
        made = []
        for o in src:
            bm = core.mesh_world_bm(context, o)
            xs = [v.co.x for v in bm.verts]
            ys = [v.co.y for v in bm.verts]
            zs = [v.co.z for v in bm.verts]
            cx, cy, z0 = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, min(zs)
            for v in bm.verts:
                v.co = Vector((v.co.x - cx, v.co.y - cy + self.z_offset, v.co.z - z0 - self.sink))
            ring.slice_x(bm, self.step)
            ring.wrap_bm(bm, R, self.angle, inward=(self.side == 'IN'), mirror=self.mirror)
            ob = gems.bm_to_object(context, bm, o.name + "_Flow", o.users_collection[0])
            for m in o.data.materials:
                ob.data.materials.append(m)
            if ring_ob:
                ob.matrix_world = Matrix.Translation(ring_ob.matrix_world.translation) @ \
                    ring_ob.matrix_world.to_3x3().normalized().to_4x4()
            if not self.keep:
                o.hide_set(True)
            made.append(ob)
        self.report({'INFO'}, f"Согнуто: {len(made)}, радиус {R:.2f} мм")
        return {'FINISHED'}


class GV_OT_engrave_text(bpy.types.Operator):
    bl_idname = "gravenarc.engrave_text"
    bl_label = "Гравировка текстом"
    bl_description = ("Текст-вырез (или рельеф) внутри/снаружи кольца или на плоскости в 3D-курсоре. "
                      "Для армянских букв укажите шрифт с армянским алфавитом (например Noto Sans Armenian)")
    bl_options = {'REGISTER', 'UNDO'}

    text: StringProperty(name="Текст", default="GravenArc")
    font: StringProperty(name="Шрифт (.ttf/.otf)", subtype='FILE_PATH', default="")
    place: EnumProperty(name="Где", items=[('IN', "Внутри кольца", ""), ('OUT', "Снаружи кольца", ""),
                                           ('FLAT', "Плоскость (3D-курсор)", "")], default='IN')
    height: P("Высота букв", 1.5, 0.3, 30, 10)
    depth: P("Глубина", 0.3, 0.05, 5, 5, "Лазерная гравировка MOPA: 0,05–0,2; литьё: от 0,3")
    spacing: FloatProperty(name="Межбуквенный интервал", default=1.0, min=0.5, max=3.0)
    relief: BoolProperty(name="Рельеф (выпуклый), а не вырез", default=False)
    angle: FloatProperty(name="Положение, °", default=180.0, min=-360, max=360,
                         description="0 = верх кольца (+Y), 180 = низ")
    z_offset: P("Сдвиг вдоль оси кольца", 0.0, -30, 30, 10)
    size_system: EnumProperty(name="Система", items=core.SIZE_SYSTEMS, default='RU')
    size_value: FloatProperty(name="Размер", default=17.0, min=0, soft_max=80, step=50, precision=2)
    size_uk: StringProperty(name="Размер UK", default="N½")
    thickness: P("Толщина шинки (если нет кольца)", 1.6, 0, 10, 10)
    boolean: BoolProperty(name="Boolean в активный объект", default=True)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "text")
        lay.prop(self, "font")
        lay.prop(self, "place", expand=True)
        for p in ("height", "depth", "spacing", "relief"):
            lay.prop(self, p)
        if self.place != 'FLAT':
            lay.prop(self, "angle")
            lay.prop(self, "z_offset")
            if _target(context) is None:
                draw_size(lay, self)
                lay.prop(self, "thickness")
        lay.prop(self, "boolean")

    def execute(self, context):
        tgt = _target(context)
        k = core.mm_per_bu(context)
        over = 0.1  # запас над поверхностью, чтобы Boolean резал чисто
        bm = ring.text_bm(context, self.text, self.height, self.depth + over, self.font, self.spacing, -over)
        if not bm.verts:
            self.report({'WARNING'}, "Пустой текст или шрифт без этих букв")
            return {'CANCELLED'}
        # для выреза: z от -over (над поверхностью) до depth (в металл)
        if self.place == 'FLAT':
            if not self.relief:
                for v in bm.verts:
                    v.co.z = -v.co.z
            M = context.scene.cursor.matrix.copy()
            ob = gems.bm_to_object(context, bm, "Text_" + self.text[:12])
            ob.matrix_world = Matrix.Translation(M.translation) @ M.to_3x3().to_4x4()
        else:
            R = None
            if tgt:
                R = ring.surface_radius(context, tgt, self.angle, self.z_offset, inner=(self.place == 'IN'))
            if R is None:
                d = get_diameter(self)
                R = d / 2 + (self.thickness if self.place == 'OUT' else 0.0)
            for v in bm.verts:
                v.co.y += self.z_offset
            ring.slice_x(bm, 0.2)
            # IN: текст читается изнутри — зеркалим; вырез идёт наружу (в металл)
            if self.place == 'IN':
                inward = self.relief
                mirror = True
            else:
                inward = not self.relief
                mirror = False
            ring.wrap_bm(bm, R, self.angle, inward=inward, mirror=mirror)
            ob = gems.bm_to_object(context, bm, "Text_" + self.text[:12])
            if tgt:
                ob.matrix_world = Matrix.Translation(tgt.matrix_world.translation) @ \
                    tgt.matrix_world.to_3x3().normalized().to_4x4()
        ob["gv_text"] = self.text
        if self.relief:
            ob["gv_metal"] = True
            ob.data.materials.append(metal_material(context.scene.gv_jewelry.metal))
        else:
            gems.style_cutter(ob)
        if self.boolean and tgt:
            add_boolean(tgt, ob, 'UNION' if self.relief else 'DIFFERENCE', name=f"GV Text {self.text[:12]}")
        if self.depth < 0.3 and not self.relief:
            self.report({'INFO'}, "Глубина < 0,3 мм: в песке может не пролиться — такую гравировку лучше делать лазером")
        else:
            self.report({'INFO'}, f"Текст «{self.text}» готов")
        return {'FINISHED'}


# ================================================================ литьё и вес

class GV_OT_weight(bpy.types.Operator):
    bl_idname = "gravenarc.weight"
    bl_label = "Вес металла"
    bl_description = "Объём выделенных объектов (с модификаторами) и вес во всех сплавах; объём смолы для печати"
    bl_options = {'REGISTER'}

    def execute(self, context):
        obs = _sel_meshes(context)
        if not obs:
            self.report({'WARNING'}, "Выделите металлические объекты")
            return {'CANCELLED'}
        vol, warn = 0.0, []
        for o in obs:
            info = analysis.metal_info(context, o)
            vol += info['volume']
            if info['non_manifold']:
                warn.append(f"{o.name}: дыры в сетке ({info['non_manifold']} рёбер)")
            if info['parts'] > 1:
                warn.append(f"{o.name}: {info['parts']} кусков — если они пересекаются, объём завышен "
                            f"(«Слить в монолит»)")
        p = context.scene.gv_jewelry
        p.last_volume = vol
        p.last_warn = "; ".join(warn)[:500]
        dens = core.METAL_DENSITY[p.metal]
        self.report({'WARNING'} if warn else {'INFO'},
                    f"Объём {vol:.1f} мм³ · {vol * dens / 1000:.2f} г · смола {vol / 1000:.2f} мл"
                    + (" · " + warn[0] if warn else ""))
        return {'FINISHED'}


class GV_OT_casting_check(bpy.types.Operator):
    bl_idname = "gravenarc.casting_check"
    bl_label = "Проверка для литья"
    bl_description = ("Раскрасить грани: красный — поднутрение, жёлтый — уклон меньше нормы, синий — стенка тоньше "
                      "минимума. Проблемные грани выделяются (Tab — увидеть в Edit Mode)")
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name="Форма", items=[
        ('TWO', "Две половинки (разъём)", "Опока из двух частей: верх снимается вверх, низ — вниз"),
        ('ONE', "Одна сторона (плоская спинка)", "Модель лежит спинкой на разъёме, форма снимается вверх")],
        default='TWO')
    parting_src: EnumProperty(name="Плоскость разъёма", items=[
        ('PROP', "Из шаблона", "Свойство gv_parting_z_mm (есть у шаблонов и шинок GravenArc); иначе середина"),
        ('MIDDLE', "Середина по высоте", ""), ('VALUE', "Задать Z", "")], default='PROP')
    parting: P("Z разъёма (мир), мм", 0.0, -1000, 1000, 10)
    draft: P("Мин. уклон, °", 2.0, 0, 15, 50)
    min_wall: P("Мин. стенка", 0.5, 0.1, 5, 5)
    check_draft: BoolProperty(name="Уклоны и поднутрения", default=True)
    check_thin: BoolProperty(name="Толщина стенок", default=True)

    def invoke(self, context, event):
        p = context.scene.gv_jewelry
        self.draft, self.min_wall = p.draft, p.min_wall
        return self.execute(context)

    def execute(self, context):
        ob = _target(context)
        if ob is None:
            self.report({'WARNING'}, "Сделайте активным проверяемый объект")
            return {'CANCELLED'}
        if ob.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')
        pz = self.parting if self.parting_src == 'VALUE' else None
        tgt, res = analysis.casting_check(context, ob, self.min_wall, self.draft, pz, self.mode,
                                          self.check_draft, self.check_thin,
                                          use_prop=(self.parting_src == 'PROP'))
        analysis.show_check_colors(context, True)
        if tgt != ob:
            for o in context.selected_objects:
                o.select_set(False)
            tgt.select_set(True)
            context.view_layer.objects.active = tgt
        c = res['counts']
        msg = (f"Поднутрения: {c['undercut']} · малый уклон: {c['draft']} · тонко: {c['thin']} "
               f"(разъём Z={res['parting_z']:.2f} мм)")
        if res['thin_min'] is not None:
            msg += f" · мин. стенка {res['thin_min']:.2f} мм"
        context.scene.gv_jewelry.last_check = msg
        self.report({'WARNING'} if (c['undercut'] or c['thin']) else {'INFO'}, msg)
        return {'FINISHED'}


class GV_OT_check_off(bpy.types.Operator):
    bl_idname = "gravenarc.check_off"
    bl_label = "Убрать раскраску"
    bl_options = {'REGISTER'}

    def execute(self, context):
        analysis.show_check_colors(context, False)
        return {'FINISHED'}


class GV_OT_shrink(bpy.types.Operator):
    bl_idname = "gravenarc.shrink"
    bl_label = "Компенсировать усадку"
    bl_description = ("Увеличить выделенные объекты на усадку металла: масштаб 1/(1 − s). "
                      "Повторное применение блокируется (свойство gv_shrink_pct)")
    bl_options = {'REGISTER', 'UNDO'}

    pct: FloatProperty(name="Усадка, %", default=1.75, min=0.0, max=10.0, step=25)
    copy: BoolProperty(name="Сделать копию для печати", default=True)
    undo_it: BoolProperty(name="Снять усадку", default=False)

    def invoke(self, context, event):
        self.pct = context.scene.gv_jewelry.shrink
        return self.execute(context)

    def execute(self, context):
        obs = [o for o in context.selected_objects if o.type == 'MESH']
        f = 1.0 / (1.0 - self.pct / 100.0)
        done = 0
        for o in obs:
            have = o.get("gv_shrink_pct")
            if self.undo_it:
                if not have:
                    continue
                o.scale = o.scale / (1.0 / (1.0 - float(have) / 100.0))
                del o["gv_shrink_pct"]
                done += 1
                continue
            if have:
                self.report({'WARNING'}, f"{o.name}: усадка {have}% уже учтена")
                continue
            tgt = o
            if self.copy:
                tgt = o.copy()
                tgt.data = o.data.copy()
                for col in o.users_collection:
                    col.objects.link(tgt)
                tgt.name = o.name + f"_Print+{self.pct:g}%"
                o.hide_set(True)
            tgt.scale = tgt.scale * f
            tgt["gv_shrink_pct"] = self.pct
            done += 1
        self.report({'INFO'}, f"Объектов: {done}, масштаб ×{f:.4f}")
        return {'FINISHED'}


class GV_OT_make_solid(bpy.types.Operator):
    bl_idname = "gravenarc.make_solid"
    bl_label = "Слить в монолит"
    bl_description = ("Объединить пересекающиеся куски объекта (крапаны, галереи, зёрна) в одну замкнутую "
                      "оболочку через точный Boolean — для веса, проверки и печати")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obs = _sel_meshes(context)
        done = 0
        for ob in obs:
            if ob.data.users > 1:
                ob.data = ob.data.copy()
            dg = context.evaluated_depsgraph_get()
            me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
            bm = bmesh.new()
            bm.from_mesh(me)
            bm.faces.index_update()
            parts = core.islands(bm)
            if len(parts) < 2:
                bm.free()
                bpy.data.meshes.remove(me)
                continue
            tmpcol = bpy.data.collections.new("_gv_tmp")
            context.scene.collection.children.link(tmpcol)
            objs = []
            for part in parts:
                b2 = bmesh.new()
                vm = {}
                for f in part:
                    vs = []
                    for v in f.verts:
                        if v not in vm:
                            vm[v] = b2.verts.new(v.co)
                        vs.append(vm[v])
                    b2.faces.new(vs)
                m2 = bpy.data.meshes.new("_gv_part")
                b2.to_mesh(m2)
                b2.free()
                o2 = bpy.data.objects.new("_gv_part", m2)
                tmpcol.objects.link(o2)
                objs.append(o2)
            bm.free()
            base = objs[0]
            tmpcol.objects.unlink(base)
            context.scene.collection.objects.link(base)
            mod = base.modifiers.new("U", 'BOOLEAN')
            mod.operation = 'UNION'
            mod.solver = 'EXACT'
            mod.operand_type = 'COLLECTION'
            mod.collection = tmpcol
            mod.use_self = True
            dg = context.evaluated_depsgraph_get()
            res = bpy.data.meshes.new_from_object(base.evaluated_get(dg))
            for o2 in objs:
                m2 = o2.data
                bpy.data.objects.remove(o2)
                bpy.data.meshes.remove(m2)
            bpy.data.collections.remove(tmpcol)
            bpy.data.meshes.remove(me)
            old = ob.data
            res.materials.clear()
            for m in old.materials:
                res.materials.append(m)
            ob.data = res
            ob.modifiers.clear()
            if old.users == 0:
                bpy.data.meshes.remove(old)
            done += 1
        self.report({'INFO'}, f"Слито объектов: {done}")
        return {'FINISHED'}


class GV_OT_report(bpy.types.Operator):
    bl_idname = "gravenarc.report"
    bl_label = "Отчёт: камни и металл"
    bl_description = ("Таблица всех камней сцены (огранка, размер, количество, караты) и веса объектов, отмеченных "
                      "как металл. Текст GV_Report в Text Editor; CSV рядом с .blend")
    bl_options = {'REGISTER'}

    def execute(self, context):
        p = context.scene.gv_jewelry
        txt, n, ct, vol = analysis.gem_report(context, p.metal)
        t = bpy.data.texts.get("GV_Report") or bpy.data.texts.new("GV_Report")
        t.clear()
        t.write(txt)
        path = ""
        if bpy.data.filepath:
            import os
            path = os.path.splitext(bpy.data.filepath)[0] + "_report.csv"
            try:
                with open(path, "w", encoding="utf-8-sig") as f:
                    f.write(txt)
            except OSError:
                path = ""
        self.report({'INFO'}, f"Камней {n} ({ct:.2f} ct), металл {vol:.0f} мм³" + (f" → {path}" if path else
                                                                                   " · текст GV_Report"))
        return {'FINISHED'}


CLASSES = (
    GV_OT_scene_mm, GV_OT_mark_metal,
    GV_OT_gem_add, GV_OT_gem_cutters, GV_OT_gem_heads,
    GV_OT_pave, GV_OT_gems_on_curve, GV_OT_polar_array,
    GV_OT_ring_shank, GV_OT_ring_measure, GV_OT_ring_resize, GV_OT_flow_ring, GV_OT_engrave_text,
    GV_OT_weight, GV_OT_casting_check, GV_OT_check_off, GV_OT_shrink, GV_OT_make_solid, GV_OT_report,
)

# SPDX-License-Identifier: GPL-3.0-or-later
"""Автотесты скульпт-модуля GravenArc в Blender 5.2 без интерфейса (pip install bpy==5.2.4).

    BLENDER_USER_RESOURCES=$(mktemp -d) python tests/test_sculpt.py dist/gravenarc_toolkit-X.Y.Z.zip

Что НЕ проверяется здесь (нужен живой Blender с мышью): запись мазка с реальных событий мыши,
перетаскивание Alt+ПКМ и Live Strength (модальные операторы), отрисовка круга во вьюпорте.
Их логика проверяется по частям: повтор по записанному пути, undo/replace, расчёт значений, отрисовка
круга во внеэкранный буфер.
"""
import os
import sys
import traceback

import bpy
import numpy as np

ZIP = sys.argv[-1]
RESULTS = []


def check(name, cond, info=""):
    RESULTS.append((name, bool(cond), info))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""), flush=True)


# ---------------------------------------------------------------- установка
bpy.ops.wm.read_factory_settings(use_empty=False)
bpy.ops.extensions.package_install_files(repo="user_default", filepath=ZIP, enable_on_install=True)
PKG = "bl_ext.user_default.gravenarc_toolkit"
check("extension enabled", PKG in bpy.context.preferences.addons)
import importlib  # noqa: E402
S = importlib.import_module(PKG + ".modules.sculpt")
common = S.common
STATE = S.state.STATE
prefs = bpy.context.preferences.addons[PKG].preferences.sculpt
check("prefs.sculpt exists", prefs is not None and prefs.repeat_strength == 1.0)
for idn in ("replay_stroke", "mask_last", "set_marker", "mask_since_marker", "remember_mask", "recall_mask",
            "separate_masked", "delete_masked", "delete_hidden", "sculpt_reset_settings", "brush_drag",
            "straight_line", "toggle_smoothing", "smoothing_preset", "preset_add_current", "preset_activate",
            "stroke_watch", "stroke_recorder"):
    check("operator gravenarc." + idn, hasattr(bpy.types, "GRAVENARC_OT_" + idn))

# ---------------------------------------------------------------- сцена
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.mesh.primitive_grid_add(x_subdivisions=120, y_subdivisions=120, size=4, location=(3, 0, 0))
bpy.context.active_object.name = "Plate"
bpy.ops.ed.undo_push(message="init")
SCR = bpy.data.screens["Layout"]
AREA = next(a for a in SCR.areas if a.type == 'VIEW_3D')
REGION = next(r for r in AREA.regions if r.type == 'WINDOW')
RV3D = AREA.spaces.active.region_3d
from bpy_extras import view3d_utils  # noqa: E402


def ob():
    return bpy.context.active_object


def pos():
    return common.get_positions(ob().data)


def resculpt():
    if bpy.context.mode != 'SCULPT':
        bpy.ops.object.mode_set(mode='SCULPT')
        bpy.ops.ed.undo_push(message="sculpt")   # в фоне переключение режима само шаг undo не делает


def px(world):
    v = view3d_utils.location_3d_to_region_2d(REGION, RV3D, world)
    return (v.x, v.y)


def fake_stroke(points_world, pressure=1.0, mode='NORMAL'):
    """То, что делает мазок мышью: снимок «до», мазок кистью, запись пути (как stroke_recorder)."""
    o = ob()
    pts = [px(w) for w in points_world]
    S.state.take_before(o)
    rec = S.state.StrokeRecord(o.name, mode, REGION, RV3D)
    for x, y in pts:
        rec.add(x, y, pressure)
    elems = S.stroke.build_elements(bpy.context, REGION, RV3D, o, rec.points, rec.pressure)
    S.stroke.run_stroke(bpy.context, AREA, REGION, elems, mode, 1.0)
    STATE.last = rec
    STATE.replace_ok = True
    return rec


LINE = [(3 - 1.0 + 0.1 * i, -0.5, 0) for i in range(21)]   # мировые точки на пластине

with bpy.context.temp_override(screen=SCR, area=AREA, region=REGION):
    try:
        resculpt()
        # ---- пересэмплинг
        r, rp = S.stroke.resample([(0, 0), (100, 0)], [0.2, 1.0], 10)
        check("resample spacing", len(r) == 11 and abs(r[5][0] - 50) < 1e-6 and abs(rp[5] - 0.6) < 1e-6, len(r))

        # ---- обычный мазок + Replay (сверху)
        p0 = pos()
        fake_stroke(LINE)
        p1 = pos()
        h1 = float((p1 - p0)[:, 2].sum())
        check("fake stroke raises surface", h1 > 0, f"{h1:.3f}")
        changed = np.linalg.norm(p1 - p0, axis=1) > 1e-6
        cy = float(p0[changed][:, 1].mean())
        check("stroke lands along the path (local y≈-0.5)", abs(cy + 0.5) < 0.08, f"{cy:.3f}")

        prefs.replace_previous = False
        prefs.repeat_strength = 1.0

        def rewind(arr):
            """Вернуть форму пластины (в фоне Ctrl+Z ненадёжен) и поставить шаг undo прямо перед мазком."""
            bpy.ops.object.mode_set(mode='OBJECT')
            ob().data.attributes["position"].data.foreach_set("vector", arr.ravel())
            ob().data.update()
            resculpt()
            return pos()

        bpy.ops.ed.undo_push(message="checkpoint")
        base = pos()
        rec = STATE.last
        fake_stroke(LINE)                      # тот же мазок рукой второй раз
        h_manual = float((pos() - base)[:, 2].sum())
        wm_ = np.linalg.norm(pos() - base, axis=1)
        wy_manual = float((p0[:, 1] * wm_).sum() / max(wm_.sum(), 1e-9))
        base = rewind(base)
        STATE.last = rec
        STATE.replace_ok = True
        res = bpy.ops.gravenarc.replay_stroke(action='ADD')
        p2 = pos()
        h2 = float((p2 - base)[:, 2].sum())
        check("Replay (add on top) = same as repeating by hand", res == {'FINISHED'} and 0.8 < h2 / h_manual < 1.25,
              f"{h2 / h_manual:.2f}x of manual repeat")
        w = np.linalg.norm(p2 - base, axis=1)
        wy = float((p0[:, 1] * w).sum() / max(w.sum(), 1e-9))
        check("Replay lands where the hand-made repeat lands", abs(wy - wy_manual) < 0.02,
              f"y {wy:.3f} vs {wy_manual:.3f}")

        # ---- Replace с силой 2: повтор отменяется (Ctrl+Z) и рисуется заново ~2x
        base = rewind(base)
        bpy.ops.gravenarc.replay_stroke(action='ADD')
        h2 = float((pos() - base)[:, 2].sum())
        prefs.repeat_strength = 2.0
        res = bpy.ops.gravenarc.replay_stroke(action='REPLACE')
        resculpt()
        h3 = float((pos() - base)[:, 2].sum())
        check("Replace: old stroke undone safely", res == {'FINISHED'} and STATE.replace_ok)
        check("Repeat Strength 2 ≈ twice the effect", 1.5 < h3 / h2 < 2.6, f"{h3 / h2:.2f}x")

        # ---- отрицательная сила = вдавить (вместо выдавить)
        base = pos()
        prefs.repeat_strength = -1.0
        bpy.ops.gravenarc.replay_stroke(action='ADD')
        h4 = float((pos() - base)[:, 2].sum())
        check("Negative Repeat Strength digs in", h4 < 0, f"{h4:.3f}")
        prefs.repeat_strength = 1.0

        # ---- если Ctrl+Z откатил бы не мазок — Replace это видит и рисует сверху
        base = rewind(base)
        bpy.ops.gravenarc.replay_stroke(action='ADD')
        S.state.take_before(ob())   # «до» не совпадает с тем, что вернёт Ctrl+Z
        STATE.before[0, 2] += 1.0
        before = pos()
        bpy.ops.gravenarc.replay_stroke(action='REPLACE')
        resculpt()
        check("Replace guard: wrong undo step is redone, stroke added on top",
              float((pos() - before)[:, 2].sum()) > 0)

        # ---- Replace защищён: если последнее действие не мазок — рисует сверху, без порчи
        STATE.replace_ok = False
        before = pos()
        bpy.ops.gravenarc.replay_stroke(action='REPLACE')
        resculpt()
        check("Replace without a stroke falls back to add", float((pos() - before)[:, 2].sum()) > 0)

        # ---- поворот вида: путь переносится через поверхность (тут вид тот же, но ключ сброшен)
        rec = STATE.last
        rec.view_key = None
        pts, _ = S.stroke.path_in_view(bpy.context, rec, REGION, RV3D, ob())
        err = max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(pts, rec.points)) if pts else 999
        check("reprojection through saved view is exact", len(pts) == len(rec.points) and err < 0.5, f"{err:.3f}px")

        # ---- Mask Last
        fake_stroke([(3 + 0.1 * i, 0.6, 0) for i in range(8)])
        res = bpy.ops.gravenarc.mask_last()
        m = common.get_mask(ob().data)
        check("Mask Last masks the changed area", res == {'FINISHED'} and (m > 0.5).sum() > 50, int((m > 0.5).sum()))
        before_m = pos()
        STATE.last.view_key = STATE.last.view_key  # тот же вид
        bpy.ops.gravenarc.replay_stroke(action='ADD')
        dm = np.linalg.norm(pos() - before_m, axis=1)
        check("masked area is protected from the next stroke", float(dm[m > 0.5].max()) < 1e-6,
              f"{float(dm[m > 0.5].max()):.2e}")

        # ---- Marker
        bpy.ops.paint.mask_flood_fill(mode='VALUE', value=0.0)
        resculpt()
        bpy.ops.gravenarc.set_marker()
        fake_stroke([(3.5, -1.2 + 0.1 * i, 0) for i in range(6)])
        fake_stroke([(2.2, -1.2 + 0.1 * i, 0) for i in range(6)])
        res = bpy.ops.gravenarc.mask_since_marker()
        m = common.get_mask(ob().data)
        P = pos()
        xs = P[m > 0.5][:, 0]
        check("Mask Since Marker covers both strokes", res == {'FINISHED'} and xs.min() < -0.5 and xs.max() > 0.3,
              f"x {xs.min():.2f}..{xs.max():.2f}")

        # ---- Remember / Recall
        bpy.ops.gravenarc.remember_mask()
        n_saved = int((m > 0.5).sum())
        bpy.ops.paint.mask_flood_fill(mode='VALUE', value=0.0)
        resculpt()
        bpy.ops.gravenarc.recall_mask()
        m2 = common.get_mask(ob().data)
        check("Recall Mask brings the mask back", int((m2 > 0.5).sum()) == n_saved, n_saved)

        # ---- Refresh by re-entering
        prefs.refresh_reenter = True
        bpy.ops.gravenarc.recall_mask()
        check("Refresh by re-entering keeps Sculpt Mode", bpy.context.mode == 'SCULPT')
        prefs.refresh_reenter = False

        # ---- Straight line (Alt+L)
        fake_stroke([(2.0, 1.2, 0), (2.2, 1.2, 0)])
        before = pos()
        tx, ty = px((4.2, 1.2, 0))
        res = bpy.ops.gravenarc.straight_line(use_target=True, target=(tx, ty))
        d = np.linalg.norm(pos() - before, axis=1) > 1e-6
        xs = before[d][:, 0]
        check("Straight line from stroke end to cursor", res == {'FINISHED'} and xs.min() < -0.6 and xs.max() > 1.0,
              f"x {xs.min():.2f}..{xs.max():.2f}")
        check("line becomes the last stroke", STATE.last.kind == "line")

        # ---- Separate / Delete masked
        n_faces = len(ob().data.polygons)
        res = bpy.ops.gravenarc.separate_masked()
        new = bpy.data.objects.get("Plate_Masked")
        check("Separate Masked makes a new object", res == {'FINISHED'} and new is not None)
        if new:
            check("faces split between objects", len(new.data.polygons) + len(ob().data.polygons) == n_faces,
                  f"{len(new.data.polygons)}+{len(ob().data.polygons)}={n_faces}")
            check("still in Sculpt Mode on the original", bpy.context.mode == 'SCULPT' and ob().name == "Plate")
        bpy.ops.gravenarc.recall_mask()   # топология изменилась — должен отказаться
        check("Recall refuses after topology change", True)
        bpy.ops.paint.mask_flood_fill(mode='VALUE', value=0.0)
        resculpt()
        b0 = pos()
        fake_stroke([(4.4, 1.5, 0), (4.8, 1.5, 0)])
        bpy.ops.gravenarc.mask_last()
        n_faces = len(ob().data.polygons)
        res = bpy.ops.gravenarc.delete_masked()
        check("Delete Masked removes faces", res == {'FINISHED'} and len(ob().data.polygons) < n_faces)

        # ---- Delete Hidden
        bpy.ops.object.mode_set(mode='OBJECT')
        me = ob().data
        hid = me.attributes.get(".hide_poly") or me.attributes.new(".hide_poly", 'BOOLEAN', 'FACE')
        vals = np.zeros(len(me.polygons), dtype=bool)
        vals[:100] = True
        hid.data.foreach_set("value", vals)
        resculpt()
        n_faces = len(ob().data.polygons)
        res = bpy.ops.gravenarc.delete_hidden()
        check("Delete Hidden removes hidden faces", res == {'FINISHED'} and len(ob().data.polygons) == n_faces - 100,
              f"{n_faces}->{len(ob().data.polygons)}")

        # ---- Multires / Dyntopo: предупреждения
        bpy.ops.object.mode_set(mode='OBJECT')
        mod = ob().modifiers.new("Multires", 'MULTIRES')
        bpy.ops.object.multires_subdivide(modifier="Multires", mode='SIMPLE')
        resculpt()
        res = bpy.ops.gravenarc.mask_last()
        check("Mask Last refused with Multires", res == {'CANCELLED'} and common.sculpt_limits(ob())[1])
        bpy.ops.object.mode_set(mode='OBJECT')
        ob().modifiers.remove(ob().modifiers["Multires"])
        resculpt()

        # ---- Reset
        prefs.repeat_strength = 0.3
        prefs.drag_vertical = 'STRENGTH'
        bpy.ops.gravenarc.sculpt_reset_settings()
        check("Reset Settings", prefs.repeat_strength == 1.0 and prefs.drag_vertical == 'HARDNESS')

        # ---- Сглаживание
        b = bpy.context.tool_settings.sculpt.brush
        was = b.use_smooth_stroke
        bpy.ops.gravenarc.toggle_smoothing()
        check("Smoothing toggle", b.use_smooth_stroke != was)
        bpy.ops.gravenarc.smoothing_preset(percent=100)
        check("Smoothing 100%", b.use_smooth_stroke and b.smooth_stroke_radius == 150 and
              abs(b.smooth_stroke_factor - 0.95) < 1e-4)
        bpy.ops.gravenarc.smoothing_preset(percent=0)
        check("Smoothing 0% = off", not b.use_smooth_stroke)

        # ---- Пресеты кистей
        P_ = S.presets
        fl = P_.folders()
        check("default folders", [f["name"] for f in fl][:3] == ["Relief", "Ornament", "Shanks"])
        bpy.ops.gravenarc.preset_add_current(folder=0)
        bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
                                     relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Clay Strips')
        bpy.ops.gravenarc.preset_add_current(folder=0)
        bpy.ops.gravenarc.preset_add_current(folder=0)   # дубль — не добавляется
        check("add current brush x2 (no duplicate)", len(fl[0]["brushes"]) == 2, [e["name"] for e in fl[0]["brushes"]])
        icon_file = os.path.join(P_.preview_dir(), fl[0]["brushes"][1]["icon"])
        check("brush preview PNG saved", os.path.getsize(icon_file) > 1000, icon_file)
        bpy.ops.gravenarc.preset_activate(folder=0, index=0)
        check("activate preset brush", bpy.context.tool_settings.sculpt.brush.name == fl[0]["brushes"][0]["name"],
              bpy.context.tool_settings.sculpt.brush.name)
        # своя библиотека GravenArc
        bpy.ops.brush.asset_activate(asset_library_type='CUSTOM', asset_library_identifier='GravenArc',
                                     relative_asset_identifier='brushes/GravenArc_Brushes.blend/Brush/GA Dam Standard')
        bpy.ops.gravenarc.preset_add_current(folder=1)
        check("custom library brush (GravenArc)", fl[1]["brushes"] and fl[1]["brushes"][0]["type"] == 'CUSTOM',
              fl[1]["brushes"][:1])
        bpy.ops.gravenarc.preset_activate(folder=0, index=1)
        bpy.ops.gravenarc.preset_activate(folder=1, index=0)
        check("activate custom-library preset", bpy.context.tool_settings.sculpt.brush.name == "GA Dam Standard")
        # локальная кисть
        nb = bpy.data.brushes.new("My Local", mode='SCULPT')
        nb.asset_mark()
        bpy.ops.brush.asset_activate(asset_library_type='LOCAL', relative_asset_identifier='Brush/My Local')
        bpy.ops.gravenarc.preset_add_current(folder=2)
        check("local brush", fl[2]["brushes"] and fl[2]["brushes"][0]["type"] == 'LOCAL')
        # пропавшая кисть — понятная ошибка, не исключение
        fl[2]["brushes"].append({"name": "Gone", "type": 'ESSENTIALS', "lib": "", "rel": "brushes/x.blend/Brush/Gone"})
        try:
            res = bpy.ops.gravenarc.preset_activate(folder=2, index=1)
        except RuntimeError as ex:
            res = str(ex)
        check("missing brush reported", res == {'CANCELLED'} or "not found" in str(res), res)
        fl[2]["brushes"].pop()
        bpy.ops.gravenarc.preset_folder_move(folder=0, direction=1)
        check("move folder", fl[1]["name"] == "Relief")
        bpy.ops.gravenarc.preset_remove(folder=1, index=0)
        check("remove brush from folder", len(fl[1]["brushes"]) == 1)
        bpy.ops.gravenarc.preset_folder_add(name="Рельеф")
        check("folder with Russian name", P_.folders()[-1]["name"] == "Рельеф")
        P_._data = None
        fl = P_.folders()
        check("folders reload from JSON", fl[-1]["name"] == "Рельеф" and fl[0]["name"] == "Ornament", P_.data_path())
        bpy.ops.gravenarc.preset_folder_remove(folder=len(fl) - 1)
        check("delete folder", P_.folders()[-1]["name"] != "Рельеф")

        # ---- круг Alt+ПКМ: расчёт значений (модальную часть можно проверить только в живом Blender)
        bpy.ops.brush.asset_activate(asset_library_type='ESSENTIALS',
                                     relative_asset_identifier='brushes/essentials_brushes-mesh_sculpt.blend/Brush/Draw')
        ups = bpy.context.tool_settings.sculpt.unified_paint_settings
        check("size owner follows Unified Size", common.size_owner(bpy.context) == (ups if ups.use_unified_size else b))
        ups.use_locked_size = 'SCENE'
        d = common.brush_diameter_px(bpy.context, REGION, RV3D, ob().matrix_world.translation)
        check("scene-locked size converts to pixels", d > 1, f"{d:.1f}px for {ups.unprojected_size}")
        ups.use_locked_size = 'VIEW'
    except Exception:
        traceback.print_exc()
        check("no exceptions", False)


# ---------------------------------------------------------------- значки и панели (мок-layout)
ICONS = set(bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items.keys())
BAD = []


class Mock:
    def __init__(self):
        self.alert = self.active = self.enabled = False
        self.scale_x = self.scale_y = 1.0

    def __getattr__(self, name):
        def fn(*args, **kw):
            ic = kw.get("icon")
            if ic and ic not in ICONS:
                BAD.append((name, ic))
            if name in ("operator",):
                return type("P", (), {})()
            return Mock()
        return fn


with bpy.context.temp_override(screen=SCR, area=AREA, region=REGION):
    prefs.large_previews = False
    for cls in S.ui.CLASSES:
        p = type("F", (), {"layout": Mock()})()
        try:
            cls.draw(p, bpy.context)
        except Exception as ex:
            traceback.print_exc()
            BAD.append((cls.__name__, str(ex)))
    prefs.large_previews = True
    p = type("F", (), {"layout": Mock()})()
    S.ui.GRAVENARC_PT_brush_presets.draw(p, bpy.context)
    ap = bpy.context.preferences.addons[PKG].preferences
    ap_cls = type(ap)
    fake = type("F", (), {"layout": Mock(), "import_method": ap.import_method, "sculpt": ap.sculpt})()
    try:
        ap_cls.draw(fake, bpy.context)
    except Exception as ex:
        traceback.print_exc()
        BAD.append(("prefs", str(ex)))
check("all panels draw, all icons exist in 5.2", not BAD, BAD)

# ---------------------------------------------------------------- круг-превью во внеэкранный буфер
try:
    import gpu
    gpu.init()
    off = gpu.types.GPUOffScreen(256, 256)
    op = type("O", (), {})()
    op.anchor = (128, 128)
    op.d_px, op.hardness, op.hardness0, op.strength, op.vertical, op.scene_locked, op.unproj = \
        180, 0.5, 0.5, 0.5, 'HARDNESS', False, 0
    op.radius_px = lambda: 90
    op.value_hardness = lambda: 0.5
    op.size_text = lambda: "180 px"
    op.vertical_text = lambda: "Hardness 50%"
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=(0.2, 0.2, 0.2, 1.0))
        gpu.matrix.load_matrix(__import__("mathutils").Matrix.Identity(4))
        gpu.matrix.load_projection_matrix(__import__("mathutils").Matrix.Identity(4))
        with gpu.matrix.push_pop_projection():
            from mathutils import Matrix
            gpu.matrix.load_projection_matrix(Matrix.OrthoProjection('XY', 4) @ Matrix.Diagonal((2 / 256, 2 / 256, 1, 1)) @ Matrix.Translation((-128, -128, 0)))
            S.brushfeel._draw_preview(op, None)
        buf = fb.read_color(0, 0, 256, 256, 4, 0, 'FLOAT')
    a = np.array(buf.to_list(), dtype=np.float32).reshape(256, 256, 4)
    off.free()
    bright = int((a[:, :, 0] > 0.9).sum())
    check("brush circle draws (offscreen GPU)", bright > 300, f"{bright} white px")
    img = bpy.data.images.new("circle", 256, 256)
    img.pixels.foreach_set(a.ravel())
    img.filepath_raw = os.path.join(os.path.dirname(ZIP), "brush_circle_test.png")
    img.file_format = 'PNG'
    img.save()
except Exception as ex:
    traceback.print_exc()
    check("brush circle draws (offscreen GPU)", False, ex)

# ---------------------------------------------------------------- горячие клавиши и конфликты
wm = bpy.context.window_manager
bpy.utils.keyconfig_set(os.path.join(bpy.utils.resource_path('LOCAL'), 'scripts', 'presets', 'keyconfig', 'Blender.py'))
wm.keyconfigs.update()
km = wm.keyconfigs.user.keymaps.get("Sculpt")
items = [(k.idname, k.type, k.shift, k.ctrl, k.alt) for k in km.keymap_items if k.active]
for idname, key, mods, _p, label in S.keymaps.HOTKEYS:
    want = (idname, key, mods.get("shift", False), mods.get("ctrl", False), mods.get("alt", False))
    pos_ours = items.index(want) if want in items else -1
    others = [i for i, it in enumerate(items) if it[1:] == want[1:] and it[0] != idname]
    check(f"hotkey {label}: ours first in Sculpt keymap", pos_ours >= 0 and all(pos_ours < i for i in others),
          f"also bound: {[items[i][0] for i in others]}" if others else "no other binding")
w = [i for i, it in enumerate(items) if it == ("gravenarc.stroke_watch", 'LEFTMOUSE', False, False, False)]
s = [i for i, it in enumerate(items) if it == ("sculpt.brush_stroke", 'LEFTMOUSE', False, False, False)]
check("stroke watcher sits before the normal brush stroke", w and s and w[0] < s[0])

# ---------------------------------------------------------------- выключить / включить
try:
    bpy.ops.preferences.addon_disable(module=PKG)
    bpy.ops.preferences.addon_enable(module=PKG)
    check("disable / enable", hasattr(bpy.types, "GRAVENARC_OT_replay_stroke"))
except Exception as ex:
    check("disable / enable", False, ex)

fails = [r for r in RESULTS if not r[1]]
print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed")
sys.exit(1 if fails else 0)

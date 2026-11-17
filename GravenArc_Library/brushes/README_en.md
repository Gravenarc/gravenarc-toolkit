# GravenArc ZBrush-style brushes for Blender 5.2 LTS

![GravenArc brushes](brushes_preview.png)


25 brush assets for jewelry sculpting. File: `brushes/GravenArc_Brushes.blend`.
The catalogs live in the shared `GravenArc_Library/blender_assets.cats.txt` (alphas and templates use the same file).

> If you installed the **GravenArc Toolkit** add-on (`gravenarc_toolkit-1.1.2.zip`), the library is already connected: skip section 1.

```
GravenArc_Library/              ← the asset library root
├── blender_assets.cats.txt     ← catalogs (shared by the whole library)
├── brushes/GravenArc_Brushes.blend
├── alphas/  templates/          ← other parts of the kit
└── tools/make_brushes.py        ← brush generator
```

---

## 1. Connect the library (once)

1. Copy the whole `GravenArc_Library` folder, for example to `D:\Blender\GravenArc_Library`. Do not split the files between folders: without `blender_assets.cats.txt` in the root the brushes end up in "Unassigned".
2. **Edit → Preferences** (top menu) → **File Paths** tab → **Asset Libraries** section → **+** button.
3. Choose the `GravenArc_Library` folder (the folder itself, not `brushes`). Name: `GravenArc`.
4. Close Preferences (they save automatically if Auto-Save Preferences is on; otherwise ☰ menu bottom left → **Save Preferences**).

## 2. Set the scene to millimetres

The "mm" brushes (Groove, Bead) assume **1 Blender unit = 1 mm**.

1. **Properties** (right) → **Scene** tab (cone with balls) → **Units**.
2. Unit System: **Metric**, Unit Scale: **0.001**, Length: **Millimeters**.
3. Export STL/OBJ from Rhino in millimetres and import with Scale = 1.0: an 18 mm ring shows as 18 mm.

Tip: save this empty scene as your startup file: **File → Defaults → Save Startup File**.

## 3. Pick a brush

1. Select the model → **Ctrl+Tab** (or the mode drop-down at the top left) → **Sculpt Mode**.
2. The **Asset Shelf** appears at the bottom of the 3D Viewport. On its left is the list of libraries/catalogs: choose **GravenArc → Brushes → Build / Carve / Flatten / …**
   If there is no shelf: hover over the 3D Viewport and press **Shift+Space** to open the brush pop-up shelf, or click the small arrow at the bottom edge of the viewport.
3. Click a brush icon. The icon shows the stroke profile: the colour is the group, a white strip at the bottom marks a millimetre brush.
4. Search the shelf: type `dam`, `polish`, `mm`, `ZBrush`; the brushes are tagged with their ZBrush names.

## 4. Sculpting hotkeys (ZBrush → Blender)

| Action | ZBrush | Blender |
|---|---|---|
| Brush size | S | **F**, move the mouse, click |
| Strength | U | **Shift+F** |
| Invert (raise ↔ carve) | Alt | **Ctrl** while stroking |
| Smooth | Shift | **Shift** while stroking (uses the Smooth brush) |
| Mask | Ctrl | **GA Mask Pen** brush; **Ctrl** erases the mask |
| Mask menu / clear / invert | — | **A** (mask pie menu), **Alt+M**, **Ctrl+I** |
| Voxel remesh / voxel size | DynaMesh | **Ctrl+R** / **R** |
| Undo / redo | Ctrl+Z | **Ctrl+Z** / **Ctrl+Shift+Z** |
| Frame all / selected | F | **Home** / **Numpad .** |
| Front / side / top view | — | **Numpad 1 / 3 / 7** |

Symmetry: the "butterfly" icon on the right of the 3D Viewport header (X/Y/Z).
Lazy Mouse (already on for Dam Standard, Orb Cracks, Groove): Tool panel (**N** → Tool tab) → **Stroke → Stabilize Stroke**.

## 5. What is in the kit

**Build: adding volume**
- **GA Clay Buildup** (ZBrush Clay Buildup): square strokes, fast blocking.
- **GA Clay**: soft clay, fills hollows.
- **GA Standard**: basic raise.
- **GA Inflate**: inflate.
- **GA Layer**: even layer of fixed height: rims, relief plateaus.
- **GA Blob**: balls and drops.
- **GA Bead 0.8 mm**: ~0.8 mm granulation, placed as dots (one click = one bead).

**Carve: cutting and engraving**
- **GA Dam Standard** (Dam_Standard): sharp cut with pinched edges; with **Ctrl** it makes a ridge.
- **GA Orb Cracks**: fine crack without pinch.
- **GA Pinch**: pulls towards the line, sharpens edges.
- **GA Groove 0.5 mm / 1.0 mm**: groove of a set width in mm, independent of zoom. 0.5 mm is the minimum for sand casting.

**Flatten: planes and polishing**
- **GA hPolish**: hard polish with crisp bevels.
- **GA Trim Dynamic**: cuts off bumps, does not fill hollows.
- **GA Flatten**: flattens to the average plane.
- **GA Fill**: fills hollows up to the plane.
- **GA Planar Cut**: two angled planes: facets, sharp edges.

**Smooth**: **GA Smooth**, **GA Smooth Surface** (keeps volume).

**Move**: **GA Move**, **GA Move Topological** (does not drag neighbouring parts), **GA Move Elastic**, **GA Snakehook** (curls, tendrils), **GA Nudge**.

**Mask**: **GA Mask Pen**.

## 6. Screen size vs size in mm

- Most brushes work like ZBrush: the radius is in screen pixels.
- To make a brush keep its size in mm: **N → Tool → Brush Settings → Radius Unit: Scene**. Each brush already has a sensible diameter (Build 3 mm, Carve 1 mm, Flatten 4 mm, Move 10 mm).
- **GA Groove** and **GA Bead** are already in Scene mode.

## 7. If you change brush settings

Library brushes are not overwritten when you edit them: changes last for the current session.
To keep your own version: in the Tool panel open the brush menu (▾ arrow next to the name) → **Save as Brush Asset…**; the copy goes to your personal brush library. **Revert Brush Asset** in the same menu restores the original settings.

## 8. Sand casting: what to keep in mind while sculpting

- **Undercuts.** Dam Standard, Pinch and Snakehook easily create overhangs. Check the model from the top (**Numpad 7**), along the mould pull direction: anything hidden under a ledge is an undercut. The **Casting check** button of the jewelry tools paints them red.
- **Draft.** Make groove walls sloped, not vertical: GA Groove already gives a V profile. After Trim/hPolish soften the edges with **Shift** smoothing.
- **Thin spots.** Grooves and bridges: no less than 0.5 mm. Measure with the ruler: in Object or Edit Mode, toolbar on the left (**T**) → **Measure** tool.
- **Shrinkage of 1.5–2 %** is added by scaling the finished model before printing, not with brushes.

## 9. Rebuild the brush file (for development)

Requires Blender 5.2. From a terminal, in the `GravenArc_Library` folder:

```
blender -b --factory-startup --python tools/make_brushes.py
```

Windows: `"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup --python tools\make_brushes.py`

The script recreates `brushes/GravenArc_Brushes.blend` and appends missing catalogs to `blender_assets.cats.txt` (other lines are left untouched). All brush parameters are in the `BRUSHES` list at the top of the script, falloff curves in `CURVES`. License: GPL-3.0-or-later.

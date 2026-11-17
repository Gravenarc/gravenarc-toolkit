# GravenArc sculpt tools (since 1.2.0)

Stroke replay in the spirit of "Sculpting Essentials" and a Photoshop-style brush, inside the same **GravenArc Toolkit** add-on.
Everything works in **Sculpt Mode**: 3D Viewport → `N` → **GravenArc** tab → panels **Sculpt: Repeat & Mask**, **Sculpt: Photoshop Brush**, **Sculpt: Brush Presets** (hidden in Object Mode on purpose).

## Hotkeys (Sculpt Mode, mouse over the 3D Viewport)

| Key | Action | Conflict with Blender 5.2 defaults |
|---|---|---|
| `Shift+R` | Replay / replace the last stroke | In Sculpt Mode it takes over "Repeat Last"; elsewhere `Shift+R` is unchanged |
| `Alt+R` | Mask the area of the last stroke | free |
| `Alt+Right Mouse` drag | ← → brush size, ↑ ↓ hardness (or strength) | only used by stencil-texture brushes; then the stencil control wins |
| `Alt+L` | Straight line from the end of the last stroke to the cursor | free |
| `Shift+S` | Toggle stroke smoothing | Blender 5.2 already toggles Stabilize Stroke here; ours does the same and reports the state |

Untouched: `LMB` (stroke), `Ctrl+LMB` (inverted stroke), `Shift+LMB` (Smooth), `Ctrl+Shift+LMB` (Lasso Mask), `Alt+LMB` (Emulate 3 Button Mouse).
Change a key: Preferences → Add-ons → GravenArc Toolkit → **Sculpt Hotkeys** (or Preferences → Keymap, search `gravenarc`).

## Dyntopo and Multires

| Feature | Dyntopo | Multires |
|---|---|---|
| Replay / Replace, Live Strength, Straight Line | works, position approximate | works, position approximate |
| Mask Last, Marker, Remember / Recall Mask | **not available** | **not available** |
| Separate Masked, Delete Masked, Delete Hidden | works | **not available** |

The panel shows a red warning when Dyntopo is on or a Multires modifier is present. Tip: use Voxel Remesh (`Ctrl+R`) instead of Dyntopo.

## Install

1. Download `gravenarc_toolkit-1.2.0.zip` (do not unzip).
2. Blender 5.2 → **Edit → Preferences** → **Get Extensions** → **⌄** → **Install from Disk…** (or drag the zip into Blender).
3. Updating replaces 1.1.x; your brush preset folders are kept.

Test scene: File → New → General; `N` → GravenArc → Scene in millimetres; `Shift+A` → UV Sphere, radius 10 mm; `Ctrl+Tab` → Sculpt Mode; `Ctrl+R` voxel remesh at 0.2 mm; pick the **Draw** brush.

## Part 1 — try it

1. **Replay (`Shift+R`)**: make a stroke → the panel says "Last stroke: N points" → `Shift+R` repeats it with the current brush. With **Replace Previous Stroke** on, the old stroke is undone and redrawn (change the brush first to see it). Ctrl-strokes replay inverted.
2. **Repeat Strength**: 2 ≈ twice as high, −1 = dig in instead of build up, 0 = nothing.
3. **Live Strength**: after `Shift+R` move the mouse right/left to grow/shrink the stroke live. LMB/Enter = apply, RMB/Esc = back to Repeat Strength. Wheel and middle mouse still navigate.
4. **Mask Last (`Alt+R`)**: masks what the last stroke changed. One `Ctrl+Z` removes it.
5. **Set Marker → Mask Since Marker**: masks everything changed after the marker.
6. **Remember / Recall Mask**: keeps a copy of the mask until Blender is closed (does not fit after a remesh).
7. **Separate Masked / Delete Masked**: faces with mask over 50% go to a new object "<name>_Masked" / are deleted.
8. **Delete Hidden**: removes geometry hidden with Box Hide / `H`.
9. **Refresh by Re-entering Sculpt Mode**: turn on if the mask shows up only after you rotate the view.
10. **Reset Settings**: defaults back; brush folders are kept.

## Part 2 — try it

1. **Alt+Right Mouse drag**: right/left = size (white ring, "Size … px"), up/down = hardness (orange inner ring) or strength. Release to apply, Esc to cancel. **Lock to One Direction** (on by default) changes only what you move first; turn it off for exact Photoshop behaviour.
2. **Straight line (`Alt+L`)**: stroke, move the mouse elsewhere on the model, `Alt+L` → straight stroke from the end of the last one. Repeat for a polyline; `Shift+R` replays the line.
3. **Brush Presets**: folders Relief / Ornament / Shanks are ready; **New Folder** adds more. Pick any brush (Essentials, the GravenArc library, your own library or a local one) and press **+** on a folder. Click a brush in a folder to activate it. Image icon = large previews; ▲▼ order, AZ rename, ✕ delete. Stored in `brush_presets.json` in the extension's user folder (folder button), not in the scene, and kept across updates.
4. **Smoothing**: 0/25/50/75/100% buttons or Radius/Factor sliders (Blender's Stabilize Stroke); `Shift+S` toggles it.

## Tested automatically vs. by hand

`GravenArc_Addon/tests/test_sculpt.py` (Blender 5.2.4 headless, 73 checks, all pass) covers install, replay along the recorded path, Replace with an undo safety check, ×2 and negative strength, all mask/marker/separate/delete tools, Multires refusal, straight line, smoothing, preset folders, icon names, the preview ring drawing, keymap priority and disable/enable.
Only checkable by hand: recording from a real mouse/pen, the Alt+Right Mouse drag, Live Strength, and viewport mask refresh.

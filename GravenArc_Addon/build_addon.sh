#!/usr/bin/env bash
# Сборка расширения GravenArc Toolkit в .zip.
#   ./build_addon.sh                          — нужен blender 5.2+ в PATH
#   BLENDER=/path/to/blender ./build_addon.sh
#   BLENDER_EXT="python3 .../bl_pkg/cli/blender_ext.py" ./build_addon.sh   — без Blender (bpy из pip)
# Берёт код из src/gravenarc_toolkit и ../GravenArc_Library/jewelry_tools, ассеты из ../GravenArc_Library,
# складывает во временную папку и вызывает «extension build» + «extension validate».
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LIB="${LIB:-$HERE/../GravenArc_Library}"
OUT="${OUT:-$HERE/dist}"
STAGE="$(mktemp -d)/gravenarc_toolkit"
if [ -n "${BLENDER_EXT:-}" ]; then EXT="$BLENDER_EXT"; else EXT="${BLENDER:-blender} --command extension"; fi

cp -r "$HERE/src/gravenarc_toolkit" "$STAGE"
mkdir -p "$STAGE/library"
cp "$LIB/blender_assets.cats.txt" "$STAGE/library/"
for d in brushes alphas templates tools sculpt_tools; do cp -r "$LIB/$d" "$STAGE/library/$d"; done
# Ювелирные инструменты: код — подпакетом modules/jewelry (без своего manifest), ассеты — в library/jewelry
mkdir -p "$STAGE/modules/jewelry" && cp "$LIB/jewelry_tools/gravenarc_jewelry/"*.py "$STAGE/modules/jewelry/"
mkdir -p "$STAGE/library/jewelry/demo"
cp "$LIB/jewelry_tools/"{GravenArc_Jewelry.blend,README_ru.md,README_en.md,jewelry_preview.png,build_jewelry_library.py} "$STAGE/library/jewelry/"
cp "$LIB/jewelry_tools/demo/demo_render.png" "$STAGE/library/jewelry/demo/"
find "$STAGE" -name "__pycache__" -type d -prune -exec rm -rf {} +

mkdir -p "$OUT"
$EXT validate "$STAGE"
$EXT build --source-dir "$STAGE" --output-dir "$OUT"
for z in "$OUT"/*.zip; do $EXT validate "$z"; done
rm -rf "$(dirname "$STAGE")"
ls -la "$OUT"

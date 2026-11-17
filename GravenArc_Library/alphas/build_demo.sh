#!/usr/bin/env sh
# Пересобрать демо-альфы GravenArc из src/*.svg -> maps/
cd "$(dirname "$0")"
python3 tools/svg2alpha.py src/jewel_rosette.svg --catalog "GravenArc/Alphas/Jewelry" --title "Розетка с зернью"
python3 tools/svg2alpha.py src/arevakhach_whirl.svg --fix-gaps --catalog "GravenArc/Alphas/Armenian" --title "Вихрь вечности (8 лучей)"
python3 tools/svg2alpha.py src/band_scroll_tile.svg --tile x --depth-mm 0.3 --fix-gaps --catalog "GravenArc/Alphas/Bands" --title "Бордюр-завиток (бесшовный)"
# Затем кисти и превью-оттиски (нужен Blender 5.2):
#   blender -b --factory-startup --python tools/make_alpha_brushes.py
#   blender -b --factory-startup --python ../tools/alpha_icons.py
#   python3 ../tools/showcase_sheet.py --out demo_preview.png --title Alphas --cols 3 --cell 400 maps/<имя>_render.png "<подпись>" ...

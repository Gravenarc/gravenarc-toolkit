"""Витринный лист-превью GravenArc: шапка, карточки со скруглением, подписи.

Работает в обычном Python 3 с Pillow (в Blender Pillow нет), поэтому вызывается
после сборки, отдельным шагом:

    python3 showcase_sheet.py --out sheet.png --title "Brushes" --subtitle "25 кистей" \
        --cols 5 icon1.png "GA Clay" icon2.png "GA Move" ...

или нарезкой готового листа-сетки:

    python3 showcase_sheet.py --out sheet.png --title ... --grid src.png 5 256 290 \
        --labels "GA Clay" "GA Move" ...
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BG = (24, 24, 27)
CARD = (38, 38, 42)
CARD_EDGE = (58, 58, 64)
TEXT = (236, 236, 238)
MUTED = (150, 150, 158)
ACCENT = (214, 120, 84)          # тёплая «восковая» медь — фирменный акцент
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
             "C:/Windows/Fonts", "/Library/Fonts", "/System/Library/Fonts/Supplemental"]


def _font(names, size):
    for d in FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _fit(draw, text, font_names, size, max_w):
    while size > 9:
        f = _font(font_names, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return _font(font_names, size)


def build(items, out, title, subtitle="", cols=5, cell=256, scale=1.0):
    """items: [(PIL.Image, label)]."""
    pad, gap, label_h, head_h = 36, 18, 44, 112
    cw = cell
    rows = (len(items) + cols - 1) // cols
    W = pad * 2 + cols * cw + (cols - 1) * gap
    H = head_h + pad + rows * (cw + label_h) + (rows - 1) * gap + pad
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)

    bold = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"]
    reg = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf", "Arial.ttf"]
    # шапка: метка-ромб, название бренда, раздел
    x0, y0 = pad, 34
    d.polygon([(x0, y0 + 16), (x0 + 16, y0), (x0 + 32, y0 + 16), (x0 + 16, y0 + 32)], fill=ACCENT)
    d.polygon([(x0 + 9, y0 + 16), (x0 + 16, y0 + 9), (x0 + 23, y0 + 16), (x0 + 16, y0 + 23)], fill=BG)
    fb = _font(bold, 30)
    d.text((x0 + 48, y0 - 4), "GravenArc", font=fb, fill=TEXT)
    tx = x0 + 48 + d.textlength("GravenArc", font=fb) + 14
    d.text((tx, y0 - 4), title, font=_font(reg, 30), fill=ACCENT)
    if subtitle:
        d.text((x0 + 48, y0 + 34), subtitle, font=_font(reg, 16), fill=MUTED)
    d.line([(pad, head_h - 8), (W - pad, head_h - 8)], fill=CARD_EDGE, width=1)

    for i, (img, label) in enumerate(items):
        r, c = divmod(i, cols)
        x = pad + c * (cw + gap)
        y = head_h + pad // 2 + r * (cw + label_h + gap)
        # мягкая тень + карточка
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).rounded_rectangle([x + 2, y + 6, x + cw + 2, y + cw + label_h + 6], 16, fill=110)
        sh = sh.filter(ImageFilter.GaussianBlur(8))
        sheet.paste(Image.new("RGB", (W, H), (8, 8, 10)), (0, 0), sh)
        d = ImageDraw.Draw(sheet)
        d.rounded_rectangle([x, y, x + cw, y + cw + label_h], 16, fill=CARD, outline=CARD_EDGE)
        im = img.convert("RGBA").resize((cw - 12, cw - 12), Image.LANCZOS)
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], 12, fill=255)
        alpha = Image.composite(im.getchannel("A"), Image.new("L", im.size, 0), mask)
        sheet.paste(im.convert("RGB"), (x + 6, y + 6), alpha)
        f = _fit(d, label, bold, 17, cw - 20)
        tw = d.textlength(label, font=f)
        d.text((x + (cw - tw) / 2, y + cw + 8), label, font=f, fill=TEXT)
    if scale != 1.0:
        sheet = sheet.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    sheet.save(out, optimize=True)
    return out


def crop_grid(src, cols, cell, pitch_y, n, pitch_x=None, bg_key=None):
    im = Image.open(src).convert("RGBA")
    pitch_x = pitch_x or cell
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        tile = im.crop((c * pitch_x, r * pitch_y, c * pitch_x + cell, r * pitch_y + cell))
        out.append(tile)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--cell", type=int, default=256)
    ap.add_argument("--grid", nargs=4, metavar=("SRC", "COLS", "CELL", "PITCH_Y"))
    ap.add_argument("--labels", nargs="*")
    ap.add_argument("pairs", nargs="*")
    a = ap.parse_args()
    if a.grid:
        src, gc, gcell, py = a.grid[0], int(a.grid[1]), int(a.grid[2]), int(a.grid[3])
        tiles = crop_grid(src, gc, gcell, py, len(a.labels))
        items = list(zip(tiles, a.labels))
    else:
        it = iter(a.pairs)
        items = [(Image.open(p), lab) for p, lab in zip(it, it)]
    build(items, a.out, a.title, a.subtitle, cols=a.cols, cell=a.cell)
    print("[GravenArc] витрина ->", a.out)


if __name__ == "__main__":
    main()

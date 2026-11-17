#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# GravenArc Blender Toolkit — svg2alpha
"""
Векторный орнамент (SVG из Illustrator, либо PNG-маска) -> карта высот для
alpha-кисти Blender (16-bit PNG, по желанию 32-bit float TIFF).

Идея:
  * Заливка фигуры = рельеф. Чёрный (или любой тёмный) = полная высота,
    серый 50% = половина высоты. Прозрачный/белый фон = 0.
  * Стенки рельефа строятся по расстоянию от контура (distance transform),
    поэтому у каждой стенки есть гарантированный уклон (draft) и нет
    поднутрений: карта высот — однозначная функция, «нависаний» в ней нет.
  * Проверка для литья в песок: перемычки тоньше --min-bridge и щели уже
    --min-gap подсвечиваются в отчётной картинке *_check.png.

Все размеры — в миллиметрах.

Пример:
  python svg2alpha.py ornament.svg --size-mm 12 --depth-mm 0.4 --draft-deg 15
  python svg2alpha.py band.svg --tile x --profile round
  python svg2alpha.py a.svg b.svg c.svg -o ../maps      # пачкой

Зависимости: numpy, scipy, pillow + один растеризатор SVG:
  cairosvg (pip install cairosvg) ИЛИ Inkscape в PATH.
  Если растеризатора нет — экспортируйте из Illustrator PNG
  (чёрное на прозрачном) и подайте его с ключами --size-mm.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

MM_PER_UNIT = {
    "mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6,
    # Illustrator пишет размеры без единиц; 1 единица = 1 pt (72 на дюйм).
    "px": 25.4 / 72, "": 25.4 / 72,
}


# --------------------------------------------------------------------------- #
# SVG: размер и растеризация
# --------------------------------------------------------------------------- #
def _parse_len(value: str | None):
    if not value:
        return None
    m = re.fullmatch(r"\s*([0-9.+-eE]+)\s*([a-z%]*)\s*", value)
    if not m or m.group(2) == "%":
        return None
    return float(m.group(1)) * MM_PER_UNIT.get(m.group(2), 25.4 / 72)


def svg_size_mm(svg_text: str):
    """(ширина, высота) монтажной области SVG в мм."""
    head = svg_text[: svg_text.find(">", svg_text.find("<svg")) + 1]
    w = _parse_len(_attr(head, "width"))
    h = _parse_len(_attr(head, "height"))
    vb = _attr(head, "viewBox")
    if (w is None or h is None) and vb:
        _, _, vw, vh = (float(x) for x in re.split(r"[ ,]+", vb.strip()))
        k = MM_PER_UNIT[""]
        w, h = w or vw * k, h or vh * k
    if w is None or h is None:
        raise ValueError("Не удалось определить размер SVG — задайте --size-mm")
    return w, h


def _attr(tag: str, name: str):
    m = re.search(rf'\s{name}\s*=\s*"([^"]*)"', tag)
    return m.group(1) if m else None


def rasterize_svg(path: Path, width_px: int, height_px: int) -> np.ndarray:
    """RGBA uint8 (H, W, 4)."""
    try:
        import cairosvg  # type: ignore

        png = cairosvg.svg2png(url=str(path), output_width=width_px,
                               output_height=height_px)
        return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
    except (ImportError, OSError):
        pass
    inkscape = shutil.which("inkscape")
    if inkscape:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.png"
            subprocess.run([inkscape, str(path), "--export-type=png",
                            f"--export-filename={out}",
                            f"--export-width={width_px}",
                            f"--export-height={height_px}"],
                           check=True, capture_output=True)
            return np.asarray(Image.open(out).convert("RGBA"))
    sys.exit("Нет растеризатора SVG: pip install cairosvg, установите Inkscape "
             "или экспортируйте PNG из Illustrator.")


def coverage(rgba: np.ndarray) -> np.ndarray:
    """0..1: насколько «высоко» пиксель. Тёмная непрозрачная заливка = 1."""
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    return np.clip((1.0 - lum) * alpha, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Рельеф
# --------------------------------------------------------------------------- #
def signed_distance(mask: np.ndarray, tile: str) -> np.ndarray:
    """Расстояние до контура в пикселях: >0 внутри, <0 снаружи."""
    pad = [(0, 0), (0, 0)]
    if "y" in tile:
        pad[0] = (mask.shape[0], mask.shape[0])
    if "x" in tile:
        pad[1] = (mask.shape[1], mask.shape[1])
    m = np.pad(mask, pad, mode="wrap") if tile else mask
    inside = ndimage.distance_transform_edt(m)
    outside = ndimage.distance_transform_edt(~m)
    sd = np.where(m, inside - 0.5, -(outside - 0.5))
    if tile:
        sd = sd[pad[0][0]: pad[0][0] + mask.shape[0],
                pad[1][0]: pad[1][0] + mask.shape[1]]
    return sd


def ramp(x: np.ndarray, profile: str) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    if profile == "flat":      # прямая фаска + плоская площадка
        return x
    if profile == "round":     # скруглённое плечо (четверть синуса)
        return np.sin(x * math.pi / 2)
    if profile == "dome":      # «подушка»: вся форма выпуклая
        return np.sqrt(1.0 - (1.0 - x) ** 2)
    raise ValueError(profile)


# Максимальный наклон ramp на [0,1] — нужен, чтобы уклон соблюдался везде.
MAX_SLOPE = {"flat": 1.0, "round": math.pi / 2, "dome": None}


def build_height(cov, ppmm, depth_mm, draft_deg, profile, levels, tile,
                 dome_width_mm, fix_gap_mm=0.0):
    """Нормированная высота 0..1 + список ступеней."""
    q = np.round(cov * levels) / levels        # квантуем уровни серого
    # уровни, которые встречаются только на сглаженных краях (антиалиасинг),
    # — не настоящие ступени: прижимаем такие пиксели к ближайшему уровню
    real = [0.0] + [v for v in np.unique(q) if v > 0 and
                    ndimage.binary_erosion(q == v, iterations=2).any()]
    real = np.array(sorted(real))
    q = real[np.abs(q[..., None] - real).argmin(axis=-1)]
    steps = [float(v) for v in real if v > 0]
    height = np.zeros(cov.shape, np.float64)
    prev = 0.0
    info = []
    masks = []
    for lv in steps:
        mask = q >= lv - 1e-6
        if fix_gap_mm > 0:
            mask = close_gaps(mask, ppmm, fix_gap_mm, tile)
            if lv > steps[0]:   # верхняя ступень не вылезает за нижнюю
                mask &= masks[-1]
        masks.append(mask)
        dh = lv - prev                          # доля полной высоты
        step_mm = dh * depth_mm
        if profile == "dome":
            w_mm = dome_width_mm
        else:
            # горизонтальный «вынос» стенки так, чтобы самый крутой участок
            # был отклонён от вертикали не меньше чем на draft
            w_mm = step_mm * math.tan(math.radians(draft_deg)) * MAX_SLOPE[profile]
        w_px = max(w_mm * ppmm, 0.75)
        sd = signed_distance(mask, tile)
        height += dh * ramp(sd / w_px, profile)
        info.append({"level": round(float(lv), 4), "step_mm": round(float(step_mm), 4),
                     "wall_run_mm": round(float(w_mm), 4)})
        prev = lv
    return height, info, masks[0] if masks else np.zeros(cov.shape, bool)


# --------------------------------------------------------------------------- #
# Проверка технологичности (литьё в песок)
# --------------------------------------------------------------------------- #
def disk(r_px: float) -> np.ndarray:
    r = max(int(math.ceil(r_px)), 1)
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r_px * r_px + 1e-9


def _padded(mask, pad, tile):
    m = np.pad(mask, ((pad, pad), (0, 0)),
               mode="wrap" if "y" in tile else "constant")
    return np.pad(m, ((0, 0), (pad, pad)),
                  mode="wrap" if "x" in tile else "constant")


def _crop(m, pad, shape):
    return m[pad:pad + shape[0], pad:pad + shape[1]]


def close_gaps(mask, ppmm, min_gap, tile):
    """Заливает щели уже min_gap и острые внутренние углы (делает галтели)."""
    r = min_gap * ppmm / 2
    pad = int(math.ceil(r)) + 2
    m = ndimage.binary_closing(_padded(mask, pad, tile), structure=disk(r))
    return _crop(m, pad, mask.shape)


def manufacturability(mask, ppmm, min_bridge, min_gap, tile):
    """Тонкие перемычки (red) и узкие щели (blue), площади в мм²."""
    pad = int(math.ceil(max(min_bridge, min_gap) * ppmm)) + 2
    m = _padded(mask, pad, tile)
    # допуск 1 пиксель на дискретизацию
    se_b = disk(max(min_bridge * ppmm / 2 - 1.0, 0.5))
    se_g = disk(max(min_gap * ppmm / 2 - 1.0, 0.5))
    opened = ndimage.binary_opening(m, structure=se_b)
    thin = m & ~ndimage.binary_dilation(opened, structure=disk(1.0))
    closed = ndimage.binary_closing(m, structure=se_g)
    narrow = closed & ~m
    thin, narrow = _crop(thin, pad, mask.shape), _crop(narrow, pad, mask.shape)
    # убираем одиночные пиксели антиалиасинга
    thin = ndimage.binary_opening(thin, structure=np.ones((3, 3)))
    narrow = ndimage.binary_opening(narrow, structure=np.ones((3, 3)))
    px2 = 1.0 / (ppmm * ppmm)
    return thin, narrow, thin.sum() * px2, narrow.sum() * px2


def hillshade(h: np.ndarray, ppmm: float, depth_mm: float) -> np.ndarray:
    z = h * depth_mm * ppmm * 3.0
    gy, gx = np.gradient(z)
    n = np.dstack([-gx, -gy, np.ones_like(z)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    light = np.array([-0.5, -0.6, 0.62])
    light /= np.linalg.norm(light)
    s = np.clip(n @ light, 0, 1)
    tint = 0.45 + 0.55 * h                      # выше = светлее
    return np.clip((30 + 225 * s) * tint, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
def convert(src: Path, out_dir: Path, a) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".svg":
        text = src.read_text(encoding="utf-8", errors="ignore")
        w_mm, h_mm = svg_size_mm(text)
        if a.size_mm:
            k = a.size_mm / max(w_mm, h_mm)
            w_mm, h_mm = w_mm * k, h_mm * k
        rgba = rasterize_svg(src, round(w_mm * a.ppmm), round(h_mm * a.ppmm))
    else:
        img = Image.open(src).convert("RGBA")
        if not a.size_mm:
            sys.exit(f"{src.name}: для PNG нужен --size-mm (ширина большей стороны)")
        k = a.size_mm / max(img.size)
        w_mm, h_mm = img.width * k, img.height * k
        img = img.resize((round(w_mm * a.ppmm), round(h_mm * a.ppmm)),
                         Image.LANCZOS)
        rgba = np.asarray(img)

    cov = coverage(rgba)
    if a.invert:
        cov = 1.0 - cov

    # поля вокруг рисунка (для бесшовной оси полей нет)
    if a.margin_mm is None:
        a_margin = 0.08 * max(w_mm, h_mm)
    else:
        a_margin = a.margin_mm
    m_px = round(a_margin * a.ppmm)
    pad_y = 0 if "y" in a.tile else m_px
    pad_x = 0 if "x" in a.tile else m_px
    cov = np.pad(cov, ((pad_y, pad_y), (pad_x, pad_x)))
    # кисть Blender натягивает текстуру на квадрат — дополняем нулями
    # (по бесшовной оси не дополняем, иначе шов)
    if a.square and a.tile != "xy":
        hh, ww = cov.shape
        s = max(hh, ww)
        py = 0 if "y" in a.tile else s - hh
        px = 0 if "x" in a.tile else s - ww
        if ("x" in a.tile and hh > ww) or ("y" in a.tile and ww > hh):
            print(f"  внимание: бесшовная ось короче другой — квадрат не получится")
        cov = np.pad(cov, ((py // 2, py - py // 2), (px // 2, px - px // 2)))

    height, steps, mask = build_height(
        cov, a.ppmm, a.depth_mm, a.draft_deg, a.profile, a.levels, a.tile,
        a.dome_width_mm, a.min_gap if a.fix_gaps else 0.0)
    if a.base_blur_mm > 0:
        height = ndimage.gaussian_filter(
            height, a.base_blur_mm * a.ppmm,
            mode="wrap" if a.tile else "constant")
    height = np.clip(height, 0, 1)

    thin, narrow, thin_mm2, narrow_mm2 = manufacturability(
        mask, a.ppmm, a.min_bridge, a.min_gap, a.tile)

    stem = a.name or src.stem
    out_png = out_dir / f"{stem}.png"
    Image.fromarray(np.round(height * 65535).astype(np.uint16)).save(out_png)
    if a.tiff32:
        Image.fromarray(height.astype(np.float32), mode="F").save(
            out_dir / f"{stem}.tif")

    # превью + отчёт
    shade = hillshade(height, a.ppmm, a.depth_mm)
    Image.fromarray(shade).resize((256, round(256 * shade.shape[0] / shade.shape[1])),
                                  Image.LANCZOS).save(out_dir / f"{stem}_preview.png")
    prev = np.dstack([shade] * 3)
    prev[thin] = [230, 30, 30]
    prev[narrow] = [30, 90, 230]
    Image.fromarray(prev).save(out_dir / f"{stem}_check.png")

    meta = {
        "name": stem,
        "title": a.title or stem.replace("_", " ").title(),
        "catalog": a.catalog,
        "source": src.name,
        "size_mm": [round(cov.shape[1] / a.ppmm, 3), round(cov.shape[0] / a.ppmm, 3)],
        "artwork_mm": [round(w_mm, 3), round(h_mm, 3)],
        "px_per_mm": a.ppmm,
        "depth_mm": a.depth_mm,
        "draft_deg": a.draft_deg,
        "profile": a.profile,
        "tile": a.tile or "none",
        "steps": steps,
        "min_bridge_mm": a.min_bridge,
        "min_gap_mm": a.min_gap,
        "fix_gaps": a.fix_gaps,
        "thin_bridges_mm2": round(float(thin_mm2), 4),
        "narrow_gaps_mm2": round(float(narrow_mm2), 4),
        "ok_for_sand_casting": bool(thin_mm2 < 0.005 and narrow_mm2 < 0.005),
    }
    (out_dir / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main(argv=None):
    p = argparse.ArgumentParser(
        description="SVG/PNG орнамент -> 16-bit карта высот для alpha-кисти Blender (мм).")
    p.add_argument("inputs", nargs="+", type=Path, help="SVG или PNG файлы")
    p.add_argument("-o", "--out", type=Path, default=None,
                   help="папка вывода (по умолчанию alphas/maps рядом с tools/)")
    p.add_argument("--name", help="имя выходного файла (только для одного входа)")
    p.add_argument("--size-mm", type=float, default=None,
                   help="масштабировать рисунок: большая сторона = N мм")
    p.add_argument("--ppmm", type=float, default=40.0,
                   help="пикселей на мм (40 = 25 мкм/пиксель)")
    p.add_argument("--depth-mm", type=float, default=0.4, help="высота рельефа, мм")
    p.add_argument("--draft-deg", type=float, default=15.0,
                   help="уклон стенок от вертикали, градусы (для песка >= 5)")
    p.add_argument("--profile", choices=["flat", "round", "dome"], default="round",
                   help="flat — фаска, round — скруглённое плечо, dome — подушка")
    p.add_argument("--dome-width-mm", type=float, default=0.6,
                   help="для dome: ширина нарастания до полной высоты")
    p.add_argument("--levels", type=int, default=4,
                   help="сколько уровней серого различать (4 = 25/50/75/100%%)")
    p.add_argument("--tile", choices=["", "x", "y", "xy"], default="",
                   help="бесшовность по оси (для бордюров на шинку — x)")
    p.add_argument("--margin-mm", type=float, default=None,
                   help="чёрные поля вокруг рисунка (по умолч. 8%% размера)")
    p.add_argument("--no-square", dest="square", action="store_false",
                   help="не дополнять до квадрата")
    p.add_argument("--base-blur-mm", type=float, default=0.015,
                   help="лёгкое размытие всей карты (смягчение), мм")
    p.add_argument("--invert", action="store_true", help="светлое = высокое")
    p.add_argument("--min-bridge", type=float, default=0.5,
                   help="минимальная ширина перемычки, мм")
    p.add_argument("--min-gap", type=float, default=0.5,
                   help="минимальная щель между элементами, мм")
    p.add_argument("--fix-gaps", action="store_true",
                   help="автоматически залить щели уже --min-gap и скруглить "
                        "острые внутренние углы (галтель радиусом min_gap/2)")
    p.add_argument("--catalog", default="GravenArc/Alphas",
                   help="каталог в библиотеке ассетов Blender")
    p.add_argument("--title", help="название кисти в Blender")
    p.add_argument("--tiff32", action="store_true",
                   help="дополнительно 32-bit float TIFF")
    a = p.parse_args(argv)

    if (a.name or a.title) and len(a.inputs) > 1:
        p.error("--name/--title можно задать только для одного файла")
    out = a.out or Path(__file__).resolve().parent.parent / "maps"
    bad = 0
    for src in a.inputs:
        m = convert(src, out, a)
        flag = "OK " if m["ok_for_sand_casting"] else "!! "
        bad += not m["ok_for_sand_casting"]
        print(f"{flag}{m['name']}: {m['size_mm'][0]}x{m['size_mm'][1]} мм, "
              f"рельеф {m['depth_mm']} мм, уклон {m['draft_deg']}°, "
              f"тонкие перемычки {m['thin_bridges_mm2']} мм², "
              f"узкие щели {m['narrow_gaps_mm2']} мм²")
    if bad:
        print(f"\n{bad} файл(ов) с проблемами — смотрите *_check.png "
              "(красное = перемычка тоньше, синее = щель уже минимума).")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

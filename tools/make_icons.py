#!/usr/bin/env python3
"""Génère les icônes PNG de l'application (PWA) à partir du dessin du favicon.

Usage : python tools/make_icons.py
Produit dans static/icons/ :
  icon-192.png, icon-512.png       – icônes classiques (Android, bureau)
  icon-maskable-512.png            – icône "maskable" (Android découpe la forme)
  apple-touch-icon-180.png         – icône iPhone / iPad
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "icons")

BLUE_TOP = (37, 99, 235)      # #2563eb
BLUE_BOTTOM = (30, 64, 175)   # #1e40af
WHITE = (255, 255, 255, 242)
WINDOW = (37, 99, 235, 153)
WHEEL = (30, 41, 59, 255)
HUB = (100, 116, 139, 255)
LIGHT = (251, 191, 36, 255)


def _gradient(size):
    """Fond dégradé bleu, du haut-gauche au bas-droit."""

    img = Image.new("RGBA", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(
                int(BLUE_TOP[i] + (BLUE_BOTTOM[i] - BLUE_TOP[i]) * t) for i in range(3)
            ) + (255,)
    return img


def _draw_car(draw, scale, offset):
    """Dessine la voiture du favicon (grille 64x64) avec un facteur d'échelle."""

    def p(x, y):
        return (offset + x * scale, offset + y * scale)

    draw.polygon(
        [p(12, 38), p(16, 28), p(24, 24), p(40, 24), p(48, 28), p(52, 38), p(52, 44), p(12, 44)],
        fill=WHITE,
    )
    draw.polygon([p(18, 36), p(20, 30), p(26, 28), p(26, 36)], fill=WINDOW)
    draw.polygon([p(28, 36), p(28, 28), p(36, 28), p(38, 30), p(38, 36)], fill=WINDOW)
    for cx in (20, 44):
        draw.ellipse([p(cx - 6, 44 - 6), p(cx + 6, 44 + 6)], fill=WHEEL)
        draw.ellipse([p(cx - 3, 44 - 3), p(cx + 3, 44 + 3)], fill=HUB)
    r = max(1, int(scale))
    draw.rounded_rectangle([p(48, 32), p(52, 36)], radius=r, fill=LIGHT)
    draw.rounded_rectangle([p(12, 32), p(16, 36)], radius=r, fill=LIGHT)


def make_icon(size, *, maskable=False):
    img = _gradient(size)
    if not maskable:
        # Coins arrondis comme le favicon (rx = 12/64).
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 12 / 64), fill=255)
        img.putalpha(mask)
        car_scale = size / 64
        offset = 0
    else:
        # Zone sûre : la voiture occupe 70 % du carré, centrée.
        car_scale = size * 0.70 / 64
        offset = (size - 64 * car_scale) / 2
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _draw_car(ImageDraw.Draw(overlay), car_scale, offset)
    return Image.alpha_composite(img, overlay)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    targets = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
        ("apple-touch-icon-180.png", 180, True),  # iOS arrondit lui-même les coins
    ]
    for name, size, maskable in targets:
        img = make_icon(size, maskable=maskable)
        if name.startswith("apple"):
            img = img.convert("RGB")  # iOS n'aime pas la transparence
        img.save(os.path.join(OUT_DIR, name), optimize=True)
        print(f"{name:26} {size}x{size}")


if __name__ == "__main__":
    main()

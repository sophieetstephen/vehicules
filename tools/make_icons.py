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

BLUE_TOP = (30, 41, 59)       # #1e293b (bleu nuit, couleur de la barre)
BLUE_BOTTOM = (15, 23, 42)    # #0f172a
BODY = (220, 38, 38, 255)     # #dc2626 rouge sapeur-pompier
BODY_DARK = (185, 28, 28, 255)
WINDOW = (224, 242, 254, 235) # vitres claires
WHEEL = (15, 23, 42, 255)
HUB = (148, 163, 184, 255)
LIGHT = (251, 191, 36, 255)
BEACON = (59, 130, 246, 255)  # gyrophare bleu
BEACON_GLOW = (147, 197, 253, 110)


def _gradient(size):
    """Fond dégradé bleu nuit, du haut-gauche au bas-droit."""

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

    # Halo du gyrophare, puis gyrophare bleu sur le toit
    draw.ellipse([p(25, 14), p(39, 26)], fill=BEACON_GLOW)
    draw.rounded_rectangle([p(28, 18), p(36, 24)], radius=max(1, int(1.5 * scale)), fill=BEACON)
    draw.rounded_rectangle([p(30, 19), p(34, 21)], radius=max(1, int(scale)), fill=(219, 234, 254, 255))
    # Carrosserie rouge
    draw.polygon(
        [p(12, 38), p(16, 28), p(24, 24), p(40, 24), p(48, 28), p(52, 38), p(52, 44), p(12, 44)],
        fill=BODY,
    )
    draw.rectangle([p(12, 40), p(52, 44)], fill=BODY_DARK)
    # Vitres claires
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

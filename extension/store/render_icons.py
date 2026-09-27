"""Draw the Swag Bot toolbar icons.

Run from the repository root:

    python3 extension/store/render_icons.py

Requires Pillow. The PNGs are committed; CI does not run this script.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "public" / "icons"
LIME = (214, 255, 63, 255)
INK = (12, 12, 14, 255)


def draw(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    margin = max(1, round(size * 0.06))
    radius = max(2, round(size * 0.22))
    pen.rounded_rectangle(
        [margin, margin, size - margin - 1, size - margin - 1],
        radius=radius,
        fill=INK,
    )
    left = round(size * 0.27)
    right = round(size * 0.73)
    thickness = max(2, round(size * 0.105))
    gap = max(1, round(size * 0.055))
    top = round(size * 0.29)
    bars = (
        (left, right),
        (left + round((right - left) * 0.28), right),
        (left, right - round((right - left) * 0.08)),
    )
    y = top
    for bar_left, bar_right in bars:
        pen.rounded_rectangle(
            [bar_left, y, bar_right, y + thickness],
            radius=max(1, thickness // 2),
            fill=LIME,
        )
        y += thickness + gap
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        draw(size).save(OUT / f"icon{size}.png")


if __name__ == "__main__":
    main()

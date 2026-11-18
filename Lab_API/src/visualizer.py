"""Image normalization and Confidence Heatmap overlay rendering with Pillow."""

from __future__ import annotations

import io
from typing import Sequence

from PIL import Image, ImageDraw, ImageOps

from src.vision_service import WordConfidence, classify_confidence

LEVEL_COLORS: dict[str, tuple[int, int, int]] = {
    "high": (34, 197, 94),     # Green: confidence >= 0.90
    "medium": (245, 158, 11),  # Yellow / Orange: 0.75 <= confidence < 0.90
    "low": (239, 68, 68),      # Red: confidence < 0.75
}

LEVEL_HEX_COLORS: dict[str, str] = {
    "high": "#22C55E",
    "medium": "#F59E0B",
    "low": "#EF4444",
}


def get_confidence_color(confidence: float) -> tuple[int, int, int]:
    """Return RGB color tuple corresponding to the confidence tier."""
    return LEVEL_COLORS[classify_confidence(confidence)]


def prepare_image(image_bytes: bytes) -> tuple[Image.Image, bytes]:
    """Normalize EXIF orientation and convert image to RGB PNG bytes.

    Normalizing before calling Cloud Vision API guarantees that returned polygon
    coordinates align 1:1 with the rendered Pillow image.
    """
    if not image_bytes:
        raise ValueError("image_bytes must not be empty.")

    with Image.open(io.BytesIO(image_bytes)) as raw_image:
        transposed = ImageOps.exif_transpose(raw_image)
        if transposed.mode in ("RGBA", "LA") or (
            transposed.mode == "P" and "transparency" in transposed.info
        ):
            rgba = transposed.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            rgb_image = Image.alpha_composite(background, rgba).convert("RGB")
        else:
            rgb_image = transposed.convert("RGB")

    return rgb_image, image_to_png_bytes(rgb_image)


def draw_confidence_heatmap(
    image: Image.Image,
    words: Sequence[WordConfidence],
    *,
    fill_alpha: int = 55,
    outline_width: int = 3,
) -> Image.Image:
    """Draw semi-transparent confidence polygons over recognized words."""
    clamped_alpha = max(0, min(255, int(fill_alpha)))
    stroke_width = max(1, int(outline_width))

    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    for word in words:
        if len(word.vertices) < 3:
            continue

        rgb = LEVEL_COLORS.get(word.level) or get_confidence_color(word.confidence)
        fill_rgba = (*rgb, clamped_alpha)
        outline_rgba = (*rgb, 235)

        draw.polygon(
            word.vertices,
            fill=fill_rgba,
            outline=outline_rgba,
            width=stroke_width,
        )

    composited = Image.alpha_composite(base, overlay)
    return composited.convert("RGB")


def image_to_png_bytes(image: Image.Image) -> bytes:
    """Encode a PIL Image as PNG bytes."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

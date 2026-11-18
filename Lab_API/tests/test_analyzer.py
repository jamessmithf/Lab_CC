"""Unit tests for Cloud Vision parsing, client handling, and heatmap visualization."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from src.vision_service import (
    VisionServiceError,
    WordConfidence,
    analyze_document,
    classify_confidence,
    parse_document_annotation,
)
from src.visualizer import (
    LEVEL_COLORS,
    draw_confidence_heatmap,
    get_confidence_color,
    image_to_png_bytes,
    prepare_image,
)


def _make_vertex(x: int | None, y: int | None) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y)


def _make_word(
    text: str,
    confidence: float,
    coords: list[tuple[int | None, int | None]],
) -> SimpleNamespace:
    return SimpleNamespace(
        confidence=confidence,
        bounding_box=SimpleNamespace(vertices=[_make_vertex(x, y) for x, y in coords]),
        symbols=[SimpleNamespace(text=ch) for ch in text],
    )


def test_classify_confidence_boundaries() -> None:
    assert classify_confidence(1.0) == "high"
    assert classify_confidence(0.90) == "high"
    assert classify_confidence(0.8999) == "medium"
    assert classify_confidence(0.75) == "medium"
    assert classify_confidence(0.7499) == "low"
    assert classify_confidence(0.0) == "low"

    assert get_confidence_color(0.95) == LEVEL_COLORS["high"]
    assert get_confidence_color(0.80) == LEVEL_COLORS["medium"]
    assert get_confidence_color(0.50) == LEVEL_COLORS["low"]


def test_parse_document_annotation_empty() -> None:
    result = parse_document_annotation(None)
    assert result.full_text == ""
    assert result.words == []
    assert result.pages_count == 0
    assert result.stats.total_words == 0
    assert result.stats.average_confidence == 0.0
    assert result.stats.percentage(0) == 0.0


def test_parse_document_annotation_hierarchy_and_stats() -> None:
    word_high = _make_word("Cloud", 0.95, [(0, 0), (50, 0), (50, 20), (0, 20)])
    word_med = _make_word("Vision", 0.80, [(60, 0), (110, 0), (110, 20), (60, 20)])
    word_low = _make_word("API", 0.65, [(None, 30), (40, 30), (40, 50), (0, 50)])

    annotation = SimpleNamespace(
        text="Cloud Vision\nAPI",
        pages=[
            SimpleNamespace(
                blocks=[
                    SimpleNamespace(
                        paragraphs=[
                            SimpleNamespace(words=[word_high, word_med]),
                        ]
                    ),
                    SimpleNamespace(
                        paragraphs=[
                            SimpleNamespace(words=[word_low]),
                        ]
                    ),
                ]
            )
        ],
    )

    result = parse_document_annotation(annotation)

    assert result.full_text == "Cloud Vision\nAPI"
    assert result.pages_count == 1
    assert len(result.words) == 3

    assert result.words[0].text == "Cloud"
    assert result.words[0].level == "high"
    assert result.words[0].block_index == 0

    assert result.words[1].text == "Vision"
    assert result.words[1].level == "medium"

    assert result.words[2].text == "API"
    assert result.words[2].level == "low"
    assert result.words[2].block_index == 1
    assert result.words[2].vertices[0] == (0, 30)

    assert result.stats.total_words == 3
    assert result.stats.high_count == 1
    assert result.stats.medium_count == 1
    assert result.stats.low_count == 1
    assert result.stats.min_confidence == pytest.approx(0.65)
    assert result.stats.max_confidence == pytest.approx(0.95)
    assert result.stats.average_confidence == pytest.approx((0.95 + 0.80 + 0.65) / 3)
    assert result.stats.percentage(1) == pytest.approx(100.0 / 3)


def test_analyze_document_with_mock_client() -> None:
    mock_annotation = SimpleNamespace(
        text="Notes",
        pages=[
            SimpleNamespace(
                blocks=[
                    SimpleNamespace(
                        paragraphs=[
                            SimpleNamespace(
                                words=[_make_word("Notes", 0.92, [(1, 1), (10, 1), (10, 10), (1, 10)])]
                            )
                        ]
                    )
                ]
            )
        ],
    )
    mock_client = SimpleNamespace(
        document_text_detection=lambda image: SimpleNamespace(
            error=SimpleNamespace(message=""),
            full_text_annotation=mock_annotation,
        )
    )

    result = analyze_document(b"fake-image-bytes", client=mock_client)
    assert result.full_text == "Notes"
    assert result.stats.total_words == 1
    assert result.words[0].level == "high"


def test_analyze_document_errors() -> None:
    with pytest.raises(ValueError):
        analyze_document(b"")

    failing_client = SimpleNamespace(
        document_text_detection=lambda image: SimpleNamespace(
            error=SimpleNamespace(message="Quota exceeded"),
            full_text_annotation=None,
        )
    )
    with pytest.raises(VisionServiceError, match="Quota exceeded"):
        analyze_document(b"bytes", client=failing_client)


def test_analyze_document_missing_credentials_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/path/key.json")
    with pytest.raises(VisionServiceError, match="не знайдено"):
        analyze_document(b"bytes")


def test_prepare_image_rgba_and_exif_transpose() -> None:
    rgba = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    buf = io.BytesIO()
    rgba.save(buf, format="PNG")
    norm_img, norm_bytes = prepare_image(buf.getvalue())

    assert norm_img.mode == "RGB"
    assert norm_img.size == (40, 20)
    assert norm_img.getpixel((5, 5)) == (255, 255, 255)
    assert len(norm_bytes) > 0

    # Image with EXIF Orientation=6 (rotated 90 deg CW / 270 deg CCW) should become (20, 40)
    rgb = Image.new("RGB", (40, 20), (240, 240, 240))
    exif = rgb.getexif()
    exif[274] = 6
    exif_buf = io.BytesIO()
    rgb.save(exif_buf, format="JPEG", exif=exif)

    transposed_img, _ = prepare_image(exif_buf.getvalue())
    assert transposed_img.size == (20, 40)


def test_draw_confidence_heatmap_colors_and_degenerate_polygons() -> None:
    canvas = Image.new("RGB", (200, 100), (255, 255, 255))
    words = [
        WordConfidence("high", 0.95, [(10, 10), (50, 10), (50, 40), (10, 40)], "high"),
        WordConfidence("medium", 0.80, [(70, 10), (110, 10), (110, 40), (70, 40)], "medium"),
        WordConfidence("low", 0.40, [(130, 10), (170, 10), (170, 40), (130, 40)], "low"),
        WordConfidence("bad_poly", 0.90, [(0, 0), (5, 5)], "high"),
    ]

    heatmap = draw_confidence_heatmap(canvas, words, fill_alpha=60, outline_width=2)
    assert heatmap.size == (200, 100)
    assert heatmap.mode == "RGB"

    r_h, g_h, b_h = heatmap.getpixel((30, 25))
    assert g_h > r_h and g_h > b_h  # Green dominant

    r_m, g_m, b_m = heatmap.getpixel((90, 25))
    assert r_m > b_m and g_m > b_m  # Amber/yellow dominant

    r_l, g_l, b_l = heatmap.getpixel((150, 25))
    assert r_l > g_l and r_l > b_l  # Red dominant

    assert heatmap.getpixel((5, 90)) == (255, 255, 255)  # Untouched background
    assert len(image_to_png_bytes(heatmap)) > 0

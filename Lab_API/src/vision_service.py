"""Google Cloud Vision API client and hierarchical response parser."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError, GoogleAuthError
from google.cloud import vision

HIGH_CONFIDENCE_THRESHOLD = 0.90
MEDIUM_CONFIDENCE_THRESHOLD = 0.75


class VisionServiceError(RuntimeError):
    """Raised when Cloud Vision API authentication or inference fails."""


@dataclass(frozen=True)
class WordConfidence:
    """Represents a single recognized word with its polygon and confidence score."""

    text: str
    confidence: float
    vertices: list[tuple[int, int]]
    level: str
    page_index: int = 0
    block_index: int = 0
    paragraph_index: int = 0


@dataclass(frozen=True)
class ConfidenceStats:
    """Aggregated confidence statistics across all recognized words."""

    total_words: int
    average_confidence: float
    min_confidence: float
    max_confidence: float
    high_count: int
    medium_count: int
    low_count: int

    def percentage(self, count: int) -> float:
        """Return percentage share for a given word count."""
        if self.total_words == 0:
            return 0.0
        return (count / self.total_words) * 100.0


@dataclass(frozen=True)
class VisionAnalysisResult:
    """Structured result extracted from Cloud Vision document_text_detection."""

    full_text: str
    words: list[WordConfidence]
    stats: ConfidenceStats
    pages_count: int


def classify_confidence(confidence: float) -> str:
    """Classify a confidence score into 'high', 'medium', or 'low'."""
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def check_credentials_status() -> tuple[bool, str]:
    """Check whether GCP credentials appear configured for local or Cloud Run use.

    Returns:
        Tuple of (is_ready, human_readable_status).
    """
    load_dotenv(override=False)
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds_path:
        resolved = Path(creds_path).expanduser()
        if resolved.is_file():
            return True, f"Service Account key found: {resolved}"
        return False, f"GOOGLE_APPLICATION_CREDENTIALS points to missing file: {resolved}"

    # Cloud Run / GCE environments provide Application Default Credentials via metadata server.
    if os.getenv("K_SERVICE") or os.getenv("GOOGLE_CLOUD_PROJECT"):
        return True, "Using Application Default Credentials (Cloud environment)"

    return (
        False,
        "GOOGLE_APPLICATION_CREDENTIALS is not set. "
        "Add it to .env or export the path to your GCP Service Account JSON key.",
    )


def compute_stats(words: list[WordConfidence]) -> ConfidenceStats:
    """Compute summary confidence statistics from parsed word entries."""
    if not words:
        return ConfidenceStats(
            total_words=0,
            average_confidence=0.0,
            min_confidence=0.0,
            max_confidence=0.0,
            high_count=0,
            medium_count=0,
            low_count=0,
        )

    confidences = [word.confidence for word in words]
    high_count = sum(1 for word in words if word.level == "high")
    medium_count = sum(1 for word in words if word.level == "medium")
    low_count = sum(1 for word in words if word.level == "low")

    return ConfidenceStats(
        total_words=len(words),
        average_confidence=sum(confidences) / len(confidences),
        min_confidence=min(confidences),
        max_confidence=max(confidences),
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
    )


def _extract_vertices(bounding_box: Any) -> list[tuple[int, int]]:
    """Extract integer (x, y) polygon vertices from a Vision BoundingPoly."""
    if bounding_box is None:
        return []
    raw_vertices = getattr(bounding_box, "vertices", None) or []
    return [
        (int(getattr(vertex, "x", 0) or 0), int(getattr(vertex, "y", 0) or 0))
        for vertex in raw_vertices
    ]


def parse_document_annotation(annotation: Any) -> VisionAnalysisResult:
    """Parse Cloud Vision TextAnnotation hierarchy (Page -> Block -> Paragraph -> Word -> Symbol)."""
    if annotation is None:
        return VisionAnalysisResult(
            full_text="",
            words=[],
            stats=compute_stats([]),
            pages_count=0,
        )

    full_text = getattr(annotation, "text", "") or ""
    pages = getattr(annotation, "pages", None) or []
    words: list[WordConfidence] = []

    for page_idx, page in enumerate(pages):
        for block_idx, block in enumerate(getattr(page, "blocks", None) or []):
            for para_idx, paragraph in enumerate(getattr(block, "paragraphs", None) or []):
                for word in getattr(paragraph, "words", None) or []:
                    symbols = getattr(word, "symbols", None) or []
                    word_text = "".join(getattr(symbol, "text", "") or "" for symbol in symbols)
                    confidence = float(getattr(word, "confidence", 0.0) or 0.0)
                    vertices = _extract_vertices(getattr(word, "bounding_box", None))

                    words.append(
                        WordConfidence(
                            text=word_text,
                            confidence=confidence,
                            vertices=vertices,
                            level=classify_confidence(confidence),
                            page_index=page_idx,
                            block_index=block_idx,
                            paragraph_index=para_idx,
                        )
                    )

    return VisionAnalysisResult(
        full_text=full_text,
        words=words,
        stats=compute_stats(words),
        pages_count=len(pages),
    )


def _create_vision_client() -> vision.ImageAnnotatorClient:
    """Initialize ImageAnnotatorClient after loading .env and validating local key path."""
    load_dotenv(override=False)
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds_path and not Path(creds_path).expanduser().is_file():
        raise VisionServiceError(
            f"Файл ключа GCP не знайдено за шляхом GOOGLE_APPLICATION_CREDENTIALS: {creds_path}"
        )

    try:
        return vision.ImageAnnotatorClient()
    except DefaultCredentialsError as exc:
        raise VisionServiceError(
            "Не знайдено облікові дані Google Cloud. Вкажіть GOOGLE_APPLICATION_CREDENTIALS "
            "у файлі .env або налаштуйте Application Default Credentials."
        ) from exc
    except GoogleAuthError as exc:
        raise VisionServiceError(f"Помилка автентифікації Google Cloud: {exc}") from exc


def analyze_document(
    image_bytes: bytes,
    client: vision.ImageAnnotatorClient | None = None,
) -> VisionAnalysisResult:
    """Send image bytes to Cloud Vision document_text_detection and parse the response."""
    if not image_bytes:
        raise ValueError("image_bytes must not be empty.")

    active_client = client if client is not None else _create_vision_client()

    try:
        image = vision.Image(content=image_bytes)
        response = active_client.document_text_detection(image=image)
    except GoogleAPIError as exc:
        raise VisionServiceError(f"Помилка запиту до Cloud Vision API: {exc}") from exc
    except GoogleAuthError as exc:
        raise VisionServiceError(f"Помилка авторизації Cloud Vision API: {exc}") from exc

    error = getattr(response, "error", None)
    error_message = getattr(error, "message", "") if error is not None else ""
    if error_message:
        raise VisionServiceError(f"Cloud Vision API повернув помилку: {error_message}")

    annotation = getattr(response, "full_text_annotation", None)
    return parse_document_annotation(annotation)

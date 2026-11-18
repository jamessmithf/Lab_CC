"""Streamlit web UI for Handwriting Confidence Analyzer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import streamlit as st
from PIL import UnidentifiedImageError

from src.vision_service import (
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
    VisionAnalysisResult,
    VisionServiceError,
    analyze_document,
    check_credentials_status,
)
from src.visualizer import (
    LEVEL_HEX_COLORS,
    draw_confidence_heatmap,
    image_to_png_bytes,
    prepare_image,
)

st.set_page_config(
    page_title="Handwriting Confidence Analyzer",
    page_icon="📝",
    layout="wide",
)


def _render_sidebar() -> tuple[int, int]:
    """Render sidebar controls, color legend, and GCP status."""
    with st.sidebar:
        st.header("Налаштування карти")
        fill_alpha = st.slider(
            "Прозорість заливки",
            min_value=0,
            max_value=180,
            value=55,
            step=5,
            help="Інтенсивність фонової заливки полігонів слів.",
        )
        outline_width = st.slider(
            "Товщина контуру (px)",
            min_value=1,
            max_value=8,
            value=3,
            step=1,
        )

        st.divider()
        st.subheader("Легенда впевненості")
        st.markdown(
            f"""
            - <span style="color:{LEVEL_HEX_COLORS['high']};font-weight:700;">● Зелений</span>: висока (`>= {HIGH_CONFIDENCE_THRESHOLD:.2f}`)
            - <span style="color:{LEVEL_HEX_COLORS['medium']};font-weight:700;">● Помаранчевий</span>: середня (`{MEDIUM_CONFIDENCE_THRESHOLD:.2f} – {HIGH_CONFIDENCE_THRESHOLD:.2f}`)
            - <span style="color:{LEVEL_HEX_COLORS['low']};font-weight:700;">● Червоний</span>: низька (`< {MEDIUM_CONFIDENCE_THRESHOLD:.2f}`)
            """,
            unsafe_allow_html=True,
        )

        st.divider()
        st.subheader("Статус Google Cloud")
        creds_ok, creds_message = check_credentials_status()
        if creds_ok:
            st.success(creds_message)
        else:
            st.warning(
                f"{creds_message}\n\n"
                "Якщо ви налаштували `gcloud auth application-default login`, "
                "API також працюватиме через ADC."
            )

    return fill_alpha, outline_width


def _render_stats(result: VisionAnalysisResult) -> None:
    """Display summary metrics and low-confidence word inspection."""
    stats = result.stats
    st.subheader("Статистика впевненості моделі")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Усього слів", stats.total_words)
    c2.metric("Середня впевненість", f"{stats.average_confidence:.1%}")
    c3.metric(
        f"Висока (≥ {HIGH_CONFIDENCE_THRESHOLD:.0%})",
        f"{stats.high_count} ({stats.percentage(stats.high_count):.1f}%)",
    )
    c4.metric(
        f"Середня ({MEDIUM_CONFIDENCE_THRESHOLD:.0%}–{HIGH_CONFIDENCE_THRESHOLD:.0%})",
        f"{stats.medium_count} ({stats.percentage(stats.medium_count):.1f}%)",
    )
    c5.metric(
        f"Низька (< {MEDIUM_CONFIDENCE_THRESHOLD:.0%})",
        f"{stats.low_count} ({stats.percentage(stats.low_count):.1f}%)",
    )

    uncertain_words = [
        word for word in result.words if word.confidence < HIGH_CONFIDENCE_THRESHOLD
    ]
    if uncertain_words:
        with st.expander(
            f"Слова, що потребують перевірки (< {HIGH_CONFIDENCE_THRESHOLD:.0%}): {len(uncertain_words)}"
        ):
            rows = [
                {
                    "Слово": word.text,
                    "Впевненість": f"{word.confidence:.2%}",
                    "Рівень": word.level,
                    "Блок": word.block_index + 1,
                }
                for word in sorted(uncertain_words, key=lambda w: w.confidence)
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)


def main() -> None:
    """Run the Streamlit single-page application."""
    st.title("Handwriting Confidence Analyzer")
    st.caption(
        "Оцифрування рукописних і друкованих конспектів через Google Cloud Vision API "
        "(`document_text_detection`) із візуалізацією карти впевненості."
    )

    fill_alpha, outline_width = _render_sidebar()
    cache: dict[str, VisionAnalysisResult] = st.session_state.setdefault("analysis_cache", {})

    uploaded_file = st.file_uploader(
        "Завантажте фото або скан сторінки конспекту",
        type=["png", "jpg", "jpeg", "webp"],
        help="Підтримуються формати PNG, JPG, JPEG, WEBP.",
    )

    if uploaded_file is None:
        st.info("Оберіть зображення сторінки конспекту вище, щоб розпочати аналіз.")
        return

    raw_bytes = uploaded_file.getvalue()
    try:
        normalized_image, normalized_bytes = prepare_image(raw_bytes)
    except (UnidentifiedImageError, ValueError, OSError) as exc:
        st.error(f"Не вдалося відкрити зображення: {exc}")
        return

    image_hash = hashlib.sha256(normalized_bytes).hexdigest()
    file_stem = Path(uploaded_file.name).stem

    if image_hash not in cache:
        st.image(normalized_image, caption="Завантажене зображення", width=500)
        if st.button("Розпізнати та побудувати карту впевненості", type="primary"):
            with st.spinner("Надсилаємо зображення до Google Cloud Vision API..."):
                try:
                    cache[image_hash] = analyze_document(normalized_bytes)
                except VisionServiceError as exc:
                    st.error(str(exc))
                    return
            st.rerun()
        return

    result = cache[image_hash]
    annotated_image = draw_confidence_heatmap(
        normalized_image,
        result.words,
        fill_alpha=fill_alpha,
        outline_width=outline_width,
    )
    annotated_png = image_to_png_bytes(annotated_image)

    st.subheader("Порівняння результатів: До / Після")
    col_before, col_after = st.columns(2)
    with col_before:
        st.markdown("**До — Оригінал**")
        st.image(normalized_image, use_container_width=True)
    with col_after:
        st.markdown("**Після — Карта впевненості (Confidence Heatmap)**")
        st.image(annotated_image, use_container_width=True)

    if not result.words:
        st.warning("Cloud Vision API не виявив тексту на цьому зображенні.")
        return

    _render_stats(result)

    st.subheader("Витягнутий текст та експорт")
    st.text_area(
        "Розпізнаний текст (full_text_annotation.text)",
        value=result.full_text,
        height=240,
    )

    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            label="Завантажити текст (.txt)",
            data=result.full_text.encode("utf-8"),
            file_name=f"{file_stem}_recognized.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with dl_col2:
        st.download_button(
            label="Завантажити розмічене зображення (.png)",
            data=annotated_png,
            file_name=f"{file_stem}_heatmap.png",
            mime="image/png",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()

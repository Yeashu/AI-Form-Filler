"""Utilities to write user-provided data back into the PDF."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any, BinaryIO, Dict, Mapping, Optional, Sequence, Tuple, Union, cast

import fitz

from .models import DetectedField, FieldType
from .filler_pypdf import fill_pdf_acroform

logger = logging.getLogger(__name__)
if not logger.handlers:
    level_name = os.getenv("AIFORMFILLER_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.setLevel(level)
    logger.addHandler(handler)

PdfSource = Union[str, bytes, BinaryIO]
WidgetKey = Tuple[int, str]
_GLOBAL_WIDGET_PAGE = -1


def _normalize_field_name(name: Optional[str]) -> Optional[str]:
    if isinstance(name, str):
        cleaned = name.strip()
        return cleaned or None
    return None


def _resolve_widget_name(widget: fitz.Widget) -> Optional[str]:
    """Return a canonical identifier for the widget regardless of attribute naming."""

    candidates = (
        getattr(widget, "field_name", None),
        getattr(widget, "name", None),
        getattr(widget, "field_label", None),
    )
    for candidate in candidates:
        normalized = _normalize_field_name(candidate)
        if normalized:
            return normalized
    return None


def _iter_page_widgets_by_name(page: fitz.Page, name: str) -> list[fitz.Widget]:
    """Return fresh widget objects on a page matching the given field name.

    Avoids keeping stale widget references which can cause weakref errors.
    """
    result: list[fitz.Widget] = []
    try:
        widgets = page.widgets()
    except Exception:
        return result
    if not widgets:
        return result
    for widget in widgets:
        field_name = _normalize_field_name(getattr(widget, "field_name", None)) or _normalize_field_name(
            getattr(widget, "name", None)
        )
        if field_name == name:
            result.append(widget)
    return result


def _rects_close(rect: fitz.Rect, bbox: Tuple[float, float, float, float], tolerance: float = 2.0) -> bool:
    return (
        abs(rect.x0 - bbox[0]) <= tolerance
        and abs(rect.y0 - bbox[1]) <= tolerance
        and abs(rect.x1 - bbox[2]) <= tolerance
        and abs(rect.y1 - bbox[3]) <= tolerance
    )


def _match_widget_by_bbox(widgets: Sequence[fitz.Widget], bbox: Tuple[float, float, float, float]) -> Optional[fitz.Widget]:
    for widget in widgets:
        rect = getattr(widget, "rect", None)
        if rect is None:
            continue
        if _rects_close(rect, bbox):
            return widget
    return widgets[0] if widgets else None


def _apply_value_to_widget(widget: fitz.Widget, field_type: FieldType, value: str) -> bool:
    widget_any = cast(Any, widget)
    try:
        if field_type in {FieldType.TEXT, FieldType.TEXTBOX}:
            widget_any.field_value = value
            widget.update()
            logger.debug("Set text widget value to '%s'", value)
            return True
        if field_type == FieldType.CHECKBOX:
            on_state = widget.on_state()
            logger.debug("Checkbox on_state='%s', value='%s', will set to '%s'", on_state, value, on_state if value else "Off")
            widget_any.field_value = on_state if value else "Off"
            widget.update()
            return True
        if field_type == FieldType.RADIO:
            if not value:
                logger.debug("Radio has no value, skipping")
                return False
            on_state = widget.on_state()
            logger.debug("Radio on_state='%s', value='%s', will set to '%s'", on_state, value, on_state or value)
            widget_any.field_value = on_state or value
            widget.update()
            return True
    except Exception as e:
        logger.debug("Widget update failed: %s", e)
        return False
    return False


def fill_pdf(
    source: PdfSource,
    destination_path: str,
    fields: Sequence[DetectedField],
    answers: Mapping[str, str],
    horizontal_padding: float = 2.0,
    vertical_offset: float = 3.0,
) -> str:
    """Fill the provided PDF with the user's answers.

    Parameters
    ----------
    source:
        Either a path to the PDF or an in-memory byte-like object.
    destination_path:
        The path where the filled PDF should be saved.
    fields:
        The parsed form fields with positional data.
    answers:
        Mapping between field labels and user answers.
    horizontal_padding:
        Number of points to offset the text from the field's left boundary.
    vertical_offset:
        Vertical point offset to draw text slightly above the underline.

    Returns
    -------
    str
        Path to the saved, filled PDF.
    """

    logger.info("Starting fill for %d detected fields", len(fields))
    
    doc = fitz.open(stream=source, filetype="pdf") if not isinstance(source, str) else fitz.open(source)
    try:
        for field in fields:
            logger.debug(
                "Processing field page=%d label='%s' type=%s name=%s bbox=%s",
                field.page,
                field.label,
                field.field_type,
                field.form_field_name,
                field.bbox,
            )
            value = answers.get(field.label)
            if value is None:
                value = answers.get(field.raw_label)
            if value is None and field.form_field_name:
                value = answers.get(field.form_field_name)
            if not value:
                logger.debug("No value found for field '%s'; skipping", field.label)
                continue
            widget_filled = False
            if field.form_field_name:
                page = doc[field.page]
                widgets = _iter_page_widgets_by_name(page, field.form_field_name)
                if widgets:
                    widget = _match_widget_by_bbox(widgets, field.bbox)
                    if widget is not None:
                        widget_filled = _apply_value_to_widget(widget, field.field_type, value)
                        logger.debug("Widget fill attempt for '%s' success=%s", field.form_field_name, widget_filled)
            if widget_filled:
                logger.info("Filled widget '%s' via PyMuPDF", field.form_field_name)
                continue

            page = doc[field.page]
            x0, y0, x1, y1 = field.bbox
            # For checkbox / radio, center the symbol inside the bbox for better visibility
            if field.field_type in {FieldType.CHECKBOX, FieldType.RADIO}:
                rect = fitz.Rect(x0, y0, x1, y1)
                symbol = value
                if not symbol:
                    logger.debug("No symbol to draw for '%s' (unchecked); skipping draw", field.label)
                else:
                    page.insert_textbox(rect, symbol, fontsize=10, align=1)
                    logger.info("Drew symbol for field '%s' centered in %s", field.label, rect)
            else:
                # Place baseline slightly above underline for text-like fields
                insertion_y = (y1 if y1 >= y0 else y0) - vertical_offset
                insertion_point = (x0 + horizontal_padding, insertion_y)
                page.insert_text(insertion_point, value, fontsize=11)
                logger.info("Drew text for field '%s' at %s", field.label, insertion_point)
        doc.save(destination_path)
        logger.info("PyMuPDF-based fill complete; saved to %s", destination_path)
    finally:
        doc.close()
    return destination_path


__all__ = ["fill_pdf"]

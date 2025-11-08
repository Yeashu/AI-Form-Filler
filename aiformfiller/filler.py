"""Utilities to write user-provided data back into the PDF."""

from __future__ import annotations

from collections import defaultdict
from typing import BinaryIO, Dict, Mapping, Optional, Sequence, Tuple, Union

import fitz

from .models import DetectedField, FieldType

PdfSource = Union[str, bytes, BinaryIO]
WidgetKey = Tuple[int, str]


def _normalize_field_name(name: Optional[str]) -> Optional[str]:
    if isinstance(name, str):
        cleaned = name.strip()
        return cleaned or None
    return None


def _build_widget_lookup(doc: fitz.Document) -> Dict[WidgetKey, list[fitz.Widget]]:
    lookup: Dict[WidgetKey, list[fitz.Widget]] = defaultdict(list)
    for page_index in range(doc.page_count):
        page = doc[page_index]
        widgets = page.widgets()
        if not widgets:
            continue
        for widget in widgets:
            field_name = _normalize_field_name(getattr(widget, "field_name", None))
            if not field_name:
                continue
            lookup[(page_index, field_name)].append(widget)
    return lookup


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
    try:
        if field_type in {FieldType.TEXT, FieldType.TEXTBOX}:
            widget.field_value = value
            widget.update()
            return True
        if field_type == FieldType.CHECKBOX:
            on_state = widget.on_state()
            widget.field_value = on_state if value else "Off"
            widget.update()
            return True
        if field_type == FieldType.RADIO:
            if not value:
                return False
            on_state = widget.on_state()
            widget.field_value = on_state or value
            widget.update()
            return True
    except Exception:
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

    doc = fitz.open(stream=source, filetype="pdf") if not isinstance(source, str) else fitz.open(source)
    try:
        widget_lookup = _build_widget_lookup(doc)
        for field in fields:
            value = answers.get(field.label) or answers.get(field.raw_label)
            if not value:
                continue
            widget_filled = False
            if field.form_field_name:
                key = (field.page, field.form_field_name)
                widgets = widget_lookup.get(key)
                if widgets:
                    widget = _match_widget_by_bbox(widgets, field.bbox)
                    if widget is not None:
                        widget_filled = _apply_value_to_widget(widget, field.field_type, value)
            if widget_filled:
                continue

            page = doc[field.page]
            x0, y0, x1, y1 = field.bbox
            # Place the baseline slightly above the underline span so text sits over the line.
            insertion_y = (y1 if y1 >= y0 else y0) - vertical_offset
            insertion_point = (x0 + horizontal_padding, insertion_y)
            page.insert_text(insertion_point, value, fontsize=11)
        doc.save(destination_path)
    finally:
        doc.close()
    return destination_path


__all__ = ["fill_pdf"]

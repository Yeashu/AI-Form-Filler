"""PDF parsing utilities for detecting underline-based fields."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple, Union

import fitz

from .models import DetectedField, FieldType
from .utils import assign_unique_labels

_FIELD_REGEX = re.compile(r"([^:\n]+)\s*:\s*(?:_{3,}|\.{3,})")
_UNDERLINE_MARKERS = ("___", "...", "____")
_UNDERLINE_TOKEN_PATTERN = re.compile(r"(?:_{3,}|\.{3,})")
_CHECKBOX_PATTERN = re.compile(r"\[\s*(?:[xX✓✔✗✘]?)\s*\]")
_RADIO_PATTERN = re.compile(r"\(\s*(?:[xXoO•●]?)\s*\)")
_TEXTBOX_PATTERN = re.compile(
    r"""
    (?:
        \[\s*[_.\-‒–—=~\s]{3,}\s*\] |
        \{\s*[_.\-‒–—=~\s]{3,}\s*\} |
        \|\s*[_.\-‒–—=~\s]{3,}\s*\|
    )
    """,
    re.VERBOSE,
)
_BUTTON_PATTERN = re.compile(r"\[[^\]\n]{2,}\]")
_CHECKBOX_GLYPHS = frozenset({"☐", "☑", "☒", "■", "□", "▢", "⬜"})
_RADIO_GLYPHS = frozenset({"○", "◯", "⚪", "⚫", "●", "◉", "◎"})
_BUTTON_KEYWORDS = (
    "button",
    "submit",
    "reset",
    "print",
    "clear",
    "apply",
    "save",
    "send",
    "next",
    "back",
    "sign",
    "ok",
)
_TEXTBOX_ALLOWED_CHARS = frozenset("_ .-‒–—=~·")
_WIDGET_TYPE_MAP_STR = {
    "text": FieldType.TEXT,
    "textarea": FieldType.TEXTBOX,
    "textbox": FieldType.TEXTBOX,
    "combobox": FieldType.TEXTBOX,
    "combo": FieldType.TEXTBOX,
    "choice": FieldType.TEXTBOX,
    "listbox": FieldType.TEXTBOX,
    "checkbox": FieldType.CHECKBOX,
    "check": FieldType.CHECKBOX,
    "radio": FieldType.RADIO,
    "radiobutton": FieldType.RADIO,
    "button": FieldType.BUTTON,
    "pushbutton": FieldType.BUTTON,
    "submit": FieldType.BUTTON,
    "reset": FieldType.BUTTON,
}
_WIDGET_TYPE_MAP_INT: Dict[int, FieldType] = {}
_WIDGET_INT_PAIRS = {
    "PDF_WIDGET_TYPE_TEXT": FieldType.TEXT,
    "PDF_WIDGET_TYPE_CHECKBOX": FieldType.CHECKBOX,
    "PDF_WIDGET_TYPE_RADIOBUTTON": FieldType.RADIO,
    "PDF_WIDGET_TYPE_BUTTON": FieldType.BUTTON,
    "PDF_WIDGET_TYPE_COMBOBOX": FieldType.TEXTBOX,
    "PDF_WIDGET_TYPE_LISTBOX": FieldType.TEXTBOX,
}
for attr_name, field_type in _WIDGET_INT_PAIRS.items():
    value = getattr(fitz, attr_name, None)
    if isinstance(value, int):
        _WIDGET_TYPE_MAP_INT[value] = field_type

PdfSource = Union[str, bytes, BinaryIO]


def _should_inspect_text(text: str) -> bool:
    return _contains_field_marker(text)


def _contains_field_marker(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if any(marker in stripped for marker in _UNDERLINE_MARKERS):
        return True
    if any(glyph in stripped for glyph in _CHECKBOX_GLYPHS | _RADIO_GLYPHS):
        return True
    if _CHECKBOX_PATTERN.search(stripped):
        return True
    if _RADIO_PATTERN.search(stripped):
        return True
    if _TEXTBOX_PATTERN.search(stripped):
        return True
    if _BUTTON_PATTERN.search(stripped):
        return True
    return False


def _detect_button_subtype(widget: fitz.Widget) -> Optional[FieldType]:
    button_type = getattr(widget, "button_type", None)
    if isinstance(button_type, str):
        normalized = button_type.strip().lower()
        if normalized in {"check", "checkbox"}:
            return FieldType.CHECKBOX
        if normalized in {"radio", "radiobutton"}:
            return FieldType.RADIO
    field_flags = getattr(widget, "field_flags", None)
    if isinstance(field_flags, int):
        # PDF spec: radio flag bit 15, pushbutton bit 16
        if field_flags & (1 << 15):
            return FieldType.RADIO
        if field_flags & (1 << 16):
            return FieldType.BUTTON
        # Checkbox is default button when not radio / push
        if getattr(widget, "field_type", None) in (getattr(fitz, "PDF_WIDGET_TYPE_BUTTON", None), "button"):
            return FieldType.CHECKBOX
    return None


def _map_widget_field_type(widget: fitz.Widget) -> FieldType:
    widget_type = getattr(widget, "field_type", None)
    if isinstance(widget_type, int):
        mapped = _WIDGET_TYPE_MAP_INT.get(widget_type)
        if mapped:
            return mapped
    if isinstance(widget_type, str):
        normalized = widget_type.strip().lower()
        mapped = _WIDGET_TYPE_MAP_STR.get(normalized)
        if mapped:
            return mapped
    subtype = _detect_button_subtype(widget)
    if subtype:
        return subtype
    return FieldType.UNKNOWN


def _extract_widget_option_value(widget: fitz.Widget) -> Optional[str]:
    candidates = (
        getattr(widget, "export_value", None),
        getattr(widget, "export", None),
        getattr(widget, "value", None),
        getattr(widget, "field_value", None),
        getattr(widget, "field_default", None),
    )
    for candidate in candidates:
        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped:
                return stripped
    return None


def _format_widget_label(widget: fitz.Widget, fallback_index: int) -> Tuple[str, str, Optional[str]]:
    base_label = (
        getattr(widget, "field_label", None)
        or getattr(widget, "field_name", None)
        or getattr(widget, "name", None)
    )
    if not isinstance(base_label, str) or not base_label.strip():
        base_label = f"Field {fallback_index}"
    base_label = base_label.strip()
    option_value = _extract_widget_option_value(widget)
    if isinstance(option_value, str):
        normalized_value = option_value.strip()
        if normalized_value and normalized_value.lower() not in {"off", "false"}:
            return f"{base_label} ({normalized_value})", base_label, normalized_value
    return base_label, base_label, None


def _classify_marker_text(text: str) -> Optional[FieldType]:
    stripped = text.strip()
    if not stripped:
        return None

    enclosed_type = _classify_enclosed_token(stripped)
    if enclosed_type is not None:
        return enclosed_type
    if any(ch in _CHECKBOX_GLYPHS for ch in stripped):
        return FieldType.CHECKBOX
    if any(ch in _RADIO_GLYPHS for ch in stripped):
        return FieldType.RADIO
    if _UNDERLINE_TOKEN_PATTERN.search(stripped):
        return FieldType.TEXT
    return None


def _classify_enclosed_token(text: str) -> Optional[FieldType]:
    if len(text) < 2:
        return None
    start, end = text[0], text[-1]
    inner = text[1:-1]
    pair = f"{start}{end}"

    if pair in {"[]", "{}", "||"}:
        if _is_checkbox_inner(inner):
            return FieldType.CHECKBOX
        if _looks_like_textbox_inner(inner):
            return FieldType.TEXTBOX
        if _looks_like_button_inner(inner):
            return FieldType.BUTTON
    if pair == "()":
        if _is_radio_inner(inner):
            return FieldType.RADIO
    return None


def _is_checkbox_inner(inner: str) -> bool:
    stripped = inner.strip().lower()
    if not stripped:
        return True
    return stripped in {"x", "✓", "✔", "✗", "✘"}


def _is_radio_inner(inner: str) -> bool:
    stripped = inner.strip().lower()
    if not stripped:
        return True
    return stripped in {"x", "o", "0", "•", "●"}


def _looks_like_textbox_inner(inner: str) -> bool:
    collapsed = inner.replace(" ", "")
    if not collapsed:
        return len(inner) >= 3
    if len(collapsed) < 3:
        return False
    return all(ch in _TEXTBOX_ALLOWED_CHARS for ch in collapsed)


def _looks_like_button_inner(inner: str) -> bool:
    cleaned = inner.strip().lower()
    if not cleaned:
        return False
    return any(keyword in cleaned for keyword in _BUTTON_KEYWORDS)


def _iter_line_spans(doc: fitz.Document) -> Iterator[Tuple[int, str, dict]]:
    for page_index in range(doc.page_count):
        page = doc[page_index]
        raw_dict = page.get_text("rawdict")
        if not isinstance(raw_dict, dict):
            continue
        blocks = raw_dict.get("blocks", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != 0:
                continue
            lines = block.get("lines", [])
            if not isinstance(lines, list):
                continue
            for line in lines:
                if not isinstance(line, dict):
                    continue
                spans = line.get("spans", [])
                if not isinstance(spans, list):
                    continue
                line_text = "".join(span.get("text", "") for span in spans if isinstance(span, dict))
                for span in spans:
                    if not isinstance(span, dict):
                        continue
                    yield page_index, line_text, span


def _extract_label(text: str) -> str:
    match = _FIELD_REGEX.search(text)
    if match:
        return match.group(1).strip()
    if ":" in text:
        return text.split(":", 1)[0].strip()
    candidate = text.replace("_", " ").replace(".", " ")
    return candidate.strip().splitlines()[0][:64].strip()


def _collect_widget_fields(doc: fitz.Document) -> List[DetectedField]:
    fields: List[DetectedField] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        widgets = page.widgets()
        if not widgets:
            continue
        for widget in widgets:
            rect = getattr(widget, "rect", None)
            if rect is None:
                continue
            label, base_label, option_value = _format_widget_label(widget, len(fields) + 1)
            field_type = _map_widget_field_type(widget)
            bbox = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
            raw_group_key = getattr(widget, "field_name", None)
            if isinstance(raw_group_key, str):
                raw_group_key = raw_group_key.strip() or None
            group_key = raw_group_key or base_label
            if field_type != FieldType.RADIO:
                group_key = None
            fields.append(
                DetectedField(
                    page=page_index,
                    label=label,
                    bbox=bbox,
                    raw_label=label,
                    field_type=field_type,
                    group_key=group_key,
                    export_value=option_value,
                )
            )
    return fields


def _collect_span_fields(doc: fitz.Document) -> List[DetectedField]:
    fields: List[DetectedField] = []
    for page_index, line_text, span in _iter_line_spans(doc):
        raw_text = span.get("text", "")
        text = raw_text if isinstance(raw_text, str) else ""
        field_type = _classify_marker_text(text)
        if field_type is None:
            continue
        raw_label = _extract_label(line_text) or f"Field {len(fields) + 1}"
        bbox_tuple = tuple(float(coord) for coord in span.get("bbox", ()))
        if len(bbox_tuple) != 4:
            continue
        fields.append(
            DetectedField(
                page=page_index,
                label=raw_label,
                bbox=bbox_tuple,
                raw_label=raw_label,
                field_type=field_type,
            )
        )
    return fields


def _is_underline_token(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return all(ch in {"_", "."} for ch in stripped) and ("_" in stripped or "." in stripped)


def _locate_underline_bbox(
    words: List[Tuple[float, float, float, float, str, int, int, int]],
    block_bbox: Tuple[float, float, float, float],
) -> Optional[Tuple[float, float, float, float]]:
    x0, y0, x1, y1 = block_bbox
    best_bbox: Optional[Tuple[float, float, float, float]] = None
    best_width = 0.0
    for word in words:
        wx0, wy0, wx1, wy1, wtext, *_ = word
        if not _is_underline_token(wtext):
            continue
        if wy1 < y0 - 2.0 or wy0 > y1 + 2.0:
            continue
        width = wx1 - wx0
        if width > best_width:
            best_width = width
            best_bbox = (float(wx0), float(wy0), float(wx1), float(wy1))
    return best_bbox


def _collect_symbol_bboxes(
    words: List[Tuple[float, float, float, float, str, int, int, int]],
) -> Dict[FieldType, List[Tuple[float, float, float, float]]]:
    symbols: Dict[FieldType, List[Tuple[float, float, float, float]]] = defaultdict(list)
    for word in words:
        wx0, wy0, wx1, wy1, wtext, *_ = word
        marker_type = _classify_marker_text(wtext)
        if marker_type is None or marker_type == FieldType.TEXT:
            continue
        symbols[marker_type].append((float(wx0), float(wy0), float(wx1), float(wy1)))
    return symbols


def _collect_block_fields(doc: fitz.Document) -> List[DetectedField]:
    fields: List[DetectedField] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        words_raw = page.get_text("words")
        if not isinstance(words_raw, list):
            continue
        words = [
            (
                float(word[0]),
                float(word[1]),
                float(word[2]),
                float(word[3]),
                str(word[4]),
                int(word[5]),
                int(word[6]),
                int(word[7]),
            )
            for word in words_raw
            if isinstance(word, (list, tuple)) and len(word) >= 8
        ]
        words_by_block: Dict[int, List[Tuple[float, float, float, float, str, int, int, int]]] = defaultdict(list)
        for word in words:
            block_id = word[5]
            words_by_block[block_id].append(word)

        blocks_raw = page.get_text("blocks")
        if not isinstance(blocks_raw, list):
            continue
        for block_index, block in enumerate(blocks_raw):
            if len(block) < 5:
                continue
            bx0, by0, bx1, by1, text, *_ = block
            if not isinstance(text, str):
                continue
            if not _should_inspect_text(text):
                continue
            raw_label = _extract_label(text) or f"Field {len(fields) + 1}"
            block_bbox = (float(bx0), float(by0), float(bx1), float(by1))
            block_words = words_by_block.get(block_index, [])
            underline_bbox = _locate_underline_bbox(block_words, block_bbox)
            symbol_bboxes = _collect_symbol_bboxes(block_words)
            if underline_bbox is None and not symbol_bboxes:
                continue

            if underline_bbox is not None:
                fields.append(
                    DetectedField(
                        page=page_index,
                        label=raw_label,
                        bbox=underline_bbox,
                        raw_label=raw_label,
                        field_type=FieldType.TEXT,
                    )
                )
            for marker_type, bboxes in symbol_bboxes.items():
                seen: set[Tuple[float, float, float, float]] = set()
                for bbox in bboxes:
                    if bbox in seen:
                        continue
                    seen.add(bbox)
                    fields.append(
                        DetectedField(
                            page=page_index,
                            label=raw_label,
                            bbox=bbox,
                            raw_label=raw_label,
                            field_type=marker_type,
                        )
                    )
    return fields


def extract_fields(source: PdfSource) -> List[DetectedField]:
    doc = fitz.open(stream=source, filetype="pdf") if not isinstance(source, str) else fitz.open(source)
    try:
        collected_fields: List[DetectedField] = []
        widget_fields = _collect_widget_fields(doc)
        if widget_fields:
            collected_fields.extend(widget_fields)

        span_fields = _collect_span_fields(doc)
        if span_fields:
            collected_fields.extend(span_fields)
        else:
            collected_fields.extend(_collect_block_fields(doc))

        return assign_unique_labels(collected_fields)
    finally:
        doc.close()


__all__ = ["extract_fields"]

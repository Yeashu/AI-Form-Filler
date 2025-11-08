"""PDF parsing utilities for detecting underline-based fields."""

from __future__ import annotations

import re
from typing import BinaryIO, Iterator, List, Optional, Tuple, Union

import fitz

from .models import DetectedField
from .utils import assign_unique_labels

_FIELD_REGEX = re.compile(r"([^:\n]+)\s*:\s*(?:_{3,}|\.{3,})")
_UNDERLINE_MARKERS = ("___", "...", "____")

PdfSource = Union[str, bytes, BinaryIO]


def _should_inspect_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return any(marker in stripped for marker in _UNDERLINE_MARKERS)


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


def _collect_span_fields(doc: fitz.Document) -> List[DetectedField]:
    fields: List[DetectedField] = []
    for page_index, line_text, span in _iter_line_spans(doc):
        text = span.get("text", "")
        if not text or not _should_inspect_text(text):
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
    block_index: int,
    block_bbox: Tuple[float, float, float, float],
) -> Optional[Tuple[float, float, float, float]]:
    x0, y0, x1, y1 = block_bbox
    best_bbox: Optional[Tuple[float, float, float, float]] = None
    best_width = 0.0
    for word in words:
        wx0, wy0, wx1, wy1, wtext, wblock, *_ = word
        if wblock != block_index:
            continue
        if not _is_underline_token(wtext):
            continue
        if wy1 < y0 - 2.0 or wy0 > y1 + 2.0:
            continue
        width = wx1 - wx0
        if width > best_width:
            best_width = width
            best_bbox = (float(wx0), float(wy0), float(wx1), float(wy1))
    return best_bbox


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
            underline_bbox = _locate_underline_bbox(
                words,
                block_index,
                (float(bx0), float(by0), float(bx1), float(by1)),
            )
            if underline_bbox is None:
                continue
            fields.append(
                DetectedField(
                    page=page_index,
                    label=raw_label,
                    bbox=underline_bbox,
                    raw_label=raw_label,
                )
            )
    return fields


def extract_fields(source: PdfSource) -> List[DetectedField]:
    doc = fitz.open(stream=source, filetype="pdf") if not isinstance(source, str) else fitz.open(source)
    try:
        fields = _collect_span_fields(doc)
        if not fields:
            fields = _collect_block_fields(doc)
        return assign_unique_labels(fields)
    finally:
        doc.close()


__all__ = ["extract_fields"]

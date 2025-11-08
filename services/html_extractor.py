"""Utilities for converting PDFs into HTML forms ready for downstream processing."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import logging
import string

import fitz
import pdfplumber

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FieldLayout:
    """Describe how a logical field maps to PDF widgets."""

    kind: str = "single"
    rows: int = 1
    columns: int = 1


@dataclass
class PDFFormField:
    """Lightweight container for form field metadata extracted from the PDF."""

    name: str
    field_type: str
    default_value: str
    label: str = ""
    options: Optional[List[str]] = None
    page: int = 0
    rect: Optional[Tuple[float, float, float, float]] = None


@dataclass
class GroupedField:
    html_name: str
    label: str
    field_type: str
    default_value: str
    options: Optional[List[str]]
    widget_names: List[str]
    layout: FieldLayout
    order: Tuple[int, float, float]


class HTMLExtractor:
    """Convert interactive PDFs into HTML form markup and collect basic metadata."""

    def pdf_to_html(self, pdf_path: str) -> Tuple[str, Dict[str, List[str]], Dict[str, FieldLayout]]:
        """Render the supplied PDF as a basic HTML form and return mapping metadata."""

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        with fitz.open(path) as document:
            fields = self._collect_form_fields_with_pymupdf(document)

        logger.info(
            "[HTMLExtractor] Extracted %s form widgets from '%s' via PyMuPDF",
            len(fields),
            path.name,
        )

        if not fields:
            logger.warning(
                "[HTMLExtractor] No interactive widgets detected in '%s'. Falling back to text-only HTML.",
                path.name,
            )
            return self._build_text_fallback(path), {}, {}

        grouped_fields = self._group_fields(fields)
        html = self._render_grouped_fields(grouped_fields)
        field_mappings = {group.html_name: group.widget_names for group in grouped_fields}
        field_layouts = {group.html_name: group.layout for group in grouped_fields}
        return html, field_mappings, field_layouts

    def extract_pdf_metadata(self, pdf_path: str) -> Dict[str, Any]:
        """Extract high-level metadata about the PDF form."""

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        with fitz.open(path) as document:
            metadata = dict(document.metadata or {})
            has_form_fields = any(page.widgets() for page in document)
            return {
                "form_name": metadata.get("title") or metadata.get("Title") or path.stem,
                "num_pages": document.page_count,
                "has_form_fields": bool(has_form_fields),
                "author": metadata.get("author") or metadata.get("Author"),
                "created_date": metadata.get("creationDate") or metadata.get("CreationDate"),
            }

    def _build_text_fallback(self, path: Path) -> str:
        with pdfplumber.open(path) as pdf:
            page_texts = [page.extract_text() or "" for page in pdf.pages]

        paragraphs = "\n".join(
            f"<p>{self._escape_html(block)}</p>" for block in page_texts if block
        )
        return (
            "<html><body><form>\n"
            "<p>No interactive fields detected. Captured page content below:</p>\n"
            f"{paragraphs}\n"
            "</form></body></html>"
        )

    def _collect_form_fields_with_pymupdf(self, document: fitz.Document) -> List[PDFFormField]:
        collected: List[PDFFormField] = []
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            widgets = page.widgets() or []
            for widget in widgets:
                name = widget.field_name or widget.field_label
                if not name:
                    logger.debug(
                        "[HTMLExtractor] PyMuPDF widget without name on page %s; skipping.",
                        page_index,
                    )
                    continue
                field_type = self._map_widget_type(widget.field_type)
                default_value = widget.field_value or ""
                label = (widget.field_label or "").strip()
                if not label or self._looks_like_gibberish(label):
                    label = self._infer_widget_label(page, widget.rect)
                options = None
                if field_type == "select":
                    options = [choice[1] for choice in (widget.choices or [])]
                collected.append(
                    PDFFormField(
                        name=name,
                        field_type=field_type,
                        default_value=str(default_value),
                        label=label,
                        options=options,
                        page=page_index,
                        rect=(widget.rect.x0, widget.rect.y0, widget.rect.x1, widget.rect.y1),
                    )
                )
        return collected

    def _group_fields(self, fields: List[PDFFormField]) -> List[GroupedField]:
        grouped: List[GroupedField] = []
        assigned: set[int] = set()
        used_names: set[str] = set()

        page_rows = self._cluster_rows(fields)

        # Identify table-like structures first (multiple consecutive rows with matching signatures).
        for page, rows in page_rows.items():
            signature_map: Dict[Tuple[Tuple[int, int], ...], List[int]] = defaultdict(list)
            for row_index, row in enumerate(rows):
                if row["signature"]:
                    signature_map[row["signature"]].append(row_index)

            for indices in signature_map.values():
                for seq in self._split_consecutive(indices):
                    if len(seq) < 2:
                        continue
                    first_row = rows[seq[0]]
                    if len(first_row["indices"]) < 2:
                        continue
                    widget_indices = [idx for row_idx in seq for idx in rows[row_idx]["indices"]]
                    if any(idx in assigned for idx in widget_indices):
                        continue

                    label = self._choose_group_label(fields, widget_indices)
                    html_name = self._make_html_name(fields[widget_indices[0]].name, used_names)
                    row_values: List[str] = []
                    for row_idx in seq:
                        row_indices = rows[row_idx]["indices"]
                        row_text = [fields[idx].default_value.strip() for idx in row_indices]
                        row_values.append(", ".join(value for value in row_text if value))

                    anchor = fields[widget_indices[0]]
                    order = (
                        anchor.page,
                        anchor.rect[1] if anchor.rect else 0.0,
                        anchor.rect[0] if anchor.rect else 0.0,
                    )

                    grouped.append(
                        GroupedField(
                            html_name=html_name,
                            label=label,
                            field_type="textarea",
                            default_value="\n".join(row_values).strip(),
                            options=None,
                            widget_names=[fields[idx].name for idx in widget_indices],
                            layout=FieldLayout(
                                kind="table",
                                rows=len(seq),
                                columns=len(first_row["indices"]),
                            ),
                            order=order,
                        )
                    )
                    assigned.update(widget_indices)

        # Identify single-row grids of small boxes (character boxes).
        for rows in page_rows.values():
            for row in rows:
                row_indices = row["indices"]
                if any(idx in assigned for idx in row_indices):
                    continue
                if len(row_indices) >= 4 and row["max_width"] <= 35:
                    widget_indices = row_indices
                    label = self._choose_group_label(fields, widget_indices)
                    html_name = self._make_html_name(fields[widget_indices[0]].name, used_names)
                    default_value = "".join(fields[idx].default_value or "" for idx in widget_indices)
                    anchor = fields[widget_indices[0]]
                    order = (
                        anchor.page,
                        anchor.rect[1] if anchor.rect else 0.0,
                        anchor.rect[0] if anchor.rect else 0.0,
                    )

                    grouped.append(
                        GroupedField(
                            html_name=html_name,
                            label=label,
                            field_type="text",
                            default_value=default_value,
                            options=None,
                            widget_names=[fields[idx].name for idx in widget_indices],
                            layout=FieldLayout(kind="grid", rows=1, columns=len(widget_indices)),
                            order=order,
                        )
                    )
                    assigned.update(widget_indices)

        # Group repeated labels into simple tables when they form consistent rows.
        label_rows: Dict[Tuple[int, str], List[List[int]]] = defaultdict(list)
        for page, rows in page_rows.items():
            for row in rows:
                remaining = [idx for idx in row["indices"] if idx not in assigned]
                if not remaining:
                    continue
                labels = {self._normalise_label(fields[idx].label) for idx in remaining}
                if len(labels) != 1:
                    continue
                label_rows[(page, labels.pop())].append(remaining)

        for (page, norm_label), row_groups in label_rows.items():
            # Require at least two rows to consider a table grouping.
            if len(row_groups) < 2:
                continue

            lengths = {len(group) for group in row_groups}
            if len(lengths) != 1:
                continue

            max_columns = lengths.pop()
            widget_indices = [idx for group in row_groups for idx in group]
            if any(idx in assigned for idx in widget_indices):
                continue

            anchor = fields[row_groups[0][0]]
            label = self._choose_group_label(fields, widget_indices)
            html_name = self._make_html_name(anchor.name, used_names)

            default_rows: List[str] = []
            ordered_widget_names: List[str] = []
            for group in row_groups:
                sorted_group = sorted(group, key=lambda idx: fields[idx].rect[0] if fields[idx].rect else 0)
                ordered_widget_names.extend(fields[idx].name for idx in sorted_group)
                row_text = [fields[idx].default_value.strip() for idx in sorted_group]
                default_rows.append(", ".join(value for value in row_text if value))

            order = (
                anchor.page,
                anchor.rect[1] if anchor.rect else 0.0,
                anchor.rect[0] if anchor.rect else 0.0,
            )

            layout = FieldLayout(
                kind="table",
                rows=len(row_groups),
                columns=max_columns,
            )

            grouped.append(
                GroupedField(
                    html_name=html_name,
                    label=label,
                    field_type="textarea",
                    default_value="\n".join(default_rows).strip(),
                    options=None,
                    widget_names=ordered_widget_names,
                    layout=layout,
                    order=order,
                )
            )
            assigned.update(widget_indices)

        # Add remaining widgets as standalone fields.
        for index, field in enumerate(fields):
            if index in assigned:
                continue

            html_name = self._make_html_name(field.name, used_names)
            label = self._choose_group_label(fields, [index])
            default_value = field.default_value
            layout = FieldLayout(kind="single", rows=1, columns=1)

            anchor = field
            order = (
                anchor.page,
                anchor.rect[1] if anchor.rect else 0.0,
                anchor.rect[0] if anchor.rect else 0.0,
            )

            grouped.append(
                GroupedField(
                    html_name=html_name,
                    label=label,
                    field_type=field.field_type,
                    default_value=default_value,
                    options=field.options,
                    widget_names=[field.name],
                    layout=layout,
                    order=order,
                )
            )

        return grouped

    def _render_grouped_fields(self, grouped: List[GroupedField]) -> str:
        parts: List[str] = ["<html><body><form>"]
        for field in sorted(grouped, key=lambda item: item.order):
            label = self._escape_html(field.label or self._derive_label_from_name(field.html_name))
            data_attrs = ""
            if field.layout.kind in {"grid", "table"}:
                data_attrs = (
                    f" data-field-kind=\"{field.layout.kind}\""
                    f" data-field-rows=\"{field.layout.rows}\""
                    f" data-field-columns=\"{field.layout.columns}\""
                )

            if field.layout.kind == "table":
                parts.append(
                    f"<label for=\"{field.html_name}\">{label}</label>"
                    f"<textarea name=\"{field.html_name}\" id=\"{field.html_name}\"{data_attrs}>{self._escape_html(field.default_value)}</textarea>"
                )
                continue

            if field.options and field.field_type == "select":
                options_markup = "".join(
                    f"<option value=\"{self._escape_html(option)}\">{self._escape_html(option)}</option>"
                    for option in field.options
                )
                parts.append(
                    f"<label for=\"{field.html_name}\">{label}</label>"
                    f"<select name=\"{field.html_name}\" id=\"{field.html_name}\"{data_attrs}>{options_markup}</select>"
                )
                continue

            if field.field_type in {"checkbox", "radio"}:
                value_attribute = self._escape_html(field.default_value or "Yes")
                checked_attr = ""
                if (field.default_value or "").strip().lower() in {"yes", "true", "1", "on"}:
                    checked_attr = " checked"
                parts.append(
                    f"<label for=\"{field.html_name}\">{label}</label>"
                    f"<input type=\"{field.field_type}\" name=\"{field.html_name}\" id=\"{field.html_name}\" value=\"{value_attribute}\"{checked_attr}{data_attrs}/>")
                continue

            maxlength_attr = ""
            if field.layout.kind == "grid" and field.layout.columns:
                maxlength_attr = f" maxlength=\"{field.layout.columns}\""

            value_attr = (
                f" value=\"{self._escape_html(field.default_value)}\"" if field.default_value else ""
            )
            parts.append(
                f"<label for=\"{field.html_name}\">{label}</label>"
                f"<input type=\"text\" name=\"{field.html_name}\" id=\"{field.html_name}\"{data_attrs}{maxlength_attr}{value_attr}/>"
            )

        parts.append("<button type=\"submit\">Submit</button>")
        parts.append("</form></body></html>")
        return "\n".join(parts)

    def _cluster_rows(self, fields: List[PDFFormField]) -> Dict[int, List[Dict[str, Any]]]:
        by_page: Dict[int, List[int]] = defaultdict(list)
        for index, field in enumerate(fields):
            if field.field_type != "text" or not field.rect:
                continue
            by_page[field.page].append(index)

        page_rows: Dict[int, List[Dict[str, Any]]] = {}
        for page, indices in by_page.items():
            sorted_indices = sorted(indices, key=lambda idx: fields[idx].rect[1])
            rows: List[List[int]] = []
            current: List[int] = []
            current_top: Optional[float] = None

            for idx in sorted_indices:
                rect = fields[idx].rect
                if rect is None:
                    continue
                top = rect[1]
                height = rect[3] - rect[1]
                if current and current_top is not None:
                    threshold = max(6.0, height * 0.6)
                    if abs(top - current_top) <= threshold:
                        current.append(idx)
                        current_top = min(current_top, top)
                    else:
                        rows.append(current)
                        current = [idx]
                        current_top = top
                else:
                    current = [idx]
                    current_top = top

            if current:
                rows.append(current)

            row_infos: List[Dict[str, Any]] = []
            for row in rows:
                sorted_row = sorted(row, key=lambda idx: fields[idx].rect[0] if fields[idx].rect else 0)
                widths = [self._width(fields[idx]) for idx in sorted_row]
                row_infos.append(
                    {
                        "indices": sorted_row,
                        "signature": self._row_signature(sorted_row, fields),
                        "max_width": max(widths) if widths else 0.0,
                    }
                )
            page_rows[page] = row_infos

        return page_rows

    def _row_signature(self, indices: Iterable[int], fields: List[PDFFormField]) -> Tuple[Tuple[int, int], ...]:
        signature: List[Tuple[int, int]] = []
        for idx in indices:
            rect = fields[idx].rect
            if not rect:
                continue
            left = int(round(rect[0] / 5))
            width = int(round((rect[2] - rect[0]) / 5))
            signature.append((left, width))
        return tuple(signature)

    def _split_consecutive(self, values: List[int]) -> List[List[int]]:
        if not values:
            return []
        ordered = sorted(values)
        sequences: List[List[int]] = [[ordered[0]]]
        for value in ordered[1:]:
            if value == sequences[-1][-1] + 1:
                sequences[-1].append(value)
            else:
                sequences.append([value])
        return sequences

    def _choose_group_label(self, fields: List[PDFFormField], indices: List[int]) -> str:
        for idx in indices:
            label = (fields[idx].label or "").strip()
            if label and not self._looks_like_gibberish(label):
                return label
        return self._derive_label_from_name(fields[indices[0]].name if indices else "field")

    def _make_html_name(self, base: str, used: set[str]) -> str:
        sanitized = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in base or "field")
        if not sanitized:
            sanitized = "field"
        candidate = sanitized
        counter = 2
        while candidate in used:
            candidate = f"{sanitized}_{counter}"
            counter += 1
        used.add(candidate)
        return candidate

    def _looks_like_gibberish(self, text: str) -> bool:
        if not text:
            return True
        letters = sum(ch.isalpha() for ch in text)
        vowels = sum(ch.lower() in "aeiou" for ch in text if ch.isalpha())
        punctuation = sum(ch in string.punctuation for ch in text)
        if letters and vowels == 0:
            return True
        if punctuation / len(text) > 0.3:
            return True
        return False

    def _normalise_label(self, text: str) -> str:
        cleaned = (text or "").strip().lower()
        return " ".join(cleaned.split())

    def _width(self, field: PDFFormField) -> float:
        if not field.rect:
            return 0.0
        return field.rect[2] - field.rect[0]

    def _map_widget_type(self, widget_type: int) -> str:
        mapping = {
            7: "text",  # Text field
            2: "checkbox",
            3: "checkbox",
            4: "radio",
            6: "select",
        }
        return mapping.get(widget_type, "text")

    def _infer_widget_label(self, page: fitz.Page, rect: fitz.Rect) -> str:
        """Approximate a human-readable label based on nearby text."""

        word_entries = page.get_text("words") or []
        if not word_entries:
            return ""

        grouped: Dict[Tuple[int, int], List[Tuple[float, float, float, float, str]]] = {}
        for x0, y0, x1, y1, text, block_no, line_no, *_ in word_entries:
            if not text.strip():
                continue
            grouped.setdefault((block_no, line_no), []).append((x0, y0, x1, y1, text))

        best_label = ""
        best_score = (3, float("inf"), float("inf"))

        for entries in grouped.values():
            x0 = min(item[0] for item in entries)
            y0 = min(item[1] for item in entries)
            x1 = max(item[2] for item in entries)
            y1 = max(item[3] for item in entries)

            if y1 < rect.y0:
                vertical_distance = rect.y0 - y1
            elif y0 > rect.y1:
                vertical_distance = y0 - rect.y1
            else:
                vertical_distance = 0.0

            if x1 <= rect.x0:
                horizontal_distance = rect.x0 - x1
                position_rank = 0  # prefer labels to the left
            elif x0 >= rect.x1:
                horizontal_distance = x0 - rect.x1
                position_rank = 2  # labels to the right last
            else:
                horizontal_distance = 0.0
                position_rank = 1  # overlapping

            # Skip lines that are too far away spatially.
            max_vertical = max(30.0, rect.height * 2)
            if vertical_distance > max_vertical or horizontal_distance > 200:
                continue

            score = (position_rank, horizontal_distance, vertical_distance)
            if score < best_score:
                sorted_entries = sorted(entries, key=lambda item: item[0])
                candidate = " ".join(text for *_, text in sorted_entries).strip()
                if candidate:
                    best_label = candidate
                    best_score = score

        if not best_label:
            return ""

        cleaned = " ".join(best_label.split())
        if ":" in cleaned:
            cleaned = cleaned.split(":")[-1].strip() or cleaned
        if cleaned.count(".") >= len(cleaned) / 2:
            cleaned = cleaned.replace(".", "").strip()
        return cleaned

    def _derive_label_from_name(self, name: str) -> str:
        cleaned = name.replace("_", " ").replace(".", " ")
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            return "Field"
        return cleaned.title()

    def _escape_html(self, value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

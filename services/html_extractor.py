"""Utilities for converting PDFs into HTML forms ready for downstream processing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import logging
import fitz
import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class PDFFormField:
    """Lightweight container for form field metadata extracted from the PDF."""

    name: str
    field_type: str
    default_value: str
    label: str = ""
    options: Optional[List[str]] = None


class HTMLExtractor:
    """Convert interactive PDFs into HTML form markup and collect basic metadata."""

    def pdf_to_html(self, pdf_path: str) -> str:
        """Render the supplied PDF as a basic HTML form.

        Args:
            pdf_path: Absolute or relative path to an interactive PDF.

        Returns:
            HTML string containing a `<form>` element populated with inputs that
            mirror the PDF form fields. When the PDF is not interactive, the
            method falls back to a static text representation so later stages can
            still operate on the document.
        """

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        with pdfplumber.open(path) as pdf:
            fields = self._collect_form_fields(pdf)
            logger.info(
                "[HTMLExtractor] Extracted %s form fields from '%s' via pdfplumber",
                len(fields),
                path.name,
            )
            page_texts = [page.extract_text() or "" for page in pdf.pages]

        if not fields:
            fallback_fields = self._collect_form_fields_with_pymupdf(path)
            logger.info(
                "[HTMLExtractor] PyMuPDF fallback detected %s form fields in '%s'",
                len(fallback_fields),
                path.name,
            )
            fields = fallback_fields

        if fields:
            inputs_html = "\n".join(
                self._build_input_markup(field) for field in fields
            )
            return (
                "<html><body><form>\n"
                f"{inputs_html}\n"
                "<button type=\"submit\">Submit</button>\n"
                "</form></body></html>"
            )

        paragraphs = "\n".join(
            f"<p>{self._escape_html(block)}</p>" for block in page_texts if block
        )
        logger.warning(
            "[HTMLExtractor] No interactive fields detected in '%s'. Returning text-only HTML fallback.",
            path.name,
        )
        return (
            "<html><body><form>\n"
            "<p>No interactive fields detected. Captured page content below:</p>\n"
            f"{paragraphs}\n"
            "</form></body></html>"
        )

    def extract_pdf_metadata(self, pdf_path: str) -> Dict[str, Any]:
        """Extract high-level metadata about the PDF form."""

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        with pdfplumber.open(path) as pdf:
            metadata = dict(pdf.metadata or {})
            form_fields = self._collect_form_fields(pdf)
            return {
                "form_name": metadata.get("Title") or path.stem,
                "num_pages": len(pdf.pages),
                "has_form_fields": bool(form_fields),
                "author": metadata.get("Author"),
                "created_date": metadata.get("CreationDate"),
            }

    def _collect_form_fields(self, pdf: pdfplumber.PDF) -> List[PDFFormField]:
        """Extract AcroForm field definitions from the PDF if present."""

        catalog = getattr(pdf, "root", None)
        if not catalog:
            logger.debug("[HTMLExtractor] PDF root catalog missing; cannot inspect AcroForm.")
            return []

        acro_form = catalog.get("AcroForm") if isinstance(catalog, dict) else None
        if not acro_form:
            logger.debug("[HTMLExtractor] No AcroForm dictionary present in PDF.")
            return []

        resolved_form = pdf.doc.resolve(acro_form) if hasattr(pdf, "doc") else None
        if not resolved_form:
            logger.debug("[HTMLExtractor] Unable to resolve AcroForm reference.")
            return []

        fields = resolved_form.get("Fields", [])
        collected: List[PDFFormField] = []
        for field_ref in fields:
            field_dict = pdf.doc.resolve(field_ref)
            if not isinstance(field_dict, dict):
                logger.debug("[HTMLExtractor] Skipping non-dict field entry: %s", type(field_dict))
                continue
            name = self._decode_if_needed(field_dict.get("T"))
            if not name:
                logger.debug("[HTMLExtractor] Encountered field without a name; skipping.")
                continue
            field_type = field_dict.get("FT", "text")
            default_value = self._decode_if_needed(field_dict.get("V", ""))
            options = self._coerce_options(field_dict.get("Opt"))
            label = self._decode_if_needed(field_dict.get("TU", ""))
            collected.append(
                PDFFormField(
                    name=name,
                    field_type=str(field_type),
                    default_value=default_value,
                    label=label,
                    options=options,
                )
            )
        return collected

    def _collect_form_fields_with_pymupdf(self, path: Path) -> List[PDFFormField]:
        """Fallback AcroForm extraction using PyMuPDF when pdfplumber returns nothing."""

        collected: List[PDFFormField] = []
        with fitz.open(path) as doc:
            for page_index in range(doc.page_count):
                page = doc.load_page(page_index)
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
                    if not label:
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
                        )
                    )
        return collected

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

    def _build_input_markup(self, field: PDFFormField) -> str:
        """Create simple HTML markup for a single input field."""

        label = field.label.strip() or self._derive_label_from_name(field.name)
        label = self._escape_html(label)
        input_type = self._map_field_type(field.field_type)
        if field.options and input_type == "select":
            options_markup = "".join(
                f"<option value=\"{self._escape_html(option)}\">{self._escape_html(option)}</option>"
                for option in field.options
            )
            return (
                f"<label for=\"{field.name}\">{label}</label>"
                f"<select name=\"{field.name}\" id=\"{field.name}\">{options_markup}</select>"
            )

        value_attribute = (
            f" value=\"{self._escape_html(field.default_value)}\""
            if field.default_value
            else ""
        )
        return (
            f"<label for=\"{field.name}\">{label}</label>"
            f"<input type=\"{input_type}\" name=\"{field.name}\" id=\"{field.name}\"{value_attribute}/>"
        )

    def _derive_label_from_name(self, name: str) -> str:
        cleaned = name.replace("_", " ").replace(".", " ")
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            return "Field"
        return cleaned.title()

    def _map_field_type(self, field_type: str) -> str:
        mapping = {
            "Btn": "checkbox",
            "Ch": "select",
            "Sig": "text",
            "Tx": "text",
        }
        return mapping.get(field_type, "text")

    def _decode_if_needed(self, value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        if value is None:
            return ""
        return str(value)

    def _coerce_options(self, raw_options: Any) -> Optional[List[str]]:
        if raw_options is None:
            return None
        if isinstance(raw_options, (list, tuple)):
            processed = [self._decode_if_needed(option) for option in raw_options]
            return [option for option in processed if option]
        return [self._decode_if_needed(raw_options)]

    def _escape_html(self, value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

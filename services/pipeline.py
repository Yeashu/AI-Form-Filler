"""High-level orchestration for the HTML-based form filling pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Tuple

from models.conversation_state import ConversationState
from services.field_detector import FieldDetector, DetectedField
from services.html_extractor import HTMLExtractor, FieldLayout
from services.html_filler import HTMLFiller
from services.pdf_filler import PDFFiller


@dataclass(frozen=True)
class FormExtractionResult:
    """Container holding the intermediate artefacts derived from a PDF."""

    html_template: str
    fields: list[DetectedField]
    metadata: Dict[str, Any]
    pdf_path: str
    field_mappings: Dict[str, list[str]]
    field_layouts: Dict[str, FieldLayout]
    field_positions: Dict[str, Tuple[int, float, float]]


class FormPipeline:
    """Coordinate PDF → HTML → Field Extraction → Fill → PDF generation."""

    def __init__(self) -> None:
        self._extractor = HTMLExtractor()
        self._detector = FieldDetector()
        self._html_filler = HTMLFiller()
        self._pdf_filler = PDFFiller()

    def extract(self, pdf_path: str) -> FormExtractionResult:
        """Convert a PDF into HTML and recover structured form fields and metadata."""

        html, field_mappings, field_layouts, field_positions = self._extractor.pdf_to_html(pdf_path)
        metadata = self._extractor.extract_pdf_metadata(pdf_path)
        fields = self._detector.extract_fields(html)
        return FormExtractionResult(
            html_template=html,
            fields=fields,
            metadata=metadata,
            pdf_path=pdf_path,
            field_mappings=field_mappings,
            field_layouts=field_layouts,
            field_positions=field_positions,
        )

    def initialise_conversation(self, extracted: FormExtractionResult) -> ConversationState:
        """Build an initial conversation state seeded with extracted form data."""

        return ConversationState(
            form_name=str(extracted.metadata.get("form_name", "")),
            fields=extracted.fields,
            html_template=extracted.html_template,
        )

    def fill(self, extracted: FormExtractionResult, answers: Dict[str, str], output_path: str) -> Tuple[str, str]:
        """Populate the HTML template with answers and persist a rendered PDF."""

        filled_html = self._html_filler.fill_html_form(extracted.html_template, answers)
        expanded = self._expand_answers_for_pdf(extracted, answers)
        pdf_path = self._pdf_filler.fill_pdf(extracted.pdf_path, expanded, output_path)
        return filled_html, pdf_path

    def preview(self, extracted: FormExtractionResult, answers: Dict[str, str]) -> str:
        """Return a filled HTML preview without generating a PDF."""
        filled_html = self._html_filler.fill_html_form(extracted.html_template, answers)
        return self._html_filler.generate_html_preview(filled_html)

    def _expand_answers_for_pdf(self, extracted: FormExtractionResult, answers: Dict[str, str]) -> Dict[str, str]:
        """Transform aggregated answers into per-widget assignments for PDF filling."""

        expanded: Dict[str, str] = {}
        for field_name, value in answers.items():
            normalized_value = "" if value is None else str(value)
            widget_names = extracted.field_mappings.get(field_name)
            layout = extracted.field_layouts.get(field_name, FieldLayout())
            if not widget_names:
                expanded[field_name] = normalized_value
                continue

            if layout.kind == "grid":
                normalized = "".join(ch for ch in normalized_value if not ch.isspace())
                for widget, char in zip(widget_names, normalized):
                    expanded[widget] = char
                for widget in widget_names[len(normalized):]:
                    expanded[widget] = ""
                continue

            if layout.kind == "table":
                rows = self._parse_table_value(normalized_value)
                expected_rows = layout.rows if layout.rows else len(rows)
                expected_cols = layout.columns if layout.columns else (max(len(r) for r in rows) if rows else 0)
                total_cells = (
                    expected_rows * expected_cols
                    if expected_rows and expected_cols
                    else len(widget_names)
                )
                cell_values: list[str] = []
                for row_index in range(expected_rows):
                    row_values = rows[row_index] if row_index < len(rows) else []
                    if expected_cols:
                        clipped = row_values[:expected_cols]
                        if len(clipped) < expected_cols:
                            clipped = clipped + [""] * (expected_cols - len(clipped))
                    else:
                        clipped = row_values
                    cell_values.extend(clipped)
                cell_values = cell_values[:total_cells]
                for index, widget in enumerate(widget_names):
                    expanded[widget] = cell_values[index] if index < len(cell_values) else ""
                continue

            expanded[widget_names[0]] = normalized_value

        return expanded

    @staticmethod
    def _parse_table_value(raw: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for line in str(raw).splitlines():
            if not line.strip():
                continue
            cells = [cell.strip() for cell in re.split(r"\t|,|\s{2,}", line)]
            rows.append(cells)
        return rows
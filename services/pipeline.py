"""High-level orchestration for the HTML-based form filling pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from models.conversation_state import ConversationState
from services.field_detector import FieldDetector, DetectedField
from services.html_extractor import HTMLExtractor
from services.html_filler import HTMLFiller
from services.pdf_filler import PDFFiller


@dataclass(frozen=True)
class FormExtractionResult:
    """Container holding the intermediate artefacts derived from a PDF."""

    html_template: str
    fields: list[DetectedField]
    metadata: Dict[str, Any]
    pdf_path: str


class FormPipeline:
    """Coordinate PDF → HTML → Field Extraction → Fill → PDF generation."""

    def __init__(self) -> None:
        self._extractor = HTMLExtractor()
        self._detector = FieldDetector()
        self._html_filler = HTMLFiller()
        self._pdf_filler = PDFFiller()

    def extract(self, pdf_path: str) -> FormExtractionResult:
        """Convert a PDF into HTML and recover structured form fields and metadata."""

        html = self._extractor.pdf_to_html(pdf_path)
        metadata = self._extractor.extract_pdf_metadata(pdf_path)
        fields = self._detector.extract_fields(html)
        return FormExtractionResult(
            html_template=html,
            fields=fields,
            metadata=metadata,
            pdf_path=pdf_path,
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
        pdf_path = self._pdf_filler.fill_pdf(extracted.pdf_path, answers, output_path)
        return filled_html, pdf_path

    def preview(self, extracted: FormExtractionResult, answers: Dict[str, str]) -> str:
        """Return a filled HTML preview without generating a PDF."""
        filled_html = self._html_filler.fill_html_form(extracted.html_template, answers)
        return self._html_filler.generate_html_preview(filled_html)
"""Direct PDF form field filler using PyMuPDF."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import fitz


class PDFFiller:
    """Write answers into the original PDF's AcroForm fields."""

    _TRUTHY = {"true", "1", "yes", "on", "checked", "y"}
    _FALSY = {"false", "0", "no", "off", "unchecked", "n"}

    def fill_pdf(self, source_pdf_path: str, answers: Dict[str, str], output_path: str) -> str:
        """Populate the PDF form fields and save the updated file."""

        if not answers:
            raise ValueError("No answers were provided to fill the PDF.")

        source_path = Path(source_pdf_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source PDF not found: {source_pdf_path}")

        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        with fitz.open(source_path) as document:
            self._apply_answers(document, answers)
            document.save(str(destination), deflate=True, garbage=4)

        return str(destination)

    def _apply_answers(self, document: fitz.Document, answers: Dict[str, str]) -> None:
        for page in document:
            widgets = page.widgets() or []
            for widget in widgets:
                name = widget.field_name or widget.field_label
                if not name:
                    continue

                value = self._resolve_answer(name, widget.field_label, answers)
                if value is None:
                    continue

                self._set_widget_value(widget, value)

    def _resolve_answer(
        self,
        name: str,
        label: Optional[str],
        answers: Dict[str, str],
    ) -> Optional[str]:
        if name in answers and answers[name] != "":
            return str(answers[name])
        if label and label in answers and answers[label] != "":
            return str(answers[label])
        return None

    def _set_widget_value(self, widget: fitz.Widget, value: str) -> None:
        widget_type = widget.field_type
        if widget_type in {fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON}:
            normalized = value.strip().lower()
            on_candidate = (getattr(widget, "button_on_state", "") or "").strip().lower()
            off_candidate = (getattr(widget, "button_off_state", "") or "").strip().lower()
            label_candidate = (widget.field_label or "").strip().lower()

            is_truthy = (
                normalized in self._TRUTHY
                or normalized == on_candidate
                or (label_candidate and normalized == label_candidate)
            )
            is_falsey = normalized in self._FALSY or (off_candidate and normalized == off_candidate)

            on_state = getattr(widget, "button_on_state", None) or "Yes"
            off_state = getattr(widget, "button_off_state", None) or "Off"
            if is_truthy:
                widget.field_value = on_state
            elif is_falsey:
                widget.field_value = off_state
            else:
                widget.field_value = on_state if normalized else off_state
            widget.update()
            return

        widget.field_value = value
        widget.update()

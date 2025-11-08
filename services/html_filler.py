"""HTML form filler and PDF generation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from bs4 import BeautifulSoup
from weasyprint import HTML


class HTMLFiller:
    """Inject collected answers into HTML templates and export results."""

    def fill_html_form(self, html_template: str, collected_answers: Dict[str, str]) -> str:
        """Populate form controls with the provided answers and return HTML."""

        soup = BeautifulSoup(html_template or "", "lxml")
        for element in soup.find_all(["input", "select", "textarea"]):
            name = element.get("name") or element.get("id")
            if not name:
                continue
            if name not in collected_answers:
                continue
            answer = collected_answers[name]

            if element.name == "select":
                self._fill_select(element, answer)
                continue
            if element.name == "textarea":
                element.string = answer
                continue

            field_type = element.get("type", "text").lower()
            if field_type in {"checkbox", "radio"}:
                self._fill_choice_control(element, answer)
            else:
                element["value"] = answer

        return str(soup)

    def generate_pdf(self, filled_html: str, output_path: str) -> str:
        """Render the supplied HTML into a PDF and persist it to disk."""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=filled_html).write_pdf(target=str(path))
        return str(path)

    def generate_html_preview(self, filled_html: str) -> str:
        """Return HTML markup suitable for previewing in a browser or Streamlit."""

        return filled_html

    def _fill_select(self, element, answer: str) -> None:
        for option in element.find_all("option"):
            option_value = option.get("value") or option.get_text(strip=True)
            if option_value == answer:
                option["selected"] = True
            else:
                option.attrs.pop("selected", None)

    def _fill_choice_control(self, element, answer: str) -> None:
        truthy_answers = {"true", "1", "yes", "on"}
        normalized = str(answer).strip().lower()
        expected = element.get("value", "").strip().lower()
        should_check = normalized in truthy_answers or normalized == expected
        if should_check:
            element["checked"] = True
        else:
            element.attrs.pop("checked", None)

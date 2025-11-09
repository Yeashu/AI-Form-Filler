"""HTML form field extraction utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup, Tag


@dataclass(frozen=True)
class DetectedField:
    """Normalized representation of an HTML form control."""

    name: str
    label: str
    field_type: str
    value: str = ""
    options: List[str] = field(default_factory=list)
    required: bool = False
    placeholder: str = ""


class FieldDetector:
    """Parse HTML documents to recover structured form field metadata."""

    def extract_fields(self, html_content: str) -> List[DetectedField]:
        """Return all form controls discovered in the provided HTML snippet."""

        soup = BeautifulSoup(html_content or "", "lxml")
        fields: List[DetectedField] = []
        for element in soup.find_all(["input", "select", "textarea"]):
            detected = self._build_field(element, soup)
            if detected:
                fields.append(detected)
        return fields

    def get_field_by_name(self, fields: List[DetectedField], name: str) -> Optional[DetectedField]:
        """Find a single field that matches the requested name."""

        for field in fields:
            if field.name == name:
                return field
        return None

    def get_fields_by_label(self, fields: List[DetectedField], label_keyword: str) -> List[DetectedField]:
        """Return every field whose label contains the supplied keyword."""

        if not label_keyword:
            return []
        keyword = label_keyword.lower()
        return [field for field in fields if keyword in field.label.lower()]

    def _build_field(self, element: Tag, soup: BeautifulSoup) -> Optional[DetectedField]:
        """Coerce a BeautifulSoup tag into a DetectedField instance."""

        name = element.get("name") or element.get("id")
        if not name:
            return None

        field_type = self._resolve_field_type(element)
        label = self._resolve_label(element, soup)
        placeholder = element.get("placeholder", "")
        required = bool(element.has_attr("required") or element.get("aria-required") == "true")

        if element.name == "select":
            options = [opt.get_text(strip=True) for opt in element.find_all("option")]
            value = element.get("value", "")
            return DetectedField(
                name=name,
                label=label,
                field_type="select",
                value=value,
                options=[option for option in options if option],
                required=required,
                placeholder=placeholder,
            )

        if element.name == "textarea":
            raw_text = element.get_text() or ""
            value = raw_text.replace("\r\n", "\n").strip("\n")
            return DetectedField(
                name=name,
                label=label,
                field_type="textarea",
                value=value,
                required=required,
                placeholder=placeholder,
            )

        value = element.get("value", "")
        options: List[str] = []
        if field_type in {"checkbox", "radio"}:
            options = [value] if value else []
        return DetectedField(
            name=name,
            label=label,
            field_type=field_type,
            value=value,
            options=options,
            required=required,
            placeholder=placeholder,
        )

    def _resolve_field_type(self, element: Tag) -> str:
        if element.name == "select":
            return "select"
        if element.name == "textarea":
            return "textarea"
        input_type = element.get("type", "text").lower()
        known_types = {"text", "email", "tel", "number", "date", "checkbox", "radio", "password"}
        return input_type if input_type in known_types else "text"

    def _resolve_label(self, element: Tag, soup: BeautifulSoup) -> str:
        element_id = element.get("id")
        if element_id:
            label_tag = soup.find("label", attrs={"for": element_id})
            if label_tag:
                text = label_tag.get_text(strip=True)
                if text:
                    return text

        parent_label = element.find_parent("label")
        if parent_label:
            text = parent_label.get_text(strip=True)
            if text:
                return text

        fallback = element.get("name") or element.get("id") or "field"
        return fallback.replace("_", " ").title()

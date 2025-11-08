"""High level orchestration helpers for the PDF filling pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .filler import fill_pdf
from .models import DetectedField
from .parser import extract_fields


@dataclass
class ParsedForm:
    pdf_bytes: bytes
    fields: list[DetectedField]


def parse_pdf(pdf_bytes: bytes) -> ParsedForm:
    fields = extract_fields(pdf_bytes)
    return ParsedForm(pdf_bytes=pdf_bytes, fields=fields)


def fill_parsed_form(parsed_form: ParsedForm, answers: Mapping[str, str], destination_path: str) -> str:
    return fill_pdf(parsed_form.pdf_bytes, destination_path, parsed_form.fields, answers)


__all__ = ["ParsedForm", "parse_pdf", "fill_parsed_form"]

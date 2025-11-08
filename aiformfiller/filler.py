"""Utilities to write user-provided data back into the PDF."""

from __future__ import annotations

from typing import BinaryIO, Mapping, Sequence, Union

import fitz

from .models import DetectedField

PdfSource = Union[str, bytes, BinaryIO]


def fill_pdf(
    source: PdfSource,
    destination_path: str,
    fields: Sequence[DetectedField],
    answers: Mapping[str, str],
    horizontal_padding: float = 2.0,
    vertical_offset: float = 3.0,
) -> str:
    """Fill the provided PDF with the user's answers.

    Parameters
    ----------
    source:
        Either a path to the PDF or an in-memory byte-like object.
    destination_path:
        The path where the filled PDF should be saved.
    fields:
        The parsed form fields with positional data.
    answers:
        Mapping between field labels and user answers.
    horizontal_padding:
        Number of points to offset the text from the field's left boundary.
    vertical_offset:
        Vertical point offset to draw text slightly above the underline.

    Returns
    -------
    str
        Path to the saved, filled PDF.
    """

    doc = fitz.open(stream=source, filetype="pdf") if not isinstance(source, str) else fitz.open(source)
    try:
        for field in fields:
            value = answers.get(field.label) or answers.get(field.raw_label)
            if not value:
                continue
            page = doc[field.page]
            x0, y0, x1, y1 = field.bbox
            # Place the baseline slightly above the underline span so text sits over the line.
            insertion_y = (y1 if y1 >= y0 else y0) - vertical_offset
            insertion_point = (x0 + horizontal_padding, insertion_y)
            page.insert_text(insertion_point, value, fontsize=11)
        doc.save(destination_path)
    finally:
        doc.close()
    return destination_path


__all__ = ["fill_pdf"]

"""Data models for AIFormFiller."""

from dataclasses import dataclass
from typing import Tuple

BBox = Tuple[float, float, float, float]


@dataclass(frozen=True)
class DetectedField:
    """Representation of a detected bracketed text field in a PDF page."""

    page: int
    label: str
    bbox: BBox
    raw_label: str

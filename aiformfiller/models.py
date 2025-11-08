"""Data models for AIFormFiller."""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class FieldType(str, Enum):
    """Enumeration of supported PDF form field types."""

    TEXT = "text"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TEXTBOX = "textbox"
    BUTTON = "button"
    UNKNOWN = "unknown"


BBox = Tuple[float, float, float, float]


@dataclass(frozen=True)
class DetectedField:
    """Representation of a detected field in a PDF page."""

    page: int
    label: str
    bbox: BBox
    raw_label: str
    field_type: FieldType = FieldType.TEXT

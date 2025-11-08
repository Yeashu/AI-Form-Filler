"""Utility helpers for AIFormFiller."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Iterable, List

from .models import DetectedField


def assign_unique_labels(fields: Iterable[DetectedField]) -> List[DetectedField]:
    fields_list = list(fields)
    total_counts = Counter(field.raw_label for field in fields_list)
    running_counts = Counter()
    unique_fields: List[DetectedField] = []

    for field in fields_list:
        running_counts[field.raw_label] += 1
        occurrences = total_counts[field.raw_label]
        if occurrences > 1:
            label = f"{field.raw_label} ({running_counts[field.raw_label]})"
        else:
            label = field.raw_label
        unique_fields.append(replace(field, label=label))
    return unique_fields


__all__ = ["assign_unique_labels"]

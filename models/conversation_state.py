"""Conversation state tracking for interactive form filling."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ConversationState:
    """Immutable snapshot describing the progress of a form-filling session."""

    fields: List[Any]
    form_name: str = ""
    collected_answers: Dict[str, str] = field(default_factory=dict)
    current_field_index: int = 0
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    is_complete: bool = False
    html_template: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def get_current_field(self) -> Optional[Any]:
        """Return the field currently awaiting a response."""

        if 0 <= self.current_field_index < len(self.fields):
            return self.fields[self.current_field_index]
        return None

    def get_next_field(self) -> Optional[Any]:
        """Return the next unanswered field without mutating state."""

        index = self._next_unanswered_index(self.collected_answers, self.current_field_index + 1)
        if index is None:
            return None
        return self.fields[index]

    def is_field_answered(self, field_name: str) -> bool:
        """Check if a specific field already has an answer registered."""

        return field_name in self.collected_answers and self.collected_answers[field_name] != ""

    def add_answer(self, field_name: str, answer: str) -> "ConversationState":
        """Store an answer and advance the iterator to the next unanswered field."""

        updated_answers = dict(self.collected_answers)
        updated_answers[field_name] = answer

        next_index = self._next_unanswered_index(updated_answers, self.current_field_index)
        is_complete = next_index is None
        resolved_index = next_index if next_index is not None else len(self.fields)

        return replace(
            self,
            collected_answers=updated_answers,
            current_field_index=resolved_index,
            is_complete=is_complete,
        )

    def mark_complete(self) -> "ConversationState":
        """Return a copy of the state flagged as complete."""

        return replace(self, is_complete=True, current_field_index=len(self.fields))

    def get_progress(self) -> Tuple[int, int]:
        """Return a tuple of (answered_fields, total_fields)."""

        answered = sum(1 for value in self.collected_answers.values() if value != "")
        return answered, len(self.fields)

    def _next_unanswered_index(
        self, answers: Dict[str, str], start_index: int
    ) -> Optional[int]:
        for index, field in enumerate(self.fields[start_index:], start=start_index):
            key = self._field_key(field)
            if key and not answers.get(key):
                return index
        return None

    def _field_key(self, field: Any) -> str:
        name = getattr(field, "name", "")
        if name:
            return str(name)
        label = getattr(field, "label", "")
        if label:
            return str(label)
        return ""

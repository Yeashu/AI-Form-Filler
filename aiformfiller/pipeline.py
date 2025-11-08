"""High level orchestration helpers for the PDF filling pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Optional

from .filler import fill_pdf
from .llm import (
    ConversationState,
    configure_gemini,
    create_conversation,
    get_next_question,
    process_user_response,
)
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


def collect_answers_with_llm(
    parsed_form: ParsedForm,
    *,
    api_key: Optional[str] = None,
    existing_state: Optional[ConversationState] = None,
    user_input: Optional[str] = None,
    validate_with_llm: bool = False,
) -> ConversationState:
    """Advance or initialise a conversational session for collecting answers.

    This helper keeps the orchestration logic inside the pipeline module while the
    Streamlit UI handles rendering. The function is intentionally pure: callers pass
    the current state and optional user input, and receive the updated state.

    Args:
        parsed_form: The parsed form that exposes detected fields.
        api_key: Optional Google API key. Only used on initialisation.
        existing_state: Previously returned conversation state, if any.
        user_input: Latest user response to record.
        validate_with_llm: When True, validate/format responses via Gemini.

    Returns:
        Updated conversation state reflecting any new answers.
    """

    if validate_with_llm:
        configure_gemini(api_key)
    elif api_key:
        configure_gemini(api_key)

    state = existing_state or create_conversation(parsed_form.fields)

    # Bootstrap the first question so the UI can render a complete history.
    if not state.conversation_history or (
        len(state.conversation_history) == 1 and state.conversation_history[0]["role"] == "assistant"
    ):
        first_question = get_next_question(state)
        if state.conversation_history[-1]["content"] != first_question:
            history = state.conversation_history + [{"role": "assistant", "content": first_question}]
            state = replace(state, conversation_history=history)

    if not user_input:
        return state

    return process_user_response(state, user_input, validate_with_llm=validate_with_llm)


__all__ = ["ParsedForm", "parse_pdf", "fill_parsed_form", "collect_answers_with_llm"]

"""LLM-based conversational field collection for PDF forms.

This module provides conversational AI capabilities using Google Gemini
to collect form field values through natural dialogue instead of manual form filling.
"""

from __future__ import annotations

import os
import json
import logging
import re
from dataclasses import dataclass, replace
from typing import Optional


import google.generativeai as genai

from .models import DetectedField
from models.conversation_state import ConversationState

logger = logging.getLogger(__name__)

if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO)

@dataclass(frozen=True)
class FieldExpectation:
    """Describes validation expectations for a form field."""

    field_type: str
    format_hint: str
    examples: tuple[str, ...]
    guidance: str


@dataclass(frozen=True)
class ValidationResult:
    """Result returned from Gemini validation."""

    is_valid: bool
    formatted_value: str
    assistant_message: str
    error_message: Optional[str] = None


def configure_gemini(api_key: Optional[str] = None) -> None:
    """Configure Google Gemini API with the provided or environment API key.

    Args:
        api_key: Optional API key. If not provided, uses GOOGLE_API_KEY from environment.

    Raises:
        ValueError: If no API key is found.
    """
    key = api_key or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise ValueError(
            "Google API key not found. Set GOOGLE_API_KEY environment variable "
            "or pass api_key parameter."
        )
    genai.configure(api_key=key)


def _normalise_model_name(raw_name: str) -> str:
    """Normalise user-provided model identifiers to the API format."""

    if not raw_name:
        return "models/gemini-2.5-flash"

    slug = raw_name.strip().lower().replace(" ", "-")
    if not slug.startswith("models/"):
        slug = f"models/{slug}"
    return slug


def create_conversation(fields: list[DetectedField]) -> ConversationState:
    """Initialize a new conversation for the given form fields.

    Args:
        fields: List of detected fields from the PDF form.

    Returns:
        New ConversationState ready to start collecting answers.
    """
    welcome_message = {
        "role": "assistant",
        "content": (
            f"Hello! I'll help you fill out this form. "
            f"I need to collect {len(fields)} pieces of information. "
            f"Let's get started!"
        )
    }

    return ConversationState(
        fields=fields,
        collected_answers={},
        current_field_index=0,
        conversation_history=[welcome_message],
        is_complete=False,
    )


def _infer_field_expectations(field: DetectedField) -> FieldExpectation:
    """Infer validation expectations based on the field label."""

    label = field.label.lower()

    if "email" in label or "e-mail" in label:
        return FieldExpectation(
            field_type="email address",
            format_hint="Must contain a username, '@', and domain (e.g., name@example.com).",
            examples=("alex.taylor@example.com", "support@company.co"),
            guidance="Reject values without '@' or domain, or with spaces.",
        )

    if "phone" in label or "mobile" in label or "contact" in label:
        return FieldExpectation(
            field_type="phone number",
            format_hint="10-15 digits, allow optional country code prefix (+1, +91).",
            examples=("+1 415 555 0198", "9876543210"),
            guidance="Reject alphabetic characters; normalize by removing spaces and hyphens.",
        )

    if "date" in label or "dob" in label or "birth" in label:
        return FieldExpectation(
            field_type="date",
            format_hint="Prefer MM/DD/YYYY unless otherwise stated by the label.",
            examples=("02/14/2025", "12/31/1999"),
            guidance="Reject impossible dates or wrong format; pad month/day with leading zero.",
        )

    if "zip" in label or "postal" in label:
        return FieldExpectation(
            field_type="postal code",
            format_hint="US ZIP (5 or 9 digits) or international alphanumeric postal code.",
            examples=("94105", "94105-1234", "SW1A 1AA"),
            guidance="Remove spaces where optional; ensure only valid postal characters.",
        )

    if "age" in label or "years" in label:
        if "word" in label or "words" in label:
            return FieldExpectation(
                field_type="age in words",
                format_hint="Spell out the age using words (e.g., 'Fourteen').",
                examples=("Fourteen", "Thirty Two", "Sixty"),
                guidance=(
                    "Convert digits to words if necessary."
                    " Accept only realistic ages between 0 and 120."
                    " Reject placeholder text or random characters."
                ),
            )
        return FieldExpectation(
            field_type="integer",
            format_hint="Positive whole number between 0 and 120.",
            examples=("29", "64"),
            guidance=(
                "Reject values outside 0-120, negative numbers, zero (unless allowed), or fractions."
                " Flag obviously unrealistic ages."
            ),
        )

    if "amount" in label or "salary" in label or "income" in label:
        return FieldExpectation(
            field_type="currency amount",
            format_hint="Numeric value with optional currency symbol and decimal places.",
            examples=("$75,000", "45000", "€1,250.50"),
            guidance="Normalize to plain digits with decimal point; reject alphabetic characters.",
        )

    if "username" in label or "user name" in label or "user id" in label:
        return FieldExpectation(
            field_type="username",
            format_hint="3-32 characters using letters, numbers, underscores, or hyphens only.",
            examples=("kartik_21", "alex-smith", "mariagarcia"),
            guidance=(
                "Reject spaces, special symbols, or offensive words."
                " Normalise by trimming whitespace and favour lowercase unless case is intentional."
            ),
        )

    if ("building" in label or "tower" in label or "block" in label) and "name" in label:
        return FieldExpectation(
            field_type="building name",
            format_hint="Official building or block name using words and optional block identifiers (e.g., 'Block A').",
            examples=("Scaler Heights", "Block A", "Emerald Tower"),
            guidance=(
                "Reject placeholder text, random characters, or numeric-only responses."
                " Title case each word and preserve valid block identifiers."
            ),
        )

    if "colony" in label and "name" in label:
        return FieldExpectation(
            field_type="colony name",
            format_hint="Residential colony or society name written with alphabetic words.",
            examples=("Shakti Nagar", "DLF Phase 2", "Palm Meadows"),
            guidance=(
                "Reject numeric-only answers or gibberish such as 'asdfg'."
                " Capitalise major words and keep abbreviations as provided."
            ),
        )

    if ("area" in label and "name" in label) or "locality" in label or "neighbourhood" in label or "neighborhood" in label:
        return FieldExpectation(
            field_type="area name",
            format_hint="Neighbourhood or locality name expressed with meaningful words.",
            examples=("White House", "Indiranagar", "Downtown District"),
            guidance=(
                "Reject numeric-only responses or repeated random letters."
                " Capitalise appropriately and trim extra spaces."
            ),
        )

    if "name" in label:
        return FieldExpectation(
            field_type="person name",
            format_hint="Alphabetic words with vowels, spaces, apostrophes, and hyphens only.",
            examples=("Priya Singh", "Anne-Marie O'Neill", "Rahul Verma"),
            guidance=(
                "Reject gibberish or sequences without vowels (e.g., 'sdfrt')."
                " Title case the value and remove digits or special symbols."
            ),
        )

    if "gender" in label or "sex" in label:
        return FieldExpectation(
            field_type="gender value",
            format_hint="Common responses include Male, Female, Non-binary, Prefer not to say.",
            examples=("Female", "Male", "Non-binary"),
            guidance="Accept common abbreviations (M/F) and expand to full words.",
        )

    return FieldExpectation(
        field_type="text response",
        format_hint="Short sentence or phrase that answers the field label.",
        examples=("Yes", "Primary residence", "Engineering Manager"),
        guidance=(
            "Trim whitespace, capitalise where appropriate, and reject obvious gibberish or placeholder text."
        ),
    )


def _generate_field_question(field: DetectedField, index: int, total: int) -> str:
    """Generate a natural question for a specific field.

    Args:
        field: The field to ask about.
        index: Current field number (0-indexed).
        total: Total number of fields.

    Returns:
        A natural language question for the field.
    """
    progress = f"({index + 1}/{total})"
    
    # Import FieldType here to avoid circular imports
    try:
        from .models import FieldType
        
        # Special handling for checkboxes - ask yes/no question
        if hasattr(field, 'field_type') and field.field_type == FieldType.CHECKBOX:
            field_label = field.label.strip() or "this option"
            return f"{progress} Do you want to check '{field_label}'? (Yes/No)"
        
        # Special handling for radio buttons - ask for selection from group
        if hasattr(field, 'field_type') and field.field_type == FieldType.RADIO:
            # Use raw_label or group_key to get the base question
            base_label = (field.raw_label or field.label).strip()
            # Clean up the label (remove trailing colons, underscores)
            base_label = base_label.replace("_", " ").strip(": ")
            return f"{progress} What is your {base_label}? (e.g., {field.export_value or field.label})"
    except ImportError:
        pass
    
    # Default handling for text fields
    field_label = field.label.strip() or "this field"
    return f"{progress} What value should I enter for '{field_label}'?"


def get_next_question(state: ConversationState) -> str:
    """Generate the next question based on current conversation state.

    Args:
        state: Current conversation state.

    Returns:
        The next question to ask the user, or completion message if done.
    """
    if state.current_field_index >= len(state.fields):
        return (
            "Perfect! I've collected all the information. "
            "Your form is ready to be filled. Click 'Fill PDF' to complete the process."
        )

    current_field = state.fields[state.current_field_index]
    return _generate_field_question(
        current_field,
        state.current_field_index,
        len(state.fields)
    )


def process_user_response(
    state: ConversationState,
    user_input: str,
    validate_with_llm: bool = False
) -> ConversationState:
    """Process user's response and update conversation state.

    Args:
        state: Current conversation state.
        user_input: User's response text.
        validate_with_llm: If True, use Gemini to validate/format the response (future feature).

    Returns:
        Updated conversation state with the answer recorded.
    """
    if state.is_complete:
        return state

    if state.current_field_index >= len(state.fields):
        return replace(state, is_complete=True)

    # Get current field and record the answer
    current_field = state.fields[state.current_field_index]
    cleaned_input = user_input.strip()

    validation_result: Optional[ValidationResult] = None
    if validate_with_llm:
        expectations = _infer_field_expectations(current_field)
        validation_result = validate_and_format_with_gemini(
            current_field.label,
            cleaned_input,
            expectations=expectations,
        )

    if validation_result and not validation_result.is_valid:
        repeat_question = _generate_field_question(
            current_field,
            state.current_field_index,
            len(state.fields),
        )
        feedback_message = validation_result.assistant_message
        error_detail = validation_result.error_message

        history = state.conversation_history + [
            {"role": "user", "content": cleaned_input},
        ]
        if feedback_message:
            history.append({"role": "assistant", "content": feedback_message})
        if error_detail:
            history.append({"role": "assistant", "content": error_detail})
        # Re-ask the same question so the user can try again.
        history.append({"role": "assistant", "content": repeat_question})

        return replace(state, conversation_history=history)

    final_value = cleaned_input
    acknowledgement = None
    if validation_result:
        final_value = validation_result.formatted_value.strip() or cleaned_input
        acknowledgement = validation_result.assistant_message

    # Update answers dictionary
    new_answers = state.collected_answers.copy()
    new_answers[current_field.label] = final_value

    # Add user message to history
    new_history = state.conversation_history + [
        {"role": "user", "content": cleaned_input}
    ]

    if acknowledgement:
        new_history.append({"role": "assistant", "content": acknowledgement})

    # Move to next field
    next_index = state.current_field_index + 1
    is_done = next_index >= len(state.fields)

    # Generate next question or completion message
    next_question = get_next_question(
        replace(state, current_field_index=next_index)
    )

    # Add assistant's next question to history
    new_history.append({"role": "assistant", "content": next_question})

    return ConversationState(
        fields=state.fields,
        collected_answers=new_answers,
        current_field_index=next_index,
        conversation_history=new_history,
        is_complete=is_done,
    )


def _extract_json_dict(candidate_text: str) -> dict[str, object]:
    """Extract a JSON object from Gemini output."""

    try:
        return json.loads(candidate_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate_text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def validate_and_format_with_gemini(
    field_label: str,
    user_input: str,
    *,
    expectations: Optional[FieldExpectation] = None,
    model_name: str = "gemini 2.0 Flash-Lite"
) -> ValidationResult:
    """Use Gemini to validate and format user input."""

    expectations = expectations or FieldExpectation(
        field_type="text response",
        format_hint="Return a concise answer matching the field label.",
        examples=(),
        guidance="Trim whitespace and keep the user's meaning intact.",
    )

    logger.info("[Gemini] Validating field '%s'", field_label)

    configure_gemini()

    try:
        resolved_model = os.getenv("GEMINI_MODEL", model_name)
        resolved_model = _normalise_model_name(resolved_model)
        temperature = float(os.getenv("TEMPERATURE", "0.0"))
        top_p = float(os.getenv("TOP_P", "0.8"))
        top_k = int(os.getenv("TOP_K", "40"))
        max_tokens = int(os.getenv("MAX_OUTPUT_TOKENS", "512"))
        model = genai.GenerativeModel(
            resolved_model,
            generation_config={
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "max_output_tokens": max_tokens,
            },
        )

        examples_text = "\n".join(f"  - {example}" for example in expectations.examples) or "  - (none provided)"

        prompt = f"""You are helping to tidy responses for a PDF form. Review the user's reply and decide whether it is suitable for the field.

Return a JSON object with these keys:
- is_valid (boolean)
- formatted_value (string) — the cleaned value ready to place into the form
- assistant_message (string) — friendly acknowledgement or guidance for the user
- error_message (string) — short description when the answer needs changes; otherwise empty

Field label: {field_label}
Expected value type: {expectations.field_type}
Formatting guidance: {expectations.format_hint}
Additional notes: {expectations.guidance}
Example values:\n{examples_text}

User response: {user_input}

Guidelines:
- Keep the user's intent and rephrase gently when needed.
- If a change is required, explain briefly and politely.
- Treat obviously nonsensical or placeholder text (e.g., 'asdf', repeated random letters) as invalid unless the additional notes explicitly allow codes.
- Apply the additional notes to enforce realism (such as valid age ranges) even when the format looks correct.
- Avoid inventing information.
- Respond strictly in JSON (no backticks).
"""

        response = model.generate_content(prompt)

        candidate = next((c for c in response.candidates if c.content.parts), None)
        if not candidate:
            logger.warning(
                "[Gemini] No candidate parts returned for '%s' (finish_reason=%s)",
                field_label,
                getattr(response.candidates[0], "finish_reason", "unknown") if response.candidates else "none",
            )
            return ValidationResult(
                is_valid=True,
                formatted_value=user_input,
                assistant_message="Got it. I'll record that as provided.",
            )

        finish_reason = getattr(candidate, "finish_reason", None)
        # STOP is encoded as integer 1 in current API; treat None/0/1 as acceptable.
        if finish_reason not in (None, 0, 1):
            logger.warning(
                "[Gemini] Candidate not finished cleanly for '%s' (reason=%s)",
                field_label,
                finish_reason,
            )
            return ValidationResult(
                is_valid=True,
                formatted_value=user_input,
                assistant_message="Thanks. I'll keep your answer as-is.",
            )

        raw_text = "".join(part.text for part in candidate.content.parts if getattr(part, "text", ""))
        if not raw_text:
            logger.warning("[Gemini] Candidate had no text content for '%s'", field_label)
            return ValidationResult(
                is_valid=True,
                formatted_value=user_input,
                assistant_message="Understood. I'll keep what you provided.",
            )

        logger.debug("[Gemini] Raw response for '%s': %s", field_label, raw_text)
        payload = _extract_json_dict(raw_text.strip())

        is_valid = bool(payload.get("is_valid", True))
        formatted_value = str(payload.get("formatted_value", user_input)).strip() or user_input
        assistant_message = str(payload.get("assistant_message", "")).strip()
        error_message_raw = payload.get("error_message")
        error_message = str(error_message_raw).strip() if error_message_raw else None

        if is_valid and not assistant_message:
            assistant_message = f"Great, I'll record '{formatted_value}'."
        if not is_valid and not error_message:
            error_message = "That response does not match the expected format."
        if not is_valid and not assistant_message:
            assistant_message = "Thanks. Could you adjust your answer as described?"

        return ValidationResult(
            is_valid=is_valid,
            formatted_value=formatted_value,
            assistant_message=assistant_message,
            error_message=error_message,
        )

    except Exception as exc:
        logger.exception("[Gemini] Validation failed for '%s': %s", field_label, exc)
        # If validation fails, accept the input as-is to avoid blocking the user.
        return ValidationResult(
            is_valid=True,
            formatted_value=user_input,
            assistant_message="Got it. I'll record that as provided.",
            error_message=None,
        )


def get_conversation_summary(state: ConversationState) -> str:
    """Generate a summary of all collected answers.

    Args:
        state: Current conversation state.

    Returns:
        Formatted string showing all collected field values.
    """
    if not state.collected_answers:
        return "No answers collected yet."

    lines = ["**Collected Information:**\n"]
    for field in state.fields:
        answer = state.collected_answers.get(field.label, "Not provided")
        lines.append(f"- **{field.label}**: {answer}")

    return "\n".join(lines)


def reset_conversation(state: ConversationState, from_field_index: int = 0) -> ConversationState:
    """Reset conversation to start from a specific field (for editing answers).

    Args:
        state: Current conversation state.
        from_field_index: Index of field to restart from.

    Returns:
        Updated conversation state reset to the specified field.
    """
    # Keep answers up to the reset point
    new_answers = {
        field.label: state.collected_answers[field.label]
        for field in state.fields[:from_field_index]
        if field.label in state.collected_answers
    }

    # Rebuild conversation history up to reset point
    new_history = [state.conversation_history[0]]  # Keep welcome message

    for i in range(from_field_index):
        if i < len(state.fields):
            field = state.fields[i]
            if field.label in state.collected_answers:
                question = _generate_field_question(field, i, len(state.fields))
                new_history.append({"role": "assistant", "content": question})
                new_history.append({
                    "role": "user",
                    "content": state.collected_answers[field.label]
                })

    # Add next question
    if from_field_index < len(state.fields):
        next_question = _generate_field_question(
            state.fields[from_field_index],
            from_field_index,
            len(state.fields)
        )
        new_history.append({"role": "assistant", "content": next_question})

    return ConversationState(
        fields=state.fields,
        collected_answers=new_answers,
        current_field_index=from_field_index,
        conversation_history=new_history,
        is_complete=False,
    )


__all__ = [
    "ConversationState",
    "FieldExpectation",
    "configure_gemini",
    "create_conversation",
    "get_next_question",
    "process_user_response",
    "validate_and_format_with_gemini",
    "get_conversation_summary",
    "reset_conversation",
    "ValidationResult",
]

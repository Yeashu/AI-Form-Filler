# Guidelines: `aiformfiller/llm.py`

## Purpose
Provide conversational data collection for PDF forms using Google Gemini.

---

## Best Practices

### 1. Keep State Immutable
- Use `ConversationState` (frozen dataclass) to track fields, answers, and history.
- When updates are needed, create a new instance via `dataclasses.replace` or helper functions.

### 2. Pure Conversation Functions
- `create_conversation`, `get_next_question`, `process_user_response`, and `reset_conversation` should not perform I/O.
- They must depend only on their inputs for predictable behaviour and easy testing.

### 3. Friendly, Specific Prompts
- `_generate_field_question` should produce concise, user-friendly questions.
- Add new label heuristics carefully; avoid brittle string comparisons.
- Always provide a fall-back question that includes the field label.

### 4. Lazy Gemini Usage
- Call `configure_gemini` only when an API key is supplied.
- Validation helpers (`validate_and_format_with_gemini`) should catch exceptions and degrade gracefully to raw input.
- Keep default flow dependency-free (user input is accepted directly without validation) to control costs.

### 5. History Structure
- `conversation_history` stores dicts with `role` (`"assistant"` or `"user"`) and `content` keys.
- Append assistant messages immediately after generating them to keep the UI display consistent.
- Avoid storing large payloads—keep messages text-only.

### 6. Summary and Reset Support
- `get_conversation_summary` should list fields in their original order.
- `reset_conversation` must keep prior answers intact up to the reset point and rebuild history with the welcome message.

### 7. Error Handling
- Propagate configuration errors quickly (missing API key → `ValueError`).
- In conversational functions, prefer returning the existing state when input is empty or the conversation is already complete.

---

## Common Pitfalls

❌ Performing API calls inside state constructors (breaks purity).

❌ Mutating `conversation_history` lists in-place when the state is frozen.

❌ Generating vague prompts that do not reference the field label or progress.

❌ Letting Gemini validation failures raise through to the UI; always fall back to raw input.

---

## Testing Checklist

- [ ] Initialise conversation with sample `DetectedField` list and ensure welcome + first question appear.
- [ ] Simulate sequential `process_user_response` calls; confirm the state marks completion and collects answers.
- [ ] Reset from mid-conversation and verify history regenerates correctly.
- [ ] Exercise `validate_and_format_with_gemini` with mock responses and with the real API (guarded by env var).
- [ ] Confirm helper functions handle empty field lists without error.

---

## Future Enhancements

- Structured output parsing to reduce reliance on string heuristics.
- Locale-aware formatting (dates, phone numbers).
- Optional batching of questions for faster completion when the user prefers forms.
- Confidence scoring to flag uncertain answers for manual review.

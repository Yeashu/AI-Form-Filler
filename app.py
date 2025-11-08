"""Streamlit UI for the AI Form Filler MVP."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

import streamlit as st
from dotenv import load_dotenv

from aiformfiller.models import DetectedField, FieldType
from aiformfiller.pipeline import (
    ParsedForm,
    collect_answers_with_llm,
    fill_parsed_form,
    parse_pdf,
)
from aiformfiller.storage import SecureStorage, StorageError

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
_RADIO_NONE_OPTION = "— No selection —"
_CHECKED_SYMBOL = "X"
_RADIO_SYMBOL = "●"

load_dotenv()


def _init_session_state() -> None:
    defaults = {
        "parsed_form": None,
        "uploaded_filename": None,
        "answers": {},
        "filled_pdf_bytes": None,
        "filled_pdf_name": None,
        "input_mode": "form",
        "conversation_state": None,
        "pending_answers": {},
        "awaiting_confirmation": False,
        "storage_password": None,
        "stored_data": {},
        "save_to_storage": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_state_on_new_upload(filename: str) -> None:
    if st.session_state.uploaded_filename != filename:
        st.session_state.parsed_form = None
        st.session_state.answers = {}
        st.session_state.filled_pdf_bytes = None
        st.session_state.filled_pdf_name = None
        st.session_state.conversation_state = None
        st.session_state.pending_answers = {}
        st.session_state.awaiting_confirmation = False
        st.session_state.uploaded_filename = filename


def _build_output_path(upload_name: str | None) -> Path:
    stem = Path(upload_name or "filled_form").stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{stem}_filled_{timestamp}.pdf"


def _stage_answers_for_confirmation(answers: Dict[str, str]) -> None:
    if not answers:
        return

    pending = st.session_state.pending_answers or {}
    existing = st.session_state.answers or {}

    if (
        not st.session_state.awaiting_confirmation
        and st.session_state.filled_pdf_bytes
        and answers == existing
    ):
        # Answers already confirmed and unchanged; skip restaging.
        return

    if st.session_state.awaiting_confirmation and answers == pending:
        return

    st.session_state.pending_answers = answers.copy()
    st.session_state.awaiting_confirmation = True
    st.session_state.answers = answers.copy()
    st.session_state.filled_pdf_bytes = None
    st.session_state.filled_pdf_name = None


def _finalise_pdf(parsed_form: ParsedForm, answers: Dict[str, str]) -> None:
    output_path = _build_output_path(st.session_state.uploaded_filename)
    fill_parsed_form(parsed_form, answers, output_path.as_posix())
    with output_path.open("rb") as fp:
        filled_bytes = fp.read()

    st.session_state.filled_pdf_bytes = filled_bytes
    st.session_state.filled_pdf_name = output_path.name
    st.session_state.awaiting_confirmation = False
    st.session_state.pending_answers = {}
    st.session_state.answers = answers.copy()

    st.success("PDF filled successfully. Download below.")


def _group_radio_fields(fields: List[DetectedField]) -> Dict[str, List[DetectedField]]:
    groups: Dict[str, List[DetectedField]] = defaultdict(list)
    for field in fields:
        if field.field_type != FieldType.RADIO:
            continue
        group_key = field.group_key or field.raw_label or field.label
        groups[group_key].append(field)
    return groups


def _format_group_title(field: DetectedField) -> str:
    source = field.group_key or field.raw_label or field.label
    cleaned = (source or "").replace("_", " ").strip().strip(":")
    if not cleaned:
        return "Selection"
    return cleaned[0].upper() + cleaned[1:]


def _radio_option_label(field: DetectedField) -> str:
    if field.export_value and field.export_value.lower() not in {"off", "false"}:
        return field.export_value
    return field.label


def _radio_group_default_selection(group_fields: List[DetectedField]) -> str:
    for field in group_fields:
        if st.session_state.answers.get(field.label):
            return _radio_option_label(field)
    return _RADIO_NONE_OPTION


def _render_radio_group(group_key: str, group_fields: List[DetectedField]) -> str:
    option_labels = [_radio_option_label(field) for field in group_fields]
    options = [_RADIO_NONE_OPTION] + option_labels
    default_label = _radio_group_default_selection(group_fields)
    default_index = options.index(default_label) if default_label in options else 0
    title = _format_group_title(group_fields[0])
    return st.radio(
        title,
        options=options,
        index=default_index,
        key=f"radio_{group_key}",
    )


def _radio_group_answers(group_fields: List[DetectedField], selection: str) -> Dict[str, str]:
    answers: Dict[str, str] = {}
    if selection == _RADIO_NONE_OPTION:
        for field in group_fields:
            answers[field.label] = ""
        return answers
    for field in group_fields:
        option_label = _radio_option_label(field)
        answers[field.label] = _RADIO_SYMBOL if option_label == selection else ""
    return answers


def _render_checkbox_field(field: DetectedField) -> str:
    default_checked = bool(st.session_state.answers.get(field.label))
    checked = st.checkbox(
        field.label,
        value=default_checked,
        key=f"checkbox_{field.label}",
    )
    return _CHECKED_SYMBOL if checked else ""


def _render_text_field(field: DetectedField) -> str:
    default_value = st.session_state.answers.get(field.label, "")
    
    # Try to get auto-fill suggestion from storage
    storage = st.session_state.get("_secure_storage_instance")
    if not default_value and st.session_state.stored_data and storage:
        suggestion = storage.get_suggestion(field.label, st.session_state.stored_data)
        if suggestion:
            default_value = suggestion
    
    if field.field_type == FieldType.TEXTBOX:
        result = st.text_area(field.label, value=default_value)
        return result if result is not None else ""
    result = st.text_input(field.label, value=default_value)
    return result if result is not None else ""


def _render_field_inputs(parsed_form: ParsedForm) -> None:
    st.subheader("Provide Field Values")
    answers: Dict[str, str] = {}
    radio_groups = _group_radio_fields(parsed_form.fields)
    processed_radio_groups: Set[str] = set()
    with st.form("field_input_form"):
        for field in parsed_form.fields:
            if field.field_type == FieldType.RADIO:
                group_key = field.group_key or field.raw_label or field.label
                if group_key in processed_radio_groups:
                    continue
                group_fields = radio_groups.get(group_key, [field])
                selection = _render_radio_group(group_key, group_fields)
                answers.update(_radio_group_answers(group_fields, selection))
                processed_radio_groups.add(group_key)
            elif field.field_type == FieldType.CHECKBOX:
                answers[field.label] = _render_checkbox_field(field)
            elif field.field_type == FieldType.BUTTON:
                st.caption(f"{field.label} (button field)")
                answers[field.label] = ""
            else:
                answers[field.label] = _render_text_field(field)
        
        # Add option to save to storage
        if st.session_state.storage_password:
            st.session_state.save_to_storage = st.checkbox(
                "💾 Save responses to encrypted storage for future use",
                value=st.session_state.save_to_storage,
                help="Your data will be encrypted and stored locally"
            )
        
        submitted = st.form_submit_button("Review Answers")
    if submitted:
        st.session_state.answers = answers
        _stage_answers_for_confirmation(answers)
        st.rerun()
    return None


def _prepare_fields_for_chat(fields: List[DetectedField]) -> List[DetectedField]:
    """Filter and prepare fields for chat mode by deduplicating radio groups and checkboxes.
    
    Returns a simplified list where radio button groups are represented by a single field.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    seen_groups: Set[str] = set()
    chat_fields: List[DetectedField] = []
    
    logger.info(f"[Chat] Preparing {len(fields)} fields for chat mode")
    
    for field in fields:
        if field.field_type == FieldType.RADIO:
            # Use group_key or raw_label to identify radio groups
            group_key = field.group_key or field.raw_label or field.label
            if group_key in seen_groups:
                logger.debug(f"[Chat] Skipping duplicate radio option: {field.label} (group: {group_key})")
                continue  # Skip duplicate radio options in the same group
            seen_groups.add(group_key)
            logger.info(f"[Chat] Including radio group: {group_key} (first option: {field.label})")
            chat_fields.append(field)
        else:
            # Include all other field types (TEXT, CHECKBOX, TEXTBOX, etc.)
            logger.debug(f"[Chat] Including field: {field.label} (type: {field.field_type})")
            chat_fields.append(field)
    
    logger.info(f"[Chat] Prepared {len(chat_fields)} fields for chat (reduced from {len(fields)})")
    return chat_fields


def _expand_chat_answers_to_form_fields(
    chat_answers: Dict[str, str], 
    all_fields: List[DetectedField]
) -> Dict[str, str]:
    """Expand chat answers to match all form fields, handling radio groups and checkboxes.
    
    Args:
        chat_answers: Answers collected from chat (one per radio group)
        all_fields: All detected fields including all radio options
        
    Returns:
        Expanded answers dict with entries for all fields
    """
    import logging
    logger = logging.getLogger(__name__)
    
    expanded: Dict[str, str] = {}
    radio_groups = _group_radio_fields(all_fields)
    
    logger.info(f"[Chat] Expanding {len(chat_answers)} chat answers to {len(all_fields)} form fields")
    logger.debug(f"[Chat] Chat answers: {chat_answers}")
    
    for field in all_fields:
        if field.field_type == FieldType.RADIO:
            # Find the answer for this radio group
            group_key = field.group_key or field.raw_label or field.label
            group_fields = radio_groups.get(group_key, [field])
            
            # Check if we have an answer for any field in this group
            chat_value = None
            for gf in group_fields:
                if gf.label in chat_answers:
                    chat_value = chat_answers[gf.label]
                    break
            
            if not chat_value:
                expanded[field.label] = ""
                logger.debug(f"[Chat] Radio field '{field.label}' - no answer found")
                continue
                
            # Determine which option was selected
            option_label = _radio_option_label(field)
            # Check if the user's answer matches this option
            if chat_value.lower() in option_label.lower() or option_label.lower() in chat_value.lower():
                expanded[field.label] = _RADIO_SYMBOL
                logger.info(f"[Chat] Radio field '{field.label}' = '{_RADIO_SYMBOL}' (matched '{chat_value}')")
            else:
                expanded[field.label] = ""
                logger.debug(f"[Chat] Radio field '{field.label}' = '' ('{chat_value}' != '{option_label}')")
                
        elif field.field_type == FieldType.CHECKBOX:
            # Convert yes/no or similar responses to X or empty
            chat_value = chat_answers.get(field.label, "").strip().lower()
            if chat_value in {"yes", "y", "true", "1", "checked", "x"}:
                expanded[field.label] = _CHECKED_SYMBOL
                logger.info(f"[Chat] Checkbox field '{field.label}' = '{_CHECKED_SYMBOL}' ('{chat_value}')")
            else:
                expanded[field.label] = ""
                logger.debug(f"[Chat] Checkbox field '{field.label}' = '' ('{chat_value}')")
        else:
            # Regular text fields - copy as is
            expanded[field.label] = chat_answers.get(field.label, "")
            if field.label in chat_answers:
                logger.info(f"[Chat] Text field '{field.label}' = '{expanded[field.label]}'")
    
    logger.info(f"[Chat] Expanded to {len(expanded)} field values")
    return expanded


def _render_chat_interface(parsed_form: ParsedForm) -> None:
    """Collect answers through a conversational interface."""

    # Initialise or resume the conversation state stored in the session.
    state = st.session_state.conversation_state
    if state is None:
        # Prepare simplified field list for chat (deduplicate radio groups)
        chat_fields = _prepare_fields_for_chat(parsed_form.fields)
        
        # Pre-fill with stored data if available
        initial_answers = {}
        if st.session_state.stored_data:
            storage = st.session_state.get("_secure_storage_instance")
            if storage:
                for field in chat_fields:
                    suggestion = storage.get_suggestion(field.label, st.session_state.stored_data)
                    if suggestion:
                        initial_answers[field.label] = suggestion
        
        try:
            # Create a temporary ParsedForm with chat-friendly fields
            from dataclasses import replace as dc_replace
            chat_form = dc_replace(parsed_form, fields=chat_fields)
            state = collect_answers_with_llm(chat_form, validate_with_llm=True)
            
            # Apply pre-filled answers if we have them
            if initial_answers:
                from dataclasses import replace
                state = replace(
                    state,
                    collected_answers={**initial_answers, **state.collected_answers}
                )
                st.info(f"🔓 Auto-filled {len(initial_answers)} field(s) from storage")
        except ValueError:
            st.error(
                "Chat Mode requires a valid GOOGLE_API_KEY. "
                "Please add it to your environment or switch back to Form Mode.",
                icon="⚠️",
            )
            st.session_state.input_mode = "form"
            st.session_state.conversation_state = None
            return
        st.session_state.conversation_state = state

    user_message = None
    if not state.is_complete:
        user_message = st.chat_input("Type your response")
        if user_message:
            try:
                # Get chat fields for processing
                chat_fields = _prepare_fields_for_chat(parsed_form.fields)
                from dataclasses import replace as dc_replace
                chat_form = dc_replace(parsed_form, fields=chat_fields)
                state = collect_answers_with_llm(
                    chat_form,
                    existing_state=state,
                    user_input=user_message,
                    validate_with_llm=True,
                )
            except ValueError:
                st.error(
                    "Gemini API key missing. Switching back to Form Mode so you can continue.",
                    icon="⚠️",
                )
                st.session_state.input_mode = "form"
                st.session_state.conversation_state = None
                return
            st.session_state.conversation_state = state

    for message in state.conversation_history:
        role = message.get("role", "assistant")
        content = message.get("content", "")
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(content)

    if state.is_complete:
        st.success("All details collected. Review and continue below.")
        # Expand chat answers to match all form fields (handle radio groups and checkboxes)
        expanded_answers = _expand_chat_answers_to_form_fields(state.collected_answers, parsed_form.fields)
        st.session_state.answers = expanded_answers
        
        # Option to save chat answers
        if st.session_state.storage_password:
            st.session_state.save_to_storage = st.checkbox(
                "💾 Save responses to encrypted storage for future use",
                value=st.session_state.save_to_storage,
                help="Your data will be encrypted and stored locally",
                key="chat_save_checkbox"
            )
        
        _stage_answers_for_confirmation(expanded_answers)
        
        # Display what was collected in chat
        for label, value in state.collected_answers.items():
            st.markdown(f"- **{label}**: {value}")

    return None

    if state.is_complete:
        st.success("All details collected. Review and continue below.")
        st.session_state.answers = state.collected_answers
        _stage_answers_for_confirmation(state.collected_answers)
        for label, value in state.collected_answers.items():
            st.markdown(f"- **{label}**: {value}")

    return None


def _render_confirmation(parsed_form: ParsedForm) -> None:
    if not st.session_state.awaiting_confirmation:
        return

    answers = st.session_state.pending_answers or {}
    if not answers:
        st.session_state.awaiting_confirmation = False
        return

    st.subheader("Review Your Answers")
    for field in parsed_form.fields:
        value = answers.get(field.label, "")
        display_value = value if value else "_Not provided_"
        st.markdown(f"- **{field.label}**: {display_value}")

    col_confirm, col_edit = st.columns(2)
    confirm_clicked = col_confirm.button(
        "Confirm & Fill PDF",
        type="primary",
        key="confirm_fill_pdf",
    )
    edit_clicked = col_edit.button(
        "Edit Answers",
        key="edit_answers_button",
    )

    if confirm_clicked:
        # Save to storage if requested
        if st.session_state.save_to_storage and st.session_state.storage_password:
            try:
                storage = st.session_state.get("_secure_storage_instance")
                # Filter out empty values and special symbols
                data_to_save = {
                    k: v for k, v in answers.items() 
                    if v and v not in {_CHECKED_SYMBOL, _RADIO_SYMBOL, ""}
                }
                if data_to_save and storage:
                    storage.save_answers(data_to_save, st.session_state.storage_password)
                    # Reload stored data immediately so it's available for next form
                    st.session_state.stored_data = storage.load_answers(st.session_state.storage_password)
                    st.success(f"💾 Saved {len(data_to_save)} field(s) to encrypted storage!")
            except StorageError as e:
                st.warning(f"Could not save to storage: {e}")
        
        _finalise_pdf(parsed_form, answers)
        return

    if edit_clicked:
        st.session_state.awaiting_confirmation = False
        st.session_state.pending_answers = answers.copy()
        st.session_state.filled_pdf_bytes = None
        st.session_state.filled_pdf_name = None
        st.session_state.input_mode = "form"
        st.session_state.conversation_state = None
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="AI Form Filler", page_icon="📝", layout="wide")
    _init_session_state()

    # Create and cache SecureStorage instance in session state
    if "_secure_storage_instance" not in st.session_state:
        st.session_state["_secure_storage_instance"] = SecureStorage()
    storage = st.session_state["_secure_storage_instance"]

    # Sidebar for storage settings
    with st.sidebar:
        st.header("🔒 Secure Storage")
        
        # Check if data exists
        if storage.has_stored_data():
            st.success("✓ Encrypted profile found")
        else:
            st.info("No saved profile yet")
        
        # Password input
        if not st.session_state.storage_password:
            password = st.text_input(
                "Storage Password",
                type="password",
                help="Enter password to unlock auto-fill. Your data is encrypted locally.",
                key="password_input"
            )
            if password:
                try:
                    # Try to load data with this password
                    stored_data = storage.load_answers(password)
                    st.session_state.storage_password = password
                    st.session_state.stored_data = stored_data
                    st.success(f"✓ Unlocked! {len(stored_data)} field(s) available")
                    st.rerun()
                except StorageError:
                    if storage.has_stored_data():
                        st.error("Invalid password")
                    else:
                        # New profile - accept any password
                        st.session_state.storage_password = password
                        st.session_state.stored_data = {}
                        st.success("Password set for new profile")
                        st.rerun()
        else:
            st.success(f"🔓 Unlocked ({len(st.session_state.stored_data)} fields)")
            if st.button("🔒 Lock Storage"):
                st.session_state.storage_password = None
                st.session_state.stored_data = {}
                st.session_state.save_to_storage = False
                st.rerun()
        
        # Storage management
        if st.session_state.storage_password:
            st.divider()
            with st.expander("📋 Stored Fields"):
                if st.session_state.stored_data:
                    for label, value in st.session_state.stored_data.items():
                        st.text(f"• {label}")
                        st.caption(f"  {value[:50]}..." if len(value) > 50 else f"  {value}")
                else:
                    st.caption("No fields stored yet")
            
            if storage.has_stored_data() and st.button("🗑️ Delete All Data", type="secondary"):
                storage.delete_all_data()
                st.session_state.storage_password = None
                st.session_state.stored_data = {}
                st.session_state.save_to_storage = False
                st.success("All data deleted")
                st.rerun()

    st.title("AI Form Filler MVP")
    st.write(
        "Upload a clean digital PDF with underline-style fields. We'll detect the fields, ask "
        "for the values, and produce a filled PDF."
    )

    uploaded_pdf = st.file_uploader("Upload PDF", type=["pdf"], accept_multiple_files=False)

    if not uploaded_pdf:
        st.info("Upload a PDF form to begin.")
        return

    _reset_state_on_new_upload(uploaded_pdf.name)
    pdf_bytes = uploaded_pdf.getvalue()

    if st.session_state.parsed_form is None:
        parsed_form = parse_pdf(pdf_bytes)
        st.session_state.parsed_form = parsed_form
    else:
        parsed_form = st.session_state.parsed_form

    if not parsed_form.fields:
        st.warning("No underline-based fields were detected. The PDF may not match the MVP constraints.")
        return

    st.subheader("Detected Fields")
    st.dataframe(
        {
            "Field": [field.label for field in parsed_form.fields],
            "Page": [field.page + 1 for field in parsed_form.fields],
            "BBox": [field.bbox for field in parsed_form.fields],
        }
    )

    st.subheader("Choose Input Mode")
    mode_labels = ("Form Mode (Manual)", "Chat Mode (AI Assistant)")
    current_index = 0 if st.session_state.input_mode == "form" else 1
    selected_label = st.radio(
        "Input method",
        options=mode_labels,
        index=current_index,
        horizontal=True,
        key="input_mode_selector",
    )
    new_mode = "form" if selected_label == mode_labels[0] else "chat"
    if st.session_state.input_mode != new_mode:
        st.session_state.input_mode = new_mode
        if new_mode == "form":
            st.session_state.conversation_state = None

    if st.session_state.input_mode == "chat":
        _render_chat_interface(parsed_form)
    else:
        _render_field_inputs(parsed_form)

    _render_confirmation(parsed_form)

    if st.session_state.filled_pdf_bytes and not st.session_state.awaiting_confirmation:
        st.download_button(
            label="Download Filled PDF",
            data=st.session_state.filled_pdf_bytes,
            file_name=st.session_state.filled_pdf_name or "filled_form.pdf",
            mime="application/pdf",
        )


if __name__ == "__main__":
    main()

"""Streamlit UI for the AI Form Filler MVP."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Dict, Sequence
import tempfile

import streamlit as st
from dotenv import load_dotenv

from aiformfiller.llm import (
    configure_gemini,
    create_conversation,
    get_next_question,
    process_user_response,
)
from services import FormPipeline, FormExtractionResult

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FORM_PIPELINE = FormPipeline()


def _persist_pdf(bytes_data: bytes, original_name: str) -> str:
    """Write uploaded PDF bytes to a temporary location and return the path."""

    temp_dir = OUTPUT_DIR / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as tmp_file:
        tmp_file.write(bytes_data)
        return tmp_file.name


def _cleanup_previous_upload() -> None:
    """Delete the last persisted upload if one exists."""

    path = st.session_state.get("uploaded_pdf_path")
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
    st.session_state.uploaded_pdf_path = None


def _map_answers_to_field_names(extracted: FormExtractionResult, answers: Dict[str, str]) -> Dict[str, str]:
    """Convert label-keyed answers into name-keyed answers expected by HTML filler."""

    mapping: Dict[str, str] = {}
    for field in extracted.fields:
        name_key = field.name or field.label
        if not name_key:
            continue
        label_key = field.label or field.name
        if label_key and label_key in answers:
            mapping[name_key] = answers[label_key]
        elif field.name and field.name in answers:
            mapping[name_key] = answers[field.name]
    return mapping


def _init_session_state() -> None:
    defaults = {
        "extracted_form": None,
        "uploaded_filename": None,
        "uploaded_pdf_path": None,
        "answers": {},
        "filled_pdf_bytes": None,
        "filled_pdf_name": None,
        "input_mode": "form",
        "conversation_state": None,
        "pending_answers": {},
        "awaiting_confirmation": False,
        "filled_html": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_state_on_new_upload(filename: str) -> None:
    if st.session_state.uploaded_filename != filename:
        _cleanup_previous_upload()
        st.session_state.extracted_form = None
        st.session_state.answers = {}
        st.session_state.filled_pdf_bytes = None
        st.session_state.filled_pdf_name = None
        st.session_state.conversation_state = None
        st.session_state.pending_answers = {}
        st.session_state.awaiting_confirmation = False
        st.session_state.filled_html = None
        st.session_state.uploaded_filename = filename


def _build_output_path(upload_name: str | None) -> Path:
    stem = Path(upload_name or "filled_form").stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{stem}_filled_{timestamp}.pdf"


def _normalise_answers(fields: Sequence, raw_answers: Dict[str, str]) -> Dict[str, str]:
    """Return a mapping keyed by HTML field name using any available labels."""

    normalised: Dict[str, str] = {}
    for field in fields:
        if not getattr(field, "name", None):
            continue
        label = field.label or field.name or ""
        if field.name in raw_answers:
            normalised[field.name] = raw_answers[field.name]
        elif label and label in raw_answers:
            normalised[field.name] = raw_answers[label]
    return normalised


def _stage_answers_for_confirmation(fields: Sequence, answers: Dict[str, str]) -> None:
    if not answers:
        return

    normalised = _normalise_answers(fields, answers)
    if not normalised:
        return

    pending = st.session_state.pending_answers or {}
    existing = st.session_state.answers or {}

    if (
        not st.session_state.awaiting_confirmation
        and st.session_state.filled_pdf_bytes
        and normalised == existing
    ):
        # Answers already confirmed and unchanged; skip restaging.
        return

    if st.session_state.awaiting_confirmation and normalised == pending:
        return

    st.session_state.pending_answers = normalised.copy()
    st.session_state.awaiting_confirmation = True
    st.session_state.answers = normalised.copy()
    st.session_state.filled_pdf_bytes = None
    st.session_state.filled_pdf_name = None


def _finalise_pdf(extracted: FormExtractionResult, answers: Dict[str, str]) -> None:
    output_path = _build_output_path(st.session_state.uploaded_filename)
    name_mapped_answers = _map_answers_to_field_names(extracted, answers)
    if not name_mapped_answers:
        st.warning("No answers available to fill the form.")
        return
    filled_html, pdf_path = FORM_PIPELINE.fill(extracted, name_mapped_answers, output_path.as_posix())
    with Path(pdf_path).open("rb") as fp:
        filled_bytes = fp.read()

    st.session_state.filled_pdf_bytes = filled_bytes
    st.session_state.filled_pdf_name = Path(pdf_path).name
    st.session_state.filled_html = filled_html
    st.session_state.awaiting_confirmation = False
    st.session_state.pending_answers = {}
    st.session_state.answers = answers.copy()

    st.success("PDF filled successfully. Download below.")


def _render_field_inputs(extracted: FormExtractionResult) -> None:
    st.subheader("Provide Field Values")
    answers: Dict[str, str] = {}
    with st.form("field_input_form"):
        for index, field in enumerate(extracted.fields):
            label = field.label or field.name or "Field"
            answer_key = field.name or (field.label or f"field_{index}")
            session_answers = st.session_state.answers or {}
            if field.name and field.name in session_answers:
                default_value = session_answers[field.name]
            elif field.label and field.label in session_answers:
                default_value = session_answers[field.label]
            else:
                default_value = field.value or ""

            layout = extracted.field_layouts.get(field.name or answer_key)
            widget_key = f"field_input_{index}_{field.name or 'unnamed'}"

            if layout and layout.kind == "grid":
                max_chars = layout.columns if layout.columns > 0 else None
                help_text = "Characters will be distributed across the boxes."
                if layout.columns:
                    help_text = f"Enter up to {layout.columns} characters; blanks will clear remaining boxes."
                text_kwargs = {
                    "label": label,
                    "value": default_value,
                    "key": widget_key,
                    "help": help_text,
                }
                if max_chars is not None:
                    text_kwargs["max_chars"] = max_chars
                answers[answer_key] = st.text_input(**text_kwargs)
            elif layout and layout.kind == "table":
                answers[answer_key] = st.text_area(
                    label,
                    value=default_value,
                    key=widget_key,
                    height=140,
                    help="Use commas or tabs to separate columns and new lines for rows.",
                )
            elif field.field_type == "textarea":
                answers[answer_key] = st.text_area(
                    label,
                    value=default_value,
                    key=widget_key,
                )
            else:
                answers[answer_key] = st.text_input(label, value=default_value, key=widget_key)
        submitted = st.form_submit_button("Review Answers")
    if submitted:
        _stage_answers_for_confirmation(extracted.fields, answers)
        st.rerun()
    return None


def _render_chat_interface(extracted: FormExtractionResult) -> None:
    """Collect answers through a conversational interface."""

    state = st.session_state.conversation_state
    if state is None:
        try:
            configure_gemini()
        except ValueError:
            st.error(
                "Chat Mode requires a valid GOOGLE_API_KEY. "
                "Please add it to your environment or switch back to Form Mode.",
                icon="⚠️",
            )
            st.session_state.input_mode = "form"
            return
        state = create_conversation(extracted.fields)
        state = replace(
            state,
            form_name=str(extracted.metadata.get("form_name", "")),
            html_template=extracted.html_template,
        )
        first_question = get_next_question(state)
        history = state.conversation_history
        if not history or history[-1].get("content") != first_question:
            history = history + [{"role": "assistant", "content": first_question}]
        state = replace(state, conversation_history=history)
        st.session_state.conversation_state = state

    if not state.is_complete:
        user_message = st.chat_input("Type your response")
        if user_message:
            try:
                state = process_user_response(state, user_message, validate_with_llm=True)
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
        _stage_answers_for_confirmation(extracted.fields, state.collected_answers)
        for label, value in state.collected_answers.items():
            st.markdown(f"- **{label}**: {value}")

    return None


def _render_confirmation(extracted: FormExtractionResult) -> None:
    if not st.session_state.awaiting_confirmation:
        return

    answers = st.session_state.pending_answers or {}
    if not answers:
        st.session_state.awaiting_confirmation = False
        return

    st.subheader("Review Your Answers")
    for field in extracted.fields:
        label = field.label or field.name or "Field"
        value = answers.get(field.name) or answers.get(label, "")
        display_value = value if value else "_Not provided_"
        layout = extracted.field_layouts.get(field.name or label)
        if layout and layout.kind == "table":
            st.markdown(f"**{label}**")
            if value:
                st.text(value)
            else:
                st.markdown("_Not provided_")
            continue

        st.markdown(f"- **{label}**: {display_value}")

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
        _finalise_pdf(extracted, answers)
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

    st.title("AI Form Filler MVP")
    st.write(
        "Upload a clean digital PDF form. We'll convert it to HTML, detect the fields, ask "
        "for the values, and produce a filled PDF."
    )

    uploaded_pdf = st.file_uploader("Upload PDF", type=["pdf"], accept_multiple_files=False)

    if not uploaded_pdf:
        st.info("Upload a PDF form to begin.")
        return

    _reset_state_on_new_upload(uploaded_pdf.name)
    pdf_bytes = uploaded_pdf.getvalue()

    if st.session_state.uploaded_pdf_path is None:
        st.session_state.uploaded_pdf_path = _persist_pdf(pdf_bytes, uploaded_pdf.name)
    pdf_path = st.session_state.uploaded_pdf_path

    if st.session_state.extracted_form is None:
        extracted_form = FORM_PIPELINE.extract(pdf_path)
        st.session_state.extracted_form = extracted_form
    else:
        extracted_form = st.session_state.extracted_form

    if not extracted_form.fields:
        st.warning("No interactive fields were detected. The PDF may not match the current capabilities.")
        metadata = extracted_form.metadata or {}
        if metadata:
            st.info(
                "Debug info: "
                f"title={metadata.get('form_name')}, pages={metadata.get('num_pages')}, "
                f"has_form_fields={metadata.get('has_form_fields')}"
            )
        st.markdown(
            "Possible causes:\n"
            "- The PDF is a scanned image without interactive form controls.\n"
            "- The form fields were flattened during export (no AcroForm data).\n"
            "- The PDF uses custom widgets unsupported by pdfplumber/WeasyPrint."
        )
        return

    metadata = extracted_form.metadata
    if metadata:
        st.caption(
            f"Form detected: {metadata.get('form_name', 'Unknown')} • Pages: {metadata.get('num_pages', 'n/a')}"
        )

    st.subheader("Detected Fields")
    layouts = extracted_form.field_layouts
    st.dataframe(
        {
            "Label": [field.label or "" for field in extracted_form.fields],
            "Name": [field.name or "" for field in extracted_form.fields],
            "Type": [field.field_type for field in extracted_form.fields],
            "Required": ["Yes" if field.required else "No" for field in extracted_form.fields],
            "Placeholder": [field.placeholder or "" for field in extracted_form.fields],
            "Layout": [
                (layouts[field.name].kind if field.name in layouts else "single")
                for field in extracted_form.fields
            ],
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
        st.session_state.conversation_state = None

    if st.session_state.input_mode == "chat":
        _render_chat_interface(extracted_form)
    else:
        _render_field_inputs(extracted_form)

    _render_confirmation(extracted_form)

    if st.session_state.filled_pdf_bytes and not st.session_state.awaiting_confirmation:
        st.download_button(
            label="Download Filled PDF",
            data=st.session_state.filled_pdf_bytes,
            file_name=st.session_state.filled_pdf_name or "filled_form.pdf",
            mime="application/pdf",
        )


if __name__ == "__main__":
    main()

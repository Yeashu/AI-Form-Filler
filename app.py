"""Streamlit UI for the AI Form Filler MVP."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

import streamlit as st

from aiformfiller.models import DetectedField, FieldType
from aiformfiller.pipeline import ParsedForm, fill_parsed_form, parse_pdf

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
_RADIO_NONE_OPTION = "— No selection —"
_CHECKED_SYMBOL = "☒"
_RADIO_SYMBOL = "●"


def _init_session_state() -> None:
    defaults = {
        "parsed_form": None,
        "uploaded_filename": None,
        "answers": {},
        "filled_pdf_bytes": None,
        "filled_pdf_name": None,
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
        st.session_state.uploaded_filename = filename


def _build_output_path(upload_name: str | None) -> Path:
    stem = Path(upload_name or "filled_form").stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{stem}_filled_{timestamp}.pdf"


def _group_radio_fields(fields: List[DetectedField]) -> Dict[str, List[DetectedField]]:
    groups: Dict[str, List[DetectedField]] = defaultdict(list)
    for field in fields:
        if field.field_type != FieldType.RADIO:
            continue
        group_key = field.group_key or field.raw_label or field.label
        groups[group_key].append(field)
    return groups


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
    title_source = group_fields[0]
    title = title_source.raw_label or title_source.label
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
    if field.field_type == FieldType.TEXTBOX:
        return st.text_area(field.label, value=default_value)
    return st.text_input(field.label, value=default_value)


def _render_field_inputs(parsed_form: ParsedForm) -> Dict[str, str]:
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
        submitted = st.form_submit_button("Fill PDF")
    if submitted:
        st.session_state.answers = answers
        return answers
    return {}


def _maybe_render_results(filled_answers: Dict[str, str], parsed_form: ParsedForm) -> None:
    if not filled_answers:
        return
    output_path = _build_output_path(st.session_state.uploaded_filename)
    fill_parsed_form(parsed_form, filled_answers, output_path.as_posix())
    with output_path.open("rb") as fp:
        filled_bytes = fp.read()
    st.session_state.filled_pdf_bytes = filled_bytes
    st.session_state.filled_pdf_name = output_path.name
    st.success("PDF filled successfully. Download below.")
    st.download_button(
        label="Download Filled PDF",
        data=filled_bytes,
        file_name=output_path.name,
        mime="application/pdf",
    )


def main() -> None:
    st.set_page_config(page_title="AI Form Filler", page_icon="📝", layout="wide")
    _init_session_state()

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

    filled_answers = _render_field_inputs(parsed_form)

    if filled_answers:
        _maybe_render_results(filled_answers, parsed_form)
    elif st.session_state.filled_pdf_bytes:
        st.info("Using previously filled PDF.")
        st.download_button(
            label="Download Filled PDF",
            data=st.session_state.filled_pdf_bytes,
            file_name=st.session_state.filled_pdf_name or "filled_form.pdf",
            mime="application/pdf",
        )


if __name__ == "__main__":
    main()

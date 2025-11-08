"""Streamlit UI for the AI Form Filler MVP."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

import streamlit as st

from aiformfiller.pipeline import ParsedForm, fill_parsed_form, parse_pdf

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


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


def _render_field_inputs(parsed_form: ParsedForm) -> Dict[str, str]:
    st.subheader("Provide Field Values")
    answers: Dict[str, str] = {}
    with st.form("field_input_form"):
        for field in parsed_form.fields:
            default_value = st.session_state.answers.get(field.label, "")
            answers[field.label] = st.text_input(field.label, value=default_value)
        submitted = st.form_submit_button("Fill PDF")
    if submitted:
        st.session_state.answers = answers
    return answers if submitted else {}


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

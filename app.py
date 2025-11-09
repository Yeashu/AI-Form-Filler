"""Streamlit UI for the AI Form Filler MVP."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Dict, Sequence, Set
import tempfile
import re
import base64
import streamlit.components.v1 as components

import streamlit as st
from dotenv import load_dotenv

from aiformfiller.llm import (
    configure_gemini,
    create_conversation,
    get_next_question,
    process_user_response,
)
from aiformfiller.models import DetectedField as ParserDetectedField, FieldType
from aiformfiller.pipeline import (
    ParsedForm,
    collect_answers_with_llm,
    fill_parsed_form,
    parse_pdf,
)
from aiformfiller.storage import SecureStorage, StorageError
from services import FormPipeline, FormExtractionResult, FieldLayout

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

FORM_PIPELINE = FormPipeline()
_TABLE_SPLIT_PATTERN = re.compile(r"\t|,|\s{2,}")
_RADIO_NONE_OPTION = "— No selection —"
_CHECKED_SYMBOL = "X"
_RADIO_SYMBOL = "●"


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
        "preview_pdf_bytes": None,
        "preview_pdf_name": None,
        "storage_password": None,
        "stored_data": {},
        "save_to_storage": False,
        "use_parser_mode": False,  # Toggle between HTML and parser mode
        "parsed_form": None,  # For parser-based mode
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
        st.session_state.preview_pdf_bytes = None
        st.session_state.preview_pdf_name = None
        st.session_state.uploaded_filename = filename


def _build_output_path(upload_name: str | None) -> Path:
    stem = Path(upload_name or "filled_form").stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{stem}_filled_{timestamp}.pdf"


def _parse_table_string(raw: str) -> list[list[str]]:
    lines = str(raw or "").splitlines()
    return [
        [cell.strip() for cell in _TABLE_SPLIT_PATTERN.split(line)] if line else [""]
        for line in lines
    ]


def _prepare_table_rows(value: str, layout: FieldLayout) -> tuple[list[list[str]], int, int]:
    parsed = _parse_table_string(value)
    rows = layout.rows or len(parsed) or 1
    cols = layout.columns or max((len(row) for row in parsed), default=0)
    if cols <= 0:
        cols = 1
    normalised: list[list[str]] = []
    for row_index in range(rows):
        source = parsed[row_index] if row_index < len(parsed) else []
        trimmed = source[:cols]
        if len(trimmed) < cols:
            trimmed = trimmed + [""] * (cols - len(trimmed))
        normalised.append(trimmed)
    return normalised, rows, cols


def _serialise_table_rows(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = ["\t".join(cell.strip() for cell in row) for row in rows]
    if all(not line for line in lines):
        return ""
    return "\n".join(lines).rstrip()


def _generate_preview_pdf(extracted: FormExtractionResult, answers: Dict[str, str]) -> None:
    if not answers:
        st.warning("No answers available to preview the form.")
        return

    name_mapped_answers = _map_answers_to_field_names(extracted, answers)
    if not name_mapped_answers:
        st.warning("No answers matched the detected form fields.")
        return

    # Debug: Show what we're filling
    st.info(f"Generating preview with {len(name_mapped_answers)} field values...")
    with st.expander("🔍 Debug: Field Mapping (Click to expand)"):
        st.markdown("**Fields we're trying to fill:**")
        for key, value in sorted(name_mapped_answers.items()):
            st.text(f"  {key}: {value[:50] if len(value) > 50 else value}")
        
        st.markdown("**All detected form fields:**")
        for field in extracted.fields:
            st.text(f"  Name: {field.name or 'N/A'} | Label: {field.label or 'N/A'}")

    temp_dir = OUTPUT_DIR / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir=temp_dir) as tmp_file:
        preview_path = tmp_file.name

    pdf_path: str | None = None
    try:
        _, pdf_path = FORM_PIPELINE.fill(extracted, name_mapped_answers, preview_path)
        if pdf_path and Path(pdf_path).exists():
            with Path(pdf_path).open("rb") as fp:
                st.session_state.preview_pdf_bytes = fp.read()
            st.session_state.preview_pdf_name = Path(pdf_path).name
            logging.info(f"Preview PDF generated: {pdf_path}, size: {len(st.session_state.preview_pdf_bytes)} bytes")
            st.success(f"✓ Preview generated successfully ({len(st.session_state.preview_pdf_bytes):,} bytes)")
        else:
            st.error(f"Failed to generate preview PDF at {pdf_path}")
            logging.error(f"Preview PDF not found at {pdf_path}")
    except Exception as e:
        st.error(f"Error generating preview: {str(e)}")
        logging.error(f"Error in _generate_preview_pdf: {e}", exc_info=True)
    finally:
        for path_str in (preview_path, pdf_path):
            if not path_str:
                continue
            try:
                Path(path_str).unlink(missing_ok=True)
            except OSError:
                pass


def _render_pdf_preview() -> None:
    preview_bytes = st.session_state.get("preview_pdf_bytes")
    if not preview_bytes:
        return

    st.subheader("PDF Preview")
    st.caption(f"Showing filled PDF preview ({len(preview_bytes):,} bytes)")
    try:
        encoded = base64.b64encode(preview_bytes).decode("utf-8")
    except Exception:  # pragma: no cover
        st.error("Unable to display preview.")
        return

    safe_payload = json.dumps(encoded)
    preview_html = f"""
<div style="width:100%; background-color:#1e1e1e; padding:12px; border-radius:8px;">
    <div style="text-align:center; margin-bottom:10px;">
        <button id="prev-page" style="padding:8px 16px; margin:0 5px; background:#4a4a4a; color:white; border:none; border-radius:4px; cursor:pointer;">← Previous</button>
        <span id="page-info" style="color:#cccccc; margin:0 10px;">Page 1 of ?</span>
        <button id="next-page" style="padding:8px 16px; margin:0 5px; background:#4a4a4a; color:white; border:none; border-radius:4px; cursor:pointer;">Next →</button>
    </div>
    <div style="max-height:800px; overflow-y:auto; background:#2b2b2b; padding:10px; border-radius:4px;">
        <canvas id="pdf-preview-canvas" style="width:100%; max-width:900px; display:block; margin:0 auto;"></canvas>
    </div>
    <div id="pdf-preview-message" style="text-align:center; color:#cccccc; margin-top:8px;">Loading preview...</div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js"></script>
    <script>
        (function() {{
            const base64 = {safe_payload};
            let pdfDoc = null;
            let currentPage = 1;
            let rendering = false;

            function toUint8Array(b64) {{
                try {{
                    const binary = atob(b64);
                    const length = binary.length;
                    const bytes = new Uint8Array(length);
                    for (let index = 0; index < length; index += 1) {{
                        bytes[index] = binary.charCodeAt(index);
                    }}
                    return bytes;
                }} catch (error) {{
                    console.error('Error converting base64:', error);
                    throw error;
                }}
            }}

            function renderPage(pageNum) {{
                if (rendering || !pdfDoc) return;
                rendering = true;

                const canvas = document.getElementById('pdf-preview-canvas');
                const message = document.getElementById('pdf-preview-message');
                const pageInfo = document.getElementById('page-info');

                message.innerText = 'Rendering page ' + pageNum + '...';

                pdfDoc.getPage(pageNum)
                    .then(function(page) {{
                        const containerWidth = canvas.parentElement.clientWidth || 600;
                        const viewport = page.getViewport({{ scale: 1 }});
                        const scale = Math.min((containerWidth - 20) / viewport.width, 2.0);
                        const scaledViewport = page.getViewport({{ scale: scale }});

                        canvas.height = scaledViewport.height;
                        canvas.width = scaledViewport.width;

                        const renderContext = {{
                            canvasContext: canvas.getContext('2d'),
                            viewport: scaledViewport,
                        }};

                        return page.render(renderContext).promise;
                    }})
                    .then(function() {{
                        rendering = false;
                        message.innerText = '';
                        pageInfo.innerText = 'Page ' + pageNum + ' of ' + pdfDoc.numPages;
                        updateButtons();
                        // Scroll to top of canvas
                        canvas.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                    }})
                    .catch(function(error) {{
                        rendering = false;
                        console.error('Error rendering page:', error);
                        message.innerText = 'Error: ' + error.message;
                        message.style.color = '#ff6b6b';
                    }});
            }}

            function updateButtons() {{
                const prevBtn = document.getElementById('prev-page');
                const nextBtn = document.getElementById('next-page');

                if (prevBtn && nextBtn && pdfDoc) {{
                    prevBtn.disabled = currentPage <= 1;
                    nextBtn.disabled = currentPage >= pdfDoc.numPages;
                    prevBtn.style.opacity = currentPage <= 1 ? '0.5' : '1';
                    nextBtn.style.opacity = currentPage >= pdfDoc.numPages ? '0.5' : '1';
                    prevBtn.style.cursor = currentPage <= 1 ? 'not-allowed' : 'pointer';
                    nextBtn.style.cursor = currentPage >= pdfDoc.numPages ? 'not-allowed' : 'pointer';
                }}
            }}

            function startRender() {{
                const canvas = document.getElementById('pdf-preview-canvas');
                const message = document.getElementById('pdf-preview-message');
                const prevBtn = document.getElementById('prev-page');
                const nextBtn = document.getElementById('next-page');

                if (!canvas || !message || typeof window.pdfjsLib === 'undefined') {{
                    return false;
                }}

                try {{
                    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
                }} catch (workerError) {{
                    console.warn('Worker configuration warning:', workerError);
                }}

                try {{
                    const pdfData = toUint8Array(base64);
                    const loadingTask = pdfjsLib.getDocument({{ data: pdfData }});

                    loadingTask.promise
                        .then(function(pdf) {{
                            pdfDoc = pdf;
                            console.log('PDF loaded, pages:', pdf.numPages);

                            // Set up navigation buttons
                            prevBtn.onclick = function() {{
                                if (currentPage > 1 && !rendering) {{
                                    currentPage--;
                                    renderPage(currentPage);
                                }}
                            }};

                            nextBtn.onclick = function() {{
                                if (currentPage < pdfDoc.numPages && !rendering) {{
                                    currentPage++;
                                    renderPage(currentPage);
                                }}
                            }};

                            // Render first page
                            renderPage(1);
                        }})
                        .catch(function(error) {{
                            console.error('Error loading PDF:', error);
                            message.innerText = 'Error loading PDF: ' + error.message;
                            message.style.color = '#ff6b6b';
                        }});

                    return true;
                }} catch (error) {{
                    console.error('Error in startRender:', error);
                    message.innerText = 'Error: ' + error.message;
                    message.style.color = '#ff6b6b';
                    return false;
                }}
            }}

            function tryRender() {{
                if (startRender()) {{
                    return;
                }}
                setTimeout(tryRender, 100);
            }}

            if (document.readyState === 'complete') {{
                setTimeout(tryRender, 100);
            }} else {{
                window.addEventListener('load', function() {{
                    setTimeout(tryRender, 100);
                }});
            }}
        }})();
    </script>
</div>
"""
    components.html(preview_html, height=900, scrolling=True)


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
    st.session_state.preview_pdf_bytes = None
    st.session_state.preview_pdf_name = None


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


def _group_radio_fields(fields: list) -> Dict[str, list]:
    """Group radio button fields by their group key."""
    from collections import defaultdict
    groups: Dict[str, list] = defaultdict(list)
    for field in fields:
        if field.field_type != FieldType.RADIO:
            continue
        group_key = field.group_key or field.raw_label or field.label
        groups[group_key].append(field)
    return groups


def _format_group_title(field) -> str:
    """Format a radio group title from field metadata."""
    source = field.group_key or field.raw_label or field.label
    cleaned = (source or "").replace("_", " ").strip().strip(":")
    if not cleaned:
        return "Selection"
    return cleaned[0].upper() + cleaned[1:]


def _radio_option_label(field) -> str:
    """Get display label for a radio option."""
    if field.export_value and field.export_value.lower() not in {"off", "false"}:
        return field.export_value
    return field.label


def _radio_group_default_selection(group_fields: list) -> str:
    """Get the default selection for a radio group."""
    for field in group_fields:
        if st.session_state.answers.get(field.label):
            return _radio_option_label(field)
    return _RADIO_NONE_OPTION


def _render_radio_group(group_key: str, group_fields: list) -> str:
    """Render a radio button group that works inside a form."""
    option_labels = [_radio_option_label(field) for field in group_fields]
    options = [_RADIO_NONE_OPTION] + option_labels
    default_label = _radio_group_default_selection(group_fields)
    default_index = options.index(default_label) if default_label in options else 0
    title = _format_group_title(group_fields[0])
    # Use st.radio which works in forms - the key makes it unique
    return st.radio(
        title,
        options=options,
        index=default_index,
        key=f"radio_{group_key}",
        horizontal=False,  # Vertical layout is clearer for forms
    )


def _radio_group_answers(group_fields: list, selection: str) -> Dict[str, str]:
    """Convert radio selection to answer dictionary."""
    answers: Dict[str, str] = {}
    if selection == _RADIO_NONE_OPTION:
        for field in group_fields:
            answers[field.label] = ""
        return answers
    for field in group_fields:
        option_label = _radio_option_label(field)
        answers[field.label] = _RADIO_SYMBOL if option_label == selection else ""
    return answers


def _render_checkbox_field(field) -> str:
    """Render a checkbox field that works inside a form."""
    default_checked = bool(st.session_state.answers.get(field.label))
    # st.checkbox works fine in forms when given a unique key
    checked = st.checkbox(
        field.label,
        value=default_checked,
        key=f"checkbox_{field.label}",
    )
    return _CHECKED_SYMBOL if checked else ""


def _render_text_field(field) -> str:
    """Render a text input field with auto-fill from storage."""
    default_value = st.session_state.answers.get(field.label, "")
    
    # Try to get auto-fill suggestion from storage
    storage = st.session_state.get("_secure_storage_instance")
    if not default_value and st.session_state.stored_data and storage:
        suggestion = storage.get_suggestion(field.label, st.session_state.stored_data)
        if suggestion:
            default_value = suggestion
            logging.info(f"Auto-filled '{field.label}' with '{suggestion[:30]}...' from storage")
    
    if field.field_type == FieldType.TEXTBOX:
        result = st.text_area(field.label, value=default_value, key=f"text_{field.label}")
        return result if result is not None else ""
    result = st.text_input(field.label, value=default_value, key=f"text_{field.label}")
    return result if result is not None else ""


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

            if layout and (layout.kind == "grid" or layout.kind == "table"):
                answers[answer_key] = st.text_input(label, value=default_value, key=widget_key)
            elif field.field_type == "textarea":
                answers[answer_key] = st.text_area(
                    label,
                    value=default_value,
                    key=widget_key,
                )
            else:
                answers[answer_key] = st.text_input(label, value=default_value, key=widget_key)
        
        # Add option to save to storage
        if st.session_state.storage_password:
            st.session_state.save_to_storage = st.checkbox(
                "💾 Save responses to encrypted storage for future use",
                value=st.session_state.save_to_storage,
                help="Your data will be encrypted and stored locally"
            )
        
        col1, col2 = st.columns(2)
        preview_btn = col1.form_submit_button("Preview Filled PDF", type="secondary")
        confirm_btn = col2.form_submit_button("Confirm & Fill PDF", type="primary")
    
    if preview_btn:
        _stage_answers_for_confirmation(extracted.fields, answers)
        _generate_preview_pdf(extracted, answers)
        st.rerun()
    elif confirm_btn:
        _stage_answers_for_confirmation(extracted.fields, answers)
        _finalise_pdf(extracted, answers)
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
        
        # Convert HTML DetectedFields to Parser DetectedFields for compatibility
        parser_fields = []
        for field in extracted.fields:
            # Create a simple ParserDetectedField with label
            # We'll use a basic FieldType.TEXT for simplicity
            label = field.label or field.name or "Field"
            parser_field = ParserDetectedField(
                label=label,
                raw_label=label,
                page=0,  # Not critical for chat
                bbox=(0, 0, 0, 0),  # Not critical for chat
                field_type=FieldType.TEXT,  # Default to text
            )
            parser_fields.append(parser_field)
        
        state = create_conversation(parser_fields)
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
    # This function is no longer needed as buttons are now in the form
    pass


def main() -> None:
    st.set_page_config(page_title="AI Form Filler", page_icon="📝", layout="wide")
    _init_session_state()

    # Sidebar for storage setup
    with st.sidebar:
        st.header("🔐 Secure Storage")
        st.markdown("Encrypt and save form responses for future use.")
        
        password = st.text_input(
            "Storage Password",
            type="password",
            value=st.session_state.storage_password or "",
            help="Set a password to encrypt/decrypt your stored data"
        )
        
        # Initialize storage instance if password is provided
        if password:
            if password != st.session_state.storage_password or "_secure_storage_instance" not in st.session_state:
                st.session_state.storage_password = password
                try:
                    storage = SecureStorage()
                    st.session_state._secure_storage_instance = storage
                    # Try to load existing data
                    try:
                        loaded_data = storage.load_answers(password)
                        st.session_state.stored_data = loaded_data
                        st.success(f"✓ Loaded {len(loaded_data)} stored fields")
                    except StorageError:
                        st.info("No previous data found or wrong password")
                        st.session_state.stored_data = {}
                except Exception as e:
                    st.error(f"Storage error: {str(e)}")
        
        if st.session_state.stored_data:
            st.metric("Stored Fields", len(st.session_state.stored_data))
            
            # Show stored fields in expander
            with st.expander("📋 View Stored Data"):
                for key, value in sorted(st.session_state.stored_data.items()):
                    st.text(f"{key}: {value[:50]}..." if len(value) > 50 else f"{key}: {value}")
            
            if st.button("🗑️ Clear Storage"):
                st.session_state.stored_data = {}
                st.session_state.storage_password = None
                if "_secure_storage_instance" in st.session_state:
                    del st.session_state._secure_storage_instance
                st.rerun()

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

    # Try HTML-based extraction first (for interactive PDFs)
    if st.session_state.extracted_form is None and st.session_state.parsed_form is None:
        extracted_form = FORM_PIPELINE.extract(pdf_path)
        
        # Check if PDF has interactive form fields
        metadata = extracted_form.metadata or {}
        has_interactive_fields = metadata.get("has_form_fields", False) and extracted_form.fields
        
        if has_interactive_fields:
            # Use HTML-based pipeline for interactive PDFs
            st.session_state.extracted_form = extracted_form
            st.session_state.use_parser_mode = False
            st.info("🎯 Detected interactive PDF form - using HTML-based extraction")
        else:
            # Fallback to parser-based pipeline for underline-style PDFs
            st.warning("⚠️ No interactive form fields detected. Trying underline-based parser...")
            try:
                parsed_form = parse_pdf(pdf_bytes)
                if parsed_form.fields:
                    st.session_state.parsed_form = parsed_form
                    st.session_state.use_parser_mode = True
                    st.success("✓ Detected underline-based fields")
                else:
                    st.session_state.extracted_form = extracted_form  # Keep empty HTML result
                    st.session_state.use_parser_mode = False
            except Exception as e:
                st.error(f"Parser fallback failed: {str(e)}")
                st.session_state.extracted_form = extracted_form
                st.session_state.use_parser_mode = False
    
    # Use the appropriate mode
    if st.session_state.use_parser_mode and st.session_state.parsed_form:
        parsed_form = st.session_state.parsed_form
        
        if not parsed_form.fields:
            st.warning("No underline-based fields were detected in the PDF.")
            return
        
        st.caption(f"📄 Underline-based PDF detected")
        
        st.subheader("Detected Fields")
        st.dataframe(
            {
                "Field": [field.label for field in parsed_form.fields],
                "Page": [field.page + 1 for field in parsed_form.fields],
                "Type": [field.field_type.value if hasattr(field.field_type, 'value') else str(field.field_type) for field in parsed_form.fields],
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
            key="input_mode_selector_parser",
        )
        new_mode = "form" if selected_label == mode_labels[0] else "chat"
        if st.session_state.input_mode != new_mode:
            st.session_state.input_mode = new_mode
            st.session_state.conversation_state = None
        
        # Render parser-based UI with proper field type support
        if st.session_state.input_mode == "form":
            st.subheader("Provide Field Values")
            
            # Debug info
            if st.session_state.stored_data:
                st.info(f"💡 Auto-fill available for {len(st.session_state.stored_data)} stored fields")
            
            answers: Dict[str, str] = {}
            radio_groups = _group_radio_fields(parsed_form.fields)
            processed_radio_groups: Set[str] = set()
            
            with st.form("parser_field_input_form"):
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
                
                submitted = st.form_submit_button("Fill PDF")
            
            if submitted:
                st.session_state.answers = answers
                
                # Save to storage if requested
                if st.session_state.save_to_storage and st.session_state.storage_password:
                    try:
                        storage = st.session_state.get("_secure_storage_instance")
                        if storage:
                            # Filter out empty values and special symbols
                            data_to_save = {
                                k: v for k, v in answers.items() 
                                if v and v not in {_CHECKED_SYMBOL, _RADIO_SYMBOL, ""}
                            }
                            if data_to_save:
                                storage.save_answers(data_to_save, st.session_state.storage_password)
                                # Update session state to reflect saved data
                                st.session_state.stored_data.update(data_to_save)
                                st.success(f"💾 Saved {len(data_to_save)} responses to encrypted storage")
                                logging.info(f"Saved fields to storage: {list(data_to_save.keys())}")
                            else:
                                st.info("No new data to save (empty or special values filtered out)")
                    except StorageError as e:
                        st.error(f"Failed to save to storage: {str(e)}")
                    except Exception as e:
                        st.error(f"Unexpected error saving to storage: {str(e)}")
                        logging.error(f"Storage save error: {e}", exc_info=True)
                
                output_path = _build_output_path(st.session_state.uploaded_filename)
                fill_parsed_form(parsed_form, answers, output_path.as_posix())
                with output_path.open("rb") as fp:
                    st.session_state.filled_pdf_bytes = fp.read()
                    st.session_state.filled_pdf_name = output_path.name
                st.success("PDF filled successfully!")
                st.rerun()
        
        if st.session_state.filled_pdf_bytes:
            st.download_button(
                label="Download Filled PDF",
                data=st.session_state.filled_pdf_bytes,
                file_name=st.session_state.filled_pdf_name or "filled_form.pdf",
                mime="application/pdf",
            )
        return

    # HTML-based mode (original code)
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
    positions = extracted_form.field_positions
    st.dataframe(
        {
            "Label": [field.label or "" for field in extracted_form.fields],
            "Name": [field.name or "" for field in extracted_form.fields],
            "Type": [field.field_type for field in extracted_form.fields],
            "Required": ["Yes" if field.required else "No" for field in extracted_form.fields],
            "Placeholder": [field.placeholder or "" for field in extracted_form.fields],
            "Page": [
                int(positions.get(field.name, (0, 0.0, 0.0))[0]) + 1
                for field in extracted_form.fields
            ],
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
    _render_pdf_preview()

    if st.session_state.filled_pdf_bytes and not st.session_state.awaiting_confirmation:
        st.download_button(
            label="Download Filled PDF",
            data=st.session_state.filled_pdf_bytes,
            file_name=st.session_state.filled_pdf_name or "filled_form.pdf",
            mime="application/pdf",
        )


if __name__ == "__main__":
    main()

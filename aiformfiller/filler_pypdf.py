"""Alternative filler using pypdf to write AcroForm fields by name.

This path is preferred for native, fillable PDFs with named fields.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from io import BytesIO
from typing import Any, BinaryIO, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union, cast

from .models import DetectedField, FieldType

logger = logging.getLogger(__name__)
if not logger.handlers:
    import os
    level_name = os.getenv("AIFORMFILLER_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.setLevel(level)
    logger.addHandler(handler)
else:
    # If already configured by parent, just set the level
    import os
    level_name = os.getenv("AIFORMFILLER_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

PdfSource = Union[str, bytes, BinaryIO]


def _to_reader_stream(source: PdfSource) -> Tuple[Optional[BytesIO], Union[str, bytes, BytesIO, BinaryIO]]:
    """Return a stream-like object suitable for pypdf.PdfReader and the backing buffer.

    The first element is a BytesIO buffer we own (or None if we can pass through),
    the second is what should be passed to PdfReader.
    """
    if isinstance(source, str):
        return None, source
    if isinstance(source, (bytes, bytearray)):
        buf = BytesIO(source)
        return buf, buf
    # BinaryIO or file-like
    return None, source


# pypdf is an optional dependency; import lazily and handle ImportError

def _import_pypdf():
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import BooleanObject, NameObject
    except Exception as exc:  # pragma: no cover - optional dep
        raise ImportError("pypdf not available") from exc
    return PdfReader, PdfWriter, BooleanObject, NameObject


def _build_values_map(fields: Sequence[DetectedField], answers: Mapping[str, str]) -> Dict[str, str]:
    """Create a mapping of AcroForm field names to values from detected fields and answers.

    Rules:
    - Prefer named fields (form_field_name); skip items without a name.
    - TEXT/TEXTBOX: use the user's provided string.
    - CHECKBOX: set to export value (or 'Yes') if checked; omit otherwise.
    - RADIO: for each group (same form_field_name), set selected option's export value.
    """
    values: Dict[str, str] = {}
    logger.debug("Building AcroForm value map from %d fields", len(fields))

    # Radios need grouping by form_field_name
    radio_groups: Dict[str, list[DetectedField]] = defaultdict(list)

    for f in fields:
        if not f.form_field_name:
            logger.debug("Skipping field without name: label=%s raw=%s", f.label, f.raw_label)
            continue
        if f.field_type == FieldType.RADIO:
            radio_groups[f.form_field_name].append(f)
            logger.debug("Queued radio field for group '%s': %s", f.form_field_name, f.label)
            continue

        # For non-radios, derive value directly
        val: Optional[str] = answers.get(f.label) or answers.get(f.raw_label) or answers.get(f.form_field_name)
        if not val:
            logger.debug("No answer for field '%s' (name=%s)", f.label, f.form_field_name)
            continue

        if f.field_type in {FieldType.TEXT, FieldType.TEXTBOX}:
            values[f.form_field_name] = val
            logger.debug("Mapped text field '%s' -> '%s'", f.form_field_name, val)
        elif f.field_type == FieldType.CHECKBOX:
            # Treat any non-empty as checked; use export_value or fallback to common values
            export = f.export_value
            if not export or export.lower() in {"off", "false"}:
                # Try common checkbox "on" states
                export = "Yes"  # Most common
            values[f.form_field_name] = export
            logger.debug("Mapped checkbox field '%s' -> '%s' (export_value=%s)", f.form_field_name, export, f.export_value)
        # Buttons are not filled

    # Handle radios: pick the option with a non-empty answer
    for name, group in radio_groups.items():
        chosen: Optional[DetectedField] = None
        for opt in group:
            ans = answers.get(opt.label) or answers.get(opt.raw_label)
            if ans:  # selected in UI
                chosen = opt
                break
        if chosen is not None:
            export = chosen.export_value
            if not export or export.lower() in {"off", "false"}:
                # Fallback to common radio "on" state
                export = "Yes"
            values[name] = export
            logger.debug("Selected radio '%s' -> '%s' (option label=%s, export_value=%s)", name, export, chosen.label, chosen.export_value)
        else:
            logger.debug("No selection for radio group '%s'", name)

    return values


def fill_pdf_acroform(
    source: PdfSource,
    destination_path: str,
    fields: Sequence[DetectedField],
    answers: Mapping[str, str],
) -> Optional[str]:
    """Fill form fields using pypdf and save to destination.

    Returns destination path on success, or None if pypdf isn't available
    or if there are no named fields to set.
    """
    # Build mapping first; if nothing to set, skip
    field_values = _build_values_map(fields, answers)
    if not field_values:
        logger.info("No AcroForm values to set (either no named fields or no answers). Skipping pypdf path.")
        return None

    try:
        PdfReader, PdfWriter, BooleanObject, NameObject = _import_pypdf()
    except ImportError:
        logger.info("pypdf not available; falling back to PyMuPDF filler.")
        return None

    # Prepare reader/writer
    buf, reader_src = _to_reader_stream(source)
    reader = PdfReader(cast(Any, reader_src))
    logger.debug("Loaded PDF with %d pages for AcroForm filling", len(reader.pages))
    writer = PdfWriter()

    # Add pages first
    for idx, page in enumerate(reader.pages):
        writer.add_page(page)
        logger.debug("Added page %d to writer", idx)

    # Copy AcroForm early so updates can find the fields
    try:
        root = cast(Any, reader.trailer)["/Root"]
        acro = getattr(root, "get", lambda *_args, **_kwargs: None)("/AcroForm")
        if acro is not None:
            writer._root_object[NameObject("/AcroForm")] = acro  # type: ignore[attr-defined]
            logger.debug("Copied AcroForm from reader to writer")
    except Exception as e:
        logger.debug("Failed to copy AcroForm before updates: %s", e)

    # Update on each page to cover per-page appearances
    for idx, page in enumerate(writer.pages):
        try:
            writer.update_page_form_field_values(page, field_values)
            logger.debug("Updated form field values on page %d with values: %s", idx, field_values)
        except Exception as e:
            # Some pypdf versions may raise if page lacks annotations; ignore
            logger.warning("Failed to update form values on page %d: %s", idx, e)
    
    # Alternative approach: directly update field values in the AcroForm
    try:
        from pypdf.generic import TextStringObject
        
        if NameObject("/AcroForm") in writer._root_object:  # type: ignore[attr-defined]
            acro_form = writer._root_object[NameObject("/AcroForm")]  # type: ignore[index]
            if NameObject("/Fields") in acro_form:  # type: ignore[operator]
                fields_array = acro_form[NameObject("/Fields")]  # type: ignore[index]
                for field_obj in fields_array:  # type: ignore[attr-defined]
                    field_obj_deref = field_obj.get_object() if hasattr(field_obj, 'get_object') else field_obj
                    if NameObject("/T") in field_obj_deref:  # type: ignore[operator]
                        field_name = str(field_obj_deref[NameObject("/T")])  # type: ignore[index]
                        if field_name in field_values:
                            value = field_values[field_name]
                            # For button fields (radio/checkbox), use NameObject; for text, use TextStringObject
                            if NameObject("/FT") in field_obj_deref:  # type: ignore[operator]
                                field_type = field_obj_deref[NameObject("/FT")]  # type: ignore[index]
                                if field_type == NameObject("/Btn"):
                                    field_obj_deref[NameObject("/V")] = NameObject(f"/{value}")  # type: ignore[index]
                                    # Also set appearance state
                                    field_obj_deref[NameObject("/AS")] = NameObject(f"/{value}")  # type: ignore[index]
                                else:
                                    field_obj_deref[NameObject("/V")] = TextStringObject(value)  # type: ignore[index]
                            else:
                                field_obj_deref[NameObject("/V")] = TextStringObject(value)  # type: ignore[index]
                            logger.debug("Directly set field '%s' to '%s'", field_name, value)
    except Exception as e:
        logger.debug("Failed to directly update AcroForm fields: %s", e)

    # Set NeedAppearances to prompt viewers to regenerate appearances
    try:
        from pypdf.generic import DictionaryObject

        if NameObject("/AcroForm") in writer._root_object:  # type: ignore[attr-defined]
            writer._root_object[NameObject("/AcroForm")][NameObject("/NeedAppearances")] = BooleanObject(True)  # type: ignore[index]
        else:
            new_acro = DictionaryObject()
            new_acro[NameObject("/NeedAppearances")] = BooleanObject(True)
            writer._root_object[NameObject("/AcroForm")] = new_acro  # type: ignore[attr-defined]
        logger.debug("Set /NeedAppearances on AcroForm")
    except Exception as e:
        logger.debug("Could not set NeedAppearances: %s", e)

    # Ensure AcroForm from reader is present (helps appearances)
    try:
        root = cast(Any, reader.trailer)["/Root"]
        acro = getattr(root, "get", lambda *_args, **_kwargs: None)("/AcroForm")
        if acro is not None and NameObject("/AcroForm") not in writer._root_object:  # type: ignore[attr-defined]
            writer._root_object[NameObject("/AcroForm")] = acro  # type: ignore[attr-defined]
            logger.debug("Ensured AcroForm present on writer")
    except Exception as e:
        logger.debug("Failed to ensure AcroForm resources: %s", e)

    with open(destination_path, "wb") as fp:
        writer.write(fp)
    logger.info("Saved AcroForm-filled PDF to %s (fields set: %d)", destination_path, len(field_values))

    # Clean up
    if buf is not None:
        buf.close()

    return destination_path


__all__ = ["fill_pdf_acroform"]

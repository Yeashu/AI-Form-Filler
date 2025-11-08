# Guidelines: `app.py` (Streamlit UI)

## Purpose
Provide a single-page Streamlit interface for uploading PDFs, reviewing detected fields, collecting user input, and downloading filled forms.

---

## Best Practices

### 1. Session State Management
- **Initialize defaults** in `_init_session_state()`:
  ```python
  defaults = {
      "parsed_form": None,
      "uploaded_filename": None,
      "answers": {},
      "filled_pdf_bytes": None,
      "filled_pdf_name": None,
  }
  ```
- Check if key exists before setting: `if key not in st.session_state`.

### 2. Reset State on New Upload
- Detect filename change to trigger fresh parsing:
  ```python
  if st.session_state.uploaded_filename != filename:
      # Clear cached data
  ```
- Prevents stale data from previous PDF.

### 3. One-Page Flow
- Upload → Parse → Display Fields → Collect Input → Fill → Download
- No tabs/navigation—keeps UX simple for MVP.

### 4. Form-Based Input
- Use `st.form()` to batch text inputs:
  ```python
  with st.form("field_input_form"):
      for field in parsed_form.fields:
          answers[field.label] = st.text_input(field.label)
      submitted = st.form_submit_button("Fill PDF")
  ```
- Prevents re-runs on every keystroke.

### 5. Conditional Rendering
- Show field inputs only after successful parsing.
- Show download button only after filling.
- Use early returns to avoid deeply nested if-blocks.

### 6. Output File Naming
- Include original filename stem + timestamp:
  ```python
  f"{stem}_filled_{timestamp}.pdf"
  ```
- Prevents overwrites in `output/` directory.

### 7. Error Handling
- Graceful degradation:
  ```python
  if not parsed_form.fields:
      st.warning("No fields detected. PDF may not match MVP constraints.")
      return
  ```
- Show user-friendly messages, not stack traces.

### 8. Download Management
- Store filled PDF bytes in session state for re-download.
- Use `st.download_button()` with proper MIME type.

---

## Common Pitfalls

❌ **Not using session state**: Streamlit re-runs entire script on interaction.  
❌ **Deeply nested conditionals**: Hard to read; use early returns.  
❌ **Missing file cleanup**: `output/` can grow indefinitely—consider cleanup task.  
❌ **Hardcoding paths**: Use `Path` objects for cross-platform compatibility.  
❌ **No loading indicators**: Users don't know if parsing/filling is in progress.

---

## UI/UX Improvements

### Current State
- Simple, functional MVP interface.
- Text inputs for all fields.

### Future Enhancements
- **Field preview**: Show PDF page snippet for each field.
- **Validation**: Required fields, format checking (email, phone).
- **Auto-save**: Persist answers to session storage.
- **Drag-and-drop**: More intuitive file upload.
- **Batch mode**: Upload multiple PDFs, apply same answers.
- **LLM chat**: Conversational interface instead of form.
- **Dark mode**: Respect user theme preference.

---

## Performance Considerations

### Current Limitations
- Entire PDF loaded into memory (OK for small forms).
- Re-parsing on every app re-run if not cached.

### Optimization Strategies
- **Caching**: Use `@st.cache_data` for parse results (careful with session state).
- **Streaming**: For large PDFs, process page-by-page.
- **Background tasks**: Long-running fills could use async workers.

---

## Testing Checklist

- [ ] Upload PDF and verify fields detected
- [ ] Fill all fields and download
- [ ] Fill partial fields (some empty)
- [ ] Re-upload same PDF (should re-parse)
- [ ] Upload different PDF (should clear state)
- [ ] Download button works on mobile
- [ ] Error message for unsupported PDF
- [ ] Session state persists across form submissions
- [ ] No crashes on malformed PDF

---

## Security Considerations

### Current MVP (Local Use Only)
- No authentication/authorization.
- All processing happens locally.
- No data persistence (PDFs not stored server-side).

### Future (Production Deployment)
- **File size limits**: Prevent DoS via huge uploads.
- **Input sanitization**: Validate field values.
- **HTTPS**: Encrypt PDF upload/download.
- **Rate limiting**: Prevent abuse.
- **Audit logging**: Track who filled which forms.
- **Encryption at rest**: For any stored PDFs.

---

## Streamlit-Specific Tips

### Layout
- Use `st.columns()` for side-by-side field inputs.
- Use `st.expander()` to hide advanced options.
- Set `layout="wide"` for more horizontal space.

### State Management
- Avoid storing large objects (PDFs) in session state long-term.
- Clear session state on logout/timeout.

### Performance
- Use `st.cache_data` for expensive computations.
- Avoid re-parsing PDF on every widget interaction.

### Deployment
- For production: Use Streamlit Cloud or Docker.
- Set environment variables for secrets (API keys).
- Use `.streamlit/config.toml` for app settings.

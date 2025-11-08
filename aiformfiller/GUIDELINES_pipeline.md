# Guidelines: `aiformfiller/pipeline.py`

## Purpose
High-level orchestration layer that combines parsing and filling operations into a simple API.

---

## Best Practices

### 1. Separation of Concerns
- **Parser**: Knows how to extract fields.
- **Filler**: Knows how to write text.
- **Pipeline**: Knows how to sequence these operations.
- Don't duplicate logic from parser/filler here.

### 2. Stateful Data Containers
- Use `ParsedForm` dataclass to bundle PDF bytes with extracted fields:
  ```python
  @dataclass
  class ParsedForm:
      pdf_bytes: bytes
      fields: list[DetectedField]
  ```
- Makes it easy to pass around partially-processed data.

### 3. Two-Phase Design
- **Phase 1**: `parse_pdf()` → Extract fields, keep PDF bytes.
- **Phase 2**: `fill_parsed_form()` → Apply answers, save output.
- This allows UI to show detected fields before asking for input.

### 4. Minimal Transformation
- Pipeline functions should be thin wrappers:
  ```python
  def parse_pdf(pdf_bytes: bytes) -> ParsedForm:
      fields = extract_fields(pdf_bytes)
      return ParsedForm(pdf_bytes=pdf_bytes, fields=fields)
  ```
- Heavy lifting stays in parser/filler.

### 5. Return Paths, Not Bytes
- `fill_parsed_form()` returns the destination path string.
- Caller decides whether to read/stream/delete the file.

### 6. Error Propagation
- Let exceptions bubble up from parser/filler.
- Pipeline doesn't add try/except (UI layer handles errors).
- Document expected exceptions in docstrings.

---

## Common Pitfalls

❌ **Logic duplication**: Don't reimplement parsing/filling here.  
❌ **Tight coupling**: Don't import Streamlit or UI libraries.  
❌ **Complex transformations**: Keep it simple; add new modules for complex workflows.  
❌ **Stateful instances**: Use functions, not classes with mutable state.

---

## When to Extend Pipeline

✅ **Good use cases**:
- Add `validate_form()` step between parse and fill.
- Create `preview_pdf()` to generate a visual diff.
- Implement `batch_fill()` for multiple PDFs with same schema.

❌ **Wrong place for**:
- LLM conversation logic (create `aiformfiller/llm.py`)
- Database persistence (create `aiformfiller/storage.py`)
- Authentication/authorization (belongs in app layer)

---

## API Design Principles

### Consistency
- All pipeline functions should have clear input/output contracts.
- Use type hints extensively.

### Composability
- Functions should be chainable:
  ```python
  path = fill_parsed_form(parse_pdf(pdf_bytes), answers, "out.pdf")
  ```

### Testability
- Pure functions are easy to test.
- No global state or side effects.

---

## Future Enhancements

- **Validation pipeline**: `parse → validate → fill`
- **Template support**: Save/load common form schemas.
- **Async support**: For batch processing large PDFs.
- **Streaming**: Process PDFs without loading entire file in memory.
- **Rollback**: Undo fill operation (save multiple versions).

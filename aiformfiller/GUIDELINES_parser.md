# Guidelines: `aiformfiller/parser.py`

## Purpose
Extract fillable field locations from PDF documents using PyMuPDF.

---

## Best Practices

### 1. Multi-Level Fallback Strategy
- **Span-level**: Preferred—precise bounding boxes for individual text runs.
- **Block-level**: Fallback when spans aren't structured (legacy PDFs).
- **Word-level geometry**: Used to locate underline tokens within blocks.

```python
fields = _collect_span_fields(doc)
if not fields:
    fields = _collect_block_fields(doc)
```

### 2. Robust Text Inspection
- Use regex patterns for structured fields: `Label: _____`
- Fallback to heuristics for unstructured layouts.
- Always strip whitespace before pattern matching.

### 3. Type Safety with PyMuPDF
- PyMuPDF returns `list | str | dict` from many methods.
- **Always validate types** before accessing:
  ```python
  raw_dict = page.get_text("rawdict")
  if not isinstance(raw_dict, dict):
      continue
  ```

### 4. Label Extraction Logic
- Primary: Regex match for `Label: ___` patterns.
- Secondary: Split on `:` if no regex match.
- Tertiary: Clean up underscores/dots and use as candidate.
- Always provide fallback: `f"Field {index}"`

### 5. Coordinate Precision
- Extract bounding boxes as floats: `tuple(float(x) for x in coords)`
- Validate bbox has exactly 4 elements before using.
- Store underline bbox, not label bbox, for accurate text placement.

### 6. Resource Management
- **Always** use try/finally to close documents:
  ```python
  doc = fitz.open(source)
  try:
      # ... extraction logic
  finally:
      doc.close()
  ```

### 7. Underline Detection
- Check for repeated `_` or `.` characters.
- Allow slight variations: `___`, `____`, `...`
- Use helper: `all(ch in {"_", "."} for ch in text)`

### 8. Word-Level Matching
- When falling back to block detection, scan word list for underline tokens.
- Match words to blocks using block index from word tuple.
- Select the **widest** underline word to avoid false positives on short dashes.

---

## Common Pitfalls

❌ **Not validating PyMuPDF return types**: Leads to runtime errors.  
❌ **Using block bbox for text insertion**: Fills at label position instead of underline.  
❌ **Forgetting to close documents**: Memory leaks in long-running processes.  
❌ **Case-sensitive pattern matching**: Use `.lower()` or case-insensitive regex.  
❌ **Hardcoding page iteration**: Use `range(doc.page_count)` for type safety.

---

## Testing Checklist

- [ ] PDFs with span-based text (modern digital forms)
- [ ] PDFs with block-only text (scanned/legacy)
- [ ] Fields with varying underline lengths
- [ ] Duplicate field labels (e.g., multiple "Name" fields)
- [ ] Unicode characters in labels
- [ ] Empty PDFs (should return empty list, not error)
- [ ] Malformed PDFs (should handle gracefully)

---

## Future Enhancements

- **OCR integration**: For scanned PDFs without extractable text.
- **ML-based field detection**: Use computer vision for complex layouts.
- **Multi-line field support**: Detect text areas, not just single lines.
- **Confidence scoring**: Return probability estimates for each field.
- **Custom pattern configuration**: Allow users to define field patterns via config.

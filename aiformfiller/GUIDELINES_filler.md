# Guidelines: `aiformfiller/filler.py`

## Purpose
Write user-provided text into PDF documents at precise coordinates.

---

## Best Practices

### 1. Coordinate System Understanding
- PyMuPDF uses **bottom-left origin** for some operations, **top-left** for text insertion.
- `bbox = (x0, y0, x1, y1)` where:
  - `(x0, y0)` = top-left corner
  - `(x1, y1)` = bottom-right corner

### 2. Text Positioning Strategy
- **Horizontal**: Add small padding from left edge to avoid overlap with label.
- **Vertical**: Place text baseline **above** the underline.
  ```python
  insertion_y = y1 - vertical_offset  # y1 is bottom of underline bbox
  insertion_point = (x0 + horizontal_padding, insertion_y)
  ```

### 3. Default Offset Tuning
- `vertical_offset = 3.0`: Positions text 3 points above underline.
- `horizontal_padding = 2.0`: Slight indent from left edge.
- **Adjust based on font size and PDF rendering**.

### 4. Font Selection
- MVP uses built-in default font (Helvetica-equivalent).
- For custom fonts:
  ```python
  page.insert_text(point, text, fontsize=11, fontname="helv")
  ```
- Future: Support TTF/OTF embedding.

### 5. Handle Missing Answers
- Skip fields where user provided no input:
  ```python
  value = answers.get(field.label) or answers.get(field.raw_label)
  if not value:
      continue
  ```
- This allows partial form completion.

### 6. Resource Management
- Same as parser: **always** close documents:
  ```python
  doc = fitz.open(source)
  try:
      # ... filling logic
      doc.save(destination_path)
  finally:
      doc.close()
  ```

### 7. Return Value Consistency
- Always return the destination path for easy chaining:
  ```python
  def fill_pdf(...) -> str:
      # ... fill logic
      doc.save(destination_path)
      return destination_path
  ```

### 8. Coordinate Validation
- Ensure bbox has valid dimensions before inserting:
  ```python
  x0, y0, x1, y1 = field.bbox
  if x1 <= x0 or y1 <= y0:
      continue  # Invalid bbox, skip
  ```

---

## Common Pitfalls

❌ **Using wrong bbox coordinate**: Using `y0` (top) instead of `y1` (bottom) for baseline.  
❌ **Hardcoded font sizes**: Makes text overflow on small fields—future work.  
❌ **Not handling empty answers**: Causes `None` to be written as text.  
❌ **Modifying source PDF**: Always save to a new path to preserve original.  
❌ **Ignoring page index**: Writing to page 0 when field is on page 5.

---

## Text Rendering Considerations

### Font Size
- Default: 11pt works for most forms.
- Future: Auto-scale based on underline length.

### Text Overflow
- Currently no clipping or wrapping.
- Long text will exceed underline boundaries.
- Future: Truncate or use smaller font dynamically.

### Special Characters
- PyMuPDF handles Unicode well, but some fonts don't.
- Test with diacritics, emojis, RTL text.

### Color
- Default: Black text.
- Future: Allow custom RGB via parameter:
  ```python
  page.insert_text(point, text, color=(0, 0, 1))  # Blue text
  ```

---

## Testing Checklist

- [ ] Text positioned correctly above underlines
- [ ] Multi-page PDFs (fields on different pages)
- [ ] Empty answers (should skip field gracefully)
- [ ] Long text (observe overflow behavior)
- [ ] Unicode characters (accented, CJK, emoji)
- [ ] Edge cases: x0 = x1 or y0 = y1 (invalid bbox)
- [ ] Duplicate labels (ensure correct field mapping)

---

## Future Enhancements

- **Auto font-size scaling**: Fit text within underline width.
- **Multi-line text**: Support text areas with wrapping.
- **Custom fonts**: Embed TTF/OTF for branding.
- **Text color/style**: Bold, italic, colored text.
- **Alignment options**: Left, center, right alignment within field.
- **Validation overlays**: Red box around fields with invalid input.

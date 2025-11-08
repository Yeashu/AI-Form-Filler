# Guidelines: `aiformfiller/models.py`

## Purpose
Define immutable data structures representing PDF form fields and related entities.

---

## Best Practices

### 1. Use Frozen Dataclasses
- **Why**: Immutability prevents accidental modification and makes data flow predictable.
- **Example**:
  ```python
  @dataclass(frozen=True)
  class DetectedField:
      page: int
      label: str
      bbox: BBox
      raw_label: str
  ```

### 2. Type Aliases for Clarity
- Define clear type aliases for complex tuples (e.g., `BBox`).
- Makes function signatures more readable.

### 3. Keep Models Simple
- No business logic in model classes.
- Use plain data containers with type hints.
- Avoid methods unless they're pure transformations.

### 4. Document Field Semantics
- Add docstrings explaining what each field represents.
- Example:
  ```python
  @dataclass(frozen=True)
  class DetectedField:
      """Representation of a detected field in a PDF page.
      
      Attributes:
          page: Zero-indexed page number.
          label: Unique user-facing label (may include disambiguation index).
          bbox: Bounding box (x0, y0, x1, y1) of the underline.
          raw_label: Original label before disambiguation.
      """
  ```

### 5. Versioning
- When adding fields, use optional/default values for backward compatibility.
- Example:
  ```python
  @dataclass(frozen=True)
  class DetectedField:
      page: int
      label: str
      bbox: BBox
      raw_label: str
      confidence: float = 1.0  # New field with default
  ```

---

## Common Pitfalls

❌ **Mutable defaults**: Never use `field(default_factory=list)` in frozen dataclasses.  
❌ **Business logic**: Don't add methods that modify state or perform I/O.  
❌ **Tight coupling**: Models should not import parser/filler modules.

---

## Future Considerations

- Add `FieldType` enum when supporting checkboxes/radio buttons.
- Include `confidence` scores for ML-based detection.
- Store `font_size` hints for better rendering.

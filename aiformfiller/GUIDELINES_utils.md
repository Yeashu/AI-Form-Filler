# Guidelines: `aiformfiller/utils.py`

## Purpose
Provide reusable helper functions that don't fit into parser/filler (e.g., label disambiguation).

---

## Best Practices

### 1. Single Responsibility
- Each utility function should do **one thing well**.
- Example: `assign_unique_labels` only handles disambiguation, nothing else.

### 2. Pure Functions Preferred
- Avoid side effects (I/O, global state).
- Take input, return output, don't modify arguments.
- Use `dataclasses.replace()` for immutable updates:
  ```python
  unique_fields.append(replace(field, label=new_label))
  ```

### 3. Label Disambiguation Algorithm
- Count total occurrences of each raw label.
- Track running count as we iterate.
- Only append index if `total_count > 1`:
  ```python
  if occurrences > 1:
      label = f"{field.raw_label} ({running_counts[field.raw_label]})"
  ```

### 4. Preserve Order
- Maintain field order from parser (top-to-bottom in PDF).
- Use list comprehension or explicit append, not dict-based reordering.

### 5. Type Hints
- Always annotate input/output types:
  ```python
  def assign_unique_labels(fields: Iterable[DetectedField]) -> List[DetectedField]:
  ```

### 6. Document Edge Cases
- What happens with zero fields? (Returns empty list)
- What about single occurrence? (No index appended)
- Unicode labels? (Works seamlessly with f-strings)

---

## Common Pitfalls

❌ **Mutating input**: Don't modify the `fields` iterable in place.  
❌ **Losing field order**: Using sets/dicts can scramble ordering.  
❌ **Off-by-one indexing**: Start counting at 1 for user-facing indices.  
❌ **Not handling empty input**: Should gracefully return `[]`.

---

## When to Add New Utilities

✅ **Good candidates**:
- Field sorting/filtering logic
- Bbox manipulation (merge, intersect, etc.)
- String sanitization for labels
- Format converters (e.g., field list → JSON schema)

❌ **Avoid**:
- PDF I/O operations (belongs in parser/filler)
- UI-specific logic (belongs in app.py)
- Complex business logic (consider a new module)

---

## Testing Checklist

- [ ] Single field (no disambiguation)
- [ ] Multiple unique fields (no disambiguation)
- [ ] Duplicate labels (should append indices)
- [ ] Triple+ duplicates (indices 1, 2, 3...)
- [ ] Empty input (should return `[]`)
- [ ] Unicode/emoji labels (should work)
- [ ] Very long labels (no truncation, just append index)

---

## Future Enhancements

- **Smart label normalization**: "Name", "name", "NAME" → same base label.
- **Bbox utilities**: Intersection, containment checks for nested fields.
- **Field sorting**: Sort by page, then top-to-bottom, left-to-right.
- **Export helpers**: Convert field list to JSON/CSV for debugging.

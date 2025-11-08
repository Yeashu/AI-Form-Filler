# AI Form Filler — Project Guidelines & Best Practices

> Comprehensive guide for maintaining, extending, and collaborating on the AI Form Filler project. Read this before making significant changes or adding new features.

---

## 📐 Architecture Principles

### 1. Modularity
- **Package structure**: Core logic lives in `aiformfiller/` package.
- **UI separation**: Streamlit app (`app.py`) is a thin client over the package.
- **Single Responsibility**: Each module has one clear purpose.

```
aiformfiller/
├── models.py      → Data structures (immutable)
├── parser.py      → PDF field extraction (read-only)
├── filler.py      → PDF text insertion (write-only)
├── utils.py       → Helpers (pure functions)
└── pipeline.py    → Orchestration (stateless)
```

### 2. Separation of Concerns
- **Parser** knows nothing about filling.
- **Filler** knows nothing about parsing.
- **Pipeline** coordinates but doesn't duplicate logic.
- **UI** consumes pipeline API without business logic.

### 3. Immutability & Purity
- Use `@dataclass(frozen=True)` for models.
- Prefer pure functions (no side effects).
- Use `replace()` for "updates" to immutable objects.

### 4. Explicit Over Implicit
- Type hints everywhere.
- No magic constants—use named parameters.
- Document assumptions in comments/docstrings.

---

## 🛠️ Development Workflow

### Environment Setup
1. **Python 3.10+** required (uses modern type hints).
2. **Virtual environment**: Always use `venv/` for isolation.
3. **Dependencies**: Keep `requirements.txt` minimal and pinned.

```fish
# Setup
python3.10 -m venv venv
source venv/bin/activate.fish
pip install -r requirements.txt

# Run
streamlit run app.py
```

### Git Workflow
- **Main branch**: Stable, tested code only.
- **Feature branches**: `feature/llm-integration`, `fix/alignment-issue`.
- **Commit messages**: Descriptive and concise.
- **`.gitignore`**: Exclude `venv/`, `output/`, `__pycache__/`, `.env`.

### Code Style
- **PEP 8**: Standard Python style guide.
- **Line length**: 120 chars (adjust in formatter config).
- **Imports**: Group stdlib, third-party, local—sorted alphabetically.
- **Type hints**: Use for all function signatures.

---

## 🧪 Testing Strategy

### Unit Tests (Future)
- Test each module independently.
- Mock PyMuPDF for parser tests.
- Use fixtures for sample PDFs.

```python
# Example: test_parser.py
def test_extract_fields_with_underlines():
    fields = extract_fields("tests/fixtures/sample_form.pdf")
    assert len(fields) == 3
    assert fields[0].label == "Name"
```

### Integration Tests
- Full pipeline: `parse → fill → validate output`.
- Use real PDFs from `tests/fixtures/`.
- Check that filled text appears in correct locations.

### Manual Testing Checklist
- [ ] PDFs with 1 field
- [ ] PDFs with 10+ fields
- [ ] Duplicate field labels
- [ ] Unicode in labels/values
- [ ] Multi-page PDFs
- [ ] Scanned PDFs (should fail gracefully)

---

## 🚀 Adding New Features

### Before You Start
1. **Read relevant guidelines**: Check module-specific `GUIDELINES_*.md`.
2. **Search codebase**: Use `grep` to find similar patterns.
3. **Update documentation**: Add to README if user-facing.

### Feature Development Checklist
- [ ] Create feature branch from `main`.
- [ ] Implement in appropriate module (or create new one).
- [ ] Add type hints and docstrings.
- [ ] Update `__all__` exports if needed.
- [ ] Test manually with sample PDFs.
- [ ] Update relevant `GUIDELINES_*.md`.
- [ ] Commit with clear message.
- [ ] Merge into `main` when stable.

### Common Additions

#### New Field Type (e.g., Checkboxes)
1. Add to `models.py`: Extend `DetectedField` or create new class.
2. Update `parser.py`: Add detection logic.
3. Update `filler.py`: Add rendering logic.
4. Update `app.py`: Handle in UI (dropdown instead of text input).

#### LLM Integration
1. Create `aiformfiller/llm.py` for conversation logic.
2. Update `pipeline.py`: Add `collect_answers_with_llm()`.
3. Update `app.py`: Switch from form to chat interface.
4. Add API key management (environment variables).

#### OCR Support
1. Add `pytesseract` to `requirements.txt`.
2. Create `aiformfiller/ocr.py` for scanned PDF handling.
3. Update `parser.py`: Fallback to OCR when text extraction fails.

---

## 🐛 Debugging Tips

### Common Issues

#### "No fields detected"
- **Check PDF text layer**: `pdftotext file.pdf -` (should show underscores).
- **Inspect patterns**: Does it use `___` or different characters?
- **Enable debug logging**: Add `print()` statements in `_collect_block_fields()`.

#### "Text positioned incorrectly"
- **Check bbox coordinates**: Print `field.bbox` values.
- **Adjust offsets**: Modify `vertical_offset` in `filler.py` (default: 3.0).
- **Inspect PDF rendering**: Open filled PDF in multiple viewers (some render differently).

#### "Streamlit won't start"
- **Check Python version**: Must be 3.10+.
- **Reinstall dependencies**: `pip install --force-reinstall -r requirements.txt`.
- **Clear cache**: `rm -rf ~/.streamlit/cache`.

### Debug Mode
Add environment variable for verbose logging (future):
```python
import os
DEBUG = os.getenv("AIFORMFILLER_DEBUG", "false").lower() == "true"

if DEBUG:
    print(f"Detected {len(fields)} fields: {[f.label for f in fields]}")
```

---

## 📦 Deployment Considerations

### Local Use (Current)
- Run with `streamlit run app.py`.
- Access at `http://localhost:8501`.

### Cloud Deployment (Future)
- **Streamlit Cloud**: Push to GitHub, connect repo.
- **Docker**: Create `Dockerfile` for containerization.
- **Heroku/Railway**: Similar to Streamlit Cloud.

### Environment Variables
```bash
# .env (gitignored)
OPENAI_API_KEY=sk-...
MAX_UPLOAD_SIZE_MB=10
OUTPUT_DIR=/tmp/aiformfiller/output
```

Load with `python-dotenv`:
```python
from dotenv import load_dotenv
load_dotenv()
```

---

## 🔐 Security Best Practices

### Current MVP (Low Risk)
- No server-side storage of PDFs.
- No external API calls.
- Local processing only.

### Production Hardening
1. **Input validation**: Reject non-PDF files, oversized uploads.
2. **Sandboxing**: Run PDF processing in isolated environment.
3. **Rate limiting**: Prevent abuse via repeated uploads.
4. **Encryption**: HTTPS for all traffic, encrypt stored PDFs.
5. **Audit logging**: Track all form fills with timestamps.

---

## 📚 Documentation Standards

### Code Comments
- **Why, not what**: Explain reasoning, not obvious syntax.
- **Edge cases**: Document assumptions and limitations.
- **TODOs**: Use `# TODO:` for future improvements.

### Docstrings
- Use **Google style** for consistency:
  ```python
  def fill_pdf(source: PdfSource, destination: str) -> str:
      """Fill PDF with user answers.
      
      Args:
          source: Path to PDF or bytes.
          destination: Where to save filled PDF.
          
      Returns:
          Path to the saved PDF.
          
      Raises:
          ValueError: If source is not a valid PDF.
      """
  ```

### README Updates
- User-facing features → `README.md`.
- Developer guidelines → `GUIDELINES_*.md`.
- API changes → Update docstrings + guidelines.

---

## 🤝 Collaboration Guidelines

### For Contributors
1. **Read this doc first**: Understand architecture before coding.
2. **Ask questions**: Open GitHub issue for clarification.
3. **Small PRs**: Easier to review incremental changes.
4. **Test locally**: Don't push broken code.

### For Maintainers
1. **Review guidelines too**: Ensure consistency.
2. **Provide feedback**: Be constructive, suggest improvements.
3. **Update docs**: Keep guidelines in sync with code.

---

## 🎯 Future Roadmap

### Phase 1: MVP (Current) ✅
- Underline-based field detection
- Simple form-based UI
- Local PDF processing

### Phase 2: Enhanced Detection
- Checkbox/radio button support
- OCR for scanned PDFs
- Multi-line text areas

### Phase 3: LLM Integration
- Conversational field collection
- Smart defaults (e.g., infer address from context)
- Validation suggestions

### Phase 4: Production Ready
- Authentication/authorization
- Database persistence (form templates)
- Batch processing API
- Audit logging

### Phase 5: Advanced Features
- Multi-language support
- Custom branding (fonts, colors)
- Export to other formats (JSON, CSV)
- Mobile app (React Native + API)

---

## 📖 Additional Resources

### PyMuPDF Documentation
- [Official Docs](https://pymupdf.readthedocs.io/)
- [Text Extraction Guide](https://pymupdf.readthedocs.io/en/latest/textpage.html)
- [Coordinate System](https://pymupdf.readthedocs.io/en/latest/faq.html#extracting-text)

### Streamlit Resources
- [API Reference](https://docs.streamlit.io/library/api-reference)
- [Session State Guide](https://docs.streamlit.io/library/advanced-features/session-state)
- [Deployment](https://docs.streamlit.io/streamlit-cloud)

### Python Best Practices
- [PEP 8 Style Guide](https://peps.python.org/pep-0008/)
- [Type Hints Cheat Sheet](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html)
- [Dataclasses Guide](https://realpython.com/python-data-classes/)

---

## 🆘 Getting Help

- **Issues**: Open GitHub issue with details.
- **Questions**: Start a discussion in GitHub Discussions.
- **Bugs**: Include sample PDF (if sharable) and error logs.

---

**Happy coding! 🚀**

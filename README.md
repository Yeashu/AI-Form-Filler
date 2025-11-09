# AI Form Filler MVP

> Take a **clean digital PDF form**, parse it to detect **fillable areas**, ask the user for info through a conversational LLM chat, and **fill those areas** (for now: only normal underline-based text fields like `Name: ___________`).

---

## 📁 Project Structure

```
AIFormFiller/
├── aiformfiller/          # Legacy underline-based pipeline (still available)
│   ├── __init__.py        # Package exports
│   ├── models.py          # PDF underline field data model
│   ├── parser.py          # Underline-based PDF field extraction
│   ├── filler.py          # Coordinate-based PDF filling utilities
│   ├── utils.py           # Helper functions (label disambiguation)
│   ├── pipeline.py        # Legacy orchestration (parse + fill + chat)
│   └── llm.py             # Gemini-powered conversational engine (shared)
├── services/              # HTML-based extraction + filling services
│   ├── html_extractor.py  # PDF → HTML conversion (pdfplumber)
│   ├── field_detector.py  # HTML field detection (BeautifulSoup)
│   ├── html_filler.py     # HTML filling + WeasyPrint PDF generation
│   ├── pipeline.py        # High-level HTML orchestration helpers
│   └── __init__.py        # Service exports
├── models/                # Shared data models (conversation state, etc.)
│   ├── conversation_state.py
│   └── __init__.py
├── app.py                 # Streamlit UI (one-page flow)
├── output/                # Generated filled PDFs (gitignored)
├── requirements.txt       # Python dependencies
├── venv/                  # Virtual environment (gitignored)
└── README.md              # This file
```

---

## 🚀 Quick Start

1. **Activate the virtual environment:**
   ```fish
   source venv/bin/activate.fish
   ```

2. **Install dependencies (if not already done):**
   ```fish
   pip install -r requirements.txt
   ```

3. **Configure your environment variables:**
   ```fish
   cp .env.example .env   # edit GOOGLE_API_KEY with your Gemini key
   ```

4. **Run the Streamlit app:**
   ```fish
   streamlit run app.py
   ```

5. **Upload a PDF** with underline-based fields (e.g., `Name: ___________`). Choose **Form Mode** for manual entry or **Chat Mode** to collect answers via Gemini, then download the completed form.

---

## 🧩 Pipeline Overview

```
PDF Upload → Persist temp copy → PDF → HTML (pdfplumber) → HTML Field Detection (BeautifulSoup)
→ (Manual Form ⬅ or ➡ LLM Chat) → HTML Fill + PDF render (WeasyPrint) → Download
```

### Key Components

1. **HTML Extractor** (`services/html_extractor.py`)
   - Opens PDFs with pdfplumber
   - Collects AcroForm metadata when available
   - Generates an HTML `<form>` skeleton for downstream processing

2. **Field Detector** (`services/field_detector.py`)
   - Parses HTML via BeautifulSoup
   - Normalises `<input>`, `<select>`, and `<textarea>` controls into `DetectedField`
   - Supports label lookups and metadata enrichment

3. **HTML Filler** (`services/html_filler.py`)
   - Injects collected answers into the HTML template
   - Renders final PDFs using WeasyPrint while preserving structure

4. **HTML Pipeline** (`services/pipeline.py`)
   - Coordinates extraction, conversation initialisation, filling, and preview generation
   - Returns `FormExtractionResult` objects consumed by the UI

5. **LLM Conversation Layer** (`aiformfiller/llm.py` + `models/conversation_state.py`)
   - Shared between underline and HTML flows
   - Sequential question/answer loop with optional Gemini validation

6. **Streamlit UI** (`app.py`)
   - Drives the new HTML pipeline
   - Provides manual form and AI chat modes
   - Manages session state (uploaded path, filled HTML/PDF, conversation history)

---

## 🧠 MVP Limitations

- Only detects `_____` or `......` style fields
- No handwriting boxes, checkboxes, or OCR
- No multilingual layout understanding
- Requires Google Gemini API key for chat mode (manual form mode works offline)

---

## ✅ Success Criteria

- [x] Upload a clean PDF form
- [x] Detect labeled fields automatically
- [x] Collect info from user via simple form inputs or conversational chat
- [x] Insert responses at correct locations (above underlines)
- [x] Download filled PDF
- [x] Disambiguate duplicate field labels by index

---

## 🔧 Development Guidelines

See individual `GUIDELINES.md` files in each module for detailed best practices.

### General Principles

1. **Modularity**: Keep parsing, filling, and UI concerns separate
2. **Type Safety**: Use type hints and dataclasses where possible
3. **Fallback Logic**: Implement graceful degradation (span → block → word level)
4. **Error Handling**: Always close PyMuPDF documents in try/finally blocks
5. **User Experience**: Provide clear feedback when fields aren't detected

---

## 🐛 Troubleshooting

**No fields detected?**
- Confirm the PDF exposes interactive fields (AcroForm) or embed clean text elements
- Scanned/image-only PDFs currently fall back to plain text but yield no form controls
- Try downloading the original digital copy rather than a scanned printout

**Output PDF formatting off?**
- Ensure WeasyPrint native dependencies (Pango, Cairo) are installed on your system
- Validate the HTML produced by `services/html_extractor.py` to confirm structure
- Custom fonts may require additional CSS in the HTML template

**Dependencies not installing?**
- Ensure you're using Python 3.10+
- Activate the venv before running pip install

---

## 📝 Future Enhancements

- [ ] Support for checkboxes and radio buttons
- [ ] OCR for scanned/image-based PDFs
- [ ] Multi-page form navigation
- [ ] Custom font selection
- [ ] Field validation and auto-completion
- [ ] Export to multiple formats (JSON, CSV)

---

## 📜 License

MIT (or your preferred license)

# AI Form Filler MVP

> Take a **clean digital PDF form**, parse it to detect **fillable areas**, ask the user for info through a conversational LLM chat, and **fill those areas** (for now: only normal underline-based text fields like `Name: ___________`).

---

## 📁 Project Structure

```
AIFormFiller/
├── aiformfiller/          # Core package (modular components)
│   ├── __init__.py        # Package exports
│   ├── models.py          # Data models (DetectedField)
│   ├── parser.py          # PDF field extraction logic
│   ├── filler.py          # PDF filling utilities
│   ├── utils.py           # Helper functions (label disambiguation)
│   ├── pipeline.py        # High-level orchestration (parse + fill + chat)
│   └── llm.py             # Gemini-powered conversational engine
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
PDF Upload → Parse (PyMuPDF) → Field Extraction → (Manual Form ⬅ or ➡ LLM Chat) → Fill PDF → Download
```

### Key Components

1. **Parser** (`aiformfiller/parser.py`)
   - Extracts text blocks and spans using PyMuPDF
   - Detects underline-based fields via pattern matching
   - Falls back to word-level geometry when span detection fails

2. **Filler** (`aiformfiller/filler.py`)
   - Inserts user-provided text at precise coordinates
   - Positions text above underlines using bbox data

3. **Pipeline** (`aiformfiller/pipeline.py`)
   - Orchestrates parsing and filling operations
   - Manages PDF bytes and field mappings

4. **LLM Conversation Layer** (`aiformfiller/llm.py` + `collect_answers_with_llm`)
   - Sequential question/answer flow for each detected field
   - Configurable Gemini prompts and optional validation
   - Pure helper functions for easy testing

5. **Streamlit UI** (`app.py`)
   - Single-page flow for upload, input, and download
   - Mode selector for Form vs Chat input
   - Session state management for multi-step interaction

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
- Ensure your PDF has text blocks with `___` or `...` patterns
- Check that fields follow the format: `Label: ___________`
- Try PDFs with at least 3 consecutive underscores

**Text alignment issues?**
- Adjust `vertical_offset` and `horizontal_padding` in `filler.py`
- Default: 3px above underline, 2px horizontal padding

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

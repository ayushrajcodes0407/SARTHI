# Contributing to SARTHI

Thank you for your interest in contributing to **SARTHI — AI-Powered Business Intelligence Assistant**.

SARTHI is a locally hosted, privacy-first business intelligence assistant engineered with Python, Flask, SQLite, and local Ollama LLMs. We welcome community contributions that uphold high code quality, deterministic calculations, and zero data leakage.

---

## Code of Conduct & Core Principles

1. **Local Privacy Guarantee**: SARTHI runs 100% locally on loopback (`127.0.0.1`). Contributions must never introduce telemetry or dependencies on external cloud AI APIs (OpenAI, Anthropic, Gemini, etc.).
2. **Deterministic Financial Math**: AI models in SARTHI are utilized strictly for natural language query understanding and translation to structured parameters. Calculations (margins, stock counts, aggregations) must be performed deterministically via SQLite and pandas.
3. **Comprehensive Automated Testing**: All PRs must include automated unit/regression tests in `test_all.py`. Existing tests must remain passing.

---

## Development Workflow

### 1. Prerequisites
- Python 3.10+
- Git
- Ollama with `qwen3:4b-instruct` model installed (`ollama pull qwen3:4b-instruct`)

### 2. Fork and Clone
```bash
git clone https://github.com/ayushrajcodes0407/SARTHI.git
cd SARTHI
```

### 3. Create a Virtual Environment
```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Running the Application Locally
```bash
python app.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

### 6. Running Tests
Run the comprehensive regression and integration test suite:
```bash
python -m unittest test_all.py
```

---

## Submitting Pull Requests

1. **Create a topic branch**: `git checkout -b feature/your-feature-name`
2. **Follow code style**: Keep functions modular, documented with docstrings, and type-hinted.
3. **Commit with conventional messages**:
   - `feat:` for new capabilities
   - `fix:` for bug fixes
   - `refactor:` for code structural improvements
   - `docs:` for documentation updates
   - `test:` for test additions or updates
4. **Push and open a PR** against `main`. Provide a clear summary of your changes, screenshots for UI modifications, and test execution results.

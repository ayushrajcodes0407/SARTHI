# Changelog - SARTHI\n\n## [1.0.0] - 2026-10-31\n### Initial Release of SARTHI\n- Initialized independent repository for SARTHI ([https://github.com/ayushrajcodes0407/SARTHI.git](https://github.com/ayushrajcodes0407/SARTHI.git)).\n- Established full on-premise business intelligence architecture from proven VANTIQ foundation.\n- Local Ollama/Qwen neural core integration, SQLite relational ledger, multi-turn conversational engine, and Excel/CSV/PDF document ingestion.\n\n---\n\n# Changelog

All notable changes to **VANTIQ: AI-Powered Business Intelligence Assistant** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-21

### Major Release: VANTIQ AI-Powered Business Intelligence Assistant

#### Added
- **Local AI Neural Core (Ollama Integration)**:
  - Loopback integration with local Ollama daemon at `http://127.0.0.1:11434`.
  - Configured model: `qwen3:4b-instruct` for offline natural language intent parsing.
  - Zero cloud AI dependency, zero external API keys, 100% loopback privacy guarantee.
  - Natural language multilingual explanation engine with built-in conceptual definitions (English, Hindi, French, Spanish).
  - Resilient automatic fallback to deterministic pattern recognition when Ollama is offline or cold starting.
- **Product Catalogue & Inventory Ledger**:
  - Full CRUD operations with SQLite persistence and schema migrations.
  - SKU validation, active status toggling, and opening stock movements.
  - Immutable stock protection: direct inventory balances cannot be overwritten via metadata edits; all changes track through audit movements.
  - Low stock and out-of-stock threshold alerts with telemetry cards.
  - Spreadsheet dataset import with automated column mapping, preview, and deduplication policies (`skip_existing`, `update_permitted_fields`).
- **Dataset Intelligence & Analytics**:
  - Multi-sheet Excel (.xlsx, .xls) and PDF table ingestion with structure detection.
  - Automatic column classification (numeric, categorical, datetime, text).
  - Business insights engine calculating revenue, profit margins, sales trends, missing values, duplicates, and anomaly alerts.
  - Natural language querying across live and persisted datasets.
- **VANTIQ Neural HUD & Web Dashboard**:
  - Dark/cyan cyber-hud UI with telemetry metrics (CPU, RAM, DB Status, Ollama Health, Response Latency).
  - Real-time product search, filtering, inventory summary chips, and active data visualization.
  - Interactive speech recognition voice assistant with audio feedback and speech synthesizer.
  - Dedicated Local AI Core telemetry card with dynamic pulsing health indicator and latency tracker.
- **Test Suite**:
  - Comprehensive automated test suite (`test_all.py`) spanning 99 test cases covering regression, dataset intelligence, catalogue operations, and local LLM accuracy.

#### Changed
- Rebranded entire project from legacy J.A.R.V.I.S. prototype to **VANTIQ — AI-Powered Business Intelligence Assistant**.
- Standardized UI headers, welcome audio greetings, terminal feedback, and API metadata to VANTIQ.
- Upgraded `.gitignore`, `requirements.txt`, and added `.env.example` with loopback defaults.

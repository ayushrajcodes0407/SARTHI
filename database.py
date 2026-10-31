"""
VANTIQ: AI-Powered Business Intelligence Assistant — Persistent Database Module
File: database.py
Description:
    Provides production-grade SQLite local persistence for VANTIQ:
    - Versioned schema migrations
    - Datasets, worksheets, structured records, analysis runs, and report storage
    - SHA-256 deduplication
    - Safe JSON serialization (handling NaNs, Timestamps, Infinities)
    - Cascade foreign key enforcement
    - Atomic transactional operations
    - SQLite online backup & restore
"""

import os
import sqlite3
import json
import uuid
import time
import datetime
import hashlib
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("VANTIQ-Database")

# Configurable database path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DEFAULT_DB_PATH = os.path.join(DEFAULT_INSTANCE_DIR, "vantiq_business.db" if os.path.exists(os.path.join(DEFAULT_INSTANCE_DIR, "vantiq_business.db")) or not os.path.exists(os.path.join(DEFAULT_INSTANCE_DIR, "jarvis_business.db")) else "jarvis_business.db")

MAX_STORED_ROWS_PER_DATASET = int(os.environ.get("VANTIQ_MAX_STORED_ROWS", os.environ.get("JARVIS_MAX_STORED_ROWS", "50000")))
CURRENT_SCHEMA_VERSION = 3
ANALYSIS_ENGINE_VERSION = "v1.0.0"

def get_db_path() -> str:
    """Returns the absolute path to the configured SQLite database file."""
    if os.environ.get("VERCEL"):
        return os.environ.get("VANTIQ_DB_PATH", os.environ.get("JARVIS_DB_PATH", "/tmp/vantiq_business.db"))
    return os.environ.get("VANTIQ_DB_PATH", os.environ.get("JARVIS_DB_PATH", DEFAULT_DB_PATH))

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Creates and returns a SQLite connection configured with:
    - Foreign key constraints enabled
    - Row factory enabled for dictionary-style access
    - Timeout for concurrency resilience
    """
    path = db_path or get_db_path()
    parent_dir = os.path.dirname(path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(path, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn

# ==============================================================================
# SAFE JSON SERIALIZER
# ==============================================================================

def safe_json_default(obj):
    """Custom JSON serializer for objects not serializable by default json code."""
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    if hasattr(obj, 'tolist'):
        return obj.tolist()
    if hasattr(obj, 'item'):
        return obj.item()
    return str(obj)

def safe_json_dumps(data: Any) -> str:
    """Safely dumps data to JSON string, replacing NaN/Inf with None."""
    def clean(val):
        if val is None:
            return None
        if isinstance(val, float):
            import math
            if math.isnan(val) or math.isinf(val):
                return None
            return val
        if isinstance(val, dict):
            return {k: clean(v) for k, v in val.items()}
        if isinstance(val, (list, tuple)):
            return [clean(v) for v in val]
        return val

    cleaned_data = clean(data)
    return json.dumps(cleaned_data, default=safe_json_default, ensure_ascii=False)

def safe_json_loads(json_str: Optional[str], default_val=None) -> Any:
    """Safely parses JSON string with fallback."""
    if not json_str:
        return default_val
    try:
        return json.loads(json_str)
    except Exception as e:
        logger.warning(f"Error parsing JSON: {e}")
        return default_val

# ==============================================================================
# SCHEMA MIGRATIONS
# ==============================================================================

MIGRATION_V1_SQL = """
-- Versioned Migrations Table
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Datasets Table
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    file_hash_sha256 TEXT NOT NULL,
    dataset_type TEXT NOT NULL,
    source_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    sheet_count INTEGER,
    page_count INTEGER,
    row_count INTEGER,
    column_count INTEGER,
    extraction_summary_json TEXT,
    analysis_status TEXT NOT NULL DEFAULT 'none',
    last_analyzed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_datasets_hash ON datasets(file_hash_sha256);
CREATE INDEX IF NOT EXISTS idx_datasets_created ON datasets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_datasets_type ON datasets(file_type);

-- Dataset Sheets Table (for Excel Worksheets)
CREATE TABLE IF NOT EXISTS dataset_sheets (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    sheet_index INTEGER NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    column_count INTEGER NOT NULL DEFAULT 0,
    columns_json TEXT,
    preview_json TEXT,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sheets_dataset ON dataset_sheets(dataset_id);

-- Dataset Records Table (Structured Rows)
CREATE TABLE IF NOT EXISTS dataset_records (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    sheet_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
    FOREIGN KEY(sheet_id) REFERENCES dataset_sheets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_records_lookup ON dataset_records(dataset_id, sheet_id, row_index);

-- Analysis Runs Table
CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    analysis_status TEXT NOT NULL,
    metrics_json TEXT,
    insights_json TEXT,
    quality_report_json TEXT,
    warnings_json TEXT,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_dataset ON analysis_runs(dataset_id, created_at DESC);

-- Reports Table
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    analysis_run_id TEXT NOT NULL,
    report_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    report_format TEXT NOT NULL DEFAULT 'json',
    report_content_json TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
    FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reports_dataset ON reports(dataset_id, created_at DESC);
"""

MIGRATION_V2_SQL = """
-- Suppliers Table
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);

-- Products Table
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    brand TEXT,
    unit TEXT DEFAULT 'piece',
    supplier_id INTEGER,
    purchase_price REAL DEFAULT 0.0 CHECK(purchase_price >= 0),
    selling_price REAL DEFAULT 0.0 CHECK(selling_price >= 0),
    currency TEXT DEFAULT 'INR',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_dataset_id TEXT,
    FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
    FOREIGN KEY(source_dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active);

-- Inventory Table (one balance per product)
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL UNIQUE,
    quantity_on_hand REAL NOT NULL DEFAULT 0.0 CHECK(quantity_on_hand >= 0),
    reorder_level REAL NOT NULL DEFAULT 0.0 CHECK(reorder_level >= 0),
    unit TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory(product_id);

-- Inventory Movements Table
CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL,
    quantity_delta REAL NOT NULL,
    quantity_before REAL NOT NULL,
    quantity_after REAL NOT NULL,
    reason TEXT NOT NULL,
    reference TEXT,
    created_at TEXT NOT NULL,
    source_dataset_id TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY(source_dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_movements_product ON inventory_movements(product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_movements_type ON inventory_movements(movement_type);
"""

MIGRATION_V3_SQL = """
-- Partial Unique Index on SKU (allows multiple NULL or empty SKUs, but unique when provided)
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku_unique 
    ON products(sku) 
    WHERE sku IS NOT NULL AND TRIM(sku) != '';

-- Purchases Ledger Table (Procurement transactions with supplier, rate, and provenance)
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_number TEXT,
    purchase_date TEXT NOT NULL,
    supplier_id INTEGER,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    total_amount REAL NOT NULL CHECK(total_amount >= 0),
    currency TEXT NOT NULL DEFAULT 'INR',
    notes TEXT,
    created_at TEXT NOT NULL,
    source_dataset_id TEXT,
    FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY(source_dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_purchases_product ON purchases(product_id);
CREATE INDEX IF NOT EXISTS idx_purchases_supplier ON purchases(supplier_id);
CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(purchase_date);
CREATE INDEX IF NOT EXISTS idx_purchases_number ON purchases(purchase_number);
CREATE INDEX IF NOT EXISTS idx_purchases_source ON purchases(source_dataset_id);

-- Sales Ledger Table (Customer sales transactions with unit price and provenance)
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT,
    sale_date TEXT NOT NULL,
    product_id INTEGER NOT NULL,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    total_amount REAL NOT NULL CHECK(total_amount >= 0),
    currency TEXT NOT NULL DEFAULT 'INR',
    customer_name TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    source_dataset_id TEXT,
    FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY(source_dataset_id) REFERENCES datasets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_product ON sales(product_id);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_invoice ON sales(invoice_number);
CREATE INDEX IF NOT EXISTS idx_sales_source ON sales(source_dataset_id);
"""

RAG_SCHEMA_SQL = """
-- Migration V4: Document Indexes and Document Chunks for Local RAG
CREATE TABLE IF NOT EXISTS document_indexes (
    dataset_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    embedding_provider TEXT NOT NULL DEFAULT 'sklearn_tfidf_cosine',
    indexed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_doc_indexes_status ON document_indexes(status);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    document_name TEXT NOT NULL,
    document_type TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    page_number INTEGER,
    sheet_name TEXT,
    row_range TEXT,
    source_hash TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    token_count INTEGER NOT NULL,
    embedding_json TEXT,
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_dataset ON document_chunks(dataset_id);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON document_chunks(source_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_name ON document_chunks(document_name);
"""

def init_db(db_path: Optional[str] = None) -> None:
    """
    Initializes the database schema if not already present.
    Safe to execute multiple times (idempotent).
    """
    conn = get_connection(db_path)
    try:
        with conn:
            # Check current version
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
            has_table = cursor.fetchone() is not None

            current_version = 0
            if has_table:
                cursor.execute("SELECT MAX(version) FROM schema_migrations")
                row = cursor.fetchone()
                if row and row[0] is not None:
                    current_version = row[0]

            if current_version < 1:
                logger.info("Applying database migration V1...")
                conn.executescript(MIGRATION_V1_SQL)
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (1, now_str)
                )
                logger.info("Database migration V1 applied successfully.")

            if current_version < 2:
                logger.info("Applying database migration V2 (Catalogue & Inventory)...")
                conn.executescript(MIGRATION_V2_SQL)
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (2, now_str)
                )
                logger.info("Database migration V2 applied successfully.")

            if current_version < 3:
                logger.info("Applying database migration V3 (Purchases, Sales & Enhanced Pricing/Provenance)...")
                cursor.execute("PRAGMA table_info(products)")
                existing_cols = {r["name"] for r in cursor.fetchall()}
                if "last_purchase_rate" not in existing_cols:
                    conn.execute("ALTER TABLE products ADD COLUMN last_purchase_rate REAL DEFAULT NULL")
                if "last_purchase_date" not in existing_cols:
                    conn.execute("ALTER TABLE products ADD COLUMN last_purchase_date TEXT DEFAULT NULL")

                conn.executescript(MIGRATION_V3_SQL)
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (3, now_str)
                )
                logger.info("Database migration V3 applied successfully.")

            # Ensure RAG indexing tables exist (idempotent)
            conn.executescript(RAG_SCHEMA_SQL)
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        conn.close()

# ==============================================================================
# HASHING & DUPLICATE CHECK
# ==============================================================================

def compute_sha256(file_bytes: bytes) -> str:
    """Computes SHA-256 hex digest of raw file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()

def find_dataset_by_hash(file_hash: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Finds an existing dataset by its SHA-256 content hash."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM datasets 
            WHERE file_hash_sha256 = ? AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
            """,
            (file_hash,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        if close_after:
            conn.close()

# ==============================================================================
# DATASET PERSISTENCE: EXCEL
# ==============================================================================

def save_excel_dataset(
    file_bytes: bytes,
    original_filename: str,
    file_type: str,
    sha256_hash: str,
    sheets_data: List[Dict[str, Any]],
    bi_report: Optional[Dict[str, Any]] = None,
    source_name: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Persists an Excel dataset transactionally:
    1. Dataset record
    2. Worksheet records
    3. Structured rows (bounded by MAX_STORED_ROWS_PER_DATASET)
    4. Initial Analysis Run
    5. Generated Report
    """
    conn = get_connection(db_path)
    dataset_id = f"ds_{uuid.uuid4().hex[:12]}"
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    total_rows = sum(s.get("row_count", 0) for s in sheets_data)
    max_cols = max((len(s.get("columns", [])) for s in sheets_data), default=0)

    is_preview_only = total_rows > MAX_STORED_ROWS_PER_DATASET
    detected_type = "Excel Dataset"
    if bi_report and isinstance(bi_report.get("classification"), dict):
        detected_type = bi_report["classification"].get("detected_type", detected_type)

    summary_meta = {
        "sheet_count": len(sheets_data),
        "total_rows": total_rows,
        "total_columns": max_cols,
        "is_preview_only": is_preview_only,
        "storage_mode": "preview_only_exceeded_limit" if is_preview_only else "full_structured"
    }

    try:
        with conn:
            cur = conn.cursor()

            # 1. Insert dataset
            cur.execute(
                """
                INSERT INTO datasets (
                    id, original_filename, file_type, file_size_bytes, file_hash_sha256,
                    dataset_type, source_name, created_at, updated_at, status,
                    sheet_count, page_count, row_count, column_count,
                    extraction_summary_json, analysis_status, last_analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    original_filename,
                    file_type,
                    len(file_bytes),
                    sha256_hash,
                    detected_type,
                    source_name,
                    now_str,
                    now_str,
                    "active",
                    len(sheets_data),
                    None,
                    total_rows,
                    max_cols,
                    safe_json_dumps(summary_meta),
                    "completed" if bi_report else "none",
                    now_str if bi_report else None
                )
            )

            # 2. Insert worksheets & rows
            for sheet_idx, sdata in enumerate(sheets_data):
                sheet_id = f"sheet_{uuid.uuid4().hex[:12]}"
                cols = sdata.get("columns", [])
                preview = sdata.get("preview_rows", [])
                all_rows = sdata.get("all_rows", preview) # If all_rows provided, persist them

                cur.execute(
                    """
                    INSERT INTO dataset_sheets (
                        id, dataset_id, sheet_name, sheet_index,
                        row_count, column_count, columns_json, preview_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sheet_id,
                        dataset_id,
                        sdata.get("sheet_name", f"Sheet{sheet_idx+1}"),
                        sheet_idx,
                        sdata.get("row_count", len(all_rows)),
                        len(cols),
                        safe_json_dumps(cols),
                        safe_json_dumps(preview[:10])
                    )
                )

                # Persist records (up to limit or preview only)
                rows_to_store = preview if is_preview_only else all_rows
                records_batch = []
                for r_idx, r_dict in enumerate(rows_to_store):
                    rec_id = f"rec_{uuid.uuid4().hex[:12]}"
                    records_batch.append((
                        rec_id,
                        dataset_id,
                        sheet_id,
                        r_idx,
                        safe_json_dumps(r_dict)
                    ))

                if records_batch:
                    cur.executemany(
                        """
                        INSERT INTO dataset_records (
                            id, dataset_id, sheet_id, row_index, record_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        records_batch
                    )

            # 3. Insert initial Analysis Run & Report if bi_report is available
            run_id = None
            if bi_report:
                run_id = f"run_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO analysis_runs (
                        id, dataset_id, created_at, analysis_version,
                        analysis_status, metrics_json, insights_json,
                        quality_report_json, warnings_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        dataset_id,
                        now_str,
                        ANALYSIS_ENGINE_VERSION,
                        "success",
                        safe_json_dumps({
                            "pricing": bi_report.get("pricing"),
                            "inventory": bi_report.get("inventory"),
                            "sales": bi_report.get("sales"),
                            "statistical_analysis": bi_report.get("statistical_analysis"),
                            "dataset_profiling": bi_report.get("dataset_profiling")
                        }),
                        safe_json_dumps(bi_report.get("insights", [])),
                        safe_json_dumps(bi_report.get("data_quality", {})),
                        safe_json_dumps(bi_report.get("data_quality", {}).get("issues", []))
                    )
                )

                # 4. Insert Report
                rep_id = f"rep_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO reports (
                        id, dataset_id, analysis_run_id, report_type,
                        created_at, report_format, report_content_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rep_id,
                        dataset_id,
                        run_id,
                        "full_bi",
                        now_str,
                        "json",
                        safe_json_dumps(bi_report)
                    )
                )

        logger.info(f"Excel dataset {dataset_id} successfully persisted to SQLite.")
        return {
            "dataset_id": dataset_id,
            "analysis_run_id": run_id,
            "created_at": now_str,
            "status": "persisted"
        }
    finally:
        conn.close()

# ==============================================================================
# DATASET PERSISTENCE: PDF
# ==============================================================================

def save_pdf_dataset(
    file_bytes: bytes,
    original_filename: str,
    sha256_hash: str,
    page_count: int,
    char_count: int,
    has_text: bool,
    text_preview: str,
    bi_report: Optional[Dict[str, Any]] = None,
    source_name: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Persists a PDF document transactionally:
    1. Dataset record
    2. Initial Analysis Run
    3. Generated Report
    """
    conn = get_connection(db_path)
    dataset_id = f"ds_{uuid.uuid4().hex[:12]}"
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    detected_type = "PDF Document"
    if bi_report and isinstance(bi_report.get("classification"), dict):
        detected_type = bi_report["classification"].get("detected_type", detected_type)

    summary_meta = {
        "page_count": page_count,
        "char_count": char_count,
        "has_text": has_text,
        "text_preview": text_preview[:2000] if text_preview else ""
    }

    try:
        with conn:
            cur = conn.cursor()

            # 1. Insert dataset
            cur.execute(
                """
                INSERT INTO datasets (
                    id, original_filename, file_type, file_size_bytes, file_hash_sha256,
                    dataset_type, source_name, created_at, updated_at, status,
                    sheet_count, page_count, row_count, column_count,
                    extraction_summary_json, analysis_status, last_analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    original_filename,
                    "pdf",
                    len(file_bytes),
                    sha256_hash,
                    detected_type,
                    source_name,
                    now_str,
                    now_str,
                    "active",
                    0,
                    page_count,
                    0,
                    0,
                    safe_json_dumps(summary_meta),
                    "completed" if bi_report else "none",
                    now_str if bi_report else None
                )
            )

            # 2. Insert initial Analysis Run & Report if bi_report
            run_id = None
            if bi_report:
                run_id = f"run_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO analysis_runs (
                        id, dataset_id, created_at, analysis_version,
                        analysis_status, metrics_json, insights_json,
                        quality_report_json, warnings_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        dataset_id,
                        now_str,
                        ANALYSIS_ENGINE_VERSION,
                        "success",
                        safe_json_dumps({
                            "pdf_document_intelligence": bi_report.get("pdf_document_intelligence"),
                            "resume_intelligence": bi_report.get("resume_intelligence")
                        }),
                        safe_json_dumps(bi_report.get("insights", [])),
                        safe_json_dumps(bi_report.get("data_quality", {})),
                        safe_json_dumps(bi_report.get("data_quality", {}).get("issues", []))
                    )
                )

                # Report
                rep_id = f"rep_{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO reports (
                        id, dataset_id, analysis_run_id, report_type,
                        created_at, report_format, report_content_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rep_id,
                        dataset_id,
                        run_id,
                        "pdf_intelligence",
                        now_str,
                        "json",
                        safe_json_dumps(bi_report)
                    )
                )

        logger.info(f"PDF dataset {dataset_id} successfully persisted to SQLite.")
        return {
            "dataset_id": dataset_id,
            "analysis_run_id": run_id,
            "created_at": now_str,
            "status": "persisted"
        }
    finally:
        conn.close()

# ==============================================================================
# RETRIEVAL & QUERY FUNCTIONS
# ==============================================================================

def list_datasets(
    page: int = 1,
    page_size: int = 10,
    search: str = "",
    file_type: Optional[str] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Returns a paginated list of saved datasets with total count."""
    page = max(1, page)
    page_size = min(max(1, page_size), 100) # Safe bound 1-100
    offset = (page - 1) * page_size

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        query = """
            SELECT 
                d.*,
                COALESCE(di.status, 'unindexed') as index_status,
                COALESCE(di.chunk_count, 0) as chunk_count,
                di.error_message as index_error_message,
                di.indexed_at as indexed_at
            FROM datasets d
            LEFT JOIN document_indexes di ON d.id = di.dataset_id
            WHERE d.status = 'active'
        """
        params: List[Any] = []

        if search:
            query += " AND (d.original_filename LIKE ? OR d.dataset_type LIKE ?)"
            pattern = f"%{search.strip()}%"
            params.extend([pattern, pattern])

        if file_type:
            query += " AND d.file_type = ?"
            params.append(file_type.lower().strip())

        # Count total
        count_query = f"SELECT COUNT(*) FROM ({query})"
        cur.execute(count_query, params)
        total_count = cur.fetchone()[0]

        # Fetch page
        query += " ORDER BY d.created_at DESC LIMIT ? OFFSET ?"
        params.extend([page_size, offset])
        cur.execute(query, params)
        rows = cur.fetchall()

        datasets = []
        for r in rows:
            item = dict(r)
            item["extraction_summary"] = safe_json_loads(item.get("extraction_summary_json"))
            item.pop("extraction_summary_json", None)
            datasets.append(item)

        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        return {
            "datasets": datasets,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }
    finally:
        conn.close()

def get_dataset_by_id(dataset_id: str, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns metadata, worksheets, and summary for a specific dataset."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM datasets WHERE id = ? AND status = 'active'", (dataset_id,))
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        data["extraction_summary"] = safe_json_loads(data.get("extraction_summary_json"))
        data.pop("extraction_summary_json", None)

        # Fetch sheets
        cur.execute(
            """
            SELECT id, sheet_name, sheet_index, row_count, column_count, columns_json, preview_json
            FROM dataset_sheets WHERE dataset_id = ? ORDER BY sheet_index ASC
            """,
            (dataset_id,)
        )
        sheet_rows = cur.fetchall()
        sheets = []
        for s in sheet_rows:
            s_dict = dict(s)
            s_dict["columns"] = safe_json_loads(s_dict.get("columns_json"), [])
            s_dict["preview_rows"] = safe_json_loads(s_dict.get("preview_json"), [])
            s_dict.pop("columns_json", None)
            s_dict.pop("preview_json", None)
            sheets.append(s_dict)

        data["sheets"] = sheets
        return data
    finally:
        if close_after:
            conn.close()


def get_dataset_sheets(dataset_id: str, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns worksheets for a dataset."""
    ds = get_dataset_by_id(dataset_id, conn=conn, db_path=db_path)
    return ds.get("sheets", []) if ds else []

def get_dataset_records(
    dataset_id: str,
    sheet_name: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Returns paginated structured records for an Excel dataset."""
    page = max(1, page)
    page_size = min(max(1, page_size), 200) # Safe bound 1-200
    offset = (page - 1) * page_size

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        # Find sheet_id
        if sheet_name:
            cur.execute(
                "SELECT id, columns_json, row_count FROM dataset_sheets WHERE dataset_id = ? AND sheet_name = ?",
                (dataset_id, sheet_name)
            )
        else:
            cur.execute(
                "SELECT id, columns_json, row_count FROM dataset_sheets WHERE dataset_id = ? ORDER BY sheet_index ASC LIMIT 1",
                (dataset_id,)
            )

        sheet_row = cur.fetchone()
        if not sheet_row:
            return {
                "records": [],
                "columns": [],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_items": 0,
                    "total_pages": 1,
                    "has_next": False,
                    "has_prev": False
                }
            }

        sheet_id = sheet_row["id"]
        columns = safe_json_loads(sheet_row["columns_json"], [])
        total_items = sheet_row["row_count"]

        cur.execute(
            """
            SELECT row_index, record_json FROM dataset_records
            WHERE dataset_id = ? AND sheet_id = ?
            ORDER BY row_index ASC LIMIT ? OFFSET ?
            """,
            (dataset_id, sheet_id, page_size, offset)
        )
        rows = cur.fetchall()
        records = [safe_json_loads(r["record_json"], {}) for r in rows]

        total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1

        return {
            "sheet_id": sheet_id,
            "columns": columns,
            "records": records,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }
    finally:
        conn.close()

def load_dataset_dataframe(
    dataset_id: str,
    sheet_name: Optional[str] = None,
    db_path: Optional[str] = None
) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """
    Loads all records of an Excel dataset (or specific sheet) from SQLite into a pandas DataFrame.
    Returns (df, dataset_dict).
    If dataset is a PDF or has no records, returns (None, dataset_dict).
    """
    import pandas as pd
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        ds_row = cur.fetchone()
        if not ds_row:
            return None, None
        ds = dict(ds_row)
        ds["extraction_summary"] = safe_json_loads(ds.get("extraction_summary_json"), {})

        if ds.get("file_type") == 'pdf':
            return None, ds

        # Find sheet
        if sheet_name:
            cur.execute(
                "SELECT id, sheet_name, columns_json, row_count FROM dataset_sheets WHERE dataset_id = ? AND sheet_name = ?",
                (dataset_id, sheet_name)
            )
        else:
            cur.execute(
                "SELECT id, sheet_name, columns_json, row_count FROM dataset_sheets WHERE dataset_id = ? ORDER BY sheet_index ASC LIMIT 1",
                (dataset_id,)
            )
        sheet_row = cur.fetchone()
        if not sheet_row:
            return pd.DataFrame(), ds

        sheet_id = sheet_row["id"]
        columns = safe_json_loads(sheet_row["columns_json"], [])

        cur.execute(
            "SELECT record_json FROM dataset_records WHERE dataset_id = ? AND sheet_id = ? ORDER BY row_index ASC",
            (dataset_id, sheet_id)
        )
        records = [safe_json_loads(r["record_json"], {}) for r in cur.fetchall()]
        if not records:
            df = pd.DataFrame(columns=columns)
        else:
            df = pd.DataFrame(records)
            existing_cols = [c for c in columns if c in df.columns]
            other_cols = [c for c in df.columns if c not in existing_cols]
            df = df[existing_cols + other_cols]

        ds["active_sheet"] = sheet_row["sheet_name"]
        ds["columns"] = columns
        ds["total_rows"] = len(df)
        return df, ds
    finally:
        conn.close()

def get_dataset_reports(dataset_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns analysis runs and saved reports for a dataset."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 
                r.id as report_id,
                r.report_type,
                r.created_at,
                r.report_format,
                ar.id as analysis_run_id,
                ar.analysis_version,
                ar.analysis_status
            FROM reports r
            JOIN analysis_runs ar ON r.analysis_run_id = ar.id
            WHERE r.dataset_id = ?
            ORDER BY r.created_at DESC
            """,
            (dataset_id,)
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_report_by_id(report_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns the full report content by report_id."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.*, d.original_filename, d.file_type, d.dataset_type, ar.analysis_version
            FROM reports r
            JOIN datasets d ON r.dataset_id = d.id
            JOIN analysis_runs ar ON r.analysis_run_id = ar.id
            WHERE r.id = ?
            """,
            (report_id,)
        )
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        data["report_content"] = safe_json_loads(data.get("report_content_json"))
        data.pop("report_content_json", None)
        return data
    finally:
        conn.close()

def get_latest_report_for_dataset(dataset_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches the latest report content for a dataset."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.*, d.original_filename, d.file_type, d.dataset_type, ar.analysis_version
            FROM reports r
            JOIN datasets d ON r.dataset_id = d.id
            JOIN analysis_runs ar ON r.analysis_run_id = ar.id
            WHERE r.dataset_id = ?
            ORDER BY r.created_at DESC LIMIT 1
            """,
            (dataset_id,)
        )
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        data["report_content"] = safe_json_loads(data.get("report_content_json"))
        data.pop("report_content_json", None)
        return data
    finally:
        conn.close()

# ==============================================================================
# RE-ANALYSIS & RUN PERSISTENCE
# ==============================================================================

def create_analysis_run(
    dataset_id: str,
    bi_report: Dict[str, Any],
    version: str = ANALYSIS_ENGINE_VERSION,
    report_type: str = "full_bi",
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Persists a new analysis run and generated report for an existing dataset.
    Preserves all previous analysis runs.
    """
    conn = get_connection(db_path)
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    rep_id = f"rep_{uuid.uuid4().hex[:12]}"
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        with conn:
            cur = conn.cursor()
            # 1. Insert analysis run
            cur.execute(
                """
                INSERT INTO analysis_runs (
                    id, dataset_id, created_at, analysis_version,
                    analysis_status, metrics_json, insights_json,
                    quality_report_json, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    dataset_id,
                    now_str,
                    version,
                    "success",
                    safe_json_dumps({
                        "pricing": bi_report.get("pricing"),
                        "inventory": bi_report.get("inventory"),
                        "sales": bi_report.get("sales"),
                        "statistical_analysis": bi_report.get("statistical_analysis"),
                        "dataset_profiling": bi_report.get("dataset_profiling"),
                        "pdf_document_intelligence": bi_report.get("pdf_document_intelligence"),
                        "resume_intelligence": bi_report.get("resume_intelligence")
                    }),
                    safe_json_dumps(bi_report.get("insights", [])),
                    safe_json_dumps(bi_report.get("data_quality", {})),
                    safe_json_dumps(bi_report.get("data_quality", {}).get("issues", []))
                )
            )

            # 2. Insert report
            cur.execute(
                """
                INSERT INTO reports (
                    id, dataset_id, analysis_run_id, report_type,
                    created_at, report_format, report_content_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rep_id,
                    dataset_id,
                    run_id,
                    report_type,
                    now_str,
                    "json",
                    safe_json_dumps(bi_report)
                )
            )

            # 3. Update dataset's last_analyzed_at and analysis_status
            cur.execute(
                """
                UPDATE datasets
                SET last_analyzed_at = ?, analysis_status = 'completed', updated_at = ?
                WHERE id = ?
                """,
                (now_str, now_str, dataset_id)
            )

        return {
            "analysis_run_id": run_id,
            "report_id": rep_id,
            "created_at": now_str,
            "version": version
        }
    finally:
        conn.close()

# ==============================================================================
# SAFE DATASET DELETION
# ==============================================================================

def delete_dataset(dataset_id: str, db_path: Optional[str] = None) -> bool:
    """
    Safely deletes a dataset and its cascading child records (sheets, rows, runs, reports)
    within a transaction.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM datasets WHERE id = ?", (dataset_id,))
            if not cur.fetchone():
                return False

            # With foreign_keys = ON and ON DELETE CASCADE, child records are removed cleanly.
            cur.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
            return True
    finally:
        conn.close()

# ==============================================================================
# BACKUP & RESTORE UTILITIES
# ==============================================================================

def backup_database(target_path: Optional[str] = None, source_db_path: Optional[str] = None) -> str:
    """
    Creates a consistent SQLite online backup using connection.backup().
    Returns the absolute path to the backup file.
    """
    src_path = source_db_path or get_db_path()
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Source database file does not exist: {src_path}")

    if not target_path:
        backups_dir = os.path.join(BASE_DIR, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = os.path.join(backups_dir, f"jarvis_backup_{timestamp}.db")
    else:
        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)

    src_conn = sqlite3.connect(src_path)
    dst_conn = sqlite3.connect(target_path)
    try:
        src_conn.backup(dst_conn)
        logger.info(f"Database backup created successfully at: {target_path}")
        return target_path
    finally:
        dst_conn.close()
        src_conn.close()

def restore_database(backup_path: str, target_db_path: Optional[str] = None) -> str:
    """
    Restores a database from a backup file into target_db_path using connection.backup().
    Fails safely if backup_path is invalid.
    """
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    dst_path = target_db_path or get_db_path()
    dst_dir = os.path.dirname(dst_path)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)

    src_conn = sqlite3.connect(backup_path)
    dst_conn = sqlite3.connect(dst_path)
    try:
        src_conn.backup(dst_conn)
        logger.info(f"Database successfully restored from {backup_path} to {dst_path}")
        return dst_path
    finally:
        dst_conn.close()
        src_conn.close()


# ==============================================================================
# J.A.R.V.I.S. STEP 4 — CATALOGUE & INVENTORY MANAGEMENT ENGINE
# ==============================================================================

def calculate_margins(purchase_price: Optional[float], selling_price: Optional[float]) -> Dict[str, Optional[float]]:
    """
    Calculates unit gross profit, gross margin percentage, and markup percentage.
    - Unit gross profit: Selling Price - Purchase Cost
    - Gross margin %: ((Selling Price - Purchase Cost) / Selling Price) * 100
    - Markup %: ((Selling Price - Purchase Cost) / Purchase Cost) * 100
    Handles zero-division and missing values safely.
    """
    if purchase_price is None or selling_price is None:
        return {"gross_profit": None, "gross_margin_pct": None, "markup_pct": None}
    try:
        p = float(purchase_price)
        s = float(selling_price)
    except (ValueError, TypeError):
        return {"gross_profit": None, "gross_margin_pct": None, "markup_pct": None}

    profit = round(s - p, 2)
    margin = round(((s - p) / s) * 100.0, 2) if s > 0 else 0.0
    markup = round(((s - p) / p) * 100.0, 2) if p > 0 else 0.0
    return {
        "gross_profit": profit,
        "gross_margin_pct": margin,
        "markup_pct": markup
    }


def create_or_get_supplier(name: str, contact_name: Optional[str] = None, phone: Optional[str] = None,
                           email: Optional[str] = None, address: Optional[str] = None,
                           notes: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Finds an existing supplier by name (case-insensitive) or creates a new one."""
    if not name or not str(name).strip():
        raise ValueError("Supplier name cannot be empty")
    cleaned_name = str(name).strip()
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM suppliers WHERE LOWER(TRIM(name)) = LOWER(?)", (cleaned_name,))
        row = cur.fetchone()
        if row:
            return dict(row)

        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO suppliers (name, contact_name, phone, email, address, notes, created_at, updated_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (cleaned_name, contact_name, phone, email, address, notes, now_str, now_str)
        )
        sup_id = cur.lastrowid
        if close_after:
            conn.commit()
        cur.execute("SELECT * FROM suppliers WHERE id = ?", (sup_id,))
        return dict(cur.fetchone())
    finally:
        if close_after:
            conn.close()


def list_suppliers(is_active: Optional[bool] = None, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Returns a list of suppliers ordered by name."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        if is_active is None:
            cur.execute("SELECT * FROM suppliers ORDER BY name ASC")
        else:
            cur.execute("SELECT * FROM suppliers WHERE is_active = ? ORDER BY name ASC", (1 if is_active else 0,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        if close_after:
            conn.close()


def create_product(product_data: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Creates a new product with an atomic initial inventory balance and opening-balance movement.
    """
    name = product_data.get("name")
    if not name or not str(name).strip():
        raise ValueError("Product name is required and cannot be empty")
    name = str(name).strip()

    sku = str(product_data.get("sku") or "").strip() or None
    description = str(product_data.get("description") or "").strip() or None
    category = str(product_data.get("category") or "").strip() or None
    brand = str(product_data.get("brand") or "").strip() or None
    unit = str(product_data.get("unit") or "piece").strip().lower() or "piece"
    currency = str(product_data.get("currency") or "INR").strip().upper() or "INR"
    supplier_id = product_data.get("supplier_id")
    source_dataset_id = product_data.get("source_dataset_id")

    raw_purchase_price = product_data.get("purchase_price")
    if raw_purchase_price is None or str(raw_purchase_price).strip() == "":
        purchase_price = None
    else:
        try:
            purchase_price = round(float(raw_purchase_price), 2)
            if purchase_price < 0:
                raise ValueError("Purchase price cannot be negative")
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid purchase price: {e}")

    try:
        selling_price = round(float(product_data.get("selling_price") or 0.0), 2)
        if selling_price < 0:
            raise ValueError("Selling price cannot be negative")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid selling price: {e}")

    try:
        raw_stock = product_data.get("opening_stock")
        if raw_stock is None:
            raw_stock = product_data.get("initial_stock", 0.0)
        opening_stock = round(float(raw_stock or 0.0), 4)
        if opening_stock < 0:
            raise ValueError("Opening stock quantity cannot be negative")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid opening stock quantity: {e}")

    try:
        reorder_level = round(float(product_data.get("reorder_level") or 0.0), 4)
        if reorder_level < 0:
            raise ValueError("Reorder level cannot be negative")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid reorder level: {e}")

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        with conn:
            cur = conn.cursor()

            # Enforce SKU uniqueness when SKU is provided
            if sku:
                cur.execute("SELECT id, name FROM products WHERE LOWER(TRIM(sku)) = LOWER(TRIM(?))", (sku,))
                existing_sku = cur.fetchone()
                if existing_sku:
                    raise ValueError(f"SKU '{sku}' is already assigned to product '{existing_sku['name']}' (ID: {existing_sku['id']})")

            if supplier_id is not None and supplier_id != "":
                cur.execute("SELECT id FROM suppliers WHERE id = ?", (int(supplier_id),))
                if not cur.fetchone():
                    supplier_id = None
            else:
                supplier_id = None

            cur.execute(
                """
                INSERT INTO products (
                    sku, name, description, category, brand, unit, supplier_id,
                    purchase_price, selling_price, currency, is_active,
                    created_at, updated_at, source_dataset_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (sku, name, description, category, brand, unit, supplier_id,
                 purchase_price, selling_price, currency, now_str, now_str, source_dataset_id)
            )
            prod_id = cur.lastrowid

            cur.execute(
                """
                INSERT INTO inventory (product_id, quantity_on_hand, reorder_level, unit, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (prod_id, opening_stock, reorder_level, unit, now_str)
            )

            if opening_stock > 0:
                cur.execute(
                    """
                    INSERT INTO inventory_movements (
                        product_id, movement_type, quantity_delta, quantity_before, quantity_after,
                        reason, reference, created_at, source_dataset_id
                    ) VALUES (?, 'opening_balance', ?, 0.0, ?, 'Initial opening balance', 'INIT', ?, ?)
                    """,
                    (prod_id, opening_stock, opening_stock, now_str, source_dataset_id)
                )

        return get_product_by_id(prod_id, conn=conn)
    finally:
        if close_after:
            conn.close()


def update_product(product_id: int, updates: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Updates permitted product fields. Rejects direct modifications to stock quantities.
    """
    for forbidden in ("quantity_on_hand", "stock", "opening_stock", "quantity"):
        if forbidden in updates:
            raise ValueError("Direct modification of stock quantity is not permitted via product update. Use the inventory movement service.")

    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        existing = cur.fetchone()
        if not existing:
            raise ValueError(f"Product with ID {product_id} not found")

        prod_fields = {}
        inv_fields = {}
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if "name" in updates:
            val = str(updates["name"] or "").strip()
            if not val:
                raise ValueError("Product name cannot be empty")
            prod_fields["name"] = val

        if "sku" in updates:
            new_sku = str(updates["sku"] or "").strip() or None
            if new_sku:
                cur.execute("SELECT id, name FROM products WHERE LOWER(TRIM(sku)) = LOWER(TRIM(?)) AND id != ?", (new_sku, product_id))
                existing_sku = cur.fetchone()
                if existing_sku:
                    raise ValueError(f"SKU '{new_sku}' is already assigned to product '{existing_sku['name']}' (ID: {existing_sku['id']})")
            prod_fields["sku"] = new_sku

        if "description" in updates:
            prod_fields["description"] = str(updates["description"] or "").strip() or None

        if "category" in updates:
            prod_fields["category"] = str(updates["category"] or "").strip() or None

        if "brand" in updates:
            prod_fields["brand"] = str(updates["brand"] or "").strip() or None

        if "unit" in updates:
            val = str(updates["unit"] or "piece").strip().lower() or "piece"
            prod_fields["unit"] = val
            inv_fields["unit"] = val

        if "currency" in updates:
            prod_fields["currency"] = str(updates["currency"] or "INR").strip().upper() or "INR"

        if "supplier_id" in updates:
            s_id = updates["supplier_id"]
            if s_id is not None and s_id != "":
                cur.execute("SELECT id FROM suppliers WHERE id = ?", (int(s_id),))
                if not cur.fetchone():
                    raise ValueError(f"Supplier ID {s_id} does not exist")
                prod_fields["supplier_id"] = int(s_id)
            else:
                prod_fields["supplier_id"] = None

        if "purchase_price" in updates:
            raw_p = updates["purchase_price"]
            if raw_p is None or str(raw_p).strip() == "":
                prod_fields["purchase_price"] = None
            else:
                try:
                    p = round(float(raw_p), 2)
                    if p < 0:
                        raise ValueError("Purchase price cannot be negative")
                    prod_fields["purchase_price"] = p
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Invalid purchase price: {e}")

        if "selling_price" in updates:
            try:
                s = round(float(updates["selling_price"]), 2)
                if s < 0:
                    raise ValueError("Selling price cannot be negative")
                prod_fields["selling_price"] = s
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid selling price: {e}")

        if "is_active" in updates:
            prod_fields["is_active"] = 1 if updates["is_active"] else 0

        if "last_purchase_rate" in updates:
            lpr = updates["last_purchase_rate"]
            if lpr is not None and lpr != "":
                try:
                    lpr_val = round(float(lpr), 2)
                    if lpr_val < 0:
                        raise ValueError("Last purchase rate cannot be negative")
                    prod_fields["last_purchase_rate"] = lpr_val
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Invalid last purchase rate: {e}")
            else:
                prod_fields["last_purchase_rate"] = None

        if "last_purchase_date" in updates:
            lpd = updates["last_purchase_date"]
            prod_fields["last_purchase_date"] = str(lpd).strip() if lpd else None

        if "reorder_level" in updates:
            try:
                r = round(float(updates["reorder_level"]), 4)
                if r < 0:
                    raise ValueError("Reorder level cannot be negative")
                inv_fields["reorder_level"] = r
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid reorder level: {e}")

        with conn:
            if prod_fields:
                prod_fields["updated_at"] = now_str
                set_clauses = [f"{col} = ?" for col in prod_fields.keys()]
                values = list(prod_fields.values()) + [product_id]
                cur.execute(f"UPDATE products SET {', '.join(set_clauses)} WHERE id = ?", values)

            if inv_fields:
                inv_fields["updated_at"] = now_str
                inv_clauses = [f"{col} = ?" for col in inv_fields.keys()]
                inv_values = list(inv_fields.values()) + [product_id]
                cur.execute(f"UPDATE inventory SET {', '.join(inv_clauses)} WHERE product_id = ?", inv_values)

        return get_product_by_id(product_id, conn=conn)
    finally:
        if close_after:
            conn.close()


def deactivate_product(product_id: int, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Marks a product as inactive without hard deleting it."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with conn:
            cur = conn.cursor()
            cur.execute("UPDATE products SET is_active = 0, updated_at = ? WHERE id = ?", (now_str, product_id))
            return cur.rowcount > 0
    finally:
        if close_after:
            conn.close()


def get_product_by_id(product_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Retrieves full product details including inventory balance, margins, and recent movements."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.*,
                   s.name as supplier_name, s.contact_name as supplier_contact, s.email as supplier_email,
                   s.phone as supplier_phone,
                   i.quantity_on_hand, i.reorder_level, i.unit as inventory_unit, i.updated_at as inventory_updated_at
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.id = ?
            """,
            (product_id,)
        )
        row = cur.fetchone()
        if not row:
            return None

        data = dict(row)
        margins = calculate_margins(data.get("purchase_price"), data.get("selling_price"))
        data.update(margins)

        qty = float(data.get("quantity_on_hand") or 0.0)
        reorder = float(data.get("reorder_level") or 0.0)
        cost = float(data.get("purchase_price") or 0.0)
        data["is_low_stock"] = (qty <= reorder and qty > 0)
        data["is_out_of_stock"] = (qty <= 0)
        data["provisional_stock_value"] = round(qty * cost, 2)
        data["stock_valuation_label"] = "Provisional (Stored Purchase Price)"

        cur.execute(
            """
            SELECT * FROM inventory_movements
            WHERE product_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 10
            """,
            (product_id,)
        )
        data["recent_movements"] = [dict(m) for m in cur.fetchall()]

        return data
    finally:
        if close_after:
            conn.close()


def list_products(search: Optional[str] = None, category: Optional[str] = None,
                  is_active: Optional[bool] = None, low_stock: Optional[bool] = None,
                  out_of_stock: Optional[bool] = None, sort_by: str = "name",
                  sort_order: str = "asc", page: int = 1, page_size: int = 20,
                  conn: Optional[sqlite3.Connection] = None,
                  db_path: Optional[str] = None) -> Dict[str, Any]:
    """Lists products with comprehensive search, filtering, sorting, and pagination."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        where_clauses = []
        params = []

        if is_active is not None:
            where_clauses.append("p.is_active = ?")
            params.append(1 if is_active else 0)

        if category and str(category).strip():
            where_clauses.append("LOWER(p.category) = LOWER(?)")
            params.append(str(category).strip())

        if search and str(search).strip():
            s = f"%{str(search).strip()}%"
            where_clauses.append("(p.name LIKE ? OR p.sku LIKE ? OR p.category LIKE ? OR p.brand LIKE ?)")
            params.extend([s, s, s, s])

        if low_stock:
            where_clauses.append("i.quantity_on_hand <= i.reorder_level AND i.quantity_on_hand > 0")

        if out_of_stock:
            where_clauses.append("i.quantity_on_hand <= 0")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cur.execute(
            f"""
            SELECT COUNT(*) FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            {where_sql}
            """,
            params
        )
        total_count = cur.fetchone()[0]

        allowed_sorts = {
            "name": "p.name",
            "sku": "p.sku",
            "price": "p.selling_price",
            "selling_price": "p.selling_price",
            "purchase_price": "p.purchase_price",
            "stock": "i.quantity_on_hand",
            "quantity_on_hand": "i.quantity_on_hand",
            "created_at": "p.created_at",
            "updated_at": "p.updated_at"
        }
        order_col = allowed_sorts.get(str(sort_by).lower(), "p.name")
        direction = "DESC" if str(sort_order).lower() == "desc" else "ASC"

        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        offset = (page - 1) * page_size

        cur.execute(
            f"""
            SELECT p.*,
                   s.name as supplier_name,
                   i.quantity_on_hand, i.reorder_level, i.unit as inventory_unit, i.updated_at as inventory_updated_at
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            {where_sql}
            ORDER BY {order_col} {direction}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset]
        )
        rows = cur.fetchall()

        items = []
        for r in rows:
            d = dict(r)
            margins = calculate_margins(d.get("purchase_price"), d.get("selling_price"))
            d.update(margins)
            qty = float(d.get("quantity_on_hand") or 0.0)
            reorder = float(d.get("reorder_level") or 0.0)
            cost = float(d.get("purchase_price") or 0.0)
            d["is_low_stock"] = (qty <= reorder and qty > 0)
            d["is_out_of_stock"] = (qty <= 0)
            d["provisional_stock_value"] = round(qty * cost, 2)
            d["stock_valuation_label"] = "Provisional (Stored Purchase Price)"
            items.append(d)

        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        return {
            "items": items,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }
    finally:
        if close_after:
            conn.close()


def record_inventory_movement(product_id: int, movement_type: str, quantity_delta: float,
                              reason: str, reference: Optional[str] = None,
                              source_dataset_id: Optional[str] = None,
                              allow_negative: bool = False,
                              conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Atomically updates inventory balance and writes an immutable movement log entry.
    Rejects stock adjustments that lead to negative balances unless allow_negative=True.
    """
    valid_types = {"opening_balance", "receipt", "sale", "adjustment", "return"}
    m_type = str(movement_type or "").strip().lower()
    if m_type not in valid_types:
        raise ValueError(f"Invalid movement type '{movement_type}'. Permitted: {', '.join(sorted(valid_types))}")

    if not reason or not str(reason).strip():
        raise ValueError("Reason is mandatory for inventory stock movements")
    reason_clean = str(reason).strip()

    try:
        delta = round(float(quantity_delta), 4)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid quantity delta: {quantity_delta}")

    if delta == 0:
        raise ValueError("Quantity change must be non-zero")

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT quantity_on_hand, unit, reorder_level FROM inventory WHERE product_id = ?", (product_id,))
            inv_row = cur.fetchone()
            if not inv_row:
                raise ValueError(f"No inventory record found for product ID {product_id}")

            current_qty = round(float(inv_row["quantity_on_hand"]), 4)
            new_qty = round(current_qty + delta, 4)

            if new_qty < 0 and not allow_negative:
                raise ValueError(
                    f"Stock adjustment rejected: business rule prohibits negative balance. "
                    f"Current stock: {current_qty}, delta: {delta}, resulting balance: {new_qty}."
                )

            cur.execute(
                "UPDATE inventory SET quantity_on_hand = ?, updated_at = ? WHERE product_id = ?",
                (new_qty, now_str, product_id)
            )

            cur.execute(
                """
                INSERT INTO inventory_movements (
                    product_id, movement_type, quantity_delta, quantity_before, quantity_after,
                    reason, reference, created_at, source_dataset_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, m_type, delta, current_qty, new_qty, reason_clean, reference, now_str, source_dataset_id)
            )
            movement_id = cur.lastrowid

            cur.execute("SELECT * FROM inventory_movements WHERE id = ?", (movement_id,))
            movement_record = dict(cur.fetchone())

        return {
            "movement": movement_record,
            "product_id": product_id,
            "quantity_before": current_qty,
            "quantity_after": new_qty,
            "quantity_delta": delta
        }
    finally:
        if close_after:
            conn.close()


def get_inventory_movements(product_id: Optional[int] = None, limit: int = 50,
                            page: int = 1, conn: Optional[sqlite3.Connection] = None,
                            db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieves paginated movement history with product information."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        where_clauses = []
        params = []
        if product_id is not None:
            where_clauses.append("m.product_id = ?")
            params.append(product_id)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cur.execute(f"SELECT COUNT(*) FROM inventory_movements m {where_sql}", params)
        total_count = cur.fetchone()[0]

        page = max(1, int(page))
        limit = max(1, min(200, int(limit)))
        offset = (page - 1) * limit

        cur.execute(
            f"""
            SELECT m.*, p.name as product_name, p.sku as product_sku, p.unit as product_unit
            FROM inventory_movements m
            JOIN products p ON m.product_id = p.id
            {where_sql}
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset]
        )
        items = [dict(r) for r in cur.fetchall()]
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

        return {
            "items": items,
            "total_count": total_count,
            "page": page,
            "page_size": limit,
            "total_pages": total_pages
        }
    finally:
        if close_after:
            conn.close()


def get_inventory_summary(conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Returns HUD summary telemetry for products and inventory balances."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
        active_products = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(quantity_on_hand), 0) FROM inventory i JOIN products p ON i.product_id = p.id WHERE p.is_active = 1")
        total_stock = round(float(cur.fetchone()[0]), 2)

        cur.execute(
            """
            SELECT COUNT(*) FROM inventory i
            JOIN products p ON i.product_id = p.id
            WHERE p.is_active = 1 AND i.quantity_on_hand <= i.reorder_level AND i.quantity_on_hand > 0
            """
        )
        low_stock_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM inventory i
            JOIN products p ON i.product_id = p.id
            WHERE p.is_active = 1 AND i.quantity_on_hand <= 0
            """
        )
        out_of_stock_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM products
            WHERE is_active = 1 AND (purchase_price <= 0 OR selling_price <= 0 OR purchase_price IS NULL OR selling_price IS NULL)
            """
        )
        missing_price_count = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COALESCE(category, 'Uncategorized') as category, COUNT(*) as count
            FROM products
            WHERE is_active = 1
            GROUP BY category
            ORDER BY count DESC
            LIMIT 10
            """
        )
        categories = [dict(r) for r in cur.fetchall()]

        return {
            "active_products": active_products,
            "total_stock_units": total_stock,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "missing_price_count": missing_price_count,
            "categories": categories
        }
    finally:
        if close_after:
            conn.close()


def find_product_by_identifier(identifier: str, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Safely matches a product identifier by SKU first, then by exact name (case-insensitive).
    Does NOT fuzzy-match or guess similar names.
    """
    if not identifier:
        return None
    raw = str(identifier).strip()
    if not raw:
        return None

    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT p.*, i.quantity_on_hand FROM products p LEFT JOIN inventory i ON p.id = i.product_id WHERE LOWER(TRIM(p.sku)) = LOWER(TRIM(?)) LIMIT 1", (raw,))
        row = cur.fetchone()
        if row:
            return dict(row)

        cur.execute("SELECT p.*, i.quantity_on_hand FROM products p LEFT JOIN inventory i ON p.id = i.product_id WHERE LOWER(TRIM(p.name)) = LOWER(TRIM(?)) LIMIT 1", (raw,))
        row = cur.fetchone()
        if row:
            return dict(row)

        return None
    finally:
        if close_after:
            conn.close()


def suggest_column_mappings(columns: List[str], purpose: str = "catalogue") -> Dict[str, str]:
    """Suggests intelligent mappings from extracted spreadsheet column headers to business fields."""
    mapping = {}
    clean_cols = {col.lower().strip().replace("_", " ").replace("-", " "): col for col in columns}

    # Strict keyword blocklist: shipping, freight, delivery, courier must NEVER be mapped to product purchase cost / COGS
    NON_PURCHASE_COST_KEYWORDS = ("shipping", "freight", "delivery", "postage", "courier", "transport", "logistics")

    if purpose == "purchases":
        rules = {
            "sku": ["sku", "item code", "product code", "code", "barcode", "art no"],
            "product": ["product name", "item name", "product", "item", "description", "title", "name"],
            "quantity": ["quantity", "qty", "units", "count", "purchased qty", "pieces", "pcs"],
            "shipping_fee": ["shipping cost", "shipping fee", "shipping", "freight charge", "freight", "delivery fee", "delivery charge", "courier", "postage", "transport cost"],
            "unit_price": ["unit price", "purchase rate", "buy price", "cost price", "purchase cost", "unit cost", "rate", "cost", "price"],
            "purchase_date": ["date", "purchase date", "po date", "invoice date", "order date", "bill date", "txn date"],
            "purchase_number": ["purchase number", "po number", "po no", "order no", "purchase no", "bill no", "invoice no", "po"],
            "supplier": ["supplier", "vendor", "distributor", "party name", "party", "supplier name"],
            "notes": ["notes", "remarks", "remark", "comment", "description"]
        }
    elif purpose == "sales":
        rules = {
            "sku": ["sku", "item code", "product code", "code", "barcode", "art no"],
            "product": ["product name", "item name", "product", "item", "description", "title", "name"],
            "quantity": ["quantity", "qty", "units", "count", "sold qty", "pieces", "pcs"],
            "shipping_fee": ["shipping cost", "shipping fee", "shipping", "freight charge", "freight", "delivery fee", "delivery charge", "courier", "postage", "transport cost"],
            "unit_price": ["unit price", "selling price", "rate", "sell rate", "sale price", "price", "mrp", "retail price"],
            "return_status": ["returned", "return status", "is return", "is returned", "return flag", "refunded"],
            "sale_date": ["date", "sale date", "invoice date", "order date", "bill date", "txn date"],
            "invoice_number": ["invoice number", "invoice no", "bill no", "bill number", "inv no", "order id", "slip no"],
            "customer_name": ["customer", "client", "buyer", "customer name", "client name", "party", "account"],
            "notes": ["notes", "remarks", "remark", "comment", "description"]
        }
    elif purpose == "inventory_adjustments":
        rules = {
            "sku": ["sku", "item code", "product code", "code"],
            "product": ["product name", "item name", "product", "item", "name"],
            "quantity_delta": ["delta", "adjustment", "change", "variance", "difference", "quantity delta", "stock change", "qty"],
            "reason": ["reason", "cause", "note", "remarks", "justification"],
            "reference": ["reference", "ref", "audit id", "batch id"]
        }
    else:  # catalogue
        rules = {
            "sku": ["sku", "item code", "product code", "code", "barcode", "art no", "article"],
            "name": ["product name", "item name", "product", "item", "description", "title", "name"],
            "category": ["category", "dept", "department", "group", "product group", "type"],
            "brand": ["brand", "manufacturer", "make"],
            "supplier": ["supplier", "vendor", "distributor", "provider"],
            "shipping_fee": ["shipping cost", "shipping fee", "shipping", "freight charge", "freight", "delivery fee", "delivery charge", "courier", "postage", "transport cost"],
            "purchase_price": ["purchase price", "cost price", "purchase cost", "unit cost", "buy price", "buying price", "cost"],
            "selling_price": ["selling price", "sell price", "retail price", "price", "mrp", "unit price", "rate"],
            "unit": ["unit", "uom", "measurement", "unit of measure"],
            "opening_stock": ["opening stock", "opening units", "initial stock", "stock", "quantity", "qty", "balance", "on hand", "inventory", "units"],
            "reorder_level": ["reorder level", "reorder", "min stock", "minimum stock", "safety stock", "threshold"]
        }

    used_cols = set()
    # Pass 1: Exact matches across all fields
    for field, candidates in rules.items():
        if field in mapping:
            continue
        for cand in candidates:
            if cand in clean_cols and clean_cols[cand] not in used_cols:
                # Critical safeguard: never map logistics/freight columns to purchase_price or unit_price
                if field in ("purchase_price", "unit_price") and any(kw in cand for kw in NON_PURCHASE_COST_KEYWORDS):
                    continue
                mapping[field] = clean_cols[cand]
                used_cols.add(clean_cols[cand])
                break

    # Pass 2: Substring matches for remaining unmapped fields
    for field, candidates in rules.items():
        if field in mapping:
            continue
        for cand in candidates:
            matched = False
            for clean_name, orig_name in clean_cols.items():
                if orig_name not in used_cols and cand in clean_name:
                    # Critical safeguard: never map logistics/freight columns to purchase_price or unit_price
                    if field in ("purchase_price", "unit_price") and any(kw in clean_name for kw in NON_PURCHASE_COST_KEYWORDS):
                        continue
                    mapping[field] = orig_name
                    used_cols.add(orig_name)
                    matched = True
                    break
            if matched:
                break

    return mapping


def preview_product_spreadsheet_import(dataset_id: str, column_mapping: Dict[str, str],
                                       sheet_name: Optional[str] = None,
                                       sync_purpose: str = "catalogue",
                                       conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Parses and validates spreadsheet records against the provided column mapping and sync_purpose.
    Categorizes rows into valid, duplicate, and invalid, returning row-level diagnostic messages.
    Supports purposes: 'catalogue', 'purchases', 'sales', 'inventory_adjustments'.
    """
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT id, original_filename, file_type FROM datasets WHERE id = ?", (dataset_id,))
        ds_row = cur.fetchone()
        if not ds_row:
            raise ValueError(f"Dataset {dataset_id} not found")

        # Get records
        if sheet_name:
            cur.execute(
                """
                SELECT r.row_index, r.record_json
                FROM dataset_records r
                JOIN dataset_sheets s ON r.sheet_id = s.id
                WHERE r.dataset_id = ? AND s.sheet_name = ?
                ORDER BY r.row_index ASC
                """,
                (dataset_id, sheet_name)
            )
        else:
            cur.execute(
                """
                SELECT row_index, record_json
                FROM dataset_records
                WHERE dataset_id = ?
                ORDER BY row_index ASC
                """,
                (dataset_id,)
            )

        rows = cur.fetchall()
        if not rows:
            if ds_row["file_type"] == 'pdf':
                raise ValueError("Dataset was extracted from an unstructured document without confirmed tabular sheets. Digital spreadsheet (XLSX, XLS, CSV) is required for structured ledger synchronization.")
            raise ValueError(f"No structured records found in dataset {dataset_id}")

        # Fetch existing products
        cur.execute("SELECT p.id, p.sku, p.name, p.purchase_price, p.selling_price, i.quantity_on_hand FROM products p LEFT JOIN inventory i ON p.id = i.product_id")
        all_prods = [dict(r) for r in cur.fetchall()]
        existing_skus = {p["sku"].strip().lower(): p for p in all_prods if p.get("sku")}
        existing_names = {p["name"].strip().lower(): p for p in all_prods if p.get("name")}

        # Existing transactions for duplicate detection
        cur.execute("SELECT product_id, purchase_number, purchase_date, quantity, unit_price, source_dataset_id FROM purchases")
        existing_purchases = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT product_id, invoice_number, sale_date, quantity, unit_price, source_dataset_id FROM sales")
        existing_sales = [dict(r) for r in cur.fetchall()]

        total_rows = len(rows)
        valid_count = 0
        duplicate_count = 0
        invalid_count = 0
        unmatched_count = 0
        proposed_stock_additions = 0.0
        proposed_stock_deductions = 0.0
        errors = []
        sample_preview = []

        seen_batch_keys = set()

        for r in rows:
            row_idx = r["row_index"] + 1
            rec = safe_json_loads(r["record_json"], {})
            row_errors = []

            if sync_purpose == "purchases":
                # Match product
                prod_col = column_mapping.get("product") or column_mapping.get("sku") or column_mapping.get("name")
                prod_val = str(rec.get(prod_col) or "").strip() if prod_col else ""
                matched_prod = None
                if prod_val:
                    if prod_val.lower() in existing_skus:
                        matched_prod = existing_skus[prod_val.lower()]
                    elif prod_val.lower() in existing_names:
                        matched_prod = existing_names[prod_val.lower()]
                
                if not matched_prod:
                    unmatched_count += 1
                    row_errors.append(f"Unmatched product '{prod_val or 'empty'}'. Product must exist in catalogue prior to procurement recording.")

                # Quantity & Unit Price
                qty = 0.0
                q_col = column_mapping.get("quantity") or column_mapping.get("qty")
                if q_col and rec.get(q_col) is not None and str(rec.get(q_col)).strip() != "":
                    try:
                        qty = round(float(rec[q_col]), 4)
                        if qty <= 0:
                            row_errors.append("Purchase quantity must be strictly greater than zero")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid quantity: '{rec[q_col]}'")
                else:
                    row_errors.append("Purchase quantity is missing")

                price = 0.0
                p_col = column_mapping.get("unit_price") or column_mapping.get("rate") or column_mapping.get("purchase_price")
                if p_col and rec.get(p_col) is not None and str(rec.get(p_col)).strip() != "":
                    try:
                        price = round(float(rec[p_col]), 2)
                        if price < 0:
                            row_errors.append("Unit purchase price cannot be negative")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid unit price: '{rec[p_col]}'")
                else:
                    row_errors.append("Purchase unit price is missing")

                po_col = column_mapping.get("purchase_number") or column_mapping.get("po_number")
                po_num = str(rec.get(po_col) or "").strip() if po_col else ""

                date_col = column_mapping.get("purchase_date") or column_mapping.get("date")
                p_date = str(rec.get(date_col) or "").strip() if date_col else ""

                # Duplicate detection for purchase
                is_duplicate = False
                if matched_prod:
                    p_id = matched_prod["id"]
                    batch_key = f"PO_{po_num}_{p_id}_{qty}_{price}" if po_num else f"PO_ROW_{row_idx}_{p_id}"
                    if batch_key in seen_batch_keys:
                        is_duplicate = True
                    seen_batch_keys.add(batch_key)

                    if po_num:
                        for ep in existing_purchases:
                            if ep.get("purchase_number") and str(ep["purchase_number"]).strip().lower() == po_num.lower() and ep["product_id"] == p_id:
                                is_duplicate = True
                                break

                status = "invalid" if row_errors else ("duplicate" if is_duplicate else "valid")
                if status == "invalid":
                    invalid_count += 1
                    errors.append({"row": row_idx, "message": "; ".join(row_errors)})
                elif status == "duplicate":
                    duplicate_count += 1
                else:
                    valid_count += 1
                    proposed_stock_additions += qty

                if len(sample_preview) < 10:
                    sample_preview.append({
                        "row_index": row_idx,
                        "product_matched": matched_prod["name"] if matched_prod else "UNMATCHED",
                        "sku": matched_prod["sku"] if matched_prod else "",
                        "purchase_number": po_num or "-",
                        "date": p_date or "-",
                        "quantity": qty,
                        "unit_price": price,
                        "total_amount": round(qty * price, 2),
                        "status": status,
                        "errors": row_errors
                    })

            elif sync_purpose == "sales":
                # Match product
                prod_col = column_mapping.get("product") or column_mapping.get("sku") or column_mapping.get("name")
                prod_val = str(rec.get(prod_col) or "").strip() if prod_col else ""
                matched_prod = None
                if prod_val:
                    if prod_val.lower() in existing_skus:
                        matched_prod = existing_skus[prod_val.lower()]
                    elif prod_val.lower() in existing_names:
                        matched_prod = existing_names[prod_val.lower()]

                if not matched_prod:
                    unmatched_count += 1
                    row_errors.append(f"Unmatched product '{prod_val or 'empty'}'. Product must exist in catalogue prior to sales recording.")

                # Quantity & Unit Price
                qty = 0.0
                q_col = column_mapping.get("quantity") or column_mapping.get("qty")
                if q_col and rec.get(q_col) is not None and str(rec.get(q_col)).strip() != "":
                    try:
                        qty = round(float(rec[q_col]), 4)
                        if qty <= 0:
                            row_errors.append("Sale quantity must be strictly greater than zero")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid quantity: '{rec[q_col]}'")
                else:
                    row_errors.append("Sale quantity is missing")

                price = 0.0
                p_col = column_mapping.get("unit_price") or column_mapping.get("selling_price") or column_mapping.get("rate")
                if p_col and rec.get(p_col) is not None and str(rec.get(p_col)).strip() != "":
                    try:
                        price = round(float(rec[p_col]), 2)
                        if price < 0:
                            row_errors.append("Selling unit price cannot be negative")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid unit price: '{rec[p_col]}'")
                else:
                    row_errors.append("Sale unit price is missing")

                # Stock check
                if matched_prod and qty > 0:
                    avail_stock = float(matched_prod.get("quantity_on_hand") or 0.0)
                    if qty > avail_stock:
                        row_errors.append(f"Insufficient stock on hand for '{matched_prod['name']}'. Available: {avail_stock}, Requested sale: {qty}")

                inv_col = column_mapping.get("invoice_number") or column_mapping.get("invoice_no") or column_mapping.get("order_id")
                inv_num = str(rec.get(inv_col) or "").strip() if inv_col else ""

                date_col = column_mapping.get("sale_date") or column_mapping.get("date")
                s_date = str(rec.get(date_col) or "").strip() if date_col else ""

                # Duplicate detection for sale
                is_duplicate = False
                if matched_prod:
                    p_id = matched_prod["id"]
                    batch_key = f"INV_{inv_num}_{p_id}_{qty}_{price}" if inv_num else f"INV_ROW_{row_idx}_{p_id}"
                    if batch_key in seen_batch_keys:
                        is_duplicate = True
                    seen_batch_keys.add(batch_key)

                    if inv_num:
                        for es in existing_sales:
                            if es.get("invoice_number") and str(es["invoice_number"]).strip().lower() == inv_num.lower() and es["product_id"] == p_id:
                                is_duplicate = True
                                break

                status = "invalid" if row_errors else ("duplicate" if is_duplicate else "valid")
                if status == "invalid":
                    invalid_count += 1
                    errors.append({"row": row_idx, "message": "; ".join(row_errors)})
                elif status == "duplicate":
                    duplicate_count += 1
                else:
                    valid_count += 1
                    proposed_stock_deductions += qty

                if len(sample_preview) < 10:
                    sample_preview.append({
                        "row_index": row_idx,
                        "product_matched": matched_prod["name"] if matched_prod else "UNMATCHED",
                        "sku": matched_prod["sku"] if matched_prod else "",
                        "invoice_number": inv_num or "-",
                        "date": s_date or "-",
                        "quantity": qty,
                        "unit_price": price,
                        "total_amount": round(qty * price, 2),
                        "status": status,
                        "errors": row_errors
                    })

            elif sync_purpose == "inventory_adjustments":
                prod_col = column_mapping.get("product") or column_mapping.get("sku") or column_mapping.get("name")
                prod_val = str(rec.get(prod_col) or "").strip() if prod_col else ""
                matched_prod = None
                if prod_val:
                    if prod_val.lower() in existing_skus:
                        matched_prod = existing_skus[prod_val.lower()]
                    elif prod_val.lower() in existing_names:
                        matched_prod = existing_names[prod_val.lower()]

                if not matched_prod:
                    unmatched_count += 1
                    row_errors.append(f"Unmatched product '{prod_val or 'empty'}'.")

                delta = 0.0
                d_col = column_mapping.get("quantity_delta") or column_mapping.get("adjustment") or column_mapping.get("qty")
                if d_col and rec.get(d_col) is not None and str(rec.get(d_col)).strip() != "":
                    try:
                        delta = round(float(rec[d_col]), 4)
                        if delta == 0:
                            row_errors.append("Adjustment delta cannot be zero")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid adjustment delta: '{rec[d_col]}'")
                else:
                    row_errors.append("Adjustment quantity delta is missing")

                if matched_prod and delta != 0:
                    current_stock = float(matched_prod.get("quantity_on_hand") or 0.0)
                    if current_stock + delta < 0:
                        row_errors.append(f"Negative balance violation: Available: {current_stock}, Delta: {delta}")

                status = "invalid" if row_errors else "valid"
                if status == "invalid":
                    invalid_count += 1
                    errors.append({"row": row_idx, "message": "; ".join(row_errors)})
                else:
                    valid_count += 1
                    if delta > 0:
                        proposed_stock_additions += delta
                    else:
                        proposed_stock_deductions += abs(delta)

                if len(sample_preview) < 10:
                    sample_preview.append({
                        "row_index": row_idx,
                        "product_matched": matched_prod["name"] if matched_prod else "UNMATCHED",
                        "sku": matched_prod["sku"] if matched_prod else "",
                        "quantity_delta": delta,
                        "reason": str(rec.get(column_mapping.get("reason") or "") or "Imported adjustment"),
                        "status": status,
                        "errors": row_errors
                    })

            else:  # catalogue (default)
                name_col = column_mapping.get("name")
                name_val = str(rec.get(name_col) or "").strip() if name_col else ""
                if not name_val:
                    row_errors.append("Product name is missing or empty")

                sku_col = column_mapping.get("sku")
                sku_val = str(rec.get(sku_col) or "").strip() if sku_col else ""

                purchase_price = None
                p_col = column_mapping.get("purchase_price")
                if p_col and rec.get(p_col) is not None and str(rec.get(p_col)).strip() != "":
                    try:
                        purchase_price = round(float(rec[p_col]), 2)
                        if purchase_price < 0:
                            row_errors.append("Purchase price cannot be negative")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid purchase price: '{rec[p_col]}'")

                selling_price = 0.0
                s_col = column_mapping.get("selling_price")
                if s_col and rec.get(s_col) is not None and str(rec.get(s_col)).strip() != "":
                    try:
                        selling_price = round(float(rec[s_col]), 2)
                        if selling_price < 0:
                            row_errors.append("Selling price cannot be negative")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid selling price: '{rec[s_col]}'")

                opening_stock = 0.0
                st_col = column_mapping.get("opening_stock")
                if st_col and rec.get(st_col) is not None and str(rec.get(st_col)).strip() != "":
                    try:
                        opening_stock = round(float(rec[st_col]), 4)
                        if opening_stock < 0:
                            row_errors.append("Opening stock cannot be negative")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid opening stock: '{rec[st_col]}'")

                reorder_level = 0.0
                ro_col = column_mapping.get("reorder_level")
                if ro_col and rec.get(ro_col) is not None and str(rec.get(ro_col)).strip() != "":
                    try:
                        reorder_level = round(float(rec[ro_col]), 4)
                        if reorder_level < 0:
                            row_errors.append("Reorder level cannot be negative")
                    except (ValueError, TypeError):
                        row_errors.append(f"Invalid reorder level: '{rec[ro_col]}'")

                # Duplicate check
                is_duplicate = False
                if sku_val:
                    sku_lower = sku_val.lower()
                    if sku_lower in existing_skus or sku_lower in seen_batch_keys:
                        is_duplicate = True
                    seen_batch_keys.add(sku_lower)

                if name_val:
                    name_lower = name_val.lower()
                    if name_lower in existing_names or name_lower in seen_batch_keys:
                        is_duplicate = True
                    seen_batch_keys.add(name_lower)

                status = "invalid" if row_errors else ("duplicate" if is_duplicate else "valid")
                if status == "invalid":
                    invalid_count += 1
                    errors.append({"row": row_idx, "message": "; ".join(row_errors)})
                elif status == "duplicate":
                    duplicate_count += 1
                else:
                    valid_count += 1
                    proposed_stock_additions += opening_stock

                if len(sample_preview) < 10:
                    sample_preview.append({
                        "row_index": row_idx,
                        "name": name_val,
                        "sku": sku_val,
                        "purchase_price": purchase_price,
                        "selling_price": selling_price,
                        "opening_stock": opening_stock,
                        "reorder_level": reorder_level,
                        "status": status,
                        "errors": row_errors
                    })

        return {
            "dataset_id": dataset_id,
            "sync_purpose": sync_purpose,
            "total_rows": total_rows,
            "valid_count": valid_count,
            "duplicate_count": duplicate_count,
            "invalid_count": invalid_count,
            "unmatched_count": unmatched_count,
            "proposed_stock_additions": proposed_stock_additions,
            "proposed_stock_deductions": proposed_stock_deductions,
            "errors": errors[:50],
            "sample_preview": sample_preview
        }
    finally:
        if close_after:
            conn.close()


def commit_product_spreadsheet_import(dataset_id: str, column_mapping: Dict[str, str],
                                      duplicate_strategy: str = "skip_existing",
                                      sheet_name: Optional[str] = None,
                                      sync_purpose: str = "catalogue",
                                      conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Applies confirmed spreadsheet import to the target business ledger transactionally.
    Supports sync_purpose: 'catalogue', 'purchases', 'sales', 'inventory_adjustments'.
    """
    valid_strategies = {"skip_existing", "update_permitted_fields"}
    if duplicate_strategy not in valid_strategies:
        raise ValueError(f"Invalid duplicate strategy '{duplicate_strategy}'. Allowed: {', '.join(sorted(valid_strategies))}")

    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT id, original_filename FROM datasets WHERE id = ?", (dataset_id,))
        if not cur.fetchone():
            raise ValueError(f"Dataset {dataset_id} not found")

        # Fetch records
        if sheet_name:
            cur.execute(
                """
                SELECT r.row_index, r.record_json
                FROM dataset_records r
                JOIN dataset_sheets s ON r.sheet_id = s.id
                WHERE r.dataset_id = ? AND s.sheet_name = ?
                ORDER BY r.row_index ASC
                """,
                (dataset_id, sheet_name)
            )
        else:
            cur.execute(
                """
                SELECT row_index, record_json
                FROM dataset_records
                WHERE dataset_id = ?
                ORDER BY row_index ASC
                """,
                (dataset_id,)
            )

        rows = cur.fetchall()
        created_count = 0
        updated_count = 0
        recorded_count = 0
        skipped_count = 0
        errors = []
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Check existing transactions for duplicate detection
        cur.execute("SELECT product_id, purchase_number, purchase_date, quantity, unit_price, source_dataset_id FROM purchases")
        existing_purchases = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT product_id, invoice_number, sale_date, quantity, unit_price, source_dataset_id FROM sales")
        existing_sales = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT COUNT(*) FROM products WHERE source_dataset_id = ?", (dataset_id,))
        previously_imported_count = cur.fetchone()[0]

        seen_batch_keys = set()

        with conn:
            for r in rows:
                row_idx = r["row_index"] + 1
                rec = safe_json_loads(r["record_json"], {})

                if sync_purpose == "purchases":
                    prod_col = column_mapping.get("product") or column_mapping.get("sku") or column_mapping.get("name")
                    prod_val = str(rec.get(prod_col) or "").strip() if prod_col else ""
                    matched_prod = find_product_by_identifier(prod_val, conn=conn)
                    if not matched_prod:
                        errors.append({"row": row_idx, "message": f"Unmatched product '{prod_val}'"})
                        continue

                    q_col = column_mapping.get("quantity") or column_mapping.get("qty")
                    try:
                        qty = round(float(rec.get(q_col) or 0.0), 4) if q_col else 0.0
                        if qty <= 0:
                            errors.append({"row": row_idx, "message": "Quantity must be greater than zero"})
                            continue
                    except Exception:
                        errors.append({"row": row_idx, "message": "Invalid quantity"})
                        continue

                    p_col = column_mapping.get("unit_price") or column_mapping.get("rate") or column_mapping.get("purchase_price")
                    try:
                        price = round(float(rec.get(p_col) or 0.0), 2) if p_col else 0.0
                        if price < 0:
                            errors.append({"row": row_idx, "message": "Unit price cannot be negative"})
                            continue
                    except Exception:
                        errors.append({"row": row_idx, "message": "Invalid unit price"})
                        continue

                    po_col = column_mapping.get("purchase_number") or column_mapping.get("po_number")
                    po_num = str(rec.get(po_col) or "").strip() if po_col else None

                    date_col = column_mapping.get("purchase_date") or column_mapping.get("date")
                    p_date = str(rec.get(date_col) or "").strip() if date_col else now_str[:10]

                    notes_col = column_mapping.get("notes") or column_mapping.get("remarks")
                    notes_val = str(rec.get(notes_col) or "").strip() if notes_col else None

                    sup_col = column_mapping.get("supplier")
                    supplier_id = None
                    if sup_col and rec.get(sup_col):
                        sup_name = str(rec.get(sup_col)).strip()
                        if sup_name:
                            sup_record = create_or_get_supplier(sup_name, conn=conn)
                            supplier_id = sup_record.get("id")

                    # Duplicate check
                    is_duplicate = False
                    p_id = matched_prod["id"]
                    batch_key = f"PO_{po_num}_{p_id}_{qty}_{price}" if po_num else f"PO_ROW_{row_idx}_{p_id}"
                    if batch_key in seen_batch_keys:
                        is_duplicate = True
                    seen_batch_keys.add(batch_key)

                    if po_num:
                        for ep in existing_purchases:
                            if ep.get("purchase_number") and str(ep["purchase_number"]).strip().lower() == po_num.lower() and ep["product_id"] == p_id:
                                is_duplicate = True
                                break
                    else:
                        for ep in existing_purchases:
                            if ep["product_id"] == p_id and ep.get("source_dataset_id") == dataset_id:
                                is_duplicate = True
                                break

                    if is_duplicate:
                        skipped_count += 1
                        previously_imported_count += 1
                        continue

                    record_purchase(
                        product_id=p_id,
                        purchase_date=p_date,
                        quantity=qty,
                        unit_price=price,
                        supplier_id=supplier_id,
                        purchase_number=po_num,
                        notes=notes_val,
                        source_dataset_id=dataset_id,
                        update_inventory=True,
                        update_last_purchase_rate=True,
                        conn=conn
                    )
                    recorded_count += 1

                elif sync_purpose == "sales":
                    prod_col = column_mapping.get("product") or column_mapping.get("sku") or column_mapping.get("name")
                    prod_val = str(rec.get(prod_col) or "").strip() if prod_col else ""
                    matched_prod = find_product_by_identifier(prod_val, conn=conn)
                    if not matched_prod:
                        errors.append({"row": row_idx, "message": f"Unmatched product '{prod_val}'"})
                        continue

                    q_col = column_mapping.get("quantity") or column_mapping.get("qty")
                    try:
                        qty = round(float(rec.get(q_col) or 0.0), 4) if q_col else 0.0
                        if qty <= 0:
                            errors.append({"row": row_idx, "message": "Quantity must be greater than zero"})
                            continue
                    except Exception:
                        errors.append({"row": row_idx, "message": "Invalid quantity"})
                        continue

                    p_col = column_mapping.get("unit_price") or column_mapping.get("selling_price") or column_mapping.get("rate")
                    try:
                        price = round(float(rec.get(p_col) or 0.0), 2) if p_col else 0.0
                        if price < 0:
                            errors.append({"row": row_idx, "message": "Unit price cannot be negative"})
                            continue
                    except Exception:
                        errors.append({"row": row_idx, "message": "Invalid unit price"})
                        continue

                    # Stock check
                    cur.execute("SELECT quantity_on_hand FROM inventory WHERE product_id = ?", (matched_prod["id"],))
                    inv_row = cur.fetchone()
                    avail_stock = float(inv_row["quantity_on_hand"]) if inv_row else 0.0
                    if qty > avail_stock:
                        errors.append({"row": row_idx, "message": f"Insufficient stock on hand ({avail_stock}) for requested sale ({qty})"})
                        continue

                    inv_col = column_mapping.get("invoice_number") or column_mapping.get("invoice_no") or column_mapping.get("order_id")
                    inv_num = str(rec.get(inv_col) or "").strip() if inv_col else None

                    date_col = column_mapping.get("sale_date") or column_mapping.get("date")
                    s_date = str(rec.get(date_col) or "").strip() if date_col else now_str[:10]

                    cust_col = column_mapping.get("customer_name") or column_mapping.get("customer")
                    cust_name = str(rec.get(cust_col) or "").strip() if cust_col else None

                    notes_col = column_mapping.get("notes") or column_mapping.get("remarks")
                    notes_val = str(rec.get(notes_col) or "").strip() if notes_col else None

                    # Duplicate check
                    is_duplicate = False
                    p_id = matched_prod["id"]
                    batch_key = f"INV_{inv_num}_{p_id}_{qty}_{price}" if inv_num else f"INV_ROW_{row_idx}_{p_id}"
                    if batch_key in seen_batch_keys:
                        is_duplicate = True
                    seen_batch_keys.add(batch_key)

                    if inv_num:
                        for es in existing_sales:
                            if es.get("invoice_number") and str(es["invoice_number"]).strip().lower() == inv_num.lower() and es["product_id"] == p_id:
                                is_duplicate = True
                                break
                    else:
                        for es in existing_sales:
                            if es["product_id"] == p_id and es.get("source_dataset_id") == dataset_id:
                                is_duplicate = True
                                break

                    if is_duplicate:
                        skipped_count += 1
                        previously_imported_count += 1
                        continue

                    record_sale(
                        product_id=p_id,
                        sale_date=s_date,
                        quantity=qty,
                        unit_price=price,
                        invoice_number=inv_num,
                        customer_name=cust_name,
                        notes=notes_val,
                        source_dataset_id=dataset_id,
                        deduct_inventory=True,
                        conn=conn
                    )
                    recorded_count += 1

                elif sync_purpose == "inventory_adjustments":
                    prod_col = column_mapping.get("product") or column_mapping.get("sku") or column_mapping.get("name")
                    prod_val = str(rec.get(prod_col) or "").strip() if prod_col else ""
                    matched_prod = find_product_by_identifier(prod_val, conn=conn)
                    if not matched_prod:
                        errors.append({"row": row_idx, "message": f"Unmatched product '{prod_val}'"})
                        continue

                    d_col = column_mapping.get("quantity_delta") or column_mapping.get("adjustment") or column_mapping.get("qty")
                    try:
                        delta = round(float(rec.get(d_col) or 0.0), 4) if d_col else 0.0
                        if delta == 0:
                            errors.append({"row": row_idx, "message": "Adjustment delta cannot be zero"})
                            continue
                    except Exception:
                        errors.append({"row": row_idx, "message": "Invalid adjustment delta"})
                        continue

                    reason_col = column_mapping.get("reason")
                    reason_val = str(rec.get(reason_col) or "").strip() if reason_col else "Batch inventory adjustment"

                    ref_col = column_mapping.get("reference")
                    ref_val = str(rec.get(ref_col) or "").strip() if ref_col else "SYNC"

                    record_inventory_movement(
                        product_id=matched_prod["id"],
                        movement_type="adjustment",
                        quantity_delta=delta,
                        reason=reason_val,
                        reference=ref_val,
                        source_dataset_id=dataset_id,
                        conn=conn
                    )
                    recorded_count += 1

                else:  # catalogue (default)
                    name_col = column_mapping.get("name")
                    name_val = str(rec.get(name_col) or "").strip() if name_col else ""
                    if not name_val:
                        errors.append({"row": row_idx, "message": "Product name is missing"})
                        continue

                    sku_col = column_mapping.get("sku")
                    sku_val = str(rec.get(sku_col) or "").strip() if sku_col else None

                    desc_col = column_mapping.get("description")
                    desc_val = str(rec.get(desc_col) or "").strip() if desc_col else None

                    cat_col = column_mapping.get("category")
                    cat_val = str(rec.get(cat_col) or "").strip() if cat_col else None

                    brand_col = column_mapping.get("brand")
                    brand_val = str(rec.get(brand_col) or "").strip() if brand_col else None

                    unit_col = column_mapping.get("unit")
                    unit_val = str(rec.get(unit_col) or "piece").strip().lower() or "piece" if unit_col else "piece"

                    supplier_col = column_mapping.get("supplier")
                    supplier_id = None
                    if supplier_col and rec.get(supplier_col):
                        sup_name = str(rec.get(supplier_col)).strip()
                        if sup_name:
                            sup_record = create_or_get_supplier(sup_name, conn=conn)
                            supplier_id = sup_record.get("id")

                    purchase_price = None
                    p_col = column_mapping.get("purchase_price")
                    if p_col and rec.get(p_col) is not None and str(rec.get(p_col)).strip() != "":
                        try:
                            purchase_price = round(float(rec.get(p_col)), 2)
                            if purchase_price < 0:
                                errors.append({"row": row_idx, "message": "Purchase price cannot be negative"})
                                continue
                        except Exception:
                            errors.append({"row": row_idx, "message": "Invalid purchase price"})
                            continue

                    try:
                        s_col = column_mapping.get("selling_price")
                        selling_price = round(float(rec.get(s_col) or 0.0), 2) if s_col else 0.0
                        if selling_price < 0:
                            errors.append({"row": row_idx, "message": "Selling price cannot be negative"})
                            continue
                    except Exception:
                        errors.append({"row": row_idx, "message": "Invalid selling price"})
                        continue

                    try:
                        st_col = column_mapping.get("opening_stock")
                        opening_stock = round(float(rec.get(st_col) or 0.0), 4) if st_col else 0.0
                        if opening_stock < 0:
                            errors.append({"row": row_idx, "message": "Opening stock cannot be negative"})
                            continue
                    except Exception:
                        errors.append({"row": row_idx, "message": "Invalid opening stock"})
                        continue

                    try:
                        ro_col = column_mapping.get("reorder_level")
                        reorder_level = round(float(rec.get(ro_col) or 0.0), 4) if ro_col else 0.0
                        if reorder_level < 0:
                            errors.append({"row": row_idx, "message": "Reorder level cannot be negative"})
                            continue
                    except Exception:
                        errors.append({"row": row_idx, "message": "Invalid reorder level"})
                        continue

                    # Check if product exists
                    existing_prod = None
                    if sku_val:
                        cur.execute("SELECT * FROM products WHERE LOWER(TRIM(sku)) = LOWER(TRIM(?))", (sku_val,))
                        existing_prod = cur.fetchone()

                    if not existing_prod:
                        cur.execute("SELECT * FROM products WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (name_val,))
                        existing_prod = cur.fetchone()

                    if existing_prod:
                        if duplicate_strategy == "skip_existing":
                            skipped_count += 1
                            continue
                        elif duplicate_strategy == "update_permitted_fields":
                            cur.execute(
                                """
                                UPDATE products SET
                                    description = COALESCE(?, description),
                                    category = COALESCE(?, category),
                                    brand = COALESCE(?, brand),
                                    unit = COALESCE(?, unit),
                                    supplier_id = COALESCE(?, supplier_id),
                                    updated_at = ?
                                WHERE id = ?
                                """,
                                (desc_val, cat_val, brand_val, unit_val, supplier_id, now_str, existing_prod["id"])
                            )
                            updated_count += 1
                            continue

                    # Create new product
                    cur.execute(
                        """
                        INSERT INTO products (
                            sku, name, description, category, brand, unit, supplier_id,
                            purchase_price, selling_price, currency, is_active,
                            created_at, updated_at, source_dataset_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'INR', 1, ?, ?, ?)
                        """,
                        (sku_val, name_val, desc_val, cat_val, brand_val, unit_val, supplier_id,
                         purchase_price, selling_price, now_str, now_str, dataset_id)
                    )
                    new_prod_id = cur.lastrowid

                    cur.execute(
                        """
                        INSERT INTO inventory (product_id, quantity_on_hand, reorder_level, unit, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (new_prod_id, opening_stock, reorder_level, unit_val, now_str)
                    )

                    if opening_stock > 0:
                        cur.execute(
                            """
                            INSERT INTO inventory_movements (
                                product_id, movement_type, quantity_delta, quantity_before, quantity_after,
                                reason, reference, created_at, source_dataset_id
                            ) VALUES (?, 'opening_balance', ?, 0.0, ?, 'Imported spreadsheet opening stock', 'IMPORT', ?, ?)
                            """,
                            (new_prod_id, opening_stock, opening_stock, now_str, dataset_id)
                        )

                    created_count += 1

        return {
            "success": True,
            "dataset_id": dataset_id,
            "sync_purpose": sync_purpose,
            "created_count": created_count,
            "updated_count": updated_count,
            "recorded_transactions": recorded_count,
            "recorded_movements": recorded_count,
            "skipped_count": skipped_count,
            "error_count": len(errors),
            "errors": errors[:50],
            "previously_imported_count": previously_imported_count
        }
    finally:
        if close_after:
            conn.close()


def list_suppliers(is_active: bool = True, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists registered suppliers from SQLite."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM suppliers WHERE is_active = ? ORDER BY name ASC", (1 if is_active else 0,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        if close_after:
            conn.close()


def get_supplier_for_product(target: str, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves product and linked supplier information."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        t = (target or "").strip().rstrip('?.')
        cur.execute(
            """
            SELECT p.id as product_id, p.name as product_name, p.sku as product_sku,
                   s.id as supplier_id, s.name as supplier_name, s.contact_name, s.phone, s.email
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.is_active = 1 AND (LOWER(p.name) LIKE ? OR LOWER(p.sku) = ?)
            LIMIT 1
            """,
            (f"%{t.lower()}%", t.lower())
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if close_after:
            conn.close()


# ==============================================================================
# PURCHASES & SALES LEDGER (STEP 3)
# ==============================================================================

def record_purchase(
    product_id: int,
    purchase_date: str,
    quantity: float,
    unit_price: float,
    supplier_id: Optional[int] = None,
    purchase_number: Optional[str] = None,
    notes: Optional[str] = None,
    currency: str = "INR",
    source_dataset_id: Optional[str] = None,
    update_inventory: bool = True,
    update_last_purchase_rate: bool = True,
    conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Atomically records a procurement purchase transaction.
    - Validates positive quantity and non-negative unit price.
    - Accurately rounds monetary values to 2 decimal places.
    - Optionally creates an inventory movement of type 'receipt' and updates stock on hand.
    - Optionally updates the product's last_purchase_rate and last_purchase_date without corrupting catalog purchase_price.
    """
    if quantity <= 0:
        raise ValueError("Purchase quantity must be strictly greater than zero")
    if unit_price < 0:
        raise ValueError("Purchase unit price cannot be negative")

    quantity = round(float(quantity), 4)
    unit_price = round(float(unit_price), 2)
    total_amount = round(quantity * unit_price, 2)
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clean_date = str(purchase_date).strip() if purchase_date else now_str[:10]

    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        with conn:
            cur = conn.cursor()
            # Verify product exists
            cur.execute("SELECT id, name, unit FROM products WHERE id = ?", (product_id,))
            prod = cur.fetchone()
            if not prod:
                raise ValueError(f"Product with ID {product_id} does not exist")

            # Verify supplier if provided
            if supplier_id:
                cur.execute("SELECT id FROM suppliers WHERE id = ?", (int(supplier_id),))
                if not cur.fetchone():
                    raise ValueError(f"Supplier with ID {supplier_id} does not exist")

            # Insert purchase transaction
            cur.execute(
                """
                INSERT INTO purchases (
                    purchase_number, purchase_date, supplier_id, product_id,
                    quantity, unit_price, total_amount, currency, notes,
                    created_at, source_dataset_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(purchase_number).strip() if purchase_number else None,
                    clean_date,
                    int(supplier_id) if supplier_id else None,
                    product_id,
                    quantity,
                    unit_price,
                    total_amount,
                    str(currency or "INR").strip().upper(),
                    str(notes).strip() if notes else None,
                    now_str,
                    source_dataset_id
                )
            )
            purchase_id = cur.lastrowid

            # Update inventory and record movement if requested
            if update_inventory:
                cur.execute("SELECT quantity_on_hand FROM inventory WHERE product_id = ?", (product_id,))
                inv_row = cur.fetchone()
                current_qty = float(inv_row["quantity_on_hand"]) if inv_row else 0.0
                new_qty = round(current_qty + quantity, 4)

                if inv_row:
                    cur.execute(
                        "UPDATE inventory SET quantity_on_hand = ?, updated_at = ? WHERE product_id = ?",
                        (new_qty, now_str, product_id)
                    )
                else:
                    cur.execute(
                        "INSERT INTO inventory (product_id, quantity_on_hand, reorder_level, unit, updated_at) VALUES (?, ?, 0.0, ?, ?)",
                        (product_id, new_qty, prod["unit"] or "piece", now_str)
                    )

                ref_str = purchase_number or f"PO-{purchase_id}"
                cur.execute(
                    """
                    INSERT INTO inventory_movements (
                        product_id, movement_type, quantity_delta, quantity_before,
                        quantity_after, reason, reference, created_at, source_dataset_id
                    ) VALUES (?, 'receipt', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product_id,
                        quantity,
                        current_qty,
                        new_qty,
                        f"Procurement purchase order ({ref_str})",
                        ref_str,
                        now_str,
                        source_dataset_id
                    )
                )

            # Update last purchase rate and date if requested
            if update_last_purchase_rate:
                cur.execute(
                    """
                    UPDATE products SET
                        last_purchase_rate = ?,
                        last_purchase_date = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (unit_price, clean_date, now_str, product_id)
                )

            cur.execute(
                """
                SELECT pu.*, pr.name as product_name, pr.sku as product_sku, s.name as supplier_name
                FROM purchases pu
                JOIN products pr ON pu.product_id = pr.id
                LEFT JOIN suppliers s ON pu.supplier_id = s.id
                WHERE pu.id = ?
                """,
                (purchase_id,)
            )
            return dict(cur.fetchone())
    finally:
        if close_after:
            conn.close()


def list_purchases(
    product_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Lists recorded purchase transactions with filtering and pagination."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        where_clauses = []
        params = []

        if product_id is not None:
            where_clauses.append("pu.product_id = ?")
            params.append(product_id)

        if supplier_id is not None:
            where_clauses.append("pu.supplier_id = ?")
            params.append(supplier_id)

        if start_date:
            where_clauses.append("pu.purchase_date >= ?")
            params.append(start_date)

        if end_date:
            where_clauses.append("pu.purchase_date <= ?")
            params.append(end_date)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cur.execute(f"SELECT COUNT(*) FROM purchases pu {where_sql}", params)
        total_count = cur.fetchone()[0]

        page = max(1, int(page))
        page_size = max(1, min(200, int(page_size)))
        offset = (page - 1) * page_size

        cur.execute(
            f"""
            SELECT pu.*, pr.name as product_name, pr.sku as product_sku, s.name as supplier_name
            FROM purchases pu
            JOIN products pr ON pu.product_id = pr.id
            LEFT JOIN suppliers s ON pu.supplier_id = s.id
            {where_sql}
            ORDER BY pu.purchase_date DESC, pu.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset]
        )
        rows = [dict(r) for r in cur.fetchall()]

        return {
            "items": rows,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1
        }
    finally:
        if close_after:
            conn.close()


def record_sale(
    product_id: int,
    sale_date: str,
    quantity: float,
    unit_price: float,
    invoice_number: Optional[str] = None,
    customer_name: Optional[str] = None,
    notes: Optional[str] = None,
    currency: str = "INR",
    source_dataset_id: Optional[str] = None,
    deduct_inventory: bool = True,
    conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Atomically records a customer sales transaction.
    - Validates positive quantity and non-negative unit price.
    - If deduct_inventory=True, ensures inventory quantity is sufficient, updates stock,
      and writes an inventory movement of type 'sale'.
    """
    if quantity <= 0:
        raise ValueError("Sale quantity must be strictly greater than zero")
    if unit_price < 0:
        raise ValueError("Sale unit price cannot be negative")

    quantity = round(float(quantity), 4)
    unit_price = round(float(unit_price), 2)
    total_amount = round(quantity * unit_price, 2)
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clean_date = str(sale_date).strip() if sale_date else now_str[:10]

    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    try:
        with conn:
            cur = conn.cursor()
            # Verify product exists
            cur.execute("SELECT id, name, unit FROM products WHERE id = ?", (product_id,))
            prod = cur.fetchone()
            if not prod:
                raise ValueError(f"Product with ID {product_id} does not exist")

            # Check stock if deduct_inventory is True
            if deduct_inventory:
                cur.execute("SELECT quantity_on_hand FROM inventory WHERE product_id = ?", (product_id,))
                inv_row = cur.fetchone()
                current_qty = float(inv_row["quantity_on_hand"]) if inv_row else 0.0

                if current_qty < quantity:
                    raise ValueError(
                        f"Insufficient stock on hand for '{prod['name']}'. Available: {current_qty}, Requested: {quantity}"
                    )

                new_qty = round(current_qty - quantity, 4)
                cur.execute(
                    "UPDATE inventory SET quantity_on_hand = ?, updated_at = ? WHERE product_id = ?",
                    (new_qty, now_str, product_id)
                )

                ref_str = invoice_number or "SALE"
                cur.execute(
                    """
                    INSERT INTO inventory_movements (
                        product_id, movement_type, quantity_delta, quantity_before,
                        quantity_after, reason, reference, created_at, source_dataset_id
                    ) VALUES (?, 'sale', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product_id,
                        -quantity,
                        current_qty,
                        new_qty,
                        f"Sales order fulfillment ({ref_str})",
                        ref_str,
                        now_str,
                        source_dataset_id
                    )
                )

            # Insert sales transaction
            cur.execute(
                """
                INSERT INTO sales (
                    invoice_number, sale_date, product_id,
                    quantity, unit_price, total_amount, currency,
                    customer_name, notes, created_at, source_dataset_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(invoice_number).strip() if invoice_number else None,
                    clean_date,
                    product_id,
                    quantity,
                    unit_price,
                    total_amount,
                    str(currency or "INR").strip().upper(),
                    str(customer_name).strip() if customer_name else None,
                    str(notes).strip() if notes else None,
                    now_str,
                    source_dataset_id
                )
            )
            sale_id = cur.lastrowid

            cur.execute(
                """
                SELECT s.*, pr.name as product_name, pr.sku as product_sku
                FROM sales s
                JOIN products pr ON s.product_id = pr.id
                WHERE s.id = ?
                """,
                (sale_id,)
            )
            return dict(cur.fetchone())
    finally:
        if close_after:
            conn.close()


def list_sales(
    product_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Lists recorded sales transactions with filtering and pagination."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        where_clauses = []
        params = []

        if product_id is not None:
            where_clauses.append("s.product_id = ?")
            params.append(product_id)

        if start_date:
            where_clauses.append("s.sale_date >= ?")
            params.append(start_date)

        if end_date:
            where_clauses.append("s.sale_date <= ?")
            params.append(end_date)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        cur.execute(f"SELECT COUNT(*) FROM sales s {where_sql}", params)
        total_count = cur.fetchone()[0]

        page = max(1, int(page))
        page_size = max(1, min(200, int(page_size)))
        offset = (page - 1) * page_size

        cur.execute(
            f"""
            SELECT s.*, pr.name as product_name, pr.sku as product_sku
            FROM sales s
            JOIN products pr ON s.product_id = pr.id
            {where_sql}
            ORDER BY s.sale_date DESC, s.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset]
        )
        rows = [dict(r) for r in cur.fetchall()]

        return {
            "items": rows,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 1
        }
    finally:
        if close_after:
            conn.close()


def get_product_pricing_summary(product_id: int, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Returns a unified pricing analysis for a product:
    - Base catalog purchase price (standard baseline)
    - Selling price (active list price)
    - Last purchase rate & date (latest procurement cost)
    - Effective gross margin based on catalog purchase price
    - Effective gross margin based on last actual purchase rate (if available)
    - Recent procurement and sales volume counts
    """
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.id, p.sku, p.name, p.currency, p.purchase_price, p.selling_price,
                   p.last_purchase_rate, p.last_purchase_date,
                   i.quantity_on_hand, s.name as supplier_name
            FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.id = ?
            """,
            (product_id,)
        )
        row = cur.fetchone()
        if not row:
            return None

        p = dict(row)
        cat_cost = float(p.get("purchase_price") or 0.0)
        sell_price = float(p.get("selling_price") or 0.0)
        last_rate = float(p.get("last_purchase_rate")) if p.get("last_purchase_rate") is not None else None

        cat_margins = calculate_margins(cat_cost, sell_price)

        last_rate_margins = None
        if last_rate is not None and last_rate > 0:
            last_rate_margins = calculate_margins(last_rate, sell_price)

        # Count total purchases and sales recorded
        cur.execute("SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM purchases WHERE product_id = ?", (product_id,))
        pu_row = cur.fetchone()
        purchase_tx_count = pu_row[0]
        total_purchased_qty = float(pu_row[1])

        cur.execute("SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM sales WHERE product_id = ?", (product_id,))
        sa_row = cur.fetchone()
        sales_tx_count = sa_row[0]
        total_sold_qty = float(sa_row[1])

        return {
            "product_id": p["id"],
            "sku": p["sku"],
            "name": p["name"],
            "currency": p["currency"] or "INR",
            "quantity_on_hand": float(p.get("quantity_on_hand") or 0.0),
            "supplier_name": p.get("supplier_name"),
            "catalog_purchase_price": cat_cost,
            "selling_price": sell_price,
            "last_purchase_rate": last_rate,
            "last_purchase_date": p.get("last_purchase_date"),
            "catalog_margins": cat_margins,
            "last_rate_margins": last_rate_margins,
            "total_purchases_recorded": purchase_tx_count,
            "total_units_purchased": total_purchased_qty,
            "total_sales_recorded": sales_tx_count,
            "total_units_sold": total_sold_qty
        }
    finally:
        if close_after:
            conn.close()


# ==============================================================================
# LOCAL RAG & DOCUMENT INTELLIGENCE PERSISTENCE
# ==============================================================================

def get_inventory_balance(product_id: int, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches the current inventory balance for a product."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM inventory WHERE product_id = ?", (product_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if close_after:
            conn.close()


def save_document_chunks(
    dataset_id: str,
    document_name: Any,
    document_type: Optional[str] = None,
    chunks: Optional[List[Dict[str, Any]]] = None,
    source_hash: Optional[str] = None,
    embedding_provider: str = "sklearn_tfidf_cosine",
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Transactionally persists extracted chunks and updates the document index status.
    Removes any obsolete prior chunks for this dataset_id.
    Accepts flexible argument ordering: (dataset_id, chunks, ...) or (dataset_id, doc_name, doc_type, chunks, source_hash, ...).
    """
    if isinstance(document_name, list):
        chunks = document_name
        first_c = chunks[0] if chunks else {}
        document_name = first_c.get("document_name", "document")
        document_type = first_c.get("document_type", "doc")
        source_hash = first_c.get("source_hash", "hash")

    chunks = chunks or []
    document_name = document_name or "document"
    document_type = document_type or "doc"
    source_hash = source_hash or "hash"

    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with conn:
            cur = conn.cursor()
            # 1. Clean previous chunks for this dataset
            cur.execute("DELETE FROM document_chunks WHERE dataset_id = ?", (dataset_id,))

            # 2. Insert new chunks
            batch = []
            for idx, ch in enumerate(chunks):
                chunk_id = ch.get("id") or f"chk_{uuid.uuid4().hex[:12]}"
                text = (ch.get("chunk_text") or ch.get("text") or "").strip()
                page_no = ch.get("page_number")
                sheet = ch.get("sheet_name")
                row_rng = ch.get("row_range")
                emb_json = safe_json_dumps(ch.get("embedding")) if ch.get("embedding") else None
                char_c = len(text)
                token_c = len(text.split())
                doc_n = ch.get("document_name") or document_name
                doc_t = ch.get("document_type") or document_type
                src_h = ch.get("source_hash") or source_hash

                batch.append((
                    chunk_id, dataset_id, doc_n, doc_t,
                    idx, text, page_no, sheet, row_rng, src_h,
                    char_c, token_c, emb_json, now_str, 1
                ))

            if batch:
                cur.executemany(
                    """
                    INSERT INTO document_chunks (
                        id, dataset_id, document_name, document_type,
                        chunk_index, chunk_text, page_number, sheet_name, row_range,
                        source_hash, char_count, token_count, embedding_json,
                        created_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch
                )

            # 3. Update or insert document index
            cur.execute(
                """
                INSERT INTO document_indexes (
                    dataset_id, status, chunk_count, error_message,
                    embedding_provider, indexed_at, updated_at
                ) VALUES (?, 'indexed', ?, NULL, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    status = 'indexed',
                    chunk_count = excluded.chunk_count,
                    error_message = NULL,
                    embedding_provider = excluded.embedding_provider,
                    updated_at = excluded.updated_at
                """,
                (dataset_id, len(batch), embedding_provider, now_str, now_str)
            )
            conn.commit()

        return {
            "success": True,
            "dataset_id": dataset_id,
            "chunk_count": len(chunks),
            "status": "indexed",
            "indexed_at": now_str
        }
    finally:
        if close_after:
            conn.close()


def update_document_index_status(
    dataset_id: str,
    status: str,
    error_message: Optional[str] = None,
    chunk_count: int = 0,
    embedding_provider: str = "sklearn_tfidf_cosine",
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None
) -> None:
    """Updates the indexing status (e.g. pending, indexing, failed, empty_ocr_required)."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO document_indexes (
                    dataset_id, status, chunk_count, error_message,
                    embedding_provider, indexed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                    status = excluded.status,
                    chunk_count = excluded.chunk_count,
                    error_message = excluded.error_message,
                    embedding_provider = excluded.embedding_provider,
                    updated_at = excluded.updated_at
                """,
                (dataset_id, status, chunk_count, error_message, embedding_provider, now_str, now_str)
            )
            conn.commit()
    finally:
        if close_after:
            conn.close()


def get_document_index_status(dataset_id: str, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns the index status for a specific dataset."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT di.*, d.original_filename, d.file_type, d.file_hash_sha256, d.file_size_bytes
            FROM document_indexes di
            JOIN datasets d ON di.dataset_id = d.id
            WHERE di.dataset_id = ?
            """,
            (dataset_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if close_after:
            conn.close()


def list_document_indexes(conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns all document index records joined with dataset metadata."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 
                d.id as dataset_id,
                d.original_filename,
                d.file_type,
                d.file_size_bytes,
                d.dataset_type,
                d.created_at as uploaded_at,
                COALESCE(di.status, 'unindexed') as index_status,
                COALESCE(di.chunk_count, 0) as chunk_count,
                di.error_message,
                di.embedding_provider,
                di.indexed_at
            FROM datasets d
            LEFT JOIN document_indexes di ON d.id = di.dataset_id
            WHERE d.status = 'active'
            ORDER BY d.created_at DESC
            """
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if close_after:
            conn.close()


def get_document_chunks(
    dataset_id: Optional[str] = None,
    is_active_only: bool = True,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetches chunks for a dataset or across all active indexed documents."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        cur = conn.cursor()
        query = "SELECT * FROM document_chunks WHERE 1=1"
        params: List[Any] = []
        if dataset_id:
            query += " AND dataset_id = ?"
            params.append(dataset_id)
        if is_active_only:
            query += " AND is_active = 1"
        query += " ORDER BY dataset_id, chunk_index ASC"

        cur.execute(query, params)
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("embedding_json"):
                d["embedding"] = safe_json_loads(d["embedding_json"])
            result.append(d)
        return result
    finally:
        if close_after:
            conn.close()


def delete_document_index(dataset_id: str, conn: Optional[sqlite3.Connection] = None, db_path: Optional[str] = None) -> bool:
    """Safely removes chunks and index records for a dataset."""
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        with conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM document_chunks WHERE dataset_id = ?", (dataset_id,))
            cur.execute("DELETE FROM document_indexes WHERE dataset_id = ?", (dataset_id,))
            conn.commit()
            return True
    finally:
        if close_after:
            conn.close()


def check_database_health(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Performs a lightweight, non-blocking health check on SQLite database.
    Returns status: 'connected' | 'error', latency_ms, and product/dataset counts.
    """
    t0 = time.time()
    try:
        conn = get_connection(db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1;")
            cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM products WHERE is_active = 1;")
            prod_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM datasets;")
            ds_count = cur.fetchone()[0]
            latency_ms = round((time.time() - t0) * 1000, 2)
            return {
                "status": "connected",
                "healthy": True,
                "connected": True,
                "latency_ms": latency_ms,
                "active_products": prod_count,
                "total_datasets": ds_count,
                "db_path": db_path or get_db_path(),
                "message": f"SQLite database connected ({latency_ms}ms)."
            }
        finally:
            conn.close()
    except Exception as e:
        latency_ms = round((time.time() - t0) * 1000, 2)
        return {
            "status": "error",
            "healthy": False,
            "connected": False,
            "latency_ms": latency_ms,
            "error": str(e),
            "message": f"SQLite database connection failed: {e}"
        }






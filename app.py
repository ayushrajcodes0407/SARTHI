import os
import sys
import re
import time
import datetime
import platform
import psutil
import requests
import pyjokes
import wikipedia
import qrcode
import io
import logging
import pandas as pd
import pymupdf
from flask import Flask, request, jsonify, send_from_directory, Response
import business_insights
import database
import intent_router
import local_llm
import rag_engine

# Initialize SQLite Persistent Database
try:
    database.init_db()
except Exception as _db_init_err:
    logging.getLogger("VANTIQ-DataImport").error(f"Failed to initialize SQLite database: {_db_init_err}")

app = Flask(__name__, static_folder='web', static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB upload limit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VANTIQ-DataImport")

# In-memory storage for the latest analyzed business intelligence report
CURRENT_BI_REPORT = None
CURRENT_FILE_INFO = None

@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({
        "success": False,
        "error": "File exceeds the 10 MB maximum upload size limit."
    }), 413

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Static routes for assets
@app.route('/')
def index():
    return send_from_directory('web', 'index.html')

@app.route('/UI/<path:filename>')
def serve_ui(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'UI'), filename)

@app.route('/Images/<path:filename>')
def serve_images(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'Images'), filename)

@app.route('/QrCodes/<path:filename>')
def serve_qrcodes(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'QrCodes'), filename)

# API Endpoints
@app.route('/api/status', methods=['GET'])
def get_status():
    now = datetime.datetime.now()
    cpu_usage = psutil.cpu_percent(interval=None) if hasattr(psutil, 'cpu_percent') else 15.0
    ram = psutil.virtual_memory() if hasattr(psutil, 'virtual_memory') else None
    ram_usage = ram.percent if ram else 50.0
    
    battery = None
    if hasattr(psutil, 'sensors_battery'):
        batt = psutil.sensors_battery()
        if batt:
            battery = {
                "percent": batt.percent,
                "power_plugged": batt.power_plugged
            }

    db_health = database.check_database_health()
    llm_health = local_llm.check_ollama_health(timeout=1.5)

    rag_health = {}
    try:
        rag_summary = rag_engine.get_rag_status_summary()
        rag_health = {
            "status": "online" if rag_summary.get("total_documents", 0) >= 0 else "offline",
            "label": "DOCUMENT RAG",
            "healthy": True,
            "total_documents": rag_summary.get("total_documents", 0),
            "total_chunks": rag_summary.get("total_chunks", 0),
            "total_tokens": rag_summary.get("total_tokens", 0)
        }
    except Exception as _rag_err:
        rag_health = {
            "status": "degraded",
            "label": "DOCUMENT RAG",
            "healthy": False,
            "error": str(_rag_err)
        }

    db_ok = db_health.get("connected", False) or db_health.get("healthy", False)
    llm_ok = llm_health.get("status") in ("online", "busy")
    if db_ok and llm_ok:
        sys_status = "ONLINE"
    elif db_ok:
        sys_status = "OPERATIONAL"
    else:
        sys_status = "DEGRADED"

    return jsonify({
        "status": sys_status,
        "assistant": "SARTHI — AI-Powered Business Intelligence Platform",
        "system": platform.system(),
        "release": platform.release(),
        "processor": platform.processor() or "Stark Quantum Arc Core",
        "python_version": platform.python_version(),
        "time": now.strftime("%I:%M:%S %p"),
        "date": now.strftime("%A, %B %d, %Y"),
        "cpu": cpu_usage,
        "ram": ram_usage,
        "battery": battery,
        "active_workspace": BASE_DIR,
        "subsystems": {
            "api": {
                "status": "online",
                "label": "API GATEWAY",
                "healthy": True
            },
            "database": {
                "status": "online" if db_ok else "offline",
                "label": "SQLITE STORAGE",
                "healthy": db_ok,
                "products_count": db_health.get("active_products", db_health.get("products_count", 0)),
                "datasets_count": db_health.get("total_datasets", db_health.get("datasets_count", 0))
            },
            "local_llm": {
                "status": llm_health.get("status"),
                "label": f"LOCAL AI ({llm_health.get('configured_model', 'qwen3:4b-instruct')})",
                "healthy": llm_ok,
                "model": llm_health.get("configured_model"),
                "service_running": llm_health.get("service_running"),
                "model_available": llm_health.get("model_available"),
                "latency_ms": llm_health.get("latency_ms"),
                "message": llm_health.get("message")
            },
            "voice_engine": {
                "status": "ready",
                "label": "VOICE SYNTHESIS",
                "healthy": True
            },
            "rag": rag_health
        },
        "database": db_health,
        "local_llm": {
            "status": llm_health.get("status"),
            "model": llm_health.get("configured_model"),
            "service_running": llm_health.get("service_running"),
            "model_available": llm_health.get("model_available"),
            "latency_ms": llm_health.get("latency_ms"),
            "message": llm_health.get("message")
        },
        "rag": rag_health
    })

@app.route('/api/llm/status', methods=['GET'])
def get_llm_status():
    """
    Returns the real-time health check, reachability, and model availability
    for the local Ollama instance (qwen3:4b-instruct).
    Zero external calls, 100% loopback offline verification.
    """
    health = local_llm.check_ollama_health()
    return jsonify(health)

@app.route('/api/system', methods=['GET'])
def get_system():
    cpu = psutil.cpu_percent(interval=None)
    cpu_freq = psutil.cpu_freq() if hasattr(psutil, 'cpu_freq') else None
    mem = psutil.virtual_memory()
    disk_used_gb, disk_total_gb, disk_percent = 0, 0, 0
    try:
        import shutil
        total, used, free = shutil.disk_usage('/')
        disk_used_gb = round(used / (1024**3), 2)
        disk_total_gb = round(total / (1024**3), 2)
        disk_percent = round((used / total) * 100, 1)
    except Exception:
        pass
    battery_info = "Not Detected"
    if hasattr(psutil, 'sensors_battery'):
        b = psutil.sensors_battery()
        if b:
            status = "Plugged In" if b.power_plugged else "On Battery"
            battery_info = f"{b.percent}% ({status})"
            
    return jsonify({
        "cpu_percent": cpu,
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_freq_mhz": round(cpu_freq.current, 1) if cpu_freq else "N/A",
        "ram_used_gb": round(mem.used / (1024**3), 2),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "ram_percent": mem.percent,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_percent": disk_percent,
        "battery": battery_info
    })


@app.route('/api/joke', methods=['GET'])
def get_joke():
    try:
        joke = pyjokes.get_joke()
        return jsonify({"joke": joke, "status": "success"})
    except Exception as e:
        return jsonify({"joke": "Why do programmers prefer dark mode? Because light attracts bugs.", "status": "fallback"})

@app.route('/api/wikipedia', methods=['GET'])
def get_wikipedia():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify({"error": "No query specified"}), 400
    try:
        summary = wikipedia.summary(query, sentences=3)
        return jsonify({"query": query, "summary": summary, "status": "success"})
    except wikipedia.exceptions.DisambiguationError as e:
        try:
            summary = wikipedia.summary(e.options[0], sentences=3)
            return jsonify({"query": e.options[0], "summary": summary, "status": "disambiguated"})
        except Exception:
            return jsonify({"error": "Multiple topics found", "options": e.options[:5]}), 200
    except Exception as e:
        return jsonify({"error": str(e), "summary": f"Could not locate Wikipedia intelligence for '{query}'."}), 200

@app.route('/api/covid', methods=['GET'])
def get_covid():
    req_state = request.args.get('state', 'delhi').strip().lower()
    from state import state as state_map
    
    # Match state
    matched_state = None
    for k, v in state_map.items():
        if k in req_state or req_state in k:
            matched_state = v
            break
            
    if not matched_state:
        matched_state = "Delhi"
        
    try:
        from covid_india import states
        data = states.getdata()
        if matched_state in data:
            st_data = data[matched_state]
            return jsonify({
                "state": matched_state,
                "total": st_data.get("Total", "N/A"),
                "active": st_data.get("Active", "N/A"),
                "cured": st_data.get("Cured", "N/A"),
                "death": st_data.get("Death", "N/A"),
                "status": "success"
            })
    except Exception as e:
        pass
        
    return jsonify({
        "state": matched_state,
        "total": "Historical Record",
        "active": "0 (Stabilized)",
        "cured": "All Records Clear",
        "death": "N/A",
        "note": "Live Ministry health stats archived; regional condition normal.",
        "status": "archived"
    })

@app.route('/api/contacts', methods=['GET', 'POST'])
def manage_contacts():
    contacts_file = os.path.join(BASE_DIR, 'Contacts.txt')
    
    if request.method == 'POST':
        data = request.json or {}
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        if not name or not phone:
            return jsonify({"error": "Name and phone required"}), 400
        try:
            with open(contacts_file, 'a', encoding='utf-8') as f:
                f.write(f'\n"{name}":"{phone}"')
            return jsonify({"status": "added", "name": name, "phone": phone})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    # GET list
    contacts = []
    if os.path.exists(contacts_file):
        with open(contacts_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if ':' in line:
                    parts = line.split(':', 1)
                    c_name = parts[0].replace('"', '').strip()
                    c_phone = parts[1].replace('"', '').strip()
                    if c_name and c_phone:
                        contacts.append({"name": c_name, "phone": c_phone})
    return jsonify({"contacts": contacts, "total": len(contacts)})

@app.route('/api/data-import', methods=['POST'])
@app.route('/api/import-data', methods=['POST'])
def import_business_data():
    global CURRENT_BI_REPORT, CURRENT_FILE_INFO
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file field in request. Please upload a file with the key 'file'."}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({"success": False, "error": "No file selected. Please select an Excel (.xlsx, .xls), CSV (.csv), or PDF (.pdf) file."}), 400

    orig_filename = os.path.basename(file.filename)
    _, ext = os.path.splitext(orig_filename)
    ext = ext.lower().lstrip('.')

    allowed_extensions = {'xlsx', 'xls', 'pdf', 'csv'}
    if ext not in allowed_extensions:
        return jsonify({
            "success": False,
            "error": f"Unsupported file format '.{ext}'. Supported formats: XLSX, XLS, CSV, PDF."
        }), 400

    try:
        file_bytes = file.read()
    except Exception as e:
        logger.warning(f"Failed to read uploaded file: {e}")
        return jsonify({"success": False, "error": "Could not read uploaded file content."}), 400

    # Validate non-empty
    if len(file_bytes) == 0:
        return jsonify({"success": False, "error": "Uploaded file is empty (0 bytes)."}), 400

    # Validate max upload size (10 MB)
    if len(file_bytes) > 10 * 1024 * 1024:
        return jsonify({"success": False, "error": "File exceeds the 10 MB maximum upload size limit."}), 413

    # SHA-256 Deduplication check
    file_hash = database.compute_sha256(file_bytes)
    force_reimport = request.form.get('force_reimport', '').lower() in {'true', '1', 'yes'}
    existing_ds = database.find_dataset_by_hash(file_hash)

    if existing_ds and not force_reimport:
        saved_rep = database.get_latest_report_for_dataset(existing_ds["id"])
        CURRENT_BI_REPORT = saved_rep["report_content"] if saved_rep else None
        CURRENT_FILE_INFO = {"bytes": file_bytes, "filename": existing_ds["original_filename"], "ext": existing_ds["file_type"], "dataset_id": existing_ds["id"]}

        full_ds = database.get_dataset_by_id(existing_ds["id"])
        sheets_data = full_ds.get("sheets", []) if full_ds else []
        summary = existing_ds.get("extraction_summary") or {
            "sheet_count": existing_ds.get("sheet_count"),
            "total_rows": existing_ds.get("row_count"),
            "total_columns": existing_ds.get("column_count"),
            "page_count": existing_ds.get("page_count")
        }

        idx_stat = database.get_document_index_status(existing_ds["id"])
        resp_data = {
            "success": True,
            "is_duplicate": True,
            "dataset_id": existing_ds["id"],
            "file_name": existing_ds["original_filename"],
            "file_type": existing_ds["file_type"],
            "summary": summary,
            "report": CURRENT_BI_REPORT,
            "index_status": idx_stat.get("status") if idx_stat else "unindexed",
            "chunk_count": idx_stat.get("chunk_count", 0) if idx_stat else 0,
            "message": f"Identical file already exists in persistent database (Dataset ID: {existing_ds['id']}). Loaded existing dataset without re-processing."
        }
        if sheets_data:
            resp_data["sheets"] = sheets_data
        if existing_ds["file_type"] == 'pdf':
            resp_data["text_preview"] = summary.get("text_preview", "")
        return jsonify(resp_data), 200

    # ==========================
    # 1. EXCEL & CSV PROCESSING
    # ==========================
    if ext in {'xlsx', 'xls', 'csv'}:
        sheet_data = []
        total_rows = 0
        max_cols = 0

        if ext == 'csv':
            try:
                try:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding='latin1')
            except Exception as exc:
                logger.warning(f"CSV parsing failure for {orig_filename}: {exc}")
                return jsonify({"success": False, "error": "Failed to parse CSV file. The file may be malformed."}), 400

            cols = [str(c).strip() if not pd.isna(c) else f"Column_{i+1}" for i, c in enumerate(df.columns)]
            df.columns = cols
            row_count = len(df)
            col_count = len(cols)
            total_rows = row_count
            max_cols = col_count

            all_rows = []
            for _, row in df.iterrows():
                row_dict = {}
                for col in cols:
                    val = row[col]
                    if pd.isna(val):
                        row_dict[col] = None
                    elif hasattr(val, 'isoformat'):
                        row_dict[col] = val.isoformat()
                    elif isinstance(val, (int, float, str, bool)):
                        row_dict[col] = val
                    else:
                        row_dict[col] = str(val)
                all_rows.append(row_dict)

            preview_rows = all_rows[:10]
            sheet_data.append({
                "sheet_name": "Sheet1",
                "row_count": row_count,
                "columns": cols,
                "preview_rows": preview_rows,
                "all_rows": all_rows
            })
        else:
            # Magic byte check
            if ext == 'xlsx' and not file_bytes.startswith(b'PK\x03\x04'):
                return jsonify({"success": False, "error": "Corrupted or invalid XLSX file (invalid signature)."}), 400
            if ext == 'xls' and not file_bytes.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
                return jsonify({"success": False, "error": "Corrupted or invalid XLS file (invalid OLE signature)."}), 400

            engine = 'openpyxl' if ext == 'xlsx' else 'xlrd'
            try:
                excel_file = pd.ExcelFile(io.BytesIO(file_bytes), engine=engine)
            except Exception as exc:
                logger.warning(f"Excel parsing failure for {orig_filename}: {exc}")
                return jsonify({"success": False, "error": "Failed to parse Excel file. The file may be corrupted or malformed."}), 400

            try:
                for sheet_name in excel_file.sheet_names:
                    try:
                        df = pd.read_excel(excel_file, sheet_name=sheet_name)
                    except Exception as sheet_err:
                        logger.warning(f"Error reading sheet '{sheet_name}': {sheet_err}")
                        continue

                    # Preserve and sanitize original column names
                    cols = [str(c).strip() if not pd.isna(c) else f"Column_{i+1}" for i, c in enumerate(df.columns)]
                    df.columns = cols

                    row_count = len(df)
                    col_count = len(cols)
                    total_rows += row_count
                    if col_count > max_cols:
                        max_cols = col_count

                    # Extract all rows safely for persistence
                    all_rows = []
                    for _, row in df.iterrows():
                        row_dict = {}
                        for col in cols:
                            val = row[col]
                            if pd.isna(val):
                                row_dict[col] = None
                            elif hasattr(val, 'isoformat'):
                                row_dict[col] = val.isoformat()
                            elif isinstance(val, (int, float, str, bool)):
                                row_dict[col] = val
                            else:
                                row_dict[col] = str(val)
                        all_rows.append(row_dict)

                    preview_rows = all_rows[:10]

                    sheet_data.append({
                        "sheet_name": str(sheet_name),
                        "row_count": row_count,
                        "columns": cols,
                        "preview_rows": preview_rows,
                        "all_rows": all_rows
                    })
            except Exception as iter_err:
                logger.warning(f"Error processing sheets: {iter_err}")
                return jsonify({"success": False, "error": "Error extracting worksheets from Excel document."}), 400

        if not sheet_data:
            return jsonify({"success": False, "error": "The spreadsheet contains no readable worksheets or data."}), 400

        # Perform Deep Business Intelligence Analysis
        try:
            bi_report = business_insights.analyze_excel_dataset(file_bytes, orig_filename, ext)
            CURRENT_BI_REPORT = bi_report
        except Exception as bi_err:
            logger.warning(f"BI analysis error on {ext} file: {bi_err}")
            bi_report = None

        # Persist Excel dataset to SQLite
        dataset_id = None
        try:
            persisted = database.save_excel_dataset(
                file_bytes=file_bytes,
                original_filename=orig_filename,
                file_type=ext,
                sha256_hash=file_hash,
                sheets_data=sheet_data,
                bi_report=bi_report
            )
            dataset_id = persisted.get("dataset_id")
        except Exception as p_err:
            logger.error(f"Persistence error for Excel dataset: {p_err}")

        CURRENT_FILE_INFO = {"bytes": file_bytes, "filename": orig_filename, "ext": ext, "dataset_id": dataset_id}

        # Clean all_rows from HTTP response
        clean_sheets = []
        for s in sheet_data:
            clean_s = {k: v for k, v in s.items() if k != "all_rows"}
            clean_sheets.append(clean_s)

        # Index dataset for local RAG intelligence
        idx_res = {}
        if dataset_id:
            try:
                idx_res = rag_engine.index_dataset(dataset_id)
            except Exception as _idx_err:
                logger.warning(f"RAG indexing warning for dataset {dataset_id}: {_idx_err}")

        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            "file_name": orig_filename,
            "file_type": ext,
            "index_status": idx_res.get("status", "unindexed"),
            "chunk_count": idx_res.get("chunk_count", 0),
            "summary": {
                "sheet_count": len(sheet_data),
                "total_rows": total_rows,
                "total_columns": max_cols
            },
            "sheets": clean_sheets,
            "report": bi_report,
            "message": "File processed and business intelligence report generated successfully."
        }), 200

    # ==========================
    # 2. PDF PROCESSING
    # ==========================
    elif ext == 'pdf':
        if not file_bytes.startswith(b'%PDF-'):
            return jsonify({"success": False, "error": "Corrupted or invalid PDF file (invalid header)."}), 400

        try:
            doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        except Exception as pdf_err:
            logger.warning(f"PDF open error: {pdf_err}")
            return jsonify({"success": False, "error": "Failed to parse PDF file. The file may be corrupted."}), 400

        try:
            if doc.is_encrypted:
                doc.close()
                return jsonify({
                    "success": False,
                    "error": "Password-protected or encrypted PDFs are not supported."
                }), 400

            page_count = len(doc)
            extracted_pages_text = []
            total_chars = 0

            for page_idx in range(page_count):
                page = doc[page_idx]
                text = page.get_text()
                if text:
                    cleaned_text = text.strip()
                    if cleaned_text:
                        extracted_pages_text.append(cleaned_text)
                        total_chars += len(cleaned_text)

            doc.close()
        except Exception as proc_err:
            try:
                doc.close()
            except Exception:
                pass
            logger.warning(f"PDF extraction error: {proc_err}")
            return jsonify({"success": False, "error": f"Error extracting PDF text: {str(proc_err)}"}), 400

        has_text = total_chars > 0
        full_text = "\n\n".join(extracted_pages_text).strip()
        preview_text = full_text[:2000] if has_text else ""

        message = (
            "PDF processed successfully."
            if has_text
            else "PDF processed successfully. Note: No readable text detected. The document may be a scanned image or empty requiring OCR."
        )

        # Perform PDF Document Analysis
        try:
            bi_report = business_insights.analyze_pdf_document(file_bytes, orig_filename)
            CURRENT_BI_REPORT = bi_report
        except Exception as bi_err:
            logger.warning(f"BI analysis error on PDF file: {bi_err}")
            bi_report = None

        # Persist PDF dataset to SQLite
        dataset_id = None
        try:
            persisted = database.save_pdf_dataset(
                file_bytes=file_bytes,
                original_filename=orig_filename,
                sha256_hash=file_hash,
                page_count=page_count,
                char_count=total_chars,
                has_text=has_text,
                text_preview=preview_text,
                bi_report=bi_report
            )
            dataset_id = persisted.get("dataset_id")
        except Exception as p_err:
            logger.error(f"Persistence error for PDF dataset: {p_err}")

        CURRENT_FILE_INFO = {"bytes": file_bytes, "filename": orig_filename, "ext": ext, "dataset_id": dataset_id}

        # Index PDF dataset for local RAG intelligence
        idx_res = {}
        if dataset_id:
            try:
                idx_res = rag_engine.index_dataset(dataset_id)
            except Exception as _idx_err:
                logger.warning(f"RAG indexing warning for PDF dataset {dataset_id}: {_idx_err}")

        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            "file_name": orig_filename,
            "file_type": "pdf",
            "index_status": idx_res.get("status", "unindexed"),
            "chunk_count": idx_res.get("chunk_count", 0),
            "summary": {
                "page_count": page_count,
                "char_count": total_chars,
                "has_text": has_text
            },
            "text_preview": preview_text,
            "report": bi_report,
            "message": message
        }), 200

    return jsonify({"success": False, "error": "Unsupported file format."}), 400

@app.route('/api/generate-report', methods=['GET', 'POST'])
@app.route('/api/report', methods=['GET'])
def generate_report():
    global CURRENT_BI_REPORT, CURRENT_FILE_INFO

    # 1. Direct file upload in POST
    if request.method == 'POST' and 'file' in request.files:
        file = request.files['file']
        if file and file.filename != '':
            orig_filename = os.path.basename(file.filename)
            _, ext = os.path.splitext(orig_filename)
            ext = ext.lower().lstrip('.')
            if ext not in {'xlsx', 'xls', 'pdf', 'csv'}:
                return jsonify({
                    "success": False,
                    "error": f"Unsupported file format '.{ext}'. Supported formats: XLSX, XLS, CSV, PDF."
                }), 400

            try:
                file_bytes = file.read()
            except Exception as e:
                return jsonify({"success": False, "error": "Could not read uploaded file content."}), 400

            if len(file_bytes) == 0:
                return jsonify({"success": False, "error": "Uploaded file is empty (0 bytes)."}), 400

            if len(file_bytes) > 10 * 1024 * 1024:
                return jsonify({"success": False, "error": "File exceeds the 10 MB maximum upload size limit."}), 413

            try:
                if ext in {'xlsx', 'xls', 'csv'}:
                    bi_report = business_insights.analyze_excel_dataset(file_bytes, orig_filename, ext)
                else:
                    bi_report = business_insights.analyze_pdf_document(file_bytes, orig_filename)

                CURRENT_FILE_INFO = {"bytes": file_bytes, "filename": orig_filename, "ext": ext}
                CURRENT_BI_REPORT = bi_report
                return jsonify({
                    "success": True,
                    "report": bi_report,
                    "message": "Report generated successfully."
                }), 200
            except Exception as exc:
                logger.warning(f"Report generation failure: {exc}")
                return jsonify({"success": False, "error": f"Failed to generate report: {str(exc)}"}), 500

    # 2. Existing cached report
    if CURRENT_BI_REPORT is not None:
        return jsonify({
            "success": True,
            "report": CURRENT_BI_REPORT,
            "message": "Report retrieved successfully."
        }), 200

    # 3. Regenerate from cached file if report was None
    if CURRENT_FILE_INFO is not None:
        try:
            ext = CURRENT_FILE_INFO["ext"]
            if ext in {'xlsx', 'xls', 'csv'}:
                bi_report = business_insights.analyze_excel_dataset(
                    CURRENT_FILE_INFO["bytes"], CURRENT_FILE_INFO["filename"], ext
                )
            else:
                bi_report = business_insights.analyze_pdf_document(
                    CURRENT_FILE_INFO["bytes"], CURRENT_FILE_INFO["filename"]
                )
            CURRENT_BI_REPORT = bi_report
            return jsonify({
                "success": True,
                "report": bi_report,
                "message": "Report generated successfully."
            }), 200
        except Exception as exc:
            logger.warning(f"Regeneration failure: {exc}")
            return jsonify({"success": False, "error": f"Failed to generate report: {str(exc)}"}), 500

    # 4. No file imported yet
    return jsonify({
        "success": False,
        "error": "No file currently imported. Please import an Excel or PDF file first."
    }), 400

@app.route('/api/bi-report', methods=['GET'])
def get_bi_report():
    global CURRENT_BI_REPORT
    if CURRENT_BI_REPORT is None:
        return jsonify({
            "success": False,
            "error": "No business intelligence dataset has been analyzed yet. Please upload an Excel or PDF document first."
        }), 404
    return jsonify({
        "success": True,
        "report": CURRENT_BI_REPORT
    }), 200

@app.route('/api/export-report', methods=['GET'])
def export_bi_report():
    global CURRENT_BI_REPORT
    if CURRENT_BI_REPORT is None:
        return jsonify({
            "success": False,
            "error": "No business dataset currently analyzed. Please upload an Excel or PDF document first."
        }), 404

    export_format = request.args.get('format', 'html').strip().lower()
    raw_name = CURRENT_BI_REPORT.get("file_name", "dataset")
    safe_name = "".join(c for c in raw_name if c.isalnum() or c in ('_', '-')) or "dataset"

    if export_format == 'json':
        resp = jsonify(CURRENT_BI_REPORT)
        resp.headers['Content-Disposition'] = f'attachment; filename="sarthi_bi_report_{safe_name}.json"'
        return resp

    elif export_format == 'csv':
        csv_str = business_insights.export_report_to_csv(CURRENT_BI_REPORT)
        return Response(
            csv_str,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename="sarthi_bi_report_{safe_name}.csv"'}
        )

    elif export_format == 'html':
        html_str = business_insights.export_report_to_html(CURRENT_BI_REPORT)
        return Response(
            html_str,
            mimetype='text/html',
            headers={'Content-Disposition': f'attachment; filename="sarthi_bi_report_{safe_name}.html"'}
        )

    else:
        return jsonify({
            "success": False,
            "error": f"Invalid export format '{export_format}'. Supported formats: html, csv, json."
        }), 400

# ==============================================================================
# PERSISTENT DATASET & REPORT APIS
# ==============================================================================

@app.route('/api/datasets', methods=['GET'])
def get_datasets():
    """Returns a paginated list of saved datasets."""
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid pagination parameters."}), 400

    search = request.args.get('search', '').strip()
    file_type = request.args.get('file_type', '').strip() or None

    try:
        data = database.list_datasets(page=page, page_size=page_size, search=search, file_type=file_type)
        return jsonify({"success": True, **data}), 200
    except Exception as e:
        logger.error(f"Error listing datasets: {e}")
        return jsonify({"success": False, "error": "Failed to retrieve dataset library."}), 500

@app.route('/api/datasets/<dataset_id>', methods=['GET'])
def get_dataset_details(dataset_id):
    """Returns metadata, worksheets, and summary for a dataset."""
    try:
        ds = database.get_dataset_by_id(dataset_id)
        if not ds:
            return jsonify({"success": False, "error": f"Dataset '{dataset_id}' not found."}), 404
        return jsonify({"success": True, "dataset": ds}), 200
    except Exception as e:
        logger.error(f"Error fetching dataset {dataset_id}: {e}")
        return jsonify({"success": False, "error": "Failed to fetch dataset details."}), 500

@app.route('/api/datasets/<dataset_id>/data', methods=['GET'])
def get_dataset_records(dataset_id):
    """Returns paginated structured records for an Excel dataset."""
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 50))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid pagination parameters."}), 400

    sheet_name = request.args.get('sheet', '').strip() or None

    # Check dataset existence
    ds = database.get_dataset_by_id(dataset_id)
    if not ds:
        return jsonify({"success": False, "error": f"Dataset '{dataset_id}' not found."}), 404

    try:
        data = database.get_dataset_records(dataset_id, sheet_name=sheet_name, page=page, page_size=page_size)
        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            **data
        }), 200
    except Exception as e:
        logger.error(f"Error fetching records for {dataset_id}: {e}")
        return jsonify({"success": False, "error": "Failed to retrieve structured records."}), 500

@app.route('/api/datasets/<dataset_id>/reports', methods=['GET'])
def get_dataset_reports(dataset_id):
    """Returns available analysis runs and saved reports for a dataset."""
    ds = database.get_dataset_by_id(dataset_id)
    if not ds:
        return jsonify({"success": False, "error": f"Dataset '{dataset_id}' not found."}), 404

    try:
        reports = database.get_dataset_reports(dataset_id)
        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            "reports": reports
        }), 200
    except Exception as e:
        logger.error(f"Error fetching reports for {dataset_id}: {e}")
        return jsonify({"success": False, "error": "Failed to retrieve reports."}), 500

@app.route('/api/reports/<report_id>', methods=['GET'])
def get_single_report(report_id):
    """Returns a specific saved report by report_id."""
    try:
        rep = database.get_report_by_id(report_id)
        if not rep:
            return jsonify({"success": False, "error": f"Report '{report_id}' not found."}), 404
        return jsonify({"success": True, "report": rep}), 200
    except Exception as e:
        logger.error(f"Error retrieving report {report_id}: {e}")
        return jsonify({"success": False, "error": "Failed to retrieve saved report."}), 500

@app.route('/api/datasets/<dataset_id>/open', methods=['POST'])
def open_saved_dataset(dataset_id):
    """Sets a previously imported dataset as the active dataset in VANTIQ."""
    global CURRENT_BI_REPORT, CURRENT_FILE_INFO
    ds = database.get_dataset_by_id(dataset_id)
    if not ds:
        return jsonify({"success": False, "error": f"Dataset '{dataset_id}' not found."}), 404

    latest_rep = database.get_latest_report_for_dataset(dataset_id)
    CURRENT_BI_REPORT = latest_rep["report_content"] if latest_rep else None
    CURRENT_FILE_INFO = {
        "filename": ds["original_filename"],
        "ext": ds["file_type"],
        "dataset_id": dataset_id
    }

    return jsonify({
        "success": True,
        "dataset_id": dataset_id,
        "dataset": ds,
        "report": CURRENT_BI_REPORT,
        "message": f"Dataset '{ds['original_filename']}' is now the active dataset in SARTHI."
    }), 200

@app.route('/api/datasets/<dataset_id>/analyze', methods=['POST'])
def reanalyze_saved_dataset(dataset_id):
    """Re-runs the analysis engine against a saved dataset and records a new analysis run."""
    global CURRENT_BI_REPORT, CURRENT_FILE_INFO
    ds = database.get_dataset_by_id(dataset_id)
    if not ds:
        return jsonify({"success": False, "error": f"Dataset '{dataset_id}' not found."}), 404

    try:
        if ds["file_type"] in {'xlsx', 'xls', 'csv'}:
            sheets_dict = {}
            for s in ds.get("sheets", []):
                sname = s["sheet_name"]
                rec_res = database.get_dataset_records(dataset_id, sheet_name=sname, page=1, page_size=database.MAX_STORED_ROWS_PER_DATASET)
                recs = rec_res.get("records", [])
                cols = rec_res.get("columns", [])
                df = pd.DataFrame(recs, columns=cols if cols else None)
                sheets_dict[sname] = df

            bi_report = business_insights.analyze_excel_dataset(ds["original_filename"], sheets_dict, ext=ds["file_type"])
        else:
            summary = ds.get("extraction_summary") or {}
            page_count = ds.get("page_count") or summary.get("page_count", 1)
            char_count = summary.get("char_count", 0)
            text_preview = summary.get("text_preview", "")
            bi_report = business_insights.analyze_pdf_document(
                ds["original_filename"],
                page_count=page_count,
                char_count=char_count,
                text_content=text_preview
            )

        existing_runs = database.get_dataset_reports(dataset_id)
        version = f"v1.0.{len(existing_runs) + 1}"
        run_res = database.create_analysis_run(dataset_id, bi_report, version=version)
        CURRENT_BI_REPORT = bi_report
        CURRENT_FILE_INFO = {"filename": ds["original_filename"], "ext": ds["file_type"], "dataset_id": dataset_id}

        return jsonify({
            "success": True,
            "dataset_id": dataset_id,
            "analysis_run_id": run_res["analysis_run_id"],
            "report_id": run_res["report_id"],
            "analysis_version": version,
            "report": bi_report,
            "message": "Dataset reanalyzed successfully and new analysis run saved."
        }), 200
    except Exception as e:
        logger.error(f"Re-analysis failed for dataset {dataset_id}: {e}")
        return jsonify({"success": False, "error": f"Re-analysis failed: {str(e)}"}), 500

@app.route('/api/datasets/<dataset_id>', methods=['DELETE'])
def delete_saved_dataset(dataset_id):
    """Safely and transactionally deletes a saved dataset and all associated history."""
    global CURRENT_BI_REPORT, CURRENT_FILE_INFO
    success = database.delete_dataset(dataset_id)
    if not success:
        return jsonify({"success": False, "error": f"Dataset '{dataset_id}' not found."}), 404

    if CURRENT_FILE_INFO and CURRENT_FILE_INFO.get("dataset_id") == dataset_id:
        CURRENT_BI_REPORT = None
        CURRENT_FILE_INFO = None

    try:
        database.delete_document_index(dataset_id)
        rag_engine.VECTOR_INDEX_CACHE.clear(dataset_id)
    except Exception as _del_rag_err:
        logger.warning(f"Warning clearing RAG index for deleted dataset {dataset_id}: {_del_rag_err}")

    return jsonify({
        "success": True,
        "message": f"Dataset '{dataset_id}' and all associated history deleted successfully."
    }), 200


# ==============================================================================
# J.A.R.V.I.S. STEP 4 — CATALOGUE & INVENTORY MANAGEMENT API
# ==============================================================================

@app.route('/api/products', methods=['GET'])
def get_products():
    """Lists products with search, filtering, sorting, and pagination."""
    search = request.args.get('search')
    category = request.args.get('category')
    is_active_raw = request.args.get('is_active')
    is_active = None
    if is_active_raw is not None and is_active_raw != "":
        is_active = is_active_raw.lower() in ('true', '1')

    low_stock = request.args.get('low_stock', '').lower() in ('true', '1')
    out_of_stock = request.args.get('out_of_stock', '').lower() in ('true', '1')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 20))

    result = database.list_products(
        search=search, category=category, is_active=is_active,
        low_stock=low_stock, out_of_stock=out_of_stock,
        sort_by=sort_by, sort_order=sort_order,
        page=page, page_size=page_size
    )
    return jsonify({"success": True, **result}), 200


@app.route('/api/products', methods=['POST'])
def create_new_product():
    """Creates a new product with initial inventory balance and opening movement."""
    payload = request.get_json() or {}
    try:
        product = database.create_product(payload)
        return jsonify({"success": True, "product": product}), 201
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        return jsonify({"success": False, "error": "Internal server error creating product"}), 500


@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """Retrieves full product details including inventory, margins, and recent movements."""
    product = database.get_product_by_id(product_id)
    if not product:
        return jsonify({"success": False, "error": f"Product with ID {product_id} not found."}), 404
    return jsonify({"success": True, "product": product}), 200


@app.route('/api/products/<int:product_id>', methods=['PATCH'])
def patch_product(product_id):
    """Updates permitted product fields. Rejects direct stock changes."""
    payload = request.get_json() or {}
    try:
        updated = database.update_product(product_id, payload)
        return jsonify({"success": True, "product": updated}), 200
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error updating product {product_id}: {e}")
        return jsonify({"success": False, "error": "Internal server error updating product"}), 500


@app.route('/api/products/<int:product_id>/deactivate', methods=['POST'])
def deactivate_existing_product(product_id):
    """Deactivates a product without hard-deleting historical records or movements."""
    product = database.get_product_by_id(product_id)
    if not product:
        return jsonify({"success": False, "error": f"Product with ID {product_id} not found."}), 404
    database.deactivate_product(product_id)
    updated = database.get_product_by_id(product_id)
    return jsonify({"success": True, "product": updated, "message": f"Product {product_id} deactivated."}), 200


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    """Returns inventory telemetry summary (active count, total stock, low stock, out of stock, missing prices)."""
    summary = database.get_inventory_summary()
    return jsonify({"success": True, "summary": summary}), 200


@app.route('/api/products/<int:product_id>/inventory-movements', methods=['POST'])
def post_inventory_movement(product_id):
    """Records a stock movement (receipt, adjustment, sale, return) atomically."""
    payload = request.get_json() or {}
    movement_type = payload.get('movement_type')
    quantity_delta = payload.get('quantity_delta')
    reason = payload.get('reason')
    reference = payload.get('reference')
    allow_negative = bool(payload.get('allow_negative', False))

    try:
        res = database.record_inventory_movement(
            product_id=product_id,
            movement_type=movement_type,
            quantity_delta=quantity_delta,
            reason=reason,
            reference=reference,
            allow_negative=allow_negative
        )
        return jsonify({"success": True, **res}), 201
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error recording movement for product {product_id}: {e}")
        return jsonify({"success": False, "error": "Internal server error adjusting stock"}), 500


@app.route('/api/products/<int:product_id>/inventory-movements', methods=['GET'])
def get_product_movements(product_id):
    """Gets movement history for a specific product."""
    limit = int(request.args.get('limit', 50))
    page = int(request.args.get('page', 1))
    result = database.get_inventory_movements(product_id=product_id, limit=limit, page=page)
    return jsonify({"success": True, **result}), 200


@app.route('/api/inventory/movements', methods=['GET'])
def get_all_movements():
    """Gets all inventory movements across the catalogue."""
    limit = int(request.args.get('limit', 50))
    page = int(request.args.get('page', 1))
    result = database.get_inventory_movements(limit=limit, page=page)
    return jsonify({"success": True, **result}), 200


@app.route('/api/suppliers', methods=['GET'])
def get_suppliers():
    """Lists suppliers ordered by name."""
    is_active_raw = request.args.get('is_active')
    is_active = None
    if is_active_raw is not None and is_active_raw != "":
        is_active = is_active_raw.lower() in ('true', '1')
    suppliers = database.list_suppliers(is_active=is_active)
    return jsonify({"success": True, "suppliers": suppliers}), 200


@app.route('/api/suppliers', methods=['POST'])
def add_supplier():
    """Creates or gets a supplier."""
    payload = request.get_json() or {}
    try:
        supplier = database.create_or_get_supplier(
            name=payload.get('name'),
            contact_name=payload.get('contact_name'),
            phone=payload.get('phone'),
            email=payload.get('email'),
            address=payload.get('address'),
            notes=payload.get('notes')
        )
        return jsonify({"success": True, "supplier": supplier}), 201
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error creating supplier: {e}")
        return jsonify({"success": False, "error": "Internal error creating supplier"}), 500


@app.route('/api/datasets/<dataset_id>/suggest-mapping', methods=['GET'])
def get_suggested_mapping(dataset_id):
    """Suggests column mapping for an existing dataset."""
    purpose = request.args.get('purpose', 'catalogue').strip()
    ds = database.get_dataset_by_id(dataset_id)
    if not ds:
        return jsonify({"success": False, "error": f"Dataset {dataset_id} not found."}), 404

    sheets = ds.get("sheets", [])
    sheet_name = request.args.get('sheet')
    target_sheet = None
    if sheet_name:
        for s in sheets:
            if s.get("sheet_name") == sheet_name:
                target_sheet = s
                break
    if not target_sheet and sheets:
        target_sheet = sheets[0]

    columns = target_sheet.get("columns", []) if target_sheet else []
    mapping = database.suggest_column_mappings(columns, purpose=purpose)
    return jsonify({"success": True, "columns": columns, "suggested_mapping": mapping, "purpose": purpose}), 200


@app.route('/api/datasets/<dataset_id>/product-import/preview', methods=['POST'])
def preview_dataset_product_import(dataset_id):
    """Previews spreadsheet rows mapped to catalogue/ledger fields and checks duplicates/errors."""
    payload = request.get_json() or {}
    mapping = payload.get('column_mapping') or {}
    sheet_name = payload.get('sheet_name')
    sync_purpose = payload.get('sync_purpose') or payload.get('purpose') or 'catalogue'

    if not mapping:
        return jsonify({"success": False, "error": "Column mapping must be provided."}), 400

    if sync_purpose == 'catalogue' and not mapping.get('name'):
        return jsonify({"success": False, "error": "Column mapping must include at least 'name'."}), 400
    elif sync_purpose in ('purchases', 'sales', 'inventory_adjustments') and not (mapping.get('product') or mapping.get('sku') or mapping.get('name')):
        return jsonify({"success": False, "error": "Column mapping must include at least 'product' or 'sku'."}), 400

    try:
        preview = database.preview_product_spreadsheet_import(
            dataset_id=dataset_id,
            column_mapping=mapping,
            sheet_name=sheet_name,
            sync_purpose=sync_purpose
        )
        return jsonify({"success": True, **preview}), 200
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error previewing product import for {dataset_id}: {e}")
        return jsonify({"success": False, "error": "Internal error previewing product import"}), 500


@app.route('/api/datasets/<dataset_id>/product-import/commit', methods=['POST'])
def commit_dataset_product_import(dataset_id):
    """Commits validated spreadsheet rows into the product catalogue or ledger transactionally."""
    payload = request.get_json() or {}
    mapping = payload.get('column_mapping') or {}
    duplicate_strategy = payload.get('duplicate_strategy', 'skip_existing')
    sheet_name = payload.get('sheet_name')
    sync_purpose = payload.get('sync_purpose') or payload.get('purpose') or 'catalogue'

    if not mapping:
        return jsonify({"success": False, "error": "Column mapping must be provided."}), 400

    if sync_purpose == 'catalogue' and not mapping.get('name'):
        return jsonify({"success": False, "error": "Column mapping must include at least 'name'."}), 400
    elif sync_purpose in ('purchases', 'sales', 'inventory_adjustments') and not (mapping.get('product') or mapping.get('sku') or mapping.get('name')):
        return jsonify({"success": False, "error": "Column mapping must include at least 'product' or 'sku'."}), 400

    try:
        result = database.commit_product_spreadsheet_import(
            dataset_id=dataset_id,
            column_mapping=mapping,
            duplicate_strategy=duplicate_strategy,
            sheet_name=sheet_name,
            sync_purpose=sync_purpose
        )
        return jsonify({"success": True, **result}), 200
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error committing product import for {dataset_id}: {e}")
        return jsonify({"success": False, "error": "Internal error committing product import"}), 500


@app.route('/api/news', methods=['GET'])
def get_news():
    try:
        # Fetch TechCrunch RSS feed for latest real-time tech news
        import xml.etree.ElementTree as ET
        res = requests.get("https://techcrunch.com/feed/", timeout=5)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            items = []
            for item in root.findall('.//item')[:8]:
                title = item.find('title').text if item.find('title') is not None else "Tech Update"
                link = item.find('link').text if item.find('link') is not None else "https://techcrunch.com"
                items.append({"title": title, "url": link})
            if items:
                return jsonify({"articles": items, "status": "success"})
    except Exception:
        pass
        
    return jsonify({
        "articles": [
            {"title": "OpenAI announces new multi-modal model capabilities", "url": "https://techcrunch.com"},
            {"title": "Quantum computing reaches new error-correction benchmark", "url": "https://techcrunch.com"},
            {"title": "Next-generation neural audio architectures launched", "url": "https://techcrunch.com"},
            {"title": "Autonomous robotics advances in industrial automation", "url": "https://techcrunch.com"}
        ],
    })


# ==============================================================================
# VANTIQ STEP 5 — LOCAL RAG & DOCUMENT INTELLIGENCE API
# ==============================================================================

@app.route('/api/rag/documents', methods=['GET'])
def get_rag_documents():
    """Returns status, chunk counts, and metadata for all indexed documents."""
    summary = rag_engine.get_rag_status_summary()
    return jsonify({"success": True, **summary}), 200


@app.route('/api/rag/documents/<dataset_id>/reindex', methods=['POST'])
def reindex_rag_document(dataset_id):
    """Forces re-indexing of a document for local RAG intelligence."""
    result = rag_engine.reindex_dataset(dataset_id)
    status_code = 200 if result.get("success") else (400 if result.get("status") == "empty_ocr_required" else 500)
    return jsonify(result), status_code


@app.route('/api/rag/query', methods=['POST'])
def query_rag_documents():
    """Natural-language question answering grounded in uploaded documents with citations."""
    payload = request.get_json() or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "Query parameter is required."}), 400

    dataset_id = payload.get("dataset_id")
    top_k = int(payload.get("top_k", rag_engine.MAX_CHUNKS_PER_QUERY))

    # Check if mixed query requested
    is_mixed = payload.get("is_mixed")
    if is_mixed or (is_mixed is None and rag_engine.is_mixed_query(query)):
        res = rag_engine.answer_mixed_query(query, dataset_id=dataset_id)
        return jsonify(res), 200

    res = rag_engine.answer_document_query(query, dataset_id=dataset_id, top_k=top_k)
    return jsonify(res), 200


@app.route('/api/command', methods=['POST'])
def process_command():
    data = request.json or {}
    raw_cmd = data.get('command', '').strip()
    request_id = data.get('request_id') or f"req_{int(time.time()*1000)}"
    session_id = data.get('session_id')
    start_time = time.time()
    logger.info(f"[{request_id}] Command received: '{raw_cmd}' (session: {session_id})")

    context = {
        "active_dataset_id": CURRENT_FILE_INFO.get("dataset_id") if CURRENT_FILE_INFO else None,
        "current_file_info": CURRENT_FILE_INFO,
        "current_bi_report": CURRENT_BI_REPORT,
        "session_id": session_id
    }

    try:
        response = intent_router.route_intent(raw_cmd, context=context, request_id=request_id)
        elapsed = round((time.time() - start_time) * 1000, 1)
        if not response.get("request_id"):
            response["request_id"] = request_id
        response["latency_ms"] = elapsed
        logger.info(f"[{request_id}] Command completed in {elapsed}ms | action='{response.get('action')}'")
        return jsonify(response), 200
    except Exception as e:
        elapsed = round((time.time() - start_time) * 1000, 1)
        logger.error(f"[{request_id}] Error routing intent for query '{raw_cmd}': {e}", exc_info=True)
        return jsonify({
            "request_id": request_id,
            "latency_ms": elapsed,
            "speak": f"An unexpected error occurred while executing that order: {str(e)}",
            "display": f"Execution Error: {str(e)}",
            "action": "error",
            "source": "SARTHI Core",
            "source_type": "system"
        }), 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print("==================================================")
    print(" SARTHI: AI-Powered Business Intelligence Assistant")
    print(" Your Business. Your Data. Your Intelligence.")
    print(f" Running locally at http://127.0.0.1:{port}")
    print("==================================================")
    app.run(host='0.0.0.0', port=port, debug=False)

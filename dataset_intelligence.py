"""
J.A.R.V.I.S. Dataset Intelligence Engine
Module: dataset_intelligence.py
Author: Antigravity AI Engineering
Description:
    Provides deterministic, real-time data calculations and natural-language
    query fulfillment for uploaded and saved datasets in J.A.R.V.I.S.:
    - Dataset summarization & dimensions
    - Column listing & inferred data types
    - Missing-value analysis & audit
    - Duplicate-row detection
    - Head & sample row retrieval
    - Column statistics (mean, min, max, unique counts)
    - Safe row filtering (equality, comparison, containment)
    - Group-by record aggregation
    - Date column detection
    - Data quality diagnostic reports
"""

import math
import logging
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np

import database

logger = logging.getLogger("JARVIS-DatasetIntel")


def find_column(columns: List[str], query: str) -> Optional[str]:
    """
    Fuzzy/flexible matcher to find a column name from user input.
    Matches exact (case-insensitive), cleaned spaces/underscores, and substrings.
    """
    if not columns or not query:
        return None
    q = query.strip().lower()
    q_norm = q.replace("_", " ").replace("-", " ")

    # 1. Exact match (case-insensitive)
    for c in columns:
        if c.strip().lower() == q:
            return c

    # 2. Normalized match (spaces vs underscores)
    for c in columns:
        c_norm = c.strip().lower().replace("_", " ").replace("-", " ")
        if c_norm == q_norm:
            return c

    # 3. Substring match
    for c in columns:
        c_lower = c.strip().lower()
        if q in c_lower or c_lower in q:
            return c

    return None


def get_dataset_dimensions(dataset_id: str, sheet_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Calculates exact rows, columns, and sheets for a dataset."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        summary = ds.get("extraction_summary", {})
        pages = summary.get("page_count", 0)
        chars = summary.get("char_count", 0)
        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "file_type": "pdf",
            "is_tabular": False,
            "page_count": pages,
            "char_count": chars,
            "summary_text": f"PDF document with {pages} page(s) and {chars:,} characters."
        }

    total_rows = len(df)
    total_cols = len(df.columns)
    active_sheet = ds.get("active_sheet", "Sheet 1")
    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "file_type": ds.get("file_type"),
        "is_tabular": True,
        "sheet_name": active_sheet,
        "row_count": total_rows,
        "column_count": total_cols,
        "columns": list(df.columns),
        "summary_text": f"Dataset '{ds.get('original_filename')}' contains {total_rows} row(s) and {total_cols} column(s) in sheet '{active_sheet}'."
    }


def summarize_dataset(dataset_id: str, sheet_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Provides a comprehensive summary of rows, columns, types, and quality."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        summary = ds.get("extraction_summary", {})
        pages = summary.get("page_count", 0)
        chars = summary.get("char_count", 0)
        preview = summary.get("text_preview", "")
        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "file_type": "pdf",
            "is_tabular": False,
            "page_count": pages,
            "char_count": chars,
            "text_preview": preview[:500],
            "speak": f"Boss, {ds.get('original_filename')} is a PDF document containing {pages} pages and {chars:,} characters.",
            "display": f"PDF Document: {pages} Pages | {chars:,} Chars"
        }

    total_rows = len(df)
    total_cols = len(df.columns)
    cols = list(df.columns)
    missing_cells = int(df.isnull().sum().sum())
    total_cells = total_rows * total_cols if total_cols > 0 else 1
    missing_pct = round((missing_cells / total_cells) * 100, 2)
    duplicates = int(df.duplicated().sum())

    # Inferred types
    num_numeric = len(df.select_dtypes(include=[np.number]).columns)
    num_text = len(df.select_dtypes(include=['object', 'string']).columns)

    speak_text = (
        f"Boss, dataset {ds.get('original_filename')} has {total_rows} rows and {total_cols} columns. "
        f"There are {num_numeric} numeric columns and {num_text} text columns. "
        f"Missing cells account for {missing_pct} percent, with {duplicates} duplicate rows detected."
    )

    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "file_type": ds.get("file_type"),
        "is_tabular": True,
        "sheet_name": ds.get("active_sheet", "Sheet 1"),
        "row_count": total_rows,
        "column_count": total_cols,
        "columns": cols,
        "missing_cells": missing_cells,
        "missing_pct": missing_pct,
        "duplicate_rows": duplicates,
        "numeric_column_count": num_numeric,
        "text_column_count": num_text,
        "speak": speak_text,
        "display": f"Dataset Summary: {total_rows} Rows × {total_cols} Columns | Missing: {missing_pct}%"
    }


def list_dataset_columns(dataset_id: str, sheet_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Returns column names, types, and populated counts."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "is_tabular": False,
            "columns": [],
            "speak": f"Boss, {ds.get('original_filename')} is an unstructured PDF document without tabular columns.",
            "display": "No tabular columns (PDF document)"
        }

    col_info = []
    total_rows = len(df)
    for c in df.columns:
        s = df[c]
        dtype = str(s.dtype)
        if pd.api.types.is_numeric_dtype(s):
            inferred = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(s):
            inferred = "datetime"
        else:
            inferred = "text"

        non_null = int(s.notnull().sum())
        null_count = int(s.isnull().sum())
        col_info.append({
            "name": str(c),
            "dtype": dtype,
            "inferred_type": inferred,
            "non_null_count": non_null,
            "null_count": null_count,
            "completeness_pct": round((non_null / total_rows * 100), 1) if total_rows > 0 else 0.0
        })

    col_names = [c["name"] for c in col_info]
    sample_names = ", ".join(col_names[:5])
    more_suffix = f" and {len(col_names) - 5} more" if len(col_names) > 5 else ""

    speak_text = f"Boss, there are {len(col_names)} columns in {ds.get('original_filename')}: {sample_names}{more_suffix}."

    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "is_tabular": True,
        "column_count": len(col_names),
        "columns": col_names,
        "column_details": col_info,
        "speak": speak_text,
        "display": f"Columns ({len(col_names)}): {', '.join(col_names)}"
    }


def get_missing_values(dataset_id: str, sheet_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Calculates missing values per column and overall."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "is_tabular": False,
            "speak": f"Boss, missing cell analysis applies to tabular spreadsheets. {ds.get('original_filename')} is a PDF.",
            "display": "Missing values not applicable to PDF."
        }

    total_rows = len(df)
    missing_by_col = []
    total_missing = 0

    for c in df.columns:
        cnt = int(df[c].isnull().sum())
        total_missing += cnt
        pct = round((cnt / total_rows * 100), 2) if total_rows > 0 else 0.0
        missing_by_col.append({
            "column": str(c),
            "missing_count": cnt,
            "missing_pct": pct,
            "has_missing": cnt > 0
        })

    missing_cols = [c for c in missing_by_col if c["has_missing"]]
    missing_cols.sort(key=lambda x: x["missing_count"], reverse=True)

    if not missing_cols:
        speak_text = f"Boss, great news: dataset {ds.get('original_filename')} has zero missing values across all {len(df.columns)} columns."
    else:
        top_col = missing_cols[0]
        speak_text = f"Boss, {len(missing_cols)} column(s) contain missing values, totaling {total_missing} empty cells. Most affected is '{top_col['column']}' with {top_col['missing_count']} missing ({top_col['missing_pct']}%)."

    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "total_missing_cells": total_missing,
        "columns_with_missing_count": len(missing_cols),
        "missing_details": missing_by_col,
        "top_missing_columns": missing_cols[:10],
        "speak": speak_text,
        "display": f"Missing Values: {total_missing} cells across {len(missing_cols)} columns"
    }


def get_duplicate_rows(dataset_id: str, sheet_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Calculates duplicate row counts and percentages."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "is_tabular": False,
            "speak": "Duplicate row checks are only applicable to tabular spreadsheets.",
            "display": "Duplicate rows not applicable to PDF."
        }

    total_rows = len(df)
    dup_mask = df.duplicated()
    dup_count = int(dup_mask.sum())
    dup_pct = round((dup_count / total_rows * 100), 2) if total_rows > 0 else 0.0

    if dup_count == 0:
        speak_text = f"Boss, all {total_rows} rows in {ds.get('original_filename')} are distinct. Zero duplicates detected."
    else:
        speak_text = f"Boss, {dup_count} duplicate row(s) were detected ({dup_pct}% of total records) in {ds.get('original_filename')}."

    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "total_rows": total_rows,
        "duplicate_count": dup_count,
        "duplicate_pct": dup_pct,
        "has_duplicates": dup_count > 0,
        "speak": speak_text,
        "display": f"Duplicates: {dup_count} rows ({dup_pct}%)"
    }


def get_head_rows(dataset_id: str, n: int = 10, sheet_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Returns the first N rows of a dataset bounded safely."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        preview = ds.get("extraction_summary", {}).get("text_preview", "")
        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "is_tabular": False,
            "text_preview": preview[:500],
            "speak": f"Boss, displaying the initial text content for PDF {ds.get('original_filename')}.",
            "display": "PDF Content Preview"
        }

    limit = min(max(1, int(n)), 50) # Safe bounded 1-50
    head_df = df.head(limit)
    records = head_df.replace({np.nan: None}).to_dict(orient="records")

    speak_text = f"Boss, displaying the first {len(records)} rows of {ds.get('original_filename')}."

    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "is_tabular": True,
        "total_rows": len(df),
        "returned_rows": len(records),
        "columns": list(df.columns),
        "rows": records,
        "speak": speak_text,
        "display": f"First {len(records)} of {len(df)} rows"
    }


def get_column_statistics(dataset_id: str, column_query: str, sheet_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Computes exact summary statistics (mean, min, max, unique) for a requested column."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "is_tabular": False,
            "speak": "Statistical column analysis is only supported on tabular datasets.",
            "display": "Column statistics not applicable to PDF."
        }

    matched_col = find_column(list(df.columns), column_query)
    if not matched_col:
        cols_str = ", ".join(list(df.columns)[:8])
        raise ValueError(f"Column '{column_query}' was not found in dataset '{ds.get('original_filename')}'. Available columns: {cols_str}.")

    series = df[matched_col]
    total_count = len(series)
    non_null_count = int(series.notnull().sum())
    null_count = int(series.isnull().sum())
    unique_count = int(series.nunique())

    # Try numeric conversion
    num_series = pd.to_numeric(series, errors='coerce')
    valid_nums = num_series.dropna()

    if len(valid_nums) > 0 and len(valid_nums) >= (non_null_count * 0.5):
        # Numeric statistics
        c_min = round(float(valid_nums.min()), 2)
        c_max = round(float(valid_nums.max()), 2)
        c_mean = round(float(valid_nums.mean()), 2)
        c_median = round(float(valid_nums.median()), 2)
        c_sum = round(float(valid_nums.sum()), 2)

        speak_text = (
            f"Boss, for column '{matched_col}', the average value is {c_mean}. "
            f"The minimum value is {c_min} and the maximum value is {c_max}."
        )

        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "column": matched_col,
            "type": "numeric",
            "count": non_null_count,
            "missing": null_count,
            "mean": c_mean,
            "median": c_median,
            "min": c_min,
            "max": c_max,
            "sum": c_sum,
            "speak": speak_text,
            "display": f"Col '{matched_col}': Mean = {c_mean} | Min = {c_min} | Max = {c_max}"
        }
    else:
        # Categorical statistics
        top_val = None
        top_freq = 0
        val_counts = series.dropna().value_counts()
        if not val_counts.empty:
            top_val = str(val_counts.index[0])
            top_freq = int(val_counts.iloc[0])

        speak_text = (
            f"Boss, text column '{matched_col}' contains {unique_count} distinct values across {non_null_count} records. "
            f"The most frequent value is '{top_val}' occurring {top_freq} times."
        )

        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "column": matched_col,
            "type": "categorical",
            "count": non_null_count,
            "missing": null_count,
            "unique_count": unique_count,
            "top_value": top_val,
            "top_frequency": top_freq,
            "speak": speak_text,
            "display": f"Col '{matched_col}': {unique_count} Unique Values | Top: '{top_val}' ({top_freq}x)"
        }


def filter_dataset(
    dataset_id: str,
    column_query: str,
    operator: str,
    target_value: Any,
    sheet_name: Optional[str] = None,
    limit: int = 20,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Filters dataset records where column condition holds."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        raise ValueError("Filtering is only supported on tabular spreadsheets.")

    matched_col = find_column(list(df.columns), column_query)
    if not matched_col:
        cols_str = ", ".join(list(df.columns)[:8])
        raise ValueError(f"Column '{column_query}' not found. Available columns: {cols_str}.")

    series = df[matched_col]
    target_str = str(target_value).strip()

    op = operator.lower().strip()
    if op in ("equals", "eq", "=="):
        # Case-insensitive equality
        mask = series.astype(str).str.strip().str.lower() == target_str.lower()
    elif op in ("contains", "has", "like"):
        mask = series.astype(str).str.contains(target_str, case=False, na=False)
    elif op in ("gt", ">", "greater_than"):
        num_s = pd.to_numeric(series, errors='coerce')
        try:
            val_num = float(target_value)
            mask = num_s > val_num
        except ValueError:
            mask = series.astype(str) > target_str
    elif op in ("lt", "<", "less_than"):
        num_s = pd.to_numeric(series, errors='coerce')
        try:
            val_num = float(target_value)
            mask = num_s < val_num
        except ValueError:
            mask = series.astype(str) < target_str
    elif op in ("gte", ">="):
        num_s = pd.to_numeric(series, errors='coerce')
        try:
            val_num = float(target_value)
            mask = num_s >= val_num
        except ValueError:
            mask = series.astype(str) >= target_str
    elif op in ("lte", "<="):
        num_s = pd.to_numeric(series, errors='coerce')
        try:
            val_num = float(target_value)
            mask = num_s <= val_num
        except ValueError:
            mask = series.astype(str) <= target_str
    elif op in ("not_equals", "!=", "ne"):
        mask = series.astype(str).str.strip().str.lower() != target_str.lower()
    else:
        mask = series.astype(str).str.contains(target_str, case=False, na=False)

    filtered_df = df[mask]
    match_count = len(filtered_df)
    sample_records = filtered_df.head(min(limit, 50)).replace({np.nan: None}).to_dict(orient="records")

    speak_text = f"Boss, found {match_count} rows where '{matched_col}' {op} '{target_value}' in {ds.get('original_filename')}."

    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "column": matched_col,
        "operator": op,
        "target_value": target_value,
        "total_rows": len(df),
        "match_count": match_count,
        "returned_rows": len(sample_records),
        "columns": list(df.columns),
        "rows": sample_records,
        "speak": speak_text,
        "display": f"Filtered: {match_count} of {len(df)} rows where '{matched_col}' {op} '{target_value}'"
    }


def group_by_column(dataset_id: str, column_query: str, sheet_name: Optional[str] = None, limit: int = 10, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Groups dataset by column and returns frequency counts."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        raise ValueError("Group-by aggregation is only supported on tabular spreadsheets.")

    matched_col = find_column(list(df.columns), column_query)
    if not matched_col:
        cols_str = ", ".join(list(df.columns)[:8])
        raise ValueError(f"Column '{column_query}' not found. Available columns: {cols_str}.")

    counts = df[matched_col].fillna("Missing / Empty").value_counts().head(limit)
    groups = [{"group": str(k), "count": int(v)} for k, v in counts.items()]

    top_summary = ", ".join([f"{g['group']} ({g['count']})" for g in groups[:3]])
    speak_text = f"Boss, grouping by '{matched_col}' yields {len(counts)} primary categories: {top_summary}."

    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "column": matched_col,
        "distinct_groups_count": int(df[matched_col].nunique()),
        "groups": groups,
        "speak": speak_text,
        "display": f"Grouped by '{matched_col}' ({len(counts)} top categories)"
    }


def detect_date_columns(dataset_id: str, sheet_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Detects which columns contain date or timestamp formats."""
    df, ds = database.load_dataset_dataframe(dataset_id, sheet_name=sheet_name, db_path=db_path)
    if not ds:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    if ds.get("file_type") == "pdf":
        return {
            "dataset_id": dataset_id,
            "filename": ds.get("original_filename"),
            "date_columns": [],
            "speak": "Date detection on columns requires a tabular dataset.",
            "display": "Date columns not applicable to PDF."
        }

    date_cols = []
    total_rows = len(df)
    threshold = total_rows * 0.6 if total_rows > 0 else 0

    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            date_cols.append(str(c))
            continue

        # Check column name hints
        c_lower = str(c).lower()
        if any(w in c_lower for w in ["date", "time", "created_at", "updated_at", "timestamp", "dob"]):
            # Validate parsing on non-nulls
            non_nulls = s.dropna().astype(str)
            if len(non_nulls) > 0:
                parsed = pd.to_datetime(non_nulls.head(50), errors='coerce')
                if parsed.notnull().sum() >= (len(parsed) * 0.5):
                    date_cols.append(str(c))
                    continue

    if not date_cols:
        speak_text = f"Boss, no obvious date or timestamp columns were detected in {ds.get('original_filename')}."
    else:
        speak_text = f"Boss, I identified {len(date_cols)} date column(s) in {ds.get('original_filename')}: {', '.join(date_cols)}."

    return {
        "dataset_id": dataset_id,
        "filename": ds.get("original_filename"),
        "date_columns": date_cols,
        "date_column_count": len(date_cols),
        "speak": speak_text,
        "display": f"Date Columns: {', '.join(date_cols) if date_cols else 'None detected'}"
    }

"""
VANTIQ: AI-Powered Business Intelligence & Complete Data Analysis Engine
Module: business_insights.py
Description:
    Provides deterministic data profiling, automatic business dataset classification,
    data quality auditing, commercial metric calculations (pricing, margins, inventory,
    sales, suppliers), evidence-based insight generation, PDF text intelligence,
    and multi-format export (JSON, CSV, standalone HUD HTML).
"""

import io
import math
import datetime
import re
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
import pymupdf

# ==============================================================================
# 1. COLUMN SYNONYM MATRICES & CLASSIFICATION
# ==============================================================================

SYNONYMS = {
    'product': [
        'product', 'product name', 'product_name', 'item', 'item name', 'item_name',
        'sku', 'product_code', 'item_code', 'model', 'description', 'part number', 'part_no'
    ],
    'cost': [
        'purchase cost', 'purchase_cost', 'purchase price', 'purchase_price', 'cost price', 'cost_price', 'buying rate',
        'buying_rate', 'purchase rate', 'purchase_rate', 'cost', 'unit cost', 'unit_cost',
        'buying price', 'buy price', 'cost_per_unit'
    ],
    'price': [
        'selling price', 'selling_price', 'sale price', 'sale_price', 'retail price',
        'retail_price', 'price', 'unit price', 'unit_price', 'mrp', 'rate', 'sale_rate',
        'selling_rate', 'list price', 'sale', 'sales price'
    ],
    'quantity': [
        'stock', 'quantity', 'available quantity', 'inventory', 'qty', 'stock_qty',
        'units', 'stock_level', 'available_stock', 'count', 'on_hand', 'in_stock',
        'current_stock', 'quantity_on_hand'
    ],
    'reorder': [
        'reorder level', 'reorder threshold', 'min stock', 'minimum stock',
        'reorder_level', 'reorder_point', 'safety stock', 'reorder_threshold', 'min_qty'
    ],
    'supplier': [
        'supplier', 'vendor', 'manufacturer', 'supplier name', 'vendor name',
        'supplier_name', 'vendor_name', 'distributor', 'source'
    ],
    'sales': [
        'totalprice', 'total_price', 'total price', 'total sales', 'total revenue',
        'sales', 'revenue', 'amount', 'total', 'sales_amount', 'line_total',
        'subtotal', 'gross sales', 'net sales', 'invoice_amount', 'total_amount'
    ],
    'region': [
        'region', 'sales_region', 'sales region', 'territory', 'zone', 'area', 'location'
    ],
    'date': [
        'date', 'invoice date', 'transaction date', 'order date', 'sale date',
        'purchase date', 'created_at', 'timestamp', 'txn_date', 'billing_date'
    ],
    'category': [
        'category', 'product category', 'department', 'type', 'group', 'classification',
        'product_type', 'segment'
    ],
    'customer': [
        'customer', 'client', 'buyer', 'customer name', 'account', 'customer_name', 'client_name'
    ],
    'shipping': [
        'shipping cost', 'shipping_cost', 'shipping fee', 'shipping_fee', 'shipping',
        'freight', 'freight cost', 'freight_cost', 'freight charge', 'delivery charge',
        'delivery fee', 'delivery cost', 'postage', 'courier fee', 'courier charge'
    ],
    'return': [
        'returned', 'return', 'is_returned', 'returned_flag', 'return_status',
        'refunded', 'is_refunded', 'cancelled'
    ]
}

NON_COST_KEYWORDS = {'shipping', 'freight', 'delivery', 'courier', 'postage', 'transport', 'logistics'}
NON_SALES_KEYWORDS = {'person', 'rep', 'representative', 'agent', 'team', 'manager', 'lead', 'executive', 'name'}

def map_column_roles(columns):
    """
    Deterministically maps user spreadsheet columns to recognized business roles.
    Uses normalized lowercase and trimmed string comparison.
    Explicitly guards against shipping/freight charges mapping to product cost (COGS).
    """
    mapped = {}
    normalized_cols = {col: str(col).strip().lower().replace('_', ' ') for col in columns}

    for role, syn_list in SYNONYMS.items():
        matched_col = None
        # 1. Exact match check
        for orig_col, norm_col in normalized_cols.items():
            if role == 'cost' and any(exc in norm_col for exc in NON_COST_KEYWORDS):
                continue
            if role == 'sales' and any(exc in norm_col for exc in NON_SALES_KEYWORDS):
                continue
            syn_norm = [s.replace('_', ' ') for s in syn_list]
            if norm_col in syn_list or norm_col in syn_norm:
                matched_col = orig_col
                break
        # 2. Substring match check if exact match not found
        if not matched_col:
            for orig_col, norm_col in normalized_cols.items():
                if role == 'cost' and any(exc in norm_col for exc in NON_COST_KEYWORDS):
                    continue
                if role == 'sales' and any(exc in norm_col for exc in NON_SALES_KEYWORDS):
                    continue
                for syn in syn_list:
                    if len(syn) >= 4 and syn in norm_col:
                        matched_col = orig_col
                        break
                if matched_col:
                    break
        if matched_col:
            mapped[role] = matched_col

    return mapped

def get_column_mappings_with_confidence(columns_or_df) -> List[Dict[str, Any]]:
    """
    Intelligently maps uploaded spreadsheet columns to business semantic concepts
    with multi-factor confidence scoring, validation reasoning, and data type analysis.
    
    Confidence scoring:
    - 0.98: Exact match to standard business entity synonym
    - 0.86: Strong token/substring match to recognized business entity matrix
    - 0.75: Data-type heuristic match (e.g. ISO datetime series)
    - 0.00: Unmapped arbitrary column
    """
    if isinstance(columns_or_df, pd.DataFrame):
        cols = list(columns_or_df.columns)
        df_ref = columns_or_df
    elif hasattr(columns_or_df, '__iter__'):
        cols = list(columns_or_df)
        df_ref = None
    else:
        return []

    mappings = []
    mapped_roles = map_column_roles(cols)
    role_to_col = {v: k for k, v in mapped_roles.items()}

    for col in cols:
        col_str = str(col).strip()
        norm_col = col_str.lower().replace('_', ' ')
        
        inferred_type = "text"
        if df_ref is not None and len(df_ref) > 0:
            s = df_ref[col]
            if pd.to_numeric(s, errors='coerce').notnull().sum() > (len(df_ref) * 0.7):
                inferred_type = "numeric"
            elif pd.to_datetime(s, errors='coerce').notnull().sum() > (len(df_ref) * 0.6):
                inferred_type = "date"
        
        matched_role = role_to_col.get(col)
        
        if matched_role:
            syn_list = SYNONYMS.get(matched_role, [])
            syn_norm_set = set(s.lower().replace('_', ' ').strip() for s in syn_list) | set(s.lower().strip() for s in syn_list)
            if norm_col in syn_norm_set or col_str.lower() in syn_norm_set:
                confidence = 0.98
                reason = f"Exact match with standard business entity synonym for '{matched_role}'."
            else:
                confidence = 0.86
                reason = f"High-confidence token and substring match for business role '{matched_role}'."
            status = "validated"
        else:
            if inferred_type == "date" and 'date' not in mapped_roles.values():
                matched_role = "date"
                confidence = 0.75
                reason = "Detected ISO or datetime timestamp patterns in column records."
                status = "validated"
            else:
                matched_role = "unmapped"
                confidence = 0.0
                reason = "Column does not match recognized catalogue, pricing, inventory, or sales matrices."
                status = "unmapped"

        mappings.append({
            "source_column": col_str,
            "suggested_field": matched_role,
            "confidence": confidence,
            "reason": reason,
            "validation_status": status,
            "data_type": inferred_type
        })

    return mappings


def compute_descriptive_statistics(series_or_list) -> Dict[str, Any]:
    """
    Computes mathematically rigorous descriptive statistical metrics for a numeric series.
    Formulas & conventions:
    - Variance: sample variance s^2 with Bessel's correction (ddof=1)
    - Standard Deviation: sample standard deviation s (ddof=1)
    - Quartiles: linear interpolation (Q1 = 25th percentile, Q2 = median, Q3 = 75th percentile)
    - Interquartile Range (IQR): Q3 - Q1
    - Outliers: Tukey's method (points < Q1 - 1.5*IQR or > Q3 + 1.5*IQR)
    - Skewness: sample skewness (Fisher-Pearson coefficient)
    - Kurtosis: Fisher's excess kurtosis (normal distribution = 0)
    """
    s = pd.to_numeric(pd.Series(series_or_list), errors='coerce')
    clean = s.dropna()
    n = len(clean)
    null_cnt = int(s.isnull().sum())
    
    if n == 0:
        return {
            "count": 0, "null_count": null_cnt, "mean": None, "median": None,
            "mode": None, "min": None, "max": None, "range": None,
            "variance": 0.0, "std": 0.0, "q25": None, "median_q50": None,
            "q75": None, "iqr": None, "p10": None, "p90": None,
            "skewness": 0.0, "kurtosis": 0.0, "outlier_count": 0, "sum": 0.0
        }
    
    mean_val = float(clean.mean())
    median_val = float(clean.median())
    mode_series = clean.mode()
    mode_val = float(mode_series.iloc[0]) if not mode_series.empty else None
    min_val = float(clean.min())
    max_val = float(clean.max())
    range_val = float(max_val - min_val)
    var_val = float(clean.var(ddof=1)) if n > 1 else 0.0
    std_val = float(clean.std(ddof=1)) if n > 1 else 0.0
    q25 = float(clean.quantile(0.25))
    q75 = float(clean.quantile(0.75))
    iqr = float(q75 - q25)
    p10 = float(clean.quantile(0.10))
    p90 = float(clean.quantile(0.90))
    skew_val = float(clean.skew()) if n >= 3 else 0.0
    kurt_val = float(clean.kurt()) if n >= 4 else 0.0
    
    low_b = q25 - 1.5 * iqr
    high_b = q75 + 1.5 * iqr
    outlier_cnt = int(((clean < low_b) | (clean > high_b)).sum())
    
    return {
        "count": n,
        "null_count": null_cnt,
        "mean": round(mean_val, 4),
        "median": round(median_val, 4),
        "mode": round(mode_val, 4) if mode_val is not None else None,
        "min": round(min_val, 4),
        "max": round(max_val, 4),
        "range": round(range_val, 4),
        "variance": round(var_val, 4),
        "std": round(std_val, 4),
        "q25": round(q25, 4),
        "median_q50": round(median_val, 4),
        "q75": round(q75, 4),
        "iqr": round(iqr, 4),
        "p10": round(p10, 4),
        "p90": round(p90, 4),
        "skewness": round(skew_val, 4),
        "kurtosis": round(kurt_val, 4),
        "outlier_count": outlier_cnt,
        "sum": round(float(clean.sum()), 4)
    }


def classify_dataset(data_or_roles, row_count=0, is_pdf=False):
    """
    Classifies dataset category based on mapped roles and structure.
    """
    if is_pdf:
        return {
            "category": "Unstructured PDF Document",
            "detected_type": "Unstructured PDF Document",
            "confidence": "High",
            "primary_focus": "Textual Intelligence & Document Summary",
            "supported_analyses": ["Text Extraction", "Document Structure", "Keyword Analysis"]
        }

    if isinstance(data_or_roles, pd.DataFrame):
        mapped_roles = map_column_roles(data_or_roles.columns)
        row_count = len(data_or_roles)
    elif isinstance(data_or_roles, dict):
        mapped_roles = data_or_roles
    elif hasattr(data_or_roles, '__iter__'):
        mapped_roles = map_column_roles(list(data_or_roles))
    else:
        mapped_roles = {}

    has_product = 'product' in mapped_roles
    has_cost = 'cost' in mapped_roles
    has_price = 'price' in mapped_roles
    has_stock = 'quantity' in mapped_roles
    has_sales = 'sales' in mapped_roles
    has_date = 'date' in mapped_roles
    has_supplier = 'supplier' in mapped_roles

    if has_product and has_cost and has_price and has_stock:
        cat = "Product Inventory & Pricing Matrix"
        focus = "Profit margins, unit markup, stock valuation & inventory health"
    elif has_cost and has_price:
        cat = "Product Pricing & Profitability Catalogue"
        focus = "Gross margin optimization, markup spread, and loss-leader detection"
    elif has_sales and has_date:
        cat = "Sales Transactions & Revenue Logs"
        focus = "Revenue performance, average order value, sales trends"
    elif has_stock or has_product and has_stock:
        cat = "Inventory & Stock Levels"
        focus = "Stock availability, replenishment alerts, and volume breakdown"
    elif has_cost and has_supplier:
        cat = "Purchasing & Supplier Intelligence"
        focus = "Vendor concentration, procurement spend, and purchase variation"
    elif has_product:
        cat = "Product Catalogue & Metadata"
        focus = "Product taxonomy, categorization, and record completeness"
    else:
        cat = "General Tabular Data"
        focus = "Descriptive profiling, distribution analysis, and data quality"

    supported = ["Overview", "Data Quality", "Raw Data"]
    if has_cost and has_price:
        supported.append("Pricing & Margins")
    if has_stock:
        supported.append("Inventory")
    if has_sales or (has_date and (has_price or has_product)):
        supported.append("Sales & Trends")
    if has_supplier:
        supported.append("Suppliers")

    confidence = "High" if len(mapped_roles) >= 3 else ("Medium" if len(mapped_roles) >= 1 else "Low")

    return {
        "category": cat,
        "detected_type": cat,
        "confidence": confidence,
        "primary_focus": focus,
        "supported_analyses": supported,
        "detected_roles": mapped_roles
    }

# ==============================================================================
# 2. DATA QUALITY AUDIT & SCORING
# ==============================================================================

def audit_data_quality(df, mapped_roles):
    """
    Performs comprehensive data quality checks on DataFrame.
    Returns list of issues and calculates a normalized 0-100% Quality Score.
    """
    issues = []
    total_rows = len(df)
    total_cells = df.size if total_rows > 0 else 1

    if total_rows == 0:
        return {
            "score": 0,
            "grade": "F (Empty Dataset)",
            "summary": {"errors": 1, "warnings": 0, "info": 0},
            "issues": [{
                "severity": "ERROR",
                "column": "ALL",
                "affected_count": 0,
                "examples": [],
                "explanation": "Worksheet contains 0 rows of data.",
                "suggestion": "Verify that source file has populated records."
            }]
        }

    # 1. Missing Values Analysis
    missing_by_col = df.isnull().sum()
    total_missing = int(missing_by_col.sum())

    for col in df.columns:
        cnt = int(missing_by_col[col])
        if cnt > 0:
            pct = round((cnt / total_rows) * 100, 1)
            is_key_col = col in mapped_roles.values()
            severity = "ERROR" if (is_key_col and pct > 20) else ("WARNING" if pct > 10 else "INFO")
            ex_rows = [int(idx + 1) for idx in df[df[col].isnull()].index[:3]]
            msg = f"Column '{col}' has {cnt} missing/blank cells ({pct}%)."
            sugg = f"Populate missing values in '{col}' or ensure downstream calculations allow nulls."
            issues.append({
                "severity": severity,
                "column": str(col),
                "affected_count": cnt,
                "affected_records": cnt,
                "percentage": pct,
                "examples": ex_rows,
                "example_rows": ex_rows,
                "explanation": msg,
                "message": msg,
                "suggestion": sugg,
                "suggested_correction": sugg
            })

    # 2. Duplicate Rows Analysis
    dup_mask = df.duplicated(keep='first')
    dup_count = int(dup_mask.sum())
    if dup_count > 0:
        dup_rows = [int(idx + 1) for idx in df[dup_mask].index[:3]]
        msg = f"Identified {dup_count} exact duplicate row(s) in the dataset."
        sugg = "Inspect and deduplicate records to prevent inflated totals."
        issues.append({
            "severity": "WARNING",
            "column": "ENTIRE_ROW",
            "affected_count": dup_count,
            "affected_records": dup_count,
            "examples": dup_rows,
            "example_rows": dup_rows,
            "explanation": msg,
            "message": msg,
            "suggestion": sugg,
            "suggested_correction": sugg
        })

    # 3. Numeric Inconsistencies & Anomalies
    for role, col in mapped_roles.items():
        if role in ['cost', 'price', 'quantity', 'sales']:
            numeric_series = pd.to_numeric(df[col], errors='coerce')
            non_numeric_cnt = int(numeric_series.isna().sum() - df[col].isna().sum())
            if non_numeric_cnt > 0:
                msg = f"Column '{col}' contains non-numeric text values in what should be a numerical field."
                sugg = "Clean currency symbols, commas, or alphanumeric characters."
                issues.append({
                    "severity": "WARNING",
                    "column": str(col),
                    "affected_count": non_numeric_cnt,
                    "affected_records": non_numeric_cnt,
                    "examples": [],
                    "example_rows": [],
                    "explanation": msg,
                    "message": msg,
                    "suggestion": sugg,
                    "suggested_correction": sugg
                })

            # Check for negative numbers
            neg_mask = numeric_series < 0
            neg_cnt = int(neg_mask.sum())
            if neg_cnt > 0:
                neg_rows = [int(idx + 1) for idx in df[neg_mask].index[:3]]
                msg = f"Detected {neg_cnt} negative value(s) in '{col}'. Negative cost or price values require validation."
                sugg = "Correct inverted signs or review negative inventory/refund lines."
                issues.append({
                    "severity": "ERROR" if role in ['cost', 'price', 'quantity'] else "WARNING",
                    "column": str(col),
                    "affected_count": neg_cnt,
                    "affected_records": neg_cnt,
                    "examples": neg_rows,
                    "example_rows": neg_rows,
                    "explanation": msg,
                    "message": msg,
                    "suggestion": sugg,
                    "suggested_correction": sugg
                })

    # 4. Business Inversion: Selling Price < Cost Price (Loss Leader / Margin Deficit)
    if 'cost' in mapped_roles and 'price' in mapped_roles:
        c_col = mapped_roles['cost']
        p_col = mapped_roles['price']
        cost_num = pd.to_numeric(df[c_col], errors='coerce')
        price_num = pd.to_numeric(df[p_col], errors='coerce')
        inversion_mask = (price_num < cost_num) & (price_num.notna()) & (cost_num.notna())
        inv_cnt = int(inversion_mask.sum())
        if inv_cnt > 0:
            inv_rows = [int(idx + 1) for idx in df[inversion_mask].index[:3]]
            msg = f"{inv_cnt} product(s) have Cost exceeds selling price (negative unit margin)."
            sugg = "Review pricing strategy or promotional discount levels for these items."
            issues.append({
                "severity": "WARNING",
                "column": f"{p_col} vs {c_col}",
                "affected_count": inv_cnt,
                "affected_records": inv_cnt,
                "examples": inv_rows,
                "example_rows": inv_rows,
                "explanation": msg,
                "message": msg,
                "suggestion": sugg,
                "suggested_correction": sugg
            })

    # Scoring Formula
    error_cnt = sum(1 for i in issues if i['severity'] == 'ERROR')
    warn_cnt = sum(1 for i in issues if i['severity'] == 'WARNING')
    missing_pct = (total_missing / total_cells) * 100
    dup_pct = (dup_count / total_rows) * 100

    score = 100.0 - (missing_pct * 0.4) - (dup_pct * 0.3) - (error_cnt * 6.0) - (warn_cnt * 2.5)
    score = max(5.0, min(100.0, round(score, 1)))

    grade = "A (Optimal)" if score >= 90 else ("B (Good)" if score >= 75 else ("C (Fair)" if score >= 60 else "D (Needs Review)"))

    return {
        "score": score,
        "overall_score": score,
        "issue_count": len(issues),
        "grade": grade,
        "missing_cells_count": total_missing,
        "duplicate_rows_count": dup_count,
        "summary": {
            "errors": error_cnt,
            "warnings": warn_cnt,
            "info": sum(1 for i in issues if i['severity'] == 'INFO'),
            "missing_cells": total_missing,
            "duplicate_rows": dup_count
        },
        "issues": issues
    }

# ==============================================================================
# 3. STATISTICAL PROFILING & METRIC CALCULATIONS
# ==============================================================================

def profile_columns(df):
    """
    Generates detailed column profiling, data types, and descriptive statistics.
    """
    col_profiles = []
    total = len(df)
    for col in df.columns:
        series = df[col]
        null_count = int(series.isnull().sum())
        null_pct = round((null_count / total) * 100, 1) if total > 0 else 0
        unique_count = int(series.nunique(dropna=True))

        # Check boolean before numeric
        is_bool = (
            (series.dtype == bool or series.dtype == 'bool') or
            (unique_count <= 2 and series.dropna().isin([True, False, 'True', 'False', 'true', 'false', 1, 0]).all())
        )

        # Check numeric
        numeric_series = pd.to_numeric(series, errors='coerce').astype(float) if not is_bool else pd.Series(dtype=float)
        valid_numeric_count = int(numeric_series.notnull().sum())

        if valid_numeric_count > 0 and (valid_numeric_count / (total - null_count + 1e-9)) > 0.7:
            # Check integer vs float
            is_int = (numeric_series.dropna() % 1 == 0).all() if valid_numeric_count > 0 else False
            inferred_type = "Integer" if is_int else "Floating-point Numeric"
            inferred_short = "numeric"
            
            clean_num = numeric_series.dropna()
            std_val = round(float(clean_num.std()), 2) if len(clean_num) > 1 else 0.0
            var_val = round(float(clean_num.var()), 2) if len(clean_num) > 1 else 0.0
            q25_val = round(float(clean_num.quantile(0.25)), 2) if len(clean_num) > 0 else None
            q75_val = round(float(clean_num.quantile(0.75)), 2) if len(clean_num) > 0 else None
            
            mode_s = clean_num.mode()
            mode_val = round(float(mode_s.iloc[0]), 2) if not mode_s.empty else None
            min_val = round(float(clean_num.min()), 2) if not clean_num.empty else None
            max_val = round(float(clean_num.max()), 2) if not clean_num.empty else None
            range_val = round(float(max_val - min_val), 2) if (min_val is not None and max_val is not None) else None
            iqr_val = round(float(q75_val - q25_val), 2) if (q75_val is not None and q25_val is not None) else None
            skew_val = round(float(clean_num.skew()), 3) if len(clean_num) >= 3 else 0.0
            kurt_val = round(float(clean_num.kurt()), 3) if len(clean_num) >= 4 else 0.0
            p10_val = round(float(clean_num.quantile(0.10)), 2) if len(clean_num) > 0 else None
            p90_val = round(float(clean_num.quantile(0.90)), 2) if len(clean_num) > 0 else None

            if q25_val is not None and q75_val is not None and iqr_val is not None:
                low_b = q25_val - 1.5 * iqr_val
                high_b = q75_val + 1.5 * iqr_val
                outlier_count = int(((clean_num < low_b) | (clean_num > high_b)).sum())
            else:
                outlier_count = 0

            stats = {
                "count": valid_numeric_count,
                "null_count": null_count,
                "min": min_val,
                "max": max_val,
                "range": range_val,
                "mean": round(float(clean_num.mean()), 2) if not clean_num.empty else None,
                "median": round(float(clean_num.median()), 2) if not clean_num.empty else None,
                "mode": mode_val,
                "std": std_val,
                "variance": var_val,
                "q25": q25_val,
                "q75": q75_val,
                "iqr": iqr_val,
                "skewness": skew_val,
                "kurtosis": kurt_val,
                "p10": p10_val,
                "p90": p90_val,
                "outlier_count": outlier_count,
                "sum": round(float(clean_num.sum()), 2) if not clean_num.empty else None
            }
        elif pd.to_datetime(series, errors='coerce').notnull().sum() > (total * 0.6):
            inferred_type = "Date/Time"
            inferred_short = "date"
            dt_series = pd.to_datetime(series, errors='coerce').dropna()
            stats = {
                "count": int(len(dt_series)),
                "null_count": null_count,
                "earliest": dt_series.min().isoformat() if not dt_series.empty else None,
                "latest": dt_series.max().isoformat() if not dt_series.empty else None
            }
        elif series.dropna().isin([True, False, 'True', 'False', 'true', 'false', 1, 0]).all() and unique_count <= 2:
            inferred_type = "Boolean"
            inferred_short = "boolean"
            top_vals = series.value_counts(dropna=True).to_dict()
            stats = {
                "count": total - null_count,
                "null_count": null_count,
                "top_values": {str(k): int(v) for k, v in top_vals.items()}
            }
        else:
            inferred_type = "Categorical / Text"
            inferred_short = "text"
            top_vals = series.value_counts(dropna=True).head(5).to_dict()
            stats = {
                "count": total - null_count,
                "null_count": null_count,
                "top_values": {str(k): int(v) for k, v in top_vals.items()}
            }

        col_profiles.append({
            "name": str(col),
            "column": str(col),
            "inferred_type": inferred_short,
            "type_display": inferred_type,
            "null_count": null_count,
            "non_null_count": total - null_count,
            "null_pct": null_pct,
            "unique_count": unique_count,
            "distinct_count": unique_count,
            "stats": stats
        })

    return col_profiles

def compute_correlation_matrix(df):
    """
    Computes Pearson correlation matrix between suitable numeric columns.
    Excludes constant columns (std == 0) and pure serial ID columns.
    Identifies notable linear relationships (|r| >= 0.5) with interpretive descriptions.
    """
    total_rows = len(df)
    if total_rows < 3:
        return {
            "available": False,
            "computed": False,
            "reason": "Dataset has fewer than 3 records. Correlation requires at least 3 data points.",
            "columns": [],
            "matrix": {},
            "significant_correlations": []
        }

    # Identify candidate numeric columns
    numeric_cols = []
    for col in df.columns:
        col_str = str(col).strip().lower()
        # Filter obvious row indices / IDs
        if any(col_str.endswith(sfx) or col_str == sfx for sfx in ['_id', ' id', 'id', 'uuid', 'guid', 'row_id', 'index']):
            s_test = pd.to_numeric(df[col], errors='coerce')
            if s_test.notnull().sum() > 0 and s_test.nunique() == total_rows:
                continue

        s = pd.to_numeric(df[col], errors='coerce')
        valid_cnt = int(s.notnull().sum())
        if valid_cnt >= 3:
            s_clean = s.dropna()
            if s_clean.std() > 0:
                numeric_cols.append(col)

    if len(numeric_cols) < 2:
        return {
            "available": False,
            "computed": False,
            "reason": f"Requires at least 2 suitable numeric columns with variation. Found {len(numeric_cols)}.",
            "columns": [str(c) for c in numeric_cols],
            "matrix": {},
            "significant_correlations": []
        }

    # Calculate Pearson correlation
    num_df = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
    corr_df = num_df.corr(method='pearson')

    matrix_dict = {}
    significant = []
    seen_pairs = set()

    for c1 in numeric_cols:
        matrix_dict[str(c1)] = {}
        for c2 in numeric_cols:
            val = corr_df.loc[c1, c2]
            if pd.isna(val) or math.isnan(val):
                matrix_dict[str(c1)][str(c2)] = None
            else:
                r_val = round(float(val), 3)
                matrix_dict[str(c1)][str(c2)] = r_val

                # Capture significant correlations (exclude diagonal & mirror pairs)
                if c1 != c2:
                    pair_key = tuple(sorted([str(c1), str(c2)]))
                    if pair_key not in seen_pairs:
                        seen_pairs.add(pair_key)
                        abs_r = abs(r_val)
                        if abs_r >= 0.5:
                            if r_val >= 0.8:
                                strength = "Very Strong Positive"
                                desc = f"Strong direct relationship: as '{c1}' increases, '{c2}' increases proportionally."
                            elif r_val >= 0.5:
                                strength = "Moderate Positive"
                                desc = f"Moderate direct correlation observed between '{c1}' and '{c2}'."
                            elif r_val <= -0.8:
                                strength = "Very Strong Negative"
                                desc = f"Strong inverse relationship: as '{c1}' increases, '{c2}' decreases substantially."
                            else:
                                strength = "Moderate Negative"
                                desc = f"Moderate inverse correlation observed between '{c1}' and '{c2}'."

                            significant.append({
                                "col1": str(c1),
                                "col2": str(c2),
                                "correlation": r_val,
                                "strength": strength,
                                "interpretation": desc
                            })

    significant.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    return {
        "available": True,
        "computed": True,
        "columns": [str(c) for c in numeric_cols],
        "matrix": matrix_dict,
        "significant_correlations": significant,
        "summary": f"Computed Pearson correlations across {len(numeric_cols)} numeric columns with {len(significant)} significant relationships (|r| >= 0.5)."
    }

def compute_categorical_distributions(df):
    """
    Computes frequency distributions and percentages for categorical columns.
    Analyzes columns with discrete categories (cardinality <= 50 and <= 85% of records).
    """
    total_rows = len(df)
    if total_rows == 0:
        return {
            "available": False,
            "computed": False,
            "columns_analyzed": [],
            "distributions": {},
            "reason": "Dataset is empty."
        }

    distributions = {}
    columns_analyzed = []

    for col in df.columns:
        series = df[col]
        # Skip primarily numeric columns
        s_num = pd.to_numeric(series, errors='coerce')
        if s_num.notnull().sum() > (total_rows * 0.7):
            continue

        # Skip datetime columns
        try:
            if pd.to_datetime(series, errors='coerce').notnull().sum() > (total_rows * 0.7):
                continue
        except Exception:
            pass

        unique_cnt = int(series.nunique(dropna=True))
        if 1 <= unique_cnt <= 50 and (unique_cnt <= total_rows * 0.85 or total_rows <= 10):
            columns_analyzed.append(str(col))
            val_counts = series.value_counts(dropna=False)
            mode_val = str(val_counts.index[0]) if not pd.isna(val_counts.index[0]) else "Missing / Blank"

            breakdown = []
            for val, cnt in val_counts.head(10).items():
                val_str = "Missing / Blank" if pd.isna(val) else str(val)
                pct = round((cnt / total_rows) * 100, 1)
                breakdown.append({
                    "value": val_str,
                    "count": int(cnt),
                    "percentage": pct
                })

            distributions[str(col)] = {
                "column": str(col),
                "distinct_count": unique_cnt,
                "total_records": total_rows,
                "mode": mode_val,
                "mode_count": int(val_counts.iloc[0]) if len(val_counts) > 0 else 0,
                "null_count": int(series.isna().sum()),
                "breakdown": breakdown
            }

    return {
        "available": len(columns_analyzed) > 0,
        "computed": len(columns_analyzed) > 0,
        "columns_analyzed": columns_analyzed,
        "distributions": distributions,
        "reason": "No discrete categorical columns found with cardinality under 50." if len(columns_analyzed) == 0 else None
    }

def compute_pricing_analytics(df, mapped_roles):
    """
    Computes commercial pricing, profit margins, and markup metrics.
    """
    if 'cost' not in mapped_roles or 'price' not in mapped_roles:
        missing = []
        if 'cost' not in mapped_roles: missing.append("Cost Price")
        if 'price' not in mapped_roles: missing.append("Selling Price")
        return {
            "available": False,
            "computed": False,
            "reason": "Requires both Purchase/Cost Price and Selling Price columns.",
            "missing_fields": missing
        }

    c_col = mapped_roles['cost']
    if any(k in str(c_col).lower() for k in NON_COST_KEYWORDS):
        return {
            "available": False,
            "computed": False,
            "reason": f"Column '{c_col}' is identified as a shipping/freight charge and cannot be used as a product purchase cost (COGS).",
            "missing_fields": ["Product Purchase/Cost Price (COGS)"]
        }

    p_col = mapped_roles['price']
    prod_col = mapped_roles.get('product', None)

    costs = pd.to_numeric(df[c_col], errors='coerce')
    prices = pd.to_numeric(df[p_col], errors='coerce')

    valid_mask = costs.notnull() & prices.notnull()
    valid_df = df[valid_mask].copy()
    valid_costs = costs[valid_mask]
    valid_prices = prices[valid_mask]

    if len(valid_df) == 0:
        return {
            "available": False,
            "computed": False,
            "reason": "No rows contain both valid numeric cost and selling price.",
            "missing_fields": ["Valid numeric Cost and Selling Price rows"]
        }

    # Gross Profit per unit = Price - Cost
    unit_profits = valid_prices - valid_costs

    # Gross Margin % = ((Price - Cost) / Price) * 100
    # Safe division: if price == 0, margin is -100% or 0%
    margins = np.where(valid_prices != 0, (unit_profits / valid_prices) * 100, np.where(unit_profits < 0, -100.0, 0.0))

    # Markup % = ((Price - Cost) / Cost) * 100
    markups = np.where(valid_costs != 0, (unit_profits / valid_costs) * 100, 0.0)

    valid_df['__profit'] = unit_profits
    valid_df['__margin'] = margins
    valid_df['__markup'] = markups

    avg_margin = float(round(np.mean(margins), 2))
    median_margin = float(round(np.median(margins), 2))
    avg_markup = float(round(np.mean(markups), 2))
    total_est_unit_profit = float(round(np.sum(unit_profits), 2))

    # Margin Distribution Breakdown
    bands = {
        "High (> 40%)": int(np.sum(margins >= 40)),
        "Healthy (20% - 40%)": int(np.sum((margins >= 20) & (margins < 40))),
        "Low (0% - 20%)": int(np.sum((margins >= 0) & (margins < 20))),
        "Negative (< 0%)": int(np.sum(margins < 0))
    }

    # Top & Bottom Margin Products
    top_margin_products = []
    lowest_margin_products = []

    valid_df_sorted = valid_df.sort_values(by='__margin', ascending=False)

    for _, r in valid_df_sorted.head(10).iterrows():
        p_name = str(r[prod_col]) if prod_col else f"Row {r.name + 1}"
        top_margin_products.append({
            "product": p_name,
            "cost": round(float(r[c_col]), 2),
            "price": round(float(r[p_col]), 2),
            "unit_profit": round(float(r['__profit']), 2),
            "margin_pct": round(float(r['__margin']), 2)
        })

    for _, r in valid_df_sorted.tail(5).iterrows():
        p_name = str(r[prod_col]) if prod_col else f"Row {r.name + 1}"
        lowest_margin_products.append({
            "product": p_name,
            "cost": round(float(r[c_col]), 2),
            "price": round(float(r[p_col]), 2),
            "unit_profit": round(float(r['__profit']), 2),
            "margin_pct": round(float(r['__margin']), 2)
        })

    neg_margin_count = int(np.sum(margins < 0))
    at_cost_count = int(np.sum(margins == 0))

    highest_margin_products = []
    for p in top_margin_products:
        # Calculate markup safely
        cost_val = p["cost"]
        sale_val = p["price"]
        markup_val = round(((sale_val - cost_val) / cost_val) * 100, 2) if cost_val > 0 else None
        highest_margin_products.append({
            "product": p["product"],
            "cost_price": cost_val,
            "selling_price": sale_val,
            "gross_profit_per_unit": p["unit_profit"],
            "gross_margin_pct": p["margin_pct"],
            "markup_pct": markup_val
        })

    lowest_margin_prods = [
        {
            "product": p["product"],
            "cost_price": p["cost"],
            "selling_price": p["price"],
            "gross_profit_per_unit": p["unit_profit"],
            "gross_margin_pct": p["margin_pct"]
        }
        for p in lowest_margin_products
    ]

    return {
        "available": True,
        "computed": True,
        "analyzed_count": len(valid_df),
        "analyzed_products_count": len(valid_df),
        "cost_column": c_col,
        "price_column": p_col,
        "average_gross_margin_pct": avg_margin,
        "median_gross_margin_pct": median_margin,
        "average_markup_pct": avg_markup,
        "total_unit_profit_spread": total_est_unit_profit,
        "negative_margin_count": neg_margin_count,
        "at_cost_count": at_cost_count,
        "metrics": {
            "average_gross_margin_pct": avg_margin,
            "median_gross_margin_pct": median_margin,
            "average_markup_pct": avg_markup,
            "total_unit_profit_spread": total_est_unit_profit,
            "negative_margin_count": neg_margin_count,
            "at_cost_count": at_cost_count
        },
        "margin_distribution": bands,
        "top_margin_products": top_margin_products,
        "highest_margin_products": highest_margin_products,
        "lowest_margin_products": lowest_margin_prods
    }


def calculate_product_profit_and_margin(
    product_record: Dict[str, Any],
    cost_basis: str = "purchase_price"
) -> Dict[str, Any]:
    """
    Calculates unit gross profit, gross margin percentage, and markup percentage
    for an individual product record from verified database fields.

    Parameters:
        product_record: Dict containing product fields (name, selling_price, purchase_price,
                        last_purchase_rate, last_purchase_date, currency, etc.).
        cost_basis: 'purchase_price' (default catalog baseline acquisition cost) or
                    'last_purchase_rate' (latest recorded procurement cost).

    Formulas:
        Gross Profit per unit = Selling Price - Purchase Cost
        Gross Margin % = ((Selling Price - Purchase Cost) / Selling Price) * 100
        Markup % = ((Selling Price - Purchase Cost) / Purchase Cost) * 100

    Safety & Integrity:
        - Never invents prices or figures.
        - Handles zero or missing selling prices safely without ZeroDivisionError.
        - Labels the calculation strictly as Gross Profit (excludes operating expenses/taxes).
        - If cost basis is 'last_purchase_rate' and none is recorded, reports missing procurement history
          rather than silently substituting baseline purchase price without notice.
    """
    if not isinstance(product_record, dict):
        return {
            "success": False,
            "status": "invalid_record",
            "error": "Product record must be a dictionary.",
            "metrics": None
        }

    p_name = product_record.get("name") or "Product"
    currency = product_record.get("currency") or "INR"

    raw_sp = product_record.get("selling_price")
    raw_cp = product_record.get("purchase_price")
    raw_last_rate = product_record.get("last_purchase_rate")
    last_date = product_record.get("last_purchase_date")

    # Determine cost based on selected basis
    is_last_rate_basis = (cost_basis == "last_purchase_rate")
    cost_basis_used = "last_purchase_rate" if is_last_rate_basis else "purchase_price"
    cost_label = "Latest Procurement Rate" if is_last_rate_basis else "Catalog Purchase Price"

    cost_val = raw_last_rate if is_last_rate_basis else raw_cp

    # Check for missing selling price
    if raw_sp is None:
        return {
            "success": False,
            "status": "missing_selling_price",
            "product_name": p_name,
            "cost_basis": cost_basis_used,
            "cost_label": cost_label,
            "cost_value": float(cost_val) if cost_val is not None else None,
            "effective_cost": float(cost_val) if cost_val is not None else None,
            "selling_price": None,
            "profit_per_unit": None,
            "gross_profit_per_unit": None,
            "gross_margin_pct": None,
            "markup_pct": None,
            "message": f"Selling price is not configured for '{p_name}'. Profit and margin cannot be calculated.",
            "metrics": {
                "selling_price": None,
                "purchase_price": float(cost_val) if cost_val is not None else None,
                "gross_profit": None,
                "gross_margin_pct": None,
                "markup_pct": None,
                "cost_basis": cost_basis_used
            }
        }

    # Check for missing cost value
    if cost_val is None:
        if is_last_rate_basis:
            msg = f"No purchase transactions have been recorded yet for '{p_name}'. Latest procurement rate is unavailable."
        else:
            msg = f"Catalog purchase price is not configured for '{p_name}'. Profit and margin cannot be calculated."
        return {
            "success": False,
            "status": "missing_cost_basis",
            "product_name": p_name,
            "cost_basis": cost_basis_used,
            "cost_label": cost_label,
            "cost_value": None,
            "effective_cost": None,
            "selling_price": float(raw_sp),
            "profit_per_unit": None,
            "gross_profit_per_unit": None,
            "gross_margin_pct": None,
            "markup_pct": None,
            "message": msg,
            "metrics": {
                "selling_price": float(raw_sp),
                "purchase_price": None,
                "gross_profit": None,
                "gross_margin_pct": None,
                "markup_pct": None,
                "cost_basis": cost_basis_used
            }
        }

    try:
        sp = float(raw_sp)
        cp = float(cost_val)
    except (ValueError, TypeError):
        return {
            "success": False,
            "status": "invalid_numeric_values",
            "product_name": p_name,
            "message": f"Non-numeric price values encountered for '{p_name}'.",
            "metrics": None
        }

    profit = round(sp - cp, 2)
    # Safe division for zero selling price
    margin_pct = round(((sp - cp) / sp) * 100.0, 2) if sp > 0 else 0.0
    markup_pct = round(((sp - cp) / cp) * 100.0, 2) if cp > 0 else 0.0

    notes = []
    if sp == 0.0:
        notes.append("Selling price is 0.00; gross margin is 0.0%.")
    if is_last_rate_basis:
        notes.append("Cost calculated using latest recorded procurement rate.")

    return {
        "success": True,
        "status": "success",
        "zero_selling_price": (sp == 0.0),
        "product_name": p_name,
        "currency": currency,
        "cost_basis": cost_basis_used,
        "cost_label": cost_label,
        "cost_date": last_date if is_last_rate_basis else None,
        "cost_value": cp,
        "effective_cost": cp,
        "selling_price": sp,
        "profit_per_unit": profit,
        "gross_profit_per_unit": profit,
        "gross_margin_pct": margin_pct,
        "markup_pct": markup_pct,
        "notes": " ".join(notes) if notes else "Calculated from recorded catalogue prices.",
        "is_estimate": True,
        "pricing_type": "Gross Profit Estimate (recorded prices only, excludes OPEX/taxes)",
        "metrics": {
            "selling_price": sp,
            "purchase_price": cp,
            "gross_profit": profit,
            "profit_per_unit": profit,
            "gross_margin_pct": margin_pct,
            "markup_pct": markup_pct,
            "cost_basis": cost_basis_used
        }
    }


def compute_inventory_analytics(df, mapped_roles):
    """
    Computes inventory volume, valuation, and stock alerts.
    """
    if 'quantity' not in mapped_roles:
        return {
            "available": False,
            "computed": False,
            "reason": "Requires Stock/Quantity column.",
            "missing_fields": ["Quantity / Stock"]
        }

    q_col = mapped_roles['quantity']
    prod_col = mapped_roles.get('product', None)
    cost_col = mapped_roles.get('cost', None)
    reorder_col = mapped_roles.get('reorder', None)

    qtys = pd.to_numeric(df[q_col], errors='coerce').fillna(0)
    total_units = int(qtys.sum())
    product_count = len(df)

    # Reorder threshold logic:
    if reorder_col:
        thresholds = pd.to_numeric(df[reorder_col], errors='coerce').fillna(5)
        low_stock_mask = (qtys > 0) & (qtys < thresholds)
        criteria_note = f"Using column '{reorder_col}' thresholds."
    else:
        thresholds = pd.Series([10] * len(df), index=df.index)
        low_stock_mask = (qtys > 0) & (qtys <= 10)
        criteria_note = "Using default threshold (quantity <= 10)."

    out_of_stock_mask = qtys == 0
    neg_stock_mask = qtys < 0

    low_stock_items = []
    # Include items below reorder threshold OR out of stock
    alert_mask = (qtys < thresholds) | out_of_stock_mask
    for idx, r in df[alert_mask].iterrows():
        p_name = str(r[prod_col]) if prod_col else f"Row {idx + 1}"
        low_stock_items.append({
            "product": p_name,
            "quantity": int(r[q_col]) if pd.notnull(r[q_col]) else 0,
            "stock": int(r[q_col]) if pd.notnull(r[q_col]) else 0,
            "threshold": int(thresholds.loc[idx])
        })

    out_of_stock_items = []
    for _, r in df[out_of_stock_mask].head(6).iterrows():
        p_name = str(r[prod_col]) if prod_col else f"Row {r.name + 1}"
        out_of_stock_items.append({"product": p_name, "stock": 0})

    # Valuation
    valuation = None
    if cost_col:
        costs = pd.to_numeric(df[cost_col], errors='coerce').fillna(0)
        valuation = round(float((qtys * costs).sum()), 2)

    # Top stock items
    df_sorted_stock = df.assign(__qty=qtys).sort_values(by='__qty', ascending=False)
    top_stock = []
    for _, r in df_sorted_stock.head(5).iterrows():
        p_name = str(r[prod_col]) if prod_col else f"Row {r.name + 1}"
        top_stock.append({"product": p_name, "stock": int(r['__qty'])})

    return {
        "available": True,
        "computed": True,
        "quantity_column": q_col,
        "total_product_records": product_count,
        "total_units_in_stock": total_units,
        "out_of_stock_count": int(out_of_stock_mask.sum()),
        "low_stock_count": len(low_stock_items),
        "negative_stock_count": int(neg_stock_mask.sum()),
        "total_inventory_value": valuation,
        "total_inventory_valuation": valuation,
        "low_stock_products": low_stock_items,
        "metrics": {
            "total_product_records": product_count,
            "total_units_in_stock": total_units,
            "out_of_stock_count": int(out_of_stock_mask.sum()),
            "low_stock_count": len(low_stock_items),
            "negative_stock_count": int(neg_stock_mask.sum()),
            "total_inventory_valuation": valuation
        },
        "threshold_criteria": criteria_note,
        "low_stock_items": low_stock_items,
        "out_of_stock_items": out_of_stock_items,
        "top_stocked_items": top_stock
    }

def compute_sales_analytics(df, mapped_roles):
    """
    Computes return-aware sales metrics, total revenue, return value, net revenue,
    order counts, and timeline trends.
    """
    if df is None or len(df) == 0:
        return {
            "available": True,
            "computed": True,
            "revenue_column": None,
            "total_revenue": 0.0,
            "gross_recorded_sales": 0.0,
            "returned_sales_value": 0.0,
            "net_sales": 0.0,
            "net_sales_after_returns": 0.0,
            "non_returned_sales_value": 0.0,
            "transaction_count": 0,
            "total_order_count": 0,
            "returned_order_count": 0,
            "non_returned_order_count": 0,
            "return_rate_pct": 0.0,
            "average_transaction_value": 0.0,
            "units_sold": 0,
            "returns_tracked": False,
            "returns_basis": "Dataset contains 0 rows.",
            "sales_by_date": [],
            "metrics": {
                "total_revenue": 0.0,
                "gross_recorded_sales": 0.0,
                "returned_sales_value": 0.0,
                "net_sales": 0.0,
                "net_sales_after_returns": 0.0,
                "non_returned_sales_value": 0.0,
                "transaction_count": 0,
                "total_order_count": 0,
                "returned_order_count": 0,
                "non_returned_order_count": 0,
                "return_rate_pct": 0.0,
                "average_transaction_value": 0.0,
                "units_sold": 0
            },
            "top_revenue_products": [],
            "top_selling_products": [],
            "timeline_trend": []
        }

    if 'sales' not in mapped_roles and 'price' not in mapped_roles:
        return {
            "available": False,
            "computed": False,
            "reason": "Requires Sales/Revenue or Price column.",
            "missing_fields": ["Sales / Revenue"]
        }

    rev_col = mapped_roles.get('sales', mapped_roles.get('price'))
    prod_col = mapped_roles.get('product', None)
    date_col = mapped_roles.get('date', None)

    sales_vals = pd.to_numeric(df[rev_col], errors='coerce').fillna(0)
    gross_recorded_sales = round(float(sales_vals.sum()), 2)
    total_order_count = len(df)
    avg_txn = round(float(sales_vals.mean()), 2) if total_order_count > 0 else 0.0

    # Locate return indicator column
    ret_col = mapped_roles.get('return')
    if not ret_col:
        for c in df.columns:
            norm_c = str(c).strip().lower().replace('_', ' ')
            if norm_c in ('returned', 'return', 'is returned', 'refunded', 'is refunded'):
                ret_col = c
                break

    if ret_col:
        ret_series = df[ret_col]
        # Identify truthy return flags: 1, 1.0, True, 'true', 'yes', 'returned'
        is_ret_mask = (
            (pd.to_numeric(ret_series, errors='coerce') == 1) |
            ret_series.astype(str).str.strip().str.lower().isin(['1', '1.0', 'true', 'yes', 'returned', 'refunded'])
        )
        returned_order_count = int(is_ret_mask.sum())
        returned_sales_val = round(float(sales_vals[is_ret_mask].sum()), 2)
        non_returned_order_count = total_order_count - returned_order_count
        non_returned_sales_val = round(float(sales_vals[~is_ret_mask].sum()), 2)
        net_sales = round(gross_recorded_sales - returned_sales_val, 2)
        return_rate_pct = round((returned_order_count / total_order_count) * 100.0, 2) if total_order_count > 0 else 0.0
        returns_tracked = True
        returns_basis = "Calculated from source dataset return flags (Returned = 1). Does not assume whether returned products were restocked or whether refunds included shipping fees."
    else:
        returned_order_count = 0
        returned_sales_val = 0.0
        non_returned_order_count = total_order_count
        non_returned_sales_val = gross_recorded_sales
        net_sales = gross_recorded_sales
        return_rate_pct = 0.0
        returns_tracked = False
        returns_basis = "No return flag column detected in source dataset; gross sales equal net sales."

    top_revenue_items = []
    if prod_col:
        grouped = df.assign(__rev=sales_vals).groupby(prod_col)['__rev'].sum().reset_index()
        grouped = grouped.sort_values(by='__rev', ascending=False)
        for _, r in grouped.head(5).iterrows():
            top_revenue_items.append({
                "product": str(r[prod_col]),
                "revenue": round(float(r['__rev']), 2)
            })

    # Time series aggregation if dates exist
    trend_data = []
    sales_by_date = []
    if date_col:
        dt_series = pd.to_datetime(df[date_col], errors='coerce')
        valid_dates = df[dt_series.notnull()].assign(__dt=dt_series[dt_series.notnull()], __rev=sales_vals[dt_series.notnull()])
        if not valid_dates.empty:
            grouped_date = valid_dates.groupby(valid_dates['__dt'].dt.strftime('%Y-%m-%d'))['__rev'].sum().reset_index()
            for _, r in grouped_date.head(15).iterrows():
                d_str = str(r['__dt'])
                rev_val = round(float(r['__rev']), 2)
                trend_data.append({"period": d_str, "revenue": rev_val})
                sales_by_date.append({"date": d_str, "revenue": rev_val})

    qty_col = mapped_roles.get('quantity')
    units_sold = int(pd.to_numeric(df[qty_col], errors='coerce').fillna(0).sum()) if qty_col else total_order_count

    return {
        "available": True,
        "computed": True,
        "revenue_column": rev_col,
        "total_revenue": gross_recorded_sales,
        "gross_recorded_sales": gross_recorded_sales,
        "returned_sales_value": returned_sales_val,
        "net_sales": net_sales,
        "net_sales_after_returns": net_sales,
        "non_returned_sales_value": non_returned_sales_val,
        "transaction_count": total_order_count,
        "total_order_count": total_order_count,
        "returned_order_count": returned_order_count,
        "non_returned_order_count": non_returned_order_count,
        "return_rate_pct": return_rate_pct,
        "average_transaction_value": avg_txn,
        "units_sold": units_sold,
        "returns_tracked": returns_tracked,
        "returns_basis": returns_basis,
        "sales_by_date": sales_by_date,
        "metrics": {
            "total_revenue": gross_recorded_sales,
            "gross_recorded_sales": gross_recorded_sales,
            "returned_sales_value": returned_sales_val,
            "net_sales": net_sales,
            "net_sales_after_returns": net_sales,
            "non_returned_sales_value": non_returned_sales_val,
            "transaction_count": total_order_count,
            "total_order_count": total_order_count,
            "returned_order_count": returned_order_count,
            "non_returned_order_count": non_returned_order_count,
            "return_rate_pct": return_rate_pct,
            "average_transaction_value": avg_txn,
            "units_sold": units_sold
        },
        "top_revenue_products": top_revenue_items,
        "top_selling_products": top_revenue_items,
        "timeline_trend": trend_data
    }

def compute_supplier_analytics(df, mapped_roles):
    """
    Computes supplier volume, spend distribution, and vendor concentration.
    """
    if 'supplier' not in mapped_roles:
        return {
            "available": False,
            "computed": False,
            "reason": "Requires Supplier/Vendor column.",
            "missing_fields": ["Supplier / Vendor"]
        }

    sup_col = mapped_roles['supplier']
    prod_col = mapped_roles.get('product', None)
    cost_col = mapped_roles.get('cost', None)

    suppliers = df[sup_col].dropna().astype(str)
    sup_counts = suppliers.value_counts()
    unique_suppliers = len(sup_counts)

    breakdown = []
    top_vendor = sup_counts.index[0] if len(sup_counts) > 0 else "N/A"
    top_vendor_share = round((sup_counts.iloc[0] / len(suppliers)) * 100, 1) if len(suppliers) > 0 else 0

    for s_name, count in sup_counts.head(5).items():
        spend = None
        if cost_col:
            sub = df[df[sup_col].astype(str) == s_name]
            spend = round(float(pd.to_numeric(sub[cost_col], errors='coerce').sum()), 2)
        breakdown.append({
            "supplier": s_name,
            "product_count": int(count),
            "count": int(count),
            "estimated_spend": spend,
            "spend": spend if spend is not None else 0.0
        })

    tot_spend = round(float(sum((s["spend"] or 0) for s in breakdown)), 2)

    return {
        "available": True,
        "computed": True,
        "supplier_column": sup_col,
        "supplier_count": unique_suppliers,
        "total_spend": tot_spend,
        "multi_supplier_products_count": 0,
        "metrics": {
            "unique_suppliers_count": unique_suppliers,
            "primary_supplier": top_vendor,
            "supplier_concentration_pct": top_vendor_share
        },
        "top_suppliers": breakdown
    }

# ==============================================================================
# 4. DETERMINISTIC INSIGHTS GENERATOR
# ==============================================================================

def generate_insights(*args, **kwargs):
    """
    Synthesizes computed metrics into actionable, evidence-based business findings.
    Flexible signature: accepts either (classification, quality, pricing, inventory, sales, suppliers)
    or (df, roles, quality, pricing, inventory, sales, suppliers)
    """
    if len(args) == 7:
        df, roles, quality, pricing, inventory, sales, suppliers = args
        classification = classify_dataset(roles, len(df))
    elif len(args) == 6:
        classification, quality, pricing, inventory, sales, suppliers = args
    else:
        classification = kwargs.get('classification', {})
        quality = kwargs.get('quality', {})
        pricing = kwargs.get('pricing', {})
        inventory = kwargs.get('inventory', {})
        sales = kwargs.get('sales', {})
        suppliers = kwargs.get('suppliers', {})

    findings = []

    # 1. Quality Insights
    if quality.get("score", 100) < 70:
        err_c = quality.get("summary", {}).get("errors", 1)
        warn_c = quality.get("summary", {}).get("warnings", 0)
        findings.append({
            "title": "Data Integrity Action Required",
            "explanation": f"Dataset health scored at {quality['score']}%. Resolved errors are required before financial consolidation.",
            "metric": f"{err_c} Errors, {warn_c} Warnings",
            "underlying_metric": f"{err_c} Errors, {warn_c} Warnings",
            "severity": "CRITICAL",
            "fields_used": ["Data Quality Audit"]
        })
    elif quality.get("missing_cells_count", 0) > 0:
        m_cells = quality.get("missing_cells_count", 0)
        findings.append({
            "title": "Incomplete Data Cells Detected",
            "explanation": f"Found {m_cells} missing/blank values across columns.",
            "metric": f"{m_cells} Missing Values",
            "underlying_metric": f"{m_cells} Missing Values",
            "severity": "WARNING",
            "fields_used": ["Null check"]
        })

    # 2. Pricing Insights
    if pricing.get("computed") or pricing.get("available"):
        p_metrics = pricing.get("metrics", pricing)
        neg_c = p_metrics.get("negative_margin_count", 0)
        if neg_c > 0:
            findings.append({
                "title": "Negative Gross Margin Alert",
                "explanation": f"{neg_c} product(s) are priced below unit cost, generating direct losses on each unit sold.",
                "metric": f"{neg_c} Loss-Making Items",
                "underlying_metric": f"{neg_c} Loss-Making Items",
                "severity": "CRITICAL",
                "fields_used": [pricing.get("cost_column", "Cost"), pricing.get("price_column", "Price")]
            })

        avg_m = p_metrics.get("average_gross_margin_pct", 0)
        findings.append({
            "title": "Gross Margin Benchmark",
            "explanation": f"Catalogue exhibits an average gross margin of {avg_m}% with a median spread of {p_metrics.get('median_gross_margin_pct', avg_m)}%.",
            "metric": f"{avg_m}% Avg Margin",
            "underlying_metric": f"{avg_m}% Avg Margin",
            "severity": "INFO",
            "fields_used": [pricing.get("price_column", "Price"), pricing.get("cost_column", "Cost")]
        })

        top_p_list = pricing.get("highest_margin_products", pricing.get("top_margin_products", []))
        if top_p_list:
            top_p = top_p_list[0]
            m_pct = top_p.get("gross_margin_pct", top_p.get("margin_pct", 0))
            p_unit = top_p.get("gross_profit_per_unit", top_p.get("unit_profit", 0))
            findings.append({
                "title": f"Top Profit Yield: {top_p['product']}",
                "explanation": f"Highest profit efficiency achieved at {m_pct}% margin (${p_unit} unit profit).",
                "metric": f"{m_pct}% Margin",
                "underlying_metric": f"{m_pct}% Margin",
                "severity": "INFO",
                "fields_used": [pricing.get("price_column", "Price")]
            })

    # 3. Inventory Insights
    if inventory.get("computed") or inventory.get("available"):
        i_metrics = inventory.get("metrics", inventory)
        out_c = i_metrics.get("out_of_stock_count", 0)
        if out_c > 0:
            findings.append({
                "title": "Stockout Critical Warning",
                "explanation": f"{out_c} product line(s) have depleted inventory (0 units).",
                "metric": f"{out_c} Out of Stock",
                "underlying_metric": f"{out_c} Out of Stock",
                "severity": "CRITICAL",
                "fields_used": [inventory.get("quantity_column", "Stock")]
            })

        low_c = i_metrics.get("low_stock_count", 0)
        if low_c > 0:
            findings.append({
                "title": "Low Stock Replenishment Alert",
                "explanation": f"{low_c} item(s) are at or below reorder thresholds.",
                "metric": f"{low_c} Low Stock",
                "underlying_metric": f"{low_c} Low Stock",
                "severity": "WARNING",
                "fields_used": [inventory.get("quantity_column", "Stock")]
            })

        if i_metrics.get("total_inventory_valuation"):
            findings.append({
                "title": "Total Stock Asset Valuation",
                "explanation": f"Combined inventory asset value is calculated at $ {i_metrics['total_inventory_valuation']:,.2f}.",
                "metric": f"$ {i_metrics['total_inventory_valuation']:,.2f}",
                "underlying_metric": f"$ {i_metrics['total_inventory_valuation']:,.2f}",
                "severity": "INFO",
                "fields_used": [inventory.get("quantity_column", "Stock")]
            })

    # 4. Supplier Insights
    if suppliers.get("computed") or suppliers.get("available"):
        s_metrics = suppliers.get("metrics", suppliers)
        if s_metrics.get("supplier_concentration_pct", 0) >= 50:
            findings.append({
                "title": "High Supplier Concentration Risk",
                "explanation": f"Supplier '{s_metrics['primary_supplier']}' provisions {s_metrics['supplier_concentration_pct']}% of catalog items.",
                "metric": f"{s_metrics['supplier_concentration_pct']}% Concentration",
                "underlying_metric": f"{s_metrics['supplier_concentration_pct']}% Concentration",
                "severity": "WARNING",
                "fields_used": [suppliers.get("supplier_column", "Supplier")]
            })

    # 5. Sales Insights
    if sales.get("computed") or sales.get("available"):
        s_metrics = sales.get("metrics", sales)
        findings.append({
            "title": "Total Generated Revenue",
            "explanation": f"Gross transaction revenue across {s_metrics['transaction_count']} transactions stands at $ {s_metrics['total_revenue']:,.2f}.",
            "metric": f"$ {s_metrics['total_revenue']:,.2f}",
            "underlying_metric": f"$ {s_metrics['total_revenue']:,.2f}",
            "severity": "INFO",
            "fields_used": [sales.get("revenue_column", "Revenue")]
        })
        if s_metrics.get("returns_tracked") and s_metrics.get("returned_order_count", 0) > 0:
            ret_val = s_metrics.get("returned_sales_value", 0.0)
            net_val = s_metrics.get("net_sales", 0.0)
            ret_rate = s_metrics.get("return_rate_pct", 0.0)
            ret_count = s_metrics.get("returned_order_count", 0)
            findings.append({
                "title": "Return-Adjusted Net Revenue",
                "explanation": f"{ret_count} orders were returned ({ret_rate}% return rate), totaling $ {ret_val:,.2f} in return value. Net recognized sales after returns is $ {net_val:,.2f}.",
                "metric": f"Net: $ {net_val:,.2f} ({ret_rate}% Returned)",
                "underlying_metric": f"Net: $ {net_val:,.2f}",
                "severity": "WARNING" if ret_rate > 15.0 else "INFO",
                "fields_used": ["Returned", sales.get("revenue_column", "Revenue")]
            })

    return findings

# ==============================================================================
# 5. MAIN ORCHESTRATION PIPELINES
# ==============================================================================

def analyze_excel_dataset(file_data_or_name, sheets_dict_or_name=None, ext='xlsx'):
    """
    Main entry point for analyzing multi-sheet Excel workbooks.
    Supports either:
      - (file_bytes, file_name, ext)
      - (file_name, sheets_dict)
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheets_dict = {}
    file_name = "spreadsheet.xlsx"

    if isinstance(file_data_or_name, str) and isinstance(sheets_dict_or_name, dict):
        file_name = file_data_or_name
        sheets_dict = sheets_dict_or_name
    elif isinstance(file_data_or_name, (bytes, bytearray, io.BytesIO)):
        file_name = sheets_dict_or_name or "spreadsheet.xlsx"
        bio = file_data_or_name if isinstance(file_data_or_name, io.BytesIO) else io.BytesIO(file_data_or_name)
        if ext == 'csv' or file_name.lower().endswith('.csv'):
            try:
                sdf = pd.read_csv(bio, encoding='utf-8')
            except Exception:
                bio.seek(0)
                try:
                    sdf = pd.read_csv(bio, encoding='latin1')
                except Exception:
                    bio.seek(0)
                    sdf = pd.read_csv(bio, encoding='utf-8-sig', errors='ignore')
            sheets_dict = {"Sheet1": sdf}
        else:
            engine = 'openpyxl' if (ext == 'xlsx' or file_name.endswith('.xlsx')) else 'xlrd'
            excel_file = pd.ExcelFile(bio, engine=engine)
            for sname in excel_file.sheet_names:
                try:
                    sdf = pd.read_excel(excel_file, sheet_name=sname)
                    sheets_dict[str(sname)] = sdf
                except Exception:
                    pass
    elif isinstance(file_data_or_name, dict):
        sheets_dict = file_data_or_name
        file_name = sheets_dict_or_name or "spreadsheet.xlsx"

    # Select primary worksheet (sheet with highest row count)
    primary_sheet_name = max(sheets_dict.keys(), key=lambda s: len(sheets_dict[s])) if sheets_dict else "Sheet1"
    primary_df = sheets_dict[primary_sheet_name] if primary_sheet_name in sheets_dict else pd.DataFrame()

    # Map roles on primary sheet
    mapped_roles = map_column_roles(primary_df.columns)
    classification = classify_dataset(mapped_roles, len(primary_df))
    quality = audit_data_quality(primary_df, mapped_roles)
    columns_profile = profile_columns(primary_df)

    # Compute correlations and categorical distributions
    correlations = compute_correlation_matrix(primary_df)
    categorical_distributions = compute_categorical_distributions(primary_df)

    # Compute specialized domains
    pricing = compute_pricing_analytics(primary_df, mapped_roles)
    inventory = compute_inventory_analytics(primary_df, mapped_roles)
    sales = compute_sales_analytics(primary_df, mapped_roles)
    suppliers = compute_supplier_analytics(primary_df, mapped_roles)

    # Generate evidence-backed insights
    insights = generate_insights(classification, quality, pricing, inventory, sales, suppliers)

    # Add correlation findings to insights if significant
    if correlations.get("available") and correlations.get("significant_correlations"):
        for top_c in correlations["significant_correlations"][:2]:
            insights.append({
                "title": f"Linear Correlation: {top_c['col1']} vs {top_c['col2']}",
                "explanation": top_c["interpretation"],
                "metric": f"r = {top_c['correlation']}",
                "underlying_metric": f"r = {top_c['correlation']}",
                "severity": "INFO",
                "fields_used": [top_c["col1"], top_c["col2"]]
            })

    # Compile descriptive statistics for numeric columns
    numeric_descriptive = []
    for cp in columns_profile:
        if cp.get("inferred_type") == "numeric":
            st = dict(cp.get("stats", {}))
            st["column"] = cp["name"]
            st["type_display"] = cp.get("type_display", "Numeric")
            numeric_descriptive.append(st)

    statistics = {
        "available": True,
        "computed": True,
        "numeric_descriptive": numeric_descriptive,
        "correlations": correlations,
        "categorical_distributions": categorical_distributions
    }

    # Compile unavailable metrics with clear explanations
    unavailable_metrics = []
    if not pricing.get("available"):
        unavailable_metrics.append({
            "metric": "Pricing & Gross Margins",
            "required_columns": ["Cost Price", "Selling Price"],
            "reason": pricing.get("reason", "Missing cost or selling price columns.")
        })
    if not inventory.get("available"):
        unavailable_metrics.append({
            "metric": "Inventory & Stock Levels",
            "required_columns": ["Quantity / Stock"],
            "reason": inventory.get("reason", "Missing inventory / stock level column.")
        })
    if not sales.get("available"):
        unavailable_metrics.append({
            "metric": "Sales & Revenue Trends",
            "required_columns": ["Sales / Revenue", "Date"],
            "reason": sales.get("reason", "Missing sales revenue or transaction date columns.")
        })
    if not suppliers.get("available"):
        unavailable_metrics.append({
            "metric": "Supplier Spend & Concentration",
            "required_columns": ["Supplier / Vendor"],
            "reason": suppliers.get("reason", "Missing supplier / vendor name column.")
        })
    if not correlations.get("available"):
        unavailable_metrics.append({
            "metric": "Numeric Correlation Matrix",
            "required_columns": ["At least 2 numeric columns with non-zero variance"],
            "reason": correlations.get("reason", "Requires at least 2 distinct numeric columns.")
        })

    # Compile report summary
    total_rows = sum(len(df) for df in sheets_dict.values())
    total_cols = len(primary_df.columns)

    preview_rows = []
    for _, r in primary_df.head(10).iterrows():
        row_dict = {}
        for col in primary_df.columns:
            val = r[col]
            if pd.isna(val):
                row_dict[str(col)] = None
            elif hasattr(val, 'isoformat'):
                row_dict[str(col)] = val.isoformat()
            elif isinstance(val, (int, float, str, bool)):
                row_dict[str(col)] = val
            else:
                row_dict[str(col)] = str(val)
        preview_rows.append(row_dict)

    return {
        "success": True,
        "file_name": file_name,
        "file_type": "excel",
        "timestamp": now_str,
        "primary_sheet": primary_sheet_name,
        "sheet_names": list(sheets_dict.keys()),
        "dataset_summary": {
            "sheet_count": len(sheets_dict),
            "total_rows": total_rows,
            "total_columns": total_cols
        },
        "overview": {
            "total_worksheets": len(sheets_dict),
            "total_rows": total_rows,
            "total_columns": total_cols,
            "primary_sheet_rows": len(primary_df),
            "columns": list(primary_df.columns),
            "mapped_roles": mapped_roles
        },
        "columns": list(primary_df.columns),
        "column_profiles": columns_profile,
        "raw_preview_rows": preview_rows,
        "classification": classification,
        "data_quality": quality,
        "columns_profile": columns_profile,
        "statistics": statistics,
        "statistical_analysis": statistics,
        "correlations": correlations,
        "categorical_distributions": categorical_distributions,
        "pricing": pricing,
        "inventory": inventory,
        "sales": sales,
        "suppliers": suppliers,
        "unavailable_metrics": unavailable_metrics,
        "insights": insights
    }

def analyze_pdf_document(file_data_or_name, file_name=None, page_count=None, char_count=None, text_content=None):
    """
    Main entry point for analyzing PDF documents.
    Supports either:
      - (pdf_bytes, file_name)
      - (file_name, page_count, char_count, text_content)
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(file_data_or_name, (bytes, bytearray, io.BytesIO)):
        fn = file_name or "document.pdf"
        pdf_bytes = file_data_or_name.getvalue() if isinstance(file_data_or_name, io.BytesIO) else file_data_or_name
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(doc)
        pages_text = []
        for p in doc:
            t = p.get_text()
            if t:
                pages_text.append(t.strip())
        doc.close()
        text_content = "\n\n".join(pages_text).strip()
        char_count = len(text_content)
        file_name = fn
    elif isinstance(file_data_or_name, str) and (page_count is not None or text_content is not None):
        file_name = file_data_or_name
        page_count = page_count or 1
        char_count = char_count if char_count is not None else len(text_content or "")
    else:
        file_name = str(file_data_or_name)
        page_count = page_count or 1
        char_count = char_count or 0
        text_content = text_content or ""

    has_text = char_count > 0
    word_count = len(text_content.split()) if text_content else 0
    lower_text = text_content.lower() if text_content else ""

    # Résumé detection keywords
    resume_keywords = [
        'resume', 'curriculum vitae', 'cv', 'education', 'experience', 'employment',
        'skills', 'work experience', 'projects', 'certifications', 'qualifications',
        'contact', 'objective', 'summary', 'technical skills', 'professional experience'
    ]
    resume_matches = [kw for kw in resume_keywords if kw in lower_text]
    is_resume = len(resume_matches) >= 3 or 'curriculum vitae' in lower_text or 'resume' in lower_text

    # Extract candidate contact details
    emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text_content) if text_content else []
    phones = re.findall(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', text_content) if text_content else []
    links = re.findall(r'(?:https?:\/\/)?(?:www\.)?(?:linkedin\.com\/[^\s]+|github\.com\/[^\s]+)', text_content) if text_content else []

    # Detect key structural sections
    section_patterns = {
        'Education': r'(?i)\b(?:education|academic background|qualifications)\b',
        'Experience': r'(?i)\b(?:experience|employment|work history|professional experience)\b',
        'Skills': r'(?i)\b(?:skills|technical skills|technologies|proficiencies|competencies)\b',
        'Projects': r'(?i)\b(?:projects|key projects|portfolio)\b',
        'Certifications': r'(?i)\b(?:certifications|certificates|licenses|courses)\b'
    }
    detected_sections = {}
    if text_content:
        for sec_name, pat in section_patterns.items():
            m = re.search(pat, text_content)
            if m:
                start_pos = m.end()
                snippet = text_content[start_pos:start_pos+350].strip()
                snippet_lines = [line.strip() for line in snippet.split('\n') if line.strip()][:3]
                detected_sections[sec_name] = {
                    "detected": True,
                    "summary": " | ".join(snippet_lines) if snippet_lines else "Section heading identified."
                }

    # Keyword scanning for commercial / invoice evidence
    invoice_keywords = ['invoice', 'subtotal', 'total', 'tax', 'vat', 'gst', 'bill to', 'payment', 'due date']
    found_keywords = [kw for kw in invoice_keywords if kw in lower_text]
    is_commercial = len(found_keywords) >= 2 and not is_resume

    classification = classify_dataset({}, page_count, is_pdf=True)
    if is_resume:
        classification["category"] = "Professional Résumé / Curriculum Vitae"
        classification["detected_type"] = "Professional Résumé / Curriculum Vitae"
        classification["primary_focus"] = "Career profile, technical capabilities, credentials & education"
        classification["supported_analyses"] = ["Contact Extraction", "Section Profiling", "Skills & Credentials Identification", "Text Quality Audit"]
    elif is_commercial:
        classification["category"] = "Financial / Commercial PDF Document"
        classification["detected_type"] = "Financial / Commercial PDF Document"
        classification["primary_focus"] = "Commercial terminology detected; structured OCR required for line-item extraction"
        classification["supported_analyses"] = ["Keyword Extraction", "Document Structure", "Text Quality Audit"]

    # Document summary
    if is_resume:
        contact_parts = []
        if emails: contact_parts.append(emails[0])
        if phones: contact_parts.append(phones[0])
        contact_str = f" Contact: {', '.join(contact_parts)}." if contact_parts else ""
        sec_str = f" Sections: {', '.join(detected_sections.keys())}." if detected_sections else ""
        doc_summary = f"Candidate résumé document spanning {page_count} page(s) and {word_count:,} words.{sec_str}{contact_str}"
    elif has_text:
        first_para = text_content.strip().split('\n\n')[0]
        doc_summary = (first_para[:320] + "...") if len(first_para) > 320 else first_para
    else:
        doc_summary = "Document contains 0 extractable characters. Scanned raster graphic or empty PDF."

    # Extraction limitations
    extraction_limitations = [
        "Unstructured linear text: Multi-column formatting and visual sidebars are linearized sequentially.",
        "Graphic timelines, skill rating bars, and design icons are omitted from vector text streams.",
        "Commercial and business financial metrics (margins, unit pricing, inventory stock, vendor concentration) are strictly NOT applicable to personal résumés or general PDF documents."
    ]

    # Data Quality
    quality_score = 90.0 if has_text else 30.0
    issues = []
    if not has_text:
        issues.append({
            "severity": "CRITICAL",
            "column": "PAGE_CONTENT",
            "affected_count": page_count,
            "affected_records": page_count,
            "explanation": "No vector text extractable from document pages.",
            "message": "No vector text extractable from document pages.",
            "suggestion": "Document consists of scanned images or raster graphics. Optical Character Recognition (OCR) is required.",
            "suggested_correction": "Document consists of scanned images or raster graphics. Optical Character Recognition (OCR) is required."
        })
    elif char_count < 100:
        issues.append({
            "severity": "WARNING",
            "column": "PAGE_CONTENT",
            "affected_count": page_count,
            "affected_records": page_count,
            "explanation": "Low character volume extracted; content may be clipped or sparse.",
            "message": "Low character volume extracted; content may be clipped or sparse.",
            "suggestion": "Check PDF generation settings.",
            "suggested_correction": "Check PDF generation settings."
        })

    # Insights - STRICTLY document-focused, NEVER business metrics
    insights = [
        {
            "title": "Document Readability Profile",
            "explanation": f"Document contains {page_count} page(s), {word_count:,} words, and {char_count:,} characters of extracted text.",
            "metric": f"{page_count} Pages / {word_count} Words",
            "underlying_metric": f"{page_count} Pages / {word_count} Words",
            "severity": "INFO",
            "fields_used": ["Document Structure"]
        }
    ]

    if is_resume:
        if emails or phones:
            contact_preview = f"Email: {emails[0] if emails else 'N/A'} | Phone: {phones[0] if phones else 'N/A'}"
            insights.append({
                "title": "Candidate Contact Information Identified",
                "explanation": f"Extracted candidate contact channels: {contact_preview}.",
                "metric": "Contact Verified",
                "underlying_metric": "Contact Verified",
                "severity": "INFO",
                "fields_used": ["Contact Details"]
            })
        if detected_sections:
            insights.append({
                "title": "Dossier Structure Verified",
                "explanation": f"Reliably identified {len(detected_sections)} profile section(s): {', '.join(detected_sections.keys())}.",
                "metric": f"{len(detected_sections)} Sections Found",
                "underlying_metric": f"{len(detected_sections)} Sections Found",
                "severity": "INFO",
                "fields_used": ["Section Headers"]
            })
    elif is_commercial:
        insights.append({
            "title": "Financial Indicators Detected",
            "explanation": f"Detected commercial keywords: {', '.join(found_keywords)}. Document represents an invoice, bill, or receipt.",
            "metric": f"{len(found_keywords)} Keywords Found",
            "underlying_metric": f"{len(found_keywords)} Keywords Found",
            "severity": "INFO",
            "fields_used": ["Text Body"]
        })

    if not has_text:
        insights.append({
            "title": "OCR Prerequisite Notice",
            "explanation": "Document cannot be parsed for text or profile figures without an OCR vision pipeline.",
            "metric": "0 Characters",
            "underlying_metric": "0 Characters",
            "severity": "CRITICAL",
            "fields_used": ["Page Text Stream"]
        })

    unavailable_metrics = [
        {
            "metric": "Pricing & Gross Margins",
            "required_columns": ["Cost Price", "Selling Price"],
            "reason": "Business metrics not applicable to résumé or unstructured PDF text."
        },
        {
            "metric": "Inventory & Stock Levels",
            "required_columns": ["Quantity / Stock"],
            "reason": "Requires structured spreadsheet inventory columns."
        },
        {
            "metric": "Sales & Revenue Trends",
            "required_columns": ["Sales / Revenue", "Date"],
            "reason": "Requires structured dated transaction records."
        },
        {
            "metric": "Supplier Spend & Concentration",
            "required_columns": ["Supplier / Vendor"],
            "reason": "Requires structured vendor catalogue records."
        },
        {
            "metric": "Statistical Correlation Matrix",
            "required_columns": ["Numeric columns with variation"],
            "reason": "Statistical and correlation analysis requires tabular numeric records."
        }
    ]

    resume_intelligence = {
        "is_resume": is_resume,
        "contact_info": {
            "emails": emails[:3],
            "phones": phones[:3],
            "links": links[:3]
        },
        "detected_sections": detected_sections,
        "document_summary": doc_summary,
        "extraction_limitations": extraction_limitations
    }

    return {
        "success": True,
        "file_name": file_name,
        "file_type": "pdf",
        "timestamp": now_str,
        "dataset_summary": {
            "page_count": page_count,
            "char_count": char_count,
            "word_count": word_count,
            "has_text": has_text,
            "is_resume": is_resume
        },
        "overview": {
            "page_count": page_count,
            "char_count": char_count,
            "word_count": word_count,
            "has_text": has_text,
            "is_resume": is_resume,
            "detected_keywords": found_keywords if not is_resume else resume_matches[:6]
        },
        "classification": classification,
        "document_summary": doc_summary,
        "extraction_limitations": extraction_limitations,
        "resume_intelligence": resume_intelligence,
        "data_quality": {
            "score": quality_score,
            "grade": "A (Readable)" if has_text else "F (Unreadable Scanned Document)",
            "missing_cells_count": 0,
            "duplicate_rows_count": 0,
            "summary": {
                "errors": 1 if not has_text else 0,
                "warnings": 1 if char_count < 100 and has_text else 0,
                "info": 1 if has_text else 0
            },
            "issues": issues
        },
        "statistics": {
            "available": False,
            "computed": False,
            "reason": "Statistical analysis not applicable to unstructured PDF text."
        },
        "statistical_analysis": {
            "available": False,
            "computed": False,
            "reason": "Statistical analysis not applicable to unstructured PDF text."
        },
        "correlations": {
            "available": False,
            "computed": False,
            "reason": "Correlations require numeric tabular columns."
        },
        "categorical_distributions": {
            "available": False,
            "computed": False,
            "reason": "Categorical distributions require tabular columns."
        },
        "pricing": {
            "computed": False,
            "available": False,
            "reason": "Business metrics not applicable to résumé or unstructured PDF text."
        },
        "inventory": {
            "computed": False,
            "available": False,
            "reason": "Requires structured spreadsheet columns."
        },
        "sales": {
            "computed": False,
            "available": False,
            "reason": "Requires dated transaction table."
        },
        "suppliers": {
            "computed": False,
            "available": False,
            "reason": "Requires vendor catalogue table."
        },
        "unavailable_metrics": unavailable_metrics,
        "insights": insights,
        "text_preview": text_content[:2000] if text_content else "",
        "raw_text_preview": text_content[:2000] if text_content else ""
    }

# ==============================================================================
# 6. REPORT EXPORT GENERATORS (HTML, CSV, JSON)
# ==============================================================================

def export_report_to_html(report_data):
    """
    Generates a standalone, self-contained, cyberpunk Iron Man HUD styled HTML report.
    """
    fn = report_data.get("file_name", "dataset")
    ts = report_data.get("timestamp", "N/A")
    cat = report_data.get("classification", {}).get("category", "General Data")
    dq = report_data.get("data_quality", {})
    score = dq.get("score", 0)
    grade = dq.get("grade", "N/A")

    # Generate insights rows
    insights_html = ""
    for ins in report_data.get("insights", []):
        color = "#00f0ff" if ins['severity'] == "INFO" else ("#ffaa00" if ins['severity'] == "WARNING" else "#ff3344")
        insights_html += f"""
        <div style="background: rgba(0, 240, 255, 0.05); border-left: 3px solid {color}; padding: 12px; margin-bottom: 8px; border-radius: 4px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; color: #fff;">{ins['title']}</span>
                <span style="font-size: 0.75rem; color: {color}; border: 1px solid {color}; padding: 2px 6px; border-radius: 3px;">{ins['severity']}</span>
            </div>
            <p style="margin: 0; font-size: 0.88rem; color: #a0c4df;">{ins['explanation']}</p>
            <div style="margin-top: 6px; font-size: 0.75rem; color: #628ea6;">METRIC: <strong style="color: {color};">{ins['metric']}</strong></div>
        </div>
        """

    # Generate pricing table if available
    pricing_html = ""
    p = report_data.get("pricing", {})
    if p.get("available"):
        pricing_html = f"""
        <h2 style="color: #00f0ff; border-bottom: 1px solid rgba(0,240,255,0.2); padding-bottom: 6px;">PRICING & GROSS MARGIN METRICS</h2>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px;">
            <div style="background: rgba(0,240,255,0.06); padding: 10px; border-radius: 4px; text-align: center;">
                <span style="font-size: 0.75rem; color: #7899b5;">AVG GROSS MARGIN</span>
                <h3 style="color: #00f0ff; margin: 4px 0;">{p['metrics']['average_gross_margin_pct']}%</h3>
            </div>
            <div style="background: rgba(0,240,255,0.06); padding: 10px; border-radius: 4px; text-align: center;">
                <span style="font-size: 0.75rem; color: #7899b5;">MEDIAN MARGIN</span>
                <h3 style="color: #00f0ff; margin: 4px 0;">{p['metrics']['median_gross_margin_pct']}%</h3>
            </div>
            <div style="background: rgba(0,240,255,0.06); padding: 10px; border-radius: 4px; text-align: center;">
                <span style="font-size: 0.75rem; color: #7899b5;">AVG MARKUP</span>
                <h3 style="color: #00f0ff; margin: 4px 0;">{p['metrics']['average_markup_pct']}%</h3>
            </div>
            <div style="background: rgba(0,240,255,0.06); padding: 10px; border-radius: 4px; text-align: center;">
                <span style="font-size: 0.75rem; color: #ff3344;">NEGATIVE MARGINS</span>
                <h3 style="color: #ff3344; margin: 4px 0;">{p['metrics']['negative_margin_count']}</h3>
            </div>
        </div>
        """

    # Generate statistics / correlation HTML
    stats_html = ""
    stats = report_data.get("statistics", {})
    corrs = stats.get("correlations", {})
    cats = stats.get("categorical_distributions", {})
    num_stats = stats.get("numeric_descriptive", [])

    if stats.get("available") and (corrs.get("available") or cats.get("available") or num_stats):
        stats_html += """
        <div class="section-box">
            <h2 style="color: #00f0ff; border-bottom: 1px solid rgba(0,240,255,0.2); padding-bottom: 6px;">STATISTICAL ANALYSIS & CORRELATIONS</h2>
        """
        if num_stats:
            stats_html += """
            <h3 style="color: #a0c4df; font-size: 1rem; margin-top: 12px;">NUMERIC DESCRIPTIVE STATISTICS</h3>
            <div style="overflow-x: auto; margin-bottom: 16px;">
                <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem; text-align: left;">
                    <thead>
                        <tr style="border-bottom: 1px solid rgba(0,240,255,0.3); color: #00f0ff;">
                            <th style="padding: 8px;">COLUMN</th>
                            <th style="padding: 8px;">COUNT</th>
                            <th style="padding: 8px;">MEAN</th>
                            <th style="padding: 8px;">STD</th>
                            <th style="padding: 8px;">MIN</th>
                            <th style="padding: 8px;">25%</th>
                            <th style="padding: 8px;">MEDIAN</th>
                            <th style="padding: 8px;">75%</th>
                            <th style="padding: 8px;">MAX</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            for ns in num_stats:
                stats_html += f"""
                        <tr style="border-bottom: 1px solid rgba(0,240,255,0.1);">
                            <td style="padding: 8px; font-weight: bold; color: #fff;">{ns.get('column')}</td>
                            <td style="padding: 8px;">{ns.get('count', 'N/A')}</td>
                            <td style="padding: 8px; color: #00f0ff;">{ns.get('mean', 'N/A')}</td>
                            <td style="padding: 8px;">{ns.get('std', 'N/A')}</td>
                            <td style="padding: 8px;">{ns.get('min', 'N/A')}</td>
                            <td style="padding: 8px;">{ns.get('q25', 'N/A')}</td>
                            <td style="padding: 8px; color: #ffaa00;">{ns.get('median', 'N/A')}</td>
                            <td style="padding: 8px;">{ns.get('q75', 'N/A')}</td>
                            <td style="padding: 8px;">{ns.get('max', 'N/A')}</td>
                        </tr>
                """
            stats_html += """
                    </tbody>
                </table>
            </div>
            """

        if corrs.get("available") and corrs.get("matrix"):
            c_cols = corrs.get("columns", [])
            c_mat = corrs.get("matrix", {})
            stats_html += """
            <h3 style="color: #a0c4df; font-size: 1rem; margin-top: 16px;">PEARSON CORRELATION MATRIX</h3>
            <div style="overflow-x: auto; margin-bottom: 16px;">
                <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem; text-align: center;">
                    <thead>
                        <tr style="border-bottom: 1px solid rgba(0,240,255,0.3); color: #00f0ff;">
                            <th style="padding: 8px; text-align: left;">VARIABLE</th>
            """
            for col in c_cols:
                stats_html += f'<th style="padding: 8px;">{col}</th>'
            stats_html += """
                        </tr>
                    </thead>
                    <tbody>
            """
            for r_col in c_cols:
                stats_html += f'<tr style="border-bottom: 1px solid rgba(0,240,255,0.1);"><td style="padding: 8px; text-align: left; font-weight: bold; color: #fff;">{r_col}</td>'
                for col in c_cols:
                    val = c_mat.get(r_col, {}).get(col)
                    if val is None:
                        val_str = "N/A"
                        color_style = "color: #628ea6;"
                    else:
                        val_str = f"{val:.3f}"
                        if r_col == col:
                            color_style = "color: #00f0ff; font-weight: bold;"
                        elif val >= 0.5:
                            color_style = "color: #00ff88; font-weight: bold;"
                        elif val <= -0.5:
                            color_style = "color: #ff3344; font-weight: bold;"
                        else:
                            color_style = "color: #a0c4df;"
                    stats_html += f'<td style="padding: 8px; {color_style}">{val_str}</td>'
                stats_html += '</tr>'
            stats_html += """
                    </tbody>
                </table>
            </div>
            """

        if cats.get("available") and cats.get("distributions"):
            stats_html += """
            <h3 style="color: #a0c4df; font-size: 1rem; margin-top: 16px;">CATEGORICAL FREQUENCY DISTRIBUTIONS</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 16px;">
            """
            for col_name, c_data in cats["distributions"].items():
                stats_html += f"""
                <div style="background: rgba(0,240,255,0.04); border: 1px solid rgba(0,240,255,0.15); padding: 12px; border-radius: 4px;">
                    <div style="color: #00f0ff; font-weight: bold; margin-bottom: 6px;">{col_name} <span style="font-size: 0.75rem; color: #7899b5;">({c_data.get('distinct_count')} distinct)</span></div>
                    <div style="font-size: 0.8rem; margin-bottom: 8px; color: #a0c4df;">MODE: <strong style="color: #fff;">{c_data.get('mode')}</strong> ({c_data.get('mode_count')} records)</div>
                """
                for bd in c_data.get("breakdown", [])[:5]:
                    stats_html += f"""
                    <div style="display: flex; justify-content: space-between; font-size: 0.78rem; margin-bottom: 4px;">
                        <span style="color: #c5e3f6;">{bd.get('value')}</span>
                        <span style="color: #00f0ff;">{bd.get('count')} ({bd.get('percentage')}%)</span>
                    </div>
                    """
                stats_html += "</div>"
            stats_html += "</div>"

        stats_html += "</div>"

    # Generate Resume Intelligence HTML if applicable
    resume_html = ""
    r_intel = report_data.get("resume_intelligence", {})
    if r_intel.get("is_resume"):
        c_info = r_intel.get("contact_info", {})
        secs = r_intel.get("detected_sections", {})
        resume_html += f"""
        <div class="section-box">
            <h2 style="color: #00f0ff; border-bottom: 1px solid rgba(0,240,255,0.2); padding-bottom: 6px;">RÉSUMÉ DOSSIER INTELLIGENCE</h2>
            <p style="color: #c5e3f6; font-size: 0.9rem; line-height: 1.5;">{r_intel.get('document_summary', '')}</p>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 16px 0;">
                <div style="background: rgba(0,240,255,0.05); padding: 10px; border-radius: 4px;">
                    <div style="font-size: 0.75rem; color: #7899b5;">IDENTIFIED EMAILS</div>
                    <div style="color: #00f0ff; font-size: 0.85rem; margin-top: 4px;">{', '.join(c_info.get('emails', [])) or 'None detected'}</div>
                </div>
                <div style="background: rgba(0,240,255,0.05); padding: 10px; border-radius: 4px;">
                    <div style="font-size: 0.75rem; color: #7899b5;">IDENTIFIED PHONES</div>
                    <div style="color: #00f0ff; font-size: 0.85rem; margin-top: 4px;">{', '.join(c_info.get('phones', [])) or 'None detected'}</div>
                </div>
                <div style="background: rgba(0,240,255,0.05); padding: 10px; border-radius: 4px;">
                    <div style="font-size: 0.75rem; color: #7899b5;">PROFILES & LINKS</div>
                    <div style="color: #00f0ff; font-size: 0.85rem; margin-top: 4px;">{', '.join(c_info.get('links', [])) or 'None detected'}</div>
                </div>
            </div>
            <h3 style="color: #a0c4df; font-size: 1rem; margin-top: 14px;">IDENTIFIED PROFILE SECTIONS</h3>
            <div style="display: flex; flex-direction: column; gap: 8px;">
        """
        for s_name, s_val in secs.items():
            resume_html += f"""
            <div style="background: rgba(0,240,255,0.03); border-left: 2px solid #00f0ff; padding: 8px 12px;">
                <strong style="color: #fff; font-size: 0.88rem;">{s_name}</strong>
                <p style="margin: 4px 0 0 0; font-size: 0.82rem; color: #7899b5;">{s_val.get('summary', '')}</p>
            </div>
            """
        resume_html += """
            </div>
            <h3 style="color: #a0c4df; font-size: 1rem; margin-top: 16px;">EXTRACTION LIMITATIONS</h3>
            <ul style="color: #7899b5; font-size: 0.82rem; margin: 4px 0; padding-left: 20px;">
        """
        for lim in r_intel.get("extraction_limitations", []):
            resume_html += f"<li>{lim}</li>"
        resume_html += "</ul></div>"

    # Generate Unavailable Metrics explanation HTML
    unavail_html = ""
    unavail = report_data.get("unavailable_metrics", [])
    if unavail:
        unavail_html = """
        <div class="section-box">
            <h2 style="color: #ffaa00; border-bottom: 1px solid rgba(255,170,0,0.2); padding-bottom: 6px;">EXPLANATION OF UNAVAILABLE METRICS</h2>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-top: 12px;">
        """
        for um in unavail:
            req_cols = ", ".join(um.get("required_columns", []))
            unavail_html += f"""
            <div style="background: rgba(255,170,0,0.05); border-left: 3px solid #ffaa00; padding: 12px; border-radius: 4px;">
                <div style="color: #fff; font-weight: bold; font-size: 0.9rem;">{um.get('metric')}</div>
                <div style="color: #ffaa00; font-size: 0.78rem; margin: 4px 0;">REQUIRED: {req_cols}</div>
                <div style="color: #a0c4df; font-size: 0.82rem;">{um.get('reason')}</div>
            </div>
            """
        unavail_html += "</div></div>"

    # Assemble HTML
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SARTHI Business Intelligence Report - {fn}</title>
    <style>
        body {{
            background: #030811;
            color: #e0f4ff;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 30px;
        }}
        .report-header {{
            border-bottom: 2px solid #00f0ff;
            padding-bottom: 16px;
            margin-bottom: 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .brand-title {{
            font-size: 1.8rem;
            letter-spacing: 3px;
            color: #fff;
            margin: 0;
            text-shadow: 0 0 10px rgba(0,240,255,0.5);
        }}
        .meta-tag {{
            color: #7899b5;
            font-size: 0.85rem;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: rgba(6, 17, 33, 0.85);
            border: 1px solid rgba(0, 240, 255, 0.25);
            border-radius: 6px;
            padding: 16px;
            text-align: center;
        }}
        .kpi-val {{
            font-size: 1.6rem;
            color: #00f0ff;
            font-weight: 700;
            margin: 8px 0;
        }}
        .section-box {{
            background: rgba(6, 17, 33, 0.7);
            border: 1px solid rgba(0, 240, 255, 0.2);
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 24px;
        }}
    </style>
</head>
<body>
    <div class="report-header">
        <div>
            <h1 class="brand-title">SARTHI BUSINESS INTELLIGENCE DOSSIER</h1>
            <div class="meta-tag">SARTHI BUSINESS INTELLIGENCE // SOURCE: {fn} // GENERATED: {ts}</div>
        </div>
        <div style="text-align: right;">
            <div style="color: #ffaa00; font-weight: 700;">{cat.upper()}</div>
            <div class="meta-tag">SARTHI TACTICAL ANALYTICS</div>
        </div>
    </div>

    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="meta-tag">DATA HEALTH SCORE</div>
            <div class="kpi-val">{score}%</div>
            <div style="font-size: 0.8rem; color: #a0c4df;">{grade}</div>
        </div>
        <div class="kpi-card">
            <div class="meta-tag">RECORDS ANALYZED</div>
            <div class="kpi-val">{report_data.get("overview", {}).get("total_rows", report_data.get("dataset_summary", {}).get("page_count", "N/A"))}</div>
            <div style="font-size: 0.8rem; color: #a0c4df;">{'Worksheet Entries' if report_data.get('file_type') == 'excel' else 'Pages Extracted'}</div>
        </div>
        <div class="kpi-card">
            <div class="meta-tag">DATA FIELDS / METRICS</div>
            <div class="kpi-val">{report_data.get("overview", {}).get("total_columns", report_data.get("dataset_summary", {}).get("char_count", "N/A"))}</div>
            <div style="font-size: 0.8rem; color: #a0c4df;">{'Detected Columns' if report_data.get('file_type') == 'excel' else 'Extracted Characters'}</div>
        </div>
        <div class="kpi-card">
            <div class="meta-tag">CRITICAL ISSUES</div>
            <div class="kpi-val" style="color: {'#ff3344' if dq.get('summary', {}).get('errors', 0) > 0 else '#00f0ff'};">
                {dq.get('summary', {}).get('errors', 0)}
            </div>
            <div style="font-size: 0.8rem; color: #a0c4df;">Errors Requiring Fix</div>
        </div>
    </div>

    {pricing_html}
    {stats_html}
    {resume_html}

    <div class="section-box">
        <h2 style="color: #00f0ff; border-bottom: 1px solid rgba(0,240,255,0.2); padding-bottom: 6px;">EVIDENCE-BASED INSIGHTS & FINDINGS</h2>
        {insights_html}
    </div>

    {unavail_html}

    <footer style="text-align: center; color: #628ea6; font-size: 0.75rem; border-top: 1px solid rgba(0,240,255,0.1); padding-top: 16px;">
        CONFIDENTIAL BUSINESS INTEL // PROCESSED LOCALLY BY SARTHI ENGINE
    </footer>
</body>
</html>
"""

def export_report_to_csv(report_data):
    """
    Generates a consolidated CSV string containing dataset overview, stats, and findings.
    """
    lines = []
    lines.append("SARTHI BUSINESS INTELLIGENCE REPORT")
    lines.append(f"File Name,{report_data.get('file_name', '')}")
    lines.append(f"File Type,{report_data.get('file_type', '')}")
    lines.append(f"Generated Timestamp,{report_data.get('timestamp', '')}")
    lines.append(f"Classification Category,\"{report_data.get('classification', {}).get('category', '')}\"")
    lines.append(f"Data Quality Score,{report_data.get('data_quality', {}).get('score', '')}%")
    lines.append(f"Data Quality Grade,\"{report_data.get('data_quality', {}).get('grade', '')}\"")
    lines.append("")

    # Insights section
    lines.append("INSIGHTS & ACTIONABLE FINDINGS")
    lines.append("Severity,Title,Explanation,Metric,Fields Used")
    for ins in report_data.get("insights", []):
        fields = "; ".join(ins.get("fields_used", []))
        lines.append(f"\"{ins['severity']}\",\"{ins['title']}\",\"{ins['explanation']}\",\"{ins['metric']}\",\"{fields}\"")
    lines.append("")

    # Pricing metrics section if available
    p = report_data.get("pricing", {})
    if p.get("available"):
        lines.append("PRICING & PROFITABILITY SUMMARY")
        m = p.get("metrics", {})
        lines.append(f"Average Gross Margin %,{m.get('average_gross_margin_pct', '')}")
        lines.append(f"Median Gross Margin %,{m.get('median_gross_margin_pct', '')}")
        lines.append(f"Average Markup %,{m.get('average_markup_pct', '')}")
        lines.append(f"Negative Margin Count,{m.get('negative_margin_count', '')}")
        lines.append("")

    # Statistical correlation section if available
    corrs = report_data.get("statistics", {}).get("correlations", {})
    if corrs.get("available") and corrs.get("significant_correlations"):
        lines.append("SIGNIFICANT PEARSON CORRELATIONS")
        lines.append("Variable 1,Variable 2,Correlation (r),Strength,Interpretation")
        for sc in corrs["significant_correlations"]:
            lines.append(f"\"{sc['col1']}\",\"{sc['col2']}\",{sc['correlation']},\"{sc['strength']}\",\"{sc['interpretation']}\"")
        lines.append("")

    # Data Quality Issues
    lines.append("DATA QUALITY ISSUES")
    lines.append("Severity,Column,Affected Count,Explanation,Suggested Correction")
    for issue in report_data.get("data_quality", {}).get("issues", []):
        lines.append(f"\"{issue['severity']}\",\"{issue['column']}\",{issue['affected_count']},\"{issue['explanation']}\",\"{issue['suggestion']}\"")

    return "\n".join(lines)

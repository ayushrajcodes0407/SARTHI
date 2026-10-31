"""
J.A.R.V.I.S. Central Intent Router & Intelligence Dispatcher
Module: intent_router.py
Author: Antigravity AI Engineering
Description:
    Provides unified, deterministic intent classification and data source resolution
    for both voice and typed console orders in J.A.R.V.I.S.:
    1. Product Catalogue Queries
    2. Inventory & Stock Audits
    3. Dataset Summaries & Dimensions
    4. Column-level Profiling, Statistics, Filtering, and Grouping
    5. Data Quality and Missing Values
    6. Commercial Business Intelligence & Report Synthesis
    7. Assistant Protocols (Diagnostics, Jokes, Media, Wikipedia)
"""

import re
import datetime
import logging
from typing import Dict, List, Any, Optional, Tuple

import requests
import pyjokes
import psutil
import wikipedia
import platform

import database
import dataset_intelligence
import business_insights
import local_llm
import multilingual
import rag_engine

logger = logging.getLogger("JARVIS-IntentRouter")



def resolve_dataset_from_query(query: str, db_path: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[List[Dict[str, Any]]]]:
    """
    Attempts to identify an explicitly mentioned dataset by filename, dataset ID, or source name.
    Returns: (matched_dataset_id, status, candidate_datasets)
    status can be: 'single_match', 'multiple_matches', 'no_match'
    """
    q_lower = query.lower()

    # Look for dataset ID pattern (e.g. ds_1234567890ab)
    id_match = re.search(r'\b(ds_[0-9a-f]{8,16})\b', q_lower)
    if id_match:
        ds_id = id_match.group(1)
        ds = database.get_dataset_by_id(ds_id, db_path=db_path)
        if ds:
            return ds["id"], "single_match", None

    # Look for explicit file mentions with extensions (.xlsx, .xls, .pdf, .csv)
    file_match = re.search(r'\b([a-zA-Z0-9_\-\.\ ]+\.(xlsx|xls|pdf|csv))\b', query, re.IGNORECASE)
    if file_match:
        fn = file_match.group(1).strip()
        ds_res = database.list_datasets(search=fn, db_path=db_path)
        matches = ds_res.get("datasets") or ds_res.get("items") or []
        if len(matches) == 1:
            return matches[0]["id"], "single_match", None
        elif len(matches) > 1:
            return None, "multiple_matches", matches

    # Check for "in <dataset>", "for <dataset>", "from <dataset>", "dataset <name>"
    triggers = [r'\bin dataset ([a-zA-Z0-9_\-]+)\b', r'\bfrom dataset ([a-zA-Z0-9_\-]+)\b', r'\bfor dataset ([a-zA-Z0-9_\-]+)\b', r'\bdataset ([a-zA-Z0-9_\-]+)\b']
    for pattern in triggers:
        m = re.search(pattern, q_lower)
        if m:
            target_name = m.group(1).strip()
            ds_res = database.list_datasets(search=target_name, db_path=db_path)
            matches = ds_res.get("datasets") or ds_res.get("items") or []
            if len(matches) == 1:
                return matches[0]["id"], "single_match", None
            elif len(matches) > 1:
                return None, "multiple_matches", matches

    return None, "no_match", None


def get_effective_dataset_id(query: str, context: Optional[Dict[str, Any]] = None, db_path: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Resolves the target dataset ID using query mentions, active context, or most recent saved dataset.
    Returns: (dataset_id, disambiguation_response_or_none)
    """
    context = context or {}

    # 1. Check if user explicitly mentioned a dataset
    ds_id, status, candidates = resolve_dataset_from_query(query, db_path=db_path)
    if status == "multiple_matches" and candidates:
        names = ", ".join([f"'{c['original_filename']}' (ID: {c['id']})" for c in candidates[:3]])
        speak_text = f"I found multiple datasets matching your request: {names}. Please specify which dataset or ID you would like me to analyze."
        disambiguation = {
            "speak": speak_text,
            "display": f"Multiple datasets matched: {len(candidates)} found",
            "action": "dataset_clarify",
            "source": "Saved Dataset Library",
            "source_type": "dataset",
            "candidates": candidates[:5],
            "follow_ups": [f"Summarise dataset {c['id']}" for c in candidates[:3]]
        }
        return None, disambiguation

    if ds_id:
        return ds_id, None

    # 2. Check active context (CURRENT_FILE_INFO or active_dataset_id)
    if context.get("active_dataset_id"):
        return context["active_dataset_id"], None
    cf_info = context.get("current_file_info")
    if isinstance(cf_info, dict) and cf_info.get("dataset_id"):
        return cf_info["dataset_id"], None

    # 3. Fallback to latest active dataset in SQLite
    ds_list_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
    latest = ds_list_res.get("datasets") or ds_list_res.get("items") or []
    if latest:
        return latest[0]["id"], None

    return None, None


def route_intent(raw_command: str, context: Optional[Dict[str, Any]] = None, db_path: Optional[str] = None, request_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Central intent routing and execution engine for SARTHI.
    Guarantees deterministic execution across product catalogue, inventory,
    tabular dataset queries, business intelligence, and assistant commands.
    """
    cmd = (raw_command or "").strip()
    c_lower = cmd.lower()
    context = context or {}
    session_id = context.get("session_id")
    session_ctx = multilingual.get_session_context(session_id)

    if not cmd:
        resp = {
            "speak": "I am standing by. How can I assist you today?",
            "display": "Awaiting tactical order...",
            "action": "none",
            "source": "SARTHI Core",
            "source_type": "system"
        }
        if request_id:
            resp["request_id"] = request_id
        return resp

    cat_conn = database.get_connection(db_path) if db_path else None
    try:
        resp = _route_intent_internal(cmd, c_lower, context, db_path, cat_conn, session_id=session_id)
        cleaned_cmd, detected_lang = multilingual.clean_query(cmd)
        session_ctx.record_turn(
            query=cmd,
            response=resp,
            intent=resp.get("action", "unknown"),
            category=resp.get("source_type", "assistant"),
            language=detected_lang
        )
        if request_id:
            resp["request_id"] = request_id
        return resp
    finally:
        if cat_conn:
            try:
                cat_conn.close()
            except Exception:
                pass



# =========================================================================
# DETERMINISTIC RESPONSE BUILDERS (Executed by both LLM & Regex Matchers)
# =========================================================================

def _build_product_list_response(cat_conn: Any, source_label: str = "Product Catalogue", lang: str = "en") -> Dict[str, Any]:
    prods = database.list_products(is_active=True, page_size=50, conn=cat_conn)
    total = prods["total_count"]
    items = prods["items"]

    # Store retrieved products in conversational session context for follow-up questions
    multilingual.SESSION_CONTEXT.update_products(items, language=lang)

    if total == 0:
        loc = multilingual.format_multilingual_response("product_list", lang, {"items": [], "total": 0})
        speak_text = loc["speak"]
        display_text = loc["display"]
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "catalogue_list",
            "source": source_label,
            "source_type": "catalogue",
            "total_count": 0,
            "match_count": 0,
            "table": {"columns": ["SKU", "NAME", "CATEGORY", "STOCK", "SELLING PRICE", "STATUS"], "rows": []},
            "follow_ups": ["Open Catalogue Modal", "Map spreadsheet to catalogue"]
        }

    sample_names = ", ".join([p["name"] for p in items[:3]])
    more_str = f" and {total - 3} more" if total > 3 else ""

    if lang in ("hi", "hinglish"):
        loc = multilingual.format_multilingual_response("product_list", lang, {"items": items, "total": total})
        speak_text = loc["speak"]
        display_text = loc["display"]
    else:
        speak_text = f"There are {total} active products in the catalogue, including {sample_names}{more_str}."
        display_text = f"Catalogue: {total} active products ({len(items)} shown)"

    table_rows = []
    for p in items:
        status_str = "OUT OF STOCK" if p.get("is_out_of_stock") else ("LOW STOCK" if p.get("is_low_stock") else "IN STOCK")
        table_rows.append({
            "id": p.get("id"),
            "sku": p.get("sku") or "--",
            "name": p.get("name"),
            "category": p.get("category") or "General",
            "stock": f"{p.get('quantity_on_hand', 0)} {p.get('unit', 'piece')}",
            "selling_price": f"₹{p.get('selling_price', 0):,.2f}",
            "status": status_str
        })

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "catalogue_list",
        "source": source_label,
        "source_type": "catalogue",
        "total_count": total,
        "match_count": len(items),
        "table": {
            "columns": ["SKU", "NAME", "CATEGORY", "STOCK", "SELLING PRICE", "STATUS"],
            "rows": table_rows
        },
        "products": items,
        "follow_ups": ["Which products are low in stock?", "Which products are out of stock?", "Check inventory summary"]
    }


def _build_product_count_response(cat_conn: Any, source_label: str = "Product Catalogue", lang: str = "en") -> Dict[str, Any]:
    summary = database.get_inventory_summary(conn=cat_conn)
    active = summary["active_products"]
    units = summary["total_stock_units"]

    if lang in ("hi", "hinglish"):
        loc = multilingual.format_multilingual_response("product_count", lang, {"active": active, "units": units})
        speak_text = loc["speak"]
        display_text = loc["display"]
    else:
        speak_text = f"We have {active} active products in the catalogue, totaling {units:,.1f} stock units across all inventory lines."
        display_text = f"Total Products: {active} | Stock Units: {units:,.1f}"

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "catalogue_count",
        "source": source_label,
        "source_type": "catalogue",
        "total_count": active,
        "summary": summary,
        "follow_ups": ["What are all products?", "Which products are low in stock?"]
    }


def _build_inventory_summary_response(cat_conn: Any, source_label: str = "Inventory Ledger", lang: str = "en") -> Dict[str, Any]:
    summary = database.get_inventory_summary(conn=cat_conn)
    active = summary.get("active_products", 0)
    units = summary.get("total_stock_units", 0.0)
    valuation = summary.get("total_inventory_valuation", 0.0)
    low_res = database.list_products(low_stock=True, is_active=True, conn=cat_conn)
    low_count = len(low_res.get("items", []))

    if lang in ("hi", "hinglish"):
        loc = multilingual.format_multilingual_response("inventory_summary", lang, {
            "active": active,
            "units": units,
            "valuation": valuation,
            "low_count": low_count
        })
        speak_text = loc["speak"]
        display_text = loc["display"]
    else:
        speak_text = f"Overall inventory status: {active} active products, totaling {units:,.1f} units in stock with an inventory valuation of ₹{valuation:,.2f}. {low_count} items are at or below reorder level."
        display_text = f"Inventory Summary: {active} products | Stock: {units:,.1f} | Value: ₹{valuation:,.2f}"

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "inventory_summary",
        "source": source_label,
        "source_type": "inventory",
        "summary": summary,
        "total_products": active,
        "total_stock_units": units,
        "total_valuation": valuation,
        "low_stock_count": low_count,
        "follow_ups": ["Show all products", "Which products are low in stock?"]
    }


def _build_product_verify_response(cat_conn: Any, source_label: str = "Catalogue Audit", lang: str = "en") -> Dict[str, Any]:
    prods = database.list_products(is_active=True, page_size=1000, conn=cat_conn)
    items = prods.get("items", [])
    total_checked = len(items)

    issues = []
    for p in items:
        sku = (p.get("sku") or "").strip()
        sp = p.get("selling_price")
        pp = p.get("purchase_price")
        qty = p.get("quantity_on_hand", 0)
        reorder = p.get("reorder_level", 0)

        item_problems = []
        if not sku:
            item_problems.append("Missing SKU")
        if sp is None or sp <= 0:
            item_problems.append("Missing or zero selling price")
        if pp is None or pp <= 0:
            item_problems.append("Missing or zero purchase price")
        elif sp is not None and sp < pp:
            item_problems.append(f"Inverted margin (Selling ₹{sp} < Cost ₹{pp})")
        if qty <= 0:
            item_problems.append("Out of stock")
        elif qty <= reorder:
            item_problems.append(f"Low stock ({qty}/{reorder})")

        if item_problems:
            issues.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "sku": sku or "N/A",
                "issues": ", ".join(item_problems)
            })

    if lang in ("hi", "hinglish"):
        loc = multilingual.format_multilingual_response("product_verify", lang, {
            "issues": issues,
            "total_checked": total_checked
        })
        speak_text = loc["speak"]
        display_text = loc["display"]
    else:
        if not issues:
            speak_text = f"Catalogue verification complete. All {total_checked} products have valid SKUs, pricing structures, and inventory records."
            display_text = f"Catalogue Verified: All {total_checked} products passed integrity audit"
        else:
            sample_issues = ", ".join([f"{i['name']} ({i['issues']})" for i in issues[:2]])
            speak_text = f"Product verification completed across {total_checked} catalogue items. Found {len(issues)} items requiring attention: {sample_issues}."
            display_text = f"Verification Report: {len(issues)} issues detected in {total_checked} products"

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "product_verify",
        "source": source_label,
        "source_type": "catalogue",
        "total_checked": total_checked,
        "issues_count": len(issues),
        "issues": issues,
        "table": {
            "columns": ["NAME", "SKU", "AUDIT STATUS"],
            "rows": [{"name": i["name"], "sku": i["sku"], "status": i["issues"]} for i in issues]
        },
        "follow_ups": ["Show all products", "Which products are low in stock?"]
    }


def _build_lowest_stock_response(cat_conn: Any, source_label: str = "Inventory Ledger", lang: str = "en") -> Dict[str, Any]:
    prods = database.list_products(is_active=True, page_size=1000, conn=cat_conn)
    items = prods.get("items", [])
    if not items:
        return _build_product_list_response(cat_conn, source_label=source_label, lang=lang)

    # Sort ascending by stock quantity
    sorted_items = sorted(items, key=lambda x: x.get("quantity_on_hand", 0))
    top_lowest = sorted_items[:5]

    loc = multilingual.format_multilingual_response("lowest_stock", lang, {"items": top_lowest})
    speak_text = loc["speak"]
    display_text = loc["display"]

    rows = [{
        "sku": p.get("sku") or "--",
        "name": p.get("name"),
        "stock": f"{p.get('quantity_on_hand', 0)} {p.get('unit', 'piece')}",
        "reorder_level": f"{p.get('reorder_level', 0)} {p.get('unit', 'piece')}"
    } for p in top_lowest]

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "catalogue_lowest_stock",
        "source": source_label,
        "source_type": "inventory",
        "items": top_lowest,
        "table": {"columns": ["SKU", "NAME", "CURRENT STOCK", "REORDER LEVEL"], "rows": rows},
        "follow_ups": ["Show all products", "Which products are out of stock?"]
    }


def _build_contextual_pricing_response(cat_conn: Any, mode: str = "cheapest", source_label: str = "Product Catalogue", lang: str = "en") -> Dict[str, Any]:
    candidates = multilingual.SESSION_CONTEXT.last_products
    if not candidates:
        prods = database.list_products(is_active=True, page_size=1000, conn=cat_conn)
        candidates = prods.get("items", [])

    valid = [p for p in candidates if p.get("selling_price") is not None and p.get("selling_price") > 0]
    if not valid:
        if lang == "hi":
            speak_text = "कैटलॉग में कोई वैध कीमत वाला प्रोडक्ट नहीं मिला।"
            display_text = "कोई प्रोडक्ट नहीं मिला"
        elif lang == "hinglish":
            speak_text = "Catalogue mein koi valid price wala product nahi mila."
            display_text = "Koi product nahi mila"
        else:
            speak_text = "No products with valid selling prices were found."
            display_text = "No valid products found"
        return {"speak": speak_text, "display": display_text, "action": "contextual_pricing", "source": source_label, "source_type": "catalogue"}

    if mode == "cheapest":
        chosen = min(valid, key=lambda x: x.get("selling_price", 0))
        intent_key = "cheapest_product"
    else:
        chosen = max(valid, key=lambda x: x.get("selling_price", 0))
        intent_key = "expensive_product"

    multilingual.SESSION_CONTEXT.update_product(chosen, language=lang)
    loc = multilingual.format_multilingual_response(intent_key, lang, {"product": chosen})
    return {
        "speak": loc["speak"],
        "display": loc["display"],
        "action": intent_key,
        "source": source_label,
        "source_type": "catalogue",
        "product": chosen,
        "follow_ups": [f"What is the stock of {chosen['name']}?", "Show all products"]
    }


def _build_low_stock_response(cat_conn: Any, source_label: str = "Inventory Ledger", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    res = database.list_products(low_stock=True, is_active=True, conn=cat_conn, db_path=db_path)
    items = res["items"]
    if not items:
        if lang == "hi":
            speak_text = "कैटलॉग के सभी प्रोडक्ट्स में पर्याप्त स्टॉक उपलब्ध है।"
            display_text = "कम स्टॉक: 0 प्रोडक्ट्स"
        elif lang == "hinglish":
            speak_text = "Sabhi active products mein sufficient stock available hai. Koi low stock alert nahi hai."
            display_text = "Low Stock: 0 items"
        else:
            speak_text = "All active catalogue products have sufficient stock levels above their reorder thresholds."
            display_text = "Low Stock: 0 items"
        rows = []
    else:
        names = [f"{p['name']} ({p['quantity_on_hand']}/{p['reorder_level']} {p['unit']})" for p in items[:3]]
        if lang == "hi":
            speak_text = f"{len(items)} प्रोडक्ट्स का स्टॉक रीऑर्डर सीमा से कम है: " + ", ".join(names) + "।"
            display_text = f"कम स्टॉक: {len(items)} प्रोडक्ट्स"
        elif lang == "hinglish":
            speak_text = f"{len(items)} products reorder level se niche hain: " + ", ".join(names) + "."
            display_text = f"Low Stock: {len(items)} items below reorder"
        else:
            speak_text = f"There are {len(items)} products below reorder thresholds: " + ", ".join(names) + "."
            display_text = f"Low Stock: {len(items)} items below reorder"
        rows = [{
            "sku": p.get("sku") or "--",
            "name": p.get("name"),
            "stock": f"{p.get('quantity_on_hand')} {p.get('unit')}",
            "reorder_level": f"{p.get('reorder_level')} {p.get('unit')}"
        } for p in items]

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "catalogue_low_stock",
        "source": source_label,
        "source_type": "catalogue",
        "total_count": len(items),
        "match_count": len(items),
        "low_stock_products": items,
        "table": {"columns": ["SKU", "NAME", "STOCK", "REORDER LEVEL"], "rows": rows},
        "items": items,
        "follow_ups": ["Which products are out of stock?", "Show all products"]
    }


def _build_out_of_stock_response(cat_conn: Any, source_label: str = "Inventory Ledger", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    res = database.list_products(out_of_stock=True, is_active=True, conn=cat_conn, db_path=db_path)
    items = res["items"]
    if not items:
        if lang == "hi":
            speak_text = "कैटलॉग में कोई भी प्रोडक्ट आउट ऑफ स्टॉक नहीं है।"
            display_text = "आउट ऑफ स्टॉक: 0 प्रोडक्ट्स"
        elif lang == "hinglish":
            speak_text = "Badhiya khabar! Catalogue mein koi bhi product out of stock nahi hai."
            display_text = "Out of Stock: 0 items"
        else:
            speak_text = "Excellent news: there are currently zero products out of stock in the catalogue."
            display_text = "Out of Stock: 0 items"
        rows = []
    else:
        names = [f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]]
        if lang == "hi":
            speak_text = f"{len(items)} प्रोडक्ट्स का स्टॉक समाप्त हो चुका है: " + ", ".join(names) + "।"
            display_text = f"आउट ऑफ स्टॉक: {len(items)} प्रोडक्ट्स"
        elif lang == "hinglish":
            speak_text = f"{len(items)} products ka stock khatam ho gaya hai: " + ", ".join(names) + "."
            display_text = f"Out of Stock: {len(items)} items"
        else:
            speak_text = f"There are {len(items)} products currently out of stock: " + ", ".join(names) + "."
            display_text = f"Out of Stock: {len(items)} items"
        rows = [{
            "sku": p.get("sku") or "--",
            "name": p.get("name"),
            "category": p.get("category") or "General",
            "selling_price": f"₹{p.get('selling_price', 0):,.2f}"
        } for p in items]

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "catalogue_out_of_stock",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": len(items),
        "table": {"columns": ["SKU", "NAME", "CATEGORY", "SELLING PRICE"], "rows": rows},
        "items": items,
        "follow_ups": ["Which products are low in stock?", "Show all products"]
    }


def _build_selling_price_response(target: str, cat_conn: Any, source_label: str = "Product Catalogue", lang: str = "en", session_id: Optional[str] = None) -> Dict[str, Any]:
    target = target.rstrip('?.')
    session_ctx = multilingual.get_session_context(session_id)
    # Check contextual resolution if target is generic
    if target in ("context_product", "is product", "iss product", "this product", "product") and session_ctx.last_product:
        target = session_ctx.last_product["name"]

    res = database.list_products(search=target, is_active=True, conn=cat_conn)
    items = res["items"]

    if not items:
        if lang in ("hi", "hinglish"):
            loc = multilingual.format_multilingual_response("product_not_found", lang, {"query": target})
            speak_text = loc["speak"]
            display_text = loc["display"]
        else:
            speak_text = f"Product '{target}' was not found in the catalogue. Would you like to view all active products?"
            display_text = f"Price: No match for '{target}'"
        session_ctx.set_pending_action(action="product_list", prompt=speak_text, language=lang)
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "catalogue_selling_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0,
            "follow_ups": ["Show all products", "Check inventory summary"]
        }
    elif len(items) > 1:
        candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
        speak_text = f"Multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
        return {
            "speak": speak_text,
            "display": f"Multiple matches for '{target}'",
            "action": "catalogue_selling_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": len(items),
            "candidates": items[:5]
        }
    else:
        p = items[0]
        session_ctx.clear_pending_action()
        session_ctx.update_product(p, language=lang)
        if lang in ("hi", "hinglish"):
            loc = multilingual.format_multilingual_response("selling_price", lang, {"product": p})
            speak_text = loc["speak"]
            display_text = loc["display"]
        else:
            speak_text = f"The selling price of {p['name']} is {p['selling_price']} {p['currency']}. Purchase cost is {p['purchase_price']} {p['currency']}."
            display_text = f"{p['name']}: Selling Price = ₹{p['selling_price']:,.2f} | Cost = ₹{p['purchase_price']:,.2f}"
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "catalogue_selling_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 1,
            "product": p,
            "follow_ups": [f"What is the stock of {p['name']}?"]
        }


def _build_market_price_clarification_response(target: Optional[str], cat_conn: Any, lang: str = "en", db_path: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    target = (target or "").rstrip('?.').strip()
    session_ctx = multilingual.get_session_context(session_id)
    if target in ("context_product", "is product", "iss product", "this product", "product") and session_ctx.last_product:
        target = session_ctx.last_product.get("name", "")

    # Check if target is a stopword or missing
    if not target or multilingual.is_product_stopword(target):
        if lang == "hi":
            msg = "VANTIQ आंतरिक कैटलॉग विक्रय मूल्य (selling price) और खरीद लागत (purchase cost) रिकॉर्ड करता है, लेकिन लाइव मार्केट फीड के बिना बाहरी खुले बाजार की कीमतों का सत्यापन नहीं किया जा सकता। आप किस प्रोडक्ट की आंतरिक कीमतें जांचना चाहते हैं?"
        elif lang == "hinglish":
            msg = "SARTHI internal catalogue selling price aur procurement cost record karta hai, lekin external open-market price live market feed ke bina verify nahi ki ja sakti. Aap kis product ki internal pricing check karna chahte hain?"
        else:
            msg = "SARTHI tracks internal catalogue selling prices and recorded purchase costs, but external open-market prices cannot currently be verified without live market feeds. Which product's internal pricing would you like to review?"
        return {
            "speak": msg,
            "display": msg,
            "action": "market_price_clarification",
            "source": "Catalogue & Market Diagnostics",
            "source_type": "pricing",
            "external_market_verified": False,
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    # Query DB for product
    res = database.list_products(search=target, is_active=True, conn=cat_conn, db_path=db_path)
    items = res.get("items", [])
    if items:
        p = items[0]
        session_ctx.update_product(p, language=lang)
        p_name = p.get("name", target)
        sp = p.get("selling_price", 0.0)
        pc = p.get("purchase_price", 0.0)
        curr = p.get("currency", "INR")
        curr_sym = "₹" if curr in ("INR", "₹") else f"{curr} "

        if lang == "hi":
            msg = f"VANTIQ में '{p_name}' की आंतरिक विक्रय मूल्य {curr_sym}{sp:,.2f} और पिछली खरीद लागत {curr_sym}{pc:,.2f} दर्ज है। बाहरी खुले बाजार की कीमत का वर्तमान में सत्यापन नहीं किया जा सकता क्योंकि बाहरी मार्केट रिसर्च उपलब्ध नहीं है। क्या आप आंतरिक कैटलॉग मूल्य जानना चाहते थे?"
        elif lang == "hinglish":
            msg = f"SARTHI mein '{p_name}' ki internal selling price {curr_sym}{sp:,.2f} aur recorded purchase cost {curr_sym}{pc:,.2f} hai. External open-market price live feeds ke bina verify nahi ho sakti. Kya aap internal catalogue price dekhna chahte hain?"
        else:
            msg = f"In SARTHI, '{p_name}' has an internal selling price of {curr_sym}{sp:,.2f} and a recorded purchase cost of {curr_sym}{pc:,.2f}. External open-market pricing cannot currently be verified without live market feeds. Did you mean our internal catalogue price or external market valuation?"

        return {
            "speak": msg,
            "display": f"{p_name}: Internal Selling = {curr_sym}{sp:,.2f} | Purchase Cost = {curr_sym}{pc:,.2f} (External market price unverified)",
            "action": "market_price_clarification",
            "source": "Catalogue & Market Diagnostics",
            "source_type": "pricing",
            "product": p,
            "internal_selling_price": sp,
            "internal_purchase_price": pc,
            "external_market_verified": False,
            "follow_ups": [f"What is the stock of {p_name}?", f"What was the last purchase rate of {p_name}?"]
        }
    else:
        if lang == "hi":
            msg = f"'{target}' कैटलॉग में नहीं मिला। VANTIQ आंतरिक कैटलॉग कीमतें दर्ज करता है, लेकिन बाहरी खुले बाजार की कीमतों का सत्यापन नहीं कर सकता।"
        elif lang == "hinglish":
            msg = f"'{target}' catalogue mein nahi mila. SARTHI internal catalogue prices track karta hai, external market prices verify nahi kar sakta."
        else:
            msg = f"Product '{target}' was not found in the catalogue. SARTHI tracks internal catalogue prices and costs, but external market prices cannot currently be verified."
        return {
            "speak": msg,
            "display": msg,
            "action": "market_price_clarification",
            "source": "Catalogue & Market Diagnostics",
            "source_type": "pricing",
            "external_market_verified": False,
            "follow_ups": ["Show all products", "Check inventory summary"]
        }


def _build_product_margin_response(
    target: str,
    cat_conn: Any,
    source_label: str = "Profitability Analysis",
    lang: str = "en",
    db_path: Optional[str] = None,
    intent_type: str = "margin",
    cost_basis: str = "purchase_price",
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    target = (target or "").rstrip('?.!').strip()
    target = re.sub(r'^(?:is|iss|is product|iss product|this product|the product|the|a|an)\s+', '', target, flags=re.IGNORECASE).strip()
    session_ctx = multilingual.get_session_context(session_id)

    if target in ("context_product", "is product", "iss product", "this product", "product", "item") and session_ctx.last_product:
        target = session_ctx.last_product["name"]

    if not target or multilingual.is_product_stopword(target):
        if lang in ("hi", "hinglish"):
            msg = "Aap kis product ka profit ya margin dekhna chahte hain? Kripya product ka naam bataiye."
        else:
            msg = "Which product would you like me to check the profit and margin for? Please specify the product name or SKU."
        return {
            "speak": msg,
            "display": msg,
            "action": "clarification_needed",
            "source": source_label,
            "source_type": "catalogue",
            "clarification_type": "missing_product",
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    # 1. First attempt exact SKU or name match via find_product_by_identifier (deterministic, avoids fuzzy confusion)
    p = database.find_product_by_identifier(target, conn=cat_conn, db_path=db_path)
    if not p:
        res = database.list_products(search=target, is_active=True, conn=cat_conn, db_path=db_path)
        items = res.get("items", [])
        if len(items) == 1:
            p = items[0]
        elif len(items) > 1:
            candidates = ", ".join([f"{item['name']} (SKU: {item['sku'] or 'N/A'})" for item in items[:3]])
            speak_text = f"Multiple products match '{target}': {candidates}. Please clarify which product you require."
            return {
                "speak": speak_text,
                "display": f"Multiple matches for '{target}'",
                "action": "product_margin",
                "status": "multiple_matches",
                "source": source_label,
                "source_type": "catalogue",
                "match_count": len(items),
                "candidates": items[:5],
                "candidate_products": items[:5],
                "follow_ups": [f"What is the profit of {item['name']}?" for item in items[:3]]
            }
        else:
            p = None

    if not p:
        if lang in ("hi", "hinglish"):
            loc = multilingual.format_multilingual_response("product_not_found", lang, {"query": target})
            speak_text = loc["speak"]
            display_text = loc["display"]
        else:
            speak_text = f"Product '{target}' was not found in the catalogue. Would you like to view all active products?"
            display_text = f"Profit/Margin: No match for '{target}'"
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "product_not_found",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0,
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    session_ctx.update_product(p, language=lang)

    # Enrich product record with latest procurement purchase rate and date if needed
    p_summary = database.get_product_pricing_summary(p["id"], conn=cat_conn, db_path=db_path)
    if p_summary:
        if p.get("last_purchase_rate") is None and p_summary.get("last_purchase_rate") is not None:
            p["last_purchase_rate"] = p_summary["last_purchase_rate"]
        if p.get("last_purchase_date") is None and p_summary.get("last_purchase_date") is not None:
            p["last_purchase_date"] = p_summary["last_purchase_date"]

    # Execute deterministic mathematical calculation via business_insights calculation service
    calc = business_insights.calculate_product_profit_and_margin(p, cost_basis=cost_basis)
    curr = p.get("currency") or "INR"
    curr_sym = "₹" if curr in ("INR", "₹") else f"{curr} "

    # Handle incomplete or edge-case pricing scenarios safely
    if calc.get("status") == "missing_selling_price":
        cost_val = calc.get("cost_value")
        cost_str = f"{curr_sym}{cost_val:,.2f}" if cost_val is not None else "Not Configured"
        if lang in ("hi", "hinglish"):
            speak_text = f"{p['name']} ka selling price catalogue mein configured nahi hai (Purchase cost: {cost_str}). Selling price set hone ke baad hi profit aur margin calculate kiya ja sakta hai."
            display_text = f"{p['name']}: Selling Price Not Configured | Cost = {cost_str}"
        else:
            speak_text = f"Selling price is not configured for {p['name']} (recorded purchase cost: {cost_str}). Gross profit and margin cannot be calculated until a selling price is set."
            display_text = f"{p['name']}: Selling Price Not Configured | Cost = {cost_str}"
    elif calc.get("status") == "missing_cost_basis":
        sp_val = calc.get("selling_price", 0.0)
        sp_str = f"{curr_sym}{sp_val:,.2f}" if sp_val is not None else "Not Configured"
        if cost_basis == "last_purchase_rate":
            base_cp = p.get("purchase_price")
            base_str = f" (Standard catalog purchase price is {curr_sym}{base_cp:,.2f})" if base_cp is not None else ""
            if lang in ("hi", "hinglish"):
                speak_text = f"{p['name']} ke liye koi purchase transaction recorded nahi hai{base_str}. Latest purchase rate ke aadhar par profit calculate nahi kiya ja sakta."
                display_text = f"{p['name']}: No Last Purchase Rate Recorded | Selling = {sp_str}"
            else:
                speak_text = f"No procurement purchase transactions have been recorded yet for {p['name']}{base_str}. Profit based on latest purchase rate cannot be calculated."
                display_text = f"{p['name']}: No Last Purchase Rate Recorded | Selling = {sp_str}"
        else:
            if lang in ("hi", "hinglish"):
                speak_text = f"{p['name']} ka purchase price catalogue mein configured nahi hai (Selling price: {sp_str}). Profit aur margin calculate nahi kiya ja sakta."
                display_text = f"{p['name']}: Purchase Price Not Configured | Selling = {sp_str}"
            else:
                speak_text = f"Purchase price is not configured for {p['name']} (selling price: {sp_str}). Profit and margin cannot be calculated."
                display_text = f"{p['name']}: Purchase Price Not Configured | Selling = {sp_str}"
    elif calc.get("status") == "zero_selling_price":
        cp_val = calc.get("cost_value", 0.0)
        profit = calc.get("gross_profit_per_unit", 0.0)
        if lang in ("hi", "hinglish"):
            speak_text = f"{p['name']} ka recorded selling price {curr_sym}0.00 hai aur purchase cost {curr_sym}{cp_val:,.2f} hai. Unit gross profit {curr_sym}{profit:,.2f} (0.0% margin) hai."
            display_text = f"{p['name']}: Selling = {curr_sym}0.00 | Cost = {curr_sym}{cp_val:,.2f} | Profit = {curr_sym}{profit:,.2f} (0.0% margin)"
        else:
            speak_text = f"{p['name']} has a recorded selling price of {curr_sym}0.00 and purchase cost of {curr_sym}{cp_val:,.2f}. Unit gross profit is {curr_sym}{profit:,.2f} with 0.0% margin."
            display_text = f"{p['name']}: Selling = {curr_sym}0.00 | Cost = {curr_sym}{cp_val:,.2f} | Profit = {curr_sym}{profit:,.2f} (0.0% margin)"
    else:
        sp = calc["selling_price"]
        cp = calc["cost_value"]
        profit = calc["gross_profit_per_unit"]
        margin_pct = calc["gross_margin_pct"]
        basis_note = f" (based on latest purchase rate on {calc.get('cost_date')})" if cost_basis == "last_purchase_rate" and calc.get('cost_date') else (" (based on latest purchase rate)" if cost_basis == "last_purchase_rate" else "")

        loc = multilingual.format_multilingual_response(
            "product_profit" if intent_type == "profit" else "product_margin",
            lang,
            {
                "name": p["name"],
                "profit": profit,
                "margin_pct": margin_pct,
                "selling_price": sp,
                "purchase_price": cp,
                "cost_basis_note": basis_note
            }
        )
        speak_text = loc["speak"]
        display_text = loc["display"]

    action_type = "product_profit" if intent_type == "profit" else "product_margin"
    return {
        "speak": speak_text,
        "display": display_text,
        "action": action_type,
        "status": calc.get("status", "success"),
        "source": source_label,
        "source_type": "catalogue",
        "match_count": 1,
        "product": p,
        "product_name": p["name"],
        "profit_per_unit": calc.get("gross_profit_per_unit"),
        "gross_margin_pct": calc.get("gross_margin_pct"),
        "metrics": {
            "selling_price": calc.get("selling_price") if calc.get("selling_price") is not None else p.get("selling_price"),
            "purchase_price": calc.get("cost_value") if calc.get("cost_value") is not None else p.get("purchase_price"),
            "gross_profit": calc.get("gross_profit_per_unit"),
            "gross_margin_pct": calc.get("gross_margin_pct"),
            "markup_pct": calc.get("markup_pct"),
            "cost_basis": cost_basis
        },
        "calculation_details": calc,
        "follow_ups": [f"What is the stock of {p['name']}?", "Show all products", "Check overall margin"]
    }


def _build_catalogue_margin_response(cat_conn: Any, context: Optional[Dict[str, Any]] = None, db_path: Optional[str] = None, source_label: str = "Profitability Analysis", lang: str = "en") -> Dict[str, Any]:
    prods = database.list_products(is_active=True, page_size=1000, conn=cat_conn).get("items", [])
    priced = []
    for p in prods:
        sp = float(p.get("selling_price") or 0.0)
        cp = float(p.get("purchase_price") or 0.0)
        if sp > 0 and cp > 0:
            profit = sp - cp
            m_pct = (profit / sp) * 100.0
            priced.append({
                "name": p.get("name"),
                "sku": p.get("sku") or "--",
                "selling_price": sp,
                "purchase_price": cp,
                "profit": profit,
                "margin_pct": round(m_pct, 2)
            })

    if not priced:
        bi_rep = (context or {}).get("current_bi_report")
        if bi_rep and bi_rep.get("pricing", {}).get("computed"):
            pricing = bi_rep["pricing"]
            avg_m = pricing.get("average_gross_margin_pct", 0)
            top_p = pricing.get("highest_margin_products", [])
            leader = top_p[0] if top_p else {"product": "N/A", "gross_margin_pct": 0}
            loc = multilingual.format_multilingual_response("catalogue_margin", lang, {
                "average_margin_pct": avg_m,
                "highest_margin_product": leader.get("product"),
                "highest_margin_pct": leader.get("gross_margin_pct", 0)
            })
            return {
                "speak": loc["speak"],
                "display": loc["display"],
                "action": "catalogue_margin",
                "source": "BI Commercial Intelligence",
                "source_type": "report",
                "average_margin_pct": avg_m,
                "leader": leader
            }

        speak_text = "No products with valid purchase and selling prices were found to compute margins."
        return {
            "speak": speak_text,
            "display": "Margin data unavailable (0 priced products)",
            "action": "catalogue_margin",
            "source": source_label,
            "source_type": "catalogue"
        }

    priced.sort(key=lambda x: x["margin_pct"], reverse=True)
    avg_m = round(sum(p["margin_pct"] for p in priced) / len(priced), 2)
    top_p = priced[0]
    low_p = priced[-1]

    loc = multilingual.format_multilingual_response("catalogue_margin", lang, {
        "average_margin_pct": avg_m,
        "highest_margin_product": top_p["name"],
        "highest_margin_pct": top_p["margin_pct"],
        "lowest_margin_product": low_p["name"],
        "lowest_margin_pct": low_p["margin_pct"]
    })

    rows = [{
        "name": p["name"],
        "cost": f"₹{p['purchase_price']:,.2f}",
        "sell": f"₹{p['selling_price']:,.2f}",
        "profit": f"₹{p['profit']:,.2f}",
        "margin": f"{p['margin_pct']}%"
    } for p in priced]

    return {
        "speak": loc["speak"],
        "display": loc["display"],
        "action": "catalogue_margin",
        "source": source_label,
        "source_type": "catalogue",
        "average_margin_pct": avg_m,
        "highest_margin": top_p,
        "lowest_margin": low_p,
        "table": {"columns": ["PRODUCT", "COST", "SELLING", "PROFIT", "MARGIN %"], "rows": rows},
        "follow_ups": [f"What is the margin of {top_p['name']}?", "Show all products"]
    }


def _build_stock_response(target: str, cat_conn: Any, source_label: str = "Inventory Balance", lang: str = "en", db_path: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    target = (target or "").rstrip('?.').strip()
    session_ctx = multilingual.get_session_context(session_id)
    # Check contextual resolution if target is generic
    if target in ("context_product", "is product", "iss product", "this product", "product") and session_ctx.last_product:
        target = session_ctx.last_product["name"]

    res = database.list_products(search=target, is_active=True, conn=cat_conn, db_path=db_path)
    items = res["items"]

    if not items:
        if lang in ("hi", "hinglish"):
            loc = multilingual.format_multilingual_response("product_not_found", lang, {"name": target, "query": target})
            speak_text = loc["speak"]
            display_text = loc["display"]
        else:
            speak_text = f"Product '{target}' was not found in the catalogue. Would you like to view all active products?"
            display_text = f"Stock: No match for '{target}'"
        session_ctx.set_pending_action(action="product_list", prompt=speak_text, language=lang)
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "catalogue_stock",
            "source": "Product Catalogue",
            "source_type": "catalogue",
            "match_count": 0,
            "follow_ups": ["Show all products", "Check inventory summary"]
        }
    elif len(items) > 1:
        candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
        speak_text = f"Multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
        return {
            "speak": speak_text,
            "display": f"Multiple Matches ({len(items)}): {candidates}",
            "action": "catalogue_stock",
            "source": "Product Catalogue",
            "source_type": "catalogue",
            "match_count": len(items),
            "candidates": items[:5],
            "follow_ups": [f"What is the stock of {p['name']}?" for p in items[:3]]
        }
    else:
        p = items[0]
        session_ctx.clear_pending_action()
        multilingual.SESSION_CONTEXT.update_product(p, language=lang)
        if lang in ("hi", "hinglish"):
            loc = multilingual.format_multilingual_response("product_stock", lang, {
                "name": p["name"],
                "quantity": p.get("quantity_on_hand", 0),
                "unit": p.get("unit", "units"),
                "reorder_level": p.get("reorder_level", 0)
            })
            speak_text = loc["speak"]
            display_text = loc["display"]
        else:
            speak_text = f"Current stock of {p['name']} is {p['quantity_on_hand']} {p['unit']}. Reorder threshold is {p['reorder_level']} {p['unit']}."
            display_text = f"{p['name']}: {p['quantity_on_hand']} {p['unit']} in stock (Reorder: {p['reorder_level']})"
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "catalogue_stock",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 1,
            "product": p,
            "follow_ups": [f"What is the selling price of {p['name']}?", "Show all products"]
        }


def _build_no_price_response(cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    all_prods = database.list_products(is_active=True, page_size=100, conn=cat_conn)["items"]
    missing_price = [p for p in all_prods if (p.get("selling_price") is None or p.get("selling_price") <= 0)]
    if not missing_price:
        speak_text = "All active products in the catalogue have valid selling prices configured."
        rows = []
    else:
        names = ", ".join([p["name"] for p in missing_price[:3]])
        speak_text = f"There are {len(missing_price)} product(s) without a selling price, including {names}."
        rows = [{"sku": p.get("sku") or "--", "name": p.get("name"), "cost": p.get("purchase_price", 0)} for p in missing_price]

    return {
        "speak": speak_text,
        "display": f"Unpriced Products: {len(missing_price)} items",
        "action": "catalogue_no_price",
        "source": source_label,
        "source_type": "catalogue",
        "total_count": len(missing_price),
        "table": {"columns": ["SKU", "NAME", "PURCHASE COST"], "rows": rows},
        "follow_ups": ["What are all products?", "Show products below reorder level"]
    }


def _build_find_product_response(target: str, cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    target = target.rstrip('?.')
    res = database.list_products(search=target, is_active=True, conn=cat_conn)
    items = res["items"]

    if not items:
        speak_text = f"No product matching '{target}' was found in the saved catalogue."
        return {
            "speak": speak_text,
            "display": f"No product found for query: '{target}'",
            "action": "catalogue_find",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }
    elif len(items) > 1:
        candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
        speak_text = f"I found {len(items)} matching products: {candidates}. Please clarify which product you require."
        return {
            "speak": speak_text,
            "display": f"Multiple matches for '{target}': {len(items)} products",
            "action": "catalogue_find",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": len(items),
            "candidates": items[:5]
        }
    else:
        p = items[0]
        speak_text = f"Product {p['name']} (SKU: {p['sku'] or 'N/A'}) has {p['quantity_on_hand']} {p['unit']} in stock, priced at {p['selling_price']} {p['currency']}."
        return {
            "speak": speak_text,
            "display": f"Found: {p['name']} | Stock: {p['quantity_on_hand']} {p['unit']} | Price: ₹{p['selling_price']:,.2f}",
            "action": "catalogue_find",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 1,
            "product": p,
            "follow_ups": [f"What is the selling price of {p['name']}?", "Show all products"]
        }


def _build_purchase_cost_response(target: str, cat_conn: Any, source_label: str = "Product Catalogue") -> Dict[str, Any]:
    target = target.rstrip('?.')
    res = database.list_products(search=target, is_active=True, conn=cat_conn)
    items = res["items"]

    if not items:
        speak_text = f"No product matching '{target}' was found in the catalogue."
        return {
            "speak": speak_text,
            "display": f"Cost: No match for '{target}'",
            "action": "catalogue_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }
    elif len(items) > 1:
        candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
        speak_text = f"Multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
        return {
            "speak": speak_text,
            "display": f"Multiple matches for '{target}'",
            "action": "catalogue_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": len(items),
            "candidates": items[:5]
        }
    else:
        p = items[0]
        speak_text = f"The purchase price of {p['name']} is {p['purchase_price']} {p['currency']}. Current selling price is {p['selling_price']} {p['currency']}."
        return {
            "speak": speak_text,
            "display": f"{p['name']}: Cost = ₹{p['purchase_price']:,.2f} | Selling = ₹{p['selling_price']:,.2f}",
            "action": "catalogue_price",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 1,
            "product": p
        }


def _build_supplier_response(target: Optional[str] = None, cat_conn: Any = None, source_label: str = "Supplier Ledger", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    target = (target or "").rstrip('?.').strip()
    if not target or target.lower() in ("all", "suppliers", "general", "none"):
        suppliers = database.list_suppliers(is_active=True, conn=cat_conn, db_path=db_path)
        loc = multilingual.format_multilingual_response("supplier_lookup", lang, {"mode": "list", "suppliers": suppliers})
        rows = [{
            "name": s.get("name"),
            "contact": s.get("contact_name") or "--",
            "phone": s.get("phone") or "--",
            "email": s.get("email") or "--"
        } for s in suppliers]
        return {
            "speak": loc["speak"],
            "display": loc["display"],
            "action": "supplier_list",
            "source": source_label,
            "source_type": "supplier",
            "suppliers": suppliers,
            "match_count": len(suppliers),
            "table": {"columns": ["SUPPLIER NAME", "CONTACT", "PHONE", "EMAIL"], "rows": rows},
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    # Specific product supplier lookup
    if target in ("context_product", "is product", "iss product", "this product", "product") and multilingual.SESSION_CONTEXT.last_product:
        target = multilingual.SESSION_CONTEXT.last_product["name"]

    supp_info = database.get_supplier_for_product(target, conn=cat_conn, db_path=db_path)
    if not supp_info:
        if lang in ("hi", "hinglish"):
            loc = multilingual.format_multilingual_response("product_not_found", lang, {"query": target})
            speak_text = loc["speak"]
            display_text = loc["display"]
        else:
            speak_text = f"No product matching '{target}' was found in the catalogue."
            display_text = f"Supplier: No match for '{target}'"
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "supplier_lookup",
            "source": source_label,
            "source_type": "supplier",
            "match_count": 0
        }

    prod_name = supp_info.get("product_name", target)
    supp_name = supp_info.get("supplier_name")
    loc = multilingual.format_multilingual_response("supplier_lookup", lang, {
        "mode": "single",
        "product_name": prod_name,
        "supplier_name": supp_name,
        "contact_name": supp_info.get("contact_name"),
        "phone": supp_info.get("phone")
    })

    return {
        "speak": loc["speak"],
        "display": loc["display"],
        "action": "supplier_lookup",
        "source": source_label,
        "source_type": "supplier",
        "product_name": prod_name,
        "supplier": supp_info if supp_name else None,
        "follow_ups": [f"What is the stock of {prod_name}?", f"What is the selling price of {prod_name}?"]
    }


def _handle_bi_inventory(context: Dict[str, Any], db_path: Optional[str]) -> Dict[str, Any]:
    bi_rep = context.get("current_bi_report")
    if not bi_rep:
        ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
        latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
        if latest_ds:
            rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
            if rep_record:
                bi_rep = rep_record.get("report_content")

    if not bi_rep:
        msg = "No dataset loaded. Please upload product inventory data first."
        return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

    inv = bi_rep.get("inventory", {})
    if not inv.get("computed"):
        missing = ", ".join(inv.get("missing_fields", ["Quantity / Stock"]))
        speak_text = f"Inventory metrics cannot be computed. The required fields ({missing}) are missing from this dataset."
        return {"speak": speak_text, "display": speak_text, "action": "bi_inventory_unavailable", "source": "BI Inventory", "source_type": "report"}

    low_items = inv.get("low_stock_items", [])
    total_units = inv.get("total_units", 0)
    speak_text = f"Recorded inventory total is {total_units} units. {len(low_items)} items are flagged for low stock or reorder."
    return {
        "speak": speak_text,
        "display": f"Inventory: {total_units} units | {len(low_items)} low-stock alerts",
        "action": "bi_inventory",
        "source": "Inventory Analytics",
        "source_type": "report",
        "inventory": inv,
        "low_stock_items": low_items,
        "follow_ups": ["Show all products", "Which products are low in stock?"]
    }


def parse_time_range(text: str) -> Dict[str, Any]:
    t = text.lower()
    today = datetime.date.today()
    if any(k in t for k in ["last month", "previous month", "pichle mahine", "pichla mahina", "पिछले महीने"]):
        first_of_this_month = today.replace(day=1)
        last_day_of_last_month = first_of_this_month - datetime.timedelta(days=1)
        start_date = last_day_of_last_month.replace(day=1).isoformat()
        end_date = last_day_of_last_month.isoformat()
        return {"start_date": start_date, "end_date": end_date, "time_label": "last month"}
    elif any(k in t for k in ["this month", "current month", "is mahine", "is mahina", "इस महीने"]):
        start_date = today.replace(day=1).isoformat()
        end_date = today.isoformat()
        return {"start_date": start_date, "end_date": end_date, "time_label": "this month"}
    elif any(k in t for k in ["today", "aaj", "आज"]):
        return {"start_date": today.isoformat(), "end_date": today.isoformat(), "time_label": "today"}
    elif any(k in t for k in ["this year", "current year", "is saal"]):
        start_date = today.replace(month=1, day=1).isoformat()
        end_date = today.isoformat()
        return {"start_date": start_date, "end_date": end_date, "time_label": "this year"}
    return {"start_date": None, "end_date": None, "time_label": "recent"}


def _build_product_details_response(target: str, cat_conn: Any, source_label: str = "Product Catalogue", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    target = target.rstrip('?.').strip()
    if target.lower().startswith("product "):
        target = target[8:].strip()
    elif target.lower().startswith("item "):
        target = target[5:].strip()

    if target in ("context_product", "is product", "iss product", "this product", "product", "is item", "item") and multilingual.SESSION_CONTEXT.last_product:
        target = multilingual.SESSION_CONTEXT.last_product.get("name") or multilingual.SESSION_CONTEXT.last_product.get("sku")

    p = database.find_product_by_identifier(target, conn=cat_conn, db_path=db_path)
    if not p:
        res = database.list_products(search=target, is_active=True, conn=cat_conn, db_path=db_path)
        items = res.get("items", [])
        if len(items) == 1:
            p = items[0]
        elif len(items) > 1:
            candidates = ", ".join([f"{item['name']} (SKU: {item['sku'] or 'N/A'})" for item in items[:3]])
            return {
                "speak": f"Multiple products match '{target}': {candidates}. Please specify the exact SKU or name.",
                "display": f"Multiple matches for '{target}' ({len(items)} found)",
                "action": "product_clarify",
                "source": source_label,
                "source_type": "catalogue",
                "match_count": len(items),
                "candidates": items[:5]
            }

    if not p:
        if lang == "hi":
            speak_text = f"प्रोडक्ट '{target}' कैटलॉग में नहीं मिला।"
            display_text = f"प्रोडक्ट नहीं मिला: '{target}'"
        elif lang == "hinglish":
            speak_text = f"Product '{target}' catalogue mein nahi mila. Kripya SKU ya sahi naam check karein."
            display_text = f"Product Not Found: '{target}'"
        else:
            speak_text = f"Product '{target}' was not found in the catalogue. Please check the SKU or product name."
            display_text = f"Product Not Found: '{target}'"
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "product_details",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }

    multilingual.SESSION_CONTEXT.update_product(p, language=lang)
    p_id = p["id"]
    inv = database.get_inventory_balance(p_id, conn=cat_conn, db_path=db_path)
    qty = inv["quantity_on_hand"] if inv else 0.0
    reorder = inv["reorder_level"] if inv else (p.get("reorder_level") or 0.0)
    unit = p.get("unit") or "units"
    sp = float(p.get("selling_price") or 0.0)
    cp = float(p.get("purchase_price") or 0.0)
    last_rate = float(p.get("last_purchase_rate")) if p.get("last_purchase_rate") is not None else None
    last_date = p.get("last_purchase_date")
    supplier = database.get_supplier_for_product(p.get("sku") or p["name"], conn=cat_conn, db_path=db_path)
    supp_name = (supplier.get("supplier_name") or supplier.get("name")) if supplier else "Unassigned"

    margins = database.calculate_margins(cp, sp)
    gp = margins.get("gross_profit")
    gm_pct = margins.get("gross_margin_pct")

    if lang == "hi":
        speak_text = f"{p['name']} (SKU: {p.get('sku') or 'N/A'}): स्टॉक {qty:g} {unit}, सेलिंग प्राइस ₹{sp:,.2f}, सप्लायर: {supp_name}।"
    elif lang == "hinglish":
        speak_text = f"{p['name']} (SKU: {p.get('sku') or 'N/A'}) ka stock {qty:g} {unit} hai, selling price ₹{sp:,.2f} hai, aur supplier {supp_name} hai."
    else:
        speak_text = f"{p['name']} (SKU: {p.get('sku') or 'N/A'}): Current stock {qty:g} {unit}, selling price ₹{sp:,.2f}, supplier {supp_name}."

    display_text = f"{p['name']} | Stock: {qty:g} {unit} | Price: ₹{sp:,.2f} | Supplier: {supp_name}"

    table_rows = [
        {"property": "Product Name", "value": p["name"]},
        {"property": "SKU", "value": p.get("sku") or "--"},
        {"property": "Category", "value": p.get("category") or "General"},
        {"property": "Current Stock", "value": f"{qty:g} {unit}"},
        {"property": "Reorder Level", "value": f"{reorder:g} {unit}"},
        {"property": "Selling Price", "value": f"₹{sp:,.2f}"},
        {"property": "Standard Cost", "value": f"₹{cp:,.2f}"},
        {"property": "Last Purchase Rate", "value": f"₹{last_rate:,.2f} ({last_date})" if last_rate else "No purchases recorded"},
        {"property": "Gross Margin", "value": f"{gm_pct}% (Profit: ₹{gp:,.2f})" if gm_pct is not None else "N/A"},
        {"property": "Supplier", "value": supp_name}
    ]

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "product_details",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": 1,
        "product": p,
        "table": {"columns": ["PROPERTY", "VALUE"], "rows": table_rows},
        "follow_ups": [f"What is the stock of {p['name']}?", f"What was the last purchase rate for {p['name']}?"]
    }


def _build_purchase_rate_history_response(target: Optional[str], cat_conn: Any, source_label: str = "Procurement Ledger", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    if (not target or target in ("this product", "is product", "iss product", "product", "item", "context_product")) and multilingual.SESSION_CONTEXT.last_product:
        target = multilingual.SESSION_CONTEXT.last_product.get("name") or multilingual.SESSION_CONTEXT.last_product.get("sku")

    if not target or target.strip().lower() in ("all", "products", "none", "general"):
        purchases_res = database.list_purchases(page=1, page_size=10, conn=cat_conn, db_path=db_path)
        items = purchases_res.get("items", [])
        if not items:
            return {
                "speak": "No purchase transactions have been recorded yet in the procurement ledger.",
                "display": "Purchase History: 0 records",
                "action": "purchase_rate_history",
                "source": source_label,
                "source_type": "catalogue",
                "match_count": 0
            }
        rows = [{
            "date": pu.get("purchase_date") or "--",
            "product": pu.get("product_name"),
            "rate": f"₹{pu.get('unit_price', 0):,.2f}",
            "qty": f"{pu.get('quantity', 0)}",
            "supplier": pu.get("supplier_name") or "--"
        } for pu in items]
        speak_text = f"Here are the latest recorded procurement purchase rates for {len(items)} transactions."
        return {
            "speak": speak_text,
            "display": f"Latest Purchase Rates ({len(items)} records)",
            "action": "purchase_rate_history",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": len(items),
            "table": {"columns": ["DATE", "PRODUCT", "UNIT RATE", "QUANTITY", "SUPPLIER"], "rows": rows}
        }

    target = target.rstrip('?.').strip()
    p = database.find_product_by_identifier(target, conn=cat_conn, db_path=db_path)
    if not p:
        res = database.list_products(search=target, is_active=True, conn=cat_conn, db_path=db_path)
        items = res.get("items", [])
        if len(items) == 1:
            p = items[0]
        elif len(items) > 1:
            candidates = ", ".join([f"{item['name']} (SKU: {item['sku'] or 'N/A'})" for item in items[:3]])
            return {
                "speak": f"Multiple products match '{target}': {candidates}. Please specify which one you mean.",
                "display": f"Multiple matches for '{target}'",
                "action": "clarify_query",
                "source": source_label,
                "source_type": "catalogue",
                "match_count": len(items)
            }

    if not p:
        if lang == "hi":
            speak_text = f"प्रोडक्ट '{target}' कैटलॉग में नहीं मिला।"
        elif lang == "hinglish":
            speak_text = f"Product '{target}' catalogue mein nahi mila."
        else:
            speak_text = f"No product matching '{target}' was found in the catalogue."
        return {
            "speak": speak_text,
            "display": f"Purchase Rate: No match for '{target}'",
            "action": "purchase_rate_history",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }

    multilingual.SESSION_CONTEXT.update_product(p, language=lang)
    p_id = p["id"]
    pricing = database.get_product_pricing_summary(p_id, conn=cat_conn, db_path=db_path)
    last_rate = pricing.get("last_purchase_rate") if pricing else p.get("last_purchase_rate")
    last_date = pricing.get("last_purchase_date") if pricing else p.get("last_purchase_date")
    base_cost = p.get("purchase_price") or 0.0

    if last_rate is not None and last_rate > 0:
        date_str = f" on {last_date}" if last_date else ""
        if lang == "hi":
            speak_text = f"{p['name']} का अंतिम खरीद भाव (Last Purchase Rate) ₹{last_rate:,.2f} था{date_str}। बेस कैटलॉग कॉस्ट ₹{base_cost:,.2f} है।"
            display_text = f"{p['name']}: Last Purchase Rate = ₹{last_rate:,.2f}{date_str} | Base Cost = ₹{base_cost:,.2f}"
        elif lang == "hinglish":
            speak_text = f"{p['name']} ka last purchase rate ₹{last_rate:,.2f} tha{date_str}. Baseline cost ₹{base_cost:,.2f} hai."
            display_text = f"{p['name']}: Last Rate = ₹{last_rate:,.2f}{date_str} | Base Cost = ₹{base_cost:,.2f}"
        else:
            speak_text = f"The last recorded purchase rate for {p['name']} was ₹{last_rate:,.2f}{date_str}. Standard catalog purchase cost is ₹{base_cost:,.2f}."
            display_text = f"{p['name']}: Last Purchase Rate = ₹{last_rate:,.2f}{date_str} | Catalog Cost = ₹{base_cost:,.2f}"
    else:
        if lang == "hi":
            speak_text = f"{p['name']} के लिए कोई खरीद लेनदेन दर्ज नहीं है। बेस कैटलॉग खरीद लागत ₹{base_cost:,.2f} है।"
            display_text = f"{p['name']}: कोई खरीद इतिहास नहीं | बेस कॉस्ट: ₹{base_cost:,.2f}"
        elif lang == "hinglish":
            speak_text = f"{p['name']} ke liye koi purchase record nahi mila. Baseline catalog purchase price ₹{base_cost:,.2f} hai."
            display_text = f"{p['name']}: No Purchase History | Base Cost: ₹{base_cost:,.2f}"
        else:
            speak_text = f"No purchase transactions have been recorded yet for {p['name']}. The baseline catalog purchase price is ₹{base_cost:,.2f}."
            display_text = f"{p['name']}: No Recorded Purchases | Base Cost = ₹{base_cost:,.2f}"

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "purchase_rate_history",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": 1,
        "product": p,
        "last_purchase_rate": last_rate,
        "last_purchase_date": last_date,
        "purchase_price": base_cost
    }


def _build_purchases_list_response(params: Dict[str, Any], cat_conn: Any, source_label: str = "Procurement Ledger", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    product_id = params.get("product_id")
    time_label = params.get("time_label", "all recorded")

    res = database.list_purchases(product_id=product_id, start_date=start_date, end_date=end_date, page=1, page_size=50, conn=cat_conn, db_path=db_path)
    items = res.get("items", [])
    total_val = sum(float(pu.get("total_amount") or 0.0) for pu in items)

    if not items:
        if lang == "hi":
            speak_text = f"{time_label} के लिए कोई खरीद लेनदेन नहीं मिले।"
            display_text = f"खरीद: 0 लेनदेन ({time_label})"
        elif lang == "hinglish":
            speak_text = f"{time_label} ke liye koi purchase record nahi mila."
            display_text = f"Purchases: 0 records ({time_label})"
        else:
            speak_text = f"There are no purchases recorded for {time_label}."
            display_text = f"Purchases: 0 records ({time_label})"
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "purchase_list",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0,
            "total_amount": 0.0,
            "items": []
        }

    rows = [{
        "date": pu.get("purchase_date") or "--",
        "po_number": pu.get("purchase_number") or "--",
        "product": pu.get("product_name"),
        "supplier": pu.get("supplier_name") or "--",
        "quantity": f"{pu.get('quantity', 0)}",
        "unit_rate": f"₹{pu.get('unit_price', 0):,.2f}",
        "total": f"₹{pu.get('total_amount', 0):,.2f}"
    } for pu in items]

    if lang == "hi":
        speak_text = f"{time_label} में कुल {len(items)} खरीद लेनदेन दर्ज हैं, जिनका कुल मूल्य ₹{total_val:,.2f} है।"
        display_text = f"खरीद: {len(items)} लेनदेन | कुल: ₹{total_val:,.2f}"
    elif lang == "hinglish":
        speak_text = f"{time_label} mein total {len(items)} purchases hui hain, jinki total value ₹{total_val:,.2f} hai."
        display_text = f"Purchases ({time_label}): {len(items)} items | Total: ₹{total_val:,.2f}"
    else:
        speak_text = f"Found {len(items)} purchase transactions for {time_label}, totaling ₹{total_val:,.2f}."
        display_text = f"Purchases ({time_label}): {len(items)} items | Total: ₹{total_val:,.2f}"

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "purchase_list",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": len(items),
        "total_amount": total_val,
        "table": {"columns": ["DATE", "PO NUMBER", "PRODUCT", "SUPPLIER", "QTY", "RATE", "TOTAL"], "rows": rows},
        "items": items,
        "follow_ups": ["Show recent sales", "Check inventory summary"]
    }


def _build_sales_list_response(params: Dict[str, Any], cat_conn: Any, source_label: str = "Sales Ledger", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    product_id = params.get("product_id")
    time_label = params.get("time_label", "all recorded")

    res = database.list_sales(product_id=product_id, start_date=start_date, end_date=end_date, page=1, page_size=50, conn=cat_conn, db_path=db_path)
    items = res.get("items", [])
    total_val = sum(float(s.get("total_amount") or 0.0) for s in items)

    if not items:
        if lang == "hi":
            speak_text = f"{time_label} के लिए कोई बिक्री लेनदेन दर्ज नहीं है।"
            display_text = f"बिक्री: 0 लेनदेन ({time_label})"
        elif lang == "hinglish":
            speak_text = f"{time_label} ke liye koi sales record nahi mila."
            display_text = f"Sales: 0 records ({time_label})"
        else:
            speak_text = f"There are no sales transactions recorded for {time_label}."
            display_text = f"Sales: 0 records ({time_label})"
        return {
            "speak": speak_text,
            "display": display_text,
            "action": "sales_list",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0,
            "total_revenue": 0.0,
            "items": []
        }

    rows = [{
        "date": s.get("sale_date") or "--",
        "invoice": s.get("invoice_number") or "--",
        "product": s.get("product_name"),
        "customer": s.get("customer_name") or "--",
        "quantity": f"{s.get('quantity', 0)}",
        "unit_price": f"₹{s.get('unit_price', 0):,.2f}",
        "total": f"₹{s.get('total_amount', 0):,.2f}"
    } for s in items]

    if lang == "hi":
        speak_text = f"{time_label} में कुल {len(items)} बिक्री लेनदेन दर्ज हैं, कुल राजस्व ₹{total_val:,.2f} है।"
        display_text = f"बिक्री: {len(items)} लेनदेन | राजस्व: ₹{total_val:,.2f}"
    elif lang == "hinglish":
        speak_text = f"{time_label} mein total {len(items)} sales transactions hue hain, total revenue ₹{total_val:,.2f} hai."
        display_text = f"Sales ({time_label}): {len(items)} txns | Revenue: ₹{total_val:,.2f}"
    else:
        speak_text = f"Found {len(items)} sales transactions for {time_label}, generating ₹{total_val:,.2f} in revenue."
        display_text = f"Sales ({time_label}): {len(items)} txns | Revenue: ₹{total_val:,.2f}"

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "sales_list",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": len(items),
        "total_revenue": total_val,
        "table": {"columns": ["DATE", "INVOICE", "PRODUCT", "CUSTOMER", "QTY", "PRICE", "TOTAL"], "rows": rows},
        "items": items,
        "follow_ups": ["Compare this month's sales with last month", "Check inventory summary"]
    }


def _build_sales_comparison_response(cat_conn: Any, source_label: str = "Sales Analytics", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    today = datetime.date.today()
    this_month_start = today.replace(day=1).isoformat()
    this_month_end = today.isoformat()

    first_of_this_month = today.replace(day=1)
    last_day_of_last_month = first_of_this_month - datetime.timedelta(days=1)
    last_month_start = last_day_of_last_month.replace(day=1).isoformat()
    last_month_end = last_day_of_last_month.isoformat()

    this_res = database.list_sales(start_date=this_month_start, end_date=this_month_end, page=1, page_size=200, conn=cat_conn, db_path=db_path)
    last_res = database.list_sales(start_date=last_month_start, end_date=last_month_end, page=1, page_size=200, conn=cat_conn, db_path=db_path)

    this_items = this_res.get("items", [])
    last_items = last_res.get("items", [])

    this_rev = sum(float(s.get("total_amount") or 0.0) for s in this_items)
    last_rev = sum(float(s.get("total_amount") or 0.0) for s in last_items)
    this_qty = sum(float(s.get("quantity") or 0.0) for s in this_items)
    last_qty = sum(float(s.get("quantity") or 0.0) for s in last_items)

    diff = this_rev - last_rev
    growth_pct = round((diff / last_rev) * 100.0, 2) if last_rev > 0 else (100.0 if this_rev > 0 else 0.0)

    growth_str = f"+{growth_pct}%" if growth_pct > 0 else f"{growth_pct}%"

    if lang == "hi":
        speak_text = (
            f"इस महीने की कुल बिक्री ₹{this_rev:,.2f} ({this_qty:g} यूनिट्स) है, जबकि पिछले महीने ₹{last_rev:,.2f} ({last_qty:g} यूनिट्स) थी। "
            f"विकास दर {growth_str} है।"
        )
        display_text = f"सेल्स तुलना: इस महीने ₹{this_rev:,.2f} vs पिछला महीना ₹{last_rev:,.2f} ({growth_str})"
    elif lang == "hinglish":
        speak_text = (
            f"Is month ki sales ₹{this_rev:,.2f} ({this_qty:g} units) hai, aur last month ₹{last_rev:,.2f} ({last_qty:g} units) thi. "
            f"Overall growth {growth_str} hai."
        )
        display_text = f"Sales Comparison: This Month ₹{this_rev:,.2f} vs Last Month ₹{last_rev:,.2f} ({growth_str})"
    else:
        speak_text = (
            f"This month's sales are ₹{this_rev:,.2f} across {this_qty:g} units, compared to ₹{last_rev:,.2f} across {last_qty:g} units last month. "
            f"Net growth is {growth_str}."
        )
        display_text = f"Sales Comparison: This Month ₹{this_rev:,.2f} vs Last Month ₹{last_rev:,.2f} ({growth_str})"

    rows = [
        {"metric": "Revenue", "this_month": f"₹{this_rev:,.2f}", "last_month": f"₹{last_rev:,.2f}", "change": growth_str},
        {"metric": "Units Sold", "this_month": f"{this_qty:g}", "last_month": f"{last_qty:g}", "change": f"{this_qty - last_qty:+g}"},
        {"metric": "Transactions", "this_month": f"{len(this_items)}", "last_month": f"{len(last_items)}", "change": f"{len(this_items) - len(last_items):+d}"}
    ]

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "sales_comparison",
        "source": source_label,
        "source_type": "report",
        "this_month_revenue": this_rev,
        "last_month_revenue": last_rev,
        "growth_pct": growth_pct,
        "table": {"columns": ["METRIC", "THIS MONTH", "LAST MONTH", "CHANGE"], "rows": rows},
        "follow_ups": ["Show purchases from last month", "Check inventory summary"]
    }


def _build_inventory_movements_response(target: Optional[str], cat_conn: Any, source_label: str = "Stock Ledger", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    p = None
    if target and target.strip().lower() not in ("all", "stock", "inventory", "movements", "none"):
        p = database.find_product_by_identifier(target.strip(), conn=cat_conn, db_path=db_path)
        if not p:
            res = database.list_products(search=target.strip(), is_active=True, conn=cat_conn, db_path=db_path)
            items = res.get("items", [])
            if len(items) == 1:
                p = items[0]

    p_id = p["id"] if p else None
    res = database.get_inventory_movements(product_id=p_id, limit=30, page=1, conn=cat_conn, db_path=db_path)
    items = res.get("items", [])

    if not items:
        prod_desc = f" for '{p['name']}'" if p else ""
        if lang == "hi":
            speak_text = f"इन्वेंट्री मूवमेंट्स का कोई रिकॉर्ड नहीं मिला{prod_desc}।"
        elif lang == "hinglish":
            speak_text = f"Koi inventory movement record nahi mila{prod_desc}."
        else:
            speak_text = f"No inventory movement records found{prod_desc}."
        return {
            "speak": speak_text,
            "display": f"Inventory Movements: 0 records{prod_desc}",
            "action": "inventory_movements",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0,
            "items": []
        }

    rows = [{
        "date": m.get("created_at", "")[:10] if m.get("created_at") else "--",
        "product": m.get("product_name"),
        "type": m.get("movement_type", "").upper(),
        "delta": f"{m.get('quantity_delta', 0):+g}",
        "before": f"{m.get('quantity_before', 0):g}",
        "after": f"{m.get('quantity_after', 0):g}",
        "reason": m.get("reason") or "--",
        "ref": m.get("reference") or "--"
    } for m in items]

    prod_desc = f" for {p['name']}" if p else ""
    if lang == "hi":
        speak_text = f"{len(items)} इन्वेंट्री मूवमेंट्स दर्ज हैं{prod_desc}।"
    elif lang == "hinglish":
        speak_text = f"{len(items)} inventory movements mile hain{prod_desc}."
    else:
        speak_text = f"Retrieved {len(items)} inventory movement records{prod_desc}."

    return {
        "speak": speak_text,
        "display": f"Inventory Movements{prod_desc}: {len(items)} events",
        "action": "inventory_movements",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": len(items),
        "table": {"columns": ["DATE", "PRODUCT", "TYPE", "DELTA", "BEFORE", "AFTER", "REASON", "REF"], "rows": rows},
        "items": items,
        "follow_ups": ["Which products are low in stock?", "Show all products"]
    }


def _build_margin_rankings_response(ranking: str = "highest", cat_conn: Any = None, source_label: str = "Profitability Analysis", lang: str = "en", db_path: Optional[str] = None) -> Dict[str, Any]:
    res = database.list_products(is_active=True, page=1, page_size=200, conn=cat_conn, db_path=db_path)
    items = res.get("items", [])
    if not items:
        return {
            "speak": "No active products are available in the catalogue to calculate margin rankings.",
            "display": "Margin Rankings: 0 products",
            "action": "margin_rankings",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }

    scored = []
    for p in items:
        cp = float(p.get("purchase_price") or 0.0)
        sp = float(p.get("selling_price") or 0.0)
        m = database.calculate_margins(cp, sp)
        margin_pct = m.get("gross_margin_pct")
        if margin_pct is not None:
            scored.append({
                "product": p,
                "margin_pct": margin_pct,
                "gross_profit": m.get("gross_profit") or 0.0,
                "markup_pct": m.get("markup_pct") or 0.0,
                "purchase_price": cp,
                "selling_price": sp
            })

    if not scored:
        return {
            "speak": "None of the products have valid pricing configured to compute margins.",
            "display": "Margin Rankings: No priced products",
            "action": "margin_rankings",
            "source": source_label,
            "source_type": "catalogue",
            "match_count": 0
        }

    reverse_sort = (ranking == "highest")
    scored.sort(key=lambda x: x["margin_pct"], reverse=reverse_sort)
    top_items = scored[:5]

    top_names = [f"{s['product']['name']} ({s['margin_pct']}%)" for s in top_items[:3]]
    rank_word = "highest" if ranking == "highest" else "lowest"
    rank_word_hi = "उच्चतम" if ranking == "highest" else "न्यूनतम"

    if lang == "hi":
        speak_text = f"{rank_word_hi} मार्जिन वाले प्रोडक्ट्स: " + ", ".join(top_names) + "।"
        display_text = f"{rank_word_hi} मार्जिन: {len(top_items)} प्रोडक्ट्स"
    elif lang == "hinglish":
        speak_text = f"Sabse {ranking} margin wale products hain: " + ", ".join(top_names) + "."
        display_text = f"{ranking.capitalize()} Margin: {len(top_items)} products"
    else:
        speak_text = f"The products with the {rank_word} recorded margins are: " + ", ".join(top_names) + "."
        display_text = f"{rank_word.capitalize()} Recorded Margins ({len(top_items)} products)"

    rows = [{
        "sku": s["product"].get("sku") or "--",
        "name": s["product"]["name"],
        "cost": f"₹{s['purchase_price']:,.2f}",
        "price": f"₹{s['selling_price']:,.2f}",
        "profit": f"₹{s['gross_profit']:,.2f}",
        "margin": f"{s['margin_pct']}%"
    } for s in top_items]

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "margin_rankings",
        "source": source_label,
        "source_type": "catalogue",
        "match_count": len(top_items),
        "ranking": ranking,
        "table": {"columns": ["SKU", "NAME", "COST", "PRICE", "PROFIT", "MARGIN %"], "rows": rows},
        "follow_ups": ["Which products need reordering?", "Show all products"]
    }


def _build_clarification_response(prompt_message: str, candidates: Optional[List[Dict[str, Any]]] = None, options: Optional[List[str]] = None, lang: str = "en") -> Dict[str, Any]:
    return {
        "speak": prompt_message,
        "display": prompt_message,
        "action": "clarify_query",
        "source": "Clarification Engine",
        "source_type": "assistant",
        "candidates": candidates or [],
        "follow_ups": options or ["Show all products", "Check inventory summary"]
    }


def _build_out_of_scope_response(raw_command: str, lang: str = "en") -> Dict[str, Any]:
    if lang == "hi":
        msg = "मैं एक बिजनेस इंटेलिजेंस और इन्वेंट्री असिस्टेंट हूँ। यह सवाल मेरे बिजनेस स्कोप से बाहर है, लेकिन मैं आपके प्रोडक्ट्स, स्टॉक या बिजनेस डॉक्यूमेंट्स में आपकी मदद कर सकता हूँ।"
    elif lang == "hinglish":
        msg = "Main SARTHI business intelligence assistant hoon. Yeh question mere scope se bahar hai. Main aapke products, stock, pricing ya business documents analyze karne mein help kar sakta hoon."
    else:
        msg = "I specialize in enterprise business intelligence, inventory tracking, pricing, and business document search. That request is outside my operational scope, but I can assist you with your products, stock, or business reports."

    return {
        "speak": msg,
        "display": msg,
        "action": "out_of_scope",
        "source": "SARTHI Core",
        "source_type": "assistant",
        "follow_ups": ["Show all products", "Which products need reordering?", "Check inventory summary"]
    }


def _route_intent_internal(cmd: str, c_lower: str, context: Dict[str, Any], db_path: Optional[str], cat_conn: Any, session_id: Optional[str] = None) -> Dict[str, Any]:
    # Multilingual normalization and language detection
    cleaned_cmd, detected_lang = multilingual.clean_query(cmd)
    clean_lower = cleaned_cmd.lower()
    session_ctx = multilingual.get_session_context(session_id)

    # =========================================================================
    # PRECEDENCE 1: CONVERSATIONAL CONTEXT & PENDING ACTION RESOLUTION
    # =========================================================================

    # 1A. Explicit Cancellation check
    if multilingual.is_cancellation(cmd, lang=detected_lang):
        had_pending = session_ctx.get_pending_action() is not None
        session_ctx.clear_pending_action()
        loc = multilingual.format_multilingual_response("cancellation", detected_lang, {})
        speak_msg = loc["speak"] if had_pending else "No action is currently pending. Standing by for your next command."
        disp_msg = loc["display"] if had_pending else "No pending action"
        return {
            "speak": speak_msg,
            "display": disp_msg,
            "action": "cancelled",
            "source": "Session Sentinel",
            "source_type": "assistant",
            "had_pending_action": had_pending,
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    # 1B. Explicit Confirmation check
    if multilingual.is_confirmation(cmd, lang=detected_lang):
        pending = session_ctx.get_pending_action()
        if pending:
            session_ctx.clear_pending_action()  # Clear immediately to prevent repeat executions
            p_action = pending.get("action")
            if p_action == "product_list":
                return _build_product_list_response(cat_conn, source_label="Product Catalogue", lang=detected_lang)
            elif p_action == "product_stock" and pending.get("product_name"):
                return _build_stock_response(pending["product_name"], cat_conn, source_label="Inventory Balance", lang=detected_lang, db_path=db_path, session_id=session_id)
            elif p_action == "product_price" and pending.get("product_name"):
                return _build_selling_price_response(pending["product_name"], cat_conn, source_label="Product Catalogue", lang=detected_lang, session_id=session_id)
            else:
                return {
                    "speak": "Acknowledged. Please specify which action or product you would like to proceed with.",
                    "display": "Confirmation received (ambiguous target)",
                    "action": "acknowledgement",
                    "source": "Session Sentinel",
                    "source_type": "assistant",
                    "follow_ups": ["Show all products", "Check inventory summary"]
                }
        else:
            # No pending action -> honest conversational acknowledgement without inventing actions
            loc = multilingual.format_multilingual_response("acknowledgement", detected_lang, {})
            return {
                "speak": loc["speak"],
                "display": loc["display"],
                "action": "acknowledgement",
                "source": "SARTHI Core",
                "source_type": "assistant",
                "follow_ups": ["Show all products", "Check inventory summary"]
            }

    # 1C. Pending clarification parameter resolution (e.g., user previously asked "Tell me the stock of the")
    pending_curr = session_ctx.get_pending_action()
    if pending_curr and pending_curr.get("action") == "product_stock_clarify":
        q_words = ["who", "what", "where", "when", "why", "how", "which", "koun", "kaun", "kya", "kab", "kahan", "kaise", "tell", "show", "check", "list", "view", "batao", "dikhao"]
        words = [w for w in re.split(r'\s+', c_lower) if w]
        is_question_or_command = any(qw in words for qw in q_words) or len(words) > 3 or any(w in c_lower for w in ["stock", "stok", "स्टॉक", "price", "keemat", "cost", "catalogue", "catalog", "help", "exit", "quit", "cancel", "no"])
        if not is_question_or_command:
            clean_target = cmd.strip().rstrip('?.')
            if not multilingual.is_product_stopword(clean_target):
                session_ctx.clear_pending_action()
                return _build_stock_response(clean_target, cat_conn, source_label="Inventory Balance", lang=detected_lang, db_path=db_path, session_id=session_id)
        else:
            # Query is a question, command, or distinct intent: clear the pending clarification
            session_ctx.clear_pending_action()

    # =========================================================================
    # PRECEDENCE 2: IDENTIFY INCOMPLETE REQUESTS & MARKET PRICE INQUIRIES
    # =========================================================================
    multi_match = multilingual.match_multilingual_intent(cmd, lang=detected_lang, session_id=session_id)

    # 2A. Incomplete stock inquiry
    if multi_match and multi_match[0] == "incomplete_stock_query":
        session_ctx.set_pending_action(action="product_stock_clarify", prompt="Which product would you like me to check the stock for?", language=detected_lang)
        loc = multilingual.format_multilingual_response("incomplete_stock_query", detected_lang, {})
        return {
            "speak": loc["speak"],
            "display": loc["display"],
            "action": "clarification_needed",
            "source": "Inventory Diagnostics",
            "source_type": "assistant",
            "clarification_type": "missing_product",
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    # 2B. Market Price inquiries (distinguish internal recorded price from unverified external market valuation)
    if (multi_match and multi_match[0] == "market_price_inquiry") or any(k in c_lower for k in ['market price', 'market value', 'bazaar bhav', 'open market']):
        target = None
        if multi_match and multi_match[0] == "market_price_inquiry":
            target = multi_match[1].get("product_name")
        if not target:
            m_p = re.search(r'(?:market\s+(?:price|value)|bazaar\s+bhav)\s+(?:of|for|ka|ki)?\s*([a-zA-Z0-9_\-\s]+)', c_lower)
            if m_p:
                target = m_p.group(1).strip()
        return _build_market_price_clarification_response(target, cat_conn, lang=detected_lang, db_path=db_path, session_id=session_id)

    # =========================================================================
    # PRECEDENCE 3: CONFIDENT STRUCTURED BUSINESS QUERIES & MULTILINGUAL MATCHING
    # =========================================================================
    if multi_match:
        m_intent, m_params = multi_match
        if m_intent == "prompt_injection":
            loc = multilingual.format_multilingual_response("prompt_injection", detected_lang, {})
            return {
                "speak": loc["speak"],
                "display": loc["display"],
                "action": "security_alert",
                "source": "Security Sentinel",
                "source_type": "security"
            }
        elif rag_engine.is_mixed_query(c_lower):
            target_doc_id = None
            if context.get("active_dataset_id"):
                target_doc_id = context["active_dataset_id"]
            elif isinstance(context.get("current_file_info"), dict) and context["current_file_info"].get("dataset_id"):
                target_doc_id = context["current_file_info"]["dataset_id"]
            else:
                ds_id, _, _ = resolve_dataset_from_query(cmd, db_path=db_path)
                if ds_id:
                    target_doc_id = ds_id
            mixed_res = rag_engine.answer_mixed_query(cmd, dataset_id=target_doc_id, db_path=db_path)
            combined_text = mixed_res.get("combined_answer", "")
            return {
                "speak": combined_text,
                "display": combined_text,
                "action": "mixed_intelligence",
                "source": "Hybrid DB & Document RAG",
                "source_type": "rag",
                "structured_fact": mixed_res.get("structured_fact"),
                "citations": mixed_res.get("citations", []),
                "follow_ups": ["Check inventory summary", "Show all products"]
            }
        elif m_intent == "identity":
            loc = multilingual.format_multilingual_response("identity", detected_lang, {})
            return {
                "speak": loc["speak"],
                "display": loc["display"],
                "action": "identity",
                "source": "SARTHI Core",
                "source_type": "assistant",
                "follow_ups": ["Tum kya kar sakte ho?", "Saare products dikhao", "What is gross margin?"]
            }
        elif m_intent == "capabilities":
            loc = multilingual.format_multilingual_response("capabilities", detected_lang, {})
            return {
                "speak": loc["speak"],
                "display": loc["display"],
                "action": "capabilities",
                "source": "SARTHI Core",
                "source_type": "assistant",
                "follow_ups": ["Saare products dikhao", "Current stock batao", "What is gross margin?"]
            }
        elif m_intent == "greeting":
            loc = multilingual.format_multilingual_response("greeting", detected_lang, {})
            return {
                "speak": loc["speak"],
                "display": loc["display"],
                "action": "greeting",
                "source": "SARTHI Core",
                "source_type": "assistant",
                "follow_ups": ["Saare products dikhao", "Tum kya kar sakte ho?"]
            }
        elif m_intent == "acknowledgement":
            loc = multilingual.format_multilingual_response("acknowledgement", detected_lang, {})
            return {
                "speak": loc["speak"],
                "display": loc["display"],
                "action": "acknowledgement",
                "source": "SARTHI Core",
                "source_type": "assistant"
            }
        elif m_intent == "follow_up_explain_lang":
            target_lang = m_params.get("target_language", "Hindi")
            last_resp = session_ctx.get_last_response()
            if last_resp:
                last_text = last_resp.get("display") or last_resp.get("speak") or ""
                last_action = last_resp.get("action", "")
                if target_lang == "Hindi":
                    if "cheapest" in last_action or "cheapest_product" in last_action:
                        p = last_resp.get("product", {})
                        p_name = p.get("name", "Product")
                        sp = p.get("selling_price", 0.0)
                        content = f"पिछली जानकारी के अनुसार, कैटलॉग में सबसे सस्ता प्रोडक्ट '{p_name}' है, जिसकी विक्रय कीमत ₹{sp:,.2f} है।"
                    elif "stock" in last_action:
                        p = last_resp.get("product", {})
                        p_name = p.get("name", "Product")
                        qty = p.get("quantity_on_hand", 0)
                        unit = p.get("unit", "units")
                        content = f"पिछली जानकारी के अनुसार, '{p_name}' का स्टॉक {qty} {unit} है।"
                    elif "margin" in last_action:
                        content = f"पिछली जानकारी के अनुसार, प्रोडक्ट का ग्रॉस मार्जिन विवरण: {last_text}"
                    else:
                        expl = local_llm.generate_explanation(last_text, language="Hindi")
                        content = expl.get("content") if expl.get("success") else f"पिछला विवरण: {last_text}"
                elif target_lang == "Hinglish":
                    content = f"Previous context: {last_text}"
                else:
                    content = f"Previous context: {last_text}"
                return {
                    "speak": content,
                    "display": content,
                    "action": "llm_explanation",
                    "source": "Context Engine",
                    "source_type": "context",
                    "explanation": content,
                    "language": target_lang
                }
            else:
                if target_lang == "Hindi":
                    msg = "वर्तमान सत्र में समझाने के लिए कोई पूर्व संदर्भ (previous context) नहीं मिला। आप किस प्रोडक्ट या बिज़नेस कॉन्सेप्ट के बारे में जानना चाहते हैं?"
                elif target_lang == "Hinglish":
                    msg = "Session mein explain karne ke liye koi previous context nahi mila. Aap kis product ya concept ke baare mein jaanna chahte hain?"
                else:
                    msg = "There is no previous response in our session to explain. What product or concept would you like me to explain?"
                return {
                    "speak": msg,
                    "display": msg,
                    "action": "assistant_help",
                    "source": "Context Engine",
                    "source_type": "context"
                }
        elif m_intent == "product_verify":
            return _build_product_verify_response(cat_conn, source_label="Catalogue Audit", lang=detected_lang)
        elif m_intent == "inventory_summary":
            if any(k in c_lower for k in ['low stock status', 'inventory status', 'bi inventory']):
                return _handle_bi_inventory(context, db_path)
            return _build_inventory_summary_response(cat_conn, source_label="Inventory Ledger", lang=detected_lang)
        elif m_intent == "product_list":
            return _build_product_list_response(cat_conn, source_label="Product Catalogue", lang=detected_lang)
        elif m_intent == "product_count":
            return _build_product_count_response(cat_conn, source_label="Product Catalogue", lang=detected_lang)
        elif m_intent == "low_stock_products":
            if any(k in c_lower for k in ['low stock status', 'inventory status', 'bi inventory']):
                return _handle_bi_inventory(context, db_path)
            return _build_low_stock_response(cat_conn, source_label="Inventory Ledger", lang=detected_lang, db_path=db_path)
        elif m_intent == "lowest_stock_products":
            return _build_lowest_stock_response(cat_conn, source_label="Inventory Ledger", lang=detected_lang)
        elif m_intent == "out_of_stock_products":
            return _build_out_of_stock_response(cat_conn, source_label="Inventory Ledger", lang=detected_lang, db_path=db_path)
        elif m_intent == "cheapest_product":
            return _build_contextual_pricing_response(cat_conn, mode="cheapest", source_label="Product Catalogue", lang=detected_lang)
        elif m_intent == "expensive_product":
            return _build_contextual_pricing_response(cat_conn, mode="expensive", source_label="Product Catalogue", lang=detected_lang)
        elif m_intent == "product_stock":
            target = m_params.get("product_name")
            if not target or multilingual.is_product_stopword(target):
                session_ctx.set_pending_action(action="product_stock_clarify", prompt="Which product would you like me to check the stock for?", language=detected_lang)
                loc = multilingual.format_multilingual_response("incomplete_stock_query", detected_lang, {})
                return {
                    "speak": loc["speak"],
                    "display": loc["display"],
                    "action": "clarification_needed",
                    "source": "Inventory Diagnostics",
                    "source_type": "assistant",
                    "clarification_type": "missing_product",
                    "follow_ups": ["Show all products", "Check inventory summary"]
                }
            return _build_stock_response(target, cat_conn, source_label="Inventory Balance", lang=detected_lang, db_path=db_path, session_id=session_id)
        elif m_intent == "product_price":
            target = m_params.get("product_name")
            if not target or multilingual.is_product_stopword(target):
                if detected_lang in ("hi", "hinglish"):
                    msg = "Aap kis product ki keemat jaanna chahte hain?"
                else:
                    msg = "Which product's price would you like me to check?"
                return {
                    "speak": msg,
                    "display": msg,
                    "action": "clarification_needed",
                    "source": "Catalogue Diagnostics",
                    "source_type": "assistant",
                    "clarification_type": "missing_product",
                    "follow_ups": ["Show all products", "Check inventory summary"]
                }
            if any(w in c_lower for w in ['purchase price', 'purchase cost', 'cost price', 'buy price', 'purchase rate']):
                return _build_purchase_cost_response(target, cat_conn, source_label="Product Catalogue")
            return _build_selling_price_response(target, cat_conn, source_label="Product Catalogue", lang=detected_lang, session_id=session_id)
        elif m_intent in ("product_margin", "product_profit"):
            target = m_params.get("product_name")
            cost_basis = m_params.get("cost_basis", "purchase_price")
            intent_type = "profit" if (m_intent == "product_profit" or any(w in c_lower for w in ['profit', 'munafa', 'labh', 'मुनाफा', 'लाभ', 'bechne', 'selling'])) else "margin"
            if target and not multilingual.is_product_stopword(target):
                return _build_product_margin_response(
                    target, cat_conn, source_label="Profitability Analysis",
                    lang=detected_lang, db_path=db_path,
                    intent_type=intent_type, cost_basis=cost_basis, session_id=session_id
                )
            return _build_catalogue_margin_response(cat_conn, context=context, db_path=db_path, source_label="Profitability Analysis", lang=detected_lang)
        elif m_intent == "catalogue_margin":
            bi_rep = context.get("current_bi_report")
            if not bi_rep and context.get("active_dataset_id"):
                ds_rep = database.get_latest_report_for_dataset(context["active_dataset_id"], db_path=db_path)
                if ds_rep and "report_content" in ds_rep:
                    bi_rep = ds_rep["report_content"]
            if bi_rep and bi_rep.get("pricing", {}).get("computed"):
                pricing = bi_rep["pricing"]
                top_p = pricing.get("highest_margin_products", [])
                avg_m = pricing.get("average_gross_margin_pct", 0)
                leader = top_p[0] if top_p else None
                if leader:
                    speak_text = f"The highest gross margin product is {leader['product']} at {leader['gross_margin_pct']} percent margin. The average gross margin is {avg_m} percent."
                else:
                    speak_text = f"Average gross margin is {avg_m} percent across available pricing records."
                return {
                    "speak": speak_text,
                    "display": f"Avg Margin: {avg_m}% | Top: {leader['product'] if leader else 'N/A'}",
                    "action": "bi_pricing",
                    "source": "Commercial Intelligence",
                    "source_type": "report",
                    "pricing": pricing,
                    "follow_ups": ["Show all products", "Check inventory summary"]
                }
            return _build_catalogue_margin_response(cat_conn, context=context, db_path=db_path, source_label="Profitability Analysis", lang=detected_lang)
        elif m_intent == "supplier_lookup":
            target = m_params.get("product_name")
            if m_params.get("list_all") or not target:
                return _build_supplier_response(None, cat_conn, source_label="Supplier Ledger", lang=detected_lang, db_path=db_path)
            return _build_supplier_response(target, cat_conn, source_label="Supplier Ledger", lang=detected_lang, db_path=db_path)
        elif m_intent == "explanation":
            concept = m_params.get("concept", cleaned_cmd)
            target_lang = m_params.get("language") or ("Hindi" if "hindi" in c_lower else ("Hinglish" if detected_lang == "hinglish" else "English"))
            expl = local_llm.generate_explanation(concept, language=target_lang)
            return {
                "speak": expl.get("content", f"Here is the explanation for {concept}."),
                "display": expl.get("content", ""),
                "action": "llm_explanation",
                "source": f"Local AI ({expl.get('model', 'offline')})",
                "source_type": "llm",
                "explanation": expl.get("content", ""),
                "concept": concept,
                "language": target_lang,
                "inference_time_seconds": expl.get("inference_time_seconds"),
                "follow_ups": ["Show all products", "How many products do we have?"]
            }
        elif m_intent == "purchase_rate_history":
            target = m_params.get("product_name")
            return _build_purchase_rate_history_response(target, cat_conn, source_label="Procurement Ledger", lang=detected_lang, db_path=db_path)
        elif m_intent == "margin_rankings":
            ranking = m_params.get("ranking", "highest")
            return _build_margin_rankings_response(ranking=ranking, cat_conn=cat_conn, source_label="Profitability Analysis", lang=detected_lang, db_path=db_path)
        elif m_intent == "sales_comparison":
            return _build_sales_comparison_response(cat_conn, source_label="Sales Performance", lang=detected_lang, db_path=db_path)
        elif m_intent == "purchases_list":
            time_info = parse_time_range(cmd)
            p_dict = {**m_params, **time_info}
            return _build_purchases_list_response(p_dict, cat_conn, source_label="Procurement Ledger", lang=detected_lang, db_path=db_path)
        elif m_intent == "sales_list":
            time_info = parse_time_range(cmd)
            s_dict = {**m_params, **time_info}
            return _build_sales_list_response(s_dict, cat_conn, source_label="Sales Ledger", lang=detected_lang, db_path=db_path)
        elif m_intent == "inventory_movements":
            target = m_params.get("product_name")
            return _build_inventory_movements_response(target, cat_conn, source_label="Stock Ledger", lang=detected_lang, db_path=db_path)
        elif m_intent == "product_details":
            target = m_params.get("product_name")
            return _build_product_details_response(target, cat_conn, source_label="Product Catalogue", lang=detected_lang, db_path=db_path)
        elif m_intent == "out_of_scope":
            return _build_out_of_scope_response(cmd, lang=detected_lang)

    # =========================================================================
    # 0B. DIRECT CONCEPTUAL / MULTILINGUAL EXPLANATION (OLLAMA LOCAL LLM)
    # =========================================================================
    is_explanation_cmd = (
        ('in hindi' in c_lower) or
        ('in french' in c_lower) or
        ('in spanish' in c_lower) or
        ('explain gross margin' in c_lower) or
        (c_lower.startswith('explain ') and not c_lower.startswith(('explain the findings', 'explain findings')) and any(w in c_lower for w in [
            'gross margin', 'margin', 'reorder level', 'profit', 'markup', 'cash flow',
            'inventory turnover', 'ebitda', 'cogs'
        ])) or
        (c_lower.startswith('define ') and any(w in c_lower for w in [
            'gross margin', 'margin', 'reorder level', 'profit', 'markup'
        ]))
    )
    if is_explanation_cmd:
        lang = "Hindi" if "hindi" in c_lower else ("French" if "french" in c_lower else ("Spanish" if "spanish" in c_lower else ("Hinglish" if detected_lang == "hinglish" else "English")))
        concept = cmd
        for pfx in ['explain', 'what is', 'define']:
            if c_lower.startswith(pfx):
                concept = cmd[len(pfx):].strip()
                break
        concept = re.sub(r'\bin (hindi|english|french|spanish|german)\b', '', concept, flags=re.IGNORECASE).strip('?. ')
        expl = local_llm.generate_explanation(concept or cmd, language=lang)
        return {
            "speak": expl.get("content", f"here is the explanation for {concept or cmd}."),
            "display": expl.get("content", ""),
            "action": "llm_explanation",
            "source": f"Local AI ({expl.get('model', 'offline')})",
            "source_type": "llm",
            "explanation": expl.get("content", ""),
            "concept": concept or cmd,
            "language": lang,
            "inference_time_seconds": expl.get("inference_time_seconds"),
            "follow_ups": ["Show all products", "How many products do we have?"]
        }

    # =========================================================================
    # 0B-RAG. MIXED QUERY & EXPLICIT DOCUMENT INTELLIGENCE
    # =========================================================================
    # Resolve target document if explicitly mentioned in query or present in active context
    target_doc_id = None
    if context.get("active_dataset_id"):
        target_doc_id = context["active_dataset_id"]
    elif isinstance(context.get("current_file_info"), dict) and context["current_file_info"].get("dataset_id"):
        target_doc_id = context["current_file_info"]["dataset_id"]
    else:
        ds_id, _, _ = resolve_dataset_from_query(cmd, db_path=db_path)
        if ds_id:
            target_doc_id = ds_id

    if rag_engine.is_mixed_query(c_lower):
        mixed_res = rag_engine.answer_mixed_query(cmd, dataset_id=target_doc_id, db_path=db_path)
        combined_text = mixed_res.get("combined_answer", "")
        return {
            "speak": combined_text,
            "display": combined_text,
            "action": "mixed_intelligence",
            "source": "Hybrid DB & Document RAG",
            "source_type": "rag",
            "structured_fact": mixed_res.get("structured_fact"),
            "citations": mixed_res.get("citations", []),
            "follow_ups": ["Check inventory summary", "Show all products"]
        }

    doc_triggers = [
        'what does the document say', 'what does the pdf say', 'what does the agreement say',
        'what does the contract say', 'according to the document', 'according to the contract',
        'contract clause', 'terms and conditions', 'warranty clause', 'payment terms',
        'delivery clause', 'delivery terms', 'in the document', 'in the pdf', 'in the contract',
        'from the document', 'document intelligence', 'document search', 'search in document'
    ]
    if any(t in c_lower for t in doc_triggers):
        doc_res = rag_engine.answer_document_query(cmd, dataset_id=target_doc_id, db_path=db_path)
        ans = doc_res.get("answer", "")
        return {
            "speak": ans,
            "display": ans,
            "action": "document_query" if doc_res.get("has_sufficient_evidence") else "document_no_evidence",
            "source": "Document Intelligence",
            "source_type": "rag",
            "has_sufficient_evidence": doc_res.get("has_sufficient_evidence", False),
            "citations": doc_res.get("citations", []),
            "confidence": doc_res.get("confidence", 0.0),
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    # High-precision legacy BI telemetry check
    if any(k in c_lower for k in ['low stock status', 'inventory status', 'bi inventory', 'stock status']):
        return _handle_bi_inventory(context, db_path)

    is_dataset_query = any(k in c_lower for k in [
        'summarise this dataset', 'summarize this dataset', 'summarise dataset', 'summarize dataset',
        'how many rows and columns', 'rows and columns', 'how many rows', 'how many columns', 'row count', 'column count',
        'list all column names', 'list all columns', 'what are the columns', 'show columns', 'column names', 'list columns',
        'missing values in each column', 'missing values in this dataset', 'what are the missing values', 'missing values',
        'are there duplicate rows', 'duplicate rows', 'check duplicates', 'count duplicate records', 'duplicates in dataset',
        'show the first 10 rows', 'show first 10 rows', 'first 10 rows', 'preview rows', 'sample rows', 'first 5 rows',
        'average value of', 'average of', 'mean of', 'highest and lowest values', 'max and min of', 'max value of', 'min value of',
        'filter rows where', 'filter by', 'show rows where', 'rows where',
        'group by', 'count by', 'count records in',
        'which columns appear to contain dates', 'date columns', 'detect dates',
        'what data is missing', 'what data-quality problems', 'data quality problems', 'data quality', 'quality score', 'quality audit'
    ])

    # =========================================================================
    # 1. PRODUCT CATALOGUE & INVENTORY INTENTS (High-Speed Deterministic Routing)
    # =========================================================================

    # 1A. All Products / Catalogue Listing
    is_catalogue_list = any(k in c_lower for k in [
        'what are all products', 'what are the products', 'all products', 'list all products',
        'show all products', 'show products', 'list products', 'catalogue products',
        'what products do we have', 'get products', 'catalogue list', 'view products'
    ])
    if is_catalogue_list:
        return _build_product_list_response(cat_conn, source_label="Product Catalogue")

    # 1B. Total Product Count
    if any(k in c_lower for k in ['how many products do we have', 'how many products', 'total products count', 'product count', 'number of products']):
        return _build_product_count_response(cat_conn, source_label="Product Catalogue")

    # 1C. Products Without Selling Price
    if any(k in c_lower for k in ['no selling price', 'missing selling price', 'products without selling price', 'which products have no price']):
        all_prods = database.list_products(is_active=True, page_size=100, conn=cat_conn)["items"]
        missing_price = [p for p in all_prods if (p.get("selling_price") is None or p.get("selling_price") <= 0)]
        if not missing_price:
            speak_text = "All active products in the catalogue have valid selling prices configured."
            rows = []
        else:
            names = ", ".join([p["name"] for p in missing_price[:3]])
            speak_text = f"There are {len(missing_price)} product(s) without a selling price, including {names}."
            rows = [{"sku": p.get("sku") or "--", "name": p.get("name"), "cost": p.get("purchase_price", 0)} for p in missing_price]

        return {
            "speak": speak_text,
            "display": f"Unpriced Products: {len(missing_price)} items",
            "action": "catalogue_no_price",
            "source": "Product Catalogue",
            "source_type": "catalogue",
            "total_count": len(missing_price),
            "table": {"columns": ["SKU", "NAME", "PURCHASE COST"], "rows": rows},
            "follow_ups": ["What are all products?", "Show products below reorder level"]
        }

    # 1D. Low Stock & Reorder Checks
    if any(k in c_lower for k in ['which products are low in stock', 'products low in stock', 'low stock products', 'what products are low in stock', 'show products below reorder level', 'products below reorder level', 'below reorder level']):
        return _build_low_stock_response(cat_conn, source_label="Inventory Ledger", lang=detected_lang, db_path=db_path)

    # 1E. Out of Stock
    if any(k in c_lower for k in ['which products are out of stock', 'products out of stock', 'out of stock products', 'what is out of stock']):
        return _build_out_of_stock_response(cat_conn, source_label="Inventory Ledger", lang=detected_lang, db_path=db_path)

    # 1F. Specific Product Stock Check
    if any(k in c_lower for k in ['current stock of', 'stock of product', 'what is the stock of', 'how much stock do we have for', 'how much stock for', 'how much stock is left for', 'stock of']):
        target = c_lower
        for pfx in ['how much stock do we have for', 'how much stock is left for', 'how much stock for', 'what is the current stock of', 'what is the stock of', 'current stock of', 'stock of product', 'stock of']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        target = target.rstrip('?.')
        if not target or multilingual.is_product_stopword(target):
            session_ctx.set_pending_action(action="product_stock_clarify", prompt="Which product would you like me to check the stock for?", language=detected_lang)
            loc = multilingual.format_multilingual_response("incomplete_stock_query", detected_lang, {})
            return {
                "speak": loc["speak"],
                "display": loc["display"],
                "action": "clarification_needed",
                "source": "Inventory Diagnostics",
                "source_type": "assistant",
                "clarification_type": "missing_product",
                "follow_ups": ["Show all products", "Check inventory summary"]
            }
        return _build_stock_response(target, cat_conn, source_label="Inventory Balance", lang=detected_lang, db_path=db_path, session_id=session_id)

    # 1G. Specific Product Selling Price
    if any(k in c_lower for k in ['show the selling price of', 'what is the selling price of', 'selling price of', 'sale price of', 'retail price of']):
        target = c_lower
        for pfx in ['show the selling price of', 'what is the selling price of', 'selling price of', 'sale price of', 'retail price of']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        return _build_selling_price_response(target, cat_conn, source_label="Product Catalogue")

    # 1H. Specific Product Purchase Cost
    if any(k in c_lower for k in ['what is the purchase price of', 'purchase price of', 'cost price of', 'buy price of', 'purchase cost of']):
        target = c_lower
        for pfx in ['what is the purchase price of', 'purchase price of', 'cost price of', 'buy price of', 'purchase cost of']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        target = target.rstrip('?.')
        res = database.list_products(search=target, is_active=True, conn=cat_conn)
        items = res["items"]

        if not items:
            speak_text = f"No product matching '{target}' was found in the catalogue."
            return {
                "speak": speak_text,
                "display": f"Cost: No match for '{target}'",
                "action": "catalogue_price",
                "source": "Product Catalogue",
                "source_type": "catalogue",
                "match_count": 0
            }
        elif len(items) > 1:
            candidates = ", ".join([f"{p['name']} (SKU: {p['sku'] or 'N/A'})" for p in items[:3]])
            speak_text = f"Multiple products match '{target}': {candidates}. Please clarify the exact SKU or name."
            return {
                "speak": speak_text,
                "display": f"Multiple matches for '{target}'",
                "action": "catalogue_price",
                "source": "Product Catalogue",
                "source_type": "catalogue",
                "match_count": len(items),
                "candidates": items[:5]
            }
        else:
            p = items[0]
            speak_text = f"The purchase price of {p['name']} is {p['purchase_price']} {p['currency']}. Current selling price is {p['selling_price']} {p['currency']}."
            return {
                "speak": speak_text,
                "display": f"{p['name']}: Cost = ₹{p['purchase_price']:,.2f} | Selling = ₹{p['selling_price']:,.2f}",
                "action": "catalogue_price",
                "source": "Product Catalogue",
                "source_type": "catalogue",
                "match_count": 1,
                "product": p
            }

    # 1I. Find Product by Name or SKU
    if any(k in c_lower for k in ['find product', 'search product', 'lookup product', 'find sku', 'search sku']):
        target = c_lower
        for pfx in ['find product sku', 'search product sku', 'find product', 'search product', 'lookup product', 'find sku', 'search sku']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        return _build_find_product_response(target, cat_conn, source_label="Product Catalogue")

    # 1J. Supplier Lookup
    if any(k in c_lower for k in ['supplier for', 'supplier of', 'who is the supplier', 'supplier details', 'list suppliers', 'all suppliers']):
        target = c_lower
        for pfx in ['who is the supplier for', 'who is the supplier of', 'supplier details for', 'supplier for', 'supplier of']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        if any(k in c_lower for k in ['list suppliers', 'all suppliers', 'show suppliers']):
            return _build_supplier_response(None, cat_conn, source_label="Supplier Ledger", lang=detected_lang, db_path=db_path)
        return _build_supplier_response(target, cat_conn, source_label="Supplier Ledger", lang=detected_lang, db_path=db_path)

    # 1K. Margin & Profit Analysis (Product & Catalogue)
    if any(k in c_lower for k in ['margin', 'profit', 'munafa', 'मार्जिन', 'मुनाफा', 'लाभ']):
        m_intent = multilingual.match_multilingual_intent(cleaned_cmd, lang=detected_lang, session_id=session_id)
        if m_intent and m_intent[0] == "explanation":
            concept = m_intent[1].get("concept", cleaned_cmd)
            target_lang = m_intent[1].get("language") or ("Hindi" if "hindi" in c_lower else ("Hinglish" if detected_lang == "hinglish" else "English"))
            expl = local_llm.generate_explanation(concept, language=target_lang)
            return {
                "speak": expl.get("content", f"Here is the explanation for {concept}."),
                "display": expl.get("content", ""),
                "action": "llm_explanation",
                "source": f"Local AI ({expl.get('model', 'offline')})",
                "source_type": "llm",
                "explanation": expl.get("content", ""),
                "concept": concept,
                "language": target_lang,
                "inference_time_seconds": expl.get("inference_time_seconds"),
                "follow_ups": ["Show all products", "How many products do we have?"]
            }
        elif m_intent and m_intent[0] in ("product_margin", "product_profit"):
            cost_basis = m_intent[1].get("cost_basis", "purchase_price")
            intent_type = "profit" if (m_intent[0] == "product_profit" or any(w in c_lower for w in ['profit', 'munafa', 'labh', 'मुनाफा', 'लाभ', 'bechne', 'selling'])) else "margin"
            return _build_product_margin_response(
                m_intent[1].get("product_name"), cat_conn,
                source_label="Profitability Analysis", lang=detected_lang,
                db_path=db_path, intent_type=intent_type, cost_basis=cost_basis, session_id=session_id
            )
        elif m_intent and m_intent[0] == "catalogue_margin":
            return _build_catalogue_margin_response(cat_conn, context=context, db_path=db_path, source_label="Profitability Analysis", lang=detected_lang)

        # Skip product margin fallback regex if query is asking to explain or define a concept
        if not (c_lower.startswith(('explain ', 'define ')) or 'kya hota hai' in c_lower or 'in hindi' in c_lower or 'samjhao' in c_lower):
            # Fallback regex extraction for profit/margin queries if multi_match was None
            cost_basis = "last_purchase_rate" if any(k in c_lower for k in ['last purchase rate', 'latest purchase rate', 'pichle purchase rate', 'aakhri purchase rate']) else "purchase_price"
        cand = None
        for pat in [
            r'(?:what\s+is\s+(?:the\s+)?)?(?:gross\s+)?(?:profit|margin)\s+(?:of|on|for|in)\s+(?:selling\s+)?(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-\s]+)',
            r'(?:what\s+profit\s+(?:do\s+we\s+make\s+)?(?:in\s+)?selling\s+|(?:what\s+is\s+(?:the\s+)?)?(?:gross\s+)?profit\s+(?:in\s+)?selling\s+)(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-\s]+)',
            r'(?:calculate\s+(?:the\s+)?(?:gross\s+)?(?:profit|margin)\s+(?:on|for|of)\s+)(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-\s]+)',
            r'([a-zA-Z0-9_\-\s]+?)\s+bechne\s+par\s+(?:kitna\s+)?(?:profit|munafa|labh)',
            r'([a-zA-Z0-9_\-\s]+?)\s+(?:ka|ki|ke|par|me|mein)\s+(?:kitna\s+)?(?:profit|margin|munafa|labh)',
        ]:
            m_cand = re.search(pat, c_lower)
            if m_cand:
                cand = m_cand.group(1).strip().rstrip('?.!')
                cand = re.sub(r'^(?:is|iss|is product|iss product|this product|the product|the|a|an)\s+', '', cand, flags=re.IGNORECASE).strip()
                cand = re.sub(r'\b(bro|bhai|sarthi|saarthi|vantiq|jarvis|please|batao|bataiye|dikhao|kya hai|kitna hai|hai)\b', '', cand, flags=re.IGNORECASE).strip()
                break

        if cand and not multilingual.is_product_stopword(cand) and cand not in ('overall', 'total', 'average', 'catalogue', 'all', 'product'):
            intent_type = "profit" if any(w in c_lower for w in ['profit', 'munafa', 'labh', 'मुनाफा', 'लाभ', 'bechne', 'selling']) else "margin"
            return _build_product_margin_response(
                cand, cat_conn, source_label="Profitability Analysis",
                lang=detected_lang, db_path=db_path, intent_type=intent_type, cost_basis=cost_basis, session_id=session_id
            )

    # 1L. Last Purchase Rate / Rate History
    if any(k in c_lower for k in ['last purchase rate', 'last purchase cost', 'what was the last purchase rate', 'purchase rate history', 'last buying rate']):
        target = c_lower
        for pfx in ['what was the last purchase rate for', 'last purchase rate for', 'last purchase rate of', 'last purchase cost of', 'last purchase cost for', 'last purchase rate', 'last purchase cost']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        target = target.rstrip('?. ')
        return _build_purchase_rate_history_response(target, cat_conn, source_label="Procurement Ledger", lang=detected_lang, db_path=db_path)

    # 1M. Margin Rankings
    if any(k in c_lower for k in ['highest recorded margin', 'highest recorded margins', 'lowest recorded margin', 'lowest recorded margins']):
        ranking = "lowest" if any(w in c_lower for w in ["lowest", "least", "kam"]) else "highest"
        return _build_margin_rankings_response(ranking=ranking, cat_conn=cat_conn, source_label="Profitability Analysis", lang=detected_lang, db_path=db_path)

    # 1N. Sales Comparison
    if any(k in c_lower for k in ["compare this month's sales with last month", "compare sales this month with last month", "compare this month with last month", "compare this month sales with last month", "sales comparison"]):
        return _build_sales_comparison_response(cat_conn, source_label="Sales Performance", lang=detected_lang, db_path=db_path)

    # 1O. Purchases & Sales Ledger Queries
    if any(k in c_lower for k in ['show purchases from last month', 'purchases from last month', 'show purchases this month', 'purchases this month', 'recent purchases', 'show all purchases', 'list purchases']):
        time_info = parse_time_range(cmd)
        return _build_purchases_list_response(time_info, cat_conn, source_label="Procurement Ledger", lang=detected_lang, db_path=db_path)

    if any(k in c_lower for k in ['show sales this month', 'sales this month', 'show sales from last month', 'sales from last month', 'recent sales', 'show all sales', 'list sales']):
        time_info = parse_time_range(cmd)
        return _build_sales_list_response(time_info, cat_conn, source_label="Sales Ledger", lang=detected_lang, db_path=db_path)

    # 1P. Inventory Movement History
    if any(k in c_lower for k in ['inventory movement history', 'stock movement history', 'inventory movements', 'stock movements', 'movement history for', 'movements for']):
        target = c_lower
        for pfx in ['inventory movement history for', 'stock movement history for', 'movement history for', 'movements for', 'inventory movements for', 'inventory movement history', 'stock movement history', 'inventory movements', 'stock movements']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        target = target.rstrip('?. ')
        return _build_inventory_movements_response(target, cat_conn, source_label="Stock Ledger", lang=detected_lang, db_path=db_path)

    # 1Q. Product Details by SKU or Name
    if any(k in c_lower for k in ['show details for', 'product details for', 'details of product', 'details for product', 'details for sku', 'sku details']):
        target = c_lower
        for pfx in ['show details for product', 'show details for sku', 'show details for', 'product details for', 'details of product', 'details for product', 'details for sku', 'sku details']:
            if pfx in target:
                target = target.split(pfx, 1)[1].strip()
                break
        target = target.rstrip('?. ')
        return _build_product_details_response(target, cat_conn, source_label="Product Catalogue", lang=detected_lang, db_path=db_path)

    # 1R. Out of Scope Queries
    if any(k in c_lower for k in ['weather in', 'what is the weather', 'weather forecast', 'bake a cake', 'recipe for', 'cricket score', 'football score']) or ('bake' in c_lower and 'cake' in c_lower) or ('recipe' in c_lower):
        return _build_out_of_scope_response(cmd, lang=detected_lang)

    # =========================================================================
    # 2. DATASET-AWARE NATURAL LANGUAGE QUERIES
    # =========================================================================

    is_dataset_query = any(k in c_lower for k in [
        'summarise this dataset', 'summarize this dataset', 'summarise dataset', 'summarize dataset',
        'how many rows and columns', 'rows and columns', 'how many rows', 'how many columns', 'row count', 'column count',
        'list all column names', 'list all columns', 'what are the columns', 'show columns', 'column names', 'list columns',
        'missing values in each column', 'missing values in this dataset', 'what are the missing values', 'missing values',
        'are there duplicate rows', 'duplicate rows', 'check duplicates', 'count duplicate records', 'duplicates in dataset',
        'show the first 10 rows', 'show first 10 rows', 'first 10 rows', 'preview rows', 'sample rows', 'first 5 rows',
        'average value of', 'average of', 'mean of', 'highest and lowest values', 'max and min of', 'max value of', 'min value of',
        'filter rows where', 'filter by', 'show rows where', 'rows where',
        'group by', 'count by', 'count records in',
        'which columns appear to contain dates', 'date columns', 'detect dates',
        'what data is missing', 'what data-quality problems', 'data quality problems', 'data quality', 'quality score', 'quality audit'
    ])

    if is_dataset_query:
        # Resolve dataset target
        target_ds_id, disambig = get_effective_dataset_id(cmd, context=context, db_path=db_path)
        if disambig:
            return disambig

        if not target_ds_id:
            msg = "no dataset is currently active. You can upload an Excel (.xlsx) or PDF file in the Data Import Protocol panel, or select a saved dataset from the Saved Data Library."
            return {
                "speak": msg,
                "display": "No active dataset loaded.",
                "action": "dataset_no_data",
                "source": "Dataset Intelligence",
                "source_type": "dataset",
                "follow_ups": ["Upload Excel File", "Show Saved Datasets", "What are all products?"]
            }

        # 2A. Dataset Dimensions (rows and columns)
        if any(k in c_lower for k in ['how many rows and columns', 'rows and columns', 'how many rows', 'how many columns', 'row count', 'column count', 'dataset dimensions']):
            try:
                res = dataset_intelligence.get_dataset_dimensions(target_ds_id, db_path=db_path)
                return {
                    "speak": f"{res['summary_text']}",
                    "display": f"{res['filename']}: {res.get('row_count', 0)} Rows × {res.get('column_count', 0)} Columns",
                    "action": "dataset_dimensions",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "data": res,
                    "follow_ups": ["List all column names", "What are the missing values in each column?", "Summarise this dataset"]
                }
            except Exception as e:
                logger.error(f"Error computing dimensions: {e}")
                return {"speak": f"could not compute dimensions: {e}", "display": str(e), "action": "error"}

        # 2B. Summarize Dataset
        if any(k in c_lower for k in ['summarise this dataset', 'summarize this dataset', 'summarise dataset', 'summarize dataset', 'dataset summary', 'tell me about this dataset']):
            try:
                res = dataset_intelligence.summarize_dataset(target_ds_id, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_summary",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "data": res,
                    "follow_ups": ["List all column names", "What are the missing values in each column?", "Show the first 10 rows"]
                }
            except Exception as e:
                return {"speak": f"error summarizing dataset: {e}", "display": str(e), "action": "error"}

        # 2C. List Columns
        if any(k in c_lower for k in ['list all column names', 'list all columns', 'what are the columns', 'show columns', 'column names', 'list columns']):
            try:
                res = dataset_intelligence.list_dataset_columns(target_ds_id, db_path=db_path)
                rows = [{"column": c["name"], "type": c["inferred_type"], "non_null": c["non_null_count"], "missing": c["null_count"]} for c in res.get("column_details", [])]
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_columns",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "columns": res["columns"],
                    "table": {"columns": ["COLUMN", "INFERRED TYPE", "NON-NULL COUNT", "MISSING COUNT"], "rows": rows},
                    "follow_ups": ["What are the missing values in each column?", "Show the first 10 rows"]
                }
            except Exception as e:
                return {"speak": f"error listing columns: {e}", "display": str(e), "action": "error"}

        # 2D. Missing Values
        if any(k in c_lower for k in ['what are the missing values', 'missing values in each column', 'missing values', 'missing data', 'null values', 'empty cells']):
            try:
                res = dataset_intelligence.get_missing_values(target_ds_id, db_path=db_path)
                rows = [{"column": c["column"], "missing_count": c["missing_count"], "missing_pct": f"{c['missing_pct']}%"} for c in res.get("top_missing_columns", [])]
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_missing_values",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "total_missing": res.get("total_missing_cells", 0),
                    "table": {"columns": ["COLUMN", "MISSING CELLS", "MISSING %"], "rows": rows},
                    "follow_ups": ["Are there duplicate rows?", "Summarise this dataset"]
                }
            except Exception as e:
                return {"speak": f"error inspecting missing values: {e}", "display": str(e), "action": "error"}

        # 2E. Duplicate Rows
        if any(k in c_lower for k in ['are there duplicate rows', 'duplicate rows', 'check duplicates', 'count duplicate records', 'duplicates in dataset']):
            try:
                res = dataset_intelligence.get_duplicate_rows(target_ds_id, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_duplicates",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "data": res,
                    "follow_ups": ["What are the missing values in each column?", "Summarise this dataset"]
                }
            except Exception as e:
                return {"speak": f"error checking duplicate rows: {e}", "display": str(e), "action": "error"}

        # 2F. First N Rows
        if any(k in c_lower for k in ['show the first 10 rows', 'show first 10 rows', 'first 10 rows', 'preview rows', 'sample rows', 'first 5 rows']):
            n = 5 if '5' in c_lower else 10
            try:
                res = dataset_intelligence.get_head_rows(target_ds_id, n=n, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_head",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "table": {"columns": res.get("columns", [])[:8], "rows": res.get("rows", [])},
                    "follow_ups": ["List all column names", "Summarise this dataset"]
                }
            except Exception as e:
                return {"speak": f"error fetching rows: {e}", "display": str(e), "action": "error"}

        # 2G. Date Columns Detection
        if any(k in c_lower for k in ['which columns appear to contain dates', 'date columns', 'detect dates']):
            try:
                res = dataset_intelligence.detect_date_columns(target_ds_id, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_dates",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "date_columns": res.get("date_columns", []),
                    "follow_ups": ["List all column names", "Summarise this dataset"]
                }
            except Exception as e:
                return {"speak": f"error checking date columns: {e}", "display": str(e), "action": "error"}

        # 2H. Column Statistics (Average, Min, Max)
        if any(k in c_lower for k in ['average value of', 'average of', 'mean of', 'highest and lowest values', 'max and min of', 'max value of', 'min value of']):
            # Extract target column name
            col_target = c_lower
            for pfx in ['what is the average value of', 'what is the average of', 'average value of', 'average of', 'mean of', 'highest and lowest values of', 'highest and lowest values in', 'max and min of', 'max value of', 'min value of']:
                if pfx in col_target:
                    col_target = col_target.split(pfx, 1)[1].strip()
                    break
            col_target = col_target.rstrip('?.')

            try:
                res = dataset_intelligence.get_column_statistics(target_ds_id, col_target, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_stats",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "data": res,
                    "follow_ups": ["List all column names", "Summarise this dataset"]
                }
            except ValueError as ve:
                return {
                    "speak": f"{ve}",
                    "display": str(ve),
                    "action": "dataset_stats_error",
                    "source": "Dataset Intelligence",
                    "source_type": "dataset"
                }

        # 2I. Filter Rows
        if any(k in c_lower for k in ['filter rows where', 'filter by', 'show rows where']):
            # Pattern: filter rows where [col] equals [val]
            m = re.search(r'where ([\w\s_-]+) (equals|==|contains|>|<|>=|<=) ([\w\s\.-]+)', c_lower)
            if not m:
                m = re.search(r'where ([\w\s_-]+) is ([\w\s\.-]+)', c_lower)
                if m:
                    col_name = m.group(1).strip()
                    op = "equals"
                    val = m.group(2).strip()
                else:
                    return {
                        "speak": "please format your filter as: 'Filter rows where [column] equals [value]'.",
                        "display": "Invalid filter format. Example: Filter rows where Status equals Active",
                        "action": "dataset_filter_error",
                        "source": "Dataset Intelligence",
                        "source_type": "dataset"
                    }
            else:
                col_name = m.group(1).strip()
                op = m.group(2).strip()
                val = m.group(3).strip()

            try:
                res = dataset_intelligence.filter_dataset(target_ds_id, col_name, op, val, db_path=db_path)
                return {
                    "speak": res["speak"],
                    "display": res["display"],
                    "action": "dataset_filter",
                    "source": f"Dataset: {res['filename']}",
                    "source_type": "dataset",
                    "dataset_id": target_ds_id,
                    "match_count": res.get("match_count", 0),
                    "table": {"columns": res.get("columns", [])[:8], "rows": res.get("rows", [])},
                    "follow_ups": ["Summarise this dataset", "Show the first 10 rows"]
                }
            except ValueError as ve:
                return {"speak": f"{ve}", "display": str(ve), "action": "dataset_filter_error"}

        # 2J. Group By
        if any(k in c_lower for k in ['group by', 'count by']):
            m = re.search(r'(?:group by|count by)\s+([\w\s_-]+)', c_lower)
            if m:
                col_name = m.group(1).replace('and count records', '').replace('and count', '').strip().rstrip('?.')
                try:
                    res = dataset_intelligence.group_by_column(target_ds_id, col_name, db_path=db_path)
                    rows = [{"group": g["group"], "count": g["count"]} for g in res.get("groups", [])]
                    return {
                        "speak": res["speak"],
                        "display": res["display"],
                        "action": "dataset_group",
                        "source": f"Dataset: {res['filename']}",
                        "source_type": "dataset",
                        "dataset_id": target_ds_id,
                        "table": {"columns": ["CATEGORY / GROUP", "RECORD COUNT"], "rows": rows},
                        "follow_ups": ["Summarise this dataset", "List all column names"]
                    }
                except ValueError as ve:
                    return {"speak": f"{ve}", "display": str(ve), "action": "dataset_group_error"}

        # 2K. Data Quality Audit
        # 2K. Data Quality Audit & Missing Data Summary
        if any(k in c_lower for k in ['what data is missing', 'what data-quality problems', 'data quality problems', 'data quality', 'quality score', 'quality audit']):
            try:
                bi_rep = context.get("current_bi_report")
                if not bi_rep and target_ds_id:
                    rep = database.get_latest_report_for_dataset(target_ds_id, db_path=db_path)
                    if rep and rep.get("report_content"):
                        bi_rep = rep.get("report_content")

                if bi_rep and bi_rep.get("data_quality"):
                    dq = bi_rep["data_quality"]
                    score = dq.get("score", 100)
                    issues = dq.get("issues", [])
                    speak_text = f"Data quality score is {score} percent with {len(issues)} issues detected."
                    return {
                        "speak": speak_text,
                        "display": f"Data Quality: {score}% ({len(issues)} anomalies)",
                        "action": "bi_quality",
                        "source": f"Dataset: {bi_rep.get('file_name', 'active')}",
                        "source_type": "dataset",
                        "issues": issues[:10],
                        "data_quality": dq,
                        "follow_ups": ["What are the missing values in each column?", "Summarise this dataset"]
                    }
                else:
                    res = dataset_intelligence.summarize_dataset(target_ds_id, db_path=db_path)
                    speak_text = f"Data quality overview for {res['filename']}: {res['missing_pct']}% missing cells and {res['duplicate_rows']} duplicate rows."
                    return {
                        "speak": speak_text,
                        "display": f"Quality: {res['missing_pct']}% missing, {res['duplicate_rows']} duplicates",
                        "action": "bi_quality",
                        "source": f"Dataset: {res['filename']}",
                        "source_type": "dataset"
                    }
            except Exception as e:
                return {"speak": f"error retrieving quality report: {e}", "display": str(e), "action": "error"}

    # =========================================================================
    # 3. EXISTING BUSINESS INTELLIGENCE REPORTS & DOSSIERS
    # =========================================================================

    if any(k in c_lower for k in ['analyze this file', 'complete report', 'bi report', 'business report', 'full report']) or (c_lower == 'report'):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            # Check latest dataset report in DB
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No business intelligence dataset has been analyzed yet. Please upload an Excel or PDF document first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        fn = bi_rep.get("file_name", "document")
        cls_name = bi_rep.get("classification", {}).get("detected_type", "General Tabular")
        q_score = bi_rep.get("data_quality", {}).get("score", "N/A")
        insights_count = len(bi_rep.get("insights", []))

        speak_text = f"Here is the intelligence synthesis for {fn}. It is classified as {cls_name} with an overall data quality score of {q_score} percent and {insights_count} analytical findings."
        return {
            "speak": speak_text,
            "display": f"REPORT: {fn} | Type: {cls_name} | Quality: {q_score}% | Insights: {insights_count}",
            "action": "bi_report_summary",
            "source": f"Report: {fn}",
            "source_type": "report",
            "report": bi_rep,
            "follow_ups": ["Explain the findings", "Highest margin products", "Summarise this dataset"]
        }

    # 3B. Highest Margin / Pricing Analysis
    if any(k in c_lower for k in ['highest margin', 'highest margins', 'which products have the highest margins', 'pricing and margins', 'profitability', 'profit margin', 'bi margin']):
        bi_rep = context.get("current_bi_report")
        if not bi_rep and context.get("active_dataset_id"):
            ds_rep = database.get_latest_report_for_dataset(context["active_dataset_id"], db_path=db_path)
            if ds_rep and "report_content" in ds_rep:
                bi_rep = ds_rep["report_content"]
        if not bi_rep:
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if bi_rep and bi_rep.get("pricing", {}).get("computed"):
            pricing = bi_rep["pricing"]
            top_p = pricing.get("highest_margin_products", [])
            avg_m = pricing.get("average_gross_margin_pct", 0)
            leader = top_p[0] if top_p else None
            if leader:
                speak_text = f"The highest gross margin product is {leader['product']} at {leader['gross_margin_pct']} percent margin. The average gross margin is {avg_m} percent."
            else:
                speak_text = f"Average gross margin is {avg_m} percent across available pricing records."

            return {
                "speak": speak_text,
                "display": f"Avg Margin: {avg_m}% | Top: {leader['product'] if leader else 'N/A'}",
                "action": "bi_pricing",
                "source": "Commercial Intelligence",
                "source_type": "report",
                "pricing": pricing,
                "follow_ups": ["Show all products", "Check inventory summary"]
            }

        return _build_catalogue_margin_response(cat_conn, context=context, db_path=db_path, source_label="Commercial Intelligence", lang=resp_lang)

    # 3C. Inventory Telemetry & Low Stock Status
    if any(k in c_lower for k in ['low stock status', 'inventory status', 'bi inventory', 'stock status']):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No dataset loaded. Please upload product inventory data first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        inv = bi_rep.get("inventory", {})
        if not inv.get("computed"):
            missing = ", ".join(inv.get("missing_fields", ["Quantity / Stock"]))
            speak_text = f"Inventory metrics cannot be computed. The required fields ({missing}) are missing from this dataset."
            return {"speak": speak_text, "display": speak_text, "action": "bi_inventory_unavailable", "source": "BI Inventory", "source_type": "report"}

        low_items = inv.get("low_stock_items", [])
        total_units = inv.get("total_units", 0)
        speak_text = f"Recorded inventory total is {total_units} units. {len(low_items)} items are flagged for low stock or reorder."
        return {
            "speak": speak_text,
            "display": f"Inventory: {total_units} units | {len(low_items)} low-stock alerts",
            "action": "bi_inventory",
            "source": "Inventory Analytics",
            "source_type": "report",
            "inventory": inv,
            "low_stock_items": low_items,
            "follow_ups": ["Show all products", "Which products are low in stock?"]
        }

    # 3D. Sales Trends
    if any(k in c_lower for k in ['sales trends', 'sales trend', 'revenue', 'sales revenue', 'sales analysis']):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No dataset loaded. Please upload sales records first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        sales = bi_rep.get("sales", {})
        if not sales.get("computed"):
            missing = ", ".join(sales.get("missing_fields", ["Sales Amount / Revenue"]))
            speak_text = f"Sales analytics cannot be computed. The dataset is missing required sales columns ({missing})."
            return {"speak": speak_text, "display": speak_text, "action": "bi_sales_unavailable", "source": "BI Sales", "source_type": "report"}

        rev = sales.get("total_revenue", 0)
        tx = sales.get("transaction_count", 0)
        atv = sales.get("average_transaction_value", 0)

        if sales.get("returns_tracked"):
            gross = sales.get("gross_recorded_sales", rev)
            ret_val = sales.get("returned_sales_value", 0.0)
            net = sales.get("net_sales_after_returns", rev - ret_val)
            ret_count = sales.get("returned_order_count", 0)
            ret_rate = sales.get("return_rate_pct", 0.0)
            speak_text = (
                f"Gross recorded sales are ₹{gross:,.2f} across {tx} orders. "
                f"Recorded returns account for {ret_count} orders worth ₹{ret_val:,.2f} ({ret_rate:.1f}% return rate). "
                f"Net sales after recorded returns are ₹{net:,.2f}."
            )
            display_text = f"Gross: ₹{gross:,.2f} | Returns: ₹{ret_val:,.2f} ({ret_rate:.1f}%) | Net Sales: ₹{net:,.2f}"
        else:
            speak_text = f"Total recorded sales revenue is ₹{rev:,.2f} across {tx} transactions, averaging ₹{atv:,.2f} per transaction."
            display_text = f"Revenue: ₹{rev:,.2f} | Transactions: {tx} | ATV: ₹{atv:,.2f}"

        return {
            "speak": speak_text,
            "display": display_text,
            "action": "bi_sales",
            "source": "Sales Analytics",
            "source_type": "report",
            "sales": sales
        }

    # 3D. Key Findings
    if any(k in c_lower for k in ['findings', 'top findings', 'insights', 'explain the findings', 'key findings']):
        bi_rep = context.get("current_bi_report")
        if not bi_rep:
            ds_res = database.list_datasets(page=1, page_size=1, db_path=db_path)
            latest_ds = ds_res.get("datasets") or ds_res.get("items") or []
            if latest_ds:
                rep_record = database.get_latest_report_for_dataset(latest_ds[0]["id"], db_path=db_path)
                if rep_record:
                    bi_rep = rep_record.get("report_content")

        if not bi_rep:
            msg = "No findings available. Please upload and analyze a dataset first."
            return {"speak": msg, "display": msg, "action": "bi_no_data", "source": "BI Engine", "source_type": "report"}

        insights = bi_rep.get("insights", [])
        if not insights:
            speak_text = "No anomalous or noteworthy insights were triggered by this dataset."
        else:
            first_two = [f"{i['title']}: {i['explanation']}" for i in insights[:2]]
            speak_text = "Here are the top findings: " + " Furthermore, ".join(first_two)

        return {
            "speak": speak_text,
            "display": f"Key Insights: {len(insights)} identified",
            "action": "bi_insights",
            "source": "Synthesized Insights",
            "source_type": "report",
            "insights": insights
        }

    # =========================================================================
    # 4. GENERAL ASSISTANT / PROTOCOL COMMANDS
    # =========================================================================

    now = datetime.datetime.now()

    if 'joke' in c_lower:
        joke = pyjokes.get_joke()
        return {"speak": joke, "display": joke, "action": "joke", "source": "Humor Protocol", "source_type": "system"}

    if 'time' in c_lower:
        t = now.strftime("%I:%M %p")
        return {"speak": f"the current time is {t}", "display": t, "action": "time", "source": "System Chronometer", "source_type": "system"}

    if 'date' in c_lower or 'today' in c_lower or 'day' in c_lower:
        d = now.strftime("%A, %B %d, %Y")
        return {"speak": f"today is {d}", "display": d, "action": "date", "source": "System Chronometer", "source_type": "system"}

    if any(q in c_lower for q in ['who are you', 'your name', 'what can you do', 'what is jarvis']):
        speak_text = "I am J.A.R.V.I.S., your personal AI business intelligence assistant. I manage local product catalogues, real-time stock balances, tabular dataset analytics, and executive business reports."
        return {"speak": speak_text, "display": speak_text, "action": "intro", "source": "J.A.R.V.I.S. Identity", "source_type": "system"}

    if any(q in c_lower for q in ['system', 'cpu', 'battery', 'condition', 'power']):
        usage = psutil.cpu_percent(interval=None) if hasattr(psutil, 'cpu_percent') else 15.0
        batt_str = ""
        if hasattr(psutil, 'sensors_battery'):
            b = psutil.sensors_battery()
            if b:
                batt_str = f" Battery level is at {b.percent} percent."
        speak_text = f"CPU is running at {usage} percent.{batt_str} All quantum core matrices are stable."
        return {"speak": speak_text, "display": speak_text, "action": "system", "source": "System Telemetry", "source_type": "system"}

    if 'play' in c_lower or 'youtube' in c_lower:
        search_query = c_lower.replace('play', '').replace('youtube', '').replace('a song', '').strip()
        yt_url = f"https://www.youtube.com/results?search_query={requests.utils.quote(search_query)}"
        return {"speak": f"Accessing YouTube protocols for {search_query}.", "display": f"Playing: {search_query}", "action": "youtube", "url": yt_url, "source": "Media Matrix", "source_type": "system"}

    if 'wikipedia' in c_lower:
        query = c_lower.replace('wikipedia', '').replace('search', '').replace('tell me about', '').strip()
        try:
            summary = wikipedia.summary(query, sentences=2)
            return {"speak": summary, "display": summary, "action": "wikipedia", "source": "Wikipedia Archive", "source_type": "system"}
        except Exception:
            return {"speak": f"Could not retrieve Wikipedia archives for {query}.", "display": "Topic not found or too broad.", "action": "wikipedia_error", "source": "Wikipedia", "source_type": "system"}

    if 'covid' in c_lower or 'coronavirus' in c_lower:
        req_state = c_lower.replace('covid', '').replace('in', '').replace('cases', '').replace('check', '').strip() or 'delhi'
        from state import state as state_map
        matched_state = "Delhi"
        for k, v in state_map.items():
            if k in req_state:
                matched_state = v
                break
        return {"speak": f"querying COVID telemetry for {matched_state}.", "display": f"State: {matched_state}", "action": "covid", "state": matched_state, "source": "COVID Telemetry", "source_type": "system"}

    if 'contact' in c_lower or 'phone' in c_lower:
        return {"speak": "Accessing local communications directory.", "display": "Displaying Contacts list.", "action": "contacts", "source": "Contacts Directory", "source_type": "system"}

    if 'news' in c_lower:
        return {"speak": "Loading today's top tech intelligence headlines.", "display": "News Protocol active.", "action": "news", "source": "Tech News Matrix", "source_type": "system"}

    # =========================================================================
    # 5. ORCHESTRATION & LOCAL LLM INTELLIGENCE
    # =========================================================================

    # 5A-RAG. Check if query matches indexed document intelligence with high confidence
    try:
        active_ds_id = context.get("active_dataset_id") if context else None
        doc_match = rag_engine.answer_document_query(cmd, dataset_id=active_ds_id, db_path=db_path)
        if doc_match.get("has_sufficient_evidence") and doc_match.get("confidence", 0.0) >= 0.12:
            ans = doc_match.get("answer", "")
            return {
                "speak": ans,
                "display": ans,
                "action": "document_query",
                "source": "Document Intelligence",
                "source_type": "rag",
                "has_sufficient_evidence": True,
                "citations": doc_match.get("citations", []),
                "confidence": doc_match.get("confidence", 0.0),
                "follow_ups": ["Show all products", "Check inventory summary"]
            }
    except Exception as _rag_check_err:
        logger.debug(f"Document intelligence pre-check: {_rag_check_err}")

    # 5B-1. Direct General-Knowledge Routing (Precedence 5)
    # Check if query is an open general knowledge or conversational question without business keywords
    business_indicators = [
        'product', 'stock', 'inventory', 'catalogue', 'catalog', 'margin', 'profit', 'supplier',
        'dataset', 'file', 'sheet', 'purchase', 'sale', 'selling', 'cost', 'price', 'rate',
        'invoice', 'gst', 'bhav', 'keemat', 'munafa', 'labh', 'bechne', 'khareed'
    ]
    is_general_query = (
        bool(re.search(r'^(who|what|where|when|why|how)\s+(is|was|are|were|do|does|did|can)\b', c_lower)) or
        any(w in c_lower for w in ['who is', 'who was', 'koun hai', 'kon hai', 'tell me about', 'what is the capital', 'history of'])
    ) and not any(b in c_lower for b in business_indicators)

    if is_general_query:
        health = local_llm.check_ollama_health(timeout=1.5)
        if health.get("status") == "online" and health.get("model_available"):
            chat_resp = local_llm.generate_chat_response(cmd, language=detected_lang)
            if chat_resp.get("success") and chat_resp.get("content"):
                c_text = chat_resp["content"]
                return {
                    "speak": c_text,
                    "display": c_text,
                    "action": "general_chat",
                    "source": f"Local AI ({chat_resp.get('model', 'qwen3:4b-instruct')})",
                    "source_type": "llm",
                    "inference_time_seconds": chat_resp.get("inference_time_seconds"),
                    "follow_ups": ["Show all products", "Check inventory summary"]
                }
        health_status = health.get("status")
        if health_status == "offline" or not health.get("service_running"):
            return {
                "speak": "The local AI service (Ollama) is offline. Please start Ollama at port 11434. Product catalogue, stock, and business reporting remain operational.",
                "display": "Local AI Offline (Ollama unreachable)",
                "action": "ai_service_offline",
                "source": "SARTHI Core",
                "source_type": "system",
                "follow_ups": ["Show all products", "Check inventory summary", "How many products do we have?"]
            }
        elif health_status == "model_missing" or not health.get("model_available"):
            cfg_model = health.get("configured_model", "qwen3:4b-instruct")
            return {
                "speak": f"The configured local model '{cfg_model}' is not installed in Ollama. Product catalogue and business reports remain operational.",
                "display": f"Model Missing: {cfg_model}",
                "action": "ai_model_missing",
                "source": "SARTHI Core",
                "source_type": "system",
                "follow_ups": ["Show all products", "Check inventory summary"]
            }

    # 5B-2. Natural language interpretation for complex business queries
    llm_intent_data = None
    try:
        llm_intent_data = local_llm.interpret_natural_language(cmd, context=context)
    except Exception as _llm_err:
        logger.warning(f"Error during local LLM interpretation: {_llm_err}")

    if llm_intent_data and llm_intent_data.get("intent") in local_llm.CANONICAL_INTENTS:
        intent = llm_intent_data["intent"]
        params = llm_intent_data.get("parameters", {})
        entity = llm_intent_data.get("entity", "")
        model_name = llm_intent_data.get("model", "qwen3:4b-instruct")
        resp_lang = llm_intent_data.get("response_language") or detected_lang

        if intent == "general_knowledge":
            direct_ans = llm_intent_data.get("direct_response") or ""
            if not direct_ans:
                chat_resp = local_llm.generate_chat_response(cmd, language=resp_lang)
                if chat_resp.get("success") and chat_resp.get("content"):
                    direct_ans = chat_resp["content"]
                else:
                    direct_ans = f"I processed your query: '{cmd}'."
            return {
                "speak": direct_ans,
                "display": direct_ans,
                "action": "general_chat",
                "source": f"Local AI ({model_name})",
                "source_type": "llm",
                "inference_time_seconds": llm_intent_data.get("inference_time_seconds"),
                "follow_ups": ["Show all products", "Check inventory summary", "What is gross margin?"]
            }

        elif intent == "product_list":
            return _build_product_list_response(cat_conn, source_label="Product Catalogue", lang=resp_lang)

        elif intent == "product_count":
            return _build_product_count_response(cat_conn, source_label="Product Catalogue", lang=resp_lang)

        elif intent == "product_verify":
            return _build_product_verify_response(cat_conn, source_label="Catalogue Audit", lang=resp_lang)

        elif intent == "inventory_summary":
            return _build_inventory_summary_response(cat_conn, source_label="Inventory Ledger", lang=resp_lang)

        elif intent == "lowest_stock_products":
            return _build_lowest_stock_response(cat_conn, source_label="Inventory Ledger", lang=resp_lang)

        elif intent == "cheapest_product":
            return _build_contextual_pricing_response(cat_conn, mode="cheapest", source_label="Product Catalogue", lang=resp_lang)

        elif intent == "expensive_product":
            return _build_contextual_pricing_response(cat_conn, mode="expensive", source_label="Product Catalogue", lang=resp_lang)

        elif intent == "low_stock_products":
            return _build_low_stock_response(cat_conn, source_label="Inventory Ledger", lang=resp_lang, db_path=db_path)

        elif intent == "out_of_stock_products":
            return _build_out_of_stock_response(cat_conn, source_label="Inventory Ledger", lang=resp_lang, db_path=db_path)

        elif intent == "product_stock":
            target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
            if target and target.lower() not in ("product", "general", "none"):
                return _build_stock_response(target, cat_conn, source_label="Inventory Balance", lang=resp_lang, db_path=db_path)
            else:
                return _build_inventory_summary_response(cat_conn, source_label="Inventory Ledger", lang=resp_lang)

        elif intent == "products_without_price":
            return _build_no_price_response(cat_conn, source_label="Product Catalogue")

        elif intent in ("product_price", "product_cost"):
            target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
            if target and target.lower() not in ("product", "general", "none"):
                op = str(params.get("operation") or llm_intent_data.get("operation") or "").lower()
                if any(w in c_lower for w in ['purchase', 'cost', 'buy']) or 'purchase' in op or 'cost' in op:
                    return _build_purchase_cost_response(target, cat_conn, source_label="Product Catalogue")
                return _build_selling_price_response(target, cat_conn, source_label="Product Catalogue", lang=resp_lang)

        elif intent in ("product_margin", "product_profit"):
            target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
            cost_basis = params.get("cost_basis", "purchase_price")
            intent_type = "profit" if (intent == "product_profit" or any(w in c_lower for w in ['profit', 'munafa', 'labh', 'मुनाफा', 'लाभ', 'bechne', 'selling'])) else "margin"
            return _build_product_margin_response(
                target, cat_conn, source_label="Profitability Analysis",
                lang=resp_lang, db_path=db_path,
                intent_type=intent_type, cost_basis=cost_basis, session_id=session_id
            )

        elif intent == "catalogue_margin":
            return _build_catalogue_margin_response(cat_conn, context=context, db_path=db_path, source_label="Profitability Analysis", lang=resp_lang)

        elif intent == "product_search":
            target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
            if target and target.lower() not in ("product", "general", "none"):
                return _build_find_product_response(target, cat_conn, source_label="Product Catalogue")

        elif intent == "supplier_lookup":
            target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
            if params.get("list_all") or not target or str(target).lower() in ("all", "suppliers", "general", "none"):
                return _build_supplier_response(None, cat_conn, source_label="Supplier Ledger", lang=resp_lang, db_path=db_path)
            return _build_supplier_response(str(target), cat_conn, source_label="Supplier Ledger", lang=resp_lang, db_path=db_path)

        elif intent == "bi_inventory":
            return _handle_bi_inventory(context, db_path)

        elif intent == "explanation":
            lang = params.get("language") or ("Hindi" if "hindi" in c_lower else ("Hinglish" if resp_lang == "hinglish" else "English"))
            concept = params.get("concept") or entity or cmd
            expl = local_llm.generate_explanation(concept, language=lang)
            if expl.get("success"):
                return {
                    "speak": expl["content"],
                    "display": expl["content"],
                    "action": "llm_explanation",
                    "source": f"Local AI ({model_name})",
                    "source_type": "llm",
                    "explanation": expl["content"],
                    "concept": concept,
                    "language": lang,
                    "inference_time_seconds": expl.get("inference_time_seconds"),
                    "follow_ups": ["Show all products", "How many products do we have?"]
                }

        elif intent == "purchase_rate_history":
            target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
            return _build_purchase_rate_history_response(target, cat_conn, source_label="Procurement Ledger", lang=resp_lang, db_path=db_path)

        elif intent == "margin_rankings":
            ranking = params.get("ranking", "highest")
            return _build_margin_rankings_response(ranking=ranking, cat_conn=cat_conn, source_label="Profitability Analysis", lang=resp_lang, db_path=db_path)

        elif intent == "sales_comparison":
            return _build_sales_comparison_response(cat_conn, source_label="Sales Performance", lang=resp_lang, db_path=db_path)

        elif intent == "purchases_list":
            time_info = parse_time_range(cmd)
            p_dict = {**params, **time_info}
            return _build_purchases_list_response(p_dict, cat_conn, source_label="Procurement Ledger", lang=resp_lang, db_path=db_path)

        elif intent == "sales_list":
            time_info = parse_time_range(cmd)
            s_dict = {**params, **time_info}
            return _build_sales_list_response(s_dict, cat_conn, source_label="Sales Ledger", lang=resp_lang, db_path=db_path)

        elif intent == "inventory_movements":
            target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
            return _build_inventory_movements_response(target, cat_conn, source_label="Stock Ledger", lang=resp_lang, db_path=db_path)

        elif intent == "product_details":
            target = params.get("target_name") or params.get("product_name") or params.get("name") or params.get("sku") or entity
            return _build_product_details_response(target, cat_conn, source_label="Product Catalogue", lang=resp_lang, db_path=db_path)

        elif intent == "out_of_scope":
            return _build_out_of_scope_response(cmd, lang=resp_lang)

    # 5C. Check if local Ollama LLM can generate a dynamic conversational response
    chat_resp = {}
    try:
        chat_resp = local_llm.generate_chat_response(cmd, language=detected_lang)
    except Exception as _chat_err:
        logger.warning(f"Error during local LLM chat response: {_chat_err}")

    if chat_resp.get("success") and chat_resp.get("content"):
        c_text = chat_resp["content"]
        return {
            "speak": c_text,
            "display": c_text,
            "action": "general_chat",
            "source": f"Local AI ({chat_resp.get('model', 'qwen')})",
            "source_type": "llm",
            "inference_time_seconds": chat_resp.get("inference_time_seconds"),
            "follow_ups": ["Saare products dikhao", "What is gross margin?", "Check inventory summary"]
        }

    # 5D. Model Availability Diagnostics & Truthful Error Responses (Rule 3)
    health = local_llm.check_ollama_health(timeout=1.5)
    health_status = health.get("status")

    if health_status == "offline" or not health.get("service_running"):
        return {
            "speak": "The local AI service (Ollama) is offline. Please start Ollama at port 11434. Product catalogue, stock, and business reporting remain operational.",
            "display": "Local AI Offline (Ollama unreachable)",
            "action": "ai_service_offline",
            "source": "SARTHI Core",
            "source_type": "system",
            "follow_ups": ["Show all products", "Check inventory summary", "How many products do we have?"]
        }
    elif health_status == "model_missing" or not health.get("model_available"):
        cfg_model = health.get("configured_model", "qwen3:4b-instruct")
        return {
            "speak": f"The configured local model '{cfg_model}' is not installed in Ollama. Product catalogue and business reports remain operational.",
            "display": f"Model Missing: {cfg_model}",
            "action": "ai_model_missing",
            "source": "SARTHI Core",
            "source_type": "system",
            "follow_ups": ["Show all products", "Check inventory summary"]
        }
    elif health_status == "timeout":
        return {
            "speak": "Local AI model inference timed out. Please try again or query catalogue and reports.",
            "display": "Inference Timeout",
            "action": "ai_timeout",
            "source": "SARTHI Core",
            "source_type": "system",
            "follow_ups": ["Show all products", "Check inventory summary"]
        }

    # 5E. Safe Deterministic Fallback when Local LLM is Unavailable or Ambiguous
    if detected_lang == "hi":
        speak_text = (
            f"मैंने आपका अनुरोध प्राप्त किया: '{cmd}'। लोकल AI मॉडल अभी स्टैंडबाय में है। "
            f"आप कैटलॉग प्रोडक्ट्स, कीमतें, स्टॉक बैलेंस या व्यावसायिक रिपोर्ट्स की जानकारी ले सकते हैं।"
        )
        display_text = f"आदेश स्टैंडबाय: '{cmd}'"
        follow_ups = ["सारे प्रोडक्ट्स दिखाओ", "इन्वेंटरी सारांश दिखाओ", "स्टॉक कितना है?"]
    elif detected_lang == "hinglish":
        speak_text = (
            f"Maine aapka request note kiya: '{cmd}'. Local AI abhi standby mode mein hai. "
            f"Aap catalogue products, pricing, stock levels ya reports check kar sakte hain."
        )
        display_text = f"Order Standby: '{cmd}'"
        follow_ups = ["Saare products dikhao", "Current stock batao", "Capacitor ka stock kitna hai?"]
    else:
        speak_text = (
            f"I processed your query: '{cmd}'. You can check catalogue products, stock, pricing, and business reports."
        )
        display_text = f"Standby: '{cmd}'"
        follow_ups = [
            "What are all products?",
            "Which products are low in stock?",
            "Summarise this dataset",
            "What is gross margin?"
        ]

    return {
        "speak": speak_text,
        "display": display_text,
        "action": "assistant_help",
        "source": "SARTHI Core",
        "source_type": "system",
        "follow_ups": follow_ups
    }


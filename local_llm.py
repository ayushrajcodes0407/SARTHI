"""
VANTIQ: AI-Powered Business Intelligence Assistant — Local LLM Service Module
Module: local_llm.py

Description:
    Integrates a free, 100% local Large Language Model via Ollama (qwen3:4b-instruct).
    Features:
    - Zero paid APIs, zero subscriptions, zero cloud AI calls, zero external tracking.
    - Strictly bound to localhost (127.0.0.1:11434).
    - Robust health checks determining if Ollama is running and model is available.
    - Natural language intent interpretation into strictly validated JSON schemas.
    - Zero data hallucinations: database facts, prices, stocks, and dataset metrics
      are always retrieved deterministically by Python/SQLite.
    - Educational / multilingual explanation support (e.g., Hindi, English, etc.).
    - Graceful fallback when Ollama is offline or times out.
"""

import os
import re
import json
import time
import logging
from typing import Dict, List, Any, Optional, Tuple
import requests

logger = logging.getLogger("VANTIQ-LocalLLM")

# Configuration defaults & Supported Models
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:4b-instruct"
ALTERNATIVE_OLLAMA_MODEL = "gemma4:e2b"
SUPPORTED_MODELS = [
    "qwen3:4b-instruct",
    "gemma4:e2b"
]
DEFAULT_OLLAMA_TIMEOUT = 45.0
_ACTIVE_MODEL: Optional[str] = None


def get_active_model() -> str:
    """Retrieves current active local LLM model name."""
    global _ACTIVE_MODEL
    if _ACTIVE_MODEL:
        return _ACTIVE_MODEL
    return os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def get_fallback_model(primary: Optional[str] = None) -> str:
    """Returns the alternate fallback model corresponding to the primary model."""
    p = (primary or get_active_model()).lower()
    if "gemma" in p:
        return DEFAULT_OLLAMA_MODEL
    return ALTERNATIVE_OLLAMA_MODEL


def unload_model(model_name: str, base_url: Optional[str] = None, timeout: float = 5.0) -> bool:
    """
    Unloads a model from RAM by sending keep_alive: 0 to Ollama /api/generate.
    Prevents memory contention and simultaneous model loading in RAM.
    """
    cfg = get_ollama_config()
    target_url = (base_url or cfg["base_url"]).rstrip("/")
    try:
        resp = requests.post(
            f"{target_url}/api/generate",
            json={"model": model_name, "keep_alive": 0},
            timeout=timeout
        )
        logger.info(f"Unloaded model '{model_name}' from RAM: HTTP {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Could not unload model '{model_name}': {e}")
        return False


def set_active_model(model_name: str, unload_previous: bool = True) -> Tuple[bool, str]:
    """
    Selects the active local LLM at runtime without changing business logic.
    If unload_previous is True, triggers RAM unloading of the displaced model.
    """
    global _ACTIVE_MODEL, _HEALTH_CACHE
    if not model_name or not isinstance(model_name, str):
        return False, "Model name must be a non-empty string"

    cleaned_name = model_name.strip()
    prev = get_active_model()

    health = check_ollama_health(model=cleaned_name, force=True)
    if not health.get("service_running"):
        return False, f"Ollama service unreachable on loopback at {health.get('base_url')}."

    available = health.get("available_models", [])
    found = any(cleaned_name.lower() in m.lower() or m.lower().startswith(cleaned_name.lower().split(':')[0]) for m in available)
    if not found and available:
        return False, f"Model '{cleaned_name}' is not installed in local Ollama. Available: {available}"

    if unload_previous and prev != cleaned_name:
        unload_model(prev)

    _ACTIVE_MODEL = cleaned_name
    _HEALTH_CACHE = {"result": None, "timestamp": 0.0, "ttl": 3.0}
    return True, f"Active model set to '{cleaned_name}'."

# Allowlist of canonical intents
CANONICAL_INTENTS = {
    "product_list",
    "product_count",
    "product_search",
    "product_stock",
    "product_verify",
    "products_without_price",
    "inventory_summary",
    "low_stock_products",
    "out_of_stock_products",
    "lowest_stock_products",
    "product_price",
    "product_profit",
    "product_margin",
    "catalogue_margin",
    "supplier_lookup",
    "cheapest_product",
    "expensive_product",
    "identity",
    "capabilities",
    "greeting",
    "acknowledgement",
    "follow_up",
    "general_knowledge",
    "dataset_summary",
    "dataset_dimensions",
    "dataset_missing_values",
    "dataset_columns",
    "dataset_duplicates",
    "dataset_head",
    "dataset_stats",
    "dataset_filter",
    "dataset_group",
    "dataset_dates",
    "business_insights",
    "bi_pricing",
    "bi_sales",
    "bi_inventory",
    "explanation",
    "document_query",
    "mixed_query",
    "product_details",
    "purchase_rate_history",
    "purchase_list",
    "sales_list",
    "sales_comparison",
    "inventory_movements",
    "margin_rankings",
    "out_of_scope",
    "general_query",
    "unknown"
}


def get_ollama_config() -> Dict[str, Any]:
    """Retrieves current local LLM configuration from environment variables or active runtime setting."""
    base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")
    model = get_active_model()
    try:
        timeout = float(os.environ.get("OLLAMA_TIMEOUT", DEFAULT_OLLAMA_TIMEOUT))
    except (ValueError, TypeError):
        timeout = DEFAULT_OLLAMA_TIMEOUT
    enabled = os.environ.get("OLLAMA_ENABLED", "true").lower() in ("true", "1", "yes")

    # Security check: Ensure URL points only to loopback/local address
    if not (base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")):
        logger.warning(f"Ollama base URL '{base_url}' is not a local loopback address! Resetting to local default.")
        base_url = DEFAULT_OLLAMA_BASE_URL

    return {
        "base_url": base_url,
        "model": model,
        "fallback_model": get_fallback_model(model),
        "supported_models": list(SUPPORTED_MODELS),
        "timeout": timeout,
        "enabled": enabled,
        "offline_mode": True
    }


# Health cache & active inference tracking
_HEALTH_CACHE: Dict[str, Any] = {
    "result": None,
    "timestamp": 0.0,
    "ttl": 3.0
}
_INFERENCE_IN_PROGRESS = False


def set_inference_active(active: bool):
    """Marks whether a model inference request is currently executing."""
    global _INFERENCE_IN_PROGRESS
    _INFERENCE_IN_PROGRESS = bool(active)


def check_ollama_health(base_url: Optional[str] = None, model: Optional[str] = None, timeout: float = 3.0, force: bool = False) -> Dict[str, Any]:
    """
    Performs a non-blocking health check against the local Ollama instance:
    1. Distinguishes: online, model_missing, offline, timeout, busy, error
    2. Uses lightweight TTL cache (3.0s) to avoid socket contention during rapid UI polling
    3. Detects active model inference so UI displays BUSY rather than timing out
    """
    global _HEALTH_CACHE, _INFERENCE_IN_PROGRESS

    cfg = get_ollama_config()
    target_url = (base_url or cfg["base_url"]).rstrip("/")
    target_model = model or cfg["model"]

    # Security: loopback enforcement
    if not (target_url.startswith("http://127.0.0.1") or target_url.startswith("http://localhost")):
        target_url = DEFAULT_OLLAMA_BASE_URL

    now = time.time()
    # If model is actively computing an answer, report busy without blocking on tags API
    if _INFERENCE_IN_PROGRESS:
        busy_result = {
            "status": "busy",
            "inference_in_progress": True,
            "service_running": True,
            "model_available": True,
            "configured_model": target_model,
            "base_url": target_url,
            "available_models": _HEALTH_CACHE["result"].get("available_models", [target_model]) if _HEALTH_CACHE["result"] else [target_model],
            "latency_ms": None,
            "message": f"Local AI model '{target_model}' is currently computing a response."
        }
        return busy_result

    # Return cached check if within TTL
    if not force and _HEALTH_CACHE["result"] is not None and (now - _HEALTH_CACHE["timestamp"]) < _HEALTH_CACHE["ttl"]:
        return _HEALTH_CACHE["result"]

    t0 = time.time()
    try:
        resp = requests.get(f"{target_url}/api/tags", timeout=timeout)
        latency_ms = round((time.time() - t0) * 1000, 1)

        if resp.status_code != 200:
            res = {
                "status": "error",
                "service_running": True,
                "model_available": False,
                "configured_model": target_model,
                "base_url": target_url,
                "available_models": [],
                "latency_ms": latency_ms,
                "message": f"Ollama HTTP {resp.status_code}: Service responded with error."
            }
            _HEALTH_CACHE = {"result": res, "timestamp": now, "ttl": 3.0}
            return res

        data = resp.json()
        models = [m.get("name", "") for m in data.get("models", [])]
        model_found = any(target_model.lower() in m.lower() or m.lower().startswith(target_model.lower().split(':')[0]) for m in models)

        loaded_models = []
        try:
            ps_resp = requests.get(f"{target_url}/api/ps", timeout=1.0)
            if ps_resp.status_code == 200:
                loaded_models = [m.get("name", "") for m in ps_resp.json().get("models", [])]
        except Exception:
            pass

        if model_found:
            status = "online"
            msg = f"Local Ollama online ({latency_ms}ms). Model '{target_model}' ready."
        else:
            status = "model_missing"
            msg = f"Ollama service reachable, but configured model '{target_model}' was not found in installed models."

        res = {
            "status": status,
            "service_running": True,
            "model_available": model_found,
            "configured_model": target_model,
            "active_model": target_model,
            "fallback_model": get_fallback_model(target_model),
            "supported_models": list(SUPPORTED_MODELS),
            "base_url": target_url,
            "available_models": models,
            "loaded_models": loaded_models,
            "offline_mode": True,
            "latency_ms": latency_ms,
            "message": msg
        }
        _HEALTH_CACHE = {"result": res, "timestamp": now, "ttl": 3.0}
        return res

    except requests.exceptions.ConnectionError:
        res = {
            "status": "offline",
            "service_running": False,
            "model_available": False,
            "configured_model": target_model,
            "base_url": target_url,
            "available_models": [],
            "latency_ms": None,
            "message": f"Local Ollama service is offline or not running at {target_url}."
        }
        _HEALTH_CACHE = {"result": res, "timestamp": now, "ttl": 3.0}
        return res

    except requests.exceptions.Timeout:
        res = {
            "status": "timeout",
            "service_running": False,
            "model_available": False,
            "configured_model": target_model,
            "base_url": target_url,
            "available_models": [],
            "latency_ms": None,
            "message": f"Connection to local Ollama service timed out ({timeout}s)."
        }
        _HEALTH_CACHE = {"result": res, "timestamp": now, "ttl": 1.5}
        return res

    except Exception as e:
        res = {
            "status": "error",
            "service_running": False,
            "model_available": False,
            "configured_model": target_model,
            "base_url": target_url,
            "available_models": [],
            "latency_ms": None,
            "message": f"Ollama health check error: {str(e)}"
        }
        _HEALTH_CACHE = {"result": res, "timestamp": now, "ttl": 1.5}
        return res


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Robustly extracts and parses JSON from raw model output, including markdown code blocks."""
    if not text:
        return None

    cleaned = text.strip()

    # 1. Direct parse attempt
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 2. Extract from markdown code fences: ```json ... ``` or ``` ... ```
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass

    # 3. Extract first and last curly braces
    first_brace = cleaned.find('{')
    last_brace = cleaned.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(cleaned[first_brace:last_brace + 1])
        except Exception:
            pass

    return None


def interpret_natural_language(
    query: str,
    context: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    model: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Uses the local Ollama LLM to classify user intent and extract query parameters.
    Returns validated structured dict or None on failure/unavailability.

    Structure:
    {
        "intent": str (from CANONICAL_INTENTS),
        "entity": str,
        "operation": str,
        "parameters": dict,
        "direct_response": str or None
    }
    """
    cfg = get_ollama_config()
    if not cfg["enabled"]:
        logger.debug("Local LLM is disabled via OLLAMA_ENABLED=false.")
        return None

    primary_model = model or get_active_model()
    fallback_model = get_fallback_model(primary_model)

    def _execute_interpretation(target_model: str) -> Optional[Dict[str, Any]]:
        health = check_ollama_health(base_url=cfg["base_url"], model=target_model, timeout=2.0)
        if not health["service_running"] or not health["model_available"]:
            logger.debug(f"Local LLM ({target_model}) unavailable: {health.get('message')}")
            return None

        ctx = context or {}
        active_ds = ctx.get("active_dataset_filename") or "None"

        system_prompt = (
            "You are VANTIQ Natural Language Intent Router. "
            "Your task is to interpret the user's business query into a strictly validated JSON structure.\n"
            "Allowed canonical intents:\n"
            "- product_list: list all catalogue products (e.g., 'show all products', 'saare products dikhao', 'kaun kaun se products hai')\n"
            "- product_count: count total products or inventory units (e.g., 'how many products', 'kitne products hai')\n"
            "- product_verify: audit and verify catalogue products (e.g., 'verify all the products', 'products check karo')\n"
            "- product_search: find or search product by name or SKU\n"
            "- product_stock: check stock balance of a specific product (e.g., 'stock of Capacitor', 'Capacitor ka stock kitna hai')\n"
            "- inventory_summary: general inventory and stock summary when no product name is given (e.g., 'what is current stock bro', 'current stock batao', 'stock status')\n"
            "- low_stock_products: products below reorder level or low in stock (e.g., 'low stock products', 'kam stock wale products')\n"
            "- out_of_stock_products: products with zero stock (e.g., 'out of stock products', 'kaun se products ka stock khatam ho gaya')\n"
            "- lowest_stock_products: products ordered by least stock (e.g., 'sabse kam stock kin products ka hai')\n"
            "- products_without_price: products with no selling price configured\n"
            "- product_price: get selling price or purchase cost of a specific product\n"
            "- product_profit: calculate gross profit per unit or financial profit for a specific product (e.g., 'what is the profit of Capacitor', 'Capacitor bechne par kitna profit hai')\n"
            "- product_margin: get gross margin, profit, or markup percentage for a specific product (e.g., 'margin kya hai chair me', 'chair ka margin kitna hai', 'what is the margin of chair')\n"
            "- catalogue_margin: get overall or average gross margin across the catalogue or business (e.g., 'margin kya hai', 'what is the average margin', 'highest margin product')\n"
            "- supplier_lookup: find supplier details for a product or list suppliers (e.g., 'supplier of <Product>', '<Product> ka supplier kaun hai', 'list suppliers')\n"
            "- cheapest_product: find the cheapest product from previous list (e.g., 'inmein sabse sasta kaunsa hai', 'which is cheapest')\n"
            "- expensive_product: find most expensive product from previous list\n"
            "- dataset_summary: overview/summary of active dataset\n"
            "- dataset_dimensions: row and column counts\n"
            "- dataset_missing_values: missing or null cells in each column\n"
            "- dataset_columns: list column names and types\n"
            "- dataset_duplicates: check for duplicate rows\n"
            "- dataset_head: show first rows\n"
            "- dataset_stats: average, mean, min, max of a column\n"
            "- dataset_filter: filter rows by column value\n"
            "- dataset_group: group by category/column and count\n"
            "- dataset_dates: detect date columns\n"
            "- business_insights: explain top findings or executive summary\n"
            "- bi_pricing: gross margins or profitability analysis\n"
            "- bi_inventory: dataset inventory or stock status\n"
            "- bi_sales: sales trends or revenue\n"
            "- product_details: comprehensive details, SKU, stock, price, and supplier for a product (e.g. 'show details for SKU-101', 'details of Product X')\n"
            "- purchase_rate_history: latest or last recorded purchase rate/cost for a product (e.g. 'what was the last purchase rate for Product X', 'is product ka last purchase rate kya tha')\n"
            "- purchase_list: list recorded procurement purchase transactions with date filtering (e.g. 'show purchases from last month', 'purchases this month', 'recent purchases')\n"
            "- sales_list: list recorded sales transactions (e.g. 'recent sales', 'show sales this month')\n"
            "- sales_comparison: compare sales metrics between periods (e.g. 'compare this month sales with last month')\n"
            "- inventory_movements: stock movement audit ledger (e.g. 'inventory movement history for Product X', 'show stock movements')\n"
            "- margin_rankings: ranked products by highest or lowest gross margin % (e.g. 'which products have the highest recorded margins', 'highest margin products')\n"
            "- general_knowledge: general question, person/entity lookup, or conversational query (e.g. 'Who is Narendra Modi?', 'Tell me about India', 'what is photosynthesis')\n"
            "- out_of_scope: non-business general requests outside VANTIQ scope (e.g. weather, recipes, sports scores)\n"
            "- explanation: user explicitly asks to explain a business/accounting concept or difference between terms (e.g. 'gross margin in Hindi', 'Purchase price aur selling price mein kya difference hai')\n"
            "- unknown: query not recognized\n\n"
            "Rules:\n"
            "1. Never invent fake product names, prices, or statistics. All business facts are calculated by the database.\n"
            "2. Understand queries in English, Hindi (Devanagari), and Hinglish (Hindi written in Roman script). "
            "Do NOT classify inventory/catalogue queries in Hindi/Hinglish as 'explanation'—use the correct canonical intent (e.g. product_list, product_stock, inventory_summary).\n"
            "3. Output MUST be valid JSON only with keys: intent, entity, operation, parameters, response_language, direct_response. Keep JSON compact.\n"
            "4. If the query is a general knowledge question (e.g. 'Who is Narendra Modi?'), set intent to 'general_knowledge' and provide a concise, factual 1-2 sentence answer in 'direct_response'."
        )

        user_prompt = f"User Query: \"{query}\"\nActive Dataset Context: {active_ds}\nOutput JSON:"
        req_payload = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 160,
                "top_p": 0.9
            }
        }

        call_timeout = timeout or cfg["timeout"]
        set_inference_active(True)
        try:
            t0 = time.time()
            resp = requests.post(
                f"{cfg['base_url']}/api/chat",
                json=req_payload,
                timeout=call_timeout
            )
            elapsed = round(time.time() - t0, 2)
            if resp.status_code != 200:
                logger.warning(f"Ollama chat error ({target_model}) HTTP {resp.status_code}: {resp.text[:200]}")
                return None

            result_data = resp.json()
            raw_msg = result_data.get("message", {}).get("content", "")
            parsed = _extract_json_from_text(raw_msg)
            if not parsed or not isinstance(parsed, dict):
                logger.warning(f"Failed to parse valid JSON from model {target_model}: {raw_msg[:100]}")
                return None

            intent = parsed.get("intent", "unknown").lower().strip()
            if intent not in CANONICAL_INTENTS:
                logger.warning(f"Model ({target_model}) returned non-canonical intent '{intent}'.")
                return None

            entity = str(parsed.get("entity", "general"))
            operation = str(parsed.get("operation", "query"))
            parameters = parsed.get("parameters") if isinstance(parsed.get("parameters"), dict) else {}
            response_language = str(parsed.get("response_language", "en")).lower()
            direct_response = parsed.get("direct_response")
            if direct_response and not isinstance(direct_response, str):
                direct_response = str(direct_response)

            logger.info(f"Local LLM ({target_model}) interpreted query in {elapsed}s -> intent='{intent}', entity='{entity}'")
            return {
                "intent": intent,
                "entity": entity,
                "operation": operation,
                "parameters": parameters,
                "response_language": response_language,
                "direct_response": direct_response,
                "model": target_model,
                "inference_time_seconds": elapsed,
                "source": "local_llm",
                "offline_mode": True
            }
        except requests.exceptions.Timeout:
            logger.warning(f"Local LLM ({target_model}) timed out after {call_timeout}s.")
            return None
        except requests.exceptions.ConnectionError:
            logger.warning(f"Local LLM ({target_model}) connection dropped.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling local LLM ({target_model}): {e}")
            return None
        finally:
            set_inference_active(False)

    # 1. Attempt primary model
    res = _execute_interpretation(primary_model)
    if res:
        res["fallback_triggered"] = False
        return res

    # 2. Graceful fallback to alternate model if primary failed
    if fallback_model != primary_model:
        logger.info(f"Primary model '{primary_model}' did not yield result; attempting graceful fallback to '{fallback_model}'.")
        fb_res = _execute_interpretation(fallback_model)
        if fb_res:
            fb_res["fallback_triggered"] = True
            fb_res["fallback_from"] = primary_model
            return fb_res

    return None


# Deterministic fallback explanations for core accounting & financial terms
FALLBACK_ACCOUNTING_KNOWLEDGE = {
    "purchase price aur selling price": {
        "Hindi": "लागत मूल्य (Purchase Price) वह दर है जिस पर आप सामान सप्लायर से खरीदते हैं, जबकि विक्रय मूल्य (Selling Price) वह दर है जिस पर आप ग्राहक को बेचते हैं। उदाहरण: यदि आपने कोई वस्तु ₹100 में खरीदी और ₹140 में बेची, तो खरीद मूल्य ₹100 और विक्रय मूल्य ₹140 है, जिससे ₹40 का सकल लाभ हुआ।",
        "Hinglish": "Purchase price (cost price) wo rate hai jispar aap item khareedte hain, aur selling price wo rate hai jispar aap customer ko bechte hain. Example: Agar aapne ek item ₹100 mein khareeda aur ₹140 mein becha, to purchase cost ₹100 hai, selling price ₹140 hai, aur ₹40 aapka profit hai.",
        "English": "Purchase price is the cost incurred to acquire goods from a supplier, whereas selling price is the price charged to customers. Example: Buying an item for ₹100 and selling it for ₹140 yields ₹40 gross profit."
    },
    "gross margin aur markup": {
        "Hindi": "सकल मार्जिन (Gross Margin) विक्रय मूल्य पर लाभ का प्रतिशत है [(विक्रय - लागत)/विक्रय × 100], जबकि मार्कअप (Markup) लागत मूल्य पर जोड़ा गया लाभ का प्रतिशत है [(विक्रय - लागत)/लागत × 100]। उदाहरण: ₹100 की लागत और ₹150 के विक्रय मूल्य पर, मार्कअप 50% है जबकि ग्रॉस मार्जिन 33.3% है।",
        "Hinglish": "Gross margin selling price par profit percentage hota hai [(Selling - Cost)/Selling × 100], jabki markup purchase cost par add kiya gaya profit percentage hota hai [(Selling - Cost)/Cost × 100]. Example: Agar cost ₹100 aur selling price ₹150 hai, to markup 50% aur gross margin 33.3% hai.",
        "English": "Gross margin is profit divided by selling price [(Price - Cost)/Price × 100], while markup is profit divided by cost [(Price - Cost)/Cost × 100]. Example: If cost is ₹100 and price is ₹150, markup is 50% while gross margin is 33.3%."
    },
    "gross margin": {
        "Hindi": "सकल मार्जिन (Gross Margin) वह प्रतिशत है जो राजस्व में से बेची गई वस्तुओं की लागत (COGS) घटाने के बाद बचता है। उदाहरण: यदि कोई वस्तु ₹100 में खरीदी और ₹150 में बेची गई, तो सकल लाभ ₹50 है और ग्रॉस मार्जिन 33.3% [(150 - 100) / 150 × 100] है।",
        "Hinglish": "Gross margin revenue ka wo percentage hai jo cost of goods sold (COGS) minus karne ke baad bachta hai. Example: Agar koi item ₹100 mein khareeda aur ₹150 mein becha gaya, to gross profit ₹50 hai aur gross margin 33.3% [(150 - 100) / 150 × 100] hai.",
        "English": "Gross margin is the percentage of revenue remaining after subtracting the cost of goods sold (COGS). Example: If you buy a product for ₹100 and sell it for ₹150, your gross profit is ₹50 and your gross margin is 33.3% [(150 - 100) / 150 × 100].",
        "French": "La marge brute représente le pourcentage de revenus restant après déduction du coût des marchandises vendues. Exemple: Achat à 100€ et vente à 150€ donne 33.3% de marge brute.",
        "Spanish": "El margen bruto representa el porcentaje de ingresos que queda tras deducir el coste de los bienes vendidos. Ejemplo: Coste 100€ y venta 150€ da un margen del 33.3%."
    },
    "reorder level": {
        "Hindi": "पुनः आदेश स्तर (Reorder Level) न्यूनतम स्टॉक सीमा है जिस पर पहुंचते ही नया माल मंगवाने का आदेश दिया जाता है ताकि स्टॉक खत्म न हो।",
        "Hinglish": "Reorder level wo minimum stock balance hai jispar naya purchase order place kiya jata hai taaki stock khatam na ho.",
        "English": "Reorder level is the minimum inventory balance that triggers a new purchase order to replenish stock before depletion.",
        "French": "Le point de commande est le niveau de stock minimum qui déclenche un réapprovisionnement.",
        "Spanish": "El punto de pedido es el nivel mínimo de existencias que activa una orden de reposición."
    },
    "markup": {
        "Hindi": "मार्कअप (Markup) लागत मूल्य पर जोड़ा गया वह प्रतिशत या राशि है जिससे वस्तु का विक्रय मूल्य तय होता है।",
        "Hinglish": "Markup purchase cost par add kiya gaya extra percentage hota hai jisse product ka final selling price decide hota hai.",
        "English": "Markup is the percentage or amount added to the cost price of goods to determine the final selling price."
    },
    "inventory turnover": {
        "Hindi": "इन्वेंटरी टर्नओवर (Inventory Turnover) यह मापता है कि एक निश्चित अवधि में स्टॉक कितनी बार बेचा और बदला गया है।",
        "Hinglish": "Inventory turnover measure karta hai ki given period mein stock kitni baar sell hokar replace hua hai.",
        "English": "Inventory turnover measures how frequently stock is sold and replaced over a given period."
    }
}


def _lookup_fallback_explanation(concept: str, language: str) -> Optional[str]:
    c_clean = concept.lower().strip()
    l_lower = (language or "en").lower()

    if "hinglish" in l_lower:
        lang_key = "Hinglish"
    elif "hindi" in l_lower or any('\u0900' <= char <= '\u097F' for char in concept):
        lang_key = "Hindi"
    elif "french" in l_lower:
        lang_key = "French"
    elif "spanish" in l_lower:
        lang_key = "Spanish"
    else:
        lang_key = "English"

    # Multi-word matching
    for term, defs in FALLBACK_ACCOUNTING_KNOWLEDGE.items():
        if term in c_clean or c_clean in term or all(w in c_clean for w in term.split()):
            res = defs.get(lang_key)
            if not res and lang_key == "Hinglish":
                res = defs.get("Hindi")
            return res or defs.get("English")
    return None


def generate_explanation(
    concept_or_query: str,
    language: str = "en",
    timeout: float = 45.0,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates a localized, concise conceptual explanation (e.g. Gross Margin in Hindi)
    using the local LLM. Zero external cloud API calls.
    """
    cfg = get_ollama_config()
    primary_model = model or get_active_model()
    fallback_model = get_fallback_model(primary_model)
    kb_fallback = _lookup_fallback_explanation(concept_or_query, language)

    def _call_model(target_model: str) -> Optional[Dict[str, Any]]:
        health = check_ollama_health(base_url=cfg["base_url"], model=target_model)
        if not health["service_running"] or not health["model_available"]:
            return None

        lang_instr = f"in {language}" if language and language.lower() not in ("en", "english") else "in concise English"
        prompt = (
            f"You are SARTHI, an intelligent AI business intelligence assistant. "
            f"Explain the following business or accounting concept clearly and concisely {lang_instr} in 1-2 sentences: "
            f"\"{concept_or_query}\". "
            f"Do not invent company numbers or data. Keep it accurate and professional."
        )

        set_inference_active(True)
        try:
            t0 = time.time()
            resp = requests.post(
                f"{cfg['base_url']}/api/chat",
                json={
                    "model": target_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 120
                    }
                },
                timeout=timeout
            )
            elapsed = round(time.time() - t0, 2)
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "").strip()
                if "hindi" in language.lower() and not any('\u0900' <= c <= '\u097F' for c in content) and kb_fallback:
                    content = kb_fallback
                return {
                    "success": True,
                    "content": content,
                    "language": language,
                    "model": target_model,
                    "inference_time_seconds": elapsed,
                    "source": "local_llm",
                    "offline_mode": True
                }
            return None
        except Exception as e:
            logger.warning(f"Error generating explanation with {target_model}: {e}")
            return None
        finally:
            set_inference_active(False)

    # 1. Primary model
    res = _call_model(primary_model)
    if res:
        res["fallback_triggered"] = False
        return res

    # 2. Fallback model
    if fallback_model != primary_model:
        fb_res = _call_model(fallback_model)
        if fb_res:
            fb_res["fallback_triggered"] = True
            return fb_res

    # 3. Deterministic Knowledge Base Fallback
    if kb_fallback:
        return {
            "success": True,
            "content": kb_fallback,
            "language": language,
            "model": "local_knowledge_base",
            "inference_time_seconds": 0.01,
            "source": "fallback",
            "fallback_triggered": True,
            "offline_mode": True
        }

    return {
        "success": False,
        "content": f"Local AI model ({primary_model}) is currently standby or offline.",
        "language": language,
        "model": primary_model,
        "source": "fallback",
        "fallback_triggered": True,
        "offline_mode": True
    }


def generate_chat_response(
    query: str,
    language: str = "en",
    context_history: Optional[List[Dict[str, str]]] = None,
    timeout: float = 35.0,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates a conversational response using the local Ollama LLM.
    Zero cloud calls. Strictly bound to localhost.
    Returns {success: bool, content: str, source: str, model: str, status: str}
    """
    cfg = get_ollama_config()
    primary_model = model or get_active_model()
    fallback_model = get_fallback_model(primary_model)

    lang_guidance = (
        "Respond in natural Hindi (Devanagari script)." if language == "hi"
        else ("Respond in natural conversational Hinglish (Hindi words written in English/Latin script)." if language == "hinglish"
              else "Respond in clear, professional English.")
    )

    sys_prompt = (
        f"You are SARTHI, a professional AI business intelligence assistant. "
        f"{lang_guidance} "
        f"Keep responses concise (1-3 sentences), polite, direct, and helpful. "
        f"Never address the user as 'Boss', 'Bro', or use informal slang. "
        f"Never invent fictional company records, stock figures, or customer records."
    )

    messages = [{"role": "system", "content": sys_prompt}]
    if context_history:
        for turn in context_history[-3:]:
            if turn.get("user"):
                messages.append({"role": "user", "content": turn["user"]})
            if turn.get("assistant"):
                messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": query})

    def _call_chat(target_model: str) -> Optional[Dict[str, Any]]:
        health = check_ollama_health(base_url=cfg["base_url"], model=target_model, timeout=2.5)
        if not health["service_running"] or not health["model_available"]:
            return None

        set_inference_active(True)
        try:
            t0 = time.time()
            resp = requests.post(
                f"{cfg['base_url']}/api/chat",
                json={
                    "model": target_model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 150
                    }
                },
                timeout=timeout
            )
            elapsed = round(time.time() - t0, 2)
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "").strip()
                return {
                    "success": True,
                    "status": "online",
                    "content": content,
                    "source": "local_llm",
                    "model": target_model,
                    "inference_time_seconds": elapsed,
                    "offline_mode": True
                }
            return None
        except Exception as e:
            logger.warning(f"Error calling {target_model} in generate_chat_response: {e}")
            return None
        finally:
            set_inference_active(False)

    # 1. Try primary model
    res = _call_chat(primary_model)
    if res:
        res["fallback_triggered"] = False
        return res

    # 2. Try fallback model
    if fallback_model != primary_model:
        fb_res = _call_chat(fallback_model)
        if fb_res:
            fb_res["fallback_triggered"] = True
            return fb_res

    # Check health for diagnostic message
    health = check_ollama_health(base_url=cfg["base_url"], model=primary_model, timeout=2.0)
    if not health["service_running"]:
        return {
            "success": False,
            "status": "offline",
            "content": f"Local AI service (Ollama) is offline or not running at {cfg['base_url']}.",
            "source": "error",
            "model": primary_model,
            "offline_mode": True,
            "fallback_triggered": True
        }
    if not health["model_available"]:
        return {
            "success": False,
            "status": "model_missing",
            "content": f"Configured model '{primary_model}' is not installed in local Ollama.",
            "source": "error",
            "model": primary_model,
            "offline_mode": True,
            "fallback_triggered": True
        }

    return {
        "success": False,
        "status": "error",
        "content": f"Local inference failed for '{primary_model}'.",
        "source": "error",
        "model": primary_model,
        "offline_mode": True,
        "fallback_triggered": True
    }


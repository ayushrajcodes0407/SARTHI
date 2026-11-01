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
DEFAULT_OLLAMA_MODEL = "gemma4:e2b"
ALTERNATIVE_OLLAMA_MODEL = "qwen3:4b-instruct"
SUPPORTED_MODELS = [
    "gemma4:e2b",
    "qwen3:4b-instruct"
]
DEFAULT_OLLAMA_TIMEOUT = 45.0
DEFAULT_KEEP_ALIVE = "10m"
DEFAULT_CPU_THREADS = 6
DEFAULT_CONTEXT_WINDOW = 1536
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
        return "qwen3:4b-instruct"
    return "gemma4:e2b"


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
            "You are SARTHI Natural Language Intent Router. Output strictly valid JSON only: "
            "{\"intent\": str, \"entity\": str, \"operation\": str, \"parameters\": dict, \"direct_response\": str or null}.\n"
            "Allowed canonical intents: product_list, product_count, product_search, product_stock, product_price, "
            "product_profit, product_margin, catalogue_margin, supplier_lookup, cheapest_product, expensive_product, "
            "inventory_summary, low_stock_products, out_of_stock_products, dataset_summary, dataset_dimensions, "
            "dataset_columns, dataset_stats, dataset_filter, dataset_group, business_insights, bi_pricing, bi_inventory, "
            "bi_sales, general_knowledge, explanation, unknown.\n"
            "Rules:\n"
            "1. Output valid JSON ONLY. No markdown, no commentary.\n"
            "2. Never fabricate numerical business facts or prices.\n"
            "3. For general knowledge queries (e.g. 'Who is Narendra Modi?'), set intent to 'general_knowledge' and provide a concise 1-2 sentence answer in 'direct_response'."
        )

        user_prompt = f"User Query: \"{query}\"\nActive Dataset Context: {active_ds}\nOutput JSON:"
        req_payload = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "format": "json",
            "stream": False,
            "keep_alive": DEFAULT_KEEP_ALIVE,
            "options": {
                "temperature": 0.1,
                "num_predict": 320 if "gemma" in target_model.lower() else 180,
                "num_ctx": DEFAULT_CONTEXT_WINDOW,
                "num_thread": DEFAULT_CPU_THREADS,
                "top_p": 0.9,
                "stop": ["\n\n\n", "User Query:", "<end_of_turn>"]
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
            if not parsed and result_data.get("message", {}).get("thinking"):
                th = result_data["message"]["thinking"]
                parsed = _extract_json_from_text(th)
                if not parsed:
                    # Fallback pattern extraction from thinking
                    m_int = re.search(r'intent["\s:]+([a-zA-Z_]+)', th, re.IGNORECASE)
                    m_ent = re.search(r'entity["\s:]+([a-zA-Z0-9_\s]+)', th, re.IGNORECASE)
                    if m_int:
                        parsed = {
                            "intent": m_int.group(1).lower().strip(),
                            "entity": m_ent.group(1).strip() if m_ent else "general"
                        }
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

    # 2. Graceful fallback to alternate model ONLY if primary failed genuinely
    if fallback_model != primary_model:
        logger.warning(f"Primary model '{primary_model}' did not yield valid result; unloading from RAM and falling back to '{fallback_model}'.")
        unload_model(primary_model)
        fb_res = _execute_interpretation(fallback_model)
        if fb_res:
            fb_res["fallback_triggered"] = True
            fb_res["fallback_from"] = primary_model
            unload_model(fallback_model)
            return fb_res
        unload_model(fallback_model)

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


def _clean_thinking_text(thinking_text: str) -> str:
    if not thinking_text:
        return ""
    th = thinking_text.strip()
    cleaned = re.sub(r'^(?:Thinking Process:?|\*\*.*?\*\*|\d+\.\s+.*?:?)\s*', '', th, flags=re.MULTILINE).strip()
    paragraphs = [p.strip() for p in cleaned.split("\n\n") if len(p.strip()) >= 20]
    if paragraphs:
        return paragraphs[-1]
    if len(cleaned) >= 20:
        return cleaned
    return ""


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


REASONING_LEAKAGE_PATTERNS = [
    r'analyze the request',
    r'determine persona',
    r'identify the persona',
    r'core content',
    r'draft the response',
    r'drafting sentence',
    r'review against constraints',
    r'thinking process',
    r'let me think',
    r'internal planning',
    r'deconstruct the request',
    r'user prompt\s*:',
    r'system prompt\s*:',
    r'here\'s a thinking process',
    r'final review against constraints',
    r'<\s*think\s*>',
    r'<\s*/\s*think\s*>',
    r'step 1:\s*analyze',
    r'step 2:\s*draft'
]

def is_internal_reasoning_leaked(text: str) -> bool:
    if not text:
        return False
    t_lower = text.lower()
    return any(re.search(pat, t_lower) for pat in REASONING_LEAKAGE_PATTERNS)

def clean_or_recover_response(text: str, query: str = "", language: str = "en") -> str:
    """
    Validates and cleans user-facing LLM text.
    If internal reasoning leakage is detected, attempts safe extraction or returns
    a professional, direct response without exposing internal traces.
    """
    if not text:
        text = ""
    # 1. If text has <think>...</think>, strip the thinking block
    cleaned = re.sub(r'<\s*think\s*>.*?<\s*/\s*think\s*>', '', text, flags=re.DOTALL).strip()
    if cleaned and not is_internal_reasoning_leaked(cleaned) and len(cleaned) >= 15:
        return cleaned

    # 2. Check if a clean user-facing sentence is embedded after the thinking steps
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    valid_paras = [p for p in paragraphs if not is_internal_reasoning_leaked(p) and len(p) >= 20 and not p.startswith(('*', '-', '#', '1.', '2.', '3.'))]
    if valid_paras:
        return valid_paras[-1]

    # 3. If query matches a known concept, use fallback knowledge
    if query:
        fb = _lookup_fallback_explanation(query, language)
        if fb:
            return fb

    # 4. Safe direct general knowledge fallbacks for standard entities
    q_low = query.lower() if query else ""
    if "cricket" in q_low:
        if "hindi" in (language or "").lower() or language == "hi":
            return "क्रिकेट एक लोकप्रिय बल्ले और गेंद का खेल है जो 11-11 खिलाड़ियों की दो टीमों के बीच खेला जाता है।"
        elif (language or "").lower() == "hinglish":
            return "Cricket ek popular bat-and-ball sport hai jo 11 players ki do teams ke beech khela jaata hai."
        else:
            return "Cricket is a popular bat-and-ball sport played between two teams of eleven players on a field with a 22-yard pitch."
    elif "narendra modi" in q_low or "modi" in q_low:
        if "hindi" in (language or "").lower() or language == "hi":
            return "नरेंद्र मोदी भारत के वर्तमान और 14वें प्रधानमंत्री हैं, जो 2014 से इस पद पर कार्यरत हैं।"
        elif (language or "").lower() == "hinglish":
            return "Narendra Modi Bharat ke current Prime Minister hain, jo 2014 se is pad par karyarat hain."
        else:
            return "Narendra Modi is the current Prime Minister of India, having served in the office since May 2014."
    elif "artificial intelligence" in q_low or "ai" in q_low.split():
        if "hindi" in (language or "").lower() or language == "hi":
            return "आर्टिफिशियल इंटेलिजेंस (AI) कंप्यूटर साइंस की वह शाखा है जो मशीनों को इंसानों की तरह सोचने, सीखने और समस्याओं को हल करने में सक्षम बनाती है।"
        elif (language or "").lower() == "hinglish":
            return "Artificial Intelligence (AI) computer science ki aisi branch hai jo machines ko insano ki tarah sochna aur learn karna sikhati hai."
        else:
            return "Artificial Intelligence (AI) is a branch of computer science focused on building smart machines capable of performing tasks that typically require human intelligence."

    return "I am SARTHI, your AI business intelligence assistant. How may I assist you with your business catalogue, stock inventory, or analytics today?"


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
                    "keep_alive": DEFAULT_KEEP_ALIVE,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 320,
                        "num_ctx": DEFAULT_CONTEXT_WINDOW,
                        "num_thread": DEFAULT_CPU_THREADS,
                        "top_p": 0.9,
                        "stop": ["User:", "<end_of_turn>"]
                    }
                },
                timeout=timeout
            )
            elapsed = round(time.time() - t0, 2)
            if resp.status_code == 200:
                msg_obj = resp.json().get("message", {})
                content = (msg_obj.get("content") or "").strip()
                if not content or len(content) < 15 or is_internal_reasoning_leaked(content):
                    if kb_fallback:
                        content = kb_fallback
                    else:
                        content = clean_or_recover_response(content, query=concept_or_query, language=language)
                if "hindi" in language.lower() and not any('\u0900' <= c <= '\u097F' for c in content) and kb_fallback:
                    content = kb_fallback
                if content and len(content) >= 15 and not is_internal_reasoning_leaked(content):
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
        logger.warning(f"Primary model '{primary_model}' failed for explanation; unloading and falling back to '{fallback_model}'.")
        unload_model(primary_model)
        fb_res = _call_model(fallback_model)
        if fb_res:
            fb_res["fallback_triggered"] = True
            unload_model(fallback_model)
            return fb_res
        unload_model(fallback_model)

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
        f"You are SARTHI, an intelligent AI business intelligence assistant. "
        f"{lang_guidance} "
        f"Keep responses concise (1-3 sentences), polite, direct, and helpful. "
        f"Provide ONLY the direct, user-facing final answer. "
        f"Do NOT output internal reasoning, thought process, planning steps, or analysis. "
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
                    "keep_alive": DEFAULT_KEEP_ALIVE,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 400 if "gemma" in target_model.lower() else 220,
                        "num_ctx": DEFAULT_CONTEXT_WINDOW,
                        "num_thread": DEFAULT_CPU_THREADS,
                        "top_p": 0.9,
                        "stop": ["User:", "User Query:", "<end_of_turn>"]
                    }
                },
                timeout=timeout
            )
            elapsed = round(time.time() - t0, 2)
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message", {})
                content = (msg.get("content") or "").strip()
                
                # STRICT REASONING ISOLATION: Never substitute thinking for user-facing content
                if is_internal_reasoning_leaked(content):
                    logger.warning(f"Detected internal reasoning leakage in {target_model} response. Rejecting candidate.")
                    content = ""
                
                if not content or len(content) < 10:
                    # Attempt a controlled retry with strict direct answer instruction
                    try:
                        retry_msg = [
                            {"role": "system", "content": "You are SARTHI. Provide ONLY the direct final answer in 1-2 concise sentences. Do not think or plan."},
                            {"role": "user", "content": f"Answer directly: {query}"}
                        ]
                        r_retry = requests.post(
                            f"{cfg['base_url']}/api/chat",
                            json={
                                "model": target_model,
                                "messages": retry_msg,
                                "stream": False,
                                "keep_alive": DEFAULT_KEEP_ALIVE,
                                "options": {
                                    "temperature": 0.1,
                                    "num_predict": 180,
                                    "num_ctx": DEFAULT_CONTEXT_WINDOW,
                                    "num_thread": DEFAULT_CPU_THREADS,
                                    "stop": ["User:", "<end_of_turn>"]
                                }
                            },
                            timeout=15.0
                        )
                        if r_retry.status_code == 200:
                            c_cand = (r_retry.json().get("message", {}).get("content") or "").strip()
                            if c_cand and not is_internal_reasoning_leaked(c_cand):
                                content = c_cand
                    except Exception as _retry_err:
                        logger.debug(f"Controlled retry failed: {_retry_err}")
                
                if not content or is_internal_reasoning_leaked(content):
                    content = clean_or_recover_response(content, query=query, language=language)

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
        logger.warning(f"Primary model '{primary_model}' failed for chat; unloading and falling back to '{fallback_model}'.")
        unload_model(primary_model)
        fb_res = _call_chat(fallback_model)
        if fb_res:
            fb_res["fallback_triggered"] = True
            unload_model(fallback_model)
            return fb_res
        unload_model(fallback_model)

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



def stream_chat_response(
    query: str,
    language: str = "en",
    context_history: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None
):
    """
    Generator that streams chat tokens in real time from local Ollama LLM.
    Yields string token chunks.
    """
    cfg = get_ollama_config()
    target_model = model or get_active_model()
    health = check_ollama_health(base_url=cfg["base_url"], model=target_model, timeout=2.0)
    if not health["service_running"] or not health["model_available"]:
        yield f"Local model '{target_model}' is currently offline."
        return

    lang_guidance = (
        "Respond in natural Hindi (Devanagari script)." if language == "hi"
        else ("Respond in conversational Hinglish." if language == "hinglish"
              else "Respond in clear, professional English.")
    )
    sys_prompt = f"You are SARTHI, a business intelligence assistant. {lang_guidance} Keep answer concise (1-3 sentences)."

    messages = [{"role": "system", "content": sys_prompt}]
    if context_history:
        for turn in context_history[-3:]:
            if turn.get("user"):
                messages.append({"role": "user", "content": turn["user"]})
            if turn.get("assistant"):
                messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": query})

    set_inference_active(True)
    try:
        with requests.post(
            f"{cfg['base_url']}/api/chat",
            json={
                "model": target_model,
                "messages": messages,
                "stream": True,
                "keep_alive": DEFAULT_KEEP_ALIVE,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 400 if "gemma" in target_model.lower() else 220,
                    "num_ctx": DEFAULT_CONTEXT_WINDOW,
                    "num_thread": DEFAULT_CPU_THREADS,
                    "stop": ["User:", "User Query:", "<end_of_turn>"]
                }
            },
            stream=True,
            timeout=40.0
        ) as resp:
            for line in resp.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line.decode('utf-8'))
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                    except Exception:
                        continue
    finally:
        set_inference_active(False)

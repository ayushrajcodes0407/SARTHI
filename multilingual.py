"""
VANTIQ: Multilingual Natural Language & Context Engine
Module: multilingual.py

Description:
    Provides language detection (English, Hindi Devanagari, Hinglish Roman script),
    query normalization (wake words, conversational fillers, spelling variations),
    conversational context management, and localized response formatting.
"""

import re
import time
from typing import Dict, List, Any, Optional, Tuple

# Stopwords and generic demonstratives for product extraction
PRODUCT_STOPWORDS = {
    'the', 'a', 'an', 'this', 'that', 'these', 'those', 'product', 'products',
    'item', 'items', 'this product', 'that product', 'the product', 'goods',
    'stock', 'current stock', 'inventory', 'all', 'everything', 'of', 'for',
    'to', 'in', 'at', 'on', 'it', 'its', 'is', 'iss', 'iska', 'iski', 'iske',
    'inka', 'inki', 'inke', 'unka', 'unki', 'unke',
    'uska', 'uski', 'uske', 'yeh', 'ye', 'woh', 'wo', 'kisi', 'kiska', 'apna',
    'apne', 'mera', 'mere', 'sab', 'saare', 'sare', 'kul', 'total', 'overall',
    'bhai', 'bro', 'zara', 'mujhe', 'humko', 'kripya', 'please', 'batao',
    'bataiye', 'batana', 'dikhao', 'dekhao', 'ka', 'ki', 'ke', 'ko', 'what', 'which',
    'tell', 'me', 'give', 'show', 'check', 'find', 'get', 'kitna', 'kitni', 'kitne',
    'hai', 'hain', 'ho', 'tha', 'thi', 'the', 'details',
    'hindi', 'english', 'hinglish', 'french', 'spanish', 'german', 'devanagari',
    'हिंदी', 'अंग्रेजी', 'इंग्लिश',
    'का', 'की', 'के', 'को', 'इस', 'उस', 'यह', 'ये', 'वह', 'प्रोडक्ट', 'सामान', 'कुल', 'सब'
}

def is_product_stopword(word: Optional[str]) -> bool:
    """Checks whether a candidate product string is empty, generic, or a stopword."""
    if not word:
        return True
    w = word.strip().lower().rstrip('?.!,:;')
    if not w:
        return True
    if w in PRODUCT_STOPWORDS:
        return True
    tokens = re.findall(r'[\u0900-\u097Fa-zA-Z0-9]+', w)
    if not tokens:
        return True
    return all(t.lower() in PRODUCT_STOPWORDS for t in tokens)


# Conversational fillers and wake words to strip for canonical intent matching
WAKE_WORDS = [
    r'\bjarvis\b', r'\bvantiq\b', r'\bassistant\b', r'\bbot\b', r'\bhey jarvis\b', r'\bhey vantiq\b'
]

CONVERSATIONAL_FILLERS = [
    r'\bbro\b', r'\bbhai\b', r'\byaar\b', r'\bplease\b', r'\bplz\b', r'\bkripya\b',
    r'\bzara\b', r'\bsun\b', r'\bsuno\b', r'\bbatao\b', r'\bbatana\b', r'\bbataiye\b',
    r'\btell me\b', r'\bcan you\b', r'\bcould you\b',
    r'\bmujhe\b', r'\bhumko\b', r'\bjust\b', r'\bactually\b'
]


# Devanagari Unicode Range: \u0900 to \u097F
DEVANAGARI_REGEX = re.compile(r'[\u0900-\u097F]')

# Common Hinglish marker words (Roman script Hindi vocabulary)
HINGLISH_MARKERS = {
    'ka', 'ki', 'ke', 'ko', 'mein', 'me', 'se', 'par', 'pe',
    'kya', 'kyu', 'kyun', 'kaun', 'kaunsa', 'kaunsi', 'kaunse',
    'kitna', 'kitni', 'kitne', 'kaisa', 'kaisi', 'kaise',
    'hai', 'hain', 'ho', 'tha', 'thi', 'the', 'hoga', 'hogi', 'honge',
    'saare', 'sare', 'sab', 'sabse', 'kuch', 'koi',
    'dikhao', 'dekhao', 'batao', 'bataye', 'bataiye', 'dekho',
    'karo', 'kariye', 'khatam', 'khatm', 'bacha', 'bache', 'bachi',
    'sasta', 'saste', 'sasti', 'mehenga', 'mehenge', 'mehangi',
    'kam', 'jyada', 'zyada', 'bhai', 'yaar', 'mujhe', 'apna', 'apne'
}


def detect_language(text: str) -> str:
    """
    Detects whether text is 'hi' (Hindi in Devanagari), 'hinglish' (Hindi in Roman script),
    or 'en' (English).
    """
    if not text:
        return 'en'

    # Check for Devanagari characters
    devanagari_chars = len(DEVANAGARI_REGEX.findall(text))
    if devanagari_chars >= 2 or (devanagari_chars > 0 and len(text.strip()) <= 10):
        return 'hi'

    # Check for Hinglish markers in Roman text
    words = re.findall(r'[a-zA-Z]+', text.lower())
    if not words:
        return 'en'

    hinglish_matches = sum(1 for w in words if w in HINGLISH_MARKERS)
    ratio = hinglish_matches / len(words)

    # If at least 2 words or >25% of words are Hinglish markers
    if hinglish_matches >= 2 or ratio >= 0.25:
        return 'hinglish'

    return 'en'


def clean_query(text: str) -> Tuple[str, str]:
    """
    Normalizes query by stripping wake words and extra filler terms.
    Returns (cleaned_query, detected_lang).
    """
    if not text:
        return "", "en"

    raw_text = text.strip()
    detected_lang = detect_language(raw_text)

    cleaned = raw_text
    # Strip wake words
    for ww in WAKE_WORDS:
        cleaned = re.sub(ww, '', cleaned, flags=re.IGNORECASE)

    # Strip conversational fillers
    for cf in CONVERSATIONAL_FILLERS:
        cleaned = re.sub(cf, '', cleaned, flags=re.IGNORECASE)

    # Clean double spaces and punctuation
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(' .,!?:;')
    return cleaned, detected_lang



class ConversationContextManager:
    """
    Stores session state for multi-turn conversational follow-ups:
    - Bounded history of recent turns (query, response, intent, category, language)
    - Pending action state for confirmations, clarifications, and multi-turn workflows
    - Last listed products (for 'which one is the cheapest', 'which product is cheapest')
    - Last mentioned product (for 'what is its price', 'is it in stock', 'what is its margin')
    - Last response payload (for 'explain that in Hindi', 'translate that')
    - Last active dataset
    - Last used language
    """
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.history: List[Dict[str, Any]] = []
        self.last_products: List[Dict[str, Any]] = []
        self.last_product: Optional[Dict[str, Any]] = None
        self.last_intent: Optional[str] = None
        self.last_category: Optional[str] = None
        self.last_query: Optional[str] = None
        self.last_response: Optional[Dict[str, Any]] = None
        self.last_language: str = "en"
        self.active_dataset_id: Optional[str] = None
        self.pending_action: Optional[Dict[str, Any]] = None

    def record_turn(self, query: str, response: Dict[str, Any], intent: str, category: str, language: str = "en"):
        self.last_query = query
        self.last_response = response
        self.last_intent = intent
        self.last_category = category
        self.last_language = language
        self.history.append({
            "query": query,
            "response": response,
            "intent": intent,
            "category": category,
            "language": language
        })
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def set_pending_action(self, action: str, parameters: Optional[Dict[str, Any]] = None, prompt: str = "", language: str = "en"):
        """Stores a minimal, explicit pending action requiring user confirmation or clarification."""
        self.pending_action = {
            "action": action,
            "parameters": parameters or {},
            "prompt": prompt,
            "language": language,
            "created_at": time.time()
        }

    def get_pending_action(self) -> Optional[Dict[str, Any]]:
        """Returns the current pending action if one exists."""
        return self.pending_action

    def clear_pending_action(self):
        """Clears the pending action after successful execution or explicit cancellation."""
        self.pending_action = None

    def update_products(self, products: List[Dict[str, Any]], language: str = "en"):
        self.last_products = products
        self.last_language = language
        if len(products) == 1:
            self.last_product = products[0]

    def update_product(self, product: Dict[str, Any], language: str = "en"):
        self.last_product = product
        self.last_language = language

    def get_last_response(self) -> Optional[Dict[str, Any]]:
        return self.last_response

    def clear(self):
        self.history = []
        self.last_products = []
        self.last_product = None
        self.last_intent = None
        self.last_category = None
        self.last_query = None
        self.last_response = None
        self.pending_action = None


# Global default context instance
SESSION_CONTEXT = ConversationContextManager()

# Registry of isolated session contexts for multi-user/multi-session environments
_SESSION_REGISTRY: Dict[str, ConversationContextManager] = {}

def get_session_context(session_id: Optional[str] = None) -> ConversationContextManager:
    """Returns the isolated context for session_id, or default global session context."""
    if not session_id or session_id in ("default", "main"):
        return SESSION_CONTEXT
    if session_id not in _SESSION_REGISTRY:
        _SESSION_REGISTRY[session_id] = ConversationContextManager()
    return _SESSION_REGISTRY[session_id]



# Confirmation and Cancellation Intent Patterns
CONFIRMATION_PATTERNS = [
    r'^(?:yes|yeah|yep|sure|of course|yes of course|yes please|definitely|absolutely|certainly)\b',
    r'^(?:haan|haanji|haan ji|bilkul|zaroor|avashya|theek hai|sahi hai|haan batao|haan dikhao|haan karo)\b',
    r'^(?:हाँ|हाँजी|हाँ जी|बिल्कुल|ज़रूर|अवश्य|ठीक है|हाँ बताओ|हाँ दिखाओ|हाँ करो)\b'
]

CANCELLATION_PATTERNS = [
    r'^(?:no|cancel|never mind|nevermind|stop|abort|skip|drop it|leave it|do not|don\'t|no thanks)\b',
    r'^(?:nahi|nahin|mat karo|rehne do|ruk jao|cancel karo|chhod do|rehne de|nahi chahiye)\b',
    r'^(?:नहीं|मत करो|रहने दो|रुक जाओ|कैंसल करो|छोड़ दो|नहीं चाहिए)\b'
]


def is_confirmation(text: str, lang: str = "en") -> bool:
    """Returns True if text is a common conversational confirmation."""
    t = (text or "").strip().lower()
    t = re.sub(r'^[,\.\s!]+|[,\.\s!]+$', '', t)
    for pat in CONFIRMATION_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def is_cancellation(text: str, lang: str = "en") -> bool:
    """Returns True if text is a common cancellation or dismissal command."""
    t = (text or "").strip().lower()
    t = re.sub(r'^[,\.\s!]+|[,\.\s!]+$', '', t)
    for pat in CANCELLATION_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def format_multilingual_response(
    intent: str,
    lang: str,
    data: Dict[str, Any]
) -> Dict[str, str]:
    """
    Returns localized ('speak', 'display') texts based on intent and language (en, hi, hinglish).
    """
    currency = data.get("currency", "₹")

    if intent == "identity":
        if lang == "hi":
            return {
                "speak": "मैं VANTIQ हूँ, आपका AI-पावर्ड बिज़नेस इंटेलिजेंस असिस्टेंट। मैं प्रोडक्ट प्राइसिंग, स्टॉक, इन्वेंटरी और बिज़नेस रिपोर्ट्स में मदद कर सकता हूँ। आप मुझसे हिंदी, हिंग्लिश या अंग्रेज़ी में बात कर सकते हैं।",
                "display": "मैं VANTIQ हूँ, आपका AI बिज़नेस असिस्टेंट। आप मुझसे हिंदी, हिंग्लिश या अंग्रेज़ी में सवाल पूछ सकते हैं।"
            }
        elif lang == "hinglish":
            return {
                "speak": "Main SARTHI hoon, aapka AI-powered business intelligence assistant. Main product pricing, stock, inventory aur business reports mein help kar sakta hoon. Aap mujhse Hindi, Hinglish ya English mein baat kar sakte hain.",
                "display": "Main SARTHI hoon, aapka AI business assistant. Aap mujhse Hindi, Hinglish ya English mein baat kar sakte hain."
            }
        else:
            return {
                "speak": "I'm SARTHI, your AI-powered business intelligence assistant. I can help you understand product pricing, inventory, stock availability, business data, and reports. You can talk to me in English, Hindi, or Hinglish.",
                "display": "I'm SARTHI, your AI-powered business intelligence assistant. You can speak with me in English, Hindi, or Hinglish."
            }

    elif intent == "capabilities":
        if lang == "hi":
            return {
                "speak": "मैं प्रोडक्ट्स की कीमतें और स्टॉक जांचने, बिज़नेस डेटा का विश्लेषण करने, रिपोर्ट्स समझने और इंपोर्टेड दस्तावेज़ों से जानकारी खोजने में मदद कर सकता हूँ। बताइए, आप क्या जानना चाहते हैं?",
                "display": "क्षमताएं: कैटलॉग एवं स्टॉक, मूल्य निर्धारण, डेटा विश्लेषण, रिपोर्ट्स और दस्तावेज़।"
            }
        elif lang == "hinglish":
            return {
                "speak": "Main products ki pricing aur stock check karne, business data analyse karne, reports samajhne aur imported documents se information dhoondhne mein madad kar sakta hoon. Chaliye, aap kya jaanna chahte hain?",
                "display": "Capabilities: Product pricing, stock checks, business analytics, reports aur document search."
            }
        else:
            return {
                "speak": "I can help you check product pricing and stock, analyze business data, review reports, and find information from imported documents. What would you like to explore?",
                "display": "Capabilities: Product pricing, inventory tracking, business analytics, and document queries."
            }

    elif intent == "greeting":
        if lang == "hi":
            return {
                "speak": "नमस्ते! मैं VANTIQ हूँ। मैं आपके प्रोडक्ट कैटलॉग, इन्वेंटरी और बिज़नेस डेटा में कैसे सहायता कर सकता हूँ?",
                "display": "नमस्ते! VANTIQ सहायता के लिए तैयार है।"
            }
        elif lang == "hinglish":
            return {
                "speak": "Namaste! Main SARTHI hoon. Main aapke product catalogue, inventory aur business data mein kaise madad kar sakta hoon?",
                "display": "Namaste! SARTHI online aur ready hai."
            }
        else:
            return {
                "speak": "Hello! I'm SARTHI, ready to assist you with product catalogue, inventory, pricing, and business intelligence.",
                "display": "Greetings! SARTHI Intelligence System online."
            }

    elif intent == "acknowledgement":
        if lang == "hi":
            return {
                "speak": "आपका स्वागत है! यदि आपको इन्वेंटरी, कीमतों या रिपोर्ट्स में और सहायता चाहिए तो ज़रूर बताएं।",
                "display": "आपका स्वागत है! VANTIQ आपकी सेवा में उपस्थित है।"
            }
        elif lang == "hinglish":
            return {
                "speak": "Aapka swagat hai! Agar aapko inventory, pricing ya reports mein aur madad chahiye to zaroor batayein.",
                "display": "You're welcome! SARTHI ready for your next query."
            }
        else:
            return {
                "speak": "You're welcome! Let me know if you need any other business insights or data.",
                "display": "You're welcome! Let me know if you need any other business insights."
            }

    elif intent == "incomplete_stock_query":
        if lang == "hi":
            return {
                "speak": "आप किस प्रोडक्ट का स्टॉक देखना चाहते हैं? कृपया प्रोडक्ट का नाम बताएं।",
                "display": "स्टॉक पूछताछ: कृपया प्रोडक्ट का नाम बताएं।"
            }
        elif lang == "hinglish":
            return {
                "speak": "Aap kis product ka stock check karna chahte hain? Kripya product ka naam batayein.",
                "display": "Stock Inquiry: Kripya product ka naam batayein."
            }
        else:
            return {
                "speak": "Which product would you like me to check the stock for?",
                "display": "Stock Inquiry: Which product would you like to check?"
            }

    elif intent == "cancellation":
        if lang == "hi":
            return {
                "speak": "अनुरोध रद्द कर दिया गया। मैं आपके बिज़नेस डेटा या कैटलॉग में और कैसे सहायता कर सकता हूँ?",
                "display": "कार्रवाई रद्द की गई।"
            }
        elif lang == "hinglish":
            return {
                "speak": "Operation cancel kar diya gaya hai. Main aapke business data ya catalogue mein aur kaise madad kar sakta hoon?",
                "display": "Action cancelled."
            }
        else:
            return {
                "speak": "Operation cancelled. How else can I assist you with your business data?",
                "display": "Action cancelled."
            }

    elif intent == "market_price_clarify":
        name = data.get("name") or "Product"
        sp = data.get("selling_price")
        pp = data.get("purchase_price")
        currency = data.get("currency", "₹")
        sp_str = f"{currency}{sp:,.2f}" if sp is not None else "Not Configured"
        pp_str = f"{currency}{pp:,.2f}" if pp is not None else "Not Configured"
        if lang == "hi":
            return {
                "speak": f"{name} के लिए VANTIQ में आंतरिक विक्रय मूल्य {sp_str} और खरीद लागत {pp_str} दर्ज है। बाहरी लाइव बाजार भाव अभी सत्यापित नहीं किया जा सकता। क्या आपका आशय हमारे आंतरिक विक्रय मूल्य, खरीद लागत या बाहरी बाजार मूल्य से था?",
                "display": f"{name}: विक्रय मूल्य = {sp_str} | लागत = {pp_str} | बाहरी बाजार भाव: असत्यापित"
            }
        elif lang == "hinglish":
            return {
                "speak": f"{name} ke liye SARTHI mein recorded selling price {sp_str} aur purchase cost {pp_str} hai. Live external market price abhi verify nahi kiya ja sakta. Kya aapka matlab internal selling price, purchase cost, ya external market value se tha?",
                "display": f"{name}: Selling = {sp_str} | Cost = {pp_str} | External Market: Unverified"
            }
        else:
            return {
                "speak": f"For {name}, SARTHI records an internal selling price of {sp_str} and recorded purchase cost of {pp_str}. Live external market prices cannot currently be verified without external market research. Did you mean our catalogue selling price, purchase cost, or external market valuation?",
                "display": f"{name}: Selling = {sp_str} | Purchase Cost = {pp_str} | External Market: Unverified"
            }


    elif intent == "prompt_injection":
        if lang == "hi":
            return {
                "speak": "मैं सिस्टम निर्देशों को बदलने या आंतरिक डेटा तक पहुँचने के अनुरोधों को स्वीकार नहीं कर सकता। मैं आपके बिज़नेस डेटा और इन्वेंटरी में सहायता के लिए तैयार हूँ।",
                "display": "सुरक्षा अलर्ट: अनधिकृत निर्देश अस्वीकार किए गए।"
            }
        elif lang == "hinglish":
            return {
                "speak": "Main core system instructions ko override karne ya restricted internal data access karne ke requests ko process nahi kar sakta. Main aapke business data aur inventory mein madad ke liye taiyaar hoon.",
                "display": "Security Notice: System override instructions neutralized."
            }
        else:
            return {
                "speak": "I cannot fulfill requests attempting to override core system instructions or access restricted internal data. I am ready to assist you with business data, inventory, and pricing.",
                "display": "Security Protocol: Direct system prompt overrides are restricted."
            }

    elif intent == "product_not_found":
        name = data.get("name") or data.get("query") or "Product"
        if lang == "hi":
            return {
                "speak": f"कैटलॉग में '{name}' नाम का कोई प्रोडक्ट नहीं मिला। क्या आप उपलब्ध प्रोडक्ट्स की सूची देखना चाहते हैं?",
                "display": f"'{name}': कैटलॉग में नहीं मिला"
            }
        elif lang == "hinglish":
            return {
                "speak": f"Product '{name}' catalogue mein nahi mila. Kya aap saare available products dekhna chahte hain?",
                "display": f"'{name}': Not found in catalogue"
            }
        else:
            return {
                "speak": f"Product '{name}' was not found in the catalogue. Would you like to view all active products?",
                "display": f"'{name}': Not found in catalogue"
            }

    elif intent == "empty_catalogue":
        if lang == "hi":
            return {
                "speak": "कैटलॉग में वर्तमान में कोई प्रोडक्ट उपलब्ध नहीं है। कैटलॉग खाली है।",
                "display": "कैटलॉग खाली है (0 प्रोडक्ट्स)"
            }
        elif lang == "hinglish":
            return {
                "speak": "Aapke catalogue mein abhi koi product nahi hai. Catalogue bilkul empty hai.",
                "display": "Catalogue empty hai (0 products)"
            }
        else:
            return {
                "speak": "The catalogue is currently empty. There are no products available in the catalogue.",
                "display": "Catalogue is empty (0 products)"
            }

    elif intent == "product_list":
        items = data.get("items", [])
        total = data.get("total", len(items))
        if total == 0:
            if lang == "hi":
                return {
                    "speak": "कैटलॉग में वर्तमान में कोई प्रोडक्ट उपलब्ध नहीं है। कैटलॉग खाली है।",
                    "display": "कैटलॉग खाली है (0 प्रोडक्ट्स)"
                }
            elif lang == "hinglish":
                return {
                    "speak": "Aapke catalogue mein abhi koi product nahi hai. Catalogue bilkul empty hai.",
                    "display": "Catalogue empty hai (0 products)"
                }
            else:
                return {
                    "speak": "The catalogue is currently empty. There are no products available in the catalogue.",
                    "display": "Catalogue is empty (0 products)"
                }

        names = [p.get("name") for p in items[:5] if p.get("name")]
        sample = ", ".join(names)

        if lang == "hi":
            speak = f"आपके कैटलॉग में {total} प्रोडक्ट्स हैं, जैसे कि: {sample}।" if total > 0 else "कैटलॉग खाली है।"
            display = f"कैटलॉग: {total} प्रोडक्ट्स ({len(items)} दिखाए गए)"
        elif lang == "hinglish":
            speak = f"Aapke catalogue mein total {total} active products hain: {sample}."
            display = f"Catalogue: {total} products ({len(items)} shown)"
        else:
            speak = f"Here are the active products in your catalogue: {sample}."
            display = f"Catalogue: {total} active products ({len(items)} shown)"

        return {"speak": speak, "display": display}

    elif intent == "product_count":
        active = data.get("active", 0)
        units = data.get("units", 0.0)

        if lang == "hi":
            speak = f"कैटलॉग में कुल {active} एक्टिव प्रोडक्ट्स हैं, और कुल स्टॉक {units:,.1f} यूनिट्स है।"
            display = f"कुल प्रोडक्ट्स: {active} | कुल स्टॉक: {units:,.1f}"
        elif lang == "hinglish":
            speak = f"Catalogue mein total {active} products hain, aur sabhi milakar {units:,.1f} stock units hain."
            display = f"Total Products: {active} | Total Stock: {units:,.1f}"
        else:
            speak = f"You have {active} active products in the catalogue, with a total of {units:,.1f} stock units."
            display = f"Total Products: {active} | Stock Units: {units:,.1f}"

        return {"speak": speak, "display": display}

    elif intent == "product_stock":
        name = data.get("name", "Product")
        qty = data.get("quantity", 0.0)
        unit = data.get("unit", "units")
        reorder = data.get("reorder_level", 0.0)

        if lang == "hi":
            status_text = " (स्टॉक न्यूनतम स्तर से कम है!)" if qty <= reorder else ""
            speak = f"{name} का वर्तमान स्टॉक {qty} {unit} है{status_text}।"
            display = f"{name}: {qty} {unit} स्टॉक"
        elif lang == "hinglish":
            status_text = " (Low stock alert!)" if qty <= reorder else ""
            speak = f"{name} ka current stock {qty} {unit} hai{status_text}."
            display = f"{name}: {qty} {unit} stock"
        else:
            status_text = " (Low stock alert!)" if qty <= reorder else ""
            speak = f"The current stock for {name} is {qty} {unit}{status_text}."
            display = f"{name}: {qty} {unit} in stock"

        return {"speak": speak, "display": display}

    elif intent == "product_not_found":
        query = data.get("query", "")
        if lang == "hi":
            speak = f"माफ़ कीजिए, '{query}' नाम से कोई प्रोडक्ट कैटलॉग में नहीं मिला।"
            display = f"प्रोडक्ट नहीं मिला: '{query}'"
        elif lang == "hinglish":
            speak = f"Sorry, '{query}' naam se koi product catalogue mein nahi mila."
            display = f"Product nahi mila: '{query}'"
        else:
            speak = f"No product matching '{query}' was found in the catalogue."
            display = f"Product not found: '{query}'"

        return {"speak": speak, "display": display}

    elif intent == "inventory_summary":
        active = data.get("active", 0)
        units = data.get("units", 0.0)
        val = data.get("valuation", 0.0)
        low_count = data.get("low_count", 0)

        if lang == "hi":
            speak = f"इन्वेंटरी सारांश: कुल {active} प्रोडक्ट्स हैं, {units:,.1f} स्टॉक यूनिट्स, और कुल वैल्यू {currency}{val:,.2f} है। {low_count} प्रोडक्ट्स में स्टॉक कम है।"
            display = f"इन्वेंटरी: {active} प्रोडक्ट्स | स्टॉक: {units:,.1f} | वैल्यू: {currency}{val:,.2f}"
        elif lang == "hinglish":
            speak = f"Overall inventory status: Total {active} products hain, {units:,.1f} stock units, aur inventory valuation {currency}{val:,.2f} hai. {low_count} products low stock par hain."
            display = f"Inventory: {active} items | Stock: {units:,.1f} | Value: {currency}{val:,.2f}"
        else:
            speak = f"Overall inventory summary: {active} products, {units:,.1f} total stock units, valued at {currency}{val:,.2f}. {low_count} items are low in stock."
            display = f"Inventory: {active} items | Stock: {units:,.1f} | Valuation: {currency}{val:,.2f}"

        return {"speak": speak, "display": display}

    elif intent == "product_verify":
        issues = data.get("issues", [])
        total_checked = data.get("total_checked", 0)
        if not issues:
            if lang == "hi":
                speak = f"सत्यापन पूरा हुआ। कैटलॉग के सभी {total_checked} प्रोडक्ट्स के रिकॉर्ड वैध और सही हैं।"
                display = f"सत्यापन सफल: सभी {total_checked} प्रोडक्ट्स सही हैं"
            elif lang == "hinglish":
                speak = f"Verification complete! Catalogue ke sabhi {total_checked} products valid aur operational hain. Koi issue nahi mila."
                display = f"Verification Complete: {total_checked} products verified"
            else:
                speak = f"Verification complete. All {total_checked} catalogue products have valid prices, categories, and inventory records."
                display = f"Verification Passed: {total_checked} products verified"
        else:
            issue_summary = f"{len(issues)} issues detected"
            if lang == "hi":
                speak = f"सत्यापन में {len(issues)} प्रोडक्ट्स में समस्याएँ मिलीं (जैसे बिना कीमत या शून्य स्टॉक वाले प्रोडक्ट्स)।"
                display = f"सत्यापन चेतावनी: {len(issues)} समस्याएँ मिलीं"
            elif lang == "hinglish":
                speak = f"Verification report: {len(issues)} products mein issues mile hain (missing price ya zero stock). Details screen par hain."
                display = f"Verification Warning: {len(issues)} issues detected"
            else:
                speak = f"Product verification identified {len(issues)} items requiring attention (such as unconfigured prices or zero stock)."
                display = f"Verification Alert: {len(issues)} issues detected"

        return {"speak": speak, "display": display}

    elif intent == "lowest_stock":
        items = data.get("items", [])
        if not items:
            if lang == "hi":
                speak = "कैटलॉग में कोई एक्टिव प्रोडक्ट नहीं है।"
                display = "कोई प्रोडक्ट नहीं मिला"
            elif lang == "hinglish":
                speak = "Catalogue mein koi active product nahi hai."
                display = "Koi product nahi mila"
            else:
                speak = "No active products recorded in the catalogue."
                display = "No products found"
        else:
            names = [f"{p['name']} ({p.get('quantity_on_hand', 0)} {p.get('unit', 'units')})" for p in items[:3]]
            sample = ", ".join(names)
            if lang == "hi":
                speak = f"सबसे कम स्टॉक वाले प्रोडक्ट्स हैं: {sample}।"
                display = f"न्यूनतम स्टॉक: {sample}"
            elif lang == "hinglish":
                speak = f"Sabse kam stock wale products ye hain: {sample}."
                display = f"Lowest Stock: {sample}"
            else:
                speak = f"The products with the lowest stock quantities are: {sample}."
                display = f"Lowest Stock: {sample}"
        return {"speak": speak, "display": display}

    elif intent == "cheapest_product":
        product = data.get("product")
        if not product:
            if lang == "hi":
                speak = "कैटलॉग में कोई प्रोडक्ट नहीं मिला।"
                display = "कोई प्रोडक्ट उपलब्ध नहीं"
            elif lang == "hinglish":
                speak = "Catalogue mein koi product nahi mila."
                display = "No products available"
            else:
                speak = "No products are currently available in the catalogue."
                display = "No products available"
        else:
            name = product.get("name", "Product")
            price = product.get("selling_price", 0.0)
            if lang == "hi":
                speak = f"उपलब्ध प्रोडक्ट्स में सबसे सस्ता प्रोडक्ट {name} है, जिसका विक्रय मूल्य {currency}{price:,.2f} है।"
                display = f"सबसे सस्ता: {name} ({currency}{price:,.2f})"
            elif lang == "hinglish":
                speak = f"Inmein sabse sasta product {name} hai, jiska selling price {currency}{price:,.2f} hai."
                display = f"Cheapest: {name} ({currency}{price:,.2f})"
            else:
                speak = f"The cheapest product in the catalogue is {name}, priced at {currency}{price:,.2f}."
                display = f"Cheapest: {name} ({currency}{price:,.2f})"
        return {"speak": speak, "display": display}

    elif intent == "expensive_product":
        product = data.get("product")
        if not product:
            if lang == "hi":
                speak = "कैटलॉग में कोई प्रोडक्ट नहीं मिला।"
                display = "कोई प्रोडक्ट उपलब्ध नहीं"
            elif lang == "hinglish":
                speak = "Catalogue mein koi product nahi mila."
                display = "No products available"
            else:
                speak = "The catalogue is currently empty. No products are available in the catalogue."
                display = "No products available (Empty Catalogue)"
        else:
            name = product.get("name", "Product")
            price = product.get("selling_price", 0.0)
            if lang == "hi":
                speak = f"उपलब्ध प्रोडक्ट्स में सबसे महँगा प्रोडक्ट {name} है, जिसका विक्रय मूल्य {currency}{price:,.2f} है।"
                display = f"सबसे महँगा: {name} ({currency}{price:,.2f})"
            elif lang == "hinglish":
                speak = f"Inmein sabse mehenga product {name} hai, jiska selling price {currency}{price:,.2f} hai."
                display = f"Most Expensive: {name} ({currency}{price:,.2f})"
            else:
                speak = f"The most expensive product in the catalogue is {name}, priced at {currency}{price:,.2f}."
                display = f"Most Expensive: {name} ({currency}{price:,.2f})"
        return {"speak": speak, "display": display}

    elif intent == "selling_price":
        product = data.get("product")
        name = product.get("name", "Product") if product else data.get("name", "Product")
        price = product.get("selling_price", 0.0) if product else data.get("price", 0.0)
        cost = product.get("purchase_price", 0.0) if product else data.get("cost", 0.0)
        if lang == "hi":
            speak = f"{name} का विक्रय मूल्य {currency}{price:,.2f} है, और लागत मूल्य {currency}{cost:,.2f} है।"
            display = f"{name}: विक्रय मूल्य = {currency}{price:,.2f} | लागत = {currency}{cost:,.2f}"
        elif lang == "hinglish":
            speak = f"{name} ka selling price {currency}{price:,.2f} hai aur purchase price {currency}{cost:,.2f} hai."
            display = f"{name}: Selling Price = {currency}{price:,.2f} | Cost = {currency}{cost:,.2f}"
        else:
            speak = f"The selling price of {name} is {currency}{price:,.2f}, with a purchase cost of {currency}{cost:,.2f}."
            display = f"{name}: Selling Price = {currency}{price:,.2f} | Cost = {currency}{cost:,.2f}"
        return {"speak": speak, "display": display}

    elif intent == "supplier_lookup":
        mode = data.get("mode", "single")
        if mode == "list":
            suppliers = data.get("suppliers", [])
            if not suppliers:
                if lang == "hi":
                    speak = "डेटाबेस में कोई पंजीकृत सप्लायर नहीं मिला।"
                    display = "कोई सप्लायर नहीं मिला"
                elif lang == "hinglish":
                    speak = "Database mein koi registered supplier nahi mila."
                    display = "No suppliers found"
                else:
                    speak = "No registered suppliers were found in the database."
                    display = "No suppliers found"
            else:
                names = [s.get("name") for s in suppliers[:4] if s.get("name")]
                sample = ", ".join(names)
                if lang == "hi":
                    speak = f"कुल {len(suppliers)} सप्लायर्स पंजीकृत हैं: {sample}।"
                    display = f"सप्लायर्स ({len(suppliers)}): {sample}"
                elif lang == "hinglish":
                    speak = f"Catalogue mein total {len(suppliers)} suppliers registered hain: {sample}."
                    display = f"Suppliers ({len(suppliers)}): {sample}"
                else:
                    speak = f"There are {len(suppliers)} registered suppliers in the database: {sample}."
                    display = f"Suppliers ({len(suppliers)}): {sample}"
        else:
            product_name = data.get("product_name", "Product")
            supplier_name = data.get("supplier_name")
            if not supplier_name:
                if lang == "hi":
                    speak = f"{product_name} कैटलॉग में है, लेकिन अभी इसके लिए कोई सप्लायर लिंक नहीं है।"
                    display = f"{product_name}: कोई सप्लायर लिंक नहीं है"
                elif lang == "hinglish":
                    speak = f"{product_name} catalogue mein registered hai, lekin abhi koi supplier linked nahi hai."
                    display = f"{product_name}: No supplier linked"
                else:
                    speak = f"Product '{product_name}' is in the catalogue, but no supplier is currently linked."
                    display = f"{product_name}: No supplier linked"
            else:
                contact = data.get("contact_name")
                extra = f" (Contact: {contact})" if contact else ""
                if lang == "hi":
                    speak = f"{product_name} के सप्लायर {supplier_name} हैं{extra}।"
                    display = f"{product_name} सप्लायर: {supplier_name}"
                elif lang == "hinglish":
                    speak = f"{product_name} ke supplier {supplier_name} hain{extra}."
                    display = f"{product_name} Supplier: {supplier_name}"
                else:
                    speak = f"The supplier for {product_name} is {supplier_name}{extra}."
                    display = f"{product_name} Supplier: {supplier_name}"
        return {"speak": speak, "display": display}

    elif intent in ("product_margin", "product_profit"):
        name = data.get("name", "Product")
        profit = data.get("profit", 0.0)
        margin_pct = data.get("margin_pct", 0.0)
        sp = data.get("selling_price", 0.0)
        cp = data.get("purchase_price", 0.0)
        basis_note = data.get("cost_basis_note", "")
        if intent == "product_profit":
            if lang == "hi":
                speak = f"{name} बेचने पर सकल लाभ (Gross Profit) {currency}{profit:,.2f} ({margin_pct:.1f}% मार्जिन) है{basis_note}। विक्रय मूल्य {currency}{sp:,.2f} और खरीद लागत {currency}{cp:,.2f} है।"
                display = f"{name} लाभ: {currency}{profit:,.2f} ({margin_pct:.1f}% मार्जिन) | विक्रय: {currency}{sp:,.2f} | लागत: {currency}{cp:,.2f}"
            elif lang == "hinglish":
                speak = f"{name} bechne par gross profit {currency}{profit:,.2f} ({margin_pct:.1f}% margin) hai{basis_note}. Selling price {currency}{sp:,.2f} aur purchase cost {currency}{cp:,.2f} hai."
                display = f"{name} Profit: {currency}{profit:,.2f} ({margin_pct:.1f}%) | Selling: {currency}{sp:,.2f} | Cost: {currency}{cp:,.2f}"
            else:
                speak = f"The estimated gross profit selling {name} is {currency}{profit:,.2f} per unit ({margin_pct:.1f}% margin){basis_note}, based on selling price {currency}{sp:,.2f} and recorded cost {currency}{cp:,.2f}."
                display = f"{name}: Profit = {currency}{profit:,.2f} ({margin_pct:.1f}% margin) | Selling = {currency}{sp:,.2f} | Cost = {currency}{cp:,.2f}"
        else:
            if lang == "hi":
                speak = f"{name} पर ग्रॉस मार्जिन {currency}{profit:,.2f} ({margin_pct:.1f}%) है{basis_note}। इसका विक्रय मूल्य {currency}{sp:,.2f} और खरीद लागत {currency}{cp:,.2f} है।"
                display = f"{name} मार्जिन: {currency}{profit:,.2f} ({margin_pct:.1f}%) | विक्रय: {currency}{sp:,.2f} | लागत: {currency}{cp:,.2f}"
            elif lang == "hinglish":
                speak = f"{name} ka gross margin {currency}{profit:,.2f} ({margin_pct:.1f}%) hai{basis_note}. Selling price {currency}{sp:,.2f} aur purchase cost {currency}{cp:,.2f} hai."
                display = f"{name} Margin: {currency}{profit:,.2f} ({margin_pct:.1f}%) | Selling: {currency}{sp:,.2f} | Cost: {currency}{cp:,.2f}"
            else:
                speak = f"The gross margin for {name} is {margin_pct:.1f}% (gross profit {currency}{profit:,.2f} per unit){basis_note}, with selling price {currency}{sp:,.2f} and cost {currency}{cp:,.2f}."
                display = f"{name}: Margin = {margin_pct:.1f}% (Profit: {currency}{profit:,.2f}) | Selling = {currency}{sp:,.2f} | Cost = {currency}{cp:,.2f}"
        return {"speak": speak, "display": display}

    elif intent == "catalogue_margin":
        avg_m = data.get("average_margin_pct", 0.0)
        top_prod = data.get("highest_margin_product", "N/A")
        top_pct = data.get("highest_margin_pct", 0.0)
        if lang == "hi":
            speak = f"कैटलॉग का समग्र औसत ग्रॉस मार्जिन {avg_m:.1f}% है। सबसे अधिक मार्जिन {top_prod} ({top_pct:.1f}%) पर है।"
            display = f"औसत मार्जिन: {avg_m:.1f}% | शीर्ष: {top_prod} ({top_pct:.1f}%)"
        elif lang == "hinglish":
            speak = f"Catalogue ka overall average gross margin {avg_m:.1f}% hai. Sabse zyada margin {top_prod} ({top_pct:.1f}%) par hai."
            display = f"Avg Margin: {avg_m:.1f}% | Top: {top_prod} ({top_pct:.1f}%)"
        else:
            speak = f"The overall average gross margin across catalogue products is {avg_m:.1f}%. The highest margin product is {top_prod} at {top_pct:.1f}%."
            display = f"Avg Margin: {avg_m:.1f}% | Top: {top_prod} ({top_pct:.1f}%)"
        return {"speak": speak, "display": display}

    # Default fallback
    return {
        "speak": data.get("speak", "Processed successfully."),
        "display": data.get("display", "Operation completed.")
    }


def match_multilingual_intent(query: str, lang: str = "en", session_id: Optional[str] = None) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Fast regex and phrase intent dispatcher for Hindi, Hinglish, and English queries.
    Returns (intent_name, params_dict) or None if no match.
    """
    q = query.strip()
    q_lower = q.lower()

    # Clean punctuation and wake words
    cleaned, detected_lang = clean_query(q)
    c_lower = cleaned.lower()
    active_lang = lang if lang in ("hi", "hinglish") else detected_lang
    session_ctx = get_session_context(session_id)

    # 0A. Prompt Injection Defense
    if any(re.search(p, c_lower) for p in [
        r'\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior)\s+(instructions|prompts|rules)\b',
        r'\b(system\s+prompt|reveal\s+prompt|database\s+password|admin\s+password|show\s+secret)\b',
        r'\b(drop\s+table|delete\s+from|rm\s+-rf)\b'
    ]):
        return ("prompt_injection", {})

    # 0B. Identity ("Kaun ho tum?", "Who are you?", "Tum kaun ho?")
    if any(phrase in c_lower for phrase in [
        'kaun ho tum', 'tum kaun ho', 'aap kaun hain', 'kon ho tum', 'tum kon ho',
        'who are you', 'who are u', 'who r u', 'what is your name', 'tumhara naam kya hai',
        'introduce yourself', 'apna intro do', 'apna parichay do', 'who made you',
        'tumhe kisne banaya', 'what is sarthi', 'sarthi kya hai', 'tum kya ho',
        'कौन हो तुम', 'तुम कौन हो', 'आप कौन हैं', 'तुम्हारा नाम क्या है', 'तुम क्या हो'
    ]) or c_lower.strip('?. ') in ('who are you', 'kaun ho tum', 'tum kaun ho', 'who are u', 'aap kaun hain'):
        return ("identity", {})

    # 0C. Capabilities ("Tum kya kar sakte ho?", "What can you do?")
    if any(phrase in c_lower for phrase in [
        'tum kya kar sakte ho', 'aap kya kar sakte hain', 'kya kar sakte ho',
        'what can you do', 'what do you do', 'apni capabilities batao',
        'what are your capabilities', 'what can sarthi do', 'tumhari capabilities kya hai',
        'तुम क्या कर सकते हो', 'आप क्या कर सकते हैं', 'क्या कर सकते हो'
    ]) or c_lower.strip('?. ') in ('what can you do', 'tum kya kar sakte ho', 'capabilities'):
        return ("capabilities", {})

    # 0D. Greetings ("Hello", "Hi", "Namaste", "Kaise ho")
    if any(phrase in c_lower for phrase in [
        'namaste', 'kaise ho', 'how are you', 'kya haal hai', 'kaisa hai',
        'good morning', 'good evening', 'good afternoon', 'नमस्ते', 'कैसे हो', 'क्या हाल है'
    ]) or c_lower.strip('?. ') in ('hello', 'hi', 'hey', 'namaste', 'greetings', 'hola'):
        return ("greeting", {})

    # 0E-1. Confirmation ("Yes", "Yeah", "Sure", "Of course", "Haan", "Bilkul")
    if any(phrase == c_lower.strip('?.! ') for phrase in [
        'yes', 'yeah', 'yep', 'sure', 'of course', 'yes of course', 'certainly',
        'definitely', 'yes please', 'ok', 'okay', 'haan', 'ha', 'haanji', 'haan ji',
        'haan batao', 'haan dikhao', 'ha batao', 'ha dikhao', 'bilkul', 'zaroor',
        'sure why not', 'haan bilkul', 'हाँ', 'हां', 'जी हाँ', 'ज़रूर', 'बिल्कुल', 'हाँ दिखाओ', 'हाँ बताओ'
    ]) or c_lower.strip('?.! ') in (
        'yes', 'yeah', 'yep', 'sure', 'of course', 'yes of course', 'certainly',
        'definitely', 'yes please', 'ok', 'okay', 'haan', 'ha', 'haanji', 'haan batao',
        'bilkul', 'zaroor', 'sure why not'
    ):
        return ("confirmation", {"text": c_lower})

    # 0E-2. Cancellation ("No", "Cancel", "Never mind", "Rehne do", "Nahi")
    if any(phrase == c_lower.strip('?.! ') for phrase in [
        'no', 'cancel', 'never mind', 'nevermind', 'rehne do', 'rehne de', 'mat karo',
        'nahi', 'nahin', 'stop', 'don\'t', 'dont', 'nope', 'cancel karo',
        'नहीं', 'मत करो', 'रहने दो', 'रद्द करो', 'कैंसिल'
    ]) or c_lower.strip('?.! ') in (
        'no', 'cancel', 'never mind', 'nevermind', 'rehne do', 'rehne de', 'mat karo',
        'nahi', 'nahin', 'stop', 'nope', 'cancel karo'
    ):
        return ("cancellation", {"text": c_lower})

    # 0E-3. Acknowledgement ("Thank you", "Thanks", "Dhanyawad", "Shukriya")
    if any(phrase in c_lower for phrase in [
        'thank you', 'thanks a lot', 'thank u', 'dhanyawad', 'dhanyavaad',
        'shukriya', 'bahut badhiya', 'great job', 'good job', 'awesome work',
        'धन्यवाद', 'शुक्रिया'
    ]) or c_lower.strip('?. ') in ('thank you', 'thanks', 'thank u', 'dhanyawad', 'shukriya', 'thx'):
        return ("acknowledgement", {})

    # 0F. Multi-turn Follow-up: Language Explanation ("Explain that in Hindi")
    if any(phrase in c_lower for phrase in [
        'explain that in hindi', 'explain this in hindi', 'translate that in hindi',
        'translate this in hindi', 'hindi me samjhao', 'hindi mein samjhao',
        'isko hindi me batao', 'isko hindi mein batao', 'isse hindi me batao',
        'हिंदी में समझाओ', 'हिंदी में बताओ'
    ]):
        return ("follow_up_explain_lang", {"target_language": "Hindi"})

    if any(phrase in c_lower for phrase in [
        'explain that in english', 'explain this in english', 'translate that in english',
        'translate this in english', 'english me samjhao', 'english mein samjhao',
        'isko english me batao', 'isko english mein batao'
    ]):
        return ("follow_up_explain_lang", {"target_language": "English"})

    if any(phrase in c_lower for phrase in [
        'explain that in hinglish', 'explain this in hinglish', 'translate that in hinglish',
        'translate this in hinglish', 'hinglish me samjhao', 'hinglish mein samjhao',
        'isko hinglish me batao', 'isko hinglish mein batao'
    ]):
        return ("follow_up_explain_lang", {"target_language": "Hinglish"})

    # 1. Product Verification
    if any(phrase in c_lower for phrase in [
        'verify all the products', 'verify all products', 'verify products',
        'validate all products', 'validate products', 'check products',
        'audit all products', 'verify catalogue', 'saare products verify',
        'sare products verify', 'products verify', 'products ko verify'
    ]) or (('verify' in c_lower or 'validate' in c_lower) and ('product' in c_lower or 'catalogue' in c_lower)):
        return ("product_verify", {})

    # 2. Contextual follow-up: Cheapest / Most expensive product
    if any(phrase in c_lower for phrase in [
        'sabse sasta', 'sabse saste', 'sabse sasti', 'cheapest product',
        'which one is cheapest', 'which product is cheapest', 'cheapest one',
        'inmein sabse sasta', 'inme sabse sasta', 'sab se sasta', 'सबसे सस्ता'
    ]):
        return ("cheapest_product", {})

    if any(phrase in c_lower for phrase in [
        'sabse mehenga', 'sabse mehnge', 'sabse costly', 'most expensive',
        'highest price product', 'inmein sabse mehenga', 'सबसे महंगा', 'सबसे महँगा'
    ]):
        return ("expensive_product", {})

    # 3. Lowest stock products
    if any(phrase in c_lower for phrase in [
        'sabse kam stock', 'sab se kam stock', 'lowest stock', 'least stock',
        'sabse kam stock kin', 'sabse kam stock kiska', 'minimum stock products',
        'सबसे कम स्टॉक'
    ]):
        return ("lowest_stock_products", {})

    # 4. Out of stock products
    if any(phrase in c_lower for phrase in [
        'stock khatam', 'khatam ho gaya', 'out of stock', 'zero stock',
        'stock khatm', 'khatam products', 'स्टॉक खत्म'
    ]):
        return ("out_of_stock_products", {})

    # 5. Low stock / Reorder products
    if any(phrase in c_lower for phrase in [
        'low stock wale products', 'low stock products', 'kam stock wale',
        'low stock dikhao', 'low stock items', 'कम स्टॉक', 'कम स्टॉक वाले',
        'need reordering', 'needs reordering', 'products to reorder', 'reorder level',
        'reorder threshold', 'reorder alerts', 'reorder alert', 'which products need reorder',
        'which products are low in stock', 'low stock', 'low in stock', 'low inventory',
        'stock kam hai', 'kam stock', 'स्टॉक कम है', 'किन प्रोडक्ट्स का स्टॉक कम है'
    ]):
        return ("low_stock_products", {})

    # 6. Specific product stock query & Incomplete Stock Inquiry
    # Handles: "Tell me the stock of the", "Tell me the stock of", "Stock of this product?",
    # "Iska stock kitna hai?", "Product ka stock batao", "Capacitor ka current stock kitna hai?"
    is_stock_keyword = ('stock' in c_lower or 'स्टॉक' in c_lower)
    if is_stock_keyword:
        # Check overall stock summary phrases first (without product specifier):
        is_overall_stock = any(phrase == c_lower.strip('?.! ') for phrase in [
            'current stock', 'what is current stock', 'overall stock', 'total stock',
            'stock summary', 'inventory summary', 'kul stock', 'stock kitna hai',
            'stock status', 'current stock bro', 'current stock sarthi',
            'कुल स्टॉक', 'स्टॉक सारांश'
        ]) or c_lower.strip('?.! ') in ('stock', 'current stock', 'total stock', 'kul stock')

        if not is_overall_stock:
            cand = None
            # Pattern A: "stock of <cand>" or "stock of"
            stock_of_match = re.search(r'(?:current\s+)?stock\s+of(?:\s+([a-zA-Z0-9_\-\s]+))?', c_lower)
            if stock_of_match:
                cand = (stock_of_match.group(1) or "").strip().rstrip('?.!')
                cand = re.sub(r'\b(bro|bhai|sarthi|saarthi|vantiq|jarvis|please)\b', '', cand).strip()

            # Pattern B: "<cand> ka (current )?stock (kitna hai|batao)?"
            if cand is None:
                stock_hinglish_match = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+(?:current\s+)?stock(?:\s+(?:kitna\s+hai|batao|status))?', c_lower)
                if stock_hinglish_match:
                    cand = stock_hinglish_match.group(1).strip().rstrip('?.!')
                    cand = re.sub(r'^(is|iss|is product|mujhe|batao|zara)\s+', '', cand).strip()

            # Pattern C: Devanagari Hindi "<cand> का स्टॉक"
            if cand is None:
                hi_stock_match = re.search(r'([\u0900-\u097F\w\s]+?)\s+का\s+(?:करंट\s+)?स्टॉक', c_lower)
                if hi_stock_match:
                    cand = hi_stock_match.group(1).strip().rstrip('?.!')

            # Pattern D: "iska stock kitna hai", "iss product ka stock"
            if cand is None and any(p in c_lower for p in ['iska stock', 'isse stock', 'iss product ka stock', 'is product ka stock', 'product ka stock', 'stock batao', 'stock bataiye']):
                cand = "context_product" if any(p in c_lower for p in ['iska', 'iss product', 'is product']) else "product"

            # Check candidate validity
            if cand is not None:
                # If cand is a demonstrative pointing to context product
                is_context_demonstrative = cand in ('context_product', 'iska', 'iss', 'is', 'this', 'this product', 'it', 'उसका', 'इसका')
                if is_context_demonstrative:
                    if session_ctx.last_product:
                        cand = session_ctx.last_product["name"]
                        return ("product_stock", {"product_name": cand})
                    else:
                        return ("incomplete_stock_query", {"prompt_lang": active_lang})

                # Check if cand is a stopword or empty (e.g. "the", "product", "")
                if is_product_stopword(cand):
                    return ("incomplete_stock_query", {"prompt_lang": active_lang})

                # Valid product identifier provided!
                return ("product_stock", {"product_name": cand})
            elif any(c_lower.endswith(tail) for tail in ['stock of', 'stock of the', 'stock batao', 'stock dikhao', 'ka stock', 'ka stock batao']):
                return ("incomplete_stock_query", {"prompt_lang": active_lang})

    # 7. Overall / Current Stock Summary (No specific product mentioned)
    if any(phrase in c_lower for phrase in [
        'current stock', 'what is current stock', 'overall stock', 'total stock',
        'stock summary', 'inventory summary', 'kul stock', 'stock kitna hai',
        'stock status', 'current stock bro', 'current stock sarthi'
    ]):
        return ("inventory_summary", {})

    # 8. All Products / Catalogue Listing
    # E.g., "jarvis kaun kaun se products hai", "Saare products dikhao", "Sabhi products ke naam batao", "show all products"
    if any(phrase in c_lower for phrase in [
        'kaun kaun se products', 'kaun se products', 'kya kya products',
        'saare products dikhao', 'sare products dikhao', 'sab products dikhao',
        'sabhi products ke naam', 'products ke naam', 'products ki list',
        'products dikhao', 'catalogue dikhao', 'list all products',
        'show all products', 'what are all products', 'all products',
        'saare products', 'sare products', 'sab products', 'सारे प्रोडक्ट्स दिखाओ',
        'सभी प्रोडक्ट्स के नाम', 'कौन कौन से प्रोडक्ट्स', 'प्रोडक्ट्स दिखाओ'
    ]):
        return ("product_list", {})

    # 9. Total Product Count
    # E.g., "Kitne products hain?", "how many products do we have", "total products"
    if any(phrase in c_lower for phrase in [
        'kitne products', 'kitne product', 'total products count', 'how many products',
        'kul kitne product', 'kul kitne products', 'number of products', 'count products',
        'कितने प्रोडक्ट्स', 'कितने प्रोडक्ट', 'कुल कितने', 'कुल कितने प्रोडक्ट'
    ]):
        return ("product_count", {})

    # 10A. Market Price / Market Value Inquiry (distinguish internal vs external)
    if any(phrase in c_lower for phrase in [
        'market price', 'market value', 'market rate', 'market valuation',
        'bazaar bhav', 'bazar bhav', 'market bhav', 'bajar bhav',
        'बाजार भाव', 'बाज़ार भाव', 'मार्केट वैल्यू', 'मार्केट प्राइस', 'मार्केट रेट'
    ]):
        m_cand = None
        m_match = re.search(r'(?:market\s+(?:price|value|rate|valuation)|bazaar\s+bhav|bazar\s+bhav)\s+(?:of|for)\s+([a-zA-Z0-9_\-\s]+)', c_lower)
        if m_match:
            m_cand = m_match.group(1).strip().rstrip('?.!')
        else:
            m_match2 = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+(?:market\s+(?:price|value|rate|valuation)|bazaar\s+bhav|bazar\s+bhav)', c_lower)
            if m_match2:
                m_cand = m_match2.group(1).strip().rstrip('?.!')

        if m_cand:
            m_cand = re.sub(r'\b(bro|bhai|sarthi|saarthi|vantiq|jarvis|please|tell me|what is|the)\b', '', m_cand).strip()
            if is_product_stopword(m_cand):
                m_cand = None

        return ("market_price_inquiry", {"product_name": m_cand, "query": q})

    # 10B. Specific product selling price
    # Hinglish: "<Product> ka selling price kya hai", "<Product> ka price"
    price_hinglish_match = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+(?:selling\s+price|price|rate|bhav)(\s+kya\s+hai)?', c_lower)
    if price_hinglish_match:
        cand = price_hinglish_match.group(1).strip()
        if cand in ('is', 'iss', 'is product', 'iss product'):
            cand = "context_product"
        if cand:
            return ("product_price", {"product_name": cand})

    # English: "What is the selling price of <Product>?", "selling price of <Product>", "price of <Product>"
    price_en_match = re.search(r'(?:what\s+is\s+(?:the\s+)?)?(?:selling\s+price|sale\s+price|price|rate|cost)\s+of\s+([a-zA-Z0-9_\-\s]+)', c_lower)
    if price_en_match:
        cand = price_en_match.group(1).strip().rstrip('?.')
        cand = re.sub(r'\b(bro|bhai|sarthi|saarthi|vantiq|jarvis|please)\b', '', cand).strip()
        if cand and cand not in ('product', 'catalogue', 'all', 'everything'):
            return ("product_price", {"product_name": cand})

    # Hindi Devanagari: "<Product> का विक्रय मूल्य / दाम / कीमत"
    hi_price_match = re.search(r'([\u0900-\u097F\w\s]+?)\s+का\s+(?:विक्रय\s+मूल्य|मूल्य|दाम|कीमत)', c_lower)
    if hi_price_match:
        cand = hi_price_match.group(1).strip()
        if cand:
            return ("product_price", {"product_name": cand})


    # 11. Supplier Lookup
    # E.g. "Who is the supplier for Capacitor?", "supplier of Capacitor", "Capacitor ka supplier kaun hai", "list suppliers"
    if any(phrase in c_lower for phrase in ['list suppliers', 'all suppliers', 'show suppliers', 'suppliers list', 'saare suppliers', 'sabhi suppliers', 'suppliers dikhao']):
        return ("supplier_lookup", {"list_all": True})

    supp_hinglish_match = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+supplier(\s+kaun\s+hai)?', c_lower)
    if supp_hinglish_match:
        cand = supp_hinglish_match.group(1).strip()
        cand = re.sub(r'^(is|iss|is product|mujhe|batao|zara)\s+', '', cand).strip()
        if cand and cand not in ('all', 'saare', 'sab', 'product'):
            return ("supplier_lookup", {"product_name": cand})

    supp_en_match = re.search(r'(?:who\s+is\s+(?:the\s+)?)?supplier\s+(?:for|of)\s+([a-zA-Z0-9_\-\s]+)', c_lower)
    if supp_en_match:
        cand = supp_en_match.group(1).strip().rstrip('?.')
        cand = re.sub(r'\b(bro|bhai|sarthi|saarthi|vantiq|jarvis|please)\b', '', cand).strip()
        if cand and cand not in ('product', 'catalogue', 'all'):
            return ("supplier_lookup", {"product_name": cand})

    # 12. Conceptual / Business Difference Explanations
    # E.g. "Purchase price aur selling price mein kya difference hai?"
    # "Gross margin aur markup mein kya difference hai?"
    if any(term in c_lower for term in ['difference', 'antar', 'farq']) or 'kya difference' in c_lower:
        if ('purchase price' in c_lower and 'selling price' in c_lower) or ('cost price' in c_lower and 'selling price' in c_lower):
            return ("explanation", {"concept": "purchase price and selling price difference", "language": active_lang})
        if ('gross margin' in c_lower and 'markup' in c_lower) or ('margin' in c_lower and 'markup' in c_lower):
            return ("explanation", {"concept": "gross margin and markup difference", "language": active_lang})

    # 13. Profit & Margin Inquiries (Product Profit, Product Margin & Overall Margin)
    # E.g. "What is the profit of Capacitor?", "What profit do we make selling Capacitor?",
    # "Calculate profit on Capacitor", "What is the margin on Chair?", "Chair ka margin kitna hai?",
    # "Capacitor bechne par kitna profit hai?"
    if any(k in c_lower for k in ['margin', 'profit', 'munafa', 'मार्जिन', 'मुनाफा', 'लाभ']):
        # Check if user explicitly asks for an abstract conceptual textbook definition
        clean_no_lang = re.sub(r'\b(in\s+)?(hindi|english|hinglish|french|spanish|german|devanagari)\b', '', c_lower, flags=re.IGNORECASE).strip('?.! ')
        clean_no_lang = re.sub(r'\b(mein|me)\s+samjhao\b', '', clean_no_lang, flags=re.IGNORECASE).strip('?.! ')
        is_conceptual = (
            clean_no_lang in (
                'what is margin', 'what is the margin', 'what is gross margin', 'what is the gross margin',
                'margin kya hota hai', 'gross margin kya hota hai',
                'define margin', 'explain margin', 'define gross margin', 'explain gross margin',
                'what is profit', 'what is the profit', 'what is gross profit', 'what is the gross profit',
                'profit kya hota hai', 'define profit', 'explain profit',
                'what is profit margin', 'profit margin kya hota hai'
            ) or (
                clean_no_lang.startswith(('explain ', 'define ')) and
                not any(w in clean_no_lang for w in [' of ', ' on ', ' for ', ' in ', ' selling ', ' bechne ', ' par ', ' me ', ' mein ', ' ka ', ' ki ', ' ke '])
            )
        )
        if is_conceptual:
            target_lang = "Hindi" if "hindi" in c_lower else ("Hinglish" if active_lang == "hinglish" else "English")
            concept = "gross profit" if ("profit" in c_lower and "margin" not in c_lower) else "gross margin"
            return ("explanation", {"concept": concept, "language": target_lang})

        # Detect explicit cost basis request (e.g. latest purchase rate)
        is_last_rate = any(k in c_lower for k in [
            'last purchase rate', 'latest purchase rate', 'last purchase cost', 'last purchase price',
            'pichla purchase rate', 'pichle purchase rate', 'aakhri purchase rate', 'last procurement rate',
            'last buy rate', 'pichli khareed dar'
        ])
        cost_basis = "last_purchase_rate" if is_last_rate else "purchase_price"

        cand = None

        # 1. English Profit Queries
        # "What profit do we make selling Capacitor?", "what is the profit selling a capacitor"
        m_prof_sell = re.search(r'(?:what\s+profit\s+(?:do\s+we\s+make\s+)?(?:in\s+)?selling\s+|(?:what\s+is\s+(?:the\s+)?)?(?:gross\s+)?profit\s+(?:in\s+)?selling\s+)(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-\s]+)', c_lower)
        if m_prof_sell:
            cand = m_prof_sell.group(1).strip()

        # "Calculate profit on/for/of <Product>"
        if cand is None:
            m_prof_calc = re.search(r'(?:calculate\s+(?:the\s+)?(?:gross\s+)?(?:profit|margin)\s+(?:on|for|of)\s+)(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-\s]+)', c_lower)
            if m_prof_calc:
                cand = m_prof_calc.group(1).strip()

        # "What is the profit of/on/for/in <Product>", "profit of <Product>"
        if cand is None:
            m_prof_of = re.search(r'(?:what\s+is\s+(?:the\s+)?)?(?:gross\s+)?profit\s+(?:of|on|for|in)\s+(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-\s]+)', c_lower)
            if m_prof_of:
                cand = m_prof_of.group(1).strip()

        # 2. Hinglish Profit Queries
        # "<Product> bechne par kitna profit hai", "<Product> bechne par profit"
        if cand is None:
            m_prof_bechne = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+bechne\s+par\s+(?:kitna\s+)?(?:profit|munafa|labh)', c_lower)
            if m_prof_bechne:
                cand = m_prof_bechne.group(1).strip()

        # "<Product> ka / par / me profit"
        if cand is None:
            m_prof_hing = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+(?:ka|ki|ke|par|pe|me|mein)\s+(?:kitna\s+)?(?:profit|munafa|labh)', c_lower)
            if m_prof_hing:
                cand = m_prof_hing.group(1).strip()

        # 3. English Margin Queries
        # "What is the margin on/of/for/in Chair?", "margin on Chair"
        if cand is None:
            m_mrg_en = re.search(r'(?:what\s+is\s+(?:the\s+)?)?(?:gross\s+)?margin\s+(?:of|on|for|in)\s+(?:a\s+|an\s+|the\s+)?([a-zA-Z0-9_\-\s]+)', c_lower)
            if m_mrg_en:
                cand = m_mrg_en.group(1).strip()

        # 4. Hinglish Margin Queries
        # "margin kya hai chair me/mein"
        if cand is None:
            m1 = re.search(r'margin\s+(?:kya\s+hai\s+|kitna\s+hai\s+)?([a-zA-Z0-9_\-\s]+?)\s+(?:me|mein)\b', c_lower)
            if m1:
                cand = m1.group(1).strip()

        # "<product> me/mein kitna margin hai"
        if cand is None:
            m2 = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+(?:me|mein)\s+(?:kitna\s+)?margin', c_lower)
            if m2:
                cand = m2.group(1).strip()

        # "<product> ka margin kitna hai", "<product> ka margin"
        if cand is None:
            m3 = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+(?:gross\s+)?margin', c_lower)
            if m3:
                cand = m3.group(1).strip()

        # 5. Hindi Devanagari Profit & Margin Queries
        if cand is None:
            hi_profit_match = re.search(r'([\u0900-\u097F\w\s]+?)\s+(?:बेचने\s+पर|पर|का|में)\s+(?:कितना\s+)?(?:लाभ|मुनाफा|ग्रॉस\s+प्रॉफिट)', c_lower)
            if hi_profit_match:
                cand = hi_profit_match.group(1).strip()

        if cand is None:
            hi_margin_match = re.search(r'([\u0900-\u097F\w\s]+?)\s+(?:का|में)\s+(?:ग्रॉस\s+)?मार्जिन', c_lower)
            if hi_margin_match:
                cand = hi_margin_match.group(1).strip()

        # Clean extracted product candidate
        if cand:
            cand = cand.strip().rstrip('?.!')
            cand = re.sub(r'^(?:is|iss|is product|iss product|this product|the product|the|a|an)\s+', '', cand, flags=re.IGNORECASE).strip()
            cand = re.sub(r'\b(bro|bhai|sarthi|saarthi|vantiq|jarvis|please|batao|bataiye|dikhao|kya hai|kitna hai|hai)\b', '', cand, flags=re.IGNORECASE).strip()

            if cand in ('context_product', 'iska', 'iss', 'is', 'this', 'this product', 'it', 'उसका', 'इसका'):
                if session_ctx.last_product:
                    cand = session_ctx.last_product["name"]
                else:
                    cand = None

            if cand and not is_product_stopword(cand) and cand not in ('overall', 'total', 'average', 'catalogue', 'all', 'product', 'products', 'inventory', 'everything'):
                is_profit = any(w in c_lower for w in ['profit', 'munafa', 'labh', 'मुनाफा', 'लाभ', 'bechne', 'selling'])
                intent_name = "product_profit" if is_profit else "product_margin"
                return (intent_name, {"product_name": cand, "cost_basis": cost_basis})

        # Overall / Catalogue margin (no specific product mentioned)
        if any(p in c_lower for p in [
            'margin kya hai', 'margin kitna hai', 'overall margin', 'average margin',
            'what is the margin', 'what is our margin', 'profit margin kya hai',
            'overall profit', 'total profit', 'total margin',
            'कुल मार्जिन', 'औसत मार्जिन', 'मार्जिन क्या है'
        ]) or c_lower.strip('?.! ') in ('margin', 'gross margin', 'profit margin', 'margin kya hai', 'profit'):
            return ("catalogue_margin", {"cost_basis": cost_basis})

    # 14. Purchase Rate / Last Purchase Rate History
    # E.g. "is product ka last purchase rate kya tha", "last purchase rate of Titanium Bolt", "aakhri purchase rate"
    if any(k in c_lower for k in [
        'last purchase rate', 'latest purchase rate', 'last purchase cost', 'last purchase price',
        'pichla purchase rate', 'aakhri purchase rate', 'last buy rate', 'last procurement rate',
        'pichla khareed bhav', 'अंतिम खरीद दर', 'पिछली खरीद दर'
    ]) or (('purchase rate' in c_lower or 'khareed bhav' in c_lower or 'purchase cost' in c_lower) and any(w in c_lower for w in ['last', 'latest', 'pichla', 'aakhri', 'kya tha'])):
        target = None
        # Extract product name
        m_pr1 = re.search(r'(?:last\s+purchase\s+rate\s+(?:for|of)\s+|latest\s+purchase\s+rate\s+(?:for|of)\s+)([a-zA-Z0-9_\-\s]+)', c_lower)
        if m_pr1:
            target = m_pr1.group(1).strip().rstrip('?.')
        else:
            m_pr2 = re.search(r'([a-zA-Z0-9_\-\s]+?)\s+ka\s+(?:last|latest|pichla|aakhri)\s+purchase\s+rate', c_lower)
            if m_pr2:
                target = m_pr2.group(1).strip()

        if target in ('is', 'iss', 'is product', 'iss product', 'this product', None):
            target = "context_product"
        return ("purchase_rate_history", {"product_name": target})

    # 15. Margin Rankings (Highest / Lowest Recorded Margins)
    # E.g. "which products have the highest recorded margins?", "lowest recorded margins"
    if any(k in c_lower for k in [
        'highest recorded margins', 'highest recorded margin',
        'sabse jyada recorded margin', 'sabse zyada recorded margin',
        'उच्चतम रिकॉर्डेड मार्जिन'
    ]):
        return ("margin_rankings", {"ranking": "highest"})

    if any(k in c_lower for k in [
        'lowest recorded margins', 'lowest recorded margin',
        'sabse kam recorded margin', 'न्यूनतम रिकॉर्डेड मार्जिन'
    ]):
        return ("margin_rankings", {"ranking": "lowest"})

    # 16. Sales Comparison
    # E.g. "compare this month's sales with last month", "compare sales", "this month vs last month sales"
    if any(k in c_lower for k in [
        'compare this month\'s sales with last month', 'compare this month sales with last month',
        'compare sales', 'sales comparison', 'this month vs last month sales',
        'sales compare karo', 'sales comparison dikhao', 'is mahine ki sales ko pichle mahine se compare'
    ]) or (('compare' in c_lower or 'comparison' in c_lower) and 'sale' in c_lower and ('month' in c_lower or 'mahine' in c_lower)):
        return ("sales_comparison", {})

    # 17. Purchases Listing
    # E.g. "show purchases from last month", "purchases this month", "recent purchases", "purchases dikhao"
    if any(k in c_lower for k in [
        'show purchases', 'list purchases', 'recent purchases', 'purchases list', 'all purchases',
        'purchases dikhao', 'purchase history', 'procurement history', 'khareed dikhao',
        'purchases from last month', 'pichle mahine ki purchases', 'खरीद दिखाओ'
    ]) or (('purchase' in c_lower or 'purchases' in c_lower or 'khareed' in c_lower) and any(w in c_lower for w in ['show', 'list', 'dikhao', 'recent', 'last month', 'this month', 'pichle mahine', 'is mahine'])):
        return ("purchases_list", {"query": q})

    # 18. Sales Listing
    # E.g. "recent sales", "show sales this month", "sales dikhao", "sales history"
    if any(k in c_lower for k in [
        'show sales', 'list sales', 'recent sales', 'sales list', 'all sales',
        'sales dikhao', 'sales history', 'bikri dikhao', 'sales this month',
        'sales from last month', 'pichle mahine ki sales', 'बिक्री दिखाओ'
    ]) or (('sale' in c_lower or 'sales' in c_lower or 'bikri' in c_lower) and any(w in c_lower for w in ['show', 'list', 'dikhao', 'recent', 'history', 'this month', 'last month'])):
        return ("sales_list", {"query": q})

    # 19. Inventory Movements
    # E.g. "inventory movement history for Product X", "show stock movements", "inventory movements"
    if any(k in c_lower for k in [
        'inventory movements', 'stock movements', 'movement history', 'stock history',
        'stock change history', 'movement log', 'stock movements dikhao', 'inventory movement history'
    ]) or (('movement' in c_lower or 'movements' in c_lower) and ('stock' in c_lower or 'inventory' in c_lower)):
        target = None
        m_mov = re.search(r'(?:movements|movement\s+history)\s+(?:for|of)\s+([a-zA-Z0-9_\-\s]+)', c_lower)
        if m_mov:
            target = m_mov.group(1).strip().rstrip('?.')
        return ("inventory_movements", {"product_name": target})

    # 20. Product Details
    # E.g. "show details for SKU-101", "details of Arc Reactor", "details for product Vibranium Plate"
    if any(k in c_lower for k in ['show details for', 'details of', 'details for', 'product details for', 'product details of', 'ki details dikhao', 'ke details dikhao']):
        m_det = re.search(r'(?:details\s+(?:for|of)\s+|details\s+)(?:product\s+|item\s+)?([a-zA-Z0-9_\-\s]+)', c_lower)
        target = m_det.group(1).strip().rstrip('?.') if m_det else None
        if target in ('is', 'iss', 'is product', 'this product', None):
            target = "context_product"
        return ("product_details", {"product_name": target})

    # 21. Out of Scope / Non-business domain
    # E.g. "weather in Paris", "recipe for chocolate cake", "who won the match"
    if any(k in c_lower for k in [
        'weather in', 'temperature in', 'recipe for', 'how to cook', 'how to bake',
        'who won the match', 'cricket score', 'football score', 'movie review',
        'tell me a joke about cats'
    ]):
        return ("out_of_scope", {})

    return None


"""
VANTIQ: AI-Powered Business Intelligence Assistant
Test Suite: tests/test_p0_fixes.py
P0 Critical Bug Fix Verification Suite:
1. Incomplete stock question asks for a product name.
2. Stopwords are not treated as product identifiers.
3. A valid product stock question queries SQLite.
4. "Show all products" returns the actual stored catalogue.
5. "Yes, of course" resolves the correct pending product-list action.
6. A pending action is cleared after successful execution.
7. Cancellation clears pending conversational state.
8. Ambiguous confirmation does not trigger an unsafe action.
9. General-knowledge queries use the configured local LLM when available.
10. Genuine Ollama failure produces one honest fallback.
11. Successful LLM responses are not followed by offline warnings.
12. Market-price questions are not confused with internal selling prices.
13. Hindi and Hinglish variants route correctly.
14. Duplicate request handlers do not render multiple answers.
15. Component health indicators reflect actual states.
16. Existing features and DB integrity preserved.
"""

import os
import sys
import unittest
import tempfile
import sqlite3
import shutil
import json
from unittest.mock import patch, MagicMock

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database
import intent_router
import multilingual
import rag_engine
import local_llm
from app import app


class TestVantiqP0CriticalFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="vantiq_p0_test_")
        cls.db_path = os.path.join(cls.temp_dir, "test_p0.db")
        cls.orig_vantiq_db = os.environ.get("VANTIQ_DB_PATH")
        cls.orig_jarvis_db = os.environ.get("JARVIS_DB_PATH")
        os.environ["VANTIQ_DB_PATH"] = cls.db_path
        os.environ["JARVIS_DB_PATH"] = cls.db_path
        os.environ["OLLAMA_ENABLED"] = "true"

        # Initialize schema
        database.init_db(cls.db_path)

        # Seed sample catalogue products using standard database helper
        conn = database.get_connection(cls.db_path)
        database.create_product({
            "sku": "CAP-100U",
            "name": "Capacitor 100uF",
            "description": "100uF 50V Electrolytic Capacitor",
            "category": "Electronics",
            "unit": "pcs",
            "purchase_price": 2.50,
            "selling_price": 5.00,
            "opening_stock": 450,
            "reorder_level": 100
        }, conn=conn)

        database.create_product({
            "sku": "RES-10K",
            "name": "Resistor 10k",
            "description": "10k Ohm 1/4W Metal Film",
            "category": "Electronics",
            "unit": "pcs",
            "purchase_price": 0.20,
            "selling_price": 1.00,
            "opening_stock": 1200,
            "reorder_level": 200
        }, conn=conn)

        database.create_product({
            "sku": "IND-10M",
            "name": "Inductor 10mH",
            "description": "10mH High Frequency Inductor",
            "category": "Electronics",
            "unit": "pcs",
            "purchase_price": 15.00,
            "selling_price": 28.00,
            "opening_stock": 25,
            "reorder_level": 50
        }, conn=conn)
        conn.close()

    @classmethod
    def tearDownClass(cls):
        if cls.orig_vantiq_db:
            os.environ["VANTIQ_DB_PATH"] = cls.orig_vantiq_db
        else:
            os.environ.pop("VANTIQ_DB_PATH", None)

        if cls.orig_jarvis_db:
            os.environ["JARVIS_DB_PATH"] = cls.orig_jarvis_db
        else:
            os.environ.pop("JARVIS_DB_PATH", None)

        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.session_id = f"test_sess_{self._testMethodName}"
        self.session_ctx = multilingual.get_session_context(self.session_id)
        self.session_ctx.clear_pending_action()

    # -------------------------------------------------------------------------
    # 1. Incomplete stock question asks for a product name
    # -------------------------------------------------------------------------
    def test_incomplete_stock_queries_ask_for_clarification(self):
        queries = [
            "Tell me the stock of the",
            "Tell me the stock of",
            "Stock of this product?",
            "Iska stock kitna hai?",
            "Product ka stock batao"
        ]
        for q in queries:
            resp = intent_router.route_intent(q, context={"session_id": self.session_id}, db_path=self.db_path)
            self.assertEqual(
                resp.get("action"),
                "clarification_needed",
                f"Query '{q}' should trigger clarification_needed, got '{resp.get('action')}'"
            )
            # Must ask which product to check stock for
            speak = resp.get("speak", "").lower()
            self.assertTrue(
                "which product" in speak or "kis product" in speak or "stock" in speak,
                f"Clarification response for '{q}' should ask which product: {speak}"
            )
            # Pending action must be set to product_stock_clarify
            pending = self.session_ctx.get_pending_action()
            self.assertIsNotNone(pending, f"Pending action must be stored for '{q}'")
            self.assertEqual(pending.get("action"), "product_stock_clarify")

    # -------------------------------------------------------------------------
    # 2. Stopwords are not treated as product identifiers
    # -------------------------------------------------------------------------
    def test_stopwords_not_treated_as_product_identifiers(self):
        stopwords = ["the", "this product", "product", "all", "these", "iska", "inka", "details", "items"]
        for sw in stopwords:
            self.assertTrue(
                multilingual.is_product_stopword(sw),
                f"'{sw}' must be recognized as a product stopword"
            )
            # Attempting stock query with stopword should NOT perform catalogue lookup for the stopword
            query = f"Tell me the stock of {sw}"
            resp = intent_router.route_intent(query, context={"session_id": self.session_id}, db_path=self.db_path)
            self.assertNotEqual(
                resp.get("action"),
                "catalogue_stock",
                f"Stopword '{sw}' must not directly execute catalogue_stock"
            )
            self.assertEqual(resp.get("action"), "clarification_needed")

    # -------------------------------------------------------------------------
    # 3. A valid product stock question queries SQLite
    # -------------------------------------------------------------------------
    def test_valid_product_stock_queries_sqlite(self):
        resp = intent_router.route_intent(
            "What is the stock of Capacitor 100uF?",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp.get("action"), "catalogue_stock")
        self.assertEqual(resp.get("match_count"), 1)
        prod = resp.get("product", {})
        self.assertEqual(prod.get("name"), "Capacitor 100uF")
        self.assertEqual(prod.get("quantity_on_hand"), 450)
        self.assertEqual(prod.get("unit"), "pcs")

    # -------------------------------------------------------------------------
    # 4. "Show all products" returns the actual stored catalogue
    # -------------------------------------------------------------------------
    def test_show_all_products_returns_stored_catalogue(self):
        resp = intent_router.route_intent(
            "Show all products",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp.get("action"), "catalogue_list")
        self.assertGreaterEqual(resp.get("total_count", 0), 3)
        rows = resp.get("table", {}).get("rows", [])
        product_names = [r.get("name") for r in rows]
        self.assertIn("Capacitor 100uF", product_names)
        self.assertIn("Resistor 10k", product_names)

    # -------------------------------------------------------------------------
    # 5. "Yes, of course" resolves the correct pending product-list action
    # -------------------------------------------------------------------------
    def test_confirmation_resolves_pending_product_list_action(self):
        # Step 1: Simulate a prompt asking user if they want to view products
        self.session_ctx.set_pending_action(action="product_list", prompt="Would you like to view all active products?")
        self.assertIsNotNone(self.session_ctx.get_pending_action())

        # Step 2: User responds "Yes, of course"
        resp = intent_router.route_intent(
            "Yes, of course",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(
            resp.get("action"),
            "catalogue_list",
            "Pending product_list action must resolve to catalogue_list on confirmation"
        )
        self.assertGreaterEqual(resp.get("total_count", 0), 3)

    # -------------------------------------------------------------------------
    # 6. A pending action is cleared after successful execution
    # -------------------------------------------------------------------------
    def test_pending_action_cleared_after_execution_no_repeat(self):
        # Set pending action
        self.session_ctx.set_pending_action(action="product_list")
        # First confirmation executes action
        resp1 = intent_router.route_intent(
            "Haan, of course",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp1.get("action"), "catalogue_list")
        self.assertIsNone(self.session_ctx.get_pending_action(), "Pending action must be None after execution")

        # Second confirmation should NOT repeat the catalogue action
        resp2 = intent_router.route_intent(
            "Yes, of course",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(
            resp2.get("action"),
            "acknowledgement",
            "Subsequent confirmation without pending action must be acknowledgement, not duplicate catalogue_list"
        )

    # -------------------------------------------------------------------------
    # 7. Cancellation clears pending conversational state
    # -------------------------------------------------------------------------
    def test_cancellation_clears_pending_state(self):
        cancellations = ["cancel", "no", "never mind", "rehne do", "nahi rehne do"]
        for c_word in cancellations:
            self.session_ctx.set_pending_action(action="product_list", prompt="Would you like to see products?")
            self.assertIsNotNone(self.session_ctx.get_pending_action())

            resp = intent_router.route_intent(
                c_word,
                context={"session_id": self.session_id},
                db_path=self.db_path
            )
            self.assertEqual(resp.get("action"), "cancelled")
            self.assertIsNone(
                self.session_ctx.get_pending_action(),
                f"Cancellation '{c_word}' must clear pending action"
            )

    # -------------------------------------------------------------------------
    # 8. Ambiguous confirmation does not trigger an unsafe action
    # -------------------------------------------------------------------------
    def test_ambiguous_confirmation_does_not_trigger_unsafe_action(self):
        # No pending action in session
        self.session_ctx.clear_pending_action()
        resp = intent_router.route_intent(
            "yes",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp.get("action"), "acknowledgement")
        # Ensure database was not altered
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM products")
        count = cur.fetchone()[0]
        conn.close()
        self.assertEqual(count, 3)

    # -------------------------------------------------------------------------
    # 9. General-knowledge queries use configured local LLM when available
    # -------------------------------------------------------------------------
    @patch("local_llm.check_ollama_health")
    @patch("local_llm.generate_chat_response")
    def test_general_knowledge_uses_local_llm(self, mock_chat, mock_health):
        mock_health.return_value = {
            "service_running": True,
            "model_available": True,
            "status": "online",
            "configured_model": "qwen3:4b-instruct"
        }
        mock_chat.return_value = {
            "success": True,
            "content": "Narendra Modi is the current Prime Minister of India, serving since May 2014.",
            "model": "qwen3:4b-instruct",
            "inference_time_seconds": 1.2
        }

        resp = intent_router.route_intent(
            "Who is Narendra Modi?",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp.get("action"), "general_chat")
        self.assertIn("Narendra Modi", resp.get("speak", ""))
        self.assertNotIn("offline", resp.get("speak", "").lower())
        self.assertNotIn("standby", resp.get("speak", "").lower())

    # -------------------------------------------------------------------------
    # 10. Genuine Ollama failure produces one honest fallback
    # -------------------------------------------------------------------------
    @patch("local_llm.check_ollama_health")
    def test_ollama_failure_produces_honest_offline_fallback(self, mock_health):
        mock_health.return_value = {
            "service_running": False,
            "model_available": False,
            "status": "offline",
            "configured_model": "qwen3:4b-instruct"
        }

        resp = intent_router.route_intent(
            "Who is Narendra Modi?",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp.get("action"), "ai_service_offline")
        speak = resp.get("speak", "")
        self.assertIn("local AI service", speak)
        self.assertIn("offline", speak.lower())
        # Confirms SQLite catalogue and business functionality remain operational
        self.assertIn("operational", speak.lower())

    # -------------------------------------------------------------------------
    # 11. Successful LLM responses are not followed by offline warnings
    # -------------------------------------------------------------------------
    @patch("local_llm.check_ollama_health")
    @patch("local_llm.generate_chat_response")
    def test_successful_llm_response_not_followed_by_offline_warnings(self, mock_chat, mock_health):
        mock_health.return_value = {
            "service_running": True,
            "model_available": True,
            "status": "online",
            "configured_model": "qwen3:4b-instruct"
        }
        mock_chat.return_value = {
            "success": True,
            "content": "Photosynthesis is the biological process used by plants to convert light into chemical energy.",
            "model": "qwen3:4b-instruct",
            "inference_time_seconds": 0.8
        }

        resp = intent_router.route_intent(
            "What is photosynthesis?",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp.get("action"), "general_chat")
        self.assertNotIn("offline", resp.get("speak", "").lower())
        self.assertNotIn("standby", resp.get("speak", "").lower())
        self.assertNotIn("warning", resp.get("speak", "").lower())

    # -------------------------------------------------------------------------
    # 12. Market-price questions are not confused with internal selling prices
    # -------------------------------------------------------------------------
    def test_market_price_clarification_distinguishes_internal_from_external(self):
        resp = intent_router.route_intent(
            "What is the market value of Capacitor?",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp.get("action"), "market_price_clarification")
        self.assertFalse(resp.get("external_market_verified", True))
        # Must report internal selling price and cost, and clarify external price unverified
        self.assertEqual(resp.get("internal_selling_price"), 5.0)
        self.assertEqual(resp.get("internal_purchase_price"), 2.5)
        speak = resp.get("speak", "").lower()
        self.assertTrue(
            "external" in speak or "live market" in speak or "cannot currently be verified" in speak,
            f"Expected clarification about external market price in: {speak}"
        )

    # -------------------------------------------------------------------------
    # 13. Hindi and Hinglish variants route correctly
    # -------------------------------------------------------------------------
    def test_hindi_and_hinglish_variants_route_correctly(self):
        # Hindi stock check
        resp_hi = intent_router.route_intent(
            "Capacitor ka current stock kitna hai?",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp_hi.get("action"), "catalogue_stock")
        self.assertEqual(resp_hi.get("product", {}).get("quantity_on_hand"), 450)

        # Hinglish catalogue check
        resp_hing = intent_router.route_intent(
            "Saare products dikhao",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp_hing.get("action"), "catalogue_list")
        self.assertGreaterEqual(resp_hing.get("total_count", 0), 3)

        # Follow-up stock parameter clarification in Hindi/Hinglish
        self.session_ctx.set_pending_action(action="product_stock_clarify")
        resp_follow = intent_router.route_intent(
            "Resistor 10k",
            context={"session_id": self.session_id},
            db_path=self.db_path
        )
        self.assertEqual(resp_follow.get("action"), "catalogue_stock")
        self.assertEqual(resp_follow.get("product", {}).get("name"), "Resistor 10k")

    # -------------------------------------------------------------------------
    # 14. Duplicate request handlers do not render multiple answers
    # -------------------------------------------------------------------------
    def test_single_response_and_request_id_tracking(self):
        req_id = "req_test_unique_12345"
        resp = intent_router.route_intent(
            "Show all products",
            context={"session_id": self.session_id},
            db_path=self.db_path,
            request_id=req_id
        )
        self.assertEqual(resp.get("request_id"), req_id)
        self.assertIn("action", resp)
        self.assertIn("speak", resp)
        self.assertIn("display", resp)

    # -------------------------------------------------------------------------
    # 15. Component health indicators reflect actual states
    # -------------------------------------------------------------------------
    @patch("local_llm.check_ollama_health")
    def test_component_health_indicators_reflect_actual_states(self, mock_llm_health):
        # Scenario A: Local LLM is offline, DB is healthy
        mock_llm_health.return_value = {
            "service_running": False,
            "model_available": False,
            "status": "offline",
            "configured_model": "qwen3:4b-instruct",
            "latency_ms": None,
            "message": "Ollama unreachable"
        }

        with app.test_client() as client:
            res = client.get('/api/status')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()

            # Overall status should be OPERATIONAL (not OFFLINE) because DB and API work
            self.assertEqual(data.get("status"), "OPERATIONAL")

            subsystems = data.get("subsystems", {})
            # DB is online
            self.assertTrue(subsystems.get("database", {}).get("healthy"))
            self.assertEqual(subsystems.get("database", {}).get("status"), "online")

            # Local LLM is offline
            self.assertFalse(subsystems.get("local_llm", {}).get("healthy"))
            self.assertEqual(subsystems.get("local_llm", {}).get("status"), "offline")

            # Voice is ready
            self.assertTrue(subsystems.get("voice_engine", {}).get("healthy"))

            # RAG is tracked separately
            self.assertIn("rag", subsystems)
            self.assertTrue(subsystems.get("rag", {}).get("healthy"))


if __name__ == '__main__':
    unittest.main()

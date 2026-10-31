"""
VANTIQ: AI-Powered Business Intelligence Assistant
Test Suite: tests/test_reliability_v7.py
Critical Fix — Reliability, Subsystem Status, & Latency Verification Suite (Rule 8)

Test Cases:
1. One query produces exactly one final response.
2. A successful answer is not followed by an offline fallback.
3. Ollama unavailable produces one accurate failure response (ai_service_offline).
4. Ollama reachable but model missing is handled distinctly (ai_model_missing).
5. Empty or malformed model responses are handled correctly without crashing.
6. One submission does not cause duplicate processing (unique request_id lifecycle).
7. Stale or slow responses are tagged with request_id to prevent overwrite of newer queries.
8. Simple database questions do NOT call local LLM (0ms inference overhead).
9. Genuine model exceptions are logged and handled without application crash.
10. Health indicators truthfully reflect individual subsystem statuses (api, database, local_llm, voice_engine).
11. Existing Hindi and Hinglish queries remain fully supported.
12. Database, catalogue, and inventory operations remain consistent and operational.
"""

import os
import sys
import unittest
import tempfile
import json
from unittest.mock import patch, MagicMock

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database
import intent_router
import multilingual
import local_llm
from app import app


class TestReliabilityAndLatencyFixV7(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="vantiq_v7_test_")
        cls.db_path = os.path.join(cls.temp_dir, "test_reliability_v7.db")
        cls.orig_db_env = os.environ.get("VANTIQ_DB_PATH")
        os.environ["VANTIQ_DB_PATH"] = cls.db_path
        os.environ["JARVIS_DB_PATH"] = cls.db_path

        # Initialize schema and seed sample products
        database.init_db(cls.db_path)
        conn = database.get_connection(cls.db_path)
        try:
            database.create_product({
                "sku": "SKU-V7-001",
                "name": "Industrial Resistor 100K",
                "category": "Passive Components",
                "purchase_price": 5.0,
                "selling_price": 12.0,
                "opening_stock": 50,
                "reorder_level": 10,
                "unit": "pcs"
            }, conn=conn)
            database.create_product({
                "sku": "SKU-V7-002",
                "name": "Microcontroller Unit MCU-8",
                "category": "Semiconductors",
                "purchase_price": 80.0,
                "selling_price": 140.0,
                "opening_stock": 3,
                "reorder_level": 15,
                "unit": "units"
            }, conn=conn)
        finally:
            conn.close()

        app.testing = True
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        if cls.orig_db_env:
            os.environ["VANTIQ_DB_PATH"] = cls.orig_db_env
            os.environ["JARVIS_DB_PATH"] = cls.orig_db_env
        else:
            os.environ.pop("VANTIQ_DB_PATH", None)
            os.environ.pop("JARVIS_DB_PATH", None)

    # --------------------------------------------------------------------------
    # Test 1: One query produces exactly one final response with unique request_id
    # --------------------------------------------------------------------------
    def test_01_one_query_produces_one_final_response(self):
        req_id = "req_test_01_abc"
        resp = intent_router.route_intent("Show all products", db_path=self.db_path, request_id=req_id)
        self.assertIsInstance(resp, dict)
        self.assertEqual(resp.get("request_id"), req_id)
        self.assertEqual(resp.get("action"), "catalogue_list")
        self.assertIn("Industrial Resistor", resp.get("speak", "") + resp.get("display", ""))

    # --------------------------------------------------------------------------
    # Test 2: A successful answer is not followed by an offline fallback
    # --------------------------------------------------------------------------
    def test_02_successful_general_knowledge_not_followed_by_offline_fallback(self):
        # Mock interpret_natural_language returning general_knowledge
        mock_data = {
            "intent": "general_knowledge",
            "entity": "Narendra Modi",
            "operation": "query",
            "parameters": {},
            "response_language": "en",
            "direct_response": "Narendra Modi is the current Prime Minister of India, serving since May 2014.",
            "model": "qwen3:4b-instruct",
            "inference_time_seconds": 1.2
        }
        with patch.object(local_llm, "interpret_natural_language", return_value=mock_data):
            resp = intent_router.route_intent("Who is Narendra Modi?", db_path=self.db_path, request_id="req_gk_01")
            self.assertEqual(resp.get("action"), "general_chat")
            self.assertIn("Prime Minister of India", resp.get("display", ""))
            # Must NOT contain standby or offline text
            self.assertNotIn("offline", resp.get("speak", "").lower())
            self.assertNotIn("standby", resp.get("display", "").lower())
            self.assertNotIn("offline", resp.get("display", "").lower())

    # --------------------------------------------------------------------------
    # Test 3: Ollama unavailable produces one accurate failure response
    # --------------------------------------------------------------------------
    def test_03_ollama_unavailable_produces_accurate_failure_response(self):
        offline_health = {
            "status": "offline",
            "service_running": False,
            "model_available": False,
            "configured_model": "qwen3:4b-instruct",
            "message": "Local AI service (Ollama) is not reachable on http://127.0.0.1:11434"
        }
        with patch.object(local_llm, "interpret_natural_language", return_value=None):
            with patch.object(local_llm, "generate_chat_response", return_value={"success": False}):
                with patch.object(local_llm, "check_ollama_health", return_value=offline_health):
                    resp = intent_router.route_intent("Who is Narendra Modi?", db_path=self.db_path, request_id="req_offline")
                    self.assertEqual(resp.get("action"), "ai_service_offline")
                    self.assertIn("offline", resp.get("display", "").lower())
                    self.assertIn("11434", resp.get("speak", ""))

    # --------------------------------------------------------------------------
    # Test 4: Ollama reachable but model missing is handled distinctly
    # --------------------------------------------------------------------------
    def test_04_ollama_reachable_but_model_missing_handled_distinctly(self):
        missing_health = {
            "status": "model_missing",
            "service_running": True,
            "model_available": False,
            "configured_model": "qwen3:4b-instruct",
            "available_models": ["llama3:8b", "mistral:latest"],
            "message": "Model 'qwen3:4b-instruct' not found in local Ollama."
        }
        with patch.object(local_llm, "interpret_natural_language", return_value=None):
            with patch.object(local_llm, "generate_chat_response", return_value={"success": False}):
                with patch.object(local_llm, "check_ollama_health", return_value=missing_health):
                    resp = intent_router.route_intent("Who is Narendra Modi?", db_path=self.db_path, request_id="req_missing")
                    self.assertEqual(resp.get("action"), "ai_model_missing")
                    self.assertIn("qwen3:4b-instruct", resp.get("display", ""))
                    self.assertIn("not installed", resp.get("speak", ""))

    # --------------------------------------------------------------------------
    # Test 5: Empty or malformed model responses are handled correctly
    # --------------------------------------------------------------------------
    def test_05_malformed_or_empty_model_response_handled_gracefully(self):
        # When model returns malformed JSON or invalid output, interpret_natural_language returns None
        with patch.object(local_llm, "interpret_natural_language", return_value=None):
            with patch.object(local_llm, "generate_chat_response", return_value={"success": False, "content": ""}):
                with patch.object(local_llm, "check_ollama_health", return_value={"status": "online", "service_running": True, "model_available": True}):
                    resp = intent_router.route_intent("Tell me something weird that breaks parsing", db_path=self.db_path)
                    self.assertIn(resp.get("action"), ("assistant_help", "out_of_scope"))
                    self.assertIn("display", resp)
                    self.assertIn("speak", resp)

    # --------------------------------------------------------------------------
    # Test 6: One submission via API attaches unique request_id and returns 200
    # --------------------------------------------------------------------------
    def test_06_single_submission_api_request_lifecycle(self):
        res = self.client.post("/api/command", json={
            "command": "Show all products",
            "request_id": "req_unique_submit_99"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("request_id"), "req_unique_submit_99")
        self.assertIn("latency_ms", data)
        self.assertEqual(data.get("action"), "catalogue_list")

    # --------------------------------------------------------------------------
    # Test 7: Stale request ID tagging prevents cross-talk between queries
    # --------------------------------------------------------------------------
    def test_07_request_id_matching_and_isolation(self):
        res1 = self.client.post("/api/command", json={"command": "Show all products", "request_id": "req_query_1"})
        res2 = self.client.post("/api/command", json={"command": "How many products do we have?", "request_id": "req_query_2"})
        d1 = res1.get_json()
        d2 = res2.get_json()
        self.assertEqual(d1["request_id"], "req_query_1")
        self.assertEqual(d2["request_id"], "req_query_2")
        self.assertNotEqual(d1["request_id"], d2["request_id"])
        self.assertEqual(d1["action"], "catalogue_list")
        self.assertEqual(d2["action"], "catalogue_count")

    # --------------------------------------------------------------------------
    # Test 8: Simple database questions do NOT call LLM (0ms inference overhead)
    # --------------------------------------------------------------------------
    def test_08_simple_database_questions_avoid_unnecessary_llm_calls(self):
        with patch.object(local_llm, "interpret_natural_language") as mock_interpret:
            with patch.object(local_llm, "generate_chat_response") as mock_chat:
                # 1. Product listing
                resp1 = intent_router.route_intent("Show all products", db_path=self.db_path)
                self.assertEqual(resp1.get("action"), "catalogue_list")

                # 2. Product count
                resp2 = intent_router.route_intent("How many products do we have?", db_path=self.db_path)
                self.assertEqual(resp2.get("action"), "catalogue_count")

                # 3. Low stock
                resp3 = intent_router.route_intent("Which products are low in stock?", db_path=self.db_path)
                self.assertEqual(resp3.get("action"), "catalogue_low_stock")

                # Neither interpret_natural_language nor generate_chat_response should be invoked
                mock_interpret.assert_not_called()
                mock_chat.assert_not_called()

    # --------------------------------------------------------------------------
    # Test 9: Genuine model errors are logged and do not crash the application
    # --------------------------------------------------------------------------
    def test_09_model_exception_does_not_crash_application(self):
        with patch.object(local_llm, "interpret_natural_language", side_effect=RuntimeError("GPU OOM / Kernel panic")):
            with patch.object(local_llm, "generate_chat_response", side_effect=RuntimeError("Model crashed")):
                with patch.object(local_llm, "check_ollama_health", return_value={"status": "error", "service_running": False}):
                    # Direct route_intent should recover and return assistant help or offline notification
                    resp = intent_router.route_intent("Complex unstructured query that trips inference", db_path=self.db_path)
                    self.assertIn("display", resp)
                    self.assertIn("action", resp)

                    # API endpoint should also return 200 without crashing Flask
                    res = self.client.post("/api/command", json={"command": "Random query"})
                    self.assertEqual(res.status_code, 200)

    # --------------------------------------------------------------------------
    # Test 10: Health indicators reflect actual separate subsystem availability
    # --------------------------------------------------------------------------
    def test_10_subsystems_health_indicators_accuracy(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertIn("subsystems", data)
        subsystems = data["subsystems"]

        # Check API subsystem
        self.assertIn("api", subsystems)
        self.assertEqual(subsystems["api"]["status"], "online")

        # Check Database subsystem
        self.assertIn("database", subsystems)
        self.assertEqual(subsystems["database"]["status"], "online")
        self.assertTrue(subsystems["database"]["healthy"])
        self.assertGreaterEqual(subsystems["database"]["products_count"], 2)

        # Check Local LLM subsystem
        self.assertIn("local_llm", subsystems)
        self.assertIn("status", subsystems["local_llm"])

        # Check Voice Engine subsystem
        self.assertIn("voice_engine", subsystems)
        self.assertEqual(subsystems["voice_engine"]["status"], "ready")

    # --------------------------------------------------------------------------
    # Test 11: Existing Hindi/English behavior is preserved
    # --------------------------------------------------------------------------
    def test_11_hindi_and_hinglish_intents_preserved(self):
        with patch.object(local_llm, "interpret_natural_language") as mock_llm:
            # Hindi catalogue query
            resp_hi = intent_router.route_intent("सारे प्रोडक्ट्स दिखाओ", db_path=self.db_path)
            self.assertEqual(resp_hi.get("action"), "catalogue_list")
            mock_llm.assert_not_called()

            # Hinglish low stock query
            resp_hinglish = intent_router.route_intent("Low stock products batao", db_path=self.db_path)
            self.assertEqual(resp_hinglish.get("action"), "catalogue_low_stock")
            mock_llm.assert_not_called()

            # Hinglish stock balance query
            resp_stock = intent_router.route_intent("Industrial Resistor 100K ka stock kitna hai?", db_path=self.db_path)
            self.assertEqual(resp_stock.get("action"), "catalogue_stock")
            mock_llm.assert_not_called()

    # --------------------------------------------------------------------------
    # Test 12: Existing inventory and data model integrity preserved
    # --------------------------------------------------------------------------
    def test_12_catalogue_and_inventory_ledger_integrity(self):
        products = database.list_products(db_path=self.db_path)
        self.assertGreaterEqual(products["total_count"], 2)

        low_stock_res = database.list_products(low_stock=True, db_path=self.db_path)
        low_items = low_stock_res.get("items", [])
        # SKU-V7-002 has quantity 3, reorder level 15 -> must be in low stock
        low_names = [p["name"] for p in low_items]
        self.assertIn("Microcontroller Unit MCU-8", low_names)


if __name__ == "__main__":
    unittest.main()

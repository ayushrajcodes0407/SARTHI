"""
Unit and integration tests for Gemma 4 E2B integration and Offline-First AI Response System.
Covers:
1. Dynamic model selection (qwen3:4b-instruct vs gemma4:e2b)
2. Graceful fallback when model is unavailable or encounters error
3. Offline-first architecture: loopback enforcement, metadata tracking (offline_mode, model_used)
4. Memory unloading via keep_alive: 0 to prevent RAM contention
5. End-to-end API endpoints (/api/llm/model, /api/llm/status, /api/command)
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import json
import local_llm
import intent_router
from app import app


class TestGemma4AndOfflineSystem(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        # Reset active model to default before each test
        local_llm._ACTIVE_MODEL = None

    def tearDown(self):
        local_llm._ACTIVE_MODEL = None

    def test_01_default_model_is_qwen3_and_gemma4_supported(self):
        """Verify default model remains qwen3:4b-instruct and gemma4:e2b is supported."""
        self.assertEqual(local_llm.DEFAULT_OLLAMA_MODEL, "qwen3:4b-instruct")
        self.assertEqual(local_llm.get_active_model(), "qwen3:4b-instruct")
        self.assertIn("qwen3:4b-instruct", local_llm.SUPPORTED_MODELS)
        self.assertIn("gemma4:e2b", local_llm.SUPPORTED_MODELS)
        self.assertEqual(local_llm.get_fallback_model("qwen3:4b-instruct"), "gemma4:e2b")
        self.assertEqual(local_llm.get_fallback_model("gemma4:e2b"), "qwen3:4b-instruct")

    def test_02_dynamic_model_selection_and_switch(self):
        """Verify setting active model updates config and fallback."""
        with patch.object(local_llm, "check_ollama_health", return_value={"service_running": True, "available_models": ["gemma4:e2b", "qwen3:4b-instruct"]}):
            with patch.object(local_llm, "unload_model", return_value=True) as mock_unload:
                ok, msg = local_llm.set_active_model("gemma4:e2b", unload_previous=True)
                self.assertTrue(ok)
                self.assertEqual(local_llm.get_active_model(), "gemma4:e2b")
                self.assertEqual(local_llm.get_fallback_model(), "qwen3:4b-instruct")
                # Displaced model qwen3:4b-instruct should have been unloaded
                mock_unload.assert_called_with("qwen3:4b-instruct")

    def test_03_invalid_model_selection_rejected(self):
        """Verify unavailable model selection returns error and preserves active model."""
        with patch.object(local_llm, "check_ollama_health", return_value={"service_running": True, "available_models": ["gemma4:e2b", "qwen3:4b-instruct"]}):
            ok, msg = local_llm.set_active_model("nonexistent_model_xyz:99b")
            self.assertFalse(ok)
            self.assertIn("not installed", msg)
            self.assertEqual(local_llm.get_active_model(), "qwen3:4b-instruct")

    def test_04_unload_model_sends_keep_alive_zero(self):
        """Verify unload_model posts keep_alive: 0 to Ollama /api/generate."""
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            success = local_llm.unload_model("gemma4:e2b")
            self.assertTrue(success)
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertIn("/api/generate", args[0])
            self.assertEqual(kwargs["json"], {"model": "gemma4:e2b", "keep_alive": 0})

    def test_05_interpret_natural_language_primary_success(self):
        """Verify successful interpretation with active model returns offline_mode and no fallback."""
        fake_response = {
            "message": {
                "content": json.dumps({
                    "intent": "product_stock",
                    "entity": "Capacitor",
                    "operation": "query",
                    "parameters": {"product_name": "Capacitor"}
                })
            }
        }
        with patch.object(local_llm, "check_ollama_health", return_value={"service_running": True, "model_available": True}):
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = fake_response
                res = local_llm.interpret_natural_language("Capacitor ka stock kitna hai")
                self.assertIsNotNone(res)
                self.assertEqual(res["intent"], "product_stock")
                self.assertEqual(res["entity"], "Capacitor")
                self.assertEqual(res["model"], "qwen3:4b-instruct")
                self.assertFalse(res["fallback_triggered"])
                self.assertTrue(res["offline_mode"])

    def test_06_interpret_natural_language_graceful_fallback(self):
        """Verify that when primary model fails, fallback model is seamlessly invoked."""
        fake_fallback_resp = {
            "message": {
                "content": json.dumps({
                    "intent": "product_list",
                    "entity": "catalogue",
                    "operation": "query",
                    "parameters": {}
                })
            }
        }
        # Simulate primary model HTTP 500 error, then fallback model succeeds
        with patch.object(local_llm, "check_ollama_health", return_value={"service_running": True, "model_available": True, "available_models": ["qwen3:4b-instruct", "gemma4:e2b"]}):
            with patch("requests.post") as mock_post:
                mock_primary_fail = MagicMock(status_code=500, text="GPU OOM")
                mock_fallback_ok = MagicMock(status_code=200)
                mock_fallback_ok.json.return_value = fake_fallback_resp
                mock_post.side_effect = [mock_primary_fail, mock_fallback_ok]

                res = local_llm.interpret_natural_language("Show all products")
                self.assertIsNotNone(res)
                self.assertEqual(res["intent"], "product_list")
                self.assertEqual(res["model"], "gemma4:e2b")
                self.assertTrue(res["fallback_triggered"])
                self.assertTrue(res["offline_mode"])

    def test_07_generate_explanation_fallback_to_deterministic_kb(self):
        """Verify explanation falls back to deterministic offline KB when both models fail."""
        with patch.object(local_llm, "check_ollama_health", return_value={"service_running": False, "model_available": False}):
            res = local_llm.generate_explanation("gross margin", language="English")
            self.assertTrue(res["success"])
            self.assertEqual(res["model"], "local_knowledge_base")
            self.assertIn("Gross margin", res["content"])
            self.assertTrue(res["offline_mode"])
            self.assertTrue(res["fallback_triggered"])

    def test_08_api_llm_model_endpoints(self):
        """Verify GET and POST /api/llm/model endpoints."""
        # 1. GET
        with patch.object(local_llm, "check_ollama_health", return_value={"service_running": True, "available_models": ["qwen3:4b-instruct", "gemma4:e2b"], "loaded_models": []}):
            res = self.app.get('/api/llm/model')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["active_model"], "qwen3:4b-instruct")
            self.assertEqual(data["fallback_model"], "gemma4:e2b")
            self.assertTrue(data["offline_mode"])

        # 2. POST switch to gemma4:e2b
        with patch.object(local_llm, "check_ollama_health", return_value={"service_running": True, "available_models": ["qwen3:4b-instruct", "gemma4:e2b"], "loaded_models": []}):
            with patch.object(local_llm, "unload_model", return_value=True):
                res2 = self.app.post('/api/llm/model', json={"model": "gemma4:e2b"})
                self.assertEqual(res2.status_code, 200)
                data2 = res2.get_json()
                self.assertEqual(data2["active_model"], "gemma4:e2b")
                self.assertEqual(data2["fallback_model"], "qwen3:4b-instruct")

    def test_09_command_endpoint_offline_metadata(self):
        """Verify /api/command returns offline_mode: True and records active_model."""
        resp = self.app.post('/api/command', json={"command": "How many products do we have?"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("offline_mode"))
        self.assertIn("active_model", data)
        self.assertIn("action", data)

    def test_10_deterministic_inventory_pipeline_preserved(self):
        """Verify deterministic inventory and catalogue functions remain intact."""
        resp = intent_router.route_intent("Show all products")
        self.assertEqual(resp.get("action"), "catalogue_list")
        self.assertTrue(resp.get("offline_mode"))
        self.assertIn("active_model", resp)


if __name__ == "__main__":
    unittest.main()


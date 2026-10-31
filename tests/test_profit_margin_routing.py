"""
Automated Regression Test Suite for VANTIQ Profit & Margin Calculations and Business Query Routing.

Requirements tested (Section 7):
1. Product profit using recorded purchase and selling prices.
2. Product gross margin percentage.
3. Margin calculation when selling price is zero.
4. Missing purchase price.
5. Missing selling price.
6. Last-purchase-rate-based profit when explicitly requested.
7. Product not found.
8. Ambiguous product name.
9. Hindi/Hinglish profit query.
10. General-knowledge queries still reaching the appropriate handler.
11. Existing stock queries remaining correct.
12. Existing catalogue and pricing queries remaining correct.
13. Business queries working when Ollama is unavailable.
14. No duplicate or contradictory responses.
"""

import os
import sys
import unittest
import tempfile
import sqlite3

# Ensure UTF-8 output if possible
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add workspace to sys.path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

import database
import business_insights
import multilingual
from intent_router import route_intent


class TestProfitAndMarginCalculations(unittest.TestCase):
    """Unit tests for calculation logic in business_insights.py."""

    def test_01_profit_using_recorded_purchase_and_selling_prices(self):
        """1. Product profit using recorded purchase and selling prices."""
        product = {
            "name": "Capacitor",
            "selling_price": 10000.0,
            "purchase_price": 999.0,
            "last_purchase_rate": None,
        }
        res = business_insights.calculate_product_profit_and_margin(product, cost_basis="purchase_price")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["cost_basis"], "purchase_price")
        self.assertAlmostEqual(res["profit_per_unit"], 9001.0, places=2)
        self.assertAlmostEqual(res["gross_margin_pct"], 90.01, places=2)
        self.assertAlmostEqual(res["markup_pct"], 901.0, places=1)

    def test_02_product_gross_margin_percentage(self):
        """2. Product gross margin percentage."""
        product = {
            "name": "Chair",
            "selling_price": 384.82,
            "purchase_price": 27.95,
            "last_purchase_rate": None,
        }
        res = business_insights.calculate_product_profit_and_margin(product, cost_basis="purchase_price")
        self.assertEqual(res["status"], "success")
        expected_profit = 384.82 - 27.95
        expected_margin = (expected_profit / 384.82) * 100.0
        self.assertAlmostEqual(res["profit_per_unit"], expected_profit, places=2)
        self.assertAlmostEqual(res["gross_margin_pct"], expected_margin, places=2)

    def test_03_margin_calculation_when_selling_price_is_zero(self):
        """3. Margin calculation when selling price is zero."""
        product = {
            "name": "Free Sample",
            "selling_price": 0.0,
            "purchase_price": 10.0,
            "last_purchase_rate": 8.0,
        }
        res = business_insights.calculate_product_profit_and_margin(product, cost_basis="purchase_price")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["gross_margin_pct"], 0.0)
        self.assertEqual(res["profit_per_unit"], -10.0)
        self.assertIn("Selling price is 0.00", res["notes"])

    def test_04_missing_purchase_price(self):
        """4. Missing purchase price."""
        product = {
            "name": "Unknown Cost Product",
            "selling_price": 500.0,
            "purchase_price": None,
            "last_purchase_rate": None,
        }
        res = business_insights.calculate_product_profit_and_margin(product, cost_basis="purchase_price")
        self.assertEqual(res["status"], "missing_cost_basis")
        self.assertIsNone(res["profit_per_unit"])
        self.assertIsNone(res["gross_margin_pct"])
        self.assertIn("purchase price", res["message"].lower())

    def test_05_missing_selling_price(self):
        """5. Missing selling price."""
        product = {
            "name": "Unpriced Product",
            "selling_price": None,
            "purchase_price": 200.0,
            "last_purchase_rate": None,
        }
        res = business_insights.calculate_product_profit_and_margin(product, cost_basis="purchase_price")
        self.assertEqual(res["status"], "missing_selling_price")
        self.assertIsNone(res["profit_per_unit"])
        self.assertIsNone(res["gross_margin_pct"])
        self.assertIn("selling price", res["message"].lower())

    def test_06_last_purchase_rate_based_profit_when_explicitly_requested(self):
        """6. Last-purchase-rate-based profit when explicitly requested."""
        product_with_last_rate = {
            "name": "Widget A",
            "selling_price": 150.0,
            "purchase_price": 80.0,
            "last_purchase_rate": 90.0,
        }
        res = business_insights.calculate_product_profit_and_margin(product_with_last_rate, cost_basis="last_purchase_rate")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["cost_basis"], "last_purchase_rate")
        self.assertEqual(res["effective_cost"], 90.0)
        self.assertEqual(res["profit_per_unit"], 60.0)
        self.assertAlmostEqual(res["gross_margin_pct"], 40.0, places=1)
        self.assertTrue("procurement rate" in res["notes"].lower() or "purchase rate" in res["notes"].lower())

        # And if last_purchase_rate is None:
        product_without_last_rate = {
            "name": "Widget B",
            "selling_price": 150.0,
            "purchase_price": 80.0,
            "last_purchase_rate": None,
        }
        res2 = business_insights.calculate_product_profit_and_margin(product_without_last_rate, cost_basis="last_purchase_rate")
        self.assertEqual(res2["status"], "missing_cost_basis")
        self.assertTrue("procurement rate" in res2["message"].lower() or "purchase rate" in res2["message"].lower())


class TestRoutingAndDatabaseIntegration(unittest.TestCase):
    """Integration tests with a dedicated SQLite database fixture."""

    @classmethod
    def setUpClass(cls):
        # Create an isolated temporary test database with full schema
        cls.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls.db_path = cls.temp_db.name
        cls.temp_db.close()

        # Initialize full schema
        database.init_db(cls.db_path)

        conn = database.get_connection(cls.db_path)
        cur = conn.cursor()

        # Insert test products with timestamp fields
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        cur.executemany("""
            INSERT INTO products (sku, name, purchase_price, selling_price, last_purchase_rate, last_purchase_date, unit, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            ("CAP-20", "Capacitor", 999.0, 10000.0, None, None, "pcs", now, now),
            ("CHR-01", "Chair", 27.95, 384.82, None, None, "units", now, now),
            ("TBL-WOOD", "Oak Table", 50.0, 100.0, 55.0, "2026-01-15", "units", now, now),
            ("TBL-GLASS", "Glass Table", 80.0, 150.0, 85.0, "2026-02-01", "units", now, now),
            ("RES-10", "Resistor", 5.0, 0.0, 4.0, None, "pcs", now, now),
            ("LED-01", "LED Strip", None, 120.0, None, None, "rolls", now, now),
        ])

        # Also insert initial stock into inventory table
        cur.execute("SELECT id, sku FROM products")
        prods = cur.fetchall()
        stock_map = {"CAP-20": 150.0, "CHR-01": 45.0, "TBL-WOOD": 10.0, "TBL-GLASS": 5.0, "RES-10": 500.0, "LED-01": 25.0}
        for pid, sku in prods:
            qty = stock_map.get(sku, 0.0)
            cur.execute("INSERT OR REPLACE INTO inventory (product_id, quantity_on_hand, reorder_level, updated_at) VALUES (?, ?, ?, ?)", (pid, qty, 5.0, now))

        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass

    def test_07_product_not_found(self):
        """7. Product not found returns appropriate message and options."""
        res = route_intent("What is the profit of Quantum Processor?", db_path=self.db_path)
        self.assertEqual(res.get("action"), "product_not_found")
        text = (res.get("display") or "") + " " + (res.get("speak") or "")
        self.assertTrue("not found in the catalogue" in text.lower() or "no match" in text.lower())
        self.assertTrue("available products" in text.lower() or res.get("follow_ups") is not None)

    def test_08_ambiguous_product_name(self):
        """8. Ambiguous product name prompts user to select correct product."""
        # Querying "Table" matches both "Oak Table" and "Glass Table"
        res = route_intent("What is the margin on Table?", db_path=self.db_path)
        self.assertIn(res.get("action"), ["product_margin", "product_profit"])
        self.assertEqual(res.get("status"), "multiple_matches")
        self.assertGreater(res.get("match_count", 0), 1)
        text = (res.get("display") or "") + " " + (res.get("speak") or "")
        self.assertIn("multiple products match", text.lower())
        self.assertTrue(len(res.get("candidate_products", [])) >= 2)

    def test_09_hindi_hinglish_profit_queries(self):
        """9. Hindi/Hinglish profit queries route and calculate correctly."""
        # Hinglish: "Capacitor bechne par kitna profit hai?"
        res1 = route_intent("Capacitor bechne par kitna profit hai?", db_path=self.db_path)
        self.assertEqual(res1.get("action"), "product_profit")
        self.assertEqual(res1.get("status"), "success")
        self.assertIn("Capacitor", res1.get("product_name"))
        self.assertEqual(res1.get("profit_per_unit"), 9001.0)

        # Hinglish: "Chair ka margin kitna hai?"
        res2 = route_intent("Chair ka margin kitna hai?", db_path=self.db_path)
        self.assertIn(res2.get("action"), ["product_margin", "product_profit"])
        self.assertEqual(res2.get("status"), "success")
        self.assertIn("Chair", res2.get("product_name"))
        self.assertAlmostEqual(res2.get("gross_margin_pct"), 92.74, places=1)

    def test_10_general_knowledge_queries_reach_appropriate_handler(self):
        """10. General-knowledge queries still reach the appropriate LLM handler."""
        # Multilingual matcher should not classify general queries as business financial intents
        matched = multilingual.match_multilingual_intent("Who is Narendra Modi?")
        if matched:
            self.assertNotIn(matched[0], ["product_profit", "product_margin", "product_stock", "product_price"])

        # Intent router should not route to product financial action
        res = route_intent("Who is Narendra Modi?", db_path=self.db_path)
        self.assertNotIn(res.get("action"), ["product_profit", "product_margin", "catalogue_stock", "catalogue_price", "catalogue_selling_price"])

    def test_11_existing_stock_queries_remain_correct(self):
        """11. Existing stock queries remaining correct."""
        res = route_intent("WHAT IS CURRENT STOCK OF CAPACITOR", db_path=self.db_path)
        self.assertEqual(res.get("action"), "catalogue_stock")
        text = (res.get("display") or "") + " " + (res.get("speak") or "")
        self.assertIn("150", text)
        self.assertIn("Capacitor", text)

    def test_12_existing_catalogue_and_pricing_queries_remain_correct(self):
        """12. Existing catalogue and pricing queries remaining correct."""
        res_price = route_intent("What is the selling price of Capacitor?", db_path=self.db_path)
        self.assertIn(res_price.get("action"), ["catalogue_selling_price", "catalogue_price", "product_pricing"])
        text_price = (res_price.get("display") or "") + " " + (res_price.get("speak") or "")
        self.assertIn("10,000", text_price)

        res_cat = route_intent("Show me all products", db_path=self.db_path)
        self.assertIn(res_cat.get("action"), ["catalogue_list", "product_catalog", "low_stock"])
        text_cat = (res_cat.get("display") or "") + " " + (res_cat.get("speak") or "")
        self.assertIn("Capacitor", text_cat)

    def test_13_business_queries_work_when_ollama_unavailable(self):
        """13. Business queries working when Ollama is unavailable."""
        old_env = os.environ.get("OLLAMA_ENABLED")
        os.environ["OLLAMA_ENABLED"] = "false"
        try:
            # Profit query with Ollama disabled
            res = route_intent("What is the profit of Capacitor?", db_path=self.db_path)
            self.assertEqual(res.get("action"), "product_profit")
            self.assertEqual(res.get("profit_per_unit"), 9001.0)

            # Margin query with Ollama disabled
            res_margin = route_intent("What is the margin on Chair?", db_path=self.db_path)
            self.assertEqual(res_margin.get("action"), "product_margin")
            self.assertAlmostEqual(res_margin.get("gross_margin_pct"), 92.74, places=1)
        finally:
            if old_env is not None:
                os.environ["OLLAMA_ENABLED"] = old_env
            else:
                os.environ.pop("OLLAMA_ENABLED", None)

    def test_14_no_duplicate_or_contradictory_responses(self):
        """14. No duplicate or contradictory responses."""
        res = route_intent("What is the profit selling a Capacitor?", db_path=self.db_path)
        text = (res.get("display") or "") + " " + (res.get("speak") or "")
        self.assertNotIn("Gross margin is the difference between revenue and COGS", text)
        self.assertNotIn("A capacitor does not generate profit", text)
        self.assertIn("9,001.00", text)


if __name__ == "__main__":
    unittest.main()

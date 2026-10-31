"""
SARTHI: Instant Business Intelligence Response Optimization Unit Tests
Verifies structured data analysis before RAG, semantic separation of inventory vs. sales,
multilingual & Hinglish query routing, deterministic calculations on real dataset,
and concise professional conversational responses without raw spreadsheet dumps.
"""

import unittest
import intent_router
import database
import business_insights

class TestInstantBusinessIntelligence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset_id = "ds_522fdc1c0af1"
        cls.df, cls.ds = database.load_dataset_dataframe(cls.dataset_id)
        assert cls.df is not None, f"Dataset {cls.dataset_id} must be loaded for real data tests"

    def test_01_stock_of_chair(self):
        """Scenario 1: What is the stock of Chair? -> Direct catalogue inventory answer."""
        resp = intent_router.route_intent("What is the stock of Chair?")
        self.assertEqual(resp.get("action"), "catalogue_stock")
        self.assertEqual(resp.get("source_type"), "catalogue")
        disp = resp.get("display", "")
        self.assertIn("Chair", disp)
        self.assertIn("18", disp)
        self.assertIn("in stock", disp)
        # Verify no raw document chunk leaks
        self.assertNotIn("Columns:", disp)
        self.assertNotIn("Sheet1", disp)

    def test_02_hinglish_chair_quantity(self):
        """Scenario 2: Chair kitne hai? -> Understands Hinglish, retrieves stock & clarifies sales volume."""
        resp = intent_router.route_intent("Chair kitne hai")
        self.assertEqual(resp.get("action"), "catalogue_stock")
        disp = resp.get("display", "")
        self.assertIn("18", disp)
        self.assertIn("in stock", disp)
        # Should also note sales volume to prevent inventory vs sales confusion
        self.assertIn("2,122", disp)
        self.assertIn("sold", disp)
        self.assertNotIn("Columns:", disp)

    def test_03_chair_sold_quantity(self):
        """Scenario 3: What is the total quantity of Chair sold? -> Exact units sold from dataset."""
        resp = intent_router.route_intent("What is the total quantity of Chair sold?")
        self.assertEqual(resp.get("action"), "product_sales_volume")
        self.assertEqual(resp.get("source_type"), "dataset")
        disp = resp.get("display", "")
        self.assertIn("2,122", disp)
        self.assertIn("units sold", disp)
        self.assertIn("209", disp)
        self.assertNotIn("Columns:", disp)

    def test_04_chair_total_revenue(self):
        """Scenario 4: Show total revenue of Chair -> Exact revenue calculation."""
        resp = intent_router.route_intent("Show total revenue of Chair")
        self.assertEqual(resp.get("action"), "product_sales_revenue")
        self.assertEqual(resp.get("source_type"), "dataset")
        disp = resp.get("display", "")
        self.assertIn("622,589.48", disp)
        self.assertNotIn("Columns:", disp)

    def test_05_highest_sales_product(self):
        """Scenario 5: Which product has the highest sales? -> Deterministic ranking identifies Tablet."""
        resp = intent_router.route_intent("Which product generated the highest revenue?")
        self.assertEqual(resp.get("action"), "top_sales_product")
        disp = resp.get("display", "")
        self.assertIn("Tablet", disp)
        self.assertIn("684,539.39", disp)
        self.assertNotIn("Columns:", disp)

    def test_06_sales_by_region(self):
        """Scenario 6: Show total sales by region -> Regional breakdown with North leading."""
        resp = intent_router.route_intent("Show total sales by region")
        self.assertEqual(resp.get("action"), "sales_by_region")
        disp = resp.get("display", "")
        speak = resp.get("speak", "")
        self.assertIn("North", speak)
        self.assertIn("967,957.98", speak)
        self.assertIn("1,500", disp)
        self.assertNotIn("Columns:", disp)

    def test_07_monthly_revenue_trends(self):
        """Scenario 7: Show monthly revenue -> 30-month trend aggregation with peak in 2023-03."""
        resp = intent_router.route_intent("Show monthly revenue")
        self.assertEqual(resp.get("action"), "monthly_sales_trends")
        disp = resp.get("display", "")
        self.assertIn("30 months", disp)
        self.assertIn("2023-03", disp)
        self.assertIn("208,548.70", disp)
        self.assertNotIn("Columns:", disp)

    def test_08_lowest_sales_products(self):
        """Scenario 8: Which products have the lowest sales? -> Identifies Phone and Desk."""
        resp = intent_router.route_intent("Which products have the lowest sales?")
        self.assertEqual(resp.get("action"), "lowest_sales_product")
        disp = resp.get("display", "")
        self.assertIn("Phone", disp)
        self.assertIn("497,162.85", disp)
        self.assertNotIn("Columns:", disp)

    def test_09_compare_chair_and_monitor(self):
        """Scenario 9: Compare Chair and Monitor sales -> Direct side-by-side comparison."""
        resp = intent_router.route_intent("Compare Chair and Monitor sales")
        self.assertEqual(resp.get("action"), "compare_product_sales")
        disp = resp.get("display", "")
        speak = resp.get("speak", "")
        self.assertIn("Monitor", disp)
        self.assertIn("Chair", disp)
        self.assertIn("651,629.39", disp)
        self.assertIn("622,589.48", disp)
        self.assertIn("29,039.91", disp)
        self.assertNotIn("Columns:", disp)

    def test_10_summarize_dataset(self):
        """Scenario 10: Summarize the uploaded dataset -> 1,500 rows, 19 columns, 7 products, 5 regions."""
        resp = intent_router.route_intent("Summarize the uploaded dataset")
        self.assertEqual(resp.get("action"), "dataset_summary")
        disp = resp.get("display", "")
        self.assertTrue("1500 Rows" in disp or "1,500 Rows" in disp)
        self.assertIn("19 Columns", disp)
        self.assertNotIn("Columns:", disp)

    def test_11_semantic_separation_inventory_vs_sales(self):
        """Verify inventory stock (18 units) is NEVER confused with sales volume (2,122 units)."""
        stock_resp = intent_router.route_intent("What is the stock of Chair?")
        sales_resp = intent_router.route_intent("What is the total quantity of Chair sold?")

        # Stock response must have 18 units, not 2,122 units
        self.assertIn("18", stock_resp.get("display", ""))
        self.assertNotIn("2,122 units in stock", stock_resp.get("display", ""))

        # Sales response must have 2,122 units, not 18 units
        self.assertIn("2,122", sales_resp.get("display", ""))
        self.assertNotIn("18 units sold", sales_resp.get("display", ""))

    def test_12_inventory_availability_maal(self):
        """Verify Hinglish 'kitna maal available hai' routes to inventory summary."""
        resp = intent_router.route_intent("kitna maal available hai")
        self.assertEqual(resp.get("action"), "inventory_summary")
        disp = resp.get("display", "")
        self.assertIn("Inventory:", disp)
        self.assertIn("items", disp)
        self.assertIn("Stock:", disp)

if __name__ == "__main__":
    unittest.main()

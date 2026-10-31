"""
SARTHI: Comprehensive Statistical Engine & File Mapping Intelligence Audit
Tests all descriptive statistics, data quality scoring, mathematical precision,
file mapping confidence, and commercial analytics.
"""

import unittest
import numpy as np
import pandas as pd
import math

from business_insights import (
    compute_descriptive_statistics,
    profile_columns,
    get_column_mappings_with_confidence,
    audit_data_quality,
    compute_pricing_analytics,
    calculate_product_profit_and_margin,
    compute_inventory_analytics,
    compute_sales_analytics,
    compute_correlation_matrix,
    map_column_roles
)

class TestStatisticalAndMappingAudit(unittest.TestCase):
    def setUp(self):
        # Known ground-truth dataset with verified analytical values
        # Data: [10, 20, 20, 40, 50, 60, 80]
        # n = 7
        # sum = 280
        # mean = 280 / 7 = 40.0
        # median = 40.0
        # mode = 20.0
        # min = 10.0, max = 80.0, range = 70.0
        # deviations: [-30, -20, -20, 0, 10, 20, 40]
        # sq deviations: [900, 400, 400, 0, 100, 400, 1600] -> sum = 3800
        # sample variance (ddof=1) = 3800 / 6 = 633.3333
        # sample std = sqrt(633.3333) = 25.1661
        # Q1 (25th percentile) = 20.0
        # Q3 (75th percentile) = 55.0
        # IQR = 55.0 - 20.0 = 35.0
        self.known_numbers = [10, 20, 20, 40, 50, 60, 80]

    def test_descriptive_statistics_known_values(self):
        """Verify exact mathematical values of descriptive statistics against analytical proof."""
        stats = compute_descriptive_statistics(self.known_numbers)
        
        self.assertEqual(stats["count"], 7)
        self.assertEqual(stats["null_count"], 0)
        self.assertAlmostEqual(stats["mean"], 40.0, places=3)
        self.assertAlmostEqual(stats["median"], 40.0, places=3)
        self.assertAlmostEqual(stats["mode"], 20.0, places=3)
        self.assertEqual(stats["min"], 10.0)
        self.assertEqual(stats["max"], 80.0)
        self.assertEqual(stats["range"], 70.0)
        self.assertAlmostEqual(stats["variance"], 633.3333, places=3)
        self.assertAlmostEqual(stats["std"], 25.1661, places=3)
        self.assertAlmostEqual(stats["q25"], 20.0, places=3)
        self.assertAlmostEqual(stats["q75"], 55.0, places=3)
        self.assertAlmostEqual(stats["iqr"], 35.0, places=3)
        self.assertEqual(stats["outlier_count"], 0)

    def test_outlier_detection_tukey_rule(self):
        """Verify Tukey 1.5*IQR outlier identification with known outlier values."""
        # [10, 20, 20, 40, 50, 60, 80, 500] -> 500 is > Q3 + 1.5*IQR
        data_with_outlier = [10, 20, 20, 40, 50, 60, 80, 500]
        stats = compute_descriptive_statistics(data_with_outlier)
        self.assertGreaterEqual(stats["outlier_count"], 1)

    def test_empty_and_null_numeric_series_safety(self):
        """Verify that zero-length and all-null series return safe zeros and do not crash."""
        empty_stats = compute_descriptive_statistics([])
        self.assertEqual(empty_stats["count"], 0)
        self.assertIsNone(empty_stats["mean"])

        null_stats = compute_descriptive_statistics([None, np.nan, "N/A"])
        self.assertEqual(null_stats["count"], 0)
        self.assertEqual(null_stats["null_count"], 3)
        self.assertIsNone(null_stats["mean"])

    def test_column_profiling_and_types(self):
        """Verify column profiling correctly detects Integers, Floats, Dates, and Categories."""
        df = pd.DataFrame({
            "SKU": ["A1", "A2", "A3"],
            "Quantity": [10, 25, 50],
            "Price": [19.99, 49.50, 99.00],
            "Order_Date": ["2026-01-10", "2026-02-15", "2026-03-20"],
            "Active": [True, True, False]
        })
        profiles = profile_columns(df)
        types_by_col = {p["name"]: p["inferred_type"] for p in profiles}

        self.assertEqual(types_by_col["SKU"], "text")
        self.assertEqual(types_by_col["Quantity"], "numeric")
        self.assertEqual(types_by_col["Price"], "numeric")
        self.assertEqual(types_by_col["Order_Date"], "date")
        self.assertEqual(types_by_col["Active"], "boolean")

    def test_pricing_and_margin_mathematical_precision(self):
        """Verify gross profit, gross margin %, and markup % calculations."""
        record = {
            "name": "Industrial Sensor",
            "selling_price": 200.0,
            "purchase_price": 120.0,
            "currency": "INR"
        }
        res = calculate_product_profit_and_margin(record)
        self.assertTrue(res["success"])
        # Gross profit = 200 - 120 = 80
        # Gross margin = (80 / 200) * 100 = 40.0%
        # Markup = (80 / 120) * 100 = 66.6667%
        self.assertAlmostEqual(res["gross_profit_per_unit"], 80.0, places=2)
        self.assertAlmostEqual(res["gross_margin_pct"], 40.0, places=2)
        self.assertAlmostEqual(res["markup_pct"], 66.67, places=2)

    def test_pricing_division_by_zero_handling(self):
        """Verify division-by-zero protection when selling price or cost is zero."""
        zero_sp = {
            "name": "Complimentary Sample",
            "selling_price": 0.0,
            "purchase_price": 25.0
        }
        res_sp = calculate_product_profit_and_margin(zero_sp)
        self.assertTrue(res_sp["success"])
        # Margin % cannot divide by 0 selling price; returns safe 0.0 with warning note
        self.assertEqual(res_sp["gross_margin_pct"], 0.0)

        zero_cp = {
            "name": "Donated Asset",
            "selling_price": 100.0,
            "purchase_price": 0.0
        }
        res_cp = calculate_product_profit_and_margin(zero_cp)
        self.assertTrue(res_cp["success"])
        # Markup cannot divide by 0 cost; returns safe 0.0 with zero cost note
        self.assertEqual(res_cp["markup_pct"], 0.0)

    def test_data_quality_scoring_penalties(self):
        """Verify data quality auditor applies penalties for nulls, duplicates, and inverted margins."""
        clean_df = pd.DataFrame({
            "product_name": ["Prod A", "Prod B", "Prod C"],
            "selling_price": [100.0, 150.0, 200.0],
            "purchase_price": [60.0, 90.0, 120.0],
            "stock_qty": [10, 20, 30]
        })
        clean_roles = map_column_roles(clean_df.columns)
        clean_audit = audit_data_quality(clean_df, clean_roles)
        self.assertGreaterEqual(clean_audit["overall_score"], 90.0)

        # Flawed dataset with duplicates and inverted margins
        flawed_df = pd.DataFrame({
            "product_name": ["Prod A", "Prod A", "Prod C"], # Duplicate Prod A
            "selling_price": [50.0, 50.0, 100.0], # Prod A inverted margin (cost 80 > price 50)
            "purchase_price": [80.0, 80.0, 40.0],
            "stock_qty": [10, 10, None] # Null stock
        })
        flawed_roles = map_column_roles(flawed_df.columns)
        flawed_audit = audit_data_quality(flawed_df, flawed_roles)
        self.assertLess(flawed_audit["overall_score"], clean_audit["overall_score"])
        self.assertGreater(flawed_audit["issue_count"], 0)

    def test_column_mapping_confidence_scores(self):
        """Verify intelligent column mapping assigns accurate confidence scores and reasons."""
        cols = ["Product_Name", "Unit_Price", "Purchase_Cost", "Stock_Qty", "Supplier_Name", "Order_Date", "Random_Extra"]
        mappings = get_column_mappings_with_confidence(cols)
        mapped_dict = {m["source_column"]: m for m in mappings}

        self.assertEqual(mapped_dict["Product_Name"]["suggested_field"], "product")
        self.assertEqual(mapped_dict["Product_Name"]["confidence"], 0.98)
        self.assertEqual(mapped_dict["Product_Name"]["validation_status"], "validated")

        self.assertEqual(mapped_dict["Unit_Price"]["suggested_field"], "price")
        self.assertEqual(mapped_dict["Unit_Price"]["confidence"], 0.98)

        self.assertEqual(mapped_dict["Purchase_Cost"]["suggested_field"], "cost")
        self.assertEqual(mapped_dict["Purchase_Cost"]["confidence"], 0.98)

        self.assertEqual(mapped_dict["Stock_Qty"]["suggested_field"], "quantity")
        self.assertEqual(mapped_dict["Stock_Qty"]["confidence"], 0.98)

        self.assertEqual(mapped_dict["Supplier_Name"]["suggested_field"], "supplier")
        self.assertEqual(mapped_dict["Supplier_Name"]["confidence"], 0.98)

        self.assertEqual(mapped_dict["Random_Extra"]["suggested_field"], "unmapped")
        self.assertEqual(mapped_dict["Random_Extra"]["confidence"], 0.0)
        self.assertEqual(mapped_dict["Random_Extra"]["validation_status"], "unmapped")

    def test_shipping_freight_shield_from_purchase_cost(self):
        """Verify non-cost keywords like shipping/freight are strictly never mapped to product cost."""
        cols = ["Product_Name", "Purchase_Price", "Shipping_Cost", "Freight_Charge"]
        roles = map_column_roles(cols)
        self.assertEqual(roles.get("cost"), "Purchase_Price")
        self.assertNotEqual(roles.get("cost"), "Shipping_Cost")
        self.assertNotEqual(roles.get("cost"), "Freight_Charge")

    def test_pearson_correlation_linear_relationship(self):
        """Verify Pearson correlation calculation correctly detects positive and negative relationships."""
        # Perfectly linear: y = 2x
        df = pd.DataFrame({
            "X": [1, 2, 3, 4, 5],
            "Y": [2, 4, 6, 8, 10],
            "Z": [10, 8, 6, 4, 2] # Perfectly negative linear: z = -2x + 12
        })
        corr = compute_correlation_matrix(df)
        self.assertTrue(corr["available"])
        self.assertAlmostEqual(corr["matrix"]["X"]["Y"], 1.0, places=2)
        self.assertAlmostEqual(corr["matrix"]["X"]["Z"], -1.0, places=2)


if __name__ == '__main__':
    unittest.main()

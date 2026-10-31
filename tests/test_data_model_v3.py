import os
import sys
import unittest
import sqlite3
import tempfile
import datetime

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database

class TestBusinessDataModelV3(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary SQLite database for each test
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.db_path = self.temp_file.name
        database.init_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_01_init_and_idempotency(self):
        """Verify init_db can be called repeatedly without error or data loss."""
        database.init_db(self.db_path)
        database.init_db(self.db_path)
        
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT MAX(version) FROM schema_migrations")
        self.assertEqual(cur.fetchone()[0], 3)
        conn.close()

    def test_02_foreign_key_enforcement(self):
        """Verify PRAGMA foreign_keys is strictly enforced."""
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        # Attempt to insert product with invalid supplier_id
        with self.assertRaises(sqlite3.IntegrityError):
            with conn:
                cur.execute(
                    """
                    INSERT INTO products (name, supplier_id, created_at, updated_at)
                    VALUES ('Ghost Product', 99999, '2026-01-01', '2026-01-01')
                    """
                )
        conn.close()

    def test_03_sku_uniqueness_and_null_tolerance(self):
        """Verify SKU is unique when specified, but multiple NULL/empty SKUs are allowed."""
        conn = database.get_connection(self.db_path)
        
        # Product 1: NULL SKU
        p1 = database.create_product({"name": "Unbranded Widget A", "sku": None}, conn=conn)
        self.assertIsNotNone(p1["id"])
        self.assertIsNone(p1["sku"])

        # Product 2: Another NULL SKU (should succeed)
        p2 = database.create_product({"name": "Unbranded Widget B", "sku": ""}, conn=conn)
        self.assertIsNotNone(p2["id"])

        # Product 3: Specific SKU
        p3 = database.create_product({"name": "SKU Item", "sku": "ITEM-100"}, conn=conn)
        self.assertEqual(p3["sku"], "ITEM-100")

        # Product 4: Duplicate SKU should fail
        with self.assertRaises(ValueError):
            database.create_product({"name": "Duplicate SKU Item", "sku": "ITEM-100"}, conn=conn)

        # Product 5: Duplicate SKU with different casing or whitespace should fail
        with self.assertRaises(ValueError):
            database.create_product({"name": "Duplicate SKU 2", "sku": "  item-100 "}, conn=conn)

        conn.close()

    def test_04_pricing_semantics_and_margins(self):
        """Verify purchase price vs selling price semantics, rounding, and margin calculations."""
        conn = database.get_connection(self.db_path)
        
        prod = database.create_product({
            "name": "Mechanical Keyboard",
            "sku": "KB-PRO",
            "purchase_price": 1500.555, # Should round to 1500.56
            "selling_price": 2499.999,  # Should round to 2500.00
            "currency": "INR"
        }, conn=conn)

        self.assertEqual(prod["purchase_price"], 1500.56)
        self.assertEqual(prod["selling_price"], 2500.00)
        self.assertAlmostEqual(prod["gross_profit"], 999.44, places=2)
        self.assertAlmostEqual(prod["gross_margin_pct"], 39.98, places=2)

        # Negative price validation
        with self.assertRaises(ValueError):
            database.create_product({"name": "Bad Price", "purchase_price": -10}, conn=conn)

        with self.assertRaises(ValueError):
            database.create_product({"name": "Bad Price 2", "selling_price": -5}, conn=conn)

        conn.close()

    def test_05_inventory_balances_and_stock_locking(self):
        """Verify inventory balances, movement auditing, and stock protection."""
        conn = database.get_connection(self.db_path)
        
        prod = database.create_product({
            "name": "Precision Sensor",
            "sku": "SENS-01",
            "opening_stock": 25.0,
            "reorder_level": 5.0
        }, conn=conn)

        self.assertEqual(prod["quantity_on_hand"], 25.0)
        self.assertEqual(len(prod["recent_movements"]), 1)
        self.assertEqual(prod["recent_movements"][0]["movement_type"], "opening_balance")

        # Direct stock modification via update_product should be strictly rejected
        with self.assertRaises(ValueError):
            database.update_product(prod["id"], {"quantity_on_hand": 100}, conn=conn)

        with self.assertRaises(ValueError):
            database.update_product(prod["id"], {"stock": 100}, conn=conn)

        conn.close()

    def test_06_purchases_ledger_and_rate_tracking(self):
        """Verify procurement recording updates stock, inventory movement, and last_purchase_rate."""
        conn = database.get_connection(self.db_path)
        
        # Create supplier
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO suppliers (name, contact_name, phone, email, created_at, updated_at)
            VALUES ('Apex Components', 'John Doe', '9876543210', 'john@apex.com', '2026-01-01', '2026-01-01')
            """
        )
        supplier_id = cur.lastrowid
        conn.commit()

        # Create product with standard catalog cost 1000.00
        prod = database.create_product({
            "name": "Heavy Duty Relay",
            "sku": "RELAY-HD",
            "purchase_price": 1000.00,
            "selling_price": 1600.00,
            "supplier_id": supplier_id,
            "opening_stock": 10.0
        }, conn=conn)

        # Record a procurement purchase at an invoice rate of 950.00 (discounted)
        purchase = database.record_purchase(
            product_id=prod["id"],
            purchase_date="2026-03-15",
            quantity=50.0,
            unit_price=950.00,
            supplier_id=supplier_id,
            purchase_number="PO-2026-001",
            notes="Bulk discount applied",
            conn=conn
        )

        self.assertEqual(purchase["total_amount"], 47500.00)
        self.assertEqual(purchase["supplier_name"], "Apex Components")

        # Verify stock on hand updated to 60.0 (10 opening + 50 purchase)
        updated_prod = database.get_product_by_id(prod["id"], conn=conn)
        self.assertEqual(updated_prod["quantity_on_hand"], 60.0)
        self.assertEqual(updated_prod["purchase_price"], 1000.00) # Base catalog price preserved
        self.assertEqual(updated_prod["last_purchase_rate"], 950.00) # Updated invoice rate
        self.assertEqual(updated_prod["last_purchase_date"], "2026-03-15")

        # Verify pricing summary
        summary = database.get_product_pricing_summary(prod["id"], conn=conn)
        self.assertEqual(summary["catalog_purchase_price"], 1000.00)
        self.assertEqual(summary["last_purchase_rate"], 950.00)
        self.assertEqual(summary["selling_price"], 1600.00)
        self.assertEqual(summary["total_purchases_recorded"], 1)
        self.assertEqual(summary["total_units_purchased"], 50.0)

        conn.close()

    def test_07_sales_ledger_and_stock_deduction(self):
        """Verify sales recording validates sufficient stock, deducts balance, and writes movement."""
        conn = database.get_connection(self.db_path)
        
        prod = database.create_product({
            "name": "Industrial Router",
            "sku": "RT-IND",
            "selling_price": 5000.00,
            "opening_stock": 5.0
        }, conn=conn)

        # Attempt to sell 10 units when only 5 exist (should fail)
        with self.assertRaises(ValueError):
            database.record_sale(
                product_id=prod["id"],
                sale_date="2026-03-20",
                quantity=10.0,
                unit_price=5000.00,
                invoice_number="INV-001",
                conn=conn
            )

        # Sell 2 units (should succeed)
        sale = database.record_sale(
            product_id=prod["id"],
            sale_date="2026-03-20",
            quantity=2.0,
            unit_price=5000.00,
            invoice_number="INV-002",
            customer_name="Tech Corp",
            conn=conn
        )

        self.assertEqual(sale["total_amount"], 10000.00)
        self.assertEqual(sale["customer_name"], "Tech Corp")

        # Verify stock decreased from 5 to 3
        updated_prod = database.get_product_by_id(prod["id"], conn=conn)
        self.assertEqual(updated_prod["quantity_on_hand"], 3.0)

        # Verify inventory movement recorded with type 'sale'
        movements = updated_prod["recent_movements"]
        self.assertEqual(movements[0]["movement_type"], "sale")
        self.assertEqual(movements[0]["quantity_delta"], -2.0)
        self.assertEqual(movements[0]["quantity_after"], 3.0)

        conn.close()

    def test_08_transaction_rollback_on_failure(self):
        """Verify atomic transaction rollback leaves no orphaned or partial records."""
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM products")
        initial_prod_count = cur.fetchone()[0]

        # Trigger an error during manual transaction
        try:
            with conn:
                cur.execute(
                    """
                    INSERT INTO products (name, created_at, updated_at)
                    VALUES ('Temporary Item', '2026-01-01', '2026-01-01')
                    """
                )
                # Intentionally trigger foreign key error
                cur.execute(
                    """
                    INSERT INTO inventory (product_id, quantity_on_hand, updated_at)
                    VALUES (999999, 10, '2026-01-01')
                    """
                )
        except sqlite3.IntegrityError:
            pass

        cur.execute("SELECT COUNT(*) FROM products")
        after_prod_count = cur.fetchone()[0]
        self.assertEqual(initial_prod_count, after_prod_count, "Rollback failed to revert partial product insertion")

        conn.close()

    def test_09_dataset_provenance_tracking(self):
        """Verify provenance is maintained across products, movements, and ledger entries."""
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()

        # Create a mock dataset
        dataset_id = "test-dataset-prov-1"
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO datasets (id, original_filename, file_type, file_size_bytes,
                                  file_hash_sha256, dataset_type, created_at, updated_at)
            VALUES (?, 'source_catalog.xlsx', 'xlsx', 1024, 'dummyhash123', 'catalogue', ?, ?)
            """,
            (dataset_id, now_str, now_str)
        )
        conn.commit()

        # Create product with dataset provenance
        prod = database.create_product({
            "name": "Provenance Monitored Unit",
            "sku": "PROV-001",
            "source_dataset_id": dataset_id,
            "opening_stock": 10.0
        }, conn=conn)

        self.assertEqual(prod["source_dataset_id"], dataset_id)

        # Record purchase and sale with provenance
        pu = database.record_purchase(
            product_id=prod["id"],
            purchase_date="2026-03-01",
            quantity=20.0,
            unit_price=100.0,
            source_dataset_id=dataset_id,
            conn=conn
        )
        self.assertEqual(pu["source_dataset_id"], dataset_id)

        sa = database.record_sale(
            product_id=prod["id"],
            sale_date="2026-03-02",
            quantity=5.0,
            unit_price=200.0,
            source_dataset_id=dataset_id,
            conn=conn
        )
        self.assertEqual(sa["source_dataset_id"], dataset_id)

        # Deleting dataset should SET NULL rather than break or leave corrupt FKs
        cur.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        conn.commit()

        updated_prod = database.get_product_by_id(prod["id"], conn=conn)
        self.assertIsNone(updated_prod["source_dataset_id"])

        cur.execute("SELECT source_dataset_id FROM purchases WHERE id = ?", (pu["id"],))
        self.assertIsNone(cur.fetchone()[0])

        cur.execute("SELECT source_dataset_id FROM sales WHERE id = ?", (sa["id"],))
        self.assertIsNone(cur.fetchone()[0])

        conn.close()

    def test_10_deactivate_product_preserves_ledger(self):
        """Verify soft deactivation retains historical purchases, sales, and movement audit trail."""
        conn = database.get_connection(self.db_path)
        prod = database.create_product({
            "name": "Legacy Gear",
            "sku": "GEAR-OLD",
            "selling_price": 500.0,
            "opening_stock": 10.0
        }, conn=conn)

        # Record a sale
        database.record_sale(
            product_id=prod["id"],
            sale_date="2026-01-10",
            quantity=3.0,
            unit_price=500.0,
            invoice_number="INV-LEGACY-01",
            conn=conn
        )

        # Deactivate
        success = database.deactivate_product(prod["id"], conn=conn)
        self.assertTrue(success)

        # Verify product is inactive
        p = database.get_product_by_id(prod["id"], conn=conn)
        self.assertEqual(p["is_active"], 0)

        # Verify historical sale and movements are still 100% accessible
        sales_resp = database.list_sales(product_id=prod["id"], conn=conn)
        self.assertEqual(sales_resp["total_count"], 1)
        self.assertEqual(len(p["recent_movements"]), 2) # opening_balance + sale

        conn.close()

    def test_11_list_purchases_and_sales_filters(self):
        """Verify date ranges and pagination for purchase and sales ledgers."""
        conn = database.get_connection(self.db_path)
        prod = database.create_product({
            "name": "Filter Test Item",
            "sku": "FILT-01",
            "selling_price": 100.0,
            "opening_stock": 100.0
        }, conn=conn)

        # Record multiple sales across dates
        for day in ["2026-01-05", "2026-02-15", "2026-03-25"]:
            database.record_sale(
                product_id=prod["id"],
                sale_date=day,
                quantity=1.0,
                unit_price=100.0,
                conn=conn
            )

        # Filter by February only
        feb_sales = database.list_sales(
            product_id=prod["id"],
            start_date="2026-02-01",
            end_date="2026-02-28",
            conn=conn
        )
        self.assertEqual(feb_sales["total_count"], 1)
        self.assertEqual(feb_sales["items"][0]["sale_date"], "2026-02-15")

        conn.close()

if __name__ == "__main__":
    unittest.main()

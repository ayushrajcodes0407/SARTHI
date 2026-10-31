import os
import sys
import io
import unittest
import sqlite3
import tempfile
import pandas as pd

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database
import app as flask_app_module

class TestImportSyncV4(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary SQLite database for each test
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.db_path = self.temp_file.name
        database.init_db(self.db_path)

        # Set database path in environment so Flask endpoints use the isolated test database
        self.orig_vantiq_db = os.environ.get("VANTIQ_DB_PATH")
        self.orig_jarvis_db = os.environ.get("JARVIS_DB_PATH")
        os.environ["VANTIQ_DB_PATH"] = self.db_path
        os.environ["JARVIS_DB_PATH"] = self.db_path
        database.DB_PATH = self.db_path

        flask_app_module.app.config['TESTING'] = True
        self.client = flask_app_module.app.test_client()

    def tearDown(self):
        if self.orig_vantiq_db is not None:
            os.environ["VANTIQ_DB_PATH"] = self.orig_vantiq_db
        else:
            os.environ.pop("VANTIQ_DB_PATH", None)

        if self.orig_jarvis_db is not None:
            os.environ["JARVIS_DB_PATH"] = self.orig_jarvis_db
        else:
            os.environ.pop("JARVIS_DB_PATH", None)

        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_01_csv_upload_and_persistence(self):
        """Verify CSV files can be uploaded, parsed, persisted, and deduplicated."""
        csv_content = (
            "Item Code,Product Description,Category,Cost,Sale Price,Stock Qty\n"
            "WID-01,Quantum Resonator,Electronics,120.50,199.99,50\n"
            "WID-02,Vortex Impeller,Hardware,45.00,89.50,120\n"
            "WID-03,Flux Inductor,Electronics,310.00,450.00,15\n"
        )
        data = {
            'file': (io.BytesIO(csv_content.encode('utf-8')), 'quantum_inventory.csv')
        }
        res = self.client.post('/api/data-import', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        res_json = res.get_json()
        self.assertTrue(res_json.get("success"))
        self.assertEqual(res_json.get("file_type"), "csv")
        dataset_id = res_json.get("dataset_id")
        self.assertIsNotNone(dataset_id)

        # Verify dataset records in DB
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, original_filename, file_type, row_count FROM datasets WHERE id = ?", (dataset_id,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["original_filename"], "quantum_inventory.csv")
        self.assertEqual(row["file_type"], "csv")
        self.assertEqual(row["row_count"], 3)

        # Verify sheets and records
        cur.execute("SELECT COUNT(*) FROM dataset_records WHERE dataset_id = ?", (dataset_id,))
        self.assertEqual(cur.fetchone()[0], 3)
        conn.close()

        # Re-upload identical CSV: verify SHA-256 deduplication
        data_dup = {
            'file': (io.BytesIO(csv_content.encode('utf-8')), 'quantum_inventory.csv')
        }
        res_dup = self.client.post('/api/data-import', data=data_dup, content_type='multipart/form-data')
        self.assertEqual(res_dup.status_code, 200)
        dup_json = res_dup.get_json()
        self.assertTrue(dup_json.get("is_duplicate"))
        self.assertEqual(dup_json.get("dataset_id"), dataset_id)

    def test_02_suggest_mappings_per_purpose(self):
        """Verify intelligent column mapping suggestions adapt to synchronization purpose."""
        # 1. Catalogue columns
        cat_cols = ["Item Code", "Product Title", "Category", "Buying Price", "Retail Price", "Opening Units"]
        m_cat = database.suggest_column_mappings(cat_cols, purpose="catalogue")
        self.assertEqual(m_cat.get("sku"), "Item Code")
        self.assertEqual(m_cat.get("name"), "Product Title")
        self.assertEqual(m_cat.get("category"), "Category")
        self.assertEqual(m_cat.get("purchase_price"), "Buying Price")
        self.assertEqual(m_cat.get("selling_price"), "Retail Price")
        self.assertEqual(m_cat.get("opening_stock"), "Opening Units")

        # 2. Purchases columns
        pur_cols = ["PO No", "PO Date", "SKU", "Supplier Name", "Purchased Qty", "Unit Cost", "Remarks"]
        m_pur = database.suggest_column_mappings(pur_cols, purpose="purchases")
        self.assertEqual(m_pur.get("purchase_number"), "PO No")
        self.assertEqual(m_pur.get("purchase_date"), "PO Date")
        self.assertEqual(m_pur.get("sku"), "SKU")
        self.assertEqual(m_pur.get("supplier"), "Supplier Name")
        self.assertEqual(m_pur.get("quantity"), "Purchased Qty")
        self.assertEqual(m_pur.get("unit_price"), "Unit Cost")
        self.assertEqual(m_pur.get("notes"), "Remarks")

        # 3. Sales columns
        sales_cols = ["Invoice Number", "Sale Date", "Item Name", "Sold Qty", "Selling Rate", "Customer Name"]
        m_sales = database.suggest_column_mappings(sales_cols, purpose="sales")
        self.assertEqual(m_sales.get("invoice_number"), "Invoice Number")
        self.assertEqual(m_sales.get("sale_date"), "Sale Date")
        self.assertEqual(m_sales.get("product"), "Item Name")
        self.assertEqual(m_sales.get("quantity"), "Sold Qty")
        self.assertEqual(m_sales.get("unit_price"), "Selling Rate")
        self.assertEqual(m_sales.get("customer_name"), "Customer Name")

        # 4. Inventory adjustments columns
        adj_cols = ["Product Code", "Stock Change", "Reason for adjustment", "Audit Ref"]
        m_adj = database.suggest_column_mappings(adj_cols, purpose="inventory_adjustments")
        self.assertEqual(m_adj.get("sku"), "Product Code")
        self.assertEqual(m_adj.get("quantity_delta"), "Stock Change")
        self.assertEqual(m_adj.get("reason"), "Reason for adjustment")
        self.assertEqual(m_adj.get("reference"), "Audit Ref")

    def test_03_catalogue_sync_preview_and_commit(self):
        """Verify catalogue spreadsheet import preview and commit with opening stock."""
        csv_content = (
            "SKU,Name,Category,Cost,Price,OpeningStock\n"
            "CAT-01,Plasma Conduit,Electronics,50.00,85.00,100\n"
            "CAT-02,Ion Thruster,Propulsion,450.00,750.00,20\n"
            ",Missing Name Product,Misc,10.00,15.00,5\n"
            "CAT-03,,Misc,10.00,15.00,5\n"  # Invalid: empty name
        )
        data = {'file': (io.BytesIO(csv_content.encode('utf-8')), 'catalogue.csv')}
        res = self.client.post('/api/data-import', data=data, content_type='multipart/form-data')
        dataset_id = res.get_json()["dataset_id"]

        mapping = {
            "sku": "SKU",
            "name": "Name",
            "category": "Category",
            "purchase_price": "Cost",
            "selling_price": "Price",
            "opening_stock": "OpeningStock"
        }

        # 1. Preview
        prev_res = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/preview',
            json={"column_mapping": mapping, "sync_purpose": "catalogue"}
        )
        self.assertEqual(prev_res.status_code, 200)
        prev_data = prev_res.get_json()
        self.assertEqual(prev_data["total_rows"], 4)
        self.assertEqual(prev_data["valid_count"], 3)
        self.assertEqual(prev_data["invalid_count"], 1)

        # 2. Commit
        commit_res = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/commit',
            json={"column_mapping": mapping, "sync_purpose": "catalogue", "duplicate_strategy": "skip_existing"}
        )
        self.assertEqual(commit_res.status_code, 200)
        commit_data = commit_res.get_json()
        self.assertEqual(commit_data["created_count"], 3)
        self.assertEqual(commit_data["error_count"], 1)

        # Verify products and opening inventory
        p1 = database.find_product_by_identifier("CAT-01", conn=database.get_connection(self.db_path))
        self.assertIsNotNone(p1)
        self.assertEqual(p1["quantity_on_hand"], 100.0)
        self.assertEqual(p1["purchase_price"], 50.0)

    def test_04_purchases_sync_with_stock_receipt(self):
        """Verify procurement ledger synchronization creates purchases, receipts, and updates prices."""
        conn = database.get_connection(self.db_path)
        # Pre-seed a product
        p = database.create_product({
            "name": "Titanium Alloy Bolt",
            "sku": "BOLT-TI-01",
            "purchase_price": 5.0,
            "selling_price": 10.0,
            "opening_stock": 50.0
        }, conn=conn)
        conn.close()

        # Upload a purchases CSV
        csv_content = (
            "PO_Number,Date,SKU,Supplier,Quantity,Unit_Cost,Notes\n"
            "PO-9001,2026-04-10,BOLT-TI-01,Stark Industries,200,4.80,Batch A shipment\n"
            "PO-9002,2026-04-11,BOLT-TI-01,Stark Industries,150,4.75,Batch B shipment\n"
            "PO-9003,2026-04-12,UNKNOWN-SKU,Acme Corp,50,12.00,Unmatched item\n"
        )
        data = {'file': (io.BytesIO(csv_content.encode('utf-8')), 'purchases.csv')}
        res = self.client.post('/api/data-import', data=data, content_type='multipart/form-data')
        dataset_id = res.get_json()["dataset_id"]

        mapping = {
            "purchase_number": "PO_Number",
            "purchase_date": "Date",
            "sku": "SKU",
            "supplier": "Supplier",
            "quantity": "Quantity",
            "unit_price": "Unit_Cost",
            "notes": "Notes"
        }

        # Preview purchases
        prev_res = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/preview',
            json={"column_mapping": mapping, "sync_purpose": "purchases"}
        )
        self.assertEqual(prev_res.status_code, 200)
        prev_data = prev_res.get_json()
        self.assertEqual(prev_data["valid_count"], 2)
        self.assertEqual(prev_data["unmatched_count"], 1)
        self.assertEqual(prev_data["proposed_stock_additions"], 350.0)

        # Commit purchases
        commit_res = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/commit',
            json={"column_mapping": mapping, "sync_purpose": "purchases"}
        )
        self.assertEqual(commit_res.status_code, 200)
        commit_data = commit_res.get_json()
        self.assertEqual(commit_data["recorded_transactions"], 2)
        self.assertEqual(commit_data["recorded_movements"], 2)
        self.assertEqual(commit_data["error_count"], 1)  # 1 unmatched SKU

        # Verify database state
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        # Verify 2 purchases recorded
        cur.execute("SELECT COUNT(*) FROM purchases WHERE product_id = ?", (p["id"],))
        self.assertEqual(cur.fetchone()[0], 2)

        # Verify stock increased from 50 to 50 + 200 + 150 = 400
        cur.execute("SELECT quantity_on_hand FROM inventory WHERE product_id = ?", (p["id"],))
        self.assertEqual(cur.fetchone()[0], 400.0)

        # Verify last_purchase_rate updated to 4.75 and date to 2026-04-11
        cur.execute("SELECT last_purchase_rate, last_purchase_date FROM products WHERE id = ?", (p["id"],))
        p_row = cur.fetchone()
        self.assertEqual(p_row["last_purchase_rate"], 4.75)
        self.assertEqual(p_row["last_purchase_date"], "2026-04-11")

        # Verify inventory_movements records
        cur.execute("SELECT movement_type, quantity_delta, reason, reference FROM inventory_movements WHERE product_id = ? ORDER BY id ASC", (p["id"],))
        moves = [dict(r) for r in cur.fetchall()]
        # 1 opening movement + 2 purchase receipt movements
        self.assertEqual(len(moves), 3)
        self.assertEqual(moves[1]["movement_type"], "receipt")
        self.assertEqual(moves[1]["quantity_delta"], 200.0)
        self.assertEqual(moves[1]["reference"], "PO-9001")
        self.assertEqual(moves[2]["quantity_delta"], 150.0)
        self.assertEqual(moves[2]["reference"], "PO-9002")
        conn.close()

    def test_05_purchases_repeated_import_idempotency(self):
        """Verify re-committing the same purchases file does not double-count inventory or duplicate transactions."""
        conn = database.get_connection(self.db_path)
        p = database.create_product({"name": "Carbon Filter", "sku": "CF-100", "opening_stock": 10.0}, conn=conn)
        conn.close()

        csv_content = (
            "PO,Date,SKU,Qty,Rate\n"
            "PO-501,2026-04-01,CF-100,50,25.00\n"
        )
        data = {'file': (io.BytesIO(csv_content.encode('utf-8')), 'cf_purchases.csv')}
        res = self.client.post('/api/data-import', data=data, content_type='multipart/form-data')
        dataset_id = res.get_json()["dataset_id"]

        mapping = {"purchase_number": "PO", "purchase_date": "Date", "sku": "SKU", "quantity": "Qty", "unit_price": "Rate"}

        # First commit
        res1 = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/commit',
            json={"column_mapping": mapping, "sync_purpose": "purchases"}
        )
        self.assertEqual(res1.get_json()["recorded_transactions"], 1)

        # Check stock = 10 + 50 = 60
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT quantity_on_hand FROM inventory WHERE product_id = ?", (p["id"],))
        self.assertEqual(cur.fetchone()[0], 60.0)
        conn.close()

        # Second commit on identical data: Idempotency Protection
        res2 = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/commit',
            json={"column_mapping": mapping, "sync_purpose": "purchases"}
        )
        res2_data = res2.get_json()
        self.assertEqual(res2_data["recorded_transactions"], 0)
        self.assertEqual(res2_data["previously_imported_count"], 1)

        # Assert stock is STILL 60 (NO double counting)
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT quantity_on_hand FROM inventory WHERE product_id = ?", (p["id"],))
        self.assertEqual(cur.fetchone()[0], 60.0)

        # Assert purchases count is STILL 1
        cur.execute("SELECT COUNT(*) FROM purchases WHERE product_id = ?", (p["id"],))
        self.assertEqual(cur.fetchone()[0], 1)
        conn.close()

    def test_06_sales_sync_with_stock_deduction(self):
        """Verify sales ledger synchronization records sales, deducts stock, and prevents overselling."""
        conn = database.get_connection(self.db_path)
        p = database.create_product({
            "name": "Solar Array Sensor",
            "sku": "SAS-01",
            "selling_price": 80.0,
            "opening_stock": 100.0
        }, conn=conn)
        conn.close()

        csv_content = (
            "Invoice,Date,Product,Customer,Qty,Price\n"
            "INV-101,2026-04-15,SAS-01,Wayne Enterprises,30,80.00\n"
            "INV-102,2026-04-16,SAS-01,Cyberdyne Systems,25,80.00\n"
        )
        data = {'file': (io.BytesIO(csv_content.encode('utf-8')), 'sales.csv')}
        res = self.client.post('/api/data-import', data=data, content_type='multipart/form-data')
        dataset_id = res.get_json()["dataset_id"]

        mapping = {
            "invoice_number": "Invoice",
            "sale_date": "Date",
            "sku": "Product",
            "customer_name": "Customer",
            "quantity": "Qty",
            "unit_price": "Price"
        }

        # Preview sales
        prev_res = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/preview',
            json={"column_mapping": mapping, "sync_purpose": "sales"}
        )
        prev_data = prev_res.get_json()
        self.assertEqual(prev_data["valid_count"], 2)
        self.assertEqual(prev_data["proposed_stock_deductions"], 55.0)

        # Commit sales
        commit_res = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/commit',
            json={"column_mapping": mapping, "sync_purpose": "sales"}
        )
        commit_data = commit_res.get_json()
        self.assertEqual(commit_data["recorded_transactions"], 2)
        self.assertEqual(commit_data["recorded_movements"], 2)

        # Check remaining stock: 100 - 30 - 25 = 45
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT quantity_on_hand FROM inventory WHERE product_id = ?", (p["id"],))
        self.assertEqual(cur.fetchone()[0], 45.0)

        # Verify sales entries
        cur.execute("SELECT COUNT(*) FROM sales WHERE product_id = ?", (p["id"],))
        self.assertEqual(cur.fetchone()[0], 2)
        conn.close()

    def test_07_sales_insufficient_stock_rejection(self):
        """Verify that attempting to sell more stock than on hand is caught during validation."""
        conn = database.get_connection(self.db_path)
        p = database.create_product({"name": "Rare Gem", "sku": "GEM-01", "opening_stock": 5.0}, conn=conn)
        conn.close()

        csv_content = (
            "Invoice,Date,Product,Qty,Price\n"
            "INV-OVER,2026-04-18,GEM-01,20,500.00\n"  # 20 > 5 available
        )
        data = {'file': (io.BytesIO(csv_content.encode('utf-8')), 'oversell.csv')}
        res = self.client.post('/api/data-import', data=data, content_type='multipart/form-data')
        dataset_id = res.get_json()["dataset_id"]

        mapping = {"invoice_number": "Invoice", "sale_date": "Date", "sku": "Product", "quantity": "Qty", "unit_price": "Price"}

        # Preview: verify flagged as invalid with clear error message
        prev_res = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/preview',
            json={"column_mapping": mapping, "sync_purpose": "sales"}
        )
        prev_data = prev_res.get_json()
        self.assertEqual(prev_data["invalid_count"], 1)
        self.assertIn("Insufficient stock", prev_data["errors"][0]["message"])

    def test_08_inventory_adjustments_sync(self):
        """Verify stock audit adjustments update quantities with complete audit trail."""
        conn = database.get_connection(self.db_path)
        p = database.create_product({"name": "Hydraulic Fluid 5L", "sku": "HYD-5L", "opening_stock": 40.0}, conn=conn)
        conn.close()

        csv_content = (
            "Item,Adjustment,Reason,AuditTicket\n"
            "HYD-5L,-4,Damaged can leaked in aisle 3,AUD-2026-09\n"
            "HYD-5L,10,Found unrecorded box in back storeroom,AUD-2026-10\n"
        )
        data = {'file': (io.BytesIO(csv_content.encode('utf-8')), 'adjustments.csv')}
        res = self.client.post('/api/data-import', data=data, content_type='multipart/form-data')
        dataset_id = res.get_json()["dataset_id"]

        mapping = {"sku": "Item", "quantity_delta": "Adjustment", "reason": "Reason", "reference": "AuditTicket"}

        # Commit adjustments
        commit_res = self.client.post(
            f'/api/datasets/{dataset_id}/product-import/commit',
            json={"column_mapping": mapping, "sync_purpose": "inventory_adjustments"}
        )
        commit_data = commit_res.get_json()
        self.assertEqual(commit_data["recorded_movements"], 2)

        # Final stock: 40 - 4 + 10 = 46
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT quantity_on_hand FROM inventory WHERE product_id = ?", (p["id"],))
        self.assertEqual(cur.fetchone()[0], 46.0)

        # Verify movements table
        cur.execute("SELECT quantity_delta, reason, reference FROM inventory_movements WHERE product_id = ? AND movement_type = 'adjustment' ORDER BY id ASC", (p["id"],))
        moves = [dict(r) for r in cur.fetchall()]
        self.assertEqual(len(moves), 2)
        self.assertEqual(moves[0]["quantity_delta"], -4.0)
        self.assertEqual(moves[0]["reference"], "AUD-2026-09")
        self.assertEqual(moves[1]["quantity_delta"], 10.0)
        self.assertEqual(moves[1]["reference"], "AUD-2026-10")
        conn.close()

    def test_09_database_integrity(self):
        """Verify PRAGMA integrity_check returns 'ok'."""
        conn = database.get_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        self.assertEqual(row[0].lower(), "ok")
        conn.close()

if __name__ == '__main__':
    unittest.main()

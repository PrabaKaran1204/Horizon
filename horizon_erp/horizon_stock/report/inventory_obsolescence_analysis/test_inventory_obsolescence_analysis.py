# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from horizon_erp.horizon_stock.report.inventory_obsolescence_analysis.inventory_obsolescence_analysis import (
	execute,
)
from horizon_erp.horizon_stock.scrap import get_default_dimensions, mark_for_scrap
from horizon_erp.tests.cleanup import purge_test_residue

COMPANY = "Horizon Manufacturing Ltd"
ITEM = "RPTTEST-OBS-ITEM"


class TestInventoryObsolescenceAnalysis(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		cls.warehouse = frappe.db.get_value(
			"Warehouse", {"company": COMPANY, "is_group": 0, "name": ["like", "%Stores%"]}, "name"
		) or frappe.db.get_value("Warehouse", {"company": COMPANY, "is_group": 0}, "name")
		if not frappe.db.exists("Item", ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": ITEM,
					"item_name": "RPTTEST Obsolescence Item",
					"item_group": "Raw Material",
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"gst_hsn_code": "999900",
				}
			).insert(ignore_permissions=True)
		dimensions = get_default_dimensions(COMPANY)
		se = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"company": COMPANY,
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"posting_date": today(),
				**dimensions,
				"items": [
					{
						"item_code": ITEM,
						"t_warehouse": cls.warehouse,
						"qty": 10,
						"basic_rate": 50,
						**dimensions,
					}
				],
			}
		)
		se.insert(ignore_permissions=True)
		se.submit()
		cls.receipt = se

	def test_execute_default_filters(self):
		columns, data, _message, chart, summary = execute({"company": COMPANY})
		self.assertTrue(columns)
		self.assertTrue(chart["data"]["labels"])
		self.assertEqual(len(summary), 3)

	def test_row_and_bucket(self):
		_columns, data, *_rest = execute({"company": COMPANY, "warehouse": self.warehouse})
		rows = [r for r in data if r.item_code == ITEM]
		self.assertEqual(len(rows), 1)
		self.assertGreaterEqual(rows[0].actual_qty, 10)
		self.assertEqual(rows[0].aging_bucket, "0-30")
		self.assertEqual(rows[0].inventory_value, rows[0].actual_qty * rows[0].valuation_rate)

	def test_mark_for_scrap_creates_draft_stock_entry(self):
		name = mark_for_scrap(
			rows=[{"item_code": ITEM, "warehouse": self.warehouse, "actual_qty": 10}],
			reason="Obsolete",
			scrap_warehouse=None,
			scrap_pct=50,
		)
		se = frappe.get_doc("Stock Entry", name)
		self.assertEqual(se.docstatus, 0)
		self.assertEqual(se.purpose, "Material Issue")
		self.assertEqual(len(se.items), 1)
		self.assertEqual(se.items[0].item_code, ITEM)
		self.assertEqual(se.items[0].qty, 5)
		self.assertIn("Obsolete", se.remarks)

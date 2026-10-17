# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_selling.report.price_list_comparison.price_list_comparison import execute
from horizon_erp.tests.cleanup import purge_test_residue

COMPANY = "Horizon Manufacturing Ltd"
ITEM = "RPTTEST-PRICE-ITEM"


class TestPriceListComparison(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		if not frappe.db.exists("Item", ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": ITEM,
					"item_name": ITEM,
					"item_group": "Products",
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"gst_hsn_code": "999900",
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Item Price", {"item_code": ITEM, "price_list": "Standard Selling"}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": ITEM,
					"price_list": "Standard Selling",
					"price_list_rate": 250,
				}
			).insert(ignore_permissions=True)

	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertTrue(any(c["fieldname"] == "standard_selling" for c in columns))
		self.assertTrue(any(c["fieldname"] == "q4_promo" for c in columns))
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 3)

	def test_execute_for_item(self):
		_c, data, *_rest = execute({"company": COMPANY, "item_group": "Products", "item": ITEM})
		self.assertEqual(len(data), 1)
		self.assertEqual(data[0].standard_selling, 250)
		self.assertGreater(data[0].q4_promo, 0)

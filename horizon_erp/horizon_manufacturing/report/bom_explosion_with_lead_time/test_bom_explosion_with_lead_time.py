# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_manufacturing.report.bom_explosion_with_lead_time.bom_explosion_with_lead_time import (
	execute,
)
from horizon_erp.tests.cleanup import purge_test_residue

COMPANY = "Horizon Manufacturing Ltd"
FG = "RPTTEST-BOM-FG"
RM = "RPTTEST-BOM-RM"


def make_item(code, lead_time_days=0):
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": "Raw Material",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"gst_hsn_code": "999900",
				"lead_time_days": lead_time_days,
			}
		).insert(ignore_permissions=True)


class TestBOMExplosionWithLeadTime(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		make_item(FG)
		make_item(RM, lead_time_days=7)
		bom = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": FG,
				"company": COMPANY,
				"quantity": 1,
				"rm_cost_as_per": "Valuation Rate",
				"items": [
					{
						"item_code": RM,
						"qty": 2,
						"rate": 10,
						"uom": "Nos",
						"stock_uom": "Nos",
						"conversion_factor": 1,
					}
				],
			}
		)
		bom.insert(ignore_permissions=True)
		bom.submit()
		cls.bom = bom.name

	def test_execute_without_bom(self):
		columns, data, message, _chart, _summary = execute({})
		self.assertTrue(columns)
		self.assertEqual(data, [])
		self.assertTrue(message)

	def test_execute_with_bom(self):
		_c, data, _m, chart, summary = execute({"bom": self.bom, "qty": 5})
		rows = [r for r in data if r.item_code == RM]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].required_qty, 10)
		self.assertEqual(rows[0].lead_time_days, 7)
		self.assertGreaterEqual(rows[0].shortage, 0)
		self.assertEqual(len(summary), 5)
		self.assertEqual(chart["data"]["labels"][0], RM)

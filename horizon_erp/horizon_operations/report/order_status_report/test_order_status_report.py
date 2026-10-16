# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_operations.report.order_status_report.order_status_report import execute, get_status

COMPANY = "Horizon Manufacturing Ltd"


class TestOrderStatusReport(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertTrue(columns)
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 3)
		self.assertIn("datasets", chart["data"])

	def test_status_logic(self):
		self.assertEqual(
			get_status(frappe._dict(pending_qty=0, days_overdue=0, delivered_qty=5)), "Fully Delivered"
		)
		self.assertEqual(
			get_status(frappe._dict(pending_qty=2, days_overdue=9, delivered_qty=0)), "Overdue > 5d"
		)
		self.assertEqual(get_status(frappe._dict(pending_qty=2, days_overdue=0, delivered_qty=3)), "Partial")
		self.assertEqual(get_status(frappe._dict(pending_qty=2, days_overdue=2, delivered_qty=0)), "Pending")

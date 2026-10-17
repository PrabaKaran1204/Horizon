# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_hr.report.leave_balance_with_carry_forward_expiry.leave_balance_with_carry_forward_expiry import (
	execute,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestLeaveBalanceWithCarryForwardExpiry(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 14)
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 4)
		self.assertEqual(len(chart["data"]["datasets"]), 2)
		for row in data:
			self.assertGreaterEqual(row.total_allocated, row.carry_forwarded)

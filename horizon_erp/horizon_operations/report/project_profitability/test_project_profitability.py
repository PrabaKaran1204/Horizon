# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from horizon_erp.horizon_operations.report.project_profitability.project_profitability import (
	execute,
	time_elapsed_pct,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestProjectProfitability(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 19)
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 5)
		for row in data:
			self.assertAlmostEqual(
				row.total_cost, row.material_cost + row.labour_cost + row.overhead, places=2
			)

	def test_time_elapsed(self):
		self.assertEqual(time_elapsed_pct("2026-01-01", "2026-01-11", getdate("2026-01-06")), 50)
		self.assertEqual(time_elapsed_pct("2026-01-01", "2026-01-11", getdate("2027-01-06")), 100)
		self.assertIsNone(time_elapsed_pct(None, "2026-01-11", getdate("2026-01-06")))

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_quality_management.report.quality_vs_deadline_conflicts.quality_vs_deadline_conflicts import (
	execute,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestQualityVsDeadlineConflicts(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 18)
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 5)
		self.assertEqual(summary[3]["label"], "Cost of Poor Quality (period)")
		self.assertIn("datasets", chart["data"])

	def test_execute_wide_horizon(self):
		_c, data, *_rest = execute({"company": COMPANY, "days_ahead": 365})
		for row in data:
			self.assertIn(row.status.split(":")[0], ("OK", "Conflict - Undecided", "Decided"))

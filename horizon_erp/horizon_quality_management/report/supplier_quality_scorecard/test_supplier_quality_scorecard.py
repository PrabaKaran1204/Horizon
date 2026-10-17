# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_quality_management.report.supplier_quality_scorecard.supplier_quality_scorecard import (
	compute_score,
	execute,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestSupplierQualityScorecard(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 12)
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 3)
		self.assertEqual(len(chart["data"]["labels"]), len(data))

	def test_score_formula(self):
		self.assertEqual(compute_score(0, 100), 100)
		self.assertEqual(compute_score(10, 80), 70)
		self.assertEqual(compute_score(80, 0), 0)

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_finance.report.salary_cost_analysis.salary_cost_analysis import execute

COMPANY = "Horizon Manufacturing Ltd"


class TestSalaryCostAnalysis(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(columns[0]["options"], "Department")
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 4)
		for row in data:
			self.assertAlmostEqual(row.ctc, row.gross_pay + row.employer_pf, places=2)

	def test_group_by_variants(self):
		for group_by, options in (
			("Employee Grade", "Employee Grade"),
			("Employment Type", "Employment Type"),
		):
			columns, data, *_rest = execute({"company": COMPANY, "group_by": group_by})
			self.assertEqual(columns[0]["options"], options)
			self.assertIsInstance(data, list)

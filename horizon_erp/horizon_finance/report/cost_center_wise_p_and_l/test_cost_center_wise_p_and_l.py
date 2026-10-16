# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_finance.report.cost_center_wise_p_and_l.cost_center_wise_p_and_l import execute

COMPANY = "Horizon Manufacturing Ltd"


class TestCostCenterWisePAndL(FrappeTestCase):
	def test_execute_ytd(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(columns[0]["fieldname"], "account")
		self.assertEqual(columns[-1]["fieldname"], "total")
		self.assertTrue(any(c["fieldname"] == "unallocated" for c in columns))
		self.assertEqual(data[-1]["account"], "Net Profit")
		self.assertEqual(len(summary), 3)
		self.assertEqual(len(chart["data"]["datasets"]), 2)

	def test_execute_monthly(self):
		columns, data, *_rest = execute(
			{"company": COMPANY, "period": "Monthly", "from_date": "2026-04-01", "to_date": "2026-06-30"}
		)
		month_cols = [c["fieldname"] for c in columns if c["fieldname"] not in ("account", "total")]
		self.assertEqual(month_cols, ["2026_04", "2026_05", "2026_06"])
		self.assertEqual(data[-1]["account"], "Net Profit")

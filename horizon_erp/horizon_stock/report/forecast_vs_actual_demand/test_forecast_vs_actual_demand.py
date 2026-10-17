# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_stock.report.forecast_vs_actual_demand.forecast_vs_actual_demand import (
	execute,
	moving_average,
	variance_pct,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestForecastVsActualDemand(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		month_columns = [c for c in columns if c["fieldtype"] == "Float" and c["fieldname"][:2] == "20"]
		self.assertEqual(len(month_columns), 12)
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 4)
		self.assertIn("datasets", chart["data"])

	def test_execute_for_single_item(self):
		_c, data, _m, chart, _s = execute(
			{"company": COMPANY, "item": "RPTTEST-NO-SUCH-ITEM", "months_back": 6}
		)
		self.assertEqual(len(data), 1)
		self.assertEqual(data[0].forecast, 0)
		self.assertEqual(chart["type"], "line")

	def test_helpers(self):
		self.assertEqual(moving_average([1, 2, 3, 4, 5, 6]), 5)
		self.assertEqual(variance_pct(8, 10), 20)
		self.assertEqual(variance_pct(0, 0), 0)
		self.assertEqual(variance_pct(5, 0), 100)

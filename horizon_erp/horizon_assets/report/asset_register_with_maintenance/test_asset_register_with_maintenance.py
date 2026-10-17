# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_assets.report.asset_register_with_maintenance.asset_register_with_maintenance import (
	execute,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestAssetRegisterWithMaintenance(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 14)
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 5)
		for row in data:
			self.assertAlmostEqual(row.nbv, row.gross_cost - row.accumulated_depreciation, places=2)
			self.assertNotIn(row.status, ("Scrapped", "Sold"))

	def test_include_disposed(self):
		_c, data, *_rest = execute({"company": COMPANY, "include_disposed": 1})
		self.assertIsInstance(data, list)

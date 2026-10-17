# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_accounts.report.net_party_position.net_party_position import execute

COMPANY = "Horizon Manufacturing Ltd"


class TestNetPartyPosition(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 10)
		self.assertIsInstance(data, list)
		self.assertEqual(len(summary), 4)
		for row in data:
			self.assertAlmostEqual(row.net, row.receivable - row.payable, places=2)
			self.assertEqual(row.settlement, abs(row.net))

	def test_execute_including_same_name_parties(self):
		_c, data, _m, chart, _s = execute({"company": COMPANY, "party_link_only": 0})
		self.assertIsInstance(data, list)
		self.assertIn("datasets", chart["data"])

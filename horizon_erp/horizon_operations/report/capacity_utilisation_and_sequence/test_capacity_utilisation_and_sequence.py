# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from horizon_erp.horizon_operations.report.capacity_utilisation_and_sequence.capacity_utilisation_and_sequence import (
	downtime_for,
	execute,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestCapacityUtilisationAndSequence(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, message, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 7)
		self.assertIsInstance(data, list)
		self.assertIn("Suggested Work Order Sequence", message)
		self.assertEqual(len(summary), 4)
		workstations = frappe.db.count("Workstation")
		self.assertEqual(len(data), workstations * 15)
		for row in data:
			self.assertAlmostEqual(row.free_hours, row.capacity_hours - row.booked_hours, places=1)

	def test_single_day(self):
		_c, data, *_rest = execute(
			{"company": COMPANY, "from_date": nowdate(), "to_date": add_days(nowdate(), -3)}
		)
		self.assertEqual(len(data), frappe.db.count("Workstation"))

	def test_downtime_constants(self):
		self.assertEqual(
			downtime_for(frappe._dict(name="Line A - Assembly", workstation_name="Line A")), 0.10
		)
		self.assertEqual(downtime_for(frappe._dict(name="Line B", workstation_name="Line B")), 0.15)
		self.assertEqual(downtime_for(frappe._dict(name="Paint Shop", workstation_name="Paint Shop")), 0.0)

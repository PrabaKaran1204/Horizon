# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from horizon_erp.horizon_manufacturing.report.capacity_utilisation_and_sequence.capacity_utilisation_and_sequence import (
	DEFAULT_HORIZON_DAYS,
	downtime_for,
	execute,
	status_for,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestCapacityUtilisationAndSequence(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, message, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 7)
		self.assertIsInstance(data, list)
		workstations = frappe.db.count("Workstation")
		self.assertEqual(len(data), workstations * (DEFAULT_HORIZON_DAYS + 1))
		for row in data:
			self.assertAlmostEqual(row.free_hours, row.capacity_hours - row.booked_hours, places=1)
		# chart is utilisation % per workstation per day
		self.assertEqual(chart["fieldtype"], "Percent")
		self.assertEqual(len(chart["data"]["labels"]), DEFAULT_HORIZON_DAYS + 1)
		self.assertEqual(len(chart["data"]["datasets"]), workstations)

	def test_today_rows_come_first(self):
		_c, data, *_rest = execute({"company": COMPANY, "from_date": nowdate()})
		today = getdate(nowdate())
		workstations = frappe.db.count("Workstation")
		self.assertTrue(all(r.date == today for r in data[:workstations]))
		self.assertEqual(
			[(r.date, r.workstation) for r in data], sorted((r.date, r.workstation) for r in data)
		)

	def test_summary_free_hours_per_line_first(self):
		_c, data, _m, _ch, summary = execute({"company": COMPANY, "from_date": nowdate()})
		workstations = frappe.db.count("Workstation")
		self.assertEqual(len(summary), workstations + 3)
		today_rows = [r for r in data if r.date == getdate(nowdate())]
		for card, row in zip(summary[:workstations], today_rows, strict=True):
			self.assertEqual(card["value"], f"{round(row.free_hours, 1)} h")
			self.assertIn(f"{row.workstation} free today", card["label"])
			self.assertIn(f"of {round(row.capacity_hours, 1)} h", card["label"])
			self.assertIn(card["indicator"], ("Green", "Orange", "Red"))
		self.assertEqual(
			[c["label"] for c in summary[workstations:-1]], ["WOs Not Fitting Before Due", "Open Work Orders"]
		)
		self.assertTrue(summary[-1]["label"].startswith("Avg utilisation, period"))

	def test_message_line_status_before_sequence(self):
		_c, _d, message, *_rest = execute({"company": COMPANY, "from_date": nowdate()})
		self.assertIn("Today - line status", message)
		self.assertIn("Suggested Work Order Sequence", message)
		self.assertLess(message.index("line status"), message.index("Suggested Work Order Sequence"))
		self.assertIn("Running Work Orders", message)
		self.assertIn("ordered by due date".capitalize(), message)

	def test_only_today_filter(self):
		_c, data, _m, chart, summary = execute({"company": COMPANY, "from_date": nowdate(), "only_today": 1})
		workstations = frappe.db.count("Workstation")
		self.assertEqual(len(data), workstations)
		self.assertTrue(all(r.date == getdate(nowdate()) for r in data))
		self.assertEqual(len(chart["data"]["labels"]), 1)
		# cards are unaffected by the table filter
		self.assertEqual(len(summary), workstations + 3)

	def test_single_day(self):
		_c, data, *_rest = execute(
			{"company": COMPANY, "from_date": nowdate(), "to_date": add_days(nowdate(), -3)}
		)
		self.assertEqual(len(data), frappe.db.count("Workstation"))

	def test_status_thresholds(self):
		self.assertEqual(status_for(84.9), ("Free", "green"))
		self.assertEqual(status_for(85), ("Busy", "orange"))
		self.assertEqual(status_for(100), ("Busy", "orange"))
		self.assertEqual(status_for(100.1), ("Overloaded", "red"))

	def test_downtime_constants(self):
		self.assertEqual(
			downtime_for(frappe._dict(name="Line A - Assembly", workstation_name="Line A")), 0.10
		)
		self.assertEqual(downtime_for(frappe._dict(name="Line B", workstation_name="Line B")), 0.15)
		self.assertEqual(downtime_for(frappe._dict(name="Paint Shop", workstation_name="Paint Shop")), 0.0)

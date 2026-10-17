# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_quality_management.report.audit_findings_dashboard.audit_findings_dashboard import (
	execute,
	low_score_workstations,
)


class TestAuditFindingsDashboard(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, message, chart, summary = execute({})
		self.assertEqual(len(columns), 11)
		self.assertIsInstance(data, list)
		self.assertIn("consistently low scores", message)
		self.assertEqual(len(summary), 4)
		self.assertEqual(chart["type"], "line")

	def test_low_score_workstations(self):
		rows = [
			frappe._dict(workstation="WS-A", audit_score=60),
			frappe._dict(workstation="WS-A", audit_score=70),
			frappe._dict(workstation="WS-B", audit_score=50),
			frappe._dict(workstation="WS-C", audit_score=90),
			frappe._dict(workstation="WS-C", audit_score=95),
		]
		self.assertEqual([x[0] for x in low_score_workstations(rows)], ["WS-A"])

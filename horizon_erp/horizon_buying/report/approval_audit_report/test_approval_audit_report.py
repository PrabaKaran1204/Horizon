# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_buying.report.approval_audit_report.approval_audit_report import (
	AUTO_ESCALATION_PREFIX,
	execute,
	get_age_bucket,
)
from horizon_erp.horizon_core.jobs import add_info_comment
from horizon_erp.horizon_core.tests.fixtures import make_purchase_order, setup_common

COMPANY = "Horizon Manufacturing Ltd"


class TestApprovalAuditReport(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertTrue(columns)
		self.assertIsInstance(data, list)
		self.assertEqual(chart["data"]["labels"], ["< 24h", "24-48h", "> 48h"])
		self.assertEqual(len(summary), 3)

	def test_execute_only_overrides(self):
		_c, data, *_rest = execute({"company": COMPANY, "only_overrides": 1})
		self.assertTrue(all(frappe.utils.cint(r.blacklist_override) for r in data))

	def test_age_bucket(self):
		self.assertEqual(get_age_bucket(3), "< 24h")
		self.assertEqual(get_age_bucket(30), "24-48h")
		self.assertEqual(get_age_bucket(72), "> 48h")

	def test_auto_escalation_comments_are_transition_rows(self):
		frappe.set_user("Administrator")
		setup_common()
		po = make_purchase_order("BRTEST Clean", "BRTEST-RM", 1, 100).insert()
		add_info_comment(
			"Purchase Order",
			po.name,
			"Auto-escalated after 48h without action: Pending Dept Head → Pending Procurement Manager",
		)
		add_info_comment("Purchase Order", po.name, "Some other Info comment that is not a transition")

		_c, data, *_rest = execute({"company": COMPANY})
		rows = [r for r in data if r.purchase_order == po.name and r.transition]
		self.assertEqual(len(rows), 1)
		self.assertTrue(rows[0].transition.startswith(AUTO_ESCALATION_PREFIX))
		self.assertIn("Pending Procurement Manager", rows[0].transition)
		self.assertIsNotNone(rows[0].hours_in_previous_state)

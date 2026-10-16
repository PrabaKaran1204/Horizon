# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_operations.report.approval_audit_report.approval_audit_report import (
	execute,
	get_age_bucket,
)

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

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_accounts.report.data_validation_report.data_validation_report import (
	execute,
	gstin_is_valid,
)

COMPANY = "Horizon Manufacturing Ltd"


class TestDataValidationReport(FrappeTestCase):
	def test_execute_default_filters(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 5)
		self.assertIsInstance(data, list)
		self.assertEqual([s["label"] for s in summary], ["Total Issues", "High", "Medium", "Low"])
		self.assertEqual(summary[0]["value"], len(data))
		self.assertIn("datasets", chart["data"])

	def test_severity_filter(self):
		_c, data, *_rest = execute({"company": COMPANY, "severity": "High"})
		self.assertTrue(all(r.severity == "High" for r in data))

	def test_gstin_validation(self):
		self.assertFalse(gstin_is_valid("27AAAAA0000A1Z0"))
		self.assertTrue(gstin_is_valid("27AAPFU0939F1ZV"))

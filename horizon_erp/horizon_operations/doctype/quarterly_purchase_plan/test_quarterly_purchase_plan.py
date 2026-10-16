# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestQuarterlyPurchasePlan(FrappeTestCase):
	def test_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Quarterly Purchase Plan"))

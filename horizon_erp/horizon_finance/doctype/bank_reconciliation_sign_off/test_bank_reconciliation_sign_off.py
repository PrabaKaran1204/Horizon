# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestBankReconciliationSignoff(FrappeTestCase):
	def test_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Bank Reconciliation Sign-off"))

	def test_difference_is_computed(self):
		doc = frappe.new_doc("Bank Reconciliation Sign-off")
		doc.bank_balance = 1000.50
		doc.gl_balance = 900.25
		doc.compute_difference()
		self.assertAlmostEqual(doc.difference, 100.25, places=2)

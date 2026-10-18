# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_setup import demo_data
from horizon_erp.tests.cleanup import purge_test_residue


class TestInternalParties(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)
		super().setUpClass()

	def test_internal_parties_carry_the_other_branch_gstin(self):
		demo_data.setup_internal_parties()
		demo_data.setup_internal_parties()  # idempotent

		customer = frappe.get_doc("Customer", "Horizon Delhi DC")
		self.assertTrue(customer.is_internal_customer)
		self.assertEqual(customer.represents_company, demo_data.COMPANY)
		self.assertEqual(customer.gstin, "07AABCU9602H1ZB")

		supplier = frappe.get_doc("Supplier", "Horizon Mumbai HQ")
		self.assertTrue(supplier.is_internal_supplier)
		self.assertEqual(supplier.gstin, "27AABCU9602H1Z9")
		self.assertTrue(supplier.allow_purchase_invoice_creation_without_purchase_order)

		for party in demo_data.INTERNAL_PARTIES:
			links = frappe.get_all(
				"Dynamic Link",
				filters={
					"parenttype": "Address",
					"link_doctype": party["doctype"],
					"link_name": party["name"],
				},
				pluck="parent",
			)
			self.assertEqual(len(links), 1, party["name"])

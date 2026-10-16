# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from horizon_erp.horizon_operations.test_fixtures import (
	COMPANY,
	make_quotation,
	make_sales_order,
	make_stock,
	setup_common,
	with_dimensions,
)


class TestSelling(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()

	def tearDown(self):
		frappe.set_user("Administrator")

	# --- discounts -----------------------------------------------------------------------------
	def test_small_discount_needs_no_approval(self):
		frappe.set_user("brtest-sales@horizon.local")
		qtn = make_quotation("BRTEST Customer", "BRTEST-FG", 1, 900).insert()
		row = qtn.items[0]
		self.assertEqual(row.price_list_rate, 1000)
		self.assertEqual(row.rule_rate, 1000)
		self.assertEqual(row.discount_over_rule_pct, 10)
		self.assertEqual(qtn.needs_discount_approval, 0)
		qtn.submit()
		self.assertEqual(qtn.docstatus, 1)

	def test_large_discount_needs_reason_and_manager(self):
		frappe.set_user("brtest-sales@horizon.local")
		qtn = make_quotation("BRTEST Customer", "BRTEST-FG", 1, 800)
		with self.assertRaises(frappe.ValidationError):
			qtn.insert()  # reason missing

		qtn = make_quotation(
			"BRTEST Customer", "BRTEST-FG", 1, 800, discount_reason="Strategic account launch pricing"
		).insert()
		self.assertEqual(qtn.needs_discount_approval, 1)
		self.assertEqual(qtn.items[0].discount_over_rule_pct, 20)

		with self.assertRaises(frappe.PermissionError):
			qtn.submit()

		frappe.set_user("brtest-sm@horizon.local")
		qtn = frappe.get_doc("Quotation", qtn.name)
		qtn.submit()
		self.assertEqual(qtn.docstatus, 1)

	def test_manual_price_list_rate_blocked_for_sales_user(self):
		frappe.set_user("brtest-sales@horizon.local")
		qtn = make_quotation("BRTEST Customer", "BRTEST-FG", 1, 900)
		qtn.items[0].price_list_rate = 900
		self.assertRaises(frappe.PermissionError, qtn.insert)

	def test_quotation_availability_fields(self):
		make_stock("BRTEST-FG", self.wh.fg, 5, rate=500)
		qtn = make_quotation("BRTEST Customer", "BRTEST-FG", 2, 950).insert()
		row = qtn.items[0]
		self.assertGreaterEqual(row.available_qty, 5)
		self.assertEqual(str(row.expected_delivery_date), add_days(nowdate(), 2))

		qtn = make_quotation("BRTEST Customer", "BRTEST-FG", 500, 950).insert()
		row = qtn.items[0]
		self.assertEqual(str(row.expected_delivery_date), add_days(nowdate(), row.mfg_lead_days))

	# --- sales invoice -------------------------------------------------------------------------
	def _invoice(self):
		return with_dimensions(
			frappe.get_doc(
				{
					"doctype": "Sales Invoice",
					"customer": "BRTEST Customer",
					"company": COMPANY,
					"items": [{"item_code": "BRTEST-FG", "qty": 1, "rate": 1000}],
				}
			)
		)

	def test_invoice_without_dn_blocked_for_accounts_user(self):
		frappe.set_user("brtest-acc@horizon.local")
		self.assertRaises(frappe.PermissionError, self._invoice().insert)

	def test_invoice_without_dn_allowed_for_finance_director(self):
		frappe.set_user("brtest-fd@horizon.local")
		si = self._invoice().insert()
		comments = frappe.get_all(
			"Comment",
			filters={
				"reference_doctype": "Sales Invoice",
				"reference_name": si.name,
				"comment_type": "Comment",
			},
			pluck="content",
		)
		self.assertTrue(any("authorised by brtest-fd@horizon.local" in c for c in comments))

	# --- delivery note -------------------------------------------------------------------------
	def test_short_delivery_requires_deviation_notes_and_creates_invoice(self):
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		make_stock("BRTEST-FG", self.wh.fg, 20, rate=500)
		so = make_sales_order("BRTEST Customer", "BRTEST-FG", 10, 1000, self.wh.fg).insert()
		so.submit()

		dn = make_delivery_note(so.name)
		dn.items[0].qty = 6
		self.assertRaises(frappe.ValidationError, dn.insert)

		dn.deviation_notes = "Customer asked for a split shipment"
		dn.insert()
		dn.submit()

		si_name = frappe.db.get_value("Sales Invoice Item", {"delivery_note": dn.name}, "parent")
		self.assertTrue(si_name)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si_name, "docstatus"), 0)

	def test_signature_requires_received_by(self):
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		make_stock("BRTEST-FG", self.wh.fg, 5, rate=500)
		so = make_sales_order("BRTEST Customer", "BRTEST-FG", 2, 1000, self.wh.fg).insert()
		so.submit()
		dn = make_delivery_note(so.name)
		dn.customer_signature = "data:image/png;base64,iVBORw0KGgo="
		self.assertRaises(frappe.ValidationError, dn.insert)
		dn.received_by = "Store keeper"
		dn.insert()
		self.assertEqual(dn.docstatus, 0)

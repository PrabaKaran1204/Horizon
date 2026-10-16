# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, cint, nowdate

from horizon_erp.horizon_operations.selling import get_mfg_lead_days, get_rule_rate
from horizon_erp.horizon_operations.test_fixtures import (
	COMPANY,
	ensure_bom,
	ensure_item,
	ensure_warehouse,
	make_quotation,
	make_sales_order,
	make_stock,
	setup_common,
	with_dimensions,
)


def ensure_pricing_rule(title, item_code, discount_percentage, **extra):
	"""Selling pricing rule on one item code (FIXTEST). Idempotent; returns the Pricing Rule name."""
	existing = frappe.db.get_value("Pricing Rule", {"title": title}, "name")
	if existing:
		frappe.db.set_value("Pricing Rule", existing, {"disable": 0, **extra})
		return existing
	rule = frappe.get_doc(
		{
			"doctype": "Pricing Rule",
			"title": title,
			"apply_on": "Item Code",
			"items": [{"item_code": item_code}],
			"selling": 1,
			"price_or_product_discount": "Price",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": discount_percentage,
			"currency": "INR",
			"company": COMPANY,
			"apply_multiple_pricing_rules": 1,
			**extra,
		}
	)
	rule.flags.ignore_permissions = True
	rule.insert()
	return rule.name


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

	# --- price locked at Sales Order (DEF-05 / DEF-06) ------------------------------------------
	def test_partial_delivery_keeps_sales_order_rate_and_invoices_cleanly(self):
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		rule = ensure_pricing_rule("FIXTEST-VOLUME-8", "BRTEST-FG", 8, min_qty=50)
		try:
			make_stock("BRTEST-FG", self.wh.fg, 60, rate=500)
			so = make_sales_order("BRTEST Customer", "BRTEST-FG", 60, 1000, self.wh.fg).insert()
			self.assertEqual(so.items[0].rate, 920)  # 1000 - 8 % volume discount
			self.assertIn(rule, so.items[0].pricing_rules)
			so.submit()

			dn = make_delivery_note(so.name)
			dn.items[0].qty = 30  # below the volume threshold: the engine would re-price to 1000
			dn.deviation_notes = "Partial shipment, balance follows next week"
			dn.insert()
			self.assertEqual(dn.items[0].rate, 920)
			self.assertEqual(dn.items[0].price_list_rate, 1000)
			self.assertEqual(dn.items[0].discount_percentage, 8)
			self.assertEqual(dn.ignore_pricing_rule, 1)
			self.assertFalse(dn.items[0].pricing_rules)
			dn.save()  # a second save (the "remove pricing rule" path) must not reset the rate
			self.assertEqual(dn.items[0].rate, 920)
			dn.submit()

			si_name = frappe.db.get_value("Sales Invoice Item", {"delivery_note": dn.name}, "parent")
			self.assertTrue(si_name, "auto draft Sales Invoice missing")
			si = frappe.get_doc("Sales Invoice", si_name)
			self.assertEqual(si.items[0].rate, 920)
			self.assertEqual(si.items[0].qty, 30)
			self.assertEqual(si.ignore_pricing_rule, 1)
			si.submit()  # no "Cannot overbill" against the SO row's 60 x 920
			self.assertEqual(si.docstatus, 1)
			self.assertEqual(
				frappe.db.get_value("Sales Order Item", so.items[0].name, "billed_amt"), 30 * 920
			)
		finally:
			frappe.db.set_value("Pricing Rule", rule, "disable", 1)

	def test_auto_invoice_is_created_when_a_sales_user_submits_the_delivery(self):
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		make_stock("BRTEST-FG", self.wh.fg, 5, rate=500)
		so = make_sales_order("BRTEST Customer", "BRTEST-FG", 2, 1000, self.wh.fg).insert()
		so.submit()

		frappe.set_user("brtest-sales@horizon.local")
		self.assertFalse(frappe.has_permission("Sales Invoice", "create"))
		dn = make_delivery_note(so.name)
		dn.insert()
		dn.submit()
		si_name = frappe.db.get_value("Sales Invoice Item", {"delivery_note": dn.name}, "parent")
		self.assertTrue(si_name, "draft Sales Invoice must be created although the user cannot create one")
		si = frappe.db.get_value("Sales Invoice", si_name, ["docstatus", "owner", "customer"], as_dict=True)
		self.assertEqual(si.docstatus, 0)
		self.assertEqual(si.owner, "brtest-sales@horizon.local")
		self.assertEqual(si.customer, "BRTEST Customer")

	# --- quotation defaults (DEF-11) -------------------------------------------------------------
	def test_quotation_valid_till_defaults_from_crm_settings(self):
		qtn = make_quotation("BRTEST Customer", "BRTEST-FG", 1, 1000).insert()
		days = cint(frappe.db.get_single_value("CRM Settings", "default_valid_till")) or 30
		self.assertEqual(str(qtn.valid_till), add_days(str(qtn.transaction_date), days))
		# an explicit date is kept
		qtn = make_quotation(
			"BRTEST Customer", "BRTEST-FG", 1, 1000, valid_till=add_days(nowdate(), 5)
		).insert()
		self.assertEqual(str(qtn.valid_till), add_days(nowdate(), 5))

	# --- manufacturing lead time through the BOM tree (DEF-12) ----------------------------------
	def test_mfg_lead_days_explodes_multi_level_bom(self):
		stores = ensure_warehouse("BRTEST Stores")
		ensure_item("FIXTEST-L3-RM", valuation_rate=10, default_warehouse=stores, lead_time_days=20)
		ensure_item("FIXTEST-L2-SA", valuation_rate=50, default_warehouse=stores, lead_time_days=0)
		ensure_item("FIXTEST-L1-SA", valuation_rate=100, default_warehouse=stores, lead_time_days=0)
		ensure_item("FIXTEST-TOP", valuation_rate=500, default_warehouse=stores, lead_time_days=0)
		ensure_bom("FIXTEST-L2-SA", "FIXTEST-L3-RM", operation_minutes=30)  # 1 day + 20 = 21
		ensure_bom("FIXTEST-L1-SA", "FIXTEST-L2-SA", operation_minutes=60)  # 1 day + 21 = 22
		ensure_bom("FIXTEST-TOP", "FIXTEST-L1-SA", operation_minutes=480)  # 1 day + 22 = 23

		self.assertEqual(get_mfg_lead_days("FIXTEST-L3-RM"), 20)
		self.assertEqual(get_mfg_lead_days("FIXTEST-L2-SA"), 21)
		self.assertEqual(get_mfg_lead_days("FIXTEST-TOP"), 23)
		# the old single-level formula (own operations + direct components' lead) would give 1 day
		self.assertGreater(get_mfg_lead_days("FIXTEST-TOP"), 1)

	# --- pricing precedence (DEF-10) --------------------------------------------------------------
	def test_rule_rate_adds_stacked_discount_percentages(self):
		rules = [
			ensure_pricing_rule("FIXTEST-STACK-5", "BRTEST-FG", 5, disable=1),
			ensure_pricing_rule("FIXTEST-STACK-8", "BRTEST-FG", 8, disable=1),
			ensure_pricing_rule("FIXTEST-STACK-10", "BRTEST-FG", 10, disable=1),
		]
		row = frappe._dict(price_list_rate=6500, pricing_rules=json.dumps(rules))
		# ERPNext adds percentages of stacked rules: 5 + 8 + 10 = 23 % -> 5,005 (not 0.95 x 0.92 x 0.90)
		self.assertEqual(get_rule_rate(row), 5005.0)
		# apply_discount_on_rate compounds that rule on the already discounted rate
		on_rate = ensure_pricing_rule("FIXTEST-STACK-ON-RATE-10", "BRTEST-FG", 10, disable=1)
		frappe.db.set_value("Pricing Rule", on_rate, "apply_discount_on_rate", 1)
		row = frappe._dict(price_list_rate=6500, pricing_rules=json.dumps([rules[0], on_rate]))
		self.assertEqual(get_rule_rate(row), 5557.5)  # 5 % then 10 % of the remaining 95 % = 14.5 %
		self.assertEqual(get_rule_rate(frappe._dict(price_list_rate=100, pricing_rules=None)), 100.0)

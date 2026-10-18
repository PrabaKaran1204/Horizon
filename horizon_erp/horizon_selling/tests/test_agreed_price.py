# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Agreed Opportunity rates (Option B) and the customer's agreed Item Price (ADR-18).
Fixture prefix ``PRICETEST``.

Run:  bench --site horizon.local run-tests --app horizon_erp --skip-test-records \
	--module horizon_erp.horizon_selling.tests.test_agreed_price
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from horizon_erp.horizon_core.tests.fixtures import (
	COMPANY,
	SELLING_PRICE_LIST,
	ensure_item,
	ensure_item_price,
	make_quotation,
	setup_common,
	with_dimensions,
)
from horizon_erp.horizon_crm.opportunity import make_quotation as horizon_make_quotation
from horizon_erp.tests.cleanup import purge_test_residue

ITEM_GROUP = "PRICETEST Equipment"
ITEM = "PRICETEST-PUMP"
LIST_PRICE = 185000
PREMIUM = "Premium"
PREMIUM_PCT = 5
PREMIUM_RULE_RATE = LIST_PRICE * (100 - PREMIUM_PCT) / 100  # 1,75,750
STANDARD_GROUP = "PRICETEST Standard"
SALES_USER = "brtest-sales@horizon.local"  # Sales User only: not a discount approver
SALES_MANAGER = "brtest-sm@horizon.local"


def ensure_master(doctype, name, **values):
	if not frappe.db.exists(doctype, name):
		doc = frappe.get_doc({"doctype": doctype, **values})
		doc.flags.ignore_permissions = True
		doc.insert()
	return name


def make_customer(name, customer_group):
	"""A fresh Customer per test: agreed Item Prices persist across the tests of the class."""
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"PRICETEST {name}",
			"customer_type": "Company",
			"customer_group": customer_group,
			"territory": "India",
			"gst_category": "Unregistered",
		}
	)
	customer.flags.ignore_permissions = True
	customer.insert()
	return customer.name


def make_opportunity(party, rate, qty=2, opportunity_from="Customer"):
	opp = frappe.get_doc(
		{
			"doctype": "Opportunity",
			"opportunity_from": opportunity_from,
			"party_name": party,
			"company": COMPANY,
			"transaction_date": nowdate(),
			"items": [{"item_code": ITEM, "qty": qty, "rate": rate}],
		}
	)
	opp.insert()
	return opp


def quotation_from_opportunity(opp_name):
	qtn = horizon_make_quotation(opp_name)
	qtn.transaction_date = nowdate()
	return with_dimensions(qtn)


def fresh_quotation(customer, qty=1, rate=None, **extra):
	"""A quotation typed on the form (not mapped): no rate posted -> priced by the engine."""
	qtn = make_quotation(customer, ITEM, qty, rate, **extra)
	return qtn


def customer_prices(customer):
	return frappe.get_all(
		"Item Price",
		filters={"item_code": ITEM, "price_list": SELLING_PRICE_LIST, "customer": customer},
		fields=["name", "price_list_rate", "valid_from", "uom", "note"],
		order_by="valid_from asc",
	)


def type_rate(row, rate):
	"""What the form posts when a user types a rate (ERPNext's client ``rate`` trigger)."""
	row.rate = rate
	row.margin_type = "Amount"
	row.margin_rate_or_amount = 0


def make_sales_order_from(quotation, warehouse):
	from erpnext.selling.doctype.quotation.quotation import make_sales_order

	so = make_sales_order(quotation)
	so.delivery_date = add_days(nowdate(), 7)
	for row in so.items:
		row.delivery_date = so.delivery_date
		row.warehouse = warehouse
	return with_dimensions(so)


class TestAgreedPrice(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		ensure_master(
			"Customer Group",
			PREMIUM,
			customer_group_name=PREMIUM,
			parent_customer_group="All Customer Groups",
		)
		ensure_master(
			"Customer Group",
			STANDARD_GROUP,
			customer_group_name=STANDARD_GROUP,
			parent_customer_group="All Customer Groups",
		)
		ensure_master(
			"Item Group", ITEM_GROUP, item_group_name=ITEM_GROUP, parent_item_group="All Item Groups"
		)
		ensure_item(ITEM, item_group=ITEM_GROUP)
		ensure_item_price(ITEM, LIST_PRICE)
		cls.rule = cls.ensure_premium_rule()

	@classmethod
	def ensure_premium_rule(cls):
		title = "PRICETEST Premium 5"
		existing = frappe.db.get_value("Pricing Rule", {"title": title}, "name")
		if existing:
			return existing
		rule = frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": title,
				"apply_on": "Item Group",
				"item_groups": [{"item_group": ITEM_GROUP}],
				"applicable_for": "Customer Group",
				"customer_group": PREMIUM,
				"selling": 1,
				"price_or_product_discount": "Price",
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": PREMIUM_PCT,
				"currency": "INR",
				"company": COMPANY,
				"apply_multiple_pricing_rules": 1,  # as PR-PREMIUM-5
			}
		)
		rule.flags.ignore_permissions = True
		rule.insert()
		return rule.name

	def setUp(self):
		frappe.set_user(SALES_USER)

	def tearDown(self):
		frappe.set_user("Administrator")

	def assert_row(self, row, price_list_rate, rate, rule_rate):
		self.assertEqual(
			(row.price_list_rate, row.rate, row.rule_rate, row.discount_over_rule_pct),
			(price_list_rate, rate, rule_rate, 0),
		)

	# --- Change 1: Option B ----------------------------------------------------------------------
	def test_higher_opportunity_rate_kept_through_save_submit_and_sales_order(self):
		customer = make_customer("Bharat Standard", STANDARD_GROUP)
		opp = make_opportunity(customer, 200000)

		frappe.clear_messages()
		qtn = quotation_from_opportunity(opp.name)
		row = qtn.items[0]
		# ERPNext's own representation of a rate above the list price on a row without rules
		self.assertEqual((row.price_list_rate, row.rate, row.discount_percentage), (LIST_PRICE, 200000, 0))
		self.assertEqual((row.margin_type, row.margin_rate_or_amount), ("Amount", 15000))
		self.assertEqual(row.horizon_agreed_rate, 200000)
		messages = [m.get("message", "") for m in frappe.get_message_log()]
		self.assertTrue(any("Agreed Opportunity rates kept" in m for m in messages), messages)

		qtn.insert()  # a Sales User: no ad-hoc pricing error, price_list_rate untouched
		self.assertEqual(qtn.needs_discount_approval, 0)
		self.assert_row(qtn.items[0], LIST_PRICE, 200000, LIST_PRICE)
		qtn.reload()
		qtn.save()
		self.assertEqual(qtn.items[0].rate, 200000)
		qtn.submit()
		self.assertEqual((qtn.docstatus, qtn.items[0].rate, qtn.grand_total > 0), (1, 200000, True))

		so = make_sales_order_from(qtn.name, self.wh.fg)
		so.insert()
		so.submit()
		self.assertEqual((so.items[0].price_list_rate, so.items[0].rate), (LIST_PRICE, 200000))
		self.assertEqual(so.items[0].horizon_agreed_rate, 200000)
		self.assertEqual(so.needs_discount_approval, 0)

	def test_lower_opportunity_rate_repriced_with_alert(self):
		"""DEF-23 regression: a low estimate is replaced by the rule rate and announced."""
		customer = make_customer("Low Estimate", STANDARD_GROUP)
		opp = make_opportunity(customer, 100000)
		frappe.clear_messages()
		qtn = quotation_from_opportunity(opp.name)
		self.assertEqual((qtn.items[0].rate, qtn.items[0].discount_percentage), (LIST_PRICE, 0))
		messages = [m.get("message", "") for m in frappe.get_message_log()]
		self.assertTrue(any("instead of the lower Opportunity rate" in m for m in messages), messages)
		qtn.insert()
		self.assertEqual(qtn.needs_discount_approval, 0)

	def test_premium_agreed_rate_kept_recorded_and_reused(self):
		premium = make_customer("Premium Agreed", PREMIUM)
		agreed = 180000  # above the Premium rule rate 1,75,750, below the list price
		qtn = quotation_from_opportunity(make_opportunity(premium, agreed).name)
		row = qtn.items[0]
		self.assertIn(self.rule, row.pricing_rules)
		self.assertEqual((row.rate, row.discount_percentage, row.discount_amount), (agreed, 0, 5000))
		self.assertEqual(row.horizon_agreed_rate, agreed)

		qtn.insert()
		self.assert_row(qtn.items[0], LIST_PRICE, agreed, PREMIUM_RULE_RATE)
		self.assertEqual(qtn.needs_discount_approval, 0)
		qtn.reload()
		qtn.save()  # the Premium rule is re-applied on every validate; the agreed rate stays
		self.assertEqual(qtn.items[0].rate, agreed)
		qtn.submit()
		self.assertEqual(qtn.items[0].rate, agreed)

		# the Sales Order keeps it against the Premium rule (agreed rate mapped by fieldname)
		so = make_sales_order_from(qtn.name, self.wh.fg).insert()
		self.assertIn(self.rule, so.items[0].pricing_rules)
		self.assertEqual((so.items[0].rate, so.items[0].horizon_agreed_rate), (agreed, agreed))
		self.assertEqual(so.needs_discount_approval, 0)
		so.delete()

		# grossed up: 1,80,000 / 0.95 = 1,89,473.68 -> 5 % Premium -> 1,80,000.00
		prices = customer_prices(premium)
		self.assertEqual([(p.price_list_rate, str(p.valid_from)) for p in prices], [(189473.68, nowdate())])
		self.assertTrue(prices[0].note.startswith(f"Quotation {qtn.name}: "))
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{"reference_doctype": "Quotation", "reference_name": qtn.name, "comment_type": "Info"},
			)
		)

		# the next quotation for the customer starts from the agreed price, net after the rules
		fresh = fresh_quotation(premium).insert()
		row = fresh.items[0]
		self.assertIn(self.rule, row.pricing_rules)
		self.assertEqual(row.discount_percentage, PREMIUM_PCT)
		self.assert_row(row, 189473.68, agreed, agreed)
		self.assertEqual(fresh.needs_discount_approval, 0)

		# nobody else gets it
		self.assertEqual(
			fresh_quotation(make_customer("Premium Other", PREMIUM)).insert().items[0].rate, PREMIUM_RULE_RATE
		)
		standard = fresh_quotation(make_customer("Standard Other", STANDARD_GROUP)).insert()
		self.assertEqual(
			(standard.items[0].price_list_rate, standard.items[0].rate), (LIST_PRICE, LIST_PRICE)
		)

	def test_typed_rate_moves_or_drops_the_agreed_rate(self):
		customer = make_customer("Retyped", STANDARD_GROUP)
		qtn = quotation_from_opportunity(make_opportunity(customer, 200000).name).insert()
		type_rate(qtn.items[0], 190000)  # still above the rule rate: the new agreed rate
		qtn.save()
		self.assertEqual((qtn.items[0].rate, qtn.items[0].horizon_agreed_rate), (190000, 190000))
		type_rate(qtn.items[0], 180000)  # below the rule rate 1,85,000: an ordinary 2.7 % discount
		qtn.save()
		self.assertEqual((qtn.items[0].rate, qtn.items[0].horizon_agreed_rate), (180000, 0))
		self.assertEqual(qtn.items[0].discount_over_rule_pct, 2.7)

	def test_rate_posted_without_agreement_still_gets_the_rule(self):
		"""Server / API documents posting the list price as rate keep standard pricing."""
		premium = make_customer("Premium Api", PREMIUM)
		qtn = fresh_quotation(premium, rate=LIST_PRICE).insert()
		self.assertEqual((qtn.items[0].rate, qtn.items[0].horizon_agreed_rate), (PREMIUM_RULE_RATE, 0))

	def test_switch_to_customer_keeps_agreed_rate(self):
		"""A qualified Lead quotation moved to its Premium Customer keeps the agreed higher rate."""
		frappe.set_user(SALES_MANAGER)  # creates the Customer from the Opportunity
		lead = frappe.get_doc(
			{
				"doctype": "Lead",
				"first_name": "PRICETEST Switch",
				"company_name": "PRICETEST Switch Pvt Ltd",
				"email_id": "pricetest.switch@pricetest.example.com",
				"territory": "India",
				"company": COMPANY,
			}
		).insert()
		opp = frappe.get_doc(
			{
				"doctype": "Opportunity",
				"opportunity_from": "Lead",
				"party_name": lead.name,
				"company": COMPANY,
				"transaction_date": nowdate(),
				"customer_group": PREMIUM,
				"territory": "India",
				"horizon_gst_category": "Unregistered",
				"items": [{"item_code": ITEM, "qty": 1, "rate": 200000}],
			}
		).insert()
		qtn = quotation_from_opportunity(opp.name).insert()
		row = qtn.items[0]
		self.assertEqual(qtn.quotation_to, "Customer")
		self.assertIn(self.rule, row.pricing_rules)
		self.assert_row(row, LIST_PRICE, 200000, PREMIUM_RULE_RATE)

	# --- Change 2: idempotent agreed Item Price ---------------------------------------------------
	def test_new_agreed_rate_updates_the_price_without_duplicates_and_cancel_reverses(self):
		customer = make_customer("Repeat Buyer", STANDARD_GROUP)
		first = quotation_from_opportunity(make_opportunity(customer, 200000).name).insert()
		first.submit()
		self.assertEqual([p.price_list_rate for p in customer_prices(customer)], [200000])

		# same customer, same day, a higher agreed rate typed on a fresh quotation -> updated in place
		second = fresh_quotation(customer, rate=210000).insert()
		self.assertEqual((second.items[0].price_list_rate, second.items[0].rate), (200000, 210000))
		second.submit()
		prices = customer_prices(customer)
		self.assertEqual([p.price_list_rate for p in prices], [210000])
		self.assertTrue(prices[0].note.startswith(f"Quotation {second.name}: "))
		self.assertIn(f"--- replaced price_list_rate=200000.0\nQuotation {first.name}: ", prices[0].note)

		# at the rule rate (now the agreed price) and below it: nothing recorded
		fresh_quotation(customer).insert().submit()
		fresh_quotation(customer, rate=205000).insert().submit()  # 2.4 % below: no approval needed
		self.assertEqual([p.price_list_rate for p in customer_prices(customer)], [210000])

		# a later agreement keeps the history by valid_from
		later = fresh_quotation(customer, rate=220000, transaction_date=add_days(nowdate(), 1))
		later.insert()
		later.submit()
		self.assertEqual([p.price_list_rate for p in customer_prices(customer)], [210000, 220000])

		# cancelling reverses: the later price goes, the updated one gets its old rate back
		frappe.set_user(SALES_MANAGER)
		later.cancel()
		second.reload()
		second.cancel()
		self.assertEqual([p.price_list_rate for p in customer_prices(customer)], [200000])
		first.reload()
		first.cancel()
		self.assertEqual(customer_prices(customer), [])

	def test_lead_quotation_creates_no_item_price(self):
		lead = frappe.get_doc(
			{
				"doctype": "Lead",
				"first_name": "PRICETEST Lead",
				"company_name": "PRICETEST Lead Pvt Ltd",
				"email_id": "pricetest.lead@pricetest.example.com",
				"territory": "India",
				"company": COMPANY,
			}
		).insert()
		opp = make_opportunity(lead.name, 200000, opportunity_from="Lead")  # unqualified: stays on Lead
		qtn = quotation_from_opportunity(opp.name).insert()
		self.assertEqual((qtn.quotation_to, qtn.items[0].rate), ("Lead", 200000))
		qtn.submit()
		self.assertFalse(
			frappe.db.exists(
				"Item Price",
				{"item_code": ITEM, "customer": ["is", "set"], "note": ["like", f"%{qtn.name}%"]},
			)
		)

	def test_genuine_manual_discount_still_needs_approval(self):
		customer = make_customer("Discount Seeker", STANDARD_GROUP)
		qtn = fresh_quotation(customer, rate=LIST_PRICE * 0.8)
		self.assertRaisesRegex(frappe.ValidationError, "Discount Reason", qtn.insert)
		qtn = fresh_quotation(
			customer, rate=LIST_PRICE * 0.8, discount_reason="PRICETEST strategic launch pricing"
		).insert()
		self.assertEqual((qtn.needs_discount_approval, qtn.items[0].discount_over_rule_pct), (1, 20))
		self.assertRaises(frappe.PermissionError, qtn.submit)
		self.assertEqual(customer_prices(customer), [])

	def test_customer_price_is_no_list_price_for_other_customers(self):
		"""A Sales User may not type another customer's agreed price as the list price."""
		owner = make_customer("Price Owner", STANDARD_GROUP)
		quotation_from_opportunity(make_opportunity(owner, 200000).name).insert().submit()
		other = fresh_quotation(make_customer("Price Borrower", STANDARD_GROUP))
		other.items[0].price_list_rate = 200000
		other.items[0].rate = 200000
		self.assertRaises(frappe.PermissionError, other.insert)

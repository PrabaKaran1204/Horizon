# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Customer created from a qualified Opportunity (ADR-17). Fixture prefix ``LEADTEST``.

Run:  bench --site horizon.local run-tests --app horizon_erp --skip-test-records \
	--module horizon_erp.horizon_crm.tests.test_opportunity_customer
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from horizon_erp.horizon_core.tests.fixtures import (
	COMPANY,
	SELLING_PRICE_LIST,
	ensure_item,
	ensure_item_price,
	setup_common,
	with_dimensions,
)
from horizon_erp.horizon_crm.opportunity import ensure_customer_from_opportunity
from horizon_erp.horizon_setup.demo_data import make_gstin
from horizon_erp.tests.cleanup import purge_test_residue

PREFIX = "LEADTEST"
ITEM_GROUP = "LEADTEST Equipment"
ITEM = "LEADTEST-EQUIP"
PRICE = 100000
PREMIUM = "Premium"
PREMIUM_PCT = 5
GSTIN_MH = make_gstin("27", "AAACL0001T")  # Maharashtra, checksum-valid
SALES_MANAGER = "brtest-sm@horizon.local"
NO_SALES_ROLE = "brtest-pu@horizon.local"


def ensure_master(doctype, name, **values):
	if not frappe.db.exists(doctype, name):
		doc = frappe.get_doc({"doctype": doctype, **values})
		doc.flags.ignore_permissions = True
		doc.insert()
	return name


def make_lead(company_name, first_name):
	lead = frappe.get_doc(
		{
			"doctype": "Lead",
			"first_name": first_name,
			"company_name": company_name,
			"email_id": f"{frappe.scrub(first_name)}@leadtest.example.com",
			"source": "Exhibition",
			"territory": "West",
			"company": COMPANY,
		}
	)
	lead.insert()
	return lead


def make_opportunity(lead, **details):
	opp = frappe.get_doc(
		{
			"doctype": "Opportunity",
			"opportunity_from": "Lead",
			"party_name": lead,
			"company": COMPANY,
			"transaction_date": nowdate(),
			"items": [{"item_code": ITEM, "qty": 1, "rate": PRICE}],
			**details,
		}
	)
	opp.insert()
	return opp


def qualified_details(**overrides):
	details = {
		"customer_group": PREMIUM,
		"territory": "West",
		"horizon_gst_category": "Registered Regular",
		"horizon_gstin": GSTIN_MH,
		"horizon_billing_address_line1": "LEADTEST Plot 12, MIDC Bhosari",
		"city": "Pune",
		"state": "Maharashtra",
		"country": "India",
		"horizon_billing_pincode": "411026",
		"horizon_credit_limit": 2500000,
		"horizon_payment_terms": "Net 30",
	}
	details.update(overrides)
	return details


def quotation_from_opportunity(opp_name):
	from erpnext.crm.doctype.opportunity.opportunity import make_quotation

	qtn = make_quotation(opp_name)
	qtn.transaction_date = nowdate()
	qtn.selling_price_list = SELLING_PRICE_LIST
	return with_dimensions(qtn)


class TestOpportunityCustomer(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		setup_common()
		ensure_master(
			"Customer Group",
			PREMIUM,
			customer_group_name=PREMIUM,
			parent_customer_group="All Customer Groups",
		)
		ensure_master("Territory", "West", territory_name="West", parent_territory="All Territories")
		ensure_master(
			"Payment Terms Template",
			"Net 30",
			template_name="Net 30",
			terms=[
				{"invoice_portion": 100, "due_date_based_on": "Day(s) after invoice date", "credit_days": 30}
			],
		)
		ensure_master(
			"Item Group", ITEM_GROUP, item_group_name=ITEM_GROUP, parent_item_group="All Item Groups"
		)
		ensure_item(ITEM, item_group=ITEM_GROUP)
		ensure_item_price(ITEM, PRICE)
		cls.rule = cls.ensure_premium_rule()

	@classmethod
	def ensure_premium_rule(cls):
		title = "LEADTEST Premium 5"
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
				"apply_multiple_pricing_rules": 1,
			}
		)
		rule.flags.ignore_permissions = True
		rule.insert()
		return rule.name

	def setUp(self):
		frappe.set_user(SALES_MANAGER)

	def tearDown(self):
		frappe.set_user("Administrator")

	# --- customer creation ---------------------------------------------------------------------
	def test_customer_created_with_commercial_details(self):
		lead = make_lead("LEADTEST Pumps Pvt Ltd", "LEADTEST Karthik")
		opp = make_opportunity(lead.name, **qualified_details())
		self.assertEqual(
			opp.contact_person,
			frappe.db.get_value("Dynamic Link", {"link_name": lead.name, "parenttype": "Contact"}, "parent"),
		)

		customer_name = ensure_customer_from_opportunity(opp.name)

		self.assertEqual(frappe.db.count("Customer", {"lead_name": lead.name}), 1)
		customer = frappe.get_doc("Customer", customer_name)
		self.assertEqual(customer.customer_name, "LEADTEST Pumps Pvt Ltd")
		self.assertEqual(customer.customer_type, "Company")
		self.assertEqual(customer.customer_group, PREMIUM)
		self.assertEqual(customer.territory, "West")
		self.assertEqual(customer.gst_category, "Registered Regular")
		self.assertEqual(customer.gstin, GSTIN_MH)
		self.assertEqual(customer.payment_terms, "Net 30")
		self.assertEqual(customer.opportunity_name, opp.name)
		self.assertEqual([(r.company, r.credit_limit) for r in customer.credit_limits], [(COMPANY, 2500000)])

		address = frappe.get_doc("Address", customer.customer_primary_address)
		self.assertEqual(address.address_type, "Billing")
		self.assertEqual(address.gstin, GSTIN_MH)
		self.assertEqual(address.gst_state_number, "27")
		self.assertEqual((address.city, address.state, address.pincode), ("Pune", "Maharashtra", "411026"))
		self.assertTrue(address.has_link("Customer", customer_name))

		contact = frappe.get_doc("Contact", customer.customer_primary_contact)
		self.assertTrue(contact.has_link("Lead", lead.name))
		self.assertTrue(contact.has_link("Customer", customer_name))

		self.assertEqual(frappe.db.get_value("Lead", lead.name, "status"), "Converted")
		self.assertEqual(frappe.db.get_value("Opportunity", opp.name, "horizon_customer"), customer_name)
		self.assertEqual(frappe.db.get_value("Opportunity", opp.name, "opportunity_from"), "Lead")
		for doctype, name in (("Lead", lead.name), ("Customer", customer_name), ("Opportunity", opp.name)):
			self.assertTrue(
				frappe.db.exists(
					"Comment", {"reference_doctype": doctype, "reference_name": name, "comment_type": "Info"}
				),
				doctype,
			)

		# idempotent: same customer, nothing duplicated
		self.assertEqual(ensure_customer_from_opportunity(opp.name), customer_name)
		self.assertEqual(frappe.db.count("Customer", {"lead_name": lead.name}), 1)
		self.assertEqual(
			frappe.db.count(
				"Dynamic Link",
				{"parenttype": "Address", "link_doctype": "Customer", "link_name": customer_name},
			),
			1,
		)

	def test_permission_required(self):
		lead = make_lead("LEADTEST Perm Pvt Ltd", "LEADTEST Perm")
		opp = make_opportunity(lead.name, **qualified_details())
		frappe.set_user(NO_SALES_ROLE)
		self.assertRaises(frappe.PermissionError, ensure_customer_from_opportunity, opp.name)

	# --- validation ----------------------------------------------------------------------------
	def test_invalid_gstin_rejected(self):
		lead = make_lead("LEADTEST Bad Gstin Ltd", "LEADTEST Bad")
		bad = GSTIN_MH[:-1] + ("A" if GSTIN_MH[-1] != "A" else "B")
		self.assertRaises(
			frappe.ValidationError, make_opportunity, lead.name, **qualified_details(horizon_gstin=bad)
		)

	def test_gstin_state_mismatch_rejected(self):
		lead = make_lead("LEADTEST Mismatch Ltd", "LEADTEST Mismatch")
		self.assertRaises(
			frappe.ValidationError, make_opportunity, lead.name, **qualified_details(state="Tamil Nadu")
		)

	def test_registered_regular_needs_gstin(self):
		lead = make_lead("LEADTEST No Gstin Ltd", "LEADTEST NoGstin")
		self.assertRaises(
			frappe.ValidationError, make_opportunity, lead.name, **qualified_details(horizon_gstin=None)
		)

	def test_state_set_from_gstin_and_normalised(self):
		lead = make_lead("LEADTEST State Ltd", "LEADTEST State")
		opp = make_opportunity(lead.name, **qualified_details(state=None, horizon_gstin=GSTIN_MH.lower()))
		self.assertEqual((opp.state, opp.horizon_gstin), ("Maharashtra", GSTIN_MH))
		opp = make_opportunity(lead.name, **qualified_details(state="maharashtra"))
		self.assertEqual(opp.state, "Maharashtra")

	# --- quotation -----------------------------------------------------------------------------
	def test_quotation_from_opportunity_switches_to_customer_before_pricing(self):
		lead = make_lead("LEADTEST Quote Pvt Ltd", "LEADTEST Quote")
		opp = make_opportunity(lead.name, **qualified_details())
		qtn = quotation_from_opportunity(opp.name)
		self.assertEqual(qtn.quotation_to, "Lead")  # ERPNext's mapper copies opportunity_from
		qtn.insert()

		customer = frappe.db.get_value("Customer", {"lead_name": lead.name}, "name")
		self.assertTrue(customer)
		self.assertEqual((qtn.quotation_to, qtn.party_name), ("Customer", customer))
		self.assertEqual(qtn.customer_name, "LEADTEST Quote Pvt Ltd")
		self.assertEqual(qtn.customer_group, PREMIUM)
		self.assertEqual(qtn.territory, "West")
		self.assertEqual(
			qtn.customer_address, frappe.db.get_value("Customer", customer, "customer_primary_address")
		)
		self.assertEqual(qtn.billing_address_gstin, GSTIN_MH)
		self.assertEqual(qtn.place_of_supply, "27-Maharashtra")

		row = qtn.items[0]
		self.assertIn(self.rule, row.pricing_rules)
		self.assertEqual(row.price_list_rate, PRICE)
		self.assertEqual(row.discount_percentage, PREMIUM_PCT)
		self.assertEqual(row.rate, PRICE * (100 - PREMIUM_PCT) / 100)
		self.assertEqual(frappe.db.get_value("Opportunity", opp.name, "horizon_customer"), customer)

		# the Sales Order path finds the same Customer (no second one from create_customer_from_lead)
		from erpnext.selling.doctype.quotation.quotation import _make_customer

		qtn.submit()
		self.assertEqual(_make_customer(qtn.name).name, customer)
		self.assertEqual(frappe.db.count("Customer", {"lead_name": lead.name}), 1)

	def test_quotation_to_converted_lead_uses_existing_customer(self):
		lead = make_lead("LEADTEST Direct Pvt Ltd", "LEADTEST Direct")
		opp = make_opportunity(lead.name, **qualified_details())
		customer = ensure_customer_from_opportunity(opp.name)
		qtn = with_dimensions(
			frappe.get_doc(
				{
					"doctype": "Quotation",
					"quotation_to": "Lead",
					"party_name": lead.name,
					"company": COMPANY,
					"transaction_date": nowdate(),
					"selling_price_list": SELLING_PRICE_LIST,
					"items": [{"item_code": ITEM, "qty": 1}],
				}
			)
		).insert()
		self.assertEqual((qtn.quotation_to, qtn.party_name), ("Customer", customer))
		self.assertEqual(qtn.items[0].discount_percentage, PREMIUM_PCT)

	def test_quotation_without_details_stays_on_lead(self):
		lead = make_lead("LEADTEST Light Ltd", "LEADTEST Light")
		opp = make_opportunity(lead.name)  # unqualified: no customer details
		frappe.clear_messages()
		qtn = quotation_from_opportunity(opp.name).insert()

		self.assertEqual((qtn.quotation_to, qtn.party_name), ("Lead", lead.name))
		self.assertFalse(frappe.db.exists("Customer", {"lead_name": lead.name}))
		self.assertNotIn(self.rule, qtn.items[0].pricing_rules or "")
		messages = [m.get("message", "") for m in frappe.get_message_log()]
		self.assertTrue(any("stays on Lead" in m for m in messages), messages)

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Customer created from a qualified Opportunity (ADR-17). Fixture prefix ``LEADTEST``.

Run:  bench --site horizon.local run-tests --app horizon_erp --skip-test-records \
	--module horizon_erp.horizon_crm.tests.test_opportunity_customer
"""

import json

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
from horizon_erp.horizon_crm.opportunity import ensure_customer_from_opportunity, make_quotation
from horizon_erp.horizon_setup.demo_data import make_gstin
from horizon_erp.tests.cleanup import purge_test_residue

PREFIX = "LEADTEST"
ITEM_GROUP = "LEADTEST Equipment"
ITEM = "LEADTEST-EQUIP"
PRICE = 100000
PREMIUM = "Premium"
PREMIUM_PCT = 5
ESTIMATE = 60000  # Opportunity Item rate typed as an estimate, 40 % below the list price (DEF-23)
LEAD_ONLY = "eval:doc.opportunity_from=='Lead'"
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

	# --- DEF-23: the Opportunity estimate never becomes the quotation rate ---------------------
	def test_opportunity_estimate_rate_is_not_copied_to_quotation(self):
		"""Root cause: ERPNext's mapper copies the Opportunity Item rate onto the Quotation row and only
		overwrites it when a pricing rule applies. The form then posted exactly this row (captured in
		the browser): price_list_rate = list price, rate = estimate, discount_percentage 0,
		pricing_rules empty, and validate_discounts asked for a discount reason."""
		from erpnext.crm.doctype.opportunity.opportunity import make_quotation as erpnext_make_quotation

		lead = make_lead("LEADTEST Estimate Ltd", "LEADTEST Estimate")
		opp = make_opportunity(lead.name, items=[{"item_code": ITEM, "qty": 2, "rate": ESTIMATE}])

		standard = with_dimensions(erpnext_make_quotation(opp.name))
		row = standard.items[0]
		self.assertEqual((row.price_list_rate, row.rate), (PRICE, ESTIMATE))
		self.assertFalse(row.discount_percentage)
		self.assertFalse(row.pricing_rules)
		self.assertRaisesRegex(frappe.ValidationError, "Discount Reason", standard.insert)

		qtn = with_dimensions(make_quotation(opp.name))
		row = qtn.items[0]
		self.assertEqual((row.price_list_rate, row.rate, row.discount_percentage), (PRICE, PRICE, 0))
		qtn.insert()
		self.assertEqual(qtn.needs_discount_approval, 0)
		self.assertEqual((qtn.items[0].rule_rate, qtn.items[0].discount_over_rule_pct), (PRICE, 0))

	def test_opportunity_quotation_keeps_pricing_rule_discount(self):
		lead = make_lead("LEADTEST Estimate Rule Ltd", "LEADTEST EstimateRule")
		opp = make_opportunity(
			lead.name, **qualified_details(), items=[{"item_code": ITEM, "qty": 1, "rate": ESTIMATE}]
		)
		qtn = with_dimensions(make_quotation(opp.name)).insert()

		row = qtn.items[0]
		self.assertEqual(qtn.quotation_to, "Customer")
		self.assertIn(self.rule, row.pricing_rules)
		self.assertEqual(row.rate, PRICE * (100 - PREMIUM_PCT) / 100)
		self.assertEqual(qtn.needs_discount_approval, 0)

	def test_get_items_from_opportunity_keeps_rows_already_on_the_quotation(self):
		lead = make_lead("LEADTEST Get Items Ltd", "LEADTEST GetItems")
		opp = make_opportunity(lead.name, items=[{"item_code": ITEM, "qty": 1, "rate": ESTIMATE}])
		target = {
			"doctype": "Quotation",
			"quotation_to": "Lead",
			"party_name": lead.name,
			"company": COMPANY,
			"transaction_date": nowdate(),
			"selling_price_list": SELLING_PRICE_LIST,
			"items": [
				{
					"doctype": "Quotation Item",
					"name": "new-quotation-item-leadtest",
					"item_code": ITEM,
					"qty": 1,
					"price_list_rate": PRICE,
					"rate": 90000,  # mapped earlier, then edited by the user
					"prevdoc_doctype": "Opportunity",
					"prevdoc_docname": opp.name,
				}
			],
		}
		qtn = make_quotation(opp.name, json.dumps(target))

		# ERPNext's map adds Opportunity rows only to an empty table ("add_if_empty"); the row already
		# on the form is never re-priced
		self.assertEqual(
			[(row.name, row.rate) for row in qtn.items], [("new-quotation-item-leadtest", 90000)]
		)

	def test_genuine_manual_discount_still_needs_reason(self):
		lead = make_lead("LEADTEST Manual Ltd", "LEADTEST Manual")
		opp = make_opportunity(lead.name)
		qtn = with_dimensions(make_quotation(opp.name))
		qtn.items[0].discount_percentage = 20
		qtn.items[0].rate = PRICE * 0.8
		self.assertRaisesRegex(frappe.ValidationError, "Discount Reason", qtn.insert)

		qtn.discount_reason = "LEADTEST launch pricing agreed with buyer"
		qtn.insert()
		self.assertEqual((qtn.needs_discount_approval, qtn.items[0].discount_over_rule_pct), (1, 20))

	def test_switch_reprices_rows_priced_for_the_lead(self):
		"""A row the form priced on the Lead (only a rule for everyone) gets the Customer's Premium rule
		after the switch; ERPNext alone re-applies the rules stored on the row during validate."""
		everyone = frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": "LEADTEST Everyone 2",
				"apply_on": "Item Group",
				"item_groups": [{"item_group": ITEM_GROUP}],
				"selling": 1,
				"price_or_product_discount": "Price",
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": 2,
				"currency": "INR",
				"company": COMPANY,
				"apply_multiple_pricing_rules": 1,
			}
		)
		everyone.flags.ignore_permissions = True
		everyone.insert()
		self.addCleanup(frappe.db.set_value, "Pricing Rule", everyone.name, "disable", 1)

		lead = make_lead("LEADTEST Switch Ltd", "LEADTEST Switch")
		opp = make_opportunity(lead.name, **qualified_details())
		qtn = with_dimensions(
			frappe.get_doc(
				{
					"doctype": "Quotation",
					"quotation_to": "Lead",
					"party_name": lead.name,
					"opportunity": opp.name,
					"company": COMPANY,
					"transaction_date": nowdate(),
					"selling_price_list": SELLING_PRICE_LIST,
					"items": [
						{  # as posted by the form for the Lead
							"item_code": ITEM,
							"qty": 1,
							"price_list_rate": PRICE,
							"discount_percentage": 2,
							"rate": PRICE * 0.98,
							"pricing_rules": json.dumps([everyone.name]),
						}
					],
				}
			)
		).insert()

		row = qtn.items[0]
		self.assertEqual(qtn.quotation_to, "Customer")
		self.assertEqual(set(json.loads(row.pricing_rules)), {self.rule, everyone.name})
		self.assertEqual(row.discount_percentage, PREMIUM_PCT + 2)
		self.assertEqual(row.rate, PRICE * (100 - PREMIUM_PCT - 2) / 100)
		self.assertEqual((row.rule_rate, row.discount_over_rule_pct), (row.rate, 0))

	# --- DEF-24: customer details asked on the Opportunity's main tab -------------------------
	def test_lead_opportunity_customer_details_on_main_tab_and_required(self):
		meta = frappe.get_meta("Opportunity")
		fieldnames = [df.fieldname for df in meta.fields]
		section = fieldnames.index("horizon_customer_details_section")
		self.assertEqual(fieldnames[section - 1], "probability")  # right after the party block
		first_tab = next(i for i, df in enumerate(meta.fields) if df.fieldtype == "Tab Break")
		self.assertLess(section, first_tab)
		self.assertEqual(meta.get_field("horizon_customer_details_section").depends_on, LEAD_ONLY)

		for fieldname in (
			"customer_group",
			"horizon_gst_category",
			"horizon_billing_address_line1",
			"city",
			"state",
			"horizon_billing_pincode",
		):
			self.assertEqual(meta.get_field(fieldname).mandatory_depends_on, LEAD_ONLY, fieldname)
		self.assertEqual(
			meta.get_field("horizon_gstin").mandatory_depends_on,
			LEAD_ONLY + " && doc.horizon_gst_category=='Registered Regular'",
		)
		for fieldname in ("horizon_credit_limit", "horizon_payment_terms"):
			self.assertFalse(meta.get_field(fieldname).mandatory_depends_on, fieldname)
			self.assertFalse(meta.get_field(fieldname).reqd, fieldname)
		self.assertEqual(meta.get_field("horizon_payment_terms").default, "Net 30")
		self.assertFalse(meta.quick_entry)  # Lead > Create > Opportunity opens the full form

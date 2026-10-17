# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Customer created from a qualified Opportunity (ADR-17).

Standard ERPNext v15 creates the Customer of a Lead only when a Sales Order is made from the
Quotation (``quotation._make_customer`` -> ``create_customer_from_lead``), with the Selling Settings
default group / territory and no GSTIN, credit limit or payment terms. Horizon's Premium pricing rule
keys on Customer Group and GST needs a GSTIN + state, so the Customer must exist *before* the first
quotation is priced.

The Lead stays light (most leads never qualify). The commercial data is captured on the Opportunity:
standard ``customer_group`` / ``city`` / ``state`` / ``country`` / ``territory`` / ``company`` (the
first four are copied from the Lead by ``Opportunity.map_fields``) plus the ``horizon_*`` fields of
``horizon_crm/custom/opportunity.json``.

Wiring (hooks.py ``doc_events``):

- ``Opportunity.validate`` -> ``validate_opportunity``: GSTIN checksum, GST Category / GSTIN format,
  GSTIN state code vs State, contact prefilled from the Lead.
- ``Quotation.before_validate`` -> ``switch_quotation_to_customer``: a Quotation addressed to a Lead
  whose Opportunity carries the details is moved to the (created or existing) Customer before the
  controller's ``validate`` runs ``set_missing_values`` and the pricing engine. Rows still priced by
  the Lead's pricing rules are re-priced for the Customer (``reset_rule_priced_rows``).
- ``override_whitelisted_methods`` -> ``make_quotation``: ERPNext's Opportunity -> Quotation mapper
  copies the Opportunity Item ``rate`` (a free-typed estimate) onto the Quotation row; rows the price
  list prices are re-priced from the price list + pricing rules (DEF-23).

The Opportunity itself keeps ``opportunity_from = "Lead"`` (funnel reports stay Lead -> Opportunity
-> Quotation; ERPNext's Opportunity -> Quotation mapper copies it into ``quotation_to``, which the
Quotation hook then switches). ``horizon_customer`` records the Customer on the Opportunity.

The Customer is built with ERPNext's own mapper ``erpnext.crm.doctype.lead.lead._make_customer`` so
``lead_name`` is set: ``Customer.after_insert`` marks the Lead Converted, ``Customer.on_update``
re-links the Lead's Contact / Address, and the Sales Order path (``quotation._make_customer``) finds
this Customer by ``lead_name`` instead of creating a second one.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_link_to_form

from horizon_erp.horizon_selling.selling import get_rule_rate

# Roles that may trigger Customer creation from an Opportunity even without Customer "create"
# permission; the Customer, Address and Contact links are then written with ignore_permissions.
CUSTOMER_CREATOR_ROLES = ("Sales User", "Sales Manager")

# Opportunity fields that, when any is filled on a Lead opportunity, switch the validation on
CUSTOMER_DETAIL_FIELDS = (
	"customer_group",
	"horizon_gst_category",
	"horizon_gstin",
	"horizon_billing_address_line1",
	"horizon_billing_pincode",
	"horizon_credit_limit",
)

# Quotation fields copied from the Lead that must be re-fetched from the Customer after the switch
# (SellingController.set_missing_lead_customer_details only fills *empty* fields)
LEAD_DERIVED_QUOTATION_FIELDS = (
	"customer_name",
	"customer_group",
	"territory",
	"customer_address",
	"address_display",
	"shipping_address_name",
	"shipping_address",
	"tax_category",
	"taxes_and_charges",
	"place_of_supply",
	"billing_address_gstin",
	"gst_category",
)

INDIA = "India"


# ---------------------------------------------------------------------------------------------
# Opportunity: validation of the customer details
# ---------------------------------------------------------------------------------------------
def validate_opportunity(doc, method=None):
	"""Opportunity ``validate`` hook. Only acts on Lead opportunities that carry customer details."""
	if doc.opportunity_from != "Lead" or not doc.party_name:
		return

	set_contact_from_lead(doc)

	if not has_customer_details(doc):
		return

	validate_customer_details(doc)


def has_customer_details(doc):
	return any(doc.get(fieldname) for fieldname in CUSTOMER_DETAIL_FIELDS)


def validate_customer_details(doc):
	"""GSTIN checksum + category format (India Compliance), GSTIN state code vs ``state``."""
	from india_compliance.gst_india.constants import STATE_NUMBERS
	from india_compliance.gst_india.utils import validate_gst_category, validate_gstin

	doc.horizon_gstin = cstr(doc.horizon_gstin).upper().strip() or None
	doc.horizon_billing_pincode = cstr(doc.horizon_billing_pincode).strip() or None

	if doc.horizon_gstin:
		doc.horizon_gstin = validate_gstin(doc.horizon_gstin)
		doc.country = doc.country or INDIA

	if doc.horizon_gst_category:
		validate_gst_category(doc.horizon_gst_category, doc.horizon_gstin)
	elif doc.horizon_gstin:
		doc.horizon_gst_category = "Registered Regular"
		validate_gst_category(doc.horizon_gst_category, doc.horizon_gstin)

	if (doc.country or INDIA) != INDIA:
		return

	gstin_state = get_state_from_gstin(doc.horizon_gstin)
	if doc.state:
		doc.state = get_canonical_state(doc.state)
	elif gstin_state:
		doc.state = gstin_state

	if doc.horizon_gstin and doc.state and STATE_NUMBERS.get(doc.state) != doc.horizon_gstin[:2]:
		frappe.throw(
			_("GSTIN {0} belongs to state code {1} ({2}) but the billing State is {3} (code {4})").format(
				frappe.bold(doc.horizon_gstin),
				doc.horizon_gstin[:2],
				gstin_state or _("unknown"),
				frappe.bold(doc.state),
				STATE_NUMBERS.get(doc.state),
			),
			title=_("GSTIN / State Mismatch"),
		)


def get_canonical_state(state):
	"""Return the India Compliance spelling of ``state`` (case-insensitive) or throw."""
	from india_compliance.gst_india.constants import INDIAN_STATES

	lookup = {name.lower(): name for name in INDIAN_STATES}
	canonical = lookup.get(cstr(state).strip().lower())
	if not canonical:
		frappe.throw(
			_("State {0} is not a valid Indian state for GST. Use one of: {1}").format(
				frappe.bold(state), ", ".join(sorted(INDIAN_STATES))
			),
			title=_("Invalid State"),
		)
	return canonical


def get_state_from_gstin(gstin):
	from india_compliance.gst_india.constants import STATE_NUMBERS

	if not gstin:
		return None
	code = cstr(gstin)[:2]
	return next((state for state, number in STATE_NUMBERS.items() if number == code), None)


@frappe.whitelist()
def get_gst_state_numbers():
	"""``{state: code}`` used by public/js/opportunity.js to set State from the GSTIN."""
	frappe.has_permission("Opportunity", "read", throw=True)
	from india_compliance.gst_india.constants import INDIAN_STATES

	return INDIAN_STATES


def set_contact_from_lead(doc):
	"""Prefill the Opportunity contact with the Lead's Contact (created by CRM Settings auto-contact)."""
	if doc.get("contact_person"):
		return
	contact = get_lead_contact(doc.party_name)
	if contact:
		doc.contact_person = contact


def get_lead_contact(lead):
	return frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Contact", "link_doctype": "Lead", "link_name": lead},
		"parent",
		order_by="creation asc",
	)


# ---------------------------------------------------------------------------------------------
# Customer creation
# ---------------------------------------------------------------------------------------------
def can_create_customer():
	if frappe.has_permission("Customer", "create"):
		return True
	return bool(set(frappe.get_roles()) & set(CUSTOMER_CREATOR_ROLES))


def check_can_create_customer():
	if not can_create_customer():
		frappe.throw(
			_("You need permission to create a Customer (or the Sales User / Sales Manager role)"),
			frappe.PermissionError,
		)


@frappe.whitelist()
def ensure_customer_from_opportunity(opportunity):
	"""Return the Customer of an Opportunity, creating it from the Lead + Opportunity details.

	Idempotent: an existing Customer for the Lead (``Customer.lead_name``) is returned and recorded
	on the Opportunity. Called by the Opportunity form button and by the Quotation hook.
	"""
	opp = frappe.get_doc("Opportunity", opportunity)
	opp.check_permission("write")
	if opp.opportunity_from == "Customer":
		return opp.party_name
	if opp.opportunity_from != "Lead" or not opp.party_name:
		frappe.throw(_("A Customer can only be created from an Opportunity for a Lead"))

	check_can_create_customer()
	return get_or_create_customer(opp)


def get_existing_customer(lead):
	return frappe.db.get_value("Customer", {"lead_name": lead}, "name")


def get_or_create_customer(opp):
	"""Existing Customer of the Opportunity's Lead, else a new one. Caller checks permissions."""
	lead = opp.party_name
	customer = get_existing_customer(lead)
	if customer:
		record_customer_on_opportunity(opp, customer)
		return customer

	validate_customer_details(opp)
	customer = make_customer(opp)
	address = make_billing_address(customer, opp)
	set_primary_contact(customer, lead)
	record_customer_on_opportunity(opp, customer.name)
	add_conversion_comments(customer, opp, address)
	return customer.name


def make_customer(opp):
	from erpnext.crm.doctype.lead.lead import _make_customer

	customer_group = opp.customer_group or frappe.db.get_single_value("Selling Settings", "customer_group")
	if not customer_group:
		frappe.throw(
			_("Set the Customer Group on Opportunity {0} before creating the Customer").format(
				get_link_to_form("Opportunity", opp.name)
			),
			frappe.MandatoryError,
			title=_("Customer Group Required"),
		)

	customer = _make_customer(opp.party_name, ignore_permissions=True)
	customer.customer_group = customer_group
	customer.territory = (
		opp.territory
		or customer.territory
		or frappe.db.get_single_value("Selling Settings", "territory")
		or frappe.db.get_value("Territory", {"is_group": 1, "parent_territory": ["in", ["", None]]})
	)
	customer.opportunity_name = opp.name
	customer.gst_category = opp.horizon_gst_category or (
		"Registered Regular" if opp.horizon_gstin else "Unregistered"
	)
	customer.gstin = opp.horizon_gstin
	if opp.horizon_payment_terms:
		customer.payment_terms = opp.horizon_payment_terms
	if flt(opp.horizon_credit_limit) > 0:
		customer.append(
			"credit_limits",
			{"company": get_company(opp), "credit_limit": flt(opp.horizon_credit_limit)},
		)
	customer.flags.ignore_permissions = True
	customer.insert()
	return customer


def get_company(opp):
	return (
		opp.company
		or frappe.defaults.get_user_default("Company")
		or frappe.defaults.get_global_default("company")
	)


def make_billing_address(customer, opp):
	"""Primary billing Address with GSTIN; reuses a Lead address already moved to the Customer."""
	from frappe.contacts.doctype.address.address import get_address_display

	if not (opp.horizon_billing_address_line1 and opp.city):
		frappe.msgprint(
			_("No billing address created for {0}: Billing Address Line 1 and City are needed").format(
				customer.name
			),
			indicator="orange",
			alert=True,
		)
		return None

	existing = find_matching_address(customer.name, opp)
	if existing:
		address = frappe.get_doc("Address", existing)
	else:
		address = frappe.new_doc("Address")
		address.address_title = customer.customer_name
		address.append("links", {"link_doctype": "Customer", "link_name": customer.name})

	address.update(
		{
			"address_type": "Billing",
			"address_line1": opp.horizon_billing_address_line1,
			"city": opp.city,
			"state": opp.state,
			"pincode": opp.horizon_billing_pincode,
			"country": opp.country or INDIA,
			"gstin": opp.horizon_gstin,
			"gst_category": customer.gst_category,
			"is_primary_address": 1,
		}
	)
	address.flags.ignore_permissions = True
	address.save()

	customer.db_set(
		{
			"customer_primary_address": address.name,
			"primary_address": get_address_display(address.as_dict()),
		}
	)
	return address


def find_matching_address(customer, opp):
	"""Address already linked to the Customer (e.g. the Lead's, re-linked by ERPNext) at the same
	street + pincode, so the conversion never duplicates it."""
	linked = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": "Customer", "link_name": customer},
		pluck="parent",
	)
	if not linked:
		return None
	for name, line1, pincode in frappe.get_all(
		"Address",
		filters={"name": ["in", linked]},
		fields=["name", "address_line1", "pincode"],
		as_list=True,
	):
		if (
			cstr(line1).strip().lower() == cstr(opp.horizon_billing_address_line1).strip().lower()
			and cstr(pincode).strip() == cstr(opp.horizon_billing_pincode).strip()
		):
			return name
	return None


def set_primary_contact(customer, lead):
	"""ERPNext skips ``create_primary_contact`` for Lead customers and only re-links the Lead's
	Contact; make that Contact the Customer's primary contact so quotations pick it up."""
	contact = get_lead_contact(lead)
	if not contact or customer.customer_primary_contact:
		return
	contact_doc = frappe.get_doc("Contact", contact)
	if not contact_doc.has_link("Customer", customer.name):
		contact_doc.append("links", {"link_doctype": "Customer", "link_name": customer.name})
	contact_doc.is_primary_contact = 1
	contact_doc.flags.ignore_permissions = True
	contact_doc.save()
	customer.db_set(
		{
			"customer_primary_contact": contact,
			"email_id": contact_doc.email_id,
			"mobile_no": contact_doc.mobile_no,
		}
	)


def record_customer_on_opportunity(opp, customer):
	if opp.get("horizon_customer") == customer:
		return
	opp.horizon_customer = customer
	if not opp.is_new():
		# no modified bump: the user may have the Opportunity form open
		opp.db_set("horizon_customer", customer, update_modified=False)


def add_conversion_comments(customer, opp, address):
	lead_link = get_link_to_form("Lead", opp.party_name)
	opp_link = get_link_to_form("Opportunity", opp.name)
	customer_link = get_link_to_form("Customer", customer.name)
	details = _("Group {0}, GST {1} {2}, credit limit {3}, terms {4}, billing address {5}").format(
		customer.customer_group,
		customer.gst_category,
		customer.gstin or "",
		frappe.format_value(flt(opp.horizon_credit_limit), {"fieldtype": "Currency"}),
		customer.payment_terms or "-",
		address.name if address else "-",
	)
	customer.add_comment(
		"Info", _("Created from Lead {0} via Opportunity {1}. {2}").format(lead_link, opp_link, details)
	)
	frappe.get_doc("Lead", opp.party_name).add_comment(
		"Info", _("Converted to Customer {0} from Opportunity {1}").format(customer_link, opp_link)
	)
	opp.add_comment("Info", _("Customer {0} created from this Opportunity").format(customer_link))


# ---------------------------------------------------------------------------------------------
# Quotation: move a Lead quotation to the Customer before pricing
# ---------------------------------------------------------------------------------------------
def switch_quotation_to_customer(doc, method=None):
	"""Quotation ``before_validate`` hook.

	Frappe runs ``before_validate`` (controller, then doc_events) before ``validate``; the
	SellingController ``validate`` -> ``set_missing_values`` -> ``set_price_list_and_item_details``
	is where the pricing rules are evaluated, so the Premium (Customer Group) rule sees the Customer.
	"""
	if doc.docstatus != 0 or doc.quotation_to != "Lead" or not doc.party_name:
		return

	lead = doc.party_name
	customer = get_existing_customer(lead)
	if not customer:
		opp = get_source_opportunity(doc)
		if not opp or not opp.customer_group:
			warn_quotation_stays_on_lead(lead, opp)
			return
		if not can_create_customer():
			warn_quotation_stays_on_lead(lead, opp, _("you are not allowed to create Customers"))
			return
		customer = get_or_create_customer(opp)

	move_quotation_to_customer(doc, customer)
	frappe.msgprint(
		_("Quotation moved from Lead {0} to Customer {1}; prices and taxes follow the Customer").format(
			lead, frappe.bold(customer)
		),
		indicator="green",
		alert=True,
	)


def get_source_opportunity(doc):
	"""Opportunity of a Lead quotation: header link (set when the Opportunity had no items) or the
	``prevdoc_docname`` of its rows (set by ERPNext's Opportunity -> Quotation mapper)."""
	names = [doc.get("opportunity")] + [
		row.prevdoc_docname for row in doc.get("items", []) if row.get("prevdoc_doctype") == "Opportunity"
	]
	for name in filter(None, names):
		opp = frappe.get_doc("Opportunity", name)
		if opp.opportunity_from == "Lead" and opp.party_name == doc.party_name:
			return opp
	return None


def warn_quotation_stays_on_lead(lead, opp, reason=None):
	reason = reason or (
		_("Opportunity {0} has no Customer Group / GST details").format(
			get_link_to_form("Opportunity", opp.name)
		)
		if opp
		else _("it is not linked to an Opportunity with customer details")
	)
	frappe.msgprint(
		_(
			"This quotation stays on Lead {0} because {1}. Premium (Customer Group) pricing, GST on the "
			"customer's GSTIN, credit limit and payment terms will not apply until the Customer exists."
		).format(frappe.bold(lead), reason),
		title=_("Quotation Still on Lead"),
		indicator="orange",
	)


def move_quotation_to_customer(doc, customer):
	from erpnext.accounts.party import get_default_price_list
	from erpnext.controllers.accounts_controller import get_taxes_and_charges

	old_template = doc.get("taxes_and_charges")
	reset_rule_priced_rows(doc)
	doc.quotation_to = "Customer"
	doc.party_name = customer
	for fieldname in LEAD_DERIVED_QUOTATION_FIELDS:
		if doc.meta.has_field(fieldname):
			doc.set(fieldname, None)

	# Customer / Customer Group default price list wins (as when a Customer is picked on the form);
	# otherwise the quotation keeps its price list
	price_list = get_default_price_list(frappe.get_cached_doc("Customer", customer))
	if price_list and price_list != doc.selling_price_list:
		doc.selling_price_list = price_list
		doc.price_list_currency = None
		doc.plc_conversion_rate = None

	# re-fetch customer, address (place of supply via India Compliance), contact, tax template
	doc.set_missing_lead_customer_details(for_validate=True)

	new_template = doc.get("taxes_and_charges")
	if new_template and new_template != old_template:
		doc.set("taxes", [])
		for tax in get_taxes_and_charges("Sales Taxes and Charges Template", new_template):
			doc.append("taxes", tax)


# Quotation Item pricing fields cleared so the controller's ``set_missing_values`` (pricing engine,
# ``for_validate``) fills them again: a row without ``pricing_rules`` gets the rules found for the
# Customer instead of re-applying the rules stored on the row
ROW_PRICING_FIELDS = (
	"price_list_rate",
	"base_price_list_rate",
	"pricing_rules",
	"discount_percentage",
	"discount_amount",
	"margin_type",
	"margin_rate_or_amount",
	"rate",
)
# Rate difference (in transaction currency) still treated as "priced by the rules"
RATE_TOLERANCE = 0.01


def reset_rule_priced_rows(doc):
	"""Re-price, for the Customer, the rows the Lead's pricing rules priced.

	ERPNext re-applies the ``pricing_rules`` stored on a row during ``validate`` (``for_validate``)
	instead of searching again, so a row priced on the Lead (no Customer Group: e.g. only the Q4 rule)
	kept the Lead's price after the switch and missed the Customer's Premium rule; a changed default
	price list also left the old ``price_list_rate`` on the row. Rows whose rate is exactly the rule
	rate of their stored rules are cleared so the engine prices them again for the Customer. Rows with
	a manual rate / discount are left alone: ``validate_discounts`` governs those.
	"""
	rule_cache = {}
	for row in doc.get("items", []):
		if not row.item_code or not flt(row.price_list_rate):
			continue
		if abs(flt(row.rate) - get_rule_rate(row, rule_cache)) > RATE_TOLERANCE:
			continue
		for fieldname in ROW_PRICING_FIELDS:
			row.set(fieldname, None)


# ---------------------------------------------------------------------------------------------
# Opportunity -> Quotation mapper (override_whitelisted_methods)
# ---------------------------------------------------------------------------------------------
@frappe.whitelist()
def make_quotation(source_name, target_doc=None):
	"""ERPNext's ``erpnext.crm.doctype.opportunity.opportunity.make_quotation`` with the mapped rows
	priced from the price list and pricing rules (DEF-23).

	The standard mapper copies the Opportunity Item ``rate`` (mandatory on the Opportunity, typed as
	an estimate) onto the Quotation row and only overwrites it when a pricing rule applies. A row
	without a rule therefore kept e.g. 1,00,000 against a list price of 1,85,000 with Discount 0 %
	on the form, and ``validate_discounts`` rightly asked for a discount reason the user never meant
	to give. Used by the Opportunity's Create > Quotation and the Quotation's Get Items From >
	Opportunity (both resolve the method through ``override_whitelisted_methods``).
	"""
	from erpnext.crm.doctype.opportunity.opportunity import make_quotation as erpnext_make_quotation

	frappe.has_permission("Opportunity", "read", source_name, throw=True)
	existing_rows = get_row_names(target_doc)
	quotation = erpnext_make_quotation(source_name, target_doc)
	price_mapped_rows(quotation, existing_rows)
	return quotation


def get_row_names(target_doc):
	"""Names of the rows already on the target Quotation (Get Items From); those are not re-priced."""
	if not target_doc:
		return set()
	if isinstance(target_doc, str):
		target_doc = frappe.parse_json(target_doc)
	return {row.get("name") for row in target_doc.get("items") or [] if row.get("name")}


def price_mapped_rows(quotation, existing_rows=None):
	"""Rows mapped from an Opportunity get ``rate = price list rate - pricing-rule discount``.

	The mapper's ``set_missing_values`` already fetched ``price_list_rate`` / ``pricing_rules`` /
	``discount_percentage`` from the price list and pricing engine; clearing ``rate`` lets ERPNext's
	``calculate_taxes_and_totals`` derive it from them. Rows the price list does not price keep the
	Opportunity rate (nothing better exists; ``validate_discounts`` ignores them).
	"""
	existing_rows = existing_rows or set()
	repriced = []
	for row in quotation.get("items", []):
		if row.name in existing_rows or row.get("prevdoc_doctype") != "Opportunity":
			continue
		if not row.item_code or not flt(row.price_list_rate):
			continue
		opportunity_rate = flt(row.rate)
		row.rate = 0
		row.discount_amount = 0
		if not row.get("pricing_rules"):
			row.discount_percentage = 0
			row.margin_type = None
			row.margin_rate_or_amount = 0
		repriced.append((row, opportunity_rate))

	if not repriced:
		return

	quotation.calculate_taxes_and_totals()
	changed = [
		(row, opportunity_rate)
		for row, opportunity_rate in repriced
		if abs(flt(row.rate) - opportunity_rate) > RATE_TOLERANCE
	]
	if changed:
		frappe.msgprint(
			_(
				"Rates priced from Price List {0} and the pricing rules instead of the Opportunity estimate: {1}"
			).format(
				frappe.bold(quotation.selling_price_list),
				"; ".join(
					_("{0} {1} (Opportunity {2})").format(
						row.item_code,
						frappe.format_value(row.rate, {"fieldtype": "Currency"}),
						frappe.format_value(opportunity_rate, {"fieldtype": "Currency"}),
					)
					for row, opportunity_rate in changed
				),
			),
			indicator="blue",
			alert=True,
		)

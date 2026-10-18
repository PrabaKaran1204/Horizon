# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Customer-agreed Item Price recorded when a Quotation is submitted (ADR-18).

A submitted Quotation to a Customer whose row rate is *above* that row's pricing-rule rate is a
price the customer agreed (typically the Opportunity rate kept by Option B). The next quotation /
sales order for that customer should start from it, as kaynes does with ``CustomQuotation``
(``create_item_price``). Horizon writes a **customer-specific Item Price** on the quotation's
selling price list whose ``price_list_rate`` is grossed up for the rules on the row, so the
customer's *net* rate after their own pricing rules is the agreed rate again:

	price_list_rate = (agreed rate + rule discount amounts) / (1 - rule discount % / 100)

e.g. Premium (5 % Customer Group rule) agreed at 1,80,000 -> Item Price 1,89,473.68 -> 5 % off ->
1,80,000.00. ERPNext prefers a customer's own Item Price over the general one and, among those
valid on the transaction date, the newest ``valid_from`` (``get_item_details.get_item_price``).

- Idempotent: the customer's active price already at that value -> nothing; same ``valid_from``
  -> updated in place, the replaced rate / note kept in the note trailer (and the Version); a later
  date -> a new Item Price (history by ``valid_from``); a newer agreed price -> left alone.
- Rows at or below the rule rate, Lead quotations, rows priced by a "Rate" pricing rule and
  quotations in a currency other than the price list's create nothing.
- ``on_cancel`` reverses it: prices this quotation created are deleted, prices it updated get
  the rate / note they had before (from the note trailer).
- Failure never blocks the submit (kaynes pattern): savepoint rollback, Error Log, red alert.
"""

import json

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_link_to_form, getdate

from horizon_erp.horizon_selling.selling import (
	RATE_TOLERANCE,
	get_row_precision,
	get_rule_rate,
	get_rule_terms,
)

SAVEPOINT = "horizon_agreed_item_price"
# ERPNext overwrites Item Price ``reference`` with the customer on save, so the quotation that recorded
# a price is the fixed (untranslated) prefix of its ``note``: "Quotation SAL-QTN-2026-00021: ..."
NOTE_MARKER = "{0} {1}: "
# an in-place update keeps what it replaced at the end of the note, machine-readable for on_cancel
# (Version stores formatted values): "...\n--- replaced price_list_rate=200000.0\n<previous note>"
REPLACED_TRAILER = "\n--- replaced price_list_rate="

CREATED, UPDATED, UNCHANGED, SUPERSEDED, SKIPPED = "created", "updated", "unchanged", "superseded", "skipped"


# ---------------------------------------------------------------------------------------------
# Quotation on_submit
# ---------------------------------------------------------------------------------------------
def on_submit_quotation(doc, method=None):
	"""Quotation ``on_submit`` hook: record the customer's agreed prices."""
	if doc.quotation_to != "Customer" or not doc.party_name or not doc.selling_price_list:
		return
	rows, results = get_agreed_rows(doc)
	if not rows and not results:
		return

	frappe.db.savepoint(SAVEPOINT)
	try:
		for row, list_rate, terms in rows:
			results.append(record_agreed_price(doc, row, list_rate, terms))
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.log_error(
			title=f"Agreed Item Price failed for {doc.name}",
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)
		frappe.msgprint(
			_("The customer's agreed Item Prices could not be recorded; see Error Log."),
			indicator="red",
			alert=True,
		)
		return

	report_agreed_prices(doc, results)


def get_agreed_rows(doc):
	"""``([(row, price_list_rate, rule_terms)], [skipped results])`` for rows above the rule rate."""
	rows, skipped = [], []
	rule_cache = {}
	same_currency = not doc.get("price_list_currency") or doc.currency == doc.price_list_currency
	for row in doc.get("items", []):
		if not row.item_code or not flt(row.price_list_rate):
			continue
		if flt(row.rate) <= get_rule_rate(row, rule_cache) + RATE_TOLERANCE:
			continue
		if not same_currency:
			skipped.append(
				make_result(row, SKIPPED, reason=_("quotation currency differs from the price list currency"))
			)
			continue
		terms = get_rule_terms(row, rule_cache)
		list_rate = get_agreed_price_list_rate(row, terms)
		if list_rate is None:
			skipped.append(make_result(row, SKIPPED, reason=_("a Rate pricing rule fixes the price")))
			continue
		rows.append((row, list_rate, terms))
	return rows, skipped


def get_agreed_price_list_rate(row, terms):
	"""Price list rate that nets to ``row.rate`` after the row's rule discounts, or None when the
	rules (a "Rate" rule, 100 % discount) make the price list rate irrelevant."""
	if flt(terms.rule_price):
		return None
	factor = 1 - flt(terms.discount_pct) / 100
	if factor <= 0:
		return None
	precision = get_row_precision(row, "price_list_rate")
	rate_precision = get_row_precision(row, "rate")
	agreed = flt(row.rate, rate_precision)
	amount = flt(terms.discount_amount)
	gross = flt((agreed + amount) / factor, precision)
	# rounding to the currency precision can move the net by one unit of the last digit
	step = 10**-precision
	for candidate in (gross, flt(gross - step, precision), flt(gross + step, precision)):
		if flt(candidate * factor - amount, rate_precision) == agreed:
			return candidate
	return gross


def record_agreed_price(doc, row, list_rate, terms):
	from erpnext.stock.get_item_details import get_item_price

	transaction_date = getdate(doc.transaction_date)
	key = {
		"item_code": row.item_code,
		"price_list": doc.selling_price_list,
		"customer": doc.party_name,
		"uom": row.uom,
	}

	# the customer price ERPNext would pick today (customer-specific, newest valid_from first)
	active = get_item_price(
		{
			"price_list": doc.selling_price_list,
			"customer": doc.party_name,
			"uom": row.uom,
			"transaction_date": transaction_date,
		},
		row.item_code,
	)
	if active and abs(flt(active[0][1]) - list_rate) < 0.005:
		return make_result(row, UNCHANGED, active[0][0], list_rate)

	newer = frappe.db.get_value("Item Price", {**key, "valid_from": [">", transaction_date]}, "name")
	if newer:
		return make_result(row, SUPERSEDED, newer, list_rate)

	same_day = frappe.db.get_value(
		"Item Price", {**key, "valid_from": transaction_date, "valid_upto": ["is", "not set"]}, "name"
	)
	if same_day:
		price = frappe.get_doc("Item Price", same_day)
		status = UPDATED
	else:
		price = frappe.new_doc("Item Price")
		price.update(key)
		price.valid_from = transaction_date
		status = CREATED

	note = get_price_note(doc, row, terms)
	if status == UPDATED:
		note += f"{REPLACED_TRAILER}{flt(price.price_list_rate)!r}\n{cstr(price.note)}"
	price.price_list_rate = list_rate
	price.note = note
	price.flags.ignore_permissions = True  # Sales Users submit quotations but cannot edit Item Prices
	price.save()
	return make_result(row, status, price.name, list_rate)


def get_price_note(doc, row, terms):
	rules = ", ".join(json.loads(row.pricing_rules)) if row.get("pricing_rules") else _("none")
	return get_note_marker(doc) + _(
		"agreed rate {0} for {1} (qty {2}). Price list rate grossed up for the pricing rules on the row "
		"({3}: {4}% / {5}) so the customer's net rate after them is the agreed rate."
	).format(
		flt(row.rate),
		doc.party_name,
		flt(row.qty),
		rules,
		flt(terms.discount_pct),
		flt(terms.discount_amount),
	)


def get_note_marker(doc):
	return NOTE_MARKER.format(doc.doctype, doc.name)


def make_result(row, status, item_price=None, list_rate=None, reason=None):
	return frappe._dict(
		item_code=row.item_code,
		uom=row.uom,
		rate=flt(row.rate),
		status=status,
		item_price=item_price,
		list_rate=list_rate,
		reason=reason,
	)


def report_agreed_prices(doc, results):
	labels = {
		CREATED: _("created"),
		UPDATED: _("updated"),
		UNCHANGED: _("already recorded"),
		SUPERSEDED: _("not changed: a newer agreed price exists"),
		SKIPPED: _("not recorded"),
	}
	lines = []
	for result in results:
		line = _("{0} ({1}) agreed {2}: Item Price {3} at {4} {5}").format(
			frappe.bold(result.item_code),
			result.uom,
			format_currency(result.rate),
			get_link_to_form("Item Price", result.item_price) if result.item_price else "-",
			format_currency(result.list_rate) if result.list_rate else "-",
			labels[result.status],
		)
		if result.reason:
			line += f" ({result.reason})"
		lines.append(line)

	message = _("Customer agreed prices for {0} on Price List {1}:<br>{2}").format(
		frappe.bold(doc.party_name), doc.selling_price_list, "<br>".join(lines)
	)
	if any(result.status in (CREATED, UPDATED) for result in results):
		doc.add_comment("Info", message)
	frappe.msgprint(message, title=_("Customer Agreed Prices"), indicator="green")


# ---------------------------------------------------------------------------------------------
# Quotation on_cancel
# ---------------------------------------------------------------------------------------------
def on_cancel_quotation(doc, method=None):
	"""Quotation ``on_cancel`` hook: undo the agreed prices this quotation recorded."""
	if doc.quotation_to != "Customer" or not doc.party_name:
		return
	marker = get_note_marker(doc)
	names = frappe.get_all(
		"Item Price",
		filters={"customer": doc.party_name, "note": ["like", f"{marker}%"]},
		pluck="name",
	)
	if not names:
		return

	lines = []
	for name in names:
		price = frappe.get_doc("Item Price", name)
		previous = get_replaced_state(price.note)
		if previous:
			price.update(previous)
			price.flags.ignore_permissions = True
			price.save()
			price.add_comment(
				"Info",
				_("Restored: Quotation {0} was cancelled").format(get_link_to_form(doc.doctype, doc.name)),
			)
			lines.append(
				_("Item Price {0} restored to {1}").format(name, format_currency(price.price_list_rate))
			)
		else:
			frappe.delete_doc("Item Price", name, ignore_permissions=True)
			lines.append(_("Item Price {0} deleted").format(name))

	message = _("Customer agreed prices of this quotation reversed:<br>{0}").format("<br>".join(lines))
	doc.add_comment("Info", message)
	frappe.msgprint(message, title=_("Customer Agreed Prices"), indicator="orange")


def get_replaced_state(note):
	"""``{price_list_rate, note}`` an in-place update replaced (its note trailer), or None when the
	quotation created the Item Price."""
	head, separator, tail = cstr(note).partition(REPLACED_TRAILER)
	if not separator:
		return None
	rate, _newline, previous_note = tail.partition("\n")
	return {"price_list_rate": flt(rate), "note": previous_note or None}


def format_currency(value):
	return frappe.format_value(value, {"fieldtype": "Currency"})

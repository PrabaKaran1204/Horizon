# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Shared helpers for Horizon ERP.

``horizon_erp.utils`` is a package (not ``utils.py``) because ``hooks.py`` registers
``jinja = {"methods": ["horizon_erp.utils.jinja_methods"]}`` and Frappe v15
(``frappe.utils.jinja.get_jinja_hooks``) resolves that path with ``frappe.get_module`` first:
every function in the module ``horizon_erp.utils.jinja_methods`` becomes a Jinja global. A
function returning a dict would be registered under the single name ``jinja_methods`` instead.
The helpers are implemented here and re-exported by ``utils/jinja_methods.py``.
"""

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, cstr, flt, getdate


def get_jinja_methods():
	"""``{"name": callable}`` of every helper exposed to Jinja (print formats, email templates).

	The hook itself points at the module ``horizon_erp.utils.jinja_methods``; this dict is kept
	for introspection / tests. Every helper swallows its own errors (returns an empty / neutral
	value) so a data problem never turns into a broken print.
	"""
	return {
		"horizon_customer_outstanding": horizon_customer_outstanding,
		"horizon_similar_items_in_stock": horizon_similar_items_in_stock,
		"horizon_due_date": horizon_due_date,
		"horizon_company_gst": horizon_company_gst,
		"horizon_dn_row_serials": horizon_dn_row_serials,
		"horizon_pan_from_gstin": horizon_pan_from_gstin,
	}


def get_setting(key, default=None):
	"""Read a Horizon-wide configuration value.

	Intended behaviour: look up ``key`` on a future "Horizon Settings" Single DocType and fall
	back to ``default``. Until that DocType exists this always returns ``default``.
	"""
	# TODO(settings): back with a "Horizon Settings" Single DocType
	return default


# ---------------------------------------------------------------------------
# Jinja helpers (print formats)
# ---------------------------------------------------------------------------
def horizon_customer_outstanding(customer, company, date=None):
	"""Receivable balance of ``customer`` in ``company`` as of ``date`` (today when omitted).
	Positive = customer owes us. Uses ``erpnext.accounts.utils.get_balance_on``."""
	if not customer or not company:
		return 0.0
	try:
		from erpnext.accounts.utils import get_balance_on

		return flt(
			get_balance_on(
				date=date,
				party_type="Customer",
				party=customer,
				company=company,
				ignore_account_permission=True,
			)
		)
	except Exception:
		frappe.log_error(title="horizon_customer_outstanding failed")
		return 0.0


def horizon_similar_items_in_stock(item_code, limit=3):
	"""Up to ``limit`` other sellable items of the same Item Group with total actual stock > 0.
	Each entry: ``{"item_code", "item_name", "actual_qty", "stock_uom"}``."""
	if not item_code:
		return []
	try:
		item_group = frappe.db.get_value("Item", item_code, "item_group")
		if not item_group:
			return []
		item = frappe.qb.DocType("Item")
		bin_ = frappe.qb.DocType("Bin")
		total = Sum(bin_.actual_qty)
		rows = (
			frappe.qb.from_(item)
			.join(bin_)
			.on(bin_.item_code == item.name)
			.select(item.name.as_("item_code"), item.item_name, item.stock_uom, total.as_("actual_qty"))
			.where(item.item_group == item_group)
			.where(item.name != item_code)
			.where(item.disabled == 0)
			.where(item.is_sales_item == 1)
			.groupby(item.name, item.item_name, item.stock_uom)
			.having(total > 0)
			.orderby(total, order=frappe.qb.desc)
			.limit(int(limit or 3))
		).run(as_dict=True)
		for r in rows:
			r.actual_qty = flt(r.actual_qty)
		return rows
	except Exception:
		frappe.log_error(title="horizon_similar_items_in_stock failed")
		return []


def horizon_due_date(doc):
	"""Payment due date of a selling document: latest ``payment_schedule.due_date``, else
	``doc.due_date``, else posting date + the customer's payment terms (ERPNext
	``get_due_date``), else the posting date itself."""
	try:
		schedule = [getdate(r.due_date) for r in (doc.get("payment_schedule") or []) if r.get("due_date")]
		if schedule:
			return max(schedule)
		if doc.get("due_date"):
			return getdate(doc.due_date)
		posting_date = doc.get("posting_date") or doc.get("transaction_date")
		if doc.get("customer") and posting_date:
			from erpnext.accounts.party import get_due_date

			due = get_due_date(posting_date, "Customer", doc.customer, doc.get("company"))
			return getdate(due) if due else getdate(posting_date)
		return getdate(posting_date) if posting_date else None
	except Exception:
		frappe.log_error(title="horizon_due_date failed")
		return getdate(doc.get("posting_date")) if doc.get("posting_date") else None


def horizon_company_gst(company, address_name=None):
	"""``{"gstin", "pan", "address_lines": [...], "address_display"}`` for a company.

	GSTIN comes from the Address (India Compliance ``Address.gstin``) when given, else from
	``Company.gstin``. PAN is derived from the GSTIN (characters 3-12)."""
	out = {"gstin": "", "pan": "", "address_lines": [], "address_display": ""}
	try:
		gstin = ""
		if address_name and frappe.db.exists("Address", address_name):
			addr = frappe.db.get_value(
				"Address",
				address_name,
				["address_line1", "address_line2", "city", "state", "pincode", "country"]
				+ (["gstin"] if frappe.db.has_column("Address", "gstin") else []),
				as_dict=True,
			)
			lines = [
				addr.address_line1,
				addr.address_line2,
				" ".join(filter(None, [addr.city, addr.pincode])),
				addr.state,
				addr.country,
			]
			out["address_lines"] = [cstr(x).strip() for x in lines if cstr(x).strip()]
			gstin = addr.get("gstin") or ""
		if not gstin and company and frappe.db.has_column("Company", "gstin"):
			gstin = frappe.db.get_value("Company", company, "gstin") or ""
		out["gstin"] = gstin
		out["pan"] = horizon_pan_from_gstin(gstin)
		out["address_display"] = ", ".join(out["address_lines"])
	except Exception:
		frappe.log_error(title="horizon_company_gst failed")
	return out


def horizon_pan_from_gstin(gstin):
	"""PAN = characters 3-12 of a 15-character GSTIN."""
	gstin = cstr(gstin).strip()
	return gstin[2:12] if len(gstin) == 15 else ""


def horizon_dn_row_serials(row):
	"""Serial numbers and batches of a Delivery Note Item row.

	Handles the v15 ``serial_and_batch_bundle`` (Serial and Batch Entry rows) as well as the
	legacy ``serial_no`` / ``batch_no`` fields. Returns
	``{"serial_nos": [...], "batches": [{"batch_no", "qty"}, ...]}``."""
	out = {"serial_nos": [], "batches": []}
	try:
		bundle = row.get("serial_and_batch_bundle")
		if bundle:
			entries = frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": bundle, "parenttype": "Serial and Batch Bundle"},
				fields=["serial_no", "batch_no", "qty"],
				order_by="idx",
			)
			batches = {}
			for e in entries:
				if e.serial_no:
					out["serial_nos"].append(e.serial_no)
				if e.batch_no:
					batches[e.batch_no] = batches.get(e.batch_no, 0) + abs(flt(e.qty))
			out["batches"] = [{"batch_no": b, "qty": q} for b, q in batches.items()]
			return out
		if row.get("serial_no"):
			out["serial_nos"] = [
				s.strip() for s in cstr(row.serial_no).replace(",", "\n").split("\n") if s.strip()
			]
		if row.get("batch_no"):
			out["batches"] = [{"batch_no": row.batch_no, "qty": flt(row.get("qty"))}]
	except Exception:
		frappe.log_error(title="horizon_dn_row_serials failed")
	return out

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Purchase Receipt document event handlers for the Receipt -> Quality Check -> GRN flow (ADR-2).

Default flow (ERPNext standard, ``config.use_qc_hold()`` False): the Purchase Receipt *draft* is the
receipt (its ``creation`` is the receipt time the inspection SLA is measured from), the Quality
Inspection is raised against it, and *submitting* it is the GRN - the only step that posts stock.
Stock Settings "Action if Quality Inspection is not Submitted = Stop" guarantees nothing is posted
before inspection. These handlers only default the Rejected warehouse and raise the paperwork
(draft Purchase Return, draft Debit Note) for rejected quantities.

Optional flow (``horizon_use_qc_hold`` on Stock Settings or in site_config): rows of items that
need inspection are received into the QC Hold warehouse and the accepted qty is moved to the item's
default warehouse by an automatic Material Transfer on submit.

Wired from ``hooks.py`` ``doc_events``. Every handler takes ``(doc, method=None)``.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_link_to_form, nowdate, nowtime

from horizon_erp.horizon_core import config


# ---------------------------------------------------------------------------------------------
# Purchase Receipt
# ---------------------------------------------------------------------------------------------
def before_validate_purchase_receipt(doc, method=None):
	"""Purchase Receipt ``before_validate`` hook (both modes).

	Rows of items with ``inspection_required_before_purchase`` (and any row carrying a
	``rejected_qty``) get the company's Rejected warehouse as ``rejected_warehouse`` when blank, so
	a partly rejected lot can be posted without a manual step. Runs before ERPNext's own
	``validate_rejected_warehouse`` (part of the controller ``validate``), which would otherwise
	reject a row whose rejected qty was entered on the first save. Rows keep the warehouse chosen on
	the receipt (the item default, HQ Raw Materials for inspected items). Returns are untouched.
	"""
	if doc.get("is_return") or not doc.get("company"):
		return
	default_rejected_warehouse(doc, get_inspection_items([row.item_code for row in doc.items]))


def validate_purchase_receipt(doc, method=None):
	"""Purchase Receipt ``validate`` hook: optional QC Hold routing (ADR-2).

	Only with QC Hold routing switched on (``config.use_qc_hold()``): inspection rows are re-routed
	into the QC Hold warehouse; ``on_submit_purchase_receipt`` then releases the accepted stock (it keys on the row warehouse
	being QC Hold, so the two handlers stay in step). Returns are untouched.
	"""
	if doc.get("is_return") or not doc.get("company") or not config.use_qc_hold():
		return
	rerouted = route_inspection_rows_to_qc_hold(doc)
	if rerouted:
		frappe.msgprint(
			_("Rows {0} routed to {1} pending inspection").format(
				", ".join(str(idx) for idx in rerouted), frappe.bold(rerouted_warehouse(doc))
			),
			alert=True,
			indicator="blue",
		)


def rerouted_warehouse(doc):
	return config.get_warehouse(config.QC_HOLD_WAREHOUSE_NAME, doc.company)


def get_inspection_items(item_codes):
	"""Subset of ``item_codes`` flagged ``inspection_required_before_purchase`` (one query)."""
	codes = [c for c in set(item_codes) if c]
	if not codes:
		return set()
	return set(
		frappe.get_all(
			"Item",
			filters={"name": ["in", codes], "inspection_required_before_purchase": 1},
			pluck="name",
		)
	)


def default_rejected_warehouse(doc, inspection_items):
	"""Fill a blank ``rejected_warehouse`` with the company's Rejected warehouse on inspection rows
	and on rows with a rejected qty. Returns the ``idx`` list of rows changed."""
	rejected = config.get_warehouse(config.REJECTED_WAREHOUSE_NAME, doc.company)
	if not rejected:
		return []
	changed = []
	for row in doc.items:
		if row.get("rejected_warehouse"):
			continue
		if row.item_code in inspection_items or flt(row.get("rejected_qty")) > 0:
			row.rejected_warehouse = rejected
			changed.append(row.idx)
	return changed


def route_inspection_rows_to_qc_hold(doc, inspection_items=None):
	"""Set ``warehouse`` = QC Hold on inspection rows (optional QC Hold mode only).

	Returns the ``idx`` list of rows whose warehouse was changed.
	"""
	qc_hold = rerouted_warehouse(doc)
	if not qc_hold:
		return []
	if inspection_items is None:
		inspection_items = get_inspection_items([row.item_code for row in doc.items])
	rerouted = []
	for row in doc.items:
		if row.item_code not in inspection_items:
			continue
		if row.warehouse != qc_hold:
			row.warehouse = qc_hold
			rerouted.append(row.idx)
	return rerouted


def on_submit_purchase_receipt(doc, method=None):
	"""Purchase Receipt ``on_submit`` hook (= GRN): raise the paperwork for rejected quantities and,
	in the optional QC Hold mode only, move QC-accepted stock out of QC Hold.

	- QC Hold mode only - rows received into the QC Hold warehouse whose Quality Inspection is
	  submitted and Accepted: a Material Transfer Stock Entry of the accepted qty (``row.qty``; ERPNext keeps rejected qty
	  in ``rejected_qty`` / ``rejected_warehouse``, so ``qty`` is already net of rejections) from
	  QC Hold to the item's default warehouse for the company, falling back to Raw Materials.
	- Rows with ``rejected_qty`` > 0: ONE draft Purchase Return (against the rejected warehouse)
	  and, if a submitted Purchase Invoice already references this receipt, a draft Debit Note.

	Nothing here may block the receipt: every step is wrapped, logged and reported via msgprint.
	"""
	if doc.get("is_return"):
		return

	created_links = []
	try:
		if config.use_qc_hold():
			created_links += release_accepted_stock(doc)
		else:
			warn_rows_left_in_qc_hold(doc)
	except Exception:
		frappe.log_error(title=f"QC release failed for {doc.name}", message=frappe.get_traceback())
		frappe.msgprint(
			_(
				"Stock could not be released from QC Hold automatically; see Error Log. "
				"Create the Material Transfer manually."
			),
			indicator="orange",
			alert=True,
		)

	try:
		created_links += raise_rejection_documents(doc)
	except Exception:
		frappe.log_error(title=f"Rejection paperwork failed for {doc.name}", message=frappe.get_traceback())
		frappe.msgprint(
			_(
				"The Purchase Return / Debit Note for rejected quantities could not be created "
				"automatically; see Error Log."
			),
			indicator="orange",
			alert=True,
		)

	if created_links:
		doc.add_comment("Comment", _("Horizon QC follow-up created: {0}").format(", ".join(created_links)))


def _qi_is_accepted(qi_name):
	if not qi_name:
		return False
	qi = frappe.db.get_value("Quality Inspection", qi_name, ["docstatus", "status"], as_dict=True)
	return bool(qi and qi.docstatus == 1 and qi.status == "Accepted")


def warn_rows_left_in_qc_hold(doc):
	"""Standard mode: nothing is released automatically. A row still received into QC Hold (a draft
	made while QC Hold routing was on, or chosen by hand) is flagged so it is moved manually."""
	qc_hold = config.get_warehouse(config.QC_HOLD_WAREHOUSE_NAME, doc.company)
	rows = [str(row.idx) for row in doc.items if qc_hold and row.warehouse == qc_hold]
	if rows:
		frappe.msgprint(
			_(
				"Rows {0} were received into {1}. QC Hold routing is switched off, so no automatic "
				"release is made; transfer the stock with a Material Transfer when it is cleared."
			).format(", ".join(rows), frappe.bold(qc_hold)),
			indicator="orange",
			alert=True,
		)


def get_item_destination_warehouse(item_code, company):
	default = frappe.db.get_value(
		"Item Default", {"parent": item_code, "company": company}, "default_warehouse"
	)
	if default:
		return default
	return config.get_warehouse(config.RAW_MATERIAL_WAREHOUSE_NAME, company)


def release_accepted_stock(doc):
	qc_hold = config.get_warehouse(config.QC_HOLD_WAREHOUSE_NAME, doc.company)
	if not qc_hold:
		return []

	rows = [
		row
		for row in doc.items
		if row.warehouse == qc_hold and flt(row.qty) > 0 and _qi_is_accepted(row.get("quality_inspection"))
	]
	if not rows:
		return []

	se = frappe.new_doc("Stock Entry")
	se.company = doc.company
	se.stock_entry_type = "Material Transfer"
	se.purpose = "Material Transfer"
	se.set_posting_time = 1
	se.posting_date = nowdate()
	se.posting_time = nowtime()
	se.remarks = _("QC release of accepted stock from {0} (Quality Inspection: {1})").format(
		doc.name, ", ".join(sorted({row.quality_inspection for row in rows}))
	)
	for row in rows:
		target = get_item_destination_warehouse(row.item_code, doc.company)
		if not target or target == qc_hold:
			continue
		se.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": flt(row.qty),
				"uom": row.uom,
				"conversion_factor": row.conversion_factor or 1,
				"s_warehouse": qc_hold,
				"t_warehouse": target,
				"batch_no": row.get("batch_no"),
			},
		)
	if not se.items:
		return []

	config.apply_default_dimensions(se)
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	frappe.msgprint(
		_("Accepted stock released from QC Hold via {0}").format(get_link_to_form("Stock Entry", se.name)),
		alert=True,
	)
	return [get_link_to_form("Stock Entry", se.name)]


def raise_rejection_documents(doc):
	rejected_rows = [row for row in doc.items if flt(row.rejected_qty) > 0]
	if not rejected_rows:
		return []

	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
		make_purchase_return_against_rejected_warehouse,
	)

	links = []
	pr_return = make_purchase_return_against_rejected_warehouse(doc.name)
	pr_return.items = [row for row in pr_return.items if flt(row.qty) < 0]
	if pr_return.items:
		pr_return.remarks = _("Auto-created for rejected quantities on {0}").format(doc.name)
		pr_return.flags.ignore_permissions = True
		pr_return.insert()
		links.append(get_link_to_form("Purchase Receipt", pr_return.name))
		frappe.msgprint(
			_("Draft Purchase Return {0} created for rejected quantities").format(
				get_link_to_form("Purchase Receipt", pr_return.name)
			),
			alert=True,
		)

	invoice = frappe.db.get_value(
		"Purchase Invoice Item",
		{"purchase_receipt": doc.name, "docstatus": 1},
		"parent",
	)
	if invoice:
		from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note

		rejected_by_item = {}
		for row in rejected_rows:
			rejected_by_item[row.item_code] = rejected_by_item.get(row.item_code, 0) + flt(row.rejected_qty)

		debit_note = make_debit_note(invoice)
		kept = []
		for row in debit_note.items:
			if row.item_code in rejected_by_item and rejected_by_item[row.item_code] > 0:
				qty = min(abs(flt(row.qty)), rejected_by_item[row.item_code])
				rejected_by_item[row.item_code] -= qty
				row.qty = -qty
				row.received_qty = -qty
				kept.append(row)
		debit_note.items = kept
		if debit_note.items:
			debit_note.update_stock = 0
			debit_note.remarks = _("Debit note for quantities rejected on {0}").format(doc.name)
			debit_note.flags.ignore_permissions = True
			debit_note.insert()
			links.append(get_link_to_form("Purchase Invoice", debit_note.name))
	else:
		doc.add_comment(
			"Comment",
			_(
				"No Purchase Invoice exists for this receipt yet; raise the Debit Note from the Purchase "
				"Return once the supplier invoice is booked."
			),
		)

	return links

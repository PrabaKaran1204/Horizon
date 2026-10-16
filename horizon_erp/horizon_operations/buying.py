# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Buying-side document event handlers (Purchase Order, Purchase Receipt).

Wired from ``hooks.py`` ``doc_events``. Every handler takes ``(doc, method=None)``.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_link_to_form, now_datetime, nowdate, nowtime

from horizon_erp.horizon_operations import config

PENDING_STATE_PREFIX = "Pending"
RESET_STATES = ("Draft", "Approved", "Rejected", "")


# ---------------------------------------------------------------------------------------------
# Purchase Order
# ---------------------------------------------------------------------------------------------
def validate_purchase_order(doc, method=None):
	"""Purchase Order ``validate`` hook.

	1. Derive ``approval_level_required`` from ``grand_total`` (and force Level 3 on an override).
	2. Block blacklisted suppliers unless an authorised user ticks ``blacklist_override`` with a
	   justification; log the override in Supplier Exception Log and notify Finance Directors.
	3. Stamp / clear ``pending_since`` when the workflow state moves into / out of a pending state.

	Limitation: ``on_submit`` is not hooked for Purchase Order, so the exception log is marked
	Approved from this ``validate`` call when ``doc.docstatus == 1`` (validate also runs on submit).
	"""
	check_supplier_hold(doc)
	set_approval_level(doc)
	enforce_blacklist(doc)
	set_pending_since(doc)


def check_supplier_hold(doc):
	"""ERPNext already blocks POs for suppliers with ``prevent_pos``; this only gives the buyer a
	clear, actionable message instead of a generic one."""
	if not doc.supplier:
		return
	supplier = frappe.db.get_value(
		"Supplier", doc.supplier, ["on_hold", "hold_type", "release_date", "prevent_pos"], as_dict=True
	)
	if not supplier:
		return
	if supplier.prevent_pos or (supplier.on_hold and supplier.hold_type in ("All", "")):
		if supplier.release_date and cstr(supplier.release_date) <= nowdate():
			return
		frappe.throw(
			_(
				"Supplier {0} is on hold ({1}). Purchase Orders cannot be raised until the hold is "
				"released on the Supplier record{2}."
			).format(
				frappe.bold(doc.supplier),
				supplier.hold_type or _("Purchase Orders blocked"),
				_(" (release date {0})").format(frappe.format(supplier.release_date, {"fieldtype": "Date"}))
				if supplier.release_date
				else "",
			),
			title=_("Supplier On Hold"),
		)


def get_approval_level(grand_total, blacklist_override=False):
	if blacklist_override:
		return "Level 3"
	grand_total = flt(grand_total)
	if grand_total < config.get_threshold("po_level_1_limit", config.PO_LEVEL_1_LIMIT):
		return "Level 1"
	if grand_total <= config.get_threshold("po_level_2_limit", config.PO_LEVEL_2_LIMIT):
		return "Level 2"
	return "Level 3"


def set_approval_level(doc):
	doc.approval_level_required = get_approval_level(doc.grand_total, doc.get("blacklist_override"))


def enforce_blacklist(doc):
	if not doc.supplier:
		return

	supplier = frappe.db.get_value(
		"Supplier", doc.supplier, ["is_blacklisted", "blacklist_reason", "blacklisted_on"], as_dict=True
	)
	if not supplier or not supplier.is_blacklisted:
		if doc.get("blacklist_override"):
			# Supplier is clean now; an override is meaningless and must not inflate the level
			doc.blacklist_override = 0
			doc.override_reason = None
			set_approval_level(doc)
		return

	if not doc.get("blacklist_override"):
		frappe.throw(
			_(
				"Supplier {0} is blacklisted{1}.<br>Reason: {2}<br><br>"
				"To proceed anyway, a Procurement Manager or Finance Director must tick "
				"<b>Blacklist Override</b> on the Horizon tab and record a justification of at least "
				"{3} characters. The order will then require Level 3 (Finance Director) approval."
			).format(
				frappe.bold(doc.supplier),
				_(" since {0}").format(frappe.format(supplier.blacklisted_on, {"fieldtype": "Date"}))
				if supplier.blacklisted_on
				else "",
				frappe.bold(supplier.blacklist_reason or _("not recorded")),
				config.OVERRIDE_REASON_MIN_LENGTH,
			),
			title=_("Blacklisted Supplier"),
			exc=frappe.ValidationError,
		)

	validate_override_permission(doc)

	reason = cstr(doc.get("override_reason")).strip()
	if len(reason) < config.OVERRIDE_REASON_MIN_LENGTH:
		frappe.throw(
			_("Override Reason must be at least {0} characters so the exception can be audited").format(
				config.OVERRIDE_REASON_MIN_LENGTH
			),
			title=_("Justification Required"),
		)

	doc.approval_level_required = "Level 3"
	upsert_exception_log(doc, supplier)


def validate_override_permission(doc):
	"""Only Procurement Manager / Finance Director may tick Blacklist Override. Checked whenever
	the flag is newly set or the reason changes, so a plain Purchase User cannot sneak it in."""
	before = doc.get_doc_before_save()
	newly_set = not before or not before.get("blacklist_override")
	reason_changed = before and before.get("override_reason") != doc.get("override_reason")
	if not (newly_set or reason_changed):
		return
	if not config.user_has_any_role(config.BLACKLIST_OVERRIDE_ROLES):
		frappe.throw(
			_("Only a {0} or {1} may override a supplier blacklist").format(
				frappe.bold(config.ROLE_PROCUREMENT_MANAGER), frappe.bold(config.ROLE_FINANCE_DIRECTOR)
			),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


def upsert_exception_log(doc, supplier):
	"""One Supplier Exception Log per Purchase Order. Created Pending on the first override;
	marked Approved (approver = session user) when the PO is submitted."""
	log_name = frappe.db.exists("Supplier Exception Log", {"purchase_order": doc.name})
	if log_name:
		log = frappe.get_doc("Supplier Exception Log", log_name)
		created = False
	else:
		log = frappe.new_doc("Supplier Exception Log")
		log.purchase_order = doc.name
		log.requested_by = frappe.session.user
		log.requested_on = now_datetime()
		log.status = "Pending"
		created = True

	log.supplier = doc.supplier
	log.po_amount = flt(doc.grand_total)
	log.blacklist_reason = supplier.blacklist_reason
	log.override_reason = doc.override_reason

	if doc.docstatus == 1 and log.status == "Pending":
		log.status = "Approved"
		log.approver = frappe.session.user

	log.flags.ignore_permissions = True
	log.flags.ignore_links = True  # the PO row does not exist yet while its validate runs on insert
	log.save()

	if created:
		notify_finance_directors_of_override(doc, log)


def notify_finance_directors_of_override(doc, log):
	subject = _("Blacklist override requested on {0} for supplier {1}").format(doc.name, doc.supplier)
	message = _(
		"{0} has raised Purchase Order {1} (amount {2}) against blacklisted supplier {3}.<br>"
		"Justification: {4}<br>Exception log: {5}"
	).format(
		frappe.session.user,
		get_link_to_form("Purchase Order", doc.name),
		frappe.format(doc.grand_total, {"fieldtype": "Currency"}),
		frappe.bold(doc.supplier),
		frappe.bold(doc.override_reason),
		get_link_to_form("Supplier Exception Log", log.name),
	)
	recipients = config.get_users_with_role(config.ROLE_FINANCE_DIRECTOR)
	for user in recipients:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"from_user": frappe.session.user,
				"type": "Alert",
				"subject": subject,
				"email_content": message,
				"document_type": "Purchase Order",
				"document_name": doc.name,
			}
		).insert(ignore_permissions=True)

	if recipients:
		try:
			frappe.sendmail(
				recipients=recipients,
				subject=subject,
				message=message,
				reference_doctype="Purchase Order",
				reference_name=doc.name,
			)
		except Exception:
			frappe.log_error(title="Blacklist override email failed", message=frappe.get_traceback())


def set_pending_since(doc):
	state = cstr(doc.get("workflow_state"))
	before = doc.get_doc_before_save()
	previous_state = cstr(before.get("workflow_state")) if before else ""

	if state.startswith(PENDING_STATE_PREFIX):
		if state != previous_state or not doc.get("pending_since"):
			doc.pending_since = now_datetime()
	elif state in RESET_STATES:
		doc.pending_since = None


# ---------------------------------------------------------------------------------------------
# Purchase Receipt
# ---------------------------------------------------------------------------------------------
def validate_purchase_receipt(doc, method=None):
	"""Purchase Receipt ``validate`` hook: enforce the QC Hold routing decided in ADR-2.

	Every row whose Item has ``inspection_required_before_purchase`` must be received into the QC
	Hold warehouse of the company; the row's ``rejected_warehouse`` defaults to the Rejected
	warehouse. Rows for items without inspection keep their own warehouse. Returns are untouched.
	``on_submit_purchase_receipt`` later releases accepted stock from QC Hold (it keys on the row
	warehouse being QC Hold, so the two handlers stay in step).
	"""
	if doc.get("is_return") or not doc.get("company"):
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


def route_inspection_rows_to_qc_hold(doc):
	"""Set ``warehouse`` = QC Hold (and a default ``rejected_warehouse``) on inspection rows.

	Returns the ``idx`` list of rows whose warehouse was changed.
	"""
	qc_hold = rerouted_warehouse(doc)
	if not qc_hold:
		return []
	rejected = config.get_warehouse(config.REJECTED_WAREHOUSE_NAME, doc.company)
	inspection_items = get_inspection_items([row.item_code for row in doc.items])
	rerouted = []
	for row in doc.items:
		if row.item_code not in inspection_items:
			continue
		if row.warehouse != qc_hold:
			row.warehouse = qc_hold
			rerouted.append(row.idx)
		if rejected and not row.get("rejected_warehouse"):
			row.rejected_warehouse = rejected
	return rerouted


def on_submit_purchase_receipt(doc, method=None):
	"""Purchase Receipt ``on_submit`` hook: move QC-accepted stock out of QC Hold and raise the
	paperwork for rejected quantities.

	- Rows received into the QC Hold warehouse whose Quality Inspection is submitted and Accepted:
	  a Material Transfer Stock Entry of the accepted qty (``row.qty``; ERPNext keeps rejected qty
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
		created_links += release_accepted_stock(doc)
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

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Buying-side document event handlers (Purchase Order).

Purchase Receipt QC-hold routing lives in ``horizon_erp.horizon_stock.purchase_receipt``.

Wired from ``hooks.py`` ``doc_events``. Every handler takes ``(doc, method=None)``.
"""

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_link_to_form, now_datetime, nowdate

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.jobs import safe_sendmail

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
		safe_sendmail(
			"Blacklist override email failed",
			recipients=recipients,
			subject=subject,
			message=message,
			reference_doctype="Purchase Order",
			reference_name=doc.name,
		)


def set_pending_since(doc):
	state = cstr(doc.get("workflow_state"))
	before = doc.get_doc_before_save()
	previous_state = cstr(before.get("workflow_state")) if before else ""

	if state.startswith(PENDING_STATE_PREFIX):
		if state != previous_state or not doc.get("pending_since"):
			doc.pending_since = now_datetime()
	elif state in RESET_STATES:
		doc.pending_since = None

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Stock Entry hooks that gate the Work Order finish: Production Audit outcomes and the
mandatory per-operation inspection (ADR-19).

Also the server side of the Work Order form (``public/js/work_order.js``): ``make_production_audit``
builds the pre-filled audit behind *Create > Production Audit* and ``get_audit_status`` feeds the
headline that tells whether the latest audit blocks the Finish."""

import frappe
from frappe import _
from frappe.utils import get_link_to_form, nowdate

from horizon_erp.horizon_core import config
from horizon_erp.horizon_quality_management.operation_inspection import (
	get_missing_before_finish,
	validate_manufacture_inspections,
)

# a Production Audit can only be recorded against an open Work Order (ProductionAudit.validate)
CLOSED_WORK_ORDER_STATUSES = ("Completed", "Cancelled", "Stopped")


def get_blocking_audits(work_order):
	"""Submitted Production Audits below the fail score that are not yet Action Closed."""
	return frappe.get_all(
		"Production Audit",
		filters={
			"work_order": work_order,
			"docstatus": 1,
			"audit_score": ["<", config.AUDIT_FAIL_SCORE],
			"status": ["!=", "Action Closed"],
		},
		fields=["name", "audit_score", "status"],
	)


def get_purpose(doc):
	"""``purpose`` is fetched from the Stock Entry Type only during link validation, which runs
	after ``before_validate``; resolve it here for entries posted with just the type."""
	purpose = doc.get("purpose")
	if not purpose and doc.get("stock_entry_type"):
		purpose = frappe.get_cached_value("Stock Entry Type", doc.stock_entry_type, "purpose")
	return purpose


def validate_stock_entry(doc, method=None):
	"""Stock Entry ``before_validate`` hook for the finished-goods (Manufacture) entry of a Work
	Order (the "Finish" button builds it with ``make_stock_entry(..., "Manufacture")``):

	1. blocked while a failed Production Audit (< ``AUDIT_FAIL_SCORE``) on the Work Order is
	   still open - audits themselves stay optional (daily);
	2. blocked until every operation has a completed Job Card with an Accepted Quality
	   Inspection (``operation_inspection.validate_manufacture_inspections``, ADR-19).

	Registered as ``before_validate`` so the one consolidated "Missing before finish" message is
	shown ahead of ERPNext's own per-operation completed-qty check. Work Order completion runs
	through this Stock Entry, so no separate Work Order hook is needed.
	"""
	if get_purpose(doc) != "Manufacture" or not doc.get("work_order"):
		return

	validate_open_audits(doc)
	validate_manufacture_inspections(doc)


def validate_open_audits(doc):
	audits = get_blocking_audits(doc.work_order)
	if not audits:
		return

	listing = "<br>".join(
		_("{0} (score {1}, status {2})").format(
			get_link_to_form("Production Audit", a.name), a.audit_score, a.status
		)
		for a in audits
	)
	frappe.throw(
		_(
			"Work Order {0} cannot be completed: Production Audits below {1} are still open.<br>{2}<br><br>"
			"Close the corrective action and move the audit to 'Action Closed' first."
		).format(frappe.bold(doc.work_order), config.AUDIT_FAIL_SCORE, listing),
		title=_("Production Audit Open"),
	)


# ---------------------------------------------------------------------------
# Work Order form: Create > Production Audit and status headline
# ---------------------------------------------------------------------------


def get_headline_audit(work_order):
	"""The audit the Work Order headline reports: the most recent audit that still blocks the
	Finish (below the fail score, not Action Closed - the same rows ``get_blocking_audits`` gates
	on, so the headline never shows green while the Finish is refused), else the latest submitted
	audit (by audit date, then creation)."""
	filters = {"work_order": work_order, "docstatus": 1}
	fields = ["name", "audit_score", "status", "audit_date"]
	order_by = "audit_date desc, creation desc"
	blocking = frappe.get_all(
		"Production Audit",
		filters={
			**filters,
			"audit_score": ["<", config.AUDIT_FAIL_SCORE],
			"status": ["!=", "Action Closed"],
		},
		fields=fields,
		order_by=order_by,
		limit=1,
	)
	if blocking:
		return blocking[0], True
	latest = frappe.get_all("Production Audit", filters=filters, fields=fields, order_by=order_by, limit=1)
	return (latest[0], False) if latest else (None, False)


def get_session_employee():
	"""Active Employee linked to the session user, if any (the audit's ``inspector``); blank for
	users without an Employee record (Administrator on the demo site)."""
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")


@frappe.whitelist()
def get_audit_status(work_order):
	"""Headline data for the Work Order form. Read permission on the Work Order is the gate; the
	audit name and score are returned even to users without Production Audit read so the headline
	never claims "no audit" for a Work Order whose Finish is in fact blocked.

	``blocking``: an audit below ``AUDIT_FAIL_SCORE`` is still open (not Action Closed); the
	headline then names that audit rather than a newer passing one.
	``missing_before_finish``: number of operations still lacking a completed Job Card / Accepted
	inspection (``operation_inspection.get_missing_before_finish``), for open Work Orders only.
	"""
	frappe.has_permission("Work Order", "read", doc=work_order, throw=True)
	wo = frappe.db.get_value("Work Order", work_order, ["status", "docstatus"], as_dict=True)
	if not wo:
		frappe.throw(_("Work Order {0} not found").format(work_order), frappe.DoesNotExistError)

	audit, blocking = get_headline_audit(work_order)
	is_open = wo.docstatus == 1 and wo.status not in CLOSED_WORK_ORDER_STATUSES
	return {
		"audit": audit.name if audit else None,
		"score": audit.audit_score if audit else None,
		"status": audit.status if audit else None,
		"fail_score": config.AUDIT_FAIL_SCORE,
		"blocking": blocking,
		"can_audit": is_open,
		"missing_before_finish": len(get_missing_before_finish(work_order)) if is_open else 0,
	}


@frappe.whitelist()
def make_production_audit(source_name, target_doc=None):
	"""Work Order "Create > Production Audit": a new audit pre-filled with the Work Order, its
	production item, the first operation's workstation, today and the session user's Employee,
	returned unsaved for the form (``frappe.model.open_mapped_doc``, the route ERPNext's own
	Create buttons use)."""
	frappe.has_permission("Work Order", "read", doc=source_name, throw=True)
	frappe.has_permission("Production Audit", "create", throw=True)

	wo = frappe.db.get_value(
		"Work Order", source_name, ["name", "status", "docstatus", "production_item"], as_dict=True
	)
	if not wo:
		frappe.throw(_("Work Order {0} not found").format(source_name), frappe.DoesNotExistError)
	if wo.docstatus != 1:
		frappe.throw(
			_("Work Order {0} must be submitted before a Production Audit can be recorded").format(
				frappe.bold(source_name)
			),
			title=_("Work Order Not Submitted"),
		)
	if wo.status in CLOSED_WORK_ORDER_STATUSES:
		frappe.throw(
			_(
				"Work Order {0} is {1}; a Production Audit can only be recorded against an open Work Order"
			).format(frappe.bold(source_name), frappe.bold(_(wo.status))),
			title=_("Work Order Closed"),
		)

	audit = frappe.new_doc("Production Audit")
	audit.update(
		{
			"work_order": wo.name,
			"item_code": wo.production_item,
			"workstation": frappe.db.get_value(
				"Work Order Operation",
				{"parent": wo.name, "parenttype": "Work Order"},
				"workstation",
				order_by="idx asc",
			),
			"audit_date": nowdate(),
			"inspector": get_session_employee(),
		}
	)
	return audit

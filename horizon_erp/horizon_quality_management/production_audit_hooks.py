# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Stock Entry hooks that gate the Work Order finish: Production Audit outcomes and the
mandatory per-operation inspection (ADR-19)."""

import frappe
from frappe import _
from frappe.utils import get_link_to_form

from horizon_erp.horizon_core import config
from horizon_erp.horizon_quality_management.operation_inspection import validate_manufacture_inspections


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

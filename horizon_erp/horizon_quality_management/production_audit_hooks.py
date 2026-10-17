# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Stock Entry hooks that enforce Production Audit outcomes."""

import frappe
from frappe import _
from frappe.utils import get_link_to_form

from horizon_erp.horizon_core import config


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


def validate_stock_entry(doc, method=None):
	"""Stock Entry ``validate`` hook: the finished-goods (Manufacture) entry of a Work Order is
	blocked while a failed Production Audit on that Work Order is still open.

	Note for the lead: Work Order completion runs through this Stock Entry, so no separate
	Work Order hook is needed; a ``before_update_after_submit`` guard on ``status`` = Completed
	would only be belt-and-braces.
	"""
	if doc.get("purpose") != "Manufacture" or not doc.get("work_order"):
		return

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

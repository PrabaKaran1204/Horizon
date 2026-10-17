# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Quality scheduler jobs: daily quality-vs-delivery-deadline conflict detection.

Scheduled from ``scheduler_events`` in hooks.py. Logging / alerting conventions shared by every job
(``@horizon_job``, Error Log + System Manager alert, retry marker) live in
``horizon_erp.horizon_core.jobs``.
"""

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	cint,
	flt,
	get_url_to_form,
	today,
)

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.jobs import (
	horizon_job,
	notify_users,
	once_per_day,
	users_with_roles,
)

QUALITY_DEADLINE_HORIZON_DAYS = 3
AUDIT_SCORE_THRESHOLD = config.AUDIT_FAIL_SCORE


# ---------------------------------------------------------------------------
# Quality vs delivery deadline conflicts
# ---------------------------------------------------------------------------
@horizon_job("detect_quality_deadline_conflicts")
def detect_quality_deadline_conflicts():
	"""Daily. Flags submitted Sales Orders due within ``QUALITY_DEADLINE_HORIZON_DAYS`` (or overdue),
	not fully delivered, whose Work Orders are not Completed, or have an open Production Audit
	below ``AUDIT_SCORE_THRESHOLD``, or a Rejected Quality Inspection (on the WO's Stock Entries /
	Job Cards), and for which no submitted Shipment Decision exists yet. One Notification Log +
	email per SO per day to Sales Manager, Operations Head and Quality Manager.

	Returns ``{"flagged": [{"sales_order", "customer", "delivery_date", "conflicts": [...]}, ...]}``.
	"""
	out = {"flagged": [], "checked": 0}
	horizon = add_days(today(), QUALITY_DEADLINE_HORIZON_DAYS)
	sales_orders = frappe.get_all(
		"Sales Order",
		filters={
			"docstatus": 1,
			"status": ["not in", ["Completed", "Closed", "Cancelled"]],
			"per_delivered": ["<", 100],
			"delivery_date": ["<=", horizon],
		},
		fields=["name", "customer", "delivery_date", "per_delivered", "grand_total", "currency"],
		limit=500,
	)
	recipients = users_with_roles("Sales Manager", "Operations Head", "Quality Manager")

	for so in sales_orders:
		out["checked"] += 1
		if frappe.db.exists("Shipment Decision", {"sales_order": so.name, "docstatus": 1}):
			continue
		conflicts = _quality_conflicts_for(so.name)
		if not conflicts:
			continue

		entry = {
			"sales_order": so.name,
			"customer": so.customer,
			"delivery_date": str(so.delivery_date),
			"per_delivered": flt(so.per_delivered),
			"conflicts": conflicts,
		}
		out["flagged"].append(entry)
		if not once_per_day("quality_conflict", so.name):
			continue

		subject = _("Delivery at risk: {0} ({1}) due {2}").format(so.name, so.customer, so.delivery_date)
		message = _(
			"Sales Order <a href='{0}'>{1}</a> for {2} is due on {3} ({4}% delivered) and has open "
			"quality / production conflicts:<ul>{5}</ul>Please record a Shipment Decision."
		).format(
			get_url_to_form("Sales Order", so.name),
			so.name,
			so.customer,
			so.delivery_date,
			cint(so.per_delivered),
			"".join(f"<li>{frappe.utils.escape_html(c)}</li>" for c in conflicts),
		)
		notify_users(recipients, subject, message, doctype="Sales Order", docname=so.name)
	return out


def _quality_conflicts_for(sales_order):
	work_orders = frappe.get_all(
		"Work Order",
		filters={"sales_order": sales_order, "docstatus": ["<", 2]},
		fields=["name", "status", "production_item"],
	)
	if not work_orders:
		return []
	wo_names = [w.name for w in work_orders]
	conflicts = [
		_("Work Order {0} ({1}) is {2}").format(w.name, w.production_item, w.status)
		for w in work_orders
		if w.status not in ("Completed",)
	]

	for audit in frappe.get_all(
		"Production Audit",
		filters={
			"work_order": ["in", wo_names],
			"docstatus": ["<", 2],
			"audit_score": ["<", AUDIT_SCORE_THRESHOLD],
			"status": ["!=", "Action Closed"],
		},
		fields=["name", "work_order", "audit_score"],
	):
		conflicts.append(
			_("Production Audit {0} on {1} scored {2}").format(
				audit.name, audit.work_order, audit.audit_score
			)
		)

	refs = frappe.get_all(
		"Stock Entry", filters={"work_order": ["in", wo_names], "docstatus": 1}, pluck="name"
	)
	refs += frappe.get_all(
		"Job Card", filters={"work_order": ["in", wo_names], "docstatus": ["<", 2]}, pluck="name"
	)
	if refs:
		for qi in frappe.get_all(
			"Quality Inspection",
			filters={"reference_name": ["in", refs], "status": "Rejected", "docstatus": 1},
			fields=["name", "item_code", "reference_name"],
		):
			conflicts.append(
				_("Quality Inspection {0} rejected {1} ({2})").format(
					qi.name, qi.item_code, qi.reference_name
				)
			)
	return conflicts

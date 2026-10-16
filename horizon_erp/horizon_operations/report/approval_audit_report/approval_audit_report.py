# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Approval Audit Report: Purchase Order workflow transitions (Comment type "Workflow")."""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, time_diff_in_hours

PENDING_LIKE = "Pending%"
AGE_BUCKETS = ("< 24h", "24-48h", "> 48h")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	columns = get_columns()
	data, pos = get_data(filters)
	return columns, data, None, get_chart(pos), get_summary(data, pos)


def get_columns():
	return [
		{
			"label": _("Purchase Order"),
			"fieldname": "purchase_order",
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": 140,
		},
		{
			"label": _("Supplier"),
			"fieldname": "supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 140,
		},
		{"label": _("Amount"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 110},
		{
			"label": _("Level Required"),
			"fieldname": "approval_level_required",
			"fieldtype": "Data",
			"width": 100,
		},
		{"label": _("Current State"), "fieldname": "workflow_state", "fieldtype": "Data", "width": 150},
		{
			"label": _("Created By"),
			"fieldname": "owner",
			"fieldtype": "Link",
			"options": "User",
			"width": 130,
		},
		{"label": _("Created On"), "fieldname": "creation", "fieldtype": "Datetime", "width": 150},
		{"label": _("Transition"), "fieldname": "transition", "fieldtype": "Data", "width": 150},
		{
			"label": _("By"),
			"fieldname": "transition_by",
			"fieldtype": "Link",
			"options": "User",
			"width": 130,
		},
		{"label": _("At"), "fieldname": "transition_at", "fieldtype": "Datetime", "width": 150},
		{
			"label": _("Hours In Previous State"),
			"fieldname": "hours_in_previous_state",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Blacklist Override"),
			"fieldname": "blacklist_override",
			"fieldtype": "Check",
			"width": 80,
		},
		{"label": _("Override Reason"), "fieldname": "override_reason", "fieldtype": "Data", "width": 160},
		{
			"label": _("Exception Log"),
			"fieldname": "exception_log",
			"fieldtype": "Link",
			"options": "Supplier Exception Log",
			"width": 120,
		},
	]


def get_data(filters):
	po = frappe.qb.DocType("Purchase Order")
	query = (
		frappe.qb.from_(po)
		.select(
			po.name.as_("purchase_order"),
			po.supplier,
			po.grand_total,
			po.approval_level_required,
			po.workflow_state,
			po.owner,
			po.creation,
			po.blacklist_override,
			po.override_reason,
			po.pending_since,
			po.docstatus,
		)
		.where((po.docstatus < 2) & (po.company == filters.company))
		.orderby(po.creation)
	)
	if filters.from_date:
		query = query.where(po.transaction_date >= filters.from_date)
	if filters.to_date:
		query = query.where(po.transaction_date <= filters.to_date)
	if filters.supplier:
		query = query.where(po.supplier == filters.supplier)
	if filters.state:
		query = query.where(po.workflow_state == filters.state)
	if cint(filters.only_overrides):
		query = query.where(po.blacklist_override == 1)
	pos = query.run(as_dict=True)
	if not pos:
		return [], []

	names = [p.purchase_order for p in pos]
	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "Purchase Order",
			"reference_name": ["in", names],
			"comment_type": "Workflow",
		},
		fields=["reference_name", "content", "owner", "creation"],
		order_by="creation asc",
	)
	by_po = {}
	for c in comments:
		by_po.setdefault(c.reference_name, []).append(c)

	logs = frappe.get_all(
		"Supplier Exception Log",
		filters={"purchase_order": ["in", names]},
		fields=["name", "purchase_order"],
		order_by="creation desc",
	)
	log_by_po = {}
	for log in logs:
		log_by_po.setdefault(log.purchase_order, log.name)

	data = []
	for p in pos:
		base = dict(p)
		base["exception_log"] = log_by_po.get(p.purchase_order)
		transitions = by_po.get(p.purchase_order) or []
		if not transitions:
			data.append(
				frappe._dict(
					base,
					transition=None,
					transition_by=None,
					transition_at=None,
					hours_in_previous_state=None,
				)
			)
			continue
		previous = get_datetime(p.creation)
		for c in transitions:
			row = frappe._dict(base)
			row.transition = frappe.utils.strip_html(c.content or "")
			row.transition_by = c.owner
			row.transition_at = c.creation
			row.hours_in_previous_state = flt(time_diff_in_hours(c.creation, previous), 2)
			previous = get_datetime(c.creation)
			data.append(row)
	return data, pos


def get_age_bucket(hours):
	if hours < 24:
		return AGE_BUCKETS[0]
	if hours <= 48:
		return AGE_BUCKETS[1]
	return AGE_BUCKETS[2]


def pending_hours(po):
	since = po.pending_since or po.creation
	return flt(time_diff_in_hours(now_datetime(), since))


def is_pending(po):
	return bool(po.workflow_state and po.workflow_state.startswith("Pending")) and po.docstatus == 0


def get_chart(pos):
	counts = dict.fromkeys(AGE_BUCKETS, 0)
	for p in pos:
		if is_pending(p):
			counts[get_age_bucket(pending_hours(p))] += 1
	return {
		"data": {
			"labels": list(counts.keys()),
			"datasets": [{"name": _("Pending POs"), "values": list(counts.values())}],
		},
		"type": "bar",
		"colors": ["#29cd42", "#ffa00a", "#ff5858"],
	}


def get_summary(data, pos):
	# approval time = creation -> last "Approved" transition
	approval_hours = []
	last_transition = {}
	for row in data:
		if row.transition and row.transition.lower().startswith("approved"):
			last_transition[row.purchase_order] = time_diff_in_hours(row.transition_at, row.creation)
	approval_hours = list(last_transition.values())
	avg = sum(approval_hours) / len(approval_hours) if approval_hours else 0
	pending_over_24 = sum(1 for p in pos if is_pending(p) and pending_hours(p) > 24)
	return [
		{"value": flt(avg, 1), "label": _("Avg Approval Time (h)"), "datatype": "Float", "indicator": "Blue"},
		{
			"value": pending_over_24,
			"label": _("Pending > 24h"),
			"datatype": "Int",
			"indicator": "Red" if pending_over_24 else "Green",
		},
		{"value": len(pos), "label": _("Purchase Orders"), "datatype": "Int", "indicator": "Blue"},
	]

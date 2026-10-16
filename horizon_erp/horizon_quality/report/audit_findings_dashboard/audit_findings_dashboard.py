# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Audit Findings Dashboard: Production Audits with scores, escalations and corrective actions."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, nowdate

LOW_SCORE = 70
CONSISTENT_LOW = 75


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.to_date:
		filters.to_date = nowdate()
	if not filters.from_date:
		filters.from_date = add_days(filters.to_date, -30)
	columns = get_columns()
	data = get_data(filters)
	return columns, data, get_message(data), get_chart(data), get_summary(data)


def get_columns():
	return [
		{
			"label": _("Audit"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Production Audit",
			"width": 140,
		},
		{"label": _("Date"), "fieldname": "audit_date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Work Order"),
			"fieldname": "work_order",
			"fieldtype": "Link",
			"options": "Work Order",
			"width": 130,
		},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
		{
			"label": _("Workstation"),
			"fieldname": "workstation",
			"fieldtype": "Link",
			"options": "Workstation",
			"width": 120,
		},
		{
			"label": _("Inspector"),
			"fieldname": "inspector",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{"label": _("Score"), "fieldname": "audit_score", "fieldtype": "Int", "width": 70},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": _("Escalated"), "fieldname": "escalated", "fieldtype": "Check", "width": 80},
		{
			"label": _("Corrective Action"),
			"fieldname": "corrective_action",
			"fieldtype": "Link",
			"options": "Quality Action",
			"width": 130,
		},
		{"label": _("CA Status"), "fieldname": "ca_status", "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	pa = frappe.qb.DocType("Production Audit")
	qa = frappe.qb.DocType("Quality Action")
	q = (
		frappe.qb.from_(pa)
		.left_join(qa)
		.on(qa.name == pa.corrective_action)
		.select(
			pa.name,
			pa.audit_date,
			pa.work_order,
			pa.item_code,
			pa.workstation,
			pa.inspector,
			pa.audit_score,
			pa.status,
			pa.escalated,
			pa.corrective_action,
			qa.status.as_("ca_status"),
		)
		.where((pa.docstatus < 2) & (pa.audit_date.between(filters.from_date, filters.to_date)))
		.orderby(pa.audit_date, order=frappe.qb.desc)
		.orderby(pa.name)
	)
	if filters.workstation:
		q = q.where(pa.workstation == filters.workstation)
	if filters.inspector:
		q = q.where(pa.inspector == filters.inspector)
	if filters.min_score is not None and filters.min_score != "":
		q = q.where(pa.audit_score >= cint(filters.min_score))
	return q.run(as_dict=True)


def get_chart(data):
	by_day = {}
	for r in data:
		by_day.setdefault(str(r.audit_date), []).append(cint(r.audit_score))
	days = sorted(by_day)
	return {
		"data": {
			"labels": days,
			"datasets": [
				{
					"name": _("Average Score"),
					"values": [flt(sum(by_day[d]) / len(by_day[d]), 1) for d in days],
				}
			],
		},
		"type": "line",
		"colors": ["#5e64ff"],
	}


def get_summary(data):
	count = len(data)
	avg = sum(cint(r.audit_score) for r in data) / count if count else 0
	below = sum(1 for r in data if cint(r.audit_score) < LOW_SCORE)
	open_ca = sum(1 for r in data if r.corrective_action and r.ca_status != "Completed")
	return [
		{"value": count, "label": _("Audits"), "datatype": "Int", "indicator": "Blue"},
		{
			"value": flt(avg, 1),
			"label": _("Average Score"),
			"datatype": "Float",
			"indicator": "Green" if avg >= LOW_SCORE else "Red",
		},
		{
			"value": below / count * 100 if count else 0,
			"label": _("% Below 70"),
			"datatype": "Percent",
			"indicator": "Red" if below else "Green",
		},
		{
			"value": open_ca,
			"label": _("Open Corrective Actions"),
			"datatype": "Int",
			"indicator": "Orange" if open_ca else "Green",
		},
	]


def low_score_workstations(data):
	scores = {}
	for r in data:
		if r.workstation:
			scores.setdefault(r.workstation, []).append(cint(r.audit_score))
	result = []
	for ws, values in scores.items():
		if len(values) >= 2 and sum(values) / len(values) < CONSISTENT_LOW:
			result.append((ws, flt(sum(values) / len(values), 1), len(values)))
	return sorted(result, key=lambda x: x[1])


def get_message(data):
	low = low_score_workstations(data)
	pending = [r for r in data if r.corrective_action and r.ca_status != "Completed"]
	parts = [
		f"<h5>{_('Workstations with consistently low scores')} (avg &lt; {CONSISTENT_LOW}, &ge; 2 audits)</h5>"
	]
	if low:
		parts.append("<ul>")
		for ws, avg, n in low:
			parts.append(
				f"<li><b>{frappe.utils.escape_html(ws)}</b>: {_('avg')} <span style='color:red'>{avg}</span> "
				f"({n} {_('audits')})</li>"
			)
		parts.append("</ul>")
	else:
		parts.append(f"<p class='text-muted'>{_('None')}</p>")
	parts.append(f"<h5>{_('Pending corrective actions')}</h5>")
	if pending:
		parts.append("<ul>")
		for r in pending:
			link = frappe.utils.get_link_to_form("Quality Action", r.corrective_action)
			audit = frappe.utils.get_link_to_form("Production Audit", r.name)
			parts.append(f"<li>{link} ({_('from')} {audit}, {_('status')}: {r.ca_status or _('Open')})</li>")
		parts.append("</ul>")
	else:
		parts.append(f"<p class='text-muted'>{_('None')}</p>")
	return "".join(parts)

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Quality vs Deadline Conflicts: near-due Sales Orders whose Work Orders carry quality risk."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

LOW_SCORE = 70


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	filters.days_ahead = cint(filters.days_ahead) or 7
	if not filters.to_date:
		filters.to_date = nowdate()
	if not filters.from_date:
		try:
			filters.from_date = get_fiscal_year(filters.to_date, company=filters.company)[1]
		except Exception:
			filters.from_date = add_days(filters.to_date, -90)
	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, get_chart(data), get_summary(data, filters)


def get_columns():
	return [
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 130,
		},
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 140,
		},
		{"label": _("Delivery Date"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days to Delivery"), "fieldname": "days_to_delivery", "fieldtype": "Int", "width": 90},
		{"label": _("% Delivered"), "fieldname": "per_delivered", "fieldtype": "Percent", "width": 90},
		{
			"label": _("Work Order"),
			"fieldname": "work_order",
			"fieldtype": "Link",
			"options": "Work Order",
			"width": 130,
		},
		{
			"label": _("Item"),
			"fieldname": "production_item",
			"fieldtype": "Link",
			"options": "Item",
			"width": 120,
		},
		{"label": _("WO Status"), "fieldname": "wo_status", "fieldtype": "Data", "width": 100},
		{"label": _("WO Qty"), "fieldname": "wo_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Produced Qty"), "fieldname": "produced_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Open Audits < 70"), "fieldname": "low_audits", "fieldtype": "Int", "width": 100},
		{"label": _("QI Rejected"), "fieldname": "qi_rejected", "fieldtype": "Int", "width": 90},
		{
			"label": _("Shipment Decision"),
			"fieldname": "shipment_decision",
			"fieldtype": "Link",
			"options": "Shipment Decision",
			"width": 130,
		},
		{"label": _("Decision"), "fieldname": "decision", "fieldtype": "Data", "width": 150},
		{
			"label": _("Est. Quality Cost"),
			"fieldname": "estimated_quality_cost",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Est. Delay Cost"),
			"fieldname": "estimated_delay_cost",
			"fieldtype": "Currency",
			"width": 120,
		},
		{"label": _("Conflict"), "fieldname": "conflict", "fieldtype": "Check", "width": 70},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 190},
	]


def get_data(filters):
	so = frappe.qb.DocType("Sales Order")
	horizon = add_days(nowdate(), filters.days_ahead)
	q = (
		frappe.qb.from_(so)
		.select(so.name.as_("sales_order"), so.customer, so.delivery_date, so.per_delivered)
		.where(
			(so.docstatus == 1)
			& (so.company == filters.company)
			& (so.per_delivered < 100)
			& (so.status.notin(["Closed", "Completed", "Cancelled"]))
			& (so.delivery_date <= horizon)
		)
		.orderby(so.delivery_date)
	)
	if filters.customer:
		q = q.where(so.customer == filters.customer)
	orders = q.run(as_dict=True)
	if not orders:
		return []
	so_names = [o.sales_order for o in orders]

	wos = frappe.get_all(
		"Work Order",
		filters={"sales_order": ["in", so_names], "docstatus": 1},
		fields=["name", "sales_order", "production_item", "status", "qty", "produced_qty"],
		order_by="planned_start_date asc, name asc",
	)
	wo_by_so = {}
	for w in wos:
		wo_by_so.setdefault(w.sales_order, []).append(w)
	wo_names = [w.name for w in wos]

	low_audits = {}
	qi_rejected = {}
	if wo_names:
		pa = frappe.qb.DocType("Production Audit")
		for r in (
			frappe.qb.from_(pa)
			.select(pa.work_order, Count(pa.name).as_("cnt"))
			.where(
				(pa.docstatus < 2)
				& (pa.work_order.isin(wo_names))
				& (pa.audit_score < LOW_SCORE)
				& (pa.status != "Action Closed")
			)
			.groupby(pa.work_order)
		).run(as_dict=True):
			low_audits[r.work_order] = r.cnt
		qi_rejected = get_rejected_qi_counts(wo_names)

	decisions = {}
	for d in frappe.get_all(
		"Shipment Decision",
		filters={"sales_order": ["in", so_names], "docstatus": 1},
		fields=["name", "sales_order", "decision", "estimated_quality_cost", "estimated_delay_cost"],
		order_by="creation desc",
	):
		decisions.setdefault(d.sales_order, d)

	as_on = getdate(nowdate())
	data = []
	for o in orders:
		decision = decisions.get(o.sales_order)
		base = frappe._dict(
			sales_order=o.sales_order,
			customer=o.customer,
			delivery_date=o.delivery_date,
			days_to_delivery=date_diff(o.delivery_date, as_on) if o.delivery_date else None,
			per_delivered=flt(o.per_delivered),
			shipment_decision=decision.name if decision else None,
			decision=decision.decision if decision else None,
			estimated_quality_cost=flt(decision.estimated_quality_cost) if decision else 0,
			estimated_delay_cost=flt(decision.estimated_delay_cost) if decision else 0,
		)
		related = wo_by_so.get(o.sales_order) or [None]
		for idx, w in enumerate(related):
			row = frappe._dict(base)
			if idx:  # show decision costs once per SO so the summary does not double count
				row.estimated_quality_cost = row.estimated_delay_cost = 0
			if w:
				row.update(
					work_order=w.name,
					production_item=w.production_item,
					wo_status=w.status,
					wo_qty=flt(w.qty),
					produced_qty=flt(w.produced_qty),
					low_audits=cint(low_audits.get(w.name)),
					qi_rejected=cint(qi_rejected.get(w.name)),
				)
				wo_incomplete = w.status not in ("Completed", "Closed")
			else:
				row.update(low_audits=0, qi_rejected=0, wo_status=None)
				wo_incomplete = False
			row.conflict = cint(wo_incomplete or row.low_audits or row.qi_rejected)
			if not row.conflict:
				row.status = "OK"
			elif decision:
				row.status = f"Decided: {decision.decision}"
			else:
				row.status = "Conflict - Undecided"
			data.append(row)
	return data


def get_rejected_qi_counts(wo_names):
	"""Rejected QIs reach a Work Order through Stock Entry or Job Card references."""
	qi = frappe.qb.DocType("Quality Inspection")
	se = frappe.qb.DocType("Stock Entry")
	jc = frappe.qb.DocType("Job Card")
	counts = {}
	for ref_dt, ref in (("Stock Entry", se), ("Job Card", jc)):
		for r in (
			frappe.qb.from_(qi)
			.inner_join(ref)
			.on((qi.reference_type == ref_dt) & (qi.reference_name == ref.name))
			.select(ref.work_order, Count(qi.name).as_("cnt"))
			.where((qi.docstatus == 1) & (qi.status == "Rejected") & (ref.work_order.isin(wo_names)))
			.groupby(ref.work_order)
		).run(as_dict=True):
			counts[r.work_order] = counts.get(r.work_order, 0) + r.cnt
	return counts


def get_chart(data):
	by_customer = {}
	for r in data:
		if r.conflict:
			by_customer[r.customer] = by_customer.get(r.customer, 0) + 1
	return {
		"data": {
			"labels": list(by_customer.keys()),
			"datasets": [{"name": _("Conflicts"), "values": list(by_customer.values())}],
		},
		"type": "bar",
		"colors": ["#ff5858"],
	}


def get_rework_cost(filters):
	"""Rework Work Orders (rework_of set) created in the period: operating + material cost."""
	wo = frappe.qb.DocType("Work Order")
	woi = frappe.qb.DocType("Work Order Item")
	rows = (
		frappe.qb.from_(wo)
		.left_join(woi)
		.on(woi.parent == wo.name)
		.select(
			wo.name,
			wo.total_operating_cost,
			wo.planned_operating_cost,
			Sum(woi.amount).as_("material_cost"),
		)
		.where(
			(wo.docstatus == 1)
			& (wo.company == filters.company)
			& (wo.rework_of.isnotnull())
			& (wo.rework_of != "")
			& (wo.creation >= filters.from_date)
		)
		.groupby(wo.name)
	).run(as_dict=True)
	total = 0.0
	for r in rows:
		total += flt(r.total_operating_cost) or flt(r.planned_operating_cost)
		total += flt(r.material_cost)
	return total


def get_summary(data, filters):
	undecided = len({r.sales_order for r in data if r.status == "Conflict - Undecided"})
	decided = len({r.sales_order for r in data if r.status.startswith("Decided")})
	ok = len({r.sales_order for r in data if r.status == "OK"})
	quality_cost = sum(r.estimated_quality_cost for r in data) + get_rework_cost(filters)
	delay_cost = sum(r.estimated_delay_cost for r in data)
	return [
		{
			"value": undecided,
			"label": _("Undecided Conflicts"),
			"datatype": "Int",
			"indicator": "Red" if undecided else "Green",
		},
		{"value": decided, "label": _("Decided"), "datatype": "Int", "indicator": "Orange"},
		{"value": ok, "label": _("OK"), "datatype": "Int", "indicator": "Green"},
		{
			"value": quality_cost,
			"label": _("Cost of Poor Quality (period)"),
			"datatype": "Currency",
			"indicator": "Red",
		},
		{"value": delay_cost, "label": _("Cost of Delay"), "datatype": "Currency", "indicator": "Orange"},
	]

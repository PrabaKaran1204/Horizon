# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Project Profitability: cost, margin and schedule variance per Project."""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import date_diff, flt, getdate, nowdate

SCHEDULE_ALERT = -10


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, get_chart(data), get_summary(data)


def get_columns():
	return [
		{
			"label": _("Project"),
			"fieldname": "project",
			"fieldtype": "Link",
			"options": "Project",
			"width": 140,
		},
		{"label": _("Project Name"), "fieldname": "project_name", "fieldtype": "Data", "width": 150},
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 130,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{
			"label": _("Estimated Cost"),
			"fieldname": "estimated_costing",
			"fieldtype": "Currency",
			"width": 120,
		},
		{"label": _("Material Cost"), "fieldname": "material_cost", "fieldtype": "Currency", "width": 120},
		{"label": _("Labour Cost"), "fieldname": "labour_cost", "fieldtype": "Currency", "width": 120},
		{"label": _("Overhead"), "fieldname": "overhead", "fieldtype": "Currency", "width": 110},
		{"label": _("Total Cost"), "fieldname": "total_cost", "fieldtype": "Currency", "width": 120},
		{"label": _("Billed"), "fieldname": "billed", "fieldtype": "Currency", "width": 120},
		{"label": _("Margin"), "fieldname": "margin", "fieldtype": "Currency", "width": 120},
		{"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 90},
		{
			"label": _("Budgeted Margin %"),
			"fieldname": "budgeted_margin_percent",
			"fieldtype": "Percent",
			"width": 110,
		},
		{"label": _("Planned Hours"), "fieldname": "planned_hours", "fieldtype": "Float", "width": 100},
		{"label": _("Actual Hours"), "fieldname": "actual_hours", "fieldtype": "Float", "width": 100},
		{
			"label": _("Hours Variance %"),
			"fieldname": "hours_variance_pct",
			"fieldtype": "Percent",
			"width": 110,
		},
		{"label": _("% Complete"), "fieldname": "percent_complete", "fieldtype": "Percent", "width": 90},
		{"label": _("Time Elapsed %"), "fieldname": "time_elapsed_pct", "fieldtype": "Percent", "width": 100},
		{
			"label": _("Schedule Variance"),
			"fieldname": "schedule_variance",
			"fieldtype": "Float",
			"width": 110,
		},
	]


def get_data(filters):
	project_filters = {"company": filters.company}
	if filters.status:
		project_filters["status"] = filters.status
	if filters.customer:
		project_filters["customer"] = filters.customer
	if filters.project:
		project_filters["name"] = filters.project
	projects = frappe.get_all(
		"Project",
		filters=project_filters,
		fields=[
			"name",
			"project_name",
			"customer",
			"status",
			"estimated_costing",
			"total_consumed_material_cost",
			"total_costing_amount",
			"overhead_percent",
			"budgeted_margin_percent",
			"total_billed_amount",
			"actual_time",
			"percent_complete",
			"expected_start_date",
			"expected_end_date",
		],
		order_by="expected_end_date asc, name asc",
	)
	if not projects:
		return []
	names = [p.name for p in projects]

	task = frappe.qb.DocType("Task")
	planned = {
		r.project: flt(r.hours)
		for r in (
			frappe.qb.from_(task)
			.select(task.project, Sum(task.expected_time).as_("hours"))
			.where(task.project.isin(names))
			.groupby(task.project)
		).run(as_dict=True)
	}
	si = frappe.qb.DocType("Sales Invoice")
	invoiced = {
		r.project: flt(r.total)
		for r in (
			frappe.qb.from_(si)
			.select(si.project, Sum(si.base_grand_total).as_("total"))
			.where((si.docstatus == 1) & (si.project.isin(names)))
			.groupby(si.project)
		).run(as_dict=True)
	}

	as_on = getdate(nowdate())
	data = []
	for p in projects:
		material = flt(p.total_consumed_material_cost)
		labour = flt(p.total_costing_amount)
		overhead = flt(p.overhead_percent) / 100 * (material + labour)
		total_cost = material + labour + overhead
		billed = flt(p.total_billed_amount) or invoiced.get(p.name, 0.0)
		margin = billed - total_cost
		planned_hours = planned.get(p.name, 0.0)
		actual_hours = flt(p.actual_time)
		elapsed = time_elapsed_pct(p.expected_start_date, p.expected_end_date, as_on)
		row = frappe._dict(
			project=p.name,
			project_name=p.project_name,
			customer=p.customer,
			status=p.status,
			estimated_costing=flt(p.estimated_costing),
			material_cost=material,
			labour_cost=labour,
			overhead=overhead,
			total_cost=total_cost,
			billed=billed,
			margin=margin,
			margin_pct=margin / billed * 100 if billed else 0,
			budgeted_margin_percent=flt(p.budgeted_margin_percent),
			planned_hours=planned_hours,
			actual_hours=actual_hours,
			hours_variance_pct=(actual_hours - planned_hours) / planned_hours * 100 if planned_hours else 0,
			percent_complete=flt(p.percent_complete),
			time_elapsed_pct=elapsed,
			schedule_variance=flt(p.percent_complete) - elapsed if elapsed is not None else None,
		)
		row.margin_alert = int(row.margin_pct < row.budgeted_margin_percent)
		row.schedule_alert = int(row.schedule_variance is not None and row.schedule_variance < SCHEDULE_ALERT)
		data.append(row)
	return data


def time_elapsed_pct(start, end, as_on):
	if not (start and end):
		return None
	total = date_diff(end, start)
	if total <= 0:
		return 100.0 if as_on >= getdate(end) else 0.0
	elapsed = date_diff(as_on, start)
	return flt(min(max(elapsed / total * 100, 0), 100), 1)


def get_chart(data):
	top = sorted(data, key=lambda r: r.billed, reverse=True)[:10]
	return {
		"data": {
			"labels": [r.project for r in top],
			"datasets": [
				{"name": _("Billed"), "values": [flt(r.billed, 2) for r in top]},
				{"name": _("Total Cost"), "values": [flt(r.total_cost, 2) for r in top]},
			],
		},
		"type": "bar",
		"colors": ["#29cd42", "#ff5858"],
	}


def get_summary(data):
	billed = sum(r.billed for r in data)
	cost = sum(r.total_cost for r in data)
	below_budget = sum(r.margin_alert for r in data)
	behind = sum(r.schedule_alert for r in data)
	return [
		{"value": billed, "label": _("Total Billed"), "datatype": "Currency", "indicator": "Green"},
		{"value": cost, "label": _("Total Cost"), "datatype": "Currency", "indicator": "Red"},
		{
			"value": (billed - cost) / billed * 100 if billed else 0,
			"label": _("Portfolio Margin %"),
			"datatype": "Percent",
			"indicator": "Blue",
		},
		{
			"value": below_budget,
			"label": _("Below Budgeted Margin"),
			"datatype": "Int",
			"indicator": "Red" if below_budget else "Green",
		},
		{
			"value": behind,
			"label": _("Behind Schedule"),
			"datatype": "Int",
			"indicator": "Red" if behind else "Green",
		},
	]

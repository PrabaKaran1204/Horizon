# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Leave Balance with Carry-forward Expiry: per employee x leave type, from Leave Allocations."""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, cint, flt, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	filters.as_on = filters.as_on or nowdate()
	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, get_chart(data), get_summary(data, filters)


def get_columns():
	return [
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 150},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 130,
		},
		{
			"label": _("Leave Type"),
			"fieldname": "leave_type",
			"fieldtype": "Link",
			"options": "Leave Type",
			"width": 130,
		},
		{
			"label": _("Allocation"),
			"fieldname": "allocation",
			"fieldtype": "Link",
			"options": "Leave Allocation",
			"width": 120,
		},
		{"label": _("Period From"), "fieldname": "from_date", "fieldtype": "Date", "width": 100},
		{"label": _("Period To"), "fieldname": "to_date", "fieldtype": "Date", "width": 100},
		{"label": _("Carry Forwarded"), "fieldname": "carry_forwarded", "fieldtype": "Float", "width": 100},
		{"label": _("New Allocated"), "fieldname": "new_leaves", "fieldtype": "Float", "width": 100},
		{"label": _("Total Allocated"), "fieldname": "total_allocated", "fieldtype": "Float", "width": 100},
		{"label": _("Used"), "fieldname": "used", "fieldtype": "Float", "width": 80},
		{"label": _("Available"), "fieldname": "available", "fieldtype": "Float", "width": 90},
		{"label": _("CF Expiry Date"), "fieldname": "cf_expiry_date", "fieldtype": "Date", "width": 110},
		{"label": _("Days to Expiry"), "fieldname": "days_to_expiry", "fieldtype": "Int", "width": 100},
	]


def get_data(filters):
	la = frappe.qb.DocType("Leave Allocation")
	emp = frappe.qb.DocType("Employee")
	q = (
		frappe.qb.from_(la)
		.inner_join(emp)
		.on(emp.name == la.employee)
		.select(
			la.name.as_("allocation"),
			la.employee,
			emp.employee_name,
			emp.department,
			la.leave_type,
			la.from_date,
			la.to_date,
			la.new_leaves_allocated,
			la.unused_leaves,
			la.total_leaves_allocated,
			la.carry_forward,
		)
		.where(
			(la.docstatus == 1)
			& (la.company == filters.company)
			& (la.from_date <= filters.as_on)
			& (la.to_date >= filters.as_on)
		)
		.orderby(la.employee)
		.orderby(la.leave_type)
	)
	if filters.employee:
		q = q.where(la.employee == filters.employee)
	if filters.leave_type:
		q = q.where(la.leave_type == filters.leave_type)
	if filters.department:
		q = q.where(emp.department == filters.department)
	allocations = q.run(as_dict=True)
	if not allocations:
		return []

	leave_types = {
		lt.name: lt
		for lt in frappe.get_all(
			"Leave Type",
			filters={"name": ["in", list({a.leave_type for a in allocations})]},
			fields=["name", "is_carry_forward", "expire_carry_forwarded_leaves_after_days"],
		)
	}
	used = get_used_leaves(allocations)
	as_on = getdate(filters.as_on)

	data = []
	for a in allocations:
		lt = leave_types.get(a.leave_type) or frappe._dict()
		a.carry_forwarded = flt(a.unused_leaves) if cint(a.carry_forward) else 0.0
		a.new_leaves = flt(a.new_leaves_allocated)
		a.total_allocated = flt(a.total_leaves_allocated)
		a.used = flt(used.get((a.employee, a.leave_type, a.from_date, a.to_date)))
		a.available = get_balance(a, as_on)
		expiry_days = cint(lt.expire_carry_forwarded_leaves_after_days)
		if a.carry_forwarded and expiry_days:
			a.cf_expiry_date = add_days(a.from_date, expiry_days)
		else:
			a.cf_expiry_date = a.to_date
		a.days_to_expiry = (getdate(a.cf_expiry_date) - as_on).days if a.cf_expiry_date else None
		data.append(a)
	return data


def get_balance(allocation, as_on):
	"""Prefer the HRMS ledger-based balance; fall back to allocated - used."""
	try:
		from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

		return flt(
			get_leave_balance_on(
				allocation.employee,
				allocation.leave_type,
				as_on,
				to_date=allocation.to_date,
				consider_all_leaves_in_the_allocation_period=True,
			)
		)
	except Exception:
		return flt(allocation.total_allocated) - flt(allocation.used)


def get_used_leaves(allocations):
	app = frappe.qb.DocType("Leave Application")
	employees = list({a.employee for a in allocations})
	rows = (
		frappe.qb.from_(app)
		.select(app.employee, app.leave_type, app.from_date, app.to_date, app.total_leave_days)
		.where((app.docstatus == 1) & (app.status == "Approved") & (app.employee.isin(employees)))
	).run(as_dict=True)
	used = {}
	for a in allocations:
		key = (a.employee, a.leave_type, a.from_date, a.to_date)
		used[key] = 0.0
		for r in rows:
			if (
				r.employee == a.employee
				and r.leave_type == a.leave_type
				and getdate(r.from_date) >= getdate(a.from_date)
				and getdate(r.to_date) <= getdate(a.to_date)
			):
				used[key] += flt(r.total_leave_days)
	return used


def get_chart(data):
	by_type = {}
	for r in data:
		entry = by_type.setdefault(r.leave_type, [0.0, 0.0])
		entry[0] += r.used
		entry[1] += r.available
	return {
		"data": {
			"labels": list(by_type.keys()),
			"datasets": [
				{"name": _("Used"), "values": [flt(v[0], 1) for v in by_type.values()]},
				{"name": _("Available"), "values": [flt(v[1], 1) for v in by_type.values()]},
			],
		},
		"type": "bar",
		"colors": ["#ff5858", "#29cd42"],
	}


def get_summary(data, filters):
	expiring = sum(
		r.carry_forwarded
		for r in data
		if r.carry_forwarded and r.days_to_expiry is not None and 0 <= r.days_to_expiry <= 30
	)
	return [
		{
			"value": len({r.employee for r in data}),
			"label": _("Employees"),
			"datatype": "Int",
			"indicator": "Blue",
		},
		{
			"value": flt(sum(r.available for r in data), 1),
			"label": _("Available Leaves"),
			"datatype": "Float",
			"indicator": "Green",
		},
		{
			"value": flt(sum(r.carry_forwarded for r in data), 1),
			"label": _("Carry Forwarded"),
			"datatype": "Float",
			"indicator": "Blue",
		},
		{
			"value": flt(expiring, 1),
			"label": _("CF Expiring in 30 Days"),
			"datatype": "Float",
			"indicator": "Red" if expiring else "Green",
		},
	]

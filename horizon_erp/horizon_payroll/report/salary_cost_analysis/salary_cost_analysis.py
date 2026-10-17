# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Salary Cost Analysis: submitted Salary Slips grouped by department / branch / grade / employment
type."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import add_months, flt, nowdate

# group label -> (fieldname, link doctype). Department and Branch are read from the Salary Slip
# itself (they are stamped on the slip at payroll time); grade / employment type from the Employee.
GROUP_FIELDS = {
	"Department": ("department", "Department"),
	"Branch": ("branch", "Branch"),
	"Employee Grade": ("grade", "Employee Grade"),
	"Employment Type": ("employment_type", "Employment Type"),
}
SALARY_SLIP_GROUP_FIELDS = ("department", "branch")
EMPLOYER_PF_COMPONENT = "Employer PF"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	if not filters.to_date:
		filters.to_date = nowdate()
	if not filters.from_date:
		try:
			filters.from_date = get_fiscal_year(filters.to_date, company=filters.company)[1]
		except Exception:
			filters.from_date = add_months(filters.to_date, -12)
	filters.group_by = filters.group_by if filters.group_by in GROUP_FIELDS else "Department"
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data, None, get_chart(data), get_summary(data)


def get_columns(filters):
	fieldname, options = GROUP_FIELDS[filters.group_by]
	return [
		{
			"label": _(filters.group_by),
			"fieldname": "group",
			"fieldtype": "Link",
			"options": options,
			"width": 180,
		},
		{"label": _("Employees"), "fieldname": "employees", "fieldtype": "Int", "width": 90},
		{"label": _("Salary Slips"), "fieldname": "slips", "fieldtype": "Int", "width": 90},
		{"label": _("Gross Pay"), "fieldname": "gross_pay", "fieldtype": "Currency", "width": 130},
		{
			"label": _("Total Deduction"),
			"fieldname": "total_deduction",
			"fieldtype": "Currency",
			"width": 130,
		},
		{"label": _("Net Pay"), "fieldname": "net_pay", "fieldtype": "Currency", "width": 130},
		{"label": _("Employer PF"), "fieldname": "employer_pf", "fieldtype": "Currency", "width": 120},
		{"label": _("Cost to Company"), "fieldname": "ctc", "fieldtype": "Currency", "width": 140},
	]


def get_data(filters):
	fieldname, _options = GROUP_FIELDS[filters.group_by]
	ss = frappe.qb.DocType("Salary Slip")
	emp = frappe.qb.DocType("Employee")
	group_field = ss[fieldname] if fieldname in SALARY_SLIP_GROUP_FIELDS else emp[fieldname]

	base = (
		frappe.qb.from_(ss)
		.inner_join(emp)
		.on(emp.name == ss.employee)
		.where(
			(ss.docstatus == 1)
			& (ss.company == filters.company)
			& (ss.start_date >= filters.from_date)
			& (ss.end_date <= filters.to_date)
		)
	)
	if filters.department:
		base = base.where(ss.department == filters.department)

	rows = (
		base.select(
			group_field.as_("group"),
			Count(ss.employee).distinct().as_("employees"),
			Count(ss.name).as_("slips"),
			Sum(ss.gross_pay).as_("gross_pay"),
			Sum(ss.total_deduction).as_("total_deduction"),
			Sum(ss.net_pay).as_("net_pay"),
		).groupby(group_field)
	).run(as_dict=True)
	if not rows:
		return []

	sd = frappe.qb.DocType("Salary Detail")
	pf_rows = (
		base.inner_join(sd)
		.on((sd.parent == ss.name) & (sd.parenttype == "Salary Slip"))
		.select(group_field.as_("group"), Sum(sd.amount).as_("employer_pf"))
		.where(sd.salary_component == EMPLOYER_PF_COMPONENT)
		.groupby(group_field)
	).run(as_dict=True)
	pf = {r.group: flt(r.employer_pf) for r in pf_rows}

	data = []
	for r in rows:
		r.group = r.group or None
		r.employer_pf = pf.get(r.group, 0.0)
		r.ctc = flt(r.gross_pay) + r.employer_pf
		data.append(r)
	data.sort(key=lambda r: r.ctc, reverse=True)
	return data


def get_chart(data):
	return {
		"data": {
			"labels": [r.group or _("Unassigned") for r in data],
			"datasets": [{"name": _("Cost to Company"), "values": [flt(r.ctc, 2) for r in data]}],
		},
		"type": "bar",
	}


def get_summary(data):
	return [
		{
			"value": sum(r.employees for r in data),
			"label": _("Employees"),
			"datatype": "Int",
			"indicator": "Blue",
		},
		{
			"value": sum(flt(r.gross_pay) for r in data),
			"label": _("Gross Pay"),
			"datatype": "Currency",
			"indicator": "Blue",
		},
		{
			"value": sum(r.employer_pf for r in data),
			"label": _("Employer PF"),
			"datatype": "Currency",
			"indicator": "Orange",
		},
		{
			"value": sum(r.ctc for r in data),
			"label": _("Cost to Company"),
			"datatype": "Currency",
			"indicator": "Green",
		},
	]

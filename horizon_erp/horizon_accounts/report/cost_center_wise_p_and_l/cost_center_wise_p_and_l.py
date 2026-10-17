# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Cost Center Wise P and L: income / expense accounts pivoted by cost centre (YTD) or by month."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe import _
from frappe.query_builder import Case, CustomFunction
from frappe.query_builder.functions import Sum
from frappe.utils import add_months, flt, formatdate, get_first_day, getdate, nowdate

UNALLOCATED = "unallocated"
DateFormat = CustomFunction("DATE_FORMAT", ["date", "format"])


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	if not filters.to_date:
		filters.to_date = nowdate()
	if not filters.from_date:
		if filters.fiscal_year:
			filters.from_date = frappe.db.get_value("Fiscal Year", filters.fiscal_year, "year_start_date")
		else:
			try:
				filters.from_date = get_fiscal_year(filters.to_date, company=filters.company)[1]
			except Exception:
				filters.from_date = get_first_day(add_months(filters.to_date, -11))
	filters.period = filters.period or "YTD"
	filters.branch_supported = frappe.db.has_column("GL Entry", "branch")

	if filters.period == "Monthly":
		pivot = get_month_columns(filters)
		rows = get_gl_rows(filters, by_month=True)
	else:
		pivot = get_cost_center_columns(filters)
		rows = get_gl_rows(filters, by_month=False)

	columns = get_columns(pivot)
	data = build_rows(rows, pivot)
	return columns, data, None, get_chart(data, pivot), get_summary(data)


def get_columns(pivot):
	columns = [{"label": _("Account"), "fieldname": "account", "fieldtype": "Data", "width": 260}]
	for key, label in pivot:
		columns.append({"label": label, "fieldname": key, "fieldtype": "Currency", "width": 130})
	columns.append({"label": _("Total"), "fieldname": "total", "fieldtype": "Currency", "width": 140})
	return columns


def get_cost_center_columns(filters):
	cost_centers = frappe.get_all(
		"Cost Center",
		filters={"company": filters.company, "is_group": 0},
		fields=["name", "cost_center_name"],
		order_by="lft",
	)
	pivot = [(frappe.scrub(cc.name), cc.name) for cc in cost_centers]
	pivot.append((UNALLOCATED, _("Unallocated")))
	return pivot


def get_month_columns(filters):
	pivot = []
	start = get_first_day(filters.from_date)
	end = getdate(filters.to_date)
	while start <= end:
		pivot.append((start.strftime("%Y_%m"), formatdate(start, "MMM yyyy")))
		start = get_first_day(add_months(start, 1))
	return pivot


def get_gl_rows(filters, by_month):
	gl = frappe.qb.DocType("GL Entry")
	acc = frappe.qb.DocType("Account")
	# income is credit-positive, expense is debit-positive
	amount = Case().when(acc.root_type == "Income", gl.credit - gl.debit).else_(gl.debit - gl.credit)
	q = (
		frappe.qb.from_(gl)
		.inner_join(acc)
		.on(acc.name == gl.account)
		.select(gl.account, acc.root_type, acc.account_name, Sum(amount).as_("amount"))
		.where(
			(gl.is_cancelled == 0)
			& (gl.company == filters.company)
			& (acc.root_type.isin(["Income", "Expense"]))
			& (gl.posting_date.between(filters.from_date, filters.to_date))
		)
		.groupby(gl.account)
	)
	if by_month:
		month_key = DateFormat(gl.posting_date, "%Y_%m")
		q = q.select(month_key.as_("month_key")).groupby(month_key)
		if filters.cost_center:
			lft, rgt = frappe.db.get_value("Cost Center", filters.cost_center, ["lft", "rgt"])
			cc = frappe.qb.DocType("Cost Center")
			names = (frappe.qb.from_(cc).select(cc.name).where((cc.lft >= lft) & (cc.rgt <= rgt))).run(
				pluck=True
			)
			q = q.where(gl.cost_center.isin(names))
	else:
		q = q.select(gl.cost_center).groupby(gl.cost_center)
	if filters.branch and filters.branch_supported:
		q = q.where(gl.branch == filters.branch)
	rows = q.run(as_dict=True)
	for r in rows:
		if by_month:
			r.key = r.month_key
		else:
			r.key = frappe.scrub(r.cost_center) if r.cost_center else UNALLOCATED
	return rows


def build_rows(rows, pivot):
	keys = [k for k, _l in pivot]
	accounts = {}
	for r in rows:
		acc = accounts.setdefault(
			r.account, frappe._dict(account=r.account, root_type=r.root_type, **dict.fromkeys(keys, 0.0))
		)
		if r.key in acc:
			acc[r.key] += flt(r.amount)
		else:  # cost centre outside the pivot (e.g. group / other company) -> unallocated
			acc[UNALLOCATED] = flt(acc.get(UNALLOCATED)) + flt(r.amount)

	def totals_row(label, members, indent, bold=True):
		row = frappe._dict(account=label, indent=indent, is_total=1 if bold else 0)
		for k in keys:
			row[k] = sum(flt(m.get(k)) for m in members)
		row.total = sum(flt(row[k]) for k in keys)
		return row

	data = []
	section_totals = {}
	for root_type in ("Income", "Expense"):
		members = sorted((a for a in accounts.values() if a.root_type == root_type), key=lambda a: a.account)
		data.append(frappe._dict(account=_(root_type), indent=0, is_header=1))
		for m in members:
			m.indent = 1
			m.total = sum(flt(m[k]) for k in keys)
			data.append(m)
		total = totals_row(_("Total {0}").format(_(root_type)), members, 0)
		section_totals[root_type] = total
		data.append(total)
		data.append(frappe._dict(account="", indent=0, is_blank=1))

	net = frappe._dict(account=_("Net Profit"), indent=0, is_total=1, is_net=1)
	for k in keys:
		net[k] = flt(section_totals["Income"][k]) - flt(section_totals["Expense"][k])
	net.total = flt(section_totals["Income"].total) - flt(section_totals["Expense"].total)
	data.append(net)
	return data


def get_chart(data, pivot):
	income = next((r for r in data if r.get("is_total") and r.account == _("Total Income")), None)
	expense = next((r for r in data if r.get("is_total") and r.account == _("Total Expense")), None)
	labels = [label for _k, label in pivot]
	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Income"), "values": [flt(income[k], 2) if income else 0 for k, _l in pivot]},
				{"name": _("Expense"), "values": [flt(expense[k], 2) if expense else 0 for k, _l in pivot]},
			],
		},
		"type": "bar",
		"colors": ["#29cd42", "#ff5858"],
	}


def get_summary(data):
	totals = {r.account: r.total for r in data if r.get("is_total")}
	income = flt(totals.get(_("Total Income")))
	expense = flt(totals.get(_("Total Expense")))
	net = income - expense
	return [
		{"value": income, "label": _("Income"), "datatype": "Currency", "indicator": "Green"},
		{"value": expense, "label": _("Expense"), "datatype": "Currency", "indicator": "Red"},
		{
			"value": net,
			"label": _("Net Profit"),
			"datatype": "Currency",
			"indicator": "Green" if net >= 0 else "Red",
		},
	]

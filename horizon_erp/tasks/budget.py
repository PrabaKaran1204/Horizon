# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Budget vs actual helpers shared by ``daily.budget_threshold_alerts`` and
``monthly.send_budget_report``.

Actuals are read from ``GL Entry`` (debit - credit, cancelled entries excluded) for the account
and the Cost Center subtree, mirroring ``erpnext.accounts.doctype.budget.budget.get_actual_expense``
but without that function's Budget-document coupling.
"""

import calendar

import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate


def get_fiscal_year_for(date, company=None):
	"""``(name, start, end)`` of the Fiscal Year containing ``date`` or ``None`` when there is none."""
	from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

	try:
		return get_fiscal_year(date, company=company, verbose=0)
	except FiscalYearError:
		return None


def get_cost_center_budgets(fiscal_year, company=None):
	"""Submitted Cost-Center budgets of ``fiscal_year`` flattened to one row per account.

	Each row: ``budget, cost_center, company, monthly_distribution, account, budget_amount``.
	"""
	filters = {"docstatus": 1, "fiscal_year": fiscal_year, "budget_against": "Cost Center"}
	if company:
		filters["company"] = company
	budgets = frappe.get_all(
		"Budget", filters=filters, fields=["name", "cost_center", "company", "monthly_distribution"]
	)
	if not budgets:
		return []

	by_name = {b.name: b for b in budgets}
	accounts = frappe.get_all(
		"Budget Account",
		filters={"parent": ["in", list(by_name)], "parenttype": "Budget"},
		fields=["parent", "account", "budget_amount"],
		order_by="parent, idx",
	)
	rows = []
	for acc in accounts:
		b = by_name[acc.parent]
		rows.append(
			frappe._dict(
				budget=b.name,
				cost_center=b.cost_center,
				company=b.company,
				monthly_distribution=b.monthly_distribution,
				account=acc.account,
				budget_amount=flt(acc.budget_amount),
			)
		)
	return rows


def get_actual_expense(account, cost_center, from_date, to_date, company=None):
	"""Sum of (debit - credit) GL Entries for ``account`` posted to ``cost_center`` or any of its
	descendants between the two dates (inclusive)."""
	lft, rgt = frappe.db.get_value("Cost Center", cost_center, ["lft", "rgt"]) or (None, None)
	gle = frappe.qb.DocType("GL Entry")
	cc = frappe.qb.DocType("Cost Center")

	query = (
		frappe.qb.from_(gle)
		.join(cc)
		.on(cc.name == gle.cost_center)
		.select(Sum(gle.debit - gle.credit))
		.where(gle.account == account)
		.where(gle.is_cancelled == 0)
		.where(gle.posting_date >= getdate(from_date))
		.where(gle.posting_date <= getdate(to_date))
	)
	if lft is not None:
		query = query.where((cc.lft >= lft) & (cc.rgt <= rgt))
	else:
		query = query.where(gle.cost_center == cost_center)
	if company:
		query = query.where(gle.company == company)

	result = query.run()
	return flt(result[0][0]) if result and result[0] else 0.0


def get_monthly_percentages(monthly_distribution):
	"""``{"January": 8.33, ...}`` from a Monthly Distribution, or ``{}`` when not set."""
	if not monthly_distribution:
		return {}
	rows = frappe.get_all(
		"Monthly Distribution Percentage",
		filters={"parent": monthly_distribution, "parenttype": "Monthly Distribution"},
		fields=["month", "percentage_allocation"],
	)
	return {r.month: flt(r.percentage_allocation) for r in rows}


def monthly_budget_share(annual_amount, month_date, percentages):
	"""Budget allotted to the month of ``month_date``: distribution % if given, else 1/12."""
	month_name = calendar.month_name[getdate(month_date).month]
	if percentages:
		return flt(annual_amount) * flt(percentages.get(month_name, 0)) / 100.0
	return flt(annual_amount) / 12.0


def budget_share_between(annual_amount, start_date, end_date, percentages):
	"""Budget for the whole months from ``start_date`` through the month of ``end_date``."""
	total = 0.0
	cursor = get_first_day(start_date)
	end = get_last_day(end_date)
	while cursor <= end:
		total += monthly_budget_share(annual_amount, cursor, percentages)
		cursor = get_first_day(add_months(cursor, 1))
	return total

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Monthly scheduler tasks (see ``scheduler_events`` in hooks.py).

See ``horizon_erp.tasks`` for the logging / alerting conventions shared by every job.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, formatdate, get_first_day, get_last_day, getdate, today

from horizon_erp.tasks import horizon_company, horizon_job, notify_users, users_with_roles
from horizon_erp.tasks.budget import (
	budget_share_between,
	get_actual_expense,
	get_cost_center_budgets,
	get_fiscal_year_for,
	get_monthly_percentages,
	monthly_budget_share,
)

OVERAGE_FLAG_PCT = 10.0  # variance % above which a row is flagged red
TOP_DRIVERS = 3


def get_budget_report_data(month_date=None, company=None):
	"""Budget vs actual for the month containing ``month_date`` (default: previous month).

	Returns ``{"month", "month_label", "fiscal_year", "currency", "rows": [...],
	"cost_centers": {cc: {"rows": [...], "drivers": [...], "totals": {...}}}}``.
	Each row: budget (monthly share via Monthly Distribution else 1/12), actual (GL), variance,
	variance_pct, flag ("red" overage > 10 %, "green" savings, ""), ytd_budget, ytd_actual,
	ytd_variance.
	"""
	company = company or horizon_company()
	month_start = get_first_day(month_date or add_months(today(), -1))
	month_end = get_last_day(month_start)
	fy = get_fiscal_year_for(month_start, company)
	data = {
		"month": str(month_start),
		"month_label": formatdate(month_start, "MMMM yyyy"),
		"company": company,
		"fiscal_year": fy[0] if fy else None,
		"currency": frappe.get_cached_value("Company", company, "default_currency") if company else "INR",
		"rows": [],
		"cost_centers": {},
	}
	if not fy:
		data["skipped"] = "no fiscal year for previous month"
		return data
	fy_start = fy[1]

	pct_cache = {}
	for b in get_cost_center_budgets(fy[0], company):
		if b.monthly_distribution not in pct_cache:
			pct_cache[b.monthly_distribution] = get_monthly_percentages(b.monthly_distribution)
		pct = pct_cache[b.monthly_distribution]

		budget = monthly_budget_share(b.budget_amount, month_start, pct)
		actual = get_actual_expense(b.account, b.cost_center, month_start, month_end, b.company)
		ytd_budget = budget_share_between(b.budget_amount, fy_start, month_end, pct)
		ytd_actual = get_actual_expense(b.account, b.cost_center, fy_start, month_end, b.company)
		variance = actual - budget
		variance_pct = (variance / budget * 100) if budget else (100.0 if actual else 0.0)
		row = {
			"budget_doc": b.budget,
			"cost_center": b.cost_center,
			"account": b.account,
			"annual_budget": b.budget_amount,
			"budget": round(budget, 2),
			"actual": round(actual, 2),
			"variance": round(variance, 2),
			"variance_pct": round(variance_pct, 1),
			"flag": "red" if variance_pct > OVERAGE_FLAG_PCT else ("green" if variance < 0 else ""),
			"ytd_budget": round(ytd_budget, 2),
			"ytd_actual": round(ytd_actual, 2),
			"ytd_variance": round(ytd_actual - ytd_budget, 2),
		}
		data["rows"].append(row)
		cc = data["cost_centers"].setdefault(
			b.cost_center,
			{
				"rows": [],
				"drivers": [],
				"totals": {"budget": 0, "actual": 0, "variance": 0, "ytd_budget": 0, "ytd_actual": 0},
			},
		)
		cc["rows"].append(row)
		for key in ("budget", "actual", "variance", "ytd_budget", "ytd_actual"):
			cc["totals"][key] = round(cc["totals"][key] + row[key], 2)

	for cc in data["cost_centers"].values():
		cc["drivers"] = sorted(cc["rows"], key=lambda r: abs(flt(r["variance"])), reverse=True)[:TOP_DRIVERS]
	return data


def render_budget_report(data):
	return frappe.render_template("horizon_erp/templates/emails/budget_report.html", {"d": data})


@horizon_job("send_budget_report")
def send_budget_report():
	"""1st of month 09:00 (cron). Email the previous month's budget vs actual (per cost centre and
	account, with YTD and the top 3 variance drivers per cost centre) to Department Heads and the
	Finance Director. Returns the report data (+ ``recipients``)."""
	data = get_budget_report_data()
	recipients = users_with_roles("Department Head", "Finance Director")
	data["recipients"] = recipients
	if not data["rows"]:
		data["skipped"] = data.get("skipped") or "no submitted cost center budgets for the fiscal year"
		return data

	html = render_budget_report(data)
	subject = _("Horizon Budget vs Actual - {0}").format(data["month_label"])
	notify_users(recipients, subject, html, doctype="Budget", docname=None, email=True)
	return data


@frappe.whitelist()
def preview_budget_report(month_date=None):
	"""Rendered budget report HTML for a manual check (System Manager only)."""
	frappe.only_for("System Manager")
	return render_budget_report(get_budget_report_data(getdate(month_date) if month_date else None))

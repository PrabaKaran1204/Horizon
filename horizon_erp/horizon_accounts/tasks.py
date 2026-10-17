# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Accounts scheduler jobs: daily budget threshold alerts and the monthly budget report (09:00 on
the 1st).

Scheduled from ``scheduler_events`` in hooks.py. Logging / alerting conventions shared by every job
(``@horizon_job``, Error Log + System Manager alert, retry marker) live in
``horizon_erp.horizon_core.jobs``.
"""

import frappe
from frappe import _
from frappe.utils import (
	add_months,
	cint,
	flt,
	fmt_money,
	formatdate,
	get_first_day,
	get_last_day,
	get_url_to_form,
	getdate,
	today,
)

from horizon_erp.horizon_accounts.budget import (
	budget_share_between,
	get_actual_expense,
	get_cost_center_budgets,
	get_fiscal_year_for,
	get_monthly_percentages,
	monthly_budget_share,
)
from horizon_erp.horizon_core.jobs import (
	horizon_company,
	horizon_job,
	notify_users,
	once_per_day,
	users_with_roles,
)

OVERAGE_FLAG_PCT = 10.0  # variance % above which a row is flagged red
FORECAST_FLAG_PCT = 10.0  # run-rate forecast above annual budget by more than this -> flagged
TOP_DRIVERS = 3
MONTHS_PER_YEAR = 12
BUDGET_ALERT_RATIO = 0.9


def months_elapsed(fy_start, month_start):
	"""Months of the fiscal year elapsed up to and including the month starting ``month_start``."""
	fy_start, month_start = getdate(fy_start), getdate(month_start)
	return max((month_start.year - fy_start.year) * 12 + month_start.month - fy_start.month + 1, 1)


def compute_forecast(annual_budget, ytd_actual, elapsed):
	"""Straight run-rate year-end forecast: YTD actual / months elapsed x 12.

	Returns ``run_rate_forecast``, ``forecast_variance`` (annual budget - forecast; negative =
	overspend), ``forecast_variance_pct`` and ``forecast_flag`` ("red" when the forecast exceeds the
	budget by more than ``FORECAST_FLAG_PCT`` %).
	"""
	annual_budget, ytd_actual = flt(annual_budget), flt(ytd_actual)
	elapsed = max(int(elapsed or 0), 1)
	forecast = ytd_actual / elapsed * MONTHS_PER_YEAR
	variance = annual_budget - forecast
	variance_pct = (variance / annual_budget * 100) if annual_budget else (-100.0 if forecast else 0.0)
	over_pct = -variance_pct
	return {
		"run_rate_forecast": round(forecast, 2),
		"forecast_variance": round(variance, 2),
		"forecast_variance_pct": round(variance_pct, 1),
		"forecast_flag": "red" if over_pct > FORECAST_FLAG_PCT else "",
	}


def get_budget_report_data(month_date=None, company=None):
	"""Budget vs actual for the month containing ``month_date`` (default: previous month).

	Returns ``{"month", "month_label", "fiscal_year", "currency", "rows": [...],
	"cost_centers": {cc: {"rows": [...], "drivers": [...], "totals": {...}}}}``.
	Each row: budget (monthly share via Monthly Distribution else 1/12), actual (GL), variance,
	variance_pct, flag ("red" overage > 10 %, "green" savings, ""), ytd_budget, ytd_actual,
	ytd_variance, plus the year-end forecast: ytd_months_elapsed, run_rate_forecast
	(YTD actual / months elapsed x 12), forecast_variance (annual budget - forecast),
	forecast_variance_pct and forecast_flag ("red" when the forecast exceeds budget by > 10 %).
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
	elapsed = months_elapsed(fy_start, month_start)
	data["ytd_months_elapsed"] = elapsed

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
			"ytd_months_elapsed": elapsed,
			**compute_forecast(b.budget_amount, ytd_actual, elapsed),
		}
		data["rows"].append(row)
		cc = data["cost_centers"].setdefault(
			b.cost_center,
			{
				"rows": [],
				"drivers": [],
				"totals": {
					"budget": 0,
					"actual": 0,
					"variance": 0,
					"ytd_budget": 0,
					"ytd_actual": 0,
					"annual_budget": 0,
					"run_rate_forecast": 0,
					"forecast_variance": 0,
				},
			},
		)
		cc["rows"].append(row)
		for key in (
			"budget",
			"actual",
			"variance",
			"ytd_budget",
			"ytd_actual",
			"annual_budget",
			"run_rate_forecast",
			"forecast_variance",
		):
			cc["totals"][key] = round(cc["totals"][key] + flt(row[key]), 2)

	for cc in data["cost_centers"].values():
		cc["drivers"] = sorted(cc["rows"], key=lambda r: abs(flt(r["variance"])), reverse=True)[:TOP_DRIVERS]
	return data


def render_budget_report(data):
	return frappe.render_template("horizon_erp/templates/emails/budget_report.html", {"d": data})


@horizon_job("send_budget_report")
def send_budget_report():
	"""1st of month 09:00 (cron). Email the previous month's budget vs actual (per cost centre and
	account, with YTD, the run-rate year-end forecast and the top 3 variance drivers per cost
	centre) to Department Heads and the Finance Director, with the report attached as PDF (HTML
	only when wkhtmltopdf is unavailable). Returns the report data (+ ``recipients``)."""
	data = get_budget_report_data()
	recipients = users_with_roles("Department Head", "Finance Director")
	data["recipients"] = recipients
	if not data["rows"]:
		data["skipped"] = data.get("skipped") or "no submitted cost center budgets for the fiscal year"
		return data

	html = render_budget_report(data)
	attachments = None
	try:
		from frappe.utils.pdf import get_pdf

		attachments = [{"fname": f"budget-report-{data['month']}.pdf", "fcontent": get_pdf(html)}]
	except Exception as exc:
		# same fallback as the daily summary: send the HTML body alone when wkhtmltopdf is missing
		data["pdf_error"] = str(exc)[:200]
		frappe.logger("horizon_jobs").warning(f"send_budget_report: PDF skipped ({exc!r})")

	subject = _("Horizon Budget vs Actual - {0}").format(data["month_label"])
	notify_users(
		recipients, subject, html, doctype="Budget", docname=None, email=True, attachments=attachments
	)
	return data


@frappe.whitelist()
def preview_budget_report(month_date=None):
	"""Rendered budget report HTML for a manual check (System Manager only)."""
	frappe.only_for("System Manager")
	return render_budget_report(get_budget_report_data(getdate(month_date) if month_date else None))


# ---------------------------------------------------------------------------
# Budget threshold alerts
# ---------------------------------------------------------------------------
@horizon_job("budget_threshold_alerts")
def budget_threshold_alerts():
	"""Daily. For every submitted Cost Center Budget of the current Fiscal Year, compare GL actuals
	(debit - credit, FY to date) per account with the annual budget; at >= ``BUDGET_ALERT_RATIO``
	notify the cost centre owners + Finance Director once per day per (budget, account).

	Cost Center has no owner field in ERPNext and none was added by this app, so "owner" is
	approximated by all users holding the Department Head role. Returns ``{"alerts": [...]}``.
	"""
	out = {"alerts": [], "checked": 0}
	company = horizon_company()
	fy = get_fiscal_year_for(today(), company)
	if not fy:
		out["skipped"] = "no fiscal year for today"
		return out
	fy_name, fy_start, fy_end = fy[0], fy[1], fy[2]

	recipients = users_with_roles("Department Head", "Finance Director")
	for row in get_cost_center_budgets(fy_name, company):
		out["checked"] += 1
		if row.budget_amount <= 0:
			continue
		actual = get_actual_expense(
			row.account, row.cost_center, fy_start, min(getdate(today()), fy_end), row.company
		)
		ratio = actual / row.budget_amount
		if ratio < BUDGET_ALERT_RATIO:
			continue

		alert = {
			"budget": row.budget,
			"cost_center": row.cost_center,
			"account": row.account,
			"budget_amount": row.budget_amount,
			"actual": actual,
			"ratio": round(ratio, 4),
			"exceeded": ratio >= 1,
		}
		out["alerts"].append(alert)
		if not once_per_day("budget_alert", f"{row.budget}:{row.account}"):
			continue

		currency = frappe.get_cached_value("Company", row.company, "default_currency")
		subject = _("Budget {0}: {1} at {2}% of {3} budget").format(
			"exceeded" if ratio >= 1 else "alert", row.cost_center, cint(ratio * 100), fy_name
		)
		message = _(
			"Cost Center <b>{0}</b>, account <b>{1}</b>: actual {2} against budget {3} ({4}%). "
			"Budget <a href='{5}'>{6}</a>."
		).format(
			row.cost_center,
			row.account,
			fmt_money(actual, currency=currency),
			fmt_money(row.budget_amount, currency=currency),
			cint(ratio * 100),
			get_url_to_form("Budget", row.budget),
			row.budget,
		)
		notify_users(recipients, subject, message, doctype="Budget", docname=row.budget)
	return out

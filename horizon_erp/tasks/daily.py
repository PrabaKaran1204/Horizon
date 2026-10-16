# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Daily scheduler tasks (see ``scheduler_events`` in hooks.py).

See ``horizon_erp.tasks`` for the logging / alerting conventions shared by every job.
"""

import math

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Min, Sum
from frappe.utils import (
	add_days,
	cint,
	flt,
	fmt_money,
	get_url_to_form,
	getdate,
	now_datetime,
	nowdate,
	today,
)

from horizon_erp.tasks import (
	add_info_comment,
	first_existing_warehouse,
	horizon_company,
	horizon_job,
	notify_users,
	once_per_day,
	safe_sendmail,
	users_with_roles,
)
from horizon_erp.tasks.budget import get_actual_expense, get_cost_center_budgets, get_fiscal_year_for

# ---------------------------------------------------------------------------
# Reorder level parameters
# ---------------------------------------------------------------------------
USAGE_WINDOW_DAYS = 90
MIN_HISTORY_DAYS = 60  # first outgoing movement must be at least this old before levels are touched
MIN_OUTGOING_MOVEMENTS = 3  # and at least this many outgoing movements must exist
DEFAULT_LEAD_TIME_DAYS = 7
SAFETY_FACTOR_BY_CRITICALITY = {"A": 0.5, "B": 0.3, "C": 0.1}
DEFAULT_SAFETY_FACTOR = 0.3
# Seasonal index applied to average daily usage for "Seasonal Q4" items during Oct-Dec.
# A constant uplift (not derived from history) is deliberate: Horizon's seasonal lines have
# fewer than two years of history, so a fitted index would be noise. Revisit once FY27 closes.
SEASONAL_Q4_INDEX = 1.5
SEASONAL_Q4_MONTHS = (10, 11, 12)
FALLBACK_PURCHASE_WAREHOUSES = ("HQ Raw Materials - HML",)

QUALITY_DEADLINE_HORIZON_DAYS = 3
AUDIT_SCORE_THRESHOLD = 70
BUDGET_ALERT_RATIO = 0.9

try:  # align with the business-rule developer's central config when it is present
	from horizon_erp.horizon_operations import config as _ops_config

	AUDIT_SCORE_THRESHOLD = getattr(_ops_config, "AUDIT_FAIL_SCORE", AUDIT_SCORE_THRESHOLD)
	_raw_wh = getattr(_ops_config, "RAW_MATERIAL_WAREHOUSE_NAME", None)
	if _raw_wh:
		FALLBACK_PURCHASE_WAREHOUSES = (f"{_raw_wh} - HML", *FALLBACK_PURCHASE_WAREHOUSES)
except ImportError:
	pass


# ---------------------------------------------------------------------------
# 3. Reorder level recompute
# ---------------------------------------------------------------------------
@horizon_job("recompute_reorder_levels")
def recompute_reorder_levels():
	"""Daily recompute of ``Item Reorder`` levels per stock item.

	avg_daily_usage = outgoing qty (SLE actual_qty < 0, Stock Reconciliations excluded) over the
	last ``USAGE_WINDOW_DAYS`` / window. lead = Item.lead_time_days or 7. factor = criticality
	A 0.5 / B 0.3 / C 0.1 (written back to ``Item.safety_stock_factor``). Seasonal Q4 items get
	usage x ``SEASONAL_Q4_INDEX`` in Oct-Dec.

	reorder_level = max(ceil(usage x lead x (1 + factor)), Item.safety_stock)
	reorder_qty   = max(existing reorder_qty, ceil(usage x lead x 2))

	Guard rails (QA DEF-08 / DEF-09):

	* An item is recomputed only with enough history: its first outgoing movement is at least
	  ``MIN_HISTORY_DAYS`` old **and** it has at least ``MIN_OUTGOING_MOVEMENTS`` outgoing
	  movements. Otherwise the manually maintained level stays (``skipped_insufficient_history``).
	* Rows are upserted **per warehouse**: an existing row keeps its ``material_request_type``
	  (a "Manufacture" row of a make-to-stock spare stays a Manufacture row) and a second row for
	  the same warehouse is never added (ERPNext's Item validation forbids it).
	* New rows are only inserted for purchase items (``is_purchase_item``), as "Purchase". Items
	  that are made, not bought, get a reorder row only when a planner creates it by hand
	  (make-to-order vs make-to-stock is a planning decision, ADR-4) - ``skipped_not_purchasable``.
	* Items with zero usage in the window keep their manual level (``skipped_no_usage``).

	Warehouse = Item Default.default_warehouse for the Horizon company, falling back to
	"HQ Raw Materials - HML" when that exists. Rows are written with ``frappe.db.set_value`` /
	child-row ``insert`` instead of saving every Item (hundreds of Item saves would re-run every
	Item validation and take minutes); the Item document cache is cleared afterwards.
	"""
	out = {
		"updated": 0,
		"inserted": 0,
		"skipped_no_usage": 0,
		"skipped_no_warehouse": 0,
		"skipped_insufficient_history": 0,
		"skipped_not_purchasable": 0,
		"samples": [],
	}
	company = horizon_company()
	if not company:
		out["skipped"] = "no company"
		return out

	items = frappe.get_all(
		"Item",
		filters={"is_stock_item": 1, "disabled": 0, "has_variants": 0, "is_fixed_asset": 0},
		fields=[
			"name",
			"lead_time_days",
			"criticality",
			"demand_pattern",
			"safety_stock_factor",
			"safety_stock",
			"is_purchase_item",
		],
	)
	if not items:
		return out
	item_names = [i.name for i in items]

	defaults = {
		d.parent: d.default_warehouse
		for d in frappe.get_all(
			"Item Default",
			filters={"parenttype": "Item", "parent": ["in", item_names], "company": company},
			fields=["parent", "default_warehouse"],
		)
		if d.default_warehouse
	}
	fallback_wh = first_existing_warehouse(*FALLBACK_PURCHASE_WAREHOUSES)
	usage = _outgoing_qty_by_item(item_names, company)
	history = _outgoing_history_by_item(item_names, company)
	seasonal_now = getdate(today()).month in SEASONAL_Q4_MONTHS
	history_cutoff = getdate(add_days(today(), -MIN_HISTORY_DAYS))

	existing = {}
	for row in frappe.get_all(
		"Item Reorder",
		filters={"parent": ["in", item_names], "parenttype": "Item"},
		fields=[
			"name",
			"parent",
			"warehouse",
			"warehouse_reorder_level",
			"warehouse_reorder_qty",
			"material_request_type",
		],
		order_by="idx asc",
	):
		existing.setdefault((row.parent, row.warehouse), row)  # first row per warehouse wins

	for item in items:
		warehouse = defaults.get(item.name) or fallback_wh
		if not warehouse:
			out["skipped_no_warehouse"] += 1
			continue

		factor = SAFETY_FACTOR_BY_CRITICALITY.get(item.criticality, DEFAULT_SAFETY_FACTOR)
		if flt(item.safety_stock_factor) != factor:
			frappe.db.set_value("Item", item.name, "safety_stock_factor", factor, update_modified=False)

		daily_usage = flt(usage.get(item.name)) / USAGE_WINDOW_DAYS
		if daily_usage <= 0:
			out["skipped_no_usage"] += 1
			continue
		hist = history.get(item.name)
		if (
			not hist
			or cint(hist.movements) < MIN_OUTGOING_MOVEMENTS
			or getdate(hist.first_date) > history_cutoff
		):
			out["skipped_insufficient_history"] += 1
			continue
		if item.demand_pattern == "Seasonal Q4" and seasonal_now:
			daily_usage *= SEASONAL_Q4_INDEX

		lead = cint(item.lead_time_days) or DEFAULT_LEAD_TIME_DAYS
		level = math.ceil(daily_usage * lead + daily_usage * lead * factor)
		if flt(item.safety_stock) > 0:
			level = max(level, math.ceil(flt(item.safety_stock)))
		row = existing.get((item.name, warehouse))
		qty = max(flt(row.warehouse_reorder_qty) if row else 0, math.ceil(daily_usage * lead * 2))

		if row:
			frappe.db.set_value(
				"Item Reorder",
				row.name,
				{"warehouse_reorder_level": level, "warehouse_reorder_qty": qty},
				update_modified=False,
			)
			out["updated"] += 1
		elif not cint(item.is_purchase_item):
			out["skipped_not_purchasable"] += 1
			continue
		else:
			frappe.get_doc(
				{
					"doctype": "Item Reorder",
					"parenttype": "Item",
					"parentfield": "reorder_levels",
					"parent": item.name,
					"warehouse_group": frappe.db.get_value("Warehouse", warehouse, "parent_warehouse"),
					"warehouse": warehouse,
					"warehouse_reorder_level": level,
					"warehouse_reorder_qty": qty,
					"material_request_type": "Purchase",
				}
			).insert(ignore_permissions=True)
			out["inserted"] += 1
		frappe.clear_document_cache("Item", item.name)

		if len(out["samples"]) < 10:
			out["samples"].append(
				{
					"item_code": item.name,
					"warehouse": warehouse,
					"material_request_type": row.material_request_type if row else "Purchase",
					"avg_daily_usage": round(daily_usage, 3),
					"lead_days": lead,
					"factor": factor,
					"reorder_level": level,
					"reorder_qty": qty,
				}
			)
	return out


def _outgoing_sle_query(item_names, company):
	sle = frappe.qb.DocType("Stock Ledger Entry")
	wh = frappe.qb.DocType("Warehouse")
	return (
		frappe.qb.from_(sle)
		.join(wh)
		.on(wh.name == sle.warehouse)
		.where(sle.item_code.isin(item_names))
		.where(sle.is_cancelled == 0)
		.where(sle.actual_qty < 0)
		.where(sle.voucher_type != "Stock Reconciliation")
		.where(wh.company == company)
		.groupby(sle.item_code)
	), sle


def _outgoing_qty_by_item(item_names, company):
	query, sle = _outgoing_sle_query(item_names, company)
	rows = (
		query.select(sle.item_code, Sum(sle.actual_qty).as_("qty")).where(
			sle.posting_date > add_days(today(), -USAGE_WINDOW_DAYS)
		)
	).run(as_dict=True)
	return {r.item_code: abs(flt(r.qty)) for r in rows}


def _outgoing_history_by_item(item_names, company):
	"""``{item_code: {"first_date", "movements"}}`` over the whole ledger (not just the window)."""
	query, sle = _outgoing_sle_query(item_names, company)
	rows = query.select(
		sle.item_code, Min(sle.posting_date).as_("first_date"), Count(sle.name).as_("movements")
	).run(as_dict=True)
	return {r.item_code: r for r in rows}


# ---------------------------------------------------------------------------
# 4. Quality vs delivery deadline conflicts
# ---------------------------------------------------------------------------
@horizon_job("detect_quality_deadline_conflicts")
def detect_quality_deadline_conflicts():
	"""Daily. Flags submitted Sales Orders due within ``QUALITY_DEADLINE_HORIZON_DAYS`` (or overdue),
	not fully delivered, whose Work Orders are not Completed, or have an open Production Audit
	below ``AUDIT_SCORE_THRESHOLD``, or a Rejected Quality Inspection (on the WO's Stock Entries /
	Job Cards), and for which no submitted Shipment Decision exists yet. One Notification Log +
	email per SO per day to Sales Manager, Operations Head and Quality Manager.

	Returns ``{"flagged": [{"sales_order", "customer", "delivery_date", "conflicts": [...]}, ...]}``.
	"""
	out = {"flagged": [], "checked": 0}
	horizon = add_days(today(), QUALITY_DEADLINE_HORIZON_DAYS)
	sales_orders = frappe.get_all(
		"Sales Order",
		filters={
			"docstatus": 1,
			"status": ["not in", ["Completed", "Closed", "Cancelled"]],
			"per_delivered": ["<", 100],
			"delivery_date": ["<=", horizon],
		},
		fields=["name", "customer", "delivery_date", "per_delivered", "grand_total", "currency"],
		limit=500,
	)
	recipients = users_with_roles("Sales Manager", "Operations Head", "Quality Manager")

	for so in sales_orders:
		out["checked"] += 1
		if frappe.db.exists("Shipment Decision", {"sales_order": so.name, "docstatus": 1}):
			continue
		conflicts = _quality_conflicts_for(so.name)
		if not conflicts:
			continue

		entry = {
			"sales_order": so.name,
			"customer": so.customer,
			"delivery_date": str(so.delivery_date),
			"per_delivered": flt(so.per_delivered),
			"conflicts": conflicts,
		}
		out["flagged"].append(entry)
		if not once_per_day("quality_conflict", so.name):
			continue

		subject = _("Delivery at risk: {0} ({1}) due {2}").format(so.name, so.customer, so.delivery_date)
		message = _(
			"Sales Order <a href='{0}'>{1}</a> for {2} is due on {3} ({4}% delivered) and has open "
			"quality / production conflicts:<ul>{5}</ul>Please record a Shipment Decision."
		).format(
			get_url_to_form("Sales Order", so.name),
			so.name,
			so.customer,
			so.delivery_date,
			cint(so.per_delivered),
			"".join(f"<li>{frappe.utils.escape_html(c)}</li>" for c in conflicts),
		)
		notify_users(recipients, subject, message, doctype="Sales Order", docname=so.name)
	return out


def _quality_conflicts_for(sales_order):
	work_orders = frappe.get_all(
		"Work Order",
		filters={"sales_order": sales_order, "docstatus": ["<", 2]},
		fields=["name", "status", "production_item"],
	)
	if not work_orders:
		return []
	wo_names = [w.name for w in work_orders]
	conflicts = [
		_("Work Order {0} ({1}) is {2}").format(w.name, w.production_item, w.status)
		for w in work_orders
		if w.status not in ("Completed",)
	]

	for audit in frappe.get_all(
		"Production Audit",
		filters={
			"work_order": ["in", wo_names],
			"docstatus": ["<", 2],
			"audit_score": ["<", AUDIT_SCORE_THRESHOLD],
			"status": ["!=", "Action Closed"],
		},
		fields=["name", "work_order", "audit_score"],
	):
		conflicts.append(
			_("Production Audit {0} on {1} scored {2}").format(
				audit.name, audit.work_order, audit.audit_score
			)
		)

	refs = frappe.get_all(
		"Stock Entry", filters={"work_order": ["in", wo_names], "docstatus": 1}, pluck="name"
	)
	refs += frappe.get_all(
		"Job Card", filters={"work_order": ["in", wo_names], "docstatus": ["<", 2]}, pluck="name"
	)
	if refs:
		for qi in frappe.get_all(
			"Quality Inspection",
			filters={"reference_name": ["in", refs], "status": "Rejected", "docstatus": 1},
			fields=["name", "item_code", "reference_name"],
		):
			conflicts.append(
				_("Quality Inspection {0} rejected {1} ({2})").format(
					qi.name, qi.item_code, qi.reference_name
				)
			)
	return conflicts


# ---------------------------------------------------------------------------
# 5. Budget threshold alerts
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


# ---------------------------------------------------------------------------
# 6. Daily summary (18:00)
# ---------------------------------------------------------------------------
def get_daily_summary_metrics(date=None):
	"""Today's operational KPIs as a plain dict (also used by ``preview_daily_summary``)."""
	date = getdate(date or today())
	company = horizon_company()
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else "INR"

	def _agg(doctype, filters, sum_field=None):
		rows = frappe.get_all(
			doctype,
			filters=filters,
			fields=["count(name) as n", f"sum({sum_field}) as total"] if sum_field else ["count(name) as n"],
		)
		row = rows[0] if rows else {}
		return cint(row.get("n")), flt(row.get("total"))

	so_count, so_total = _agg("Sales Order", {"docstatus": 1, "transaction_date": date}, "grand_total")
	qtn_count, qtn_total = _agg("Quotation", {"docstatus": 1, "transaction_date": date}, "grand_total")
	dn_count, _dn = _agg("Delivery Note", {"docstatus": 1, "posting_date": date})
	si_count, si_total = _agg("Sales Invoice", {"docstatus": 1, "posting_date": date}, "grand_total")
	wo_count, wo_qty = _agg(
		"Work Order",
		{
			"status": "Completed",
			"docstatus": 1,
			"modified": ["between", [f"{date} 00:00:00", f"{date} 23:59:59"]],
		},
		"produced_qty",
	)
	po_filters = {"docstatus": 0}
	if frappe.db.has_column("Purchase Order", "workflow_state"):
		po_filters["workflow_state"] = ["like", "Pending%"]
	po_pending, _po = _agg("Purchase Order", po_filters)
	audits_low, _a = _agg(
		"Production Audit",
		{"docstatus": ["<", 2], "audit_date": date, "audit_score": ["<", AUDIT_SCORE_THRESHOLD]},
	)

	bin_ = frappe.qb.DocType("Bin")
	reorder = frappe.qb.DocType("Item Reorder")
	low_stock = (
		frappe.qb.from_(bin_)
		.join(reorder)
		.on(
			(reorder.parent == bin_.item_code)
			& (reorder.parenttype == "Item")
			& (reorder.warehouse == bin_.warehouse)
		)
		.select(bin_.item_code, bin_.warehouse, bin_.actual_qty, reorder.warehouse_reorder_level)
		.where(bin_.actual_qty < reorder.warehouse_reorder_level)
		.where(reorder.warehouse_reorder_level > 0)
	).run(as_dict=True)

	return {
		"date": str(date),
		"company": company,
		"currency": currency,
		"sales_orders": {"count": so_count, "total": so_total},
		"quotations_sent": {"count": qtn_count, "total": qtn_total},
		"delivery_notes": {"count": dn_count},
		"sales_invoices": {"count": si_count, "total": si_total},
		"work_orders_completed": {"count": wo_count, "produced_qty": wo_qty},
		"purchase_orders_pending_approval": po_pending,
		"production_audits_below_70": audits_low,
		"low_stock": {"count": len(low_stock), "items": low_stock[:20]},
		"generated_at": str(now_datetime()),
	}


def render_daily_summary(metrics):
	return frappe.render_template("horizon_erp/templates/emails/daily_summary.html", {"m": metrics})


@horizon_job("send_daily_summary")
def send_daily_summary():
	"""18:00 daily (cron). Compute today's KPIs, render ``templates/emails/daily_summary.html``,
	attach it as PDF (skipped with a warning when wkhtmltopdf is unavailable) and email it to
	Finance Director and Operations Head users. Returns the metrics dict (+ ``recipients``)."""
	metrics = get_daily_summary_metrics()
	html = render_daily_summary(metrics)
	attachments = None
	try:
		from frappe.utils.pdf import get_pdf

		attachments = [{"fname": f"daily-summary-{metrics['date']}.pdf", "fcontent": get_pdf(html)}]
	except Exception as exc:
		metrics["pdf_error"] = str(exc)[:200]
		frappe.logger("horizon_jobs").warning(f"send_daily_summary: PDF skipped ({exc!r})")

	recipients = users_with_roles("Finance Director", "Operations Head")
	metrics["recipients"] = recipients
	if recipients and not safe_sendmail(
		"Horizon daily summary: email failed",
		recipients=recipients,
		subject=_("Horizon Daily Summary {0}").format(metrics["date"]),
		message=html,
		attachments=attachments,
	):
		metrics["email_error"] = True
	return metrics


@frappe.whitelist()
def preview_daily_summary(date=None):
	"""Return the rendered daily summary HTML for a manual check (System Manager only)."""
	frappe.only_for("System Manager")
	return render_daily_summary(get_daily_summary_metrics(date))

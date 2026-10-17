# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Stock scheduler jobs: hourly reorder + stock-accuracy check, daily reorder-level recompute.

Scheduled from ``scheduler_events`` in hooks.py. Logging / alerting conventions shared by every job
(``@horizon_job``, Error Log + System Manager alert, retry marker) live in
``horizon_erp.horizon_core.jobs``.
"""

import math

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Max, Min, Sum
from frappe.utils import (
	add_days,
	add_to_date,
	cint,
	flt,
	getdate,
	now_datetime,
	today,
)

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.jobs import (
	add_info_comment,
	first_existing_warehouse,
	horizon_company,
	horizon_job,
)

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
FALLBACK_PURCHASE_WAREHOUSES = (f"{config.RAW_MATERIAL_WAREHOUSE_NAME} - HML",)

STOCK_ACCURACY_TOLERANCE = 0.001  # qty units; Bin vs latest SLE qty_after_transaction
COUNT_VARIANCE_PCT = 2.0  # Stock Reconciliation qty vs current_qty


# ---------------------------------------------------------------------------
# Reorder + stock accuracy
# ---------------------------------------------------------------------------
@horizon_job("reorder_and_accuracy_check")
def reorder_and_accuracy_check():
	"""Hourly.

	(a) Run ERPNext's own reorder logic (``erpnext.stock.reorder_item.reorder_item``), which
	    respects Stock Settings ``auto_indent`` and the ``Item Reorder`` rows maintained by
	    ``daily.recompute_reorder_levels``; report Material Requests created in the last hour.
	(b) Stock accuracy: every Bin whose ``actual_qty`` differs from the ``qty_after_transaction`` of
	    its latest non-cancelled Stock Ledger Entry is flagged with an Info comment on the Item
	    (once per day), and so is
	    every item on a Stock Reconciliation submitted today whose counted qty deviates more than
	    ``COUNT_VARIANCE_PCT`` from the system qty ("physical count variance").

	Returns ``{"material_requests": n, "bin_mismatches": [...], "count_variances": [...]}``.
	"""
	out = {"material_requests": 0, "bin_mismatches": [], "count_variances": [], "reorder_error": None}

	try:
		from erpnext.stock.reorder_item import reorder_item

		reorder_item()
	except Exception as exc:
		# reorder failures (e.g. missing default supplier) must not block the accuracy check
		out["reorder_error"] = str(exc)[:200]
		frappe.log_error(title="Horizon hourly: ERPNext reorder_item failed")

	out["material_requests"] = frappe.db.count(
		"Material Request", {"creation": [">=", add_to_date(now_datetime(), hours=-1)]}
	)

	out["bin_mismatches"] = _flag_bin_mismatches()
	out["count_variances"] = _flag_count_variances()
	return out


def _flag_bin_mismatches():
	"""Bins whose ``actual_qty`` differs from the latest non-cancelled Stock Ledger Entry's
	``qty_after_transaction`` for the same item / warehouse.

	Comparing with ``SUM(actual_qty)`` is wrong: Stock Reconciliation entries (opening stock,
	counts) carry ``actual_qty`` 0 and only set ``qty_after_transaction``, so every reconciled bin
	would be a false positive. "Latest" = highest ``posting_datetime``, ties broken by ``creation``
	(the order ERPNext itself uses for the ledger).
	"""
	latest = _latest_sle_qty_by_bin()
	bins = frappe.get_all(
		"Bin",
		fields=["item_code", "warehouse", "actual_qty"],
		filters={"actual_qty": ["!=", 0]} if not latest else {},
		limit=5000,
	)
	flagged = []
	for b in bins:
		sle_qty = flt(latest.get((b.item_code, b.warehouse)))
		if abs(flt(b.actual_qty) - sle_qty) <= STOCK_ACCURACY_TOLERANCE:
			continue
		flagged.append(
			{
				"item_code": b.item_code,
				"warehouse": b.warehouse,
				"bin_qty": flt(b.actual_qty),
				"sle_qty": sle_qty,
			}
		)
		add_info_comment(
			"Item",
			b.item_code,
			_("Stock accuracy flag: Bin {0} vs SLE {1} in {2}").format(
				flt(b.actual_qty), sle_qty, b.warehouse
			),
			dedupe_prefix="Stock accuracy flag",
		)
		if len(flagged) >= 500:
			break
	return flagged


def _latest_sle_qty_by_bin():
	"""``{(item_code, warehouse): qty_after_transaction}`` of the latest non-cancelled SLE."""
	sle = frappe.qb.DocType("Stock Ledger Entry")
	last = (
		frappe.qb.from_(sle)
		.select(sle.item_code, sle.warehouse, Max(sle.posting_datetime).as_("posting_datetime"))
		.where(sle.is_cancelled == 0)
		.groupby(sle.item_code, sle.warehouse)
	).as_("last")
	rows = (
		frappe.qb.from_(sle)
		.join(last)
		.on(
			(last.item_code == sle.item_code)
			& (last.warehouse == sle.warehouse)
			& (last.posting_datetime == sle.posting_datetime)
		)
		.select(sle.item_code, sle.warehouse, sle.qty_after_transaction)
		.where(sle.is_cancelled == 0)
		.orderby(sle.creation)
	).run(as_dict=True)
	# several entries can share a posting_datetime; the last created wins
	return {(r.item_code, r.warehouse): flt(r.qty_after_transaction) for r in rows}


def _flag_count_variances():
	sr = frappe.qb.DocType("Stock Reconciliation")
	sri = frappe.qb.DocType("Stock Reconciliation Item")
	rows = (
		frappe.qb.from_(sri)
		.join(sr)
		.on(sri.parent == sr.name)
		.select(sr.name.as_("reconciliation"), sri.item_code, sri.warehouse, sri.qty, sri.current_qty)
		.where((sr.docstatus == 1) & (sr.posting_date == today()))
	).run(as_dict=True)

	flagged = []
	for row in rows:
		counted, system = flt(row.qty), flt(row.current_qty)
		if system:
			variance_pct = abs(counted - system) / abs(system) * 100
		else:
			variance_pct = 100.0 if counted else 0.0
		if variance_pct <= COUNT_VARIANCE_PCT:
			continue
		flagged.append(
			{
				"reconciliation": row.reconciliation,
				"item_code": row.item_code,
				"warehouse": row.warehouse,
				"system_qty": system,
				"counted_qty": counted,
				"variance_pct": round(variance_pct, 2),
			}
		)
		add_info_comment(
			"Item",
			row.item_code,
			_("Physical count variance: counted {0} vs system {1} ({2}%) in {3} ({4})").format(
				counted, system, round(variance_pct, 1), row.warehouse, row.reconciliation
			),
			dedupe_prefix="Physical count variance",
		)
	return flagged


# ---------------------------------------------------------------------------
# Reorder level recompute
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

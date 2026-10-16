# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Inventory REST endpoints consumed by external systems.

``POST /api/method/horizon_erp.api.inventory.get_inventory_snapshot``
(also reachable as ``horizon_erp.api.get_inventory_snapshot``; see ``horizon_erp/api/__init__.py``).

Every call - success, invalid input, rate limited or error - is recorded in ``Inventory API Log``
(Horizon Integration). Full contract, error bodies and examples: ``docs/api.md``.
"""

import json
import time
import traceback

import frappe
from frappe import _
from frappe.query_builder.functions import Max, Sum
from frappe.utils import cint, flt

from horizon_erp.api.rate_limit import get_client_identity, get_configured_limit, rate_limited
from horizon_erp.horizon_integration.doctype.inventory_api_log.inventory_api_log import (
	STATUS_ERROR,
	STATUS_INVALID_INPUT,
	STATUS_RATE_LIMITED,
	STATUS_SUCCESS,
	iso_now,
	log_api_call,
)

ENDPOINT = "horizon_erp.api.inventory.get_inventory_snapshot"
RETRY_AFTER_ON_FAILURE = 30
QTY_PRECISION = 3
AMOUNT_PRECISION = 2
CRITICAL_LEVELS = ("A", "B")


# ---------------------------------------------------------------------------
# endpoint
# ---------------------------------------------------------------------------


def _log_rate_limited(state, *args, **kwargs):
	log_api_call(
		endpoint=ENDPOINT,
		client=state.client,
		parameters=_params_for_log(kwargs.get("warehouse"), kwargs.get("filter_by_criticality")),
		response_time_ms=0,
		http_status=429,
		status=STATUS_RATE_LIMITED,
		error=f"limit {state.limit}/{state.window}s exceeded (count {state.count})",
	)


@frappe.whitelist(methods=["POST", "GET"])
@rate_limited(limit=get_configured_limit, on_exceed=_log_rate_limited)
def get_inventory_snapshot(warehouse=None, filter_by_criticality=False, _simulate_failure=None):
	"""Return current stock per item for ``warehouse`` (leaf or group).

	:param warehouse: Warehouse name, ``name - ABBR`` or ``warehouse_name`` (resolved leniently)
	:param filter_by_criticality: truthy -> only items with criticality A or B
	:return: dict - see ``docs/api.md`` (success) or an error dict with ``error`` + HTTP status set
	"""
	started = time.perf_counter()
	client = get_client_identity()
	params = _params_for_log(warehouse, filter_by_criticality)

	def finish(status, http_status, body, error=None, commit=False):
		log_api_call(
			endpoint=ENDPOINT,
			client=client,
			parameters=params,
			response_time_ms=(time.perf_counter() - started) * 1000,
			http_status=http_status,
			status=status,
			error=error,
			commit=commit,
		)
		if http_status != 200:
			frappe.local.response["http_status_code"] = http_status
		return body

	# -- auth -------------------------------------------------------------
	if not frappe.session.user or frappe.session.user == "Guest":
		finish(STATUS_ERROR, 401, None, error="Guest access is not allowed", commit=True)
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)
	if not frappe.has_permission("Bin", "read"):
		finish(STATUS_ERROR, 403, None, error="No read permission on Bin", commit=True)
		frappe.throw(_("Not permitted to read stock levels"), frappe.PermissionError)

	# -- input ------------------------------------------------------------
	warehouse = (warehouse or "").strip()
	if not warehouse:
		return finish(
			STATUS_INVALID_INPUT,
			400,
			_error_body("missing_warehouse", _("Parameter 'warehouse' is required")),
			error="missing warehouse",
		)

	resolved = resolve_warehouse(warehouse)
	if not resolved:
		return finish(
			STATUS_INVALID_INPUT,
			404,
			_error_body(
				"invalid_warehouse",
				_("Warehouse '{0}' not found").format(warehouse),
				hint=_(
					"Pass the Warehouse ID (e.g. 'Delhi DC - HML') or its Warehouse Name (e.g. 'Delhi DC')"
				),
			),
			error=f"warehouse '{warehouse}' not found",
		)

	only_critical = parse_bool(filter_by_criticality)
	leaves = get_leaf_warehouses(resolved)

	# -- data -------------------------------------------------------------
	savepoint = "horizon_inventory_snapshot"
	frappe.db.savepoint(savepoint)
	try:
		if _simulate_failure and frappe.conf.developer_mode and parse_bool(_simulate_failure):
			raise frappe.db.InternalError("simulated database failure (_simulate_failure=1)")
		items = fetch_snapshot_rows(leaves, only_critical)
	except Exception:
		tb = traceback.format_exc()
		# discard whatever the failed statement left behind without touching the caller's transaction
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(title="Inventory snapshot query failed", message=tb)
		return finish(
			STATUS_ERROR,
			503,
			_error_body(
				"temporary_failure",
				_("Inventory data is temporarily unavailable, please retry"),
				retry_after_seconds=RETRY_AFTER_ON_FAILURE,
			),
			error=tb,
		)

	body = build_snapshot(resolved, leaves, items)
	body["generated_in_ms"] = round((time.perf_counter() - started) * 1000, 2)
	return finish(STATUS_SUCCESS, 200, body)


# ---------------------------------------------------------------------------
# helpers (importable for tests / other modules)
# ---------------------------------------------------------------------------


def parse_bool(value) -> bool:
	if isinstance(value, bool):
		return value
	if value is None:
		return False
	if isinstance(value, int | float):
		return bool(value)
	return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def resolve_warehouse(name: str) -> str | None:
	"""Exact name -> ``name - <abbr>`` for any company -> ``warehouse_name`` match. ``None`` if unknown."""
	if not name:
		return None
	if frappe.db.exists("Warehouse", name):
		return name

	abbrs = frappe.get_all("Company", pluck="abbr")
	candidates = [f"{name} - {abbr}" for abbr in abbrs if abbr]
	default_company = frappe.defaults.get_global_default("company")
	if candidates:
		matches = frappe.get_all(
			"Warehouse",
			filters={"name": ["in", candidates]},
			fields=["name", "company"],
			order_by="lft asc",
		)
		if matches:
			return _prefer_default_company(matches, default_company)

	matches = frappe.get_all(
		"Warehouse",
		filters={"warehouse_name": name},
		fields=["name", "company"],
		order_by="lft asc",
	)
	if matches:
		return _prefer_default_company(matches, default_company)
	return None


def _prefer_default_company(matches, default_company):
	for row in matches:
		if default_company and row.company == default_company:
			return row.name
	return matches[0].name


def get_leaf_warehouses(warehouse: str) -> list[str]:
	"""Leaf warehouses under ``warehouse`` (itself when it is a leaf)."""
	wh = frappe.db.get_value("Warehouse", warehouse, ["is_group", "lft", "rgt"], as_dict=True)
	if not wh:
		return []
	if not cint(wh.is_group):
		return [warehouse]
	return frappe.get_all(
		"Warehouse",
		filters={"lft": [">=", wh.lft], "rgt": ["<=", wh.rgt], "is_group": 0, "disabled": 0},
		pluck="name",
		order_by="lft asc",
	)


def fetch_snapshot_rows(leaves: list[str], only_critical: bool = False) -> list[dict]:
	"""One aggregate query Bin x Item, plus one query for Item Reorder rows (no N+1)."""
	if not leaves:
		return []

	Bin = frappe.qb.DocType("Bin")
	Item = frappe.qb.DocType("Item")
	has_criticality = frappe.get_meta("Item").has_field("criticality")

	query = (
		frappe.qb.from_(Bin)
		.join(Item)
		.on(Item.name == Bin.item_code)
		.select(
			Bin.item_code,
			Item.item_name,
			Item.item_group,
			Sum(Bin.actual_qty).as_("actual_qty"),
			Sum(Bin.reserved_qty).as_("reserved_qty"),
			Sum(Bin.projected_qty).as_("projected_qty"),
			Sum(Bin.stock_value).as_("stock_value"),
			Max(Bin.valuation_rate).as_("max_valuation_rate"),
		)
		.where(Bin.warehouse.isin(leaves))
		.where(Item.is_stock_item == 1)
		.where(Item.disabled == 0)
		.groupby(Bin.item_code, Item.item_name, Item.item_group)
		.orderby(Bin.item_code)
	)
	if has_criticality:
		query = query.select(Item.criticality).groupby(Item.criticality)
		if only_critical:
			query = query.where(Item.criticality.isin(list(CRITICAL_LEVELS)))
	elif only_critical:
		return []

	rows = query.run(as_dict=True)
	if not rows:
		return []

	reorder = get_reorder_levels([r.item_code for r in rows], leaves)
	for row in rows:
		level, qty = reorder.get(row.item_code, (0.0, 0.0))
		row["reorder_point"] = level
		row["reorder_qty"] = qty
		row.setdefault("criticality", None)
	return rows


def get_reorder_levels(item_codes: list[str], leaves: list[str]) -> dict[str, tuple[float, float]]:
	"""``{item_code: (reorder_level, reorder_qty)}`` - row for one of ``leaves`` first, else any row."""
	if not item_codes:
		return {}
	rows = frappe.get_all(
		"Item Reorder",
		filters={"parenttype": "Item", "parent": ["in", item_codes]},
		fields=["parent", "warehouse", "warehouse_reorder_level", "warehouse_reorder_qty"],
		order_by="idx asc",
	)
	leaf_set = set(leaves)
	best: dict[str, tuple[int, float, float]] = {}
	for r in rows:
		rank = 2 if r.warehouse in leaf_set else 1
		current = best.get(r.parent)
		if current is None or rank > current[0]:
			best[r.parent] = (rank, flt(r.warehouse_reorder_level), flt(r.warehouse_reorder_qty))
	return {code: (level, qty) for code, (_rank, level, qty) in best.items()}


def build_snapshot(warehouse: str, leaves: list[str], rows: list[dict]) -> dict:
	items, alerts = [], []
	total_value = 0.0
	for r in rows:
		actual = flt(r.actual_qty, QTY_PRECISION)
		reserved = flt(r.reserved_qty, QTY_PRECISION)
		available = flt(actual - reserved, QTY_PRECISION)
		reorder_point = flt(r.reorder_point, QTY_PRECISION)
		stock_value = flt(r.stock_value, AMOUNT_PRECISION)
		if actual > 0 and stock_value:
			valuation_rate = flt(stock_value / actual, AMOUNT_PRECISION)
		else:
			valuation_rate = flt(r.max_valuation_rate, AMOUNT_PRECISION)
		below = reorder_point > 0 and available < reorder_point

		items.append(
			{
				"item_code": r.item_code,
				"item_name": r.item_name,
				"item_group": r.item_group,
				"criticality": r.get("criticality"),
				"available_qty": available,
				"actual_qty": actual,
				"reserved_qty": reserved,
				"projected_qty": flt(r.projected_qty, QTY_PRECISION),
				"reorder_point": reorder_point,
				"reorder_qty": flt(r.reorder_qty, QTY_PRECISION),
				"below_reorder": below,
				"valuation_rate": valuation_rate,
			}
		)
		total_value += stock_value
		if below:
			alerts.append(
				{
					"item_code": r.item_code,
					"available_qty": available,
					"reorder_point": reorder_point,
					"shortfall": flt(reorder_point - available, QTY_PRECISION),
					"criticality": r.get("criticality"),
				}
			)

	return {
		"timestamp": iso_now(),
		"warehouse": warehouse,
		"warehouses_included": leaves,
		"generated_in_ms": 0,
		"items": items,
		"low_stock_alerts": alerts,
		"summary": {
			"item_count": len(items),
			"low_stock_count": len(alerts),
			"total_stock_value": flt(total_value, AMOUNT_PRECISION),
		},
	}


def _error_body(code: str, message: str, **extra) -> dict:
	body = {"error": code, "message": message, "timestamp": iso_now()}
	body.update(extra)
	return body


def _params_for_log(warehouse, filter_by_criticality) -> str:
	return json.dumps(
		{"warehouse": warehouse, "filter_by_criticality": filter_by_criticality}, default=str, sort_keys=True
	)

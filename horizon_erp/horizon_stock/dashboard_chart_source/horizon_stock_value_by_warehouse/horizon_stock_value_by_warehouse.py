# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Stock value per leaf warehouse with readable labels for the Horizon Inventory workspace.

The standard Group By chart on Bin labels each bar with the warehouse *name* ("HQ Raw Materials -
HML"), which frappe-charts truncates to "HQ ..." on a half-width card. This source labels the bars
with ``Warehouse.warehouse_name`` (no company suffix), skips empty warehouses and reads Bin through
``frappe.get_list`` so Warehouse User Permissions apply (a Delhi user only sees Delhi warehouses).
"""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.dashboard import cache_source

MAX_WAREHOUSES = 10


@frappe.whitelist()
@cache_source
def get(
	chart_name=None,
	chart=None,
	no_cache=None,
	filters=None,
	from_date=None,
	to_date=None,
	timespan=None,
	time_interval=None,
	heatmap_year=None,
):
	frappe.has_permission("Bin", throw=True)
	return get_data(frappe.parse_json(filters) or {})


def get_data(filters):
	warehouse_filters = {"is_group": 0}
	if filters.get("company"):
		warehouse_filters["company"] = filters.get("company")
	names = dict(
		frappe.get_list(
			"Warehouse", filters=warehouse_filters, fields=["name", "warehouse_name"], as_list=True
		)
	)
	if not names:
		return {"labels": [], "datasets": [{"name": _("Stock Value"), "values": []}], "type": "bar"}

	rows = frappe.get_list(
		"Bin",
		fields=["warehouse", "sum(stock_value) as stock_value"],
		filters={"warehouse": ["in", list(names)]},
		group_by="warehouse",
		order_by="stock_value desc",
	)
	rows = [r for r in rows if flt(r.stock_value) > 0][:MAX_WAREHOUSES]
	return {
		"labels": [names[r.warehouse] or r.warehouse for r in rows],
		"datasets": [{"name": _("Stock Value"), "values": [flt(r.stock_value, 2) for r in rows]}],
		"type": "bar",
	}

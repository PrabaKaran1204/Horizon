# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Inventory Obsolescence Analysis: stock on hand aged by last sale (or first receipt)."""

import frappe
from frappe import _
from frappe.query_builder import Case
from frappe.query_builder.functions import Max, Min
from frappe.utils import cint, date_diff, flt, getdate, today

from horizon_erp.horizon_stock.permissions import get_permitted_warehouses

BUCKETS = (("0-30", 0, 30), ("31-90", 31, 90), ("91-180", 91, 180), ("180+", 181, None))
SALE_VOUCHERS = ("Delivery Note", "Sales Invoice")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
			"Global Defaults", "default_company"
		)
	filters.days_threshold = cint(filters.days_threshold) or 90

	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	summary = get_summary(data, filters)
	return columns, data, None, chart, summary


def get_columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 180},
		{
			"label": _("Category"),
			"fieldname": "item_group",
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 120,
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 160,
		},
		{"label": _("Current Stock"), "fieldname": "actual_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Valuation Rate"), "fieldname": "valuation_rate", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Inventory Value"),
			"fieldname": "inventory_value",
			"fieldtype": "Currency",
			"width": 130,
		},
		{"label": _("Last Purchase"), "fieldname": "last_purchase", "fieldtype": "Date", "width": 110},
		{"label": _("Last Sale"), "fieldname": "last_sale", "fieldtype": "Date", "width": 110},
		{
			"label": _("Days Since Last Sale"),
			"fieldname": "days_since_last_sale",
			"fieldtype": "Int",
			"width": 120,
		},
		{"label": _("Aging Bucket"), "fieldname": "aging_bucket", "fieldtype": "Data", "width": 100},
	]


def get_data(filters):
	bin_ = frappe.qb.DocType("Bin")
	item = frappe.qb.DocType("Item")
	wh = frappe.qb.DocType("Warehouse")

	query = (
		frappe.qb.from_(bin_)
		.inner_join(item)
		.on(item.name == bin_.item_code)
		.inner_join(wh)
		.on(wh.name == bin_.warehouse)
		.select(
			bin_.item_code,
			item.item_name,
			item.item_group,
			bin_.warehouse,
			bin_.actual_qty,
			bin_.valuation_rate,
			bin_.stock_value,
		)
		.where((bin_.actual_qty > 0) & (item.is_stock_item == 1) & (wh.company == filters.company))
		.orderby(bin_.item_code)
		.orderby(bin_.warehouse)
	)
	if filters.item_group:
		query = query.where(item.item_group == filters.item_group)
	if filters.warehouse:
		query = query.where(bin_.warehouse == filters.warehouse)
	# rows, summary and the Aging Stock Value card stay inside the user's Warehouse permissions
	allowed = get_permitted_warehouses()
	if allowed is not None:
		if not allowed:
			return []
		query = query.where(bin_.warehouse.isin(sorted(allowed)))

	rows = query.run(as_dict=True)
	if not rows:
		return []

	movements = get_movements(filters, rows)
	as_on = getdate(today())
	data = []
	for row in rows:
		mv = movements.get((row.item_code, row.warehouse), frappe._dict())
		row.last_purchase = mv.get("last_purchase")
		row.last_sale = mv.get("last_sale")
		reference = row.last_sale or mv.get("first_receipt")
		row.days_since_last_sale = date_diff(as_on, reference) if reference else 0
		row.inventory_value = flt(row.actual_qty) * flt(row.valuation_rate)
		row.aging_bucket = get_bucket(row.days_since_last_sale)
		data.append(row)
	return data


def get_movements(filters, rows):
	"""One aggregate pass over Stock Ledger Entry for the item/warehouse pairs in scope."""
	sle = frappe.qb.DocType("Stock Ledger Entry")
	item_codes = list({r.item_code for r in rows})
	warehouses = list({r.warehouse for r in rows})

	purchase_case = Case().when(
		(sle.voucher_type == "Purchase Receipt") & (sle.actual_qty > 0), sle.posting_date
	)
	sale_case = Case().when((sle.voucher_type.isin(SALE_VOUCHERS)) & (sle.actual_qty < 0), sle.posting_date)
	receipt_case = Case().when(sle.actual_qty > 0, sle.posting_date)

	result = (
		frappe.qb.from_(sle)
		.select(
			sle.item_code,
			sle.warehouse,
			Max(purchase_case).as_("last_purchase"),
			Max(sale_case).as_("last_sale"),
			Min(receipt_case).as_("first_receipt"),
		)
		.where(
			(sle.is_cancelled == 0)
			& (sle.item_code.isin(item_codes))
			& (sle.warehouse.isin(warehouses))
			& (sle.company == filters.company)
		)
		.groupby(sle.item_code, sle.warehouse)
	).run(as_dict=True)
	return {(r.item_code, r.warehouse): r for r in result}


def get_bucket(days):
	for label, low, high in BUCKETS:
		if days >= low and (high is None or days <= high):
			return label
	return BUCKETS[0][0]


def get_chart(data):
	values = {b[0]: 0.0 for b in BUCKETS}
	for row in data:
		values[row.aging_bucket] += flt(row.inventory_value)
	return {
		"data": {
			"labels": list(values.keys()),
			"datasets": [{"name": _("Inventory Value"), "values": [round(v, 2) for v in values.values()]}],
		},
		"type": "bar",
		"colors": ["#5e64ff", "#ffa00a", "#ff5858", "#b3b3b3"],
	}


def get_summary(data, filters):
	total = sum(flt(r.inventory_value) for r in data)
	above = sum(flt(r.inventory_value) for r in data if r.days_since_last_sale > filters.days_threshold)
	return [
		{"value": total, "label": _("Total Inventory Value"), "datatype": "Currency", "indicator": "Blue"},
		{
			"value": above,
			"label": _("Value Older Than {0} Days").format(filters.days_threshold),
			"datatype": "Currency",
			"indicator": "Red" if above else "Green",
		},
		{
			"value": len({r.item_code for r in data}),
			"label": _("Items In Stock"),
			"datatype": "Int",
			"indicator": "Blue",
		},
	]

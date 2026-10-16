# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""BOM Explosion with Lead Time: exploded leaf items vs stock, with procurement lead times."""

import frappe
from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict
from frappe import _
from frappe.utils import add_days, cint, flt, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.qty = flt(filters.qty) or 1
	columns = get_columns()
	if not filters.bom:
		return columns, [], _("Select a BOM to explode."), None, None
	bom = frappe.get_doc("BOM", filters.bom)
	bom.check_permission("read")
	filters.company = bom.company
	if not filters.warehouse:
		default = f"HQ Raw Materials - {frappe.get_cached_value('Company', bom.company, 'abbr')}"
		filters.warehouse = default if frappe.db.exists("Warehouse", default) else None
	data = get_data(filters, bom)
	return columns, data, None, get_chart(data), get_summary(data, bom, filters)


def get_columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 160},
		{
			"label": _("Group"),
			"fieldname": "item_group",
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 110,
		},
		{"label": _("Required Qty"), "fieldname": "required_qty", "fieldtype": "Float", "width": 100},
		{"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 70},
		{"label": _("In Stock"), "fieldname": "in_stock", "fieldtype": "Float", "width": 90},
		{"label": _("Shortage"), "fieldname": "shortage", "fieldtype": "Float", "width": 90},
		{"label": _("Lead Time Days"), "fieldname": "lead_time_days", "fieldtype": "Int", "width": 90},
		{"label": _("Available On"), "fieldname": "available_on", "fieldtype": "Date", "width": 100},
		{"label": _("Criticality"), "fieldname": "criticality", "fieldtype": "Data", "width": 80},
		{"label": _("Rate"), "fieldname": "rate", "fieldtype": "Currency", "width": 100},
		{"label": _("Projected Cost"), "fieldname": "projected_cost", "fieldtype": "Currency", "width": 120},
	]


def get_data(filters, bom):
	items = get_bom_items_as_dict(bom.name, bom.company, qty=filters.qty, fetch_exploded=1)
	if not items:
		return []
	item_codes = list(items)
	meta = {
		i.name: i
		for i in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes]},
			fields=["name", "lead_time_days", "criticality", "valuation_rate", "last_purchase_rate"],
		)
	}
	bins = {}
	bin_filters = {"item_code": ["in", item_codes]}
	if filters.warehouse:
		bin_filters["warehouse"] = filters.warehouse
	for b in frappe.get_all("Bin", filters=bin_filters, fields=["item_code", "actual_qty", "valuation_rate"]):
		entry = bins.setdefault(b.item_code, frappe._dict(actual_qty=0.0, valuation_rate=0.0))
		entry.actual_qty += flt(b.actual_qty)
		entry.valuation_rate = entry.valuation_rate or flt(b.valuation_rate)

	today = nowdate()
	data = []
	for item_code, d in items.items():
		m = meta.get(item_code) or frappe._dict()
		b = bins.get(item_code) or frappe._dict(actual_qty=0.0, valuation_rate=0.0)
		required = flt(d.qty)
		shortage = max(required - flt(b.actual_qty), 0)
		lead = cint(m.lead_time_days)
		rate = flt(b.valuation_rate) or flt(m.valuation_rate) or flt(m.last_purchase_rate) or flt(d.rate)
		data.append(
			frappe._dict(
				item_code=item_code,
				item_name=d.item_name,
				item_group=d.item_group,
				required_qty=required,
				stock_uom=d.stock_uom,
				in_stock=flt(b.actual_qty),
				shortage=shortage,
				lead_time_days=lead,
				available_on=add_days(today, lead) if shortage else today,
				criticality=m.criticality,
				rate=rate,
				projected_cost=required * rate,
			)
		)
	data.sort(key=lambda r: (-r.shortage, -r.projected_cost))
	return data


def get_chart(data):
	top = sorted(data, key=lambda r: r.projected_cost, reverse=True)[:10]
	return {
		"data": {
			"labels": [r.item_code for r in top],
			"datasets": [{"name": _("Projected Cost"), "values": [flt(r.projected_cost, 2) for r in top]}],
		},
		"type": "bar",
	}


def get_summary(data, bom, filters):
	material = sum(r.projected_cost for r in data)
	max_lead = max([r.lead_time_days for r in data if r.shortage] or [0])
	operating = flt(bom.operating_cost) * filters.qty / (flt(bom.quantity) or 1)
	return [
		{"value": material, "label": _("Total Material Cost"), "datatype": "Currency", "indicator": "Blue"},
		{"value": operating, "label": _("Operation Cost"), "datatype": "Currency", "indicator": "Blue"},
		{
			"value": material + operating,
			"label": _("Total Projected Cost"),
			"datatype": "Currency",
			"indicator": "Green",
		},
		{
			"value": max_lead,
			"label": _("Max Lead Time (days) - earliest start"),
			"datatype": "Int",
			"indicator": "Red" if max_lead else "Green",
		},
		{
			"value": sum(1 for r in data if r.shortage),
			"label": _("Items Short"),
			"datatype": "Int",
			"indicator": "Red" if any(r.shortage for r in data) else "Green",
		},
	]

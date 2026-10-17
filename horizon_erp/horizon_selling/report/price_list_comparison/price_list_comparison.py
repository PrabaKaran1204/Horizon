# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Price List Comparison: list rates vs. effective rates after Pricing Rules per segment."""

import frappe
from erpnext.accounts.doctype.pricing_rule.pricing_rule import get_pricing_rule_for_item
from frappe import _
from frappe.utils import flt, nowdate

DEFAULT_GROUPS = ("Equipment", "Spares", "Components")
CUSTOMER_GROUPS = ("Premium", "Standard")
TERRITORIES = ("West", "North")
BULK_QTY = 60
Q4_PROMO_DATE = "2026-11-15"
MAX_ITEMS = 200


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	filters.price_list = filters.price_list or "Standard Selling"
	filters.currency = frappe.get_cached_value("Company", filters.company, "default_currency") or "INR"
	segments = get_segments()
	price_lists = [pl for pl in ("Standard Selling", "North Selling") if frappe.db.exists("Price List", pl)]
	columns = get_columns(segments, price_lists)
	data = get_data(filters, segments, price_lists)
	return columns, data, None, get_chart(data, segments), get_summary(data, segments)


def get_segments():
	groups = [g for g in CUSTOMER_GROUPS if frappe.db.exists("Customer Group", g)]
	territories = [t for t in TERRITORIES if frappe.db.exists("Territory", t)]
	segments = []
	for g in groups:
		for t in territories:
			segments.append(
				frappe._dict(key=frappe.scrub(f"{g}_{t}"), label=f"{g} / {t}", customer_group=g, territory=t)
			)
	return segments


def get_columns(segments, price_lists):
	columns = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 150},
		{
			"label": _("Group"),
			"fieldname": "item_group",
			"fieldtype": "Link",
			"options": "Item Group",
			"width": 100,
		},
	]
	for pl in price_lists:
		columns.append({"label": _(pl), "fieldname": frappe.scrub(pl), "fieldtype": "Currency", "width": 110})
	for s in segments:
		columns.append({"label": s.label, "fieldname": s.key, "fieldtype": "Currency", "width": 120})
		columns.append(
			{
				"label": f"{s.label} {_('Bulk')} ({BULK_QTY})",
				"fieldname": f"{s.key}_bulk",
				"fieldtype": "Currency",
				"width": 130,
			}
		)
	columns.append({"label": _("Q4 Promo"), "fieldname": "q4_promo", "fieldtype": "Currency", "width": 110})
	return columns


def get_items(filters):
	item_filters = {"disabled": 0, "is_sales_item": 1}
	if filters.item_group:
		item_filters["item_group"] = filters.item_group
	else:
		groups = [g for g in DEFAULT_GROUPS if frappe.db.exists("Item Group", g)]
		if groups:
			item_filters["item_group"] = ["in", groups]
	if filters.item:
		item_filters["name"] = filters.item
	return frappe.get_all(
		"Item",
		filters=item_filters,
		fields=["name", "item_name", "item_group", "stock_uom"],
		order_by="item_group, name",
		limit=MAX_ITEMS,
	)


def get_list_rates(item_codes, price_lists):
	rates = {}
	if not item_codes or not price_lists:
		return rates
	for p in frappe.get_all(
		"Item Price",
		filters={"item_code": ["in", item_codes], "price_list": ["in", price_lists], "selling": 1},
		fields=["item_code", "price_list", "price_list_rate", "valid_from"],
		order_by="valid_from asc",
	):
		rates[(p.item_code, p.price_list)] = flt(p.price_list_rate)
	return rates


def effective_rate(filters, item, base_rate, customer_group, territory, qty, transaction_date):
	"""Rate after Pricing Rules for the segment; falls back to the list rate on any error."""
	if not base_rate:
		return 0.0
	args = frappe._dict(
		item_code=item.name,
		item_group=item.item_group,
		customer_group=customer_group,
		territory=territory,
		qty=qty,
		stock_qty=qty,
		uom=item.stock_uom,
		stock_uom=item.stock_uom,
		conversion_factor=1,
		transaction_date=transaction_date,
		price_list=filters.price_list,
		price_list_rate=base_rate,
		company=filters.company,
		doctype="Quotation",
		parenttype="Quotation",
		currency=filters.currency,
		conversion_rate=1,
		plc_conversion_rate=1,
		transaction_type="selling",
	)
	try:
		result = get_pricing_rule_for_item(args) or {}
	except Exception:
		frappe.log_error(title="Price List Comparison: pricing rule evaluation failed")
		return base_rate
	rate = flt(result.get("price_list_rate")) or base_rate
	if flt(result.get("discount_amount")):
		rate -= flt(result.get("discount_amount"))
	elif flt(result.get("discount_percentage")):
		rate *= 1 - flt(result.get("discount_percentage")) / 100
	return flt(max(rate, 0), 2)


def get_data(filters, segments, price_lists):
	items = get_items(filters)
	if not items:
		return []
	list_rates = get_list_rates([i.name for i in items], price_lists)
	today = nowdate()
	data = []
	for item in items:
		row = frappe._dict(item_code=item.name, item_name=item.item_name, item_group=item.item_group)
		for pl in price_lists:
			row[frappe.scrub(pl)] = list_rates.get((item.name, pl), 0.0)
		base = list_rates.get((item.name, filters.price_list), 0.0)
		for s in segments:
			row[s.key] = effective_rate(filters, item, base, s.customer_group, s.territory, 1, today)
			row[f"{s.key}_bulk"] = effective_rate(
				filters, item, base, s.customer_group, s.territory, BULK_QTY, today
			)
		row.q4_promo = effective_rate(filters, item, base, None, None, 1, Q4_PROMO_DATE)
		row.base_rate = base
		data.append(row)
	return data


def get_chart(data, segments):
	top = data[:10]
	datasets = [{"name": _("List Rate"), "values": [r.base_rate for r in top]}]
	for s in segments[:3]:
		datasets.append({"name": s.label, "values": [r[s.key] for r in top]})
	return {"data": {"labels": [r.item_code for r in top], "datasets": datasets}, "type": "bar"}


def get_summary(data, segments):
	discounted = 0
	for r in data:
		if any(r[s.key] < r.base_rate for s in segments) or r.q4_promo < r.base_rate:
			discounted += 1
	return [
		{"value": len(data), "label": _("Items Compared"), "datatype": "Int", "indicator": "Blue"},
		{
			"value": discounted,
			"label": _("Items With Rule Discounts"),
			"datatype": "Int",
			"indicator": "Orange",
		},
		{"value": len(segments), "label": _("Segments"), "datatype": "Int", "indicator": "Blue"},
	]

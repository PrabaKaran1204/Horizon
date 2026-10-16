# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Forecast vs Actual Demand: monthly outgoing qty per item with a 3-month moving-average forecast."""

import frappe
from frappe import _
from frappe.query_builder import CustomFunction
from frappe.query_builder.functions import Min, Sum
from frappe.utils import add_months, cint, flt, formatdate, get_first_day, getdate, nowdate

DateFormat = CustomFunction("DATE_FORMAT", ["date", "format"])
DELIVERY_VOUCHERS = ("Delivery Note", "Sales Invoice")
ISSUE_PURPOSES = ("Material Issue", "Manufacture", "Material Consumption for Manufacture")
SEASONAL_MULTIPLIER = 1.5
Q4_MONTHS = (10, 11, 12)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	filters.months_back = cint(filters.months_back) or 12
	months = get_months(filters.months_back)
	columns = get_columns(months)
	data = get_data(filters, months)
	return columns, data, None, get_chart(data, months, filters), get_summary(data)


def get_months(months_back):
	"""[(key, label, first_day)] for the last ``months_back`` months ending with the current month."""
	first = get_first_day(add_months(nowdate(), -(months_back - 1)))
	months = []
	for i in range(months_back):
		d = get_first_day(add_months(first, i))
		months.append((d.strftime("%Y_%m"), formatdate(d, "MMM yy"), d))
	return months


def get_columns(months):
	columns = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 160},
		{"label": _("Demand Pattern"), "fieldname": "demand_pattern", "fieldtype": "Data", "width": 100},
	]
	for key, label, _d in months:
		columns.append({"label": label, "fieldname": key, "fieldtype": "Float", "width": 80})
	columns += [
		{"label": _("Last Actual"), "fieldname": "last_actual", "fieldtype": "Float", "width": 90},
		{"label": _("Forecast (Next Month)"), "fieldname": "forecast", "fieldtype": "Float", "width": 120},
		{"label": _("Variance %"), "fieldname": "variance_pct", "fieldtype": "Percent", "width": 90},
	]
	return columns


def get_outgoing(filters, from_date):
	sle = frappe.qb.DocType("Stock Ledger Entry")
	se = frappe.qb.DocType("Stock Entry")
	item = frappe.qb.DocType("Item")
	month_key = DateFormat(sle.posting_date, "%Y_%m")
	q = (
		frappe.qb.from_(sle)
		.inner_join(item)
		.on(item.name == sle.item_code)
		.left_join(se)
		.on((sle.voucher_type == "Stock Entry") & (se.name == sle.voucher_no))
		.select(sle.item_code, month_key.as_("month_key"), Sum(-sle.actual_qty).as_("qty"))
		.where(
			(sle.is_cancelled == 0)
			& (sle.actual_qty < 0)
			& (sle.company == filters.company)
			& (sle.posting_date >= from_date)
			& ((sle.voucher_type.isin(DELIVERY_VOUCHERS)) | (se.purpose.isin(ISSUE_PURPOSES)))
		)
		.groupby(sle.item_code, month_key)
	)
	if filters.item_group:
		q = q.where(item.item_group == filters.item_group)
	if filters.item:
		q = q.where(sle.item_code == filters.item)
	return q.run(as_dict=True)


def get_first_movement(filters, item_codes):
	sle = frappe.qb.DocType("Stock Ledger Entry")
	rows = (
		frappe.qb.from_(sle)
		.select(sle.item_code, Min(sle.posting_date).as_("first_date"))
		.where((sle.is_cancelled == 0) & (sle.item_code.isin(item_codes)) & (sle.company == filters.company))
		.groupby(sle.item_code)
	).run(as_dict=True)
	return {r.item_code: r.first_date for r in rows}


def get_data(filters, months):
	# fetch 13 months of history on top of the displayed range for the seasonal index
	history_start = get_first_day(add_months(months[0][2], -13))
	rows = get_outgoing(filters, history_start)
	per_item = {}
	for r in rows:
		per_item.setdefault(r.item_code, {})[r.month_key] = flt(r.qty)
	if filters.item and filters.item not in per_item:
		per_item[filters.item] = {}
	if not per_item:
		return []

	items = frappe.get_all(
		"Item",
		filters={"name": ["in", list(per_item)]},
		fields=["name", "item_name", "demand_pattern"],
	)
	items = {i.name: i for i in items}
	first_movement = get_first_movement(filters, list(per_item))

	next_month = get_first_day(add_months(months[-1][2], 1))
	data = []
	for item_code, by_month in per_item.items():
		meta = items.get(item_code) or frappe._dict()
		row = frappe._dict(item_code=item_code, item_name=meta.item_name, demand_pattern=meta.demand_pattern)
		series = []
		for key, _label, _d in months:
			row[key] = flt(by_month.get(key))
			series.append(row[key])
		row.last_actual = series[-1]
		ma = moving_average(series)
		seasonal = seasonal_index(by_month, next_month, first_movement.get(item_code))
		row.seasonal_index = flt(seasonal, 2)
		forecast = ma * seasonal
		if meta.demand_pattern == "Seasonal Q4" and next_month.month in Q4_MONTHS:
			forecast *= SEASONAL_MULTIPLIER
		row.forecast = flt(forecast, 2)
		previous_ma = moving_average(series[:-1])
		row.variance_pct = variance_pct(previous_ma, row.last_actual)
		data.append(row)
	data.sort(key=lambda r: sum(r[k] for k, _l, _d in months), reverse=True)
	return data


def moving_average(series, window=3):
	window_values = [v for v in series[-window:]]
	return sum(window_values) / len(window_values) if window_values else 0.0


def seasonal_index(by_month, next_month, first_date):
	"""Last year's share of ``next_month`` x 12, only when the item has >= 13 months of history."""
	if not first_date or getdate(first_date) > add_months(next_month, -13):
		return 1.0
	same_month_last_year = add_months(next_month, -12)
	year_start = add_months(same_month_last_year, -11)
	total = 0.0
	for i in range(12):
		total += flt(by_month.get(get_first_day(add_months(year_start, i)).strftime("%Y_%m")))
	if not total:
		return 1.0
	return flt(by_month.get(same_month_last_year.strftime("%Y_%m"))) / total * 12


def variance_pct(forecast, actual):
	if actual:
		return flt(abs(forecast - actual) / actual * 100, 1)
	return 100.0 if forecast else 0.0


def get_chart(data, months, filters):
	labels = [label for _k, label, _d in months]
	if filters.item and data:
		row = data[0]
		actual = [row[k] for k, _l, _d in months]
		forecast = [flt(moving_average(actual[:i]), 2) if i >= 3 else None for i in range(len(actual))]
		return {
			"data": {
				"labels": labels,
				"datasets": [
					{"name": _("Actual"), "values": actual},
					{"name": _("Forecast (3M MA)"), "values": forecast},
				],
			},
			"type": "line",
			"colors": ["#5e64ff", "#ffa00a"],
		}
	top = data[:10]
	return {
		"data": {
			"labels": [r.item_code for r in top],
			"datasets": [
				{"name": _("Actual (period)"), "values": [sum(r[k] for k, _l, _d in months) for r in top]},
				{"name": _("Forecast (next month)"), "values": [r.forecast for r in top]},
			],
		},
		"type": "bar",
		"colors": ["#5e64ff", "#ffa00a"],
	}


def get_summary(data):
	total_forecast = sum(r.forecast for r in data)
	total_last = sum(r.last_actual for r in data)
	seasonal = sum(1 for r in data if r.demand_pattern == "Seasonal Q4")
	return [
		{"value": len(data), "label": _("Items With Demand"), "datatype": "Int", "indicator": "Blue"},
		{
			"value": flt(total_last, 2),
			"label": _("Last Month Actual"),
			"datatype": "Float",
			"indicator": "Blue",
		},
		{
			"value": flt(total_forecast, 2),
			"label": _("Next Month Forecast"),
			"datatype": "Float",
			"indicator": "Orange",
		},
		{"value": seasonal, "label": _("Seasonal Q4 Items"), "datatype": "Int", "indicator": "Green"},
	]

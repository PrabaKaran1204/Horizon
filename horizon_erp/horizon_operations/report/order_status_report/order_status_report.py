# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Order Status Report: fulfilment of every Sales Order line with overdue flags."""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, date_diff, flt, getdate, today

OVERDUE_DAYS = 5


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, get_chart(data), get_summary(data)


def get_columns():
	return [
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 140,
		},
		{"label": _("Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 150,
		},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Ordered Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 100},
		{"label": _("Delivered Qty"), "fieldname": "delivered_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Invoiced Qty"), "fieldname": "invoiced_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Pending Delivery Qty"), "fieldname": "pending_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Pending Value"), "fieldname": "pending_value", "fieldtype": "Currency", "width": 120},
		{"label": _("Delivery Date"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 100},
		{"label": _("Fulfilment %"), "fieldname": "fulfilment_pct", "fieldtype": "Percent", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 130},
	]


def get_data(filters):
	so = frappe.qb.DocType("Sales Order")
	soi = frappe.qb.DocType("Sales Order Item")
	query = (
		frappe.qb.from_(soi)
		.inner_join(so)
		.on(so.name == soi.parent)
		.select(
			so.name.as_("sales_order"),
			so.transaction_date,
			so.customer,
			so.status.as_("so_status"),
			soi.name.as_("so_detail"),
			soi.item_code,
			soi.qty,
			soi.delivered_qty,
			soi.rate,
			soi.delivery_date,
		)
		.where((so.docstatus == 1) & (so.company == filters.company))
		.orderby(so.transaction_date)
		.orderby(so.name)
		.orderby(soi.idx)
	)
	if filters.customer:
		query = query.where(so.customer == filters.customer)
	if filters.from_date:
		query = query.where(so.transaction_date >= filters.from_date)
	if filters.to_date:
		query = query.where(so.transaction_date <= filters.to_date)
	if filters.status:
		query = query.where(so.status == filters.status)
	rows = query.run(as_dict=True)
	if not rows:
		return []

	invoiced = get_invoiced_qty([r.so_detail for r in rows])
	as_on = getdate(today())
	data = []
	for r in rows:
		r.invoiced_qty = flt(invoiced.get(r.so_detail))
		r.pending_qty = max(flt(r.qty) - flt(r.delivered_qty), 0)
		r.pending_value = r.pending_qty * flt(r.rate)
		r.days_overdue = 0
		if r.pending_qty > 0 and r.delivery_date and getdate(r.delivery_date) < as_on:
			r.days_overdue = date_diff(as_on, r.delivery_date)
		r.fulfilment_pct = min(flt(r.delivered_qty) / flt(r.qty) * 100, 100) if flt(r.qty) else 0
		r.status = get_status(r)
		if cint(filters.only_pending) and r.pending_qty <= 0:
			continue
		data.append(r)
	return data


def get_invoiced_qty(so_details):
	sii = frappe.qb.DocType("Sales Invoice Item")
	si = frappe.qb.DocType("Sales Invoice")
	result = (
		frappe.qb.from_(sii)
		.inner_join(si)
		.on(si.name == sii.parent)
		.select(sii.so_detail, Sum(sii.qty).as_("qty"))
		.where((si.docstatus == 1) & (si.is_return == 0) & (sii.so_detail.isin(so_details)))
		.groupby(sii.so_detail)
	).run(as_dict=True)
	return {r.so_detail: r.qty for r in result}


def get_status(row):
	if row.pending_qty <= 0:
		return "Fully Delivered"
	if row.days_overdue > OVERDUE_DAYS:
		return f"Overdue > {OVERDUE_DAYS}d"
	if flt(row.delivered_qty) > 0:
		return "Partial"
	return "Pending"


def get_chart(data):
	by_customer = {}
	for r in data:
		if r.pending_qty > 0:
			by_customer[r.customer] = by_customer.get(r.customer, 0) + r.pending_qty
	top = sorted(by_customer.items(), key=lambda x: x[1], reverse=True)[:10]
	return {
		"data": {
			"labels": [t[0] for t in top],
			"datasets": [{"name": _("Pending Qty"), "values": [round(t[1], 2) for t in top]}],
		},
		"type": "bar",
	}


def get_summary(data):
	pending_orders = {r.sales_order for r in data if r.pending_qty > 0}
	overdue_orders = {r.sales_order for r in data if r.days_overdue > OVERDUE_DAYS}
	pending_value = sum(r.pending_value for r in data)
	return [
		{"value": len(pending_orders), "label": _("Pending Orders"), "datatype": "Int", "indicator": "Blue"},
		{
			"value": len(overdue_orders),
			"label": _("Overdue > {0} Days").format(OVERDUE_DAYS),
			"datatype": "Int",
			"indicator": "Red" if overdue_orders else "Green",
		},
		{"value": pending_value, "label": _("Pending Value"), "datatype": "Currency", "indicator": "Orange"},
	]

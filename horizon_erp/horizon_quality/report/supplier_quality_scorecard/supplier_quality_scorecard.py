# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Supplier Quality Scorecard: rejection, on-time delivery and price stability per supplier."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe import _
from frappe.query_builder import Case
from frappe.query_builder.functions import Count, Sum
from frappe.utils import add_months, flt, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	if not filters.to_date:
		filters.to_date = nowdate()
	if not filters.from_date:
		filters.from_date = _period_start(filters)
	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, get_chart(data), get_summary(data)


def _period_start(filters):
	try:
		return get_fiscal_year(filters.to_date, company=filters.company)[1]
	except Exception:
		return add_months(filters.to_date, -12)


def get_columns():
	return [
		{
			"label": _("Supplier"),
			"fieldname": "supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 160,
		},
		{"label": _("Supplier Name"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 160},
		{"label": _("PO Count"), "fieldname": "po_count", "fieldtype": "Int", "width": 80},
		{"label": _("Received Qty"), "fieldname": "received_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Rejected Qty"), "fieldname": "rejected_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Rejection %"), "fieldname": "rejection_pct", "fieldtype": "Percent", "width": 90},
		{"label": _("QI Count"), "fieldname": "qi_count", "fieldtype": "Int", "width": 80},
		{"label": _("QI Rejected"), "fieldname": "qi_rejected", "fieldtype": "Int", "width": 90},
		{"label": _("On-time %"), "fieldname": "ontime_pct", "fieldtype": "Percent", "width": 90},
		{
			"label": _("Avg Price Change %"),
			"fieldname": "avg_price_change_pct",
			"fieldtype": "Percent",
			"width": 120,
		},
		{"label": _("Is Blacklisted"), "fieldname": "is_blacklisted", "fieldtype": "Check", "width": 90},
		{"label": _("Score"), "fieldname": "score", "fieldtype": "Float", "width": 80},
	]


def get_data(filters):
	suppliers = {}

	def row_for(supplier):
		return suppliers.setdefault(
			supplier,
			frappe._dict(
				supplier=supplier,
				po_count=0,
				received_qty=0.0,
				rejected_qty=0.0,
				qi_count=0,
				qi_rejected=0,
				ontime_lines=0,
				dated_lines=0,
				price_changes=[],
			),
		)

	# Purchase Orders
	po = frappe.qb.DocType("Purchase Order")
	q = (
		frappe.qb.from_(po)
		.select(po.supplier, Count(po.name).as_("po_count"))
		.where(
			(po.docstatus == 1)
			& (po.company == filters.company)
			& (po.transaction_date.between(filters.from_date, filters.to_date))
		)
		.groupby(po.supplier)
	)
	if filters.supplier:
		q = q.where(po.supplier == filters.supplier)
	for r in q.run(as_dict=True):
		row_for(r.supplier).po_count = r.po_count

	# Purchase Receipt lines (+ on-time vs PO schedule date)
	pr = frappe.qb.DocType("Purchase Receipt")
	pri = frappe.qb.DocType("Purchase Receipt Item")
	poi = frappe.qb.DocType("Purchase Order Item")
	ontime_case = Case().when(pr.posting_date <= poi.schedule_date, 1).else_(0)
	dated_case = Case().when(poi.schedule_date.isnotnull(), 1).else_(0)
	q = (
		frappe.qb.from_(pri)
		.inner_join(pr)
		.on(pr.name == pri.parent)
		.left_join(poi)
		.on(poi.name == pri.purchase_order_item)
		.select(
			pr.supplier,
			Sum(pri.received_qty).as_("received_qty"),
			Sum(pri.rejected_qty).as_("rejected_qty"),
			Sum(ontime_case).as_("ontime_lines"),
			Sum(dated_case).as_("dated_lines"),
		)
		.where(
			(pr.docstatus == 1)
			& (pr.is_return == 0)
			& (pr.company == filters.company)
			& (pr.posting_date.between(filters.from_date, filters.to_date))
		)
		.groupby(pr.supplier)
	)
	if filters.supplier:
		q = q.where(pr.supplier == filters.supplier)
	for r in q.run(as_dict=True):
		row = row_for(r.supplier)
		row.received_qty = flt(r.received_qty)
		row.rejected_qty = flt(r.rejected_qty)
		row.ontime_lines = flt(r.ontime_lines)
		row.dated_lines = flt(r.dated_lines)

	# Price movement: earliest vs latest PR rate per supplier/item within the period
	q = (
		frappe.qb.from_(pri)
		.inner_join(pr)
		.on(pr.name == pri.parent)
		.select(pr.supplier, pri.item_code, pri.rate, pr.posting_date, pr.creation)
		.where(
			(pr.docstatus == 1)
			& (pr.is_return == 0)
			& (pr.company == filters.company)
			& (pr.posting_date.between(filters.from_date, filters.to_date))
		)
		.orderby(pr.posting_date)
		.orderby(pr.creation)
	)
	if filters.supplier:
		q = q.where(pr.supplier == filters.supplier)
	first_last = {}
	for r in q.run(as_dict=True):
		key = (r.supplier, r.item_code)
		if key not in first_last:
			first_last[key] = [flt(r.rate), flt(r.rate)]
		else:
			first_last[key][1] = flt(r.rate)
	for (supplier, _item), (first, last) in first_last.items():
		if first:
			row_for(supplier).price_changes.append((last - first) / first * 100)

	# Quality Inspections against Purchase Receipts
	qi = frappe.qb.DocType("Quality Inspection")
	rejected_case = Case().when(qi.status == "Rejected", 1).else_(0)
	q = (
		frappe.qb.from_(qi)
		.inner_join(pr)
		.on((qi.reference_type == "Purchase Receipt") & (qi.reference_name == pr.name))
		.select(pr.supplier, Count(qi.name).as_("qi_count"), Sum(rejected_case).as_("qi_rejected"))
		.where(
			(qi.docstatus == 1)
			& (pr.company == filters.company)
			& (qi.report_date.between(filters.from_date, filters.to_date))
		)
		.groupby(pr.supplier)
	)
	if filters.supplier:
		q = q.where(pr.supplier == filters.supplier)
	for r in q.run(as_dict=True):
		row = row_for(r.supplier)
		row.qi_count = r.qi_count
		row.qi_rejected = flt(r.qi_rejected)

	if not suppliers:
		return []

	meta = frappe.get_all(
		"Supplier",
		filters={"name": ["in", list(suppliers)]},
		fields=["name", "supplier_name", "is_blacklisted"],
	)
	meta = {m.name: m for m in meta}

	data = []
	for supplier, row in suppliers.items():
		row.supplier_name = meta.get(supplier, {}).get("supplier_name") or supplier
		row.is_blacklisted = meta.get(supplier, {}).get("is_blacklisted") or 0
		row.rejection_pct = row.rejected_qty / row.received_qty * 100 if row.received_qty else 0
		row.ontime_pct = row.ontime_lines / row.dated_lines * 100 if row.dated_lines else 100
		changes = row.pop("price_changes")
		row.avg_price_change_pct = sum(changes) / len(changes) if changes else 0
		row.score = compute_score(row.rejection_pct, row.ontime_pct)
		data.append(row)
	data.sort(key=lambda r: r.score, reverse=True)
	return data


def compute_score(rejection_pct, ontime_pct):
	score = 100 - flt(rejection_pct) * 2 - (100 - flt(ontime_pct)) * 0.5
	return flt(max(0, min(100, score)), 1)


def get_chart(data):
	return {
		"data": {
			"labels": [r.supplier for r in data],
			"datasets": [{"name": _("Rejection %"), "values": [flt(r.rejection_pct, 2) for r in data]}],
		},
		"type": "bar",
		"colors": ["#ff5858"],
	}


def get_summary(data):
	received = sum(r.received_qty for r in data)
	rejected = sum(r.rejected_qty for r in data)
	avg_score = sum(r.score for r in data) / len(data) if data else 0
	return [
		{"value": len(data), "label": _("Suppliers"), "datatype": "Int", "indicator": "Blue"},
		{
			"value": rejected / received * 100 if received else 0,
			"label": _("Overall Rejection %"),
			"datatype": "Percent",
			"indicator": "Red" if rejected else "Green",
		},
		{"value": flt(avg_score, 1), "label": _("Average Score"), "datatype": "Float", "indicator": "Blue"},
	]

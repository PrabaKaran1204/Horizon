# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Data Validation Report: master / transaction data issues found after migration."""

import frappe
from frappe import _
from frappe.query_builder.functions import Count

SEVERITIES = ("High", "Medium", "Low")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	columns = get_columns()
	data = get_data(filters)
	if filters.severity:
		data = [d for d in data if d.severity == filters.severity]
	if filters.entity_type:
		data = [d for d in data if d.entity_type == filters.entity_type]
	return columns, data, None, get_chart(data), get_summary(data)


def get_columns():
	return [
		{"label": _("Entity Type"), "fieldname": "entity_type", "fieldtype": "Data", "width": 130},
		{
			"label": _("Name"),
			"fieldname": "name",
			"fieldtype": "Dynamic Link",
			"options": "entity_type",
			"width": 180,
		},
		{"label": _("Issue"), "fieldname": "issue", "fieldtype": "Data", "width": 320},
		{"label": _("Severity"), "fieldname": "severity", "fieldtype": "Data", "width": 90},
		{"label": _("Suggested Action"), "fieldname": "action", "fieldtype": "Data", "width": 320},
	]


def _row(entity_type, name, issue, severity, action):
	return frappe._dict(entity_type=entity_type, name=name, issue=issue, severity=severity, action=action)


def gstin_is_valid(gstin):
	try:
		from india_compliance.gst_india.utils import validate_gstin

		validate_gstin(gstin)
		return True
	except ImportError:
		return len(gstin or "") == 15
	except Exception:
		return False


def check_parties(data):
	for doctype in ("Customer", "Supplier"):
		if not frappe.db.has_column(doctype, "gstin"):
			continue
		for p in frappe.get_all(doctype, filters={"disabled": 0}, fields=["name", "gstin", "gst_category"]):
			if p.gst_category == "Registered Regular" and not p.gstin:
				data.append(
					_row(
						doctype,
						p.name,
						_("GST category is Registered Regular but GSTIN is empty"),
						"High",
						_("Enter the GSTIN or change the GST category to Unregistered"),
					)
				)
			elif p.gstin and not gstin_is_valid(p.gstin):
				data.append(
					_row(
						doctype,
						p.name,
						_("GSTIN {0} fails format / checksum validation").format(p.gstin),
						"High",
						_("Correct the GSTIN against the GST portal"),
					)
				)


def check_negative_stock(data):
	bin_ = frappe.qb.DocType("Bin")
	for b in (
		frappe.qb.from_(bin_)
		.select(bin_.item_code, bin_.warehouse, bin_.actual_qty)
		.where(bin_.actual_qty < 0)
	).run(as_dict=True):
		data.append(
			_row(
				"Item",
				b.item_code,
				_("Negative stock {0} in {1}").format(b.actual_qty, b.warehouse),
				"High",
				_("Post a Stock Reconciliation or back-dated receipt"),
			)
		)


def check_purchase_invoices(data, company):
	pi = frappe.qb.DocType("Purchase Invoice")
	pii = frappe.qb.DocType("Purchase Invoice Item")
	linked = (
		frappe.qb.from_(pii)
		.select(pii.parent)
		.where(pii.purchase_order.isnotnull() & (pii.purchase_order != ""))
	)
	rows = (
		frappe.qb.from_(pi)
		.select(pi.name, pi.supplier)
		.where((pi.docstatus == 1) & (pi.company == company) & (pi.is_return == 0) & (pi.name.notin(linked)))
	).run(as_dict=True)
	for r in rows:
		data.append(
			_row(
				"Purchase Invoice",
				r.name,
				_("No Purchase Order linked on any line ({0})").format(r.supplier),
				"Medium",
				_("Link the invoice to its Purchase Order or document the direct purchase"),
			)
		)


def check_sales_invoices(data, company):
	si = frappe.qb.DocType("Sales Invoice")
	sii = frappe.qb.DocType("Sales Invoice Item")
	item = frappe.qb.DocType("Item")
	rows = (
		frappe.qb.from_(si)
		.inner_join(sii)
		.on(sii.parent == si.name)
		.inner_join(item)
		.on(item.name == sii.item_code)
		.select(si.name, si.customer)
		.distinct()
		.where(
			(si.docstatus == 1)
			& (si.company == company)
			& (si.is_return == 0)
			& (si.update_stock == 0)
			& (item.is_stock_item == 1)
			& ((sii.delivery_note.isnull()) | (sii.delivery_note == ""))
		)
	).run(as_dict=True)
	for r in rows:
		data.append(
			_row(
				"Sales Invoice",
				r.name,
				_("Stock item invoiced without a Delivery Note ({0})").format(r.customer),
				"Medium",
				_("Create the Delivery Note or enable Update Stock on the invoice"),
			)
		)


def check_items(data):
	item = frappe.qb.DocType("Item")
	reorder = frappe.qb.DocType("Item Reorder")
	with_reorder = frappe.qb.from_(reorder).select(reorder.parent)
	rows = (
		frappe.qb.from_(item)
		.select(item.name)
		.where(
			(item.disabled == 0)
			& (item.is_stock_item == 1)
			& (item.valuation_rate == 0)
			& (item.name.notin(with_reorder))
		)
	).run(as_dict=True)
	for r in rows:
		data.append(
			_row(
				"Item",
				r.name,
				_("Stock item without valuation rate and without reorder level"),
				"Low",
				_("Set a valuation rate (or receive stock) and define a reorder level"),
			)
		)


def check_employees(data, company):
	for e in frappe.get_all(
		"Employee",
		filters={"status": "Active", "company": company, "payroll_cost_center": ["in", ["", None]]},
		fields=["name", "employee_name"],
	):
		data.append(
			_row(
				"Employee",
				e.name,
				_("No payroll cost center ({0})").format(e.employee_name),
				"Medium",
				_("Set Payroll Cost Center on the Employee or its Department"),
			)
		)


def get_data(filters):
	data = []
	check_parties(data)
	check_negative_stock(data)
	check_purchase_invoices(data, filters.company)
	check_sales_invoices(data, filters.company)
	check_items(data)
	check_employees(data, filters.company)
	order = {s: i for i, s in enumerate(SEVERITIES)}
	data.sort(key=lambda r: (order.get(r.severity, 9), r.entity_type, r.name))
	return data


def get_chart(data):
	by_type = {}
	for r in data:
		by_type[r.entity_type] = by_type.get(r.entity_type, 0) + 1
	return {
		"data": {
			"labels": list(by_type.keys()),
			"datasets": [{"name": _("Issues"), "values": list(by_type.values())}],
		},
		"type": "bar",
		"colors": ["#ff5858"],
	}


def get_summary(data):
	counts = {s: sum(1 for r in data if r.severity == s) for s in SEVERITIES}
	indicator = {"High": "Red", "Medium": "Orange", "Low": "Blue"}
	summary = [
		{
			"value": len(data),
			"label": _("Total Issues"),
			"datatype": "Int",
			"indicator": "Red" if data else "Green",
		}
	]
	for s in SEVERITIES:
		summary.append({"value": counts[s], "label": _(s), "datatype": "Int", "indicator": indicator[s]})
	return summary

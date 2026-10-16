# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Net Party Position: receivable vs payable for parties that are both Customer and Supplier."""

import frappe
from erpnext.accounts.utils import get_balance_on
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import cint, flt, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	if filters.party_link_only is None:
		filters.party_link_only = 1
	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, get_chart(data), get_summary(data)


def get_columns():
	return [
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 160,
		},
		{
			"label": _("Supplier"),
			"fieldname": "supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 160,
		},
		{
			"label": _("Party Link"),
			"fieldname": "party_link",
			"fieldtype": "Link",
			"options": "Party Link",
			"width": 110,
		},
		{"label": _("Receivable"), "fieldname": "receivable", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Open Sales Invoices"),
			"fieldname": "open_sales_invoices",
			"fieldtype": "Int",
			"width": 100,
		},
		{"label": _("Payable"), "fieldname": "payable", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Open Purchase Invoices"),
			"fieldname": "open_purchase_invoices",
			"fieldtype": "Int",
			"width": 110,
		},
		{"label": _("Net"), "fieldname": "net", "fieldtype": "Currency", "width": 120},
		{"label": _("Direction"), "fieldname": "direction", "fieldtype": "Data", "width": 120},
		{
			"label": _("Suggested Settlement"),
			"fieldname": "settlement",
			"fieldtype": "Currency",
			"width": 130,
		},
	]


def get_pairs(filters):
	"""(customer, supplier, party_link) tuples from Party Link, plus same-name parties."""
	pairs = {}
	for pl in frappe.get_all(
		"Party Link", fields=["name", "primary_role", "primary_party", "secondary_role", "secondary_party"]
	):
		roles = {pl.primary_role: pl.primary_party, pl.secondary_role: pl.secondary_party}
		if "Customer" in roles and "Supplier" in roles:
			pairs[(roles["Customer"], roles["Supplier"])] = pl.name
	if not cint(filters.party_link_only):
		customer = frappe.qb.DocType("Customer")
		supplier = frappe.qb.DocType("Supplier")
		same = (
			frappe.qb.from_(customer)
			.inner_join(supplier)
			.on(supplier.name == customer.name)
			.select(customer.name)
		).run(pluck=True)
		for name in same:
			pairs.setdefault((name, name), None)
	if filters.party:
		pairs = {k: v for k, v in pairs.items() if filters.party in k}
	return pairs


def get_open_invoice_counts(doctype, party_field, parties, company):
	if not parties:
		return {}
	inv = frappe.qb.DocType(doctype)
	rows = (
		frappe.qb.from_(inv)
		.select(inv[party_field], Count(inv.name).as_("cnt"))
		.where(
			(inv.docstatus == 1)
			& (inv.company == company)
			& (inv[party_field].isin(parties))
			& (inv.outstanding_amount != 0)
		)
		.groupby(inv[party_field])
	).run(as_dict=True)
	return {r[party_field]: r.cnt for r in rows}


def get_data(filters):
	pairs = get_pairs(filters)
	if not pairs:
		return []
	customers = list({c for c, _s in pairs})
	suppliers = list({s for _c, s in pairs})
	si_counts = get_open_invoice_counts("Sales Invoice", "customer", customers, filters.company)
	pi_counts = get_open_invoice_counts("Purchase Invoice", "supplier", suppliers, filters.company)
	as_on = filters.as_on or nowdate()

	data = []
	for (customer, supplier), link in pairs.items():
		receivable = flt(
			get_balance_on(
				party_type="Customer",
				party=customer,
				company=filters.company,
				date=as_on,
				ignore_account_permission=True,
			)
		)
		# supplier balances are credit (negative) in GL terms; present payable as positive
		payable = -flt(
			get_balance_on(
				party_type="Supplier",
				party=supplier,
				company=filters.company,
				date=as_on,
				ignore_account_permission=True,
			)
		)
		net = receivable - payable
		data.append(
			frappe._dict(
				customer=customer,
				supplier=supplier,
				party_link=link,
				receivable=receivable,
				open_sales_invoices=cint(si_counts.get(customer)),
				payable=payable,
				open_purchase_invoices=cint(pi_counts.get(supplier)),
				net=net,
				direction="Net Receivable" if net >= 0 else "Net Payable",
				settlement=abs(net),
			)
		)
	data.sort(key=lambda r: abs(r.net), reverse=True)
	return data


def get_chart(data):
	return {
		"data": {
			"labels": [r.customer for r in data],
			"datasets": [
				{"name": _("Receivable"), "values": [flt(r.receivable, 2) for r in data]},
				{"name": _("Payable"), "values": [flt(r.payable, 2) for r in data]},
			],
		},
		"type": "bar",
		"colors": ["#29cd42", "#ff5858"],
	}


def get_summary(data):
	receivable = sum(r.receivable for r in data)
	payable = sum(r.payable for r in data)
	return [
		{"value": receivable, "label": _("Total Receivable"), "datatype": "Currency", "indicator": "Green"},
		{"value": payable, "label": _("Total Payable"), "datatype": "Currency", "indicator": "Red"},
		{
			"value": receivable - payable,
			"label": _("Net Position"),
			"datatype": "Currency",
			"indicator": "Blue",
		},
		{"value": len(data), "label": _("Linked Parties"), "datatype": "Int", "indicator": "Blue"},
	]

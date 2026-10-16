# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Asset Register with Maintenance: NBV, maintenance spend and replacement candidates."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe import _
from frappe.query_builder.functions import Max, Sum
from frappe.utils import cint, flt, nowdate

EXCLUDED_STATUSES = ("Scrapped", "Sold", "Capitalized", "Decapitalized")
MAINTENANCE_PCT_LIMIT = 20
NBV_PCT_LIMIT = 5


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	try:
		filters.fy_start, filters.fy_end = get_fiscal_year(nowdate(), company=filters.company)[1:3]
	except Exception:
		filters.fy_start, filters.fy_end = f"{nowdate()[:4]}-01-01", f"{nowdate()[:4]}-12-31"
	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, get_chart(data), get_summary(data)


def get_columns():
	return [
		{"label": _("Asset"), "fieldname": "asset", "fieldtype": "Link", "options": "Asset", "width": 130},
		{"label": _("Asset Name"), "fieldname": "asset_name", "fieldtype": "Data", "width": 150},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
		{
			"label": _("Category"),
			"fieldname": "asset_category",
			"fieldtype": "Link",
			"options": "Asset Category",
			"width": 120,
		},
		{
			"label": _("Location"),
			"fieldname": "location",
			"fieldtype": "Link",
			"options": "Location",
			"width": 110,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Purchase Date"), "fieldname": "purchase_date", "fieldtype": "Date", "width": 100},
		{"label": _("Gross Cost"), "fieldname": "gross_cost", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Accumulated Depreciation"),
			"fieldname": "accumulated_depreciation",
			"fieldtype": "Currency",
			"width": 130,
		},
		{"label": _("NBV"), "fieldname": "nbv", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Last Maintenance"),
			"fieldname": "last_maintenance_date",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("Maintenance Cost YTD"),
			"fieldname": "maintenance_cost_ytd",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Maintenance % of NBV"),
			"fieldname": "maintenance_pct",
			"fieldtype": "Percent",
			"width": 120,
		},
		{
			"label": _("Replacement Candidate"),
			"fieldname": "replacement_candidate",
			"fieldtype": "Check",
			"width": 110,
		},
	]


def get_data(filters):
	asset_filters = {"company": filters.company, "docstatus": 1}
	if filters.asset_category:
		asset_filters["asset_category"] = filters.asset_category
	if filters.location:
		asset_filters["location"] = filters.location
	if not cint(filters.include_disposed):
		asset_filters["status"] = ["not in", EXCLUDED_STATUSES]
	assets = frappe.get_all(
		"Asset",
		filters=asset_filters,
		fields=[
			"name",
			"asset_name",
			"item_code",
			"asset_category",
			"location",
			"status",
			"purchase_date",
			"gross_purchase_amount",
			"total_asset_cost",
			"opening_accumulated_depreciation",
			"value_after_depreciation",
			"calculate_depreciation",
		],
		order_by="purchase_date asc, name asc",
	)
	if not assets:
		return []
	names = [a.name for a in assets]

	booked = get_booked_depreciation(names)
	last_maintenance = get_last_maintenance(names)
	repair_cost = get_repair_cost(names, filters)

	data = []
	for a in assets:
		gross = flt(a.total_asset_cost) or flt(a.gross_purchase_amount)
		accumulated = flt(a.opening_accumulated_depreciation) + flt(booked.get(a.name))
		if (
			cint(a.calculate_depreciation)
			and a.value_after_depreciation is not None
			and not booked.get(a.name)
		):
			# no booked schedule rows yet: trust the asset's own value_after_depreciation
			accumulated = max(
				gross - flt(a.value_after_depreciation), flt(a.opening_accumulated_depreciation)
			)
		nbv = gross - accumulated
		maintenance = flt(repair_cost.get(a.name))
		maintenance_pct = maintenance / nbv * 100 if nbv > 0 else (100.0 if maintenance else 0.0)
		data.append(
			frappe._dict(
				asset=a.name,
				asset_name=a.asset_name,
				item_code=a.item_code,
				asset_category=a.asset_category,
				location=a.location,
				status=a.status,
				purchase_date=a.purchase_date,
				gross_cost=gross,
				accumulated_depreciation=accumulated,
				nbv=nbv,
				last_maintenance_date=last_maintenance.get(a.name),
				maintenance_cost_ytd=maintenance,
				maintenance_pct=flt(maintenance_pct, 1),
				replacement_candidate=int(
					maintenance_pct > MAINTENANCE_PCT_LIMIT or (gross and nbv < gross * NBV_PCT_LIMIT / 100)
				),
			)
		)
	return data


def get_booked_depreciation(asset_names):
	ads = frappe.qb.DocType("Asset Depreciation Schedule")
	ds = frappe.qb.DocType("Depreciation Schedule")
	rows = (
		frappe.qb.from_(ds)
		.inner_join(ads)
		.on(ads.name == ds.parent)
		.select(ads.asset, Sum(ds.depreciation_amount).as_("amount"))
		.where(
			(ads.docstatus == 1)
			& (ads.asset.isin(asset_names))
			& (ds.journal_entry.isnotnull())
			& (ds.journal_entry != "")
		)
		.groupby(ads.asset)
	).run(as_dict=True)
	return {r.asset: flt(r.amount) for r in rows}


def get_last_maintenance(asset_names):
	aml = frappe.qb.DocType("Asset Maintenance Log")
	am = frappe.qb.DocType("Asset Maintenance")
	rows = (
		frappe.qb.from_(aml)
		.inner_join(am)
		.on(am.name == aml.asset_maintenance)
		.select(am.asset_name.as_("asset"), Max(aml.completion_date).as_("last_date"))
		.where(
			(aml.docstatus < 2) & (aml.maintenance_status == "Completed") & (am.asset_name.isin(asset_names))
		)
		.groupby(am.asset_name)
	).run(as_dict=True)
	return {r.asset: r.last_date for r in rows}


def get_repair_cost(asset_names, filters):
	ar = frappe.qb.DocType("Asset Repair")
	rows = (
		frappe.qb.from_(ar)
		.select(ar.asset, Sum(ar.total_repair_cost).as_("cost"))
		.where(
			(ar.docstatus == 1)
			& (ar.asset.isin(asset_names))
			& (ar.completion_date.between(filters.fy_start, filters.fy_end))
		)
		.groupby(ar.asset)
	).run(as_dict=True)
	return {r.asset: flt(r.cost) for r in rows}


def get_chart(data):
	by_category = {}
	for r in data:
		entry = by_category.setdefault(r.asset_category or _("Uncategorised"), [0.0, 0.0])
		entry[0] += r.nbv
		entry[1] += r.maintenance_cost_ytd
	return {
		"data": {
			"labels": list(by_category.keys()),
			"datasets": [
				{"name": _("NBV"), "values": [flt(v[0], 2) for v in by_category.values()]},
				{"name": _("Maintenance YTD"), "values": [flt(v[1], 2) for v in by_category.values()]},
			],
		},
		"type": "bar",
		"colors": ["#5e64ff", "#ff5858"],
	}


def get_summary(data):
	candidates = sum(r.replacement_candidate for r in data)
	return [
		{"value": len(data), "label": _("Assets"), "datatype": "Int", "indicator": "Blue"},
		{
			"value": sum(r.gross_cost for r in data),
			"label": _("Gross Cost"),
			"datatype": "Currency",
			"indicator": "Blue",
		},
		{
			"value": sum(r.nbv for r in data),
			"label": _("Net Book Value"),
			"datatype": "Currency",
			"indicator": "Green",
		},
		{
			"value": sum(r.maintenance_cost_ytd for r in data),
			"label": _("Maintenance YTD"),
			"datatype": "Currency",
			"indicator": "Orange",
		},
		{
			"value": candidates,
			"label": _("Replacement Candidates"),
			"datatype": "Int",
			"indicator": "Red" if candidates else "Green",
		},
	]

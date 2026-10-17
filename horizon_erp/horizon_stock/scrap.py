# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Bulk "Mark for Scrap" action used by the Inventory Obsolescence Analysis report."""

import json

import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_dimensions
from frappe import _
from frappe.utils import flt

ALLOWED_ROLES = ("System Manager", "Stock Manager", "Operations Head")
SCRAP_REASONS = ("Obsolete", "Damaged", "Expired", "Slow-moving")


@frappe.whitelist()
def mark_for_scrap(rows, reason, scrap_warehouse=None, scrap_pct=100):
	"""Create ONE draft Stock Entry moving (or issuing) the selected stock for scrapping.

	:param rows: JSON list of ``{"item_code", "warehouse", "actual_qty"}``
	:param reason: one of ``SCRAP_REASONS``
	:param scrap_warehouse: target warehouse -> Material Transfer; empty -> Material Issue
	:param scrap_pct: percentage of ``actual_qty`` to scrap (default 100)
	:returns: name of the draft Stock Entry
	"""
	if not set(frappe.get_roles()) & set(ALLOWED_ROLES):
		frappe.throw(_("Only Stock Manager, Operations Head or System Manager can mark stock for scrap."))
	frappe.has_permission("Stock Entry", "create", throw=True)

	if isinstance(rows, str):
		rows = json.loads(rows)
	rows = [frappe._dict(r) for r in (rows or []) if r]
	if not rows:
		frappe.throw(_("No rows selected."))
	if reason not in SCRAP_REASONS:
		frappe.throw(_("Invalid scrap reason: {0}").format(reason))

	scrap_pct = flt(scrap_pct) or 100
	if scrap_pct <= 0 or scrap_pct > 100:
		frappe.throw(_("Scrap Qty % must be between 0 and 100."))

	source_warehouses = {r.warehouse for r in rows if r.warehouse}
	if not source_warehouses:
		frappe.throw(_("Selected rows have no warehouse."))

	companies = set(
		frappe.get_all("Warehouse", filters={"name": ["in", list(source_warehouses)]}, pluck="company")
	)
	if len(companies) != 1:
		frappe.throw(_("All selected warehouses must belong to the same company."))
	company = companies.pop()

	if scrap_warehouse:
		if frappe.db.get_value("Warehouse", scrap_warehouse, "company") != company:
			frappe.throw(_("Scrap warehouse {0} does not belong to {1}.").format(scrap_warehouse, company))

	company_doc = frappe.get_cached_doc("Company", company)
	abbr = company_doc.abbr
	expense_account = _first_existing("Account", [f"Scrap Loss - {abbr}"], company) or (
		company_doc.stock_adjustment_account
	)
	cost_center = _first_existing("Cost Center", [f"Admin - {abbr}"], company) or company_doc.cost_center

	dimension_defaults = get_default_dimensions(company)
	se = frappe.new_doc("Stock Entry")
	se.company = company
	se.update(dimension_defaults)
	se.stock_entry_type = se.purpose = "Material Transfer" if scrap_warehouse else "Material Issue"
	se.remarks = _("Marked for scrap from Inventory Obsolescence Analysis: {0}").format(reason)
	if scrap_warehouse:
		se.to_warehouse = scrap_warehouse

	# collapse duplicate (item, warehouse) selections
	seen = {}
	for r in rows:
		key = (r.item_code, r.warehouse)
		seen[key] = max(flt(seen.get(key)), flt(r.actual_qty))

	for (item_code, warehouse), actual_qty in seen.items():
		qty = flt(actual_qty) * scrap_pct / 100.0
		if qty <= 0:
			continue
		se.append(
			"items",
			{
				"item_code": item_code,
				"s_warehouse": warehouse,
				"t_warehouse": scrap_warehouse,
				"qty": qty,
				"expense_account": expense_account if not scrap_warehouse else None,
				"cost_center": cost_center,
				**dimension_defaults,
			},
		)
	if not se.items:
		frappe.throw(_("Nothing to scrap: all selected quantities are zero."))

	se.insert()
	return se.name


def get_default_dimensions(company):
	"""Company defaults for Accounting Dimensions (e.g. Branch) so the draft can be submitted as-is."""
	try:
		_dimensions, defaults = get_dimensions()
	except Exception:
		return {}
	return {k: v for k, v in (defaults.get(company) or {}).items() if v}


def _first_existing(doctype, names, company):
	for name in names:
		if frappe.db.exists(doctype, {"name": name, "company": company}):
			return name
	return None

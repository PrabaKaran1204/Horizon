# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Warehouse User Permissions applied where Frappe does not apply them itself.

Frappe trims list views and report rows by a Warehouse User Permission through link fields on the
parent document and on report columns only. Two gaps remained for the Delhi warehouse manager:

- documents that carry the warehouse on their item rows only (a Delivery Note without *Set Source
  Warehouse*) were listed although opening them is refused -> ``permission_query_conditions``
  below hide every document that has a row in a warehouse the user may not read;
- Horizon reports and number cards that aggregate Bin / Stock Ledger Entry themselves (summary
  totals, Aging Stock Value, Stock Turnover) returned company-wide figures -> they filter by
  ``get_permitted_warehouses``.
"""

import frappe
import frappe.permissions
from frappe.utils import cint

# parent DocType -> (item-row DocType, warehouse fields on the row)
ROW_WAREHOUSE_FIELDS = {
	"Delivery Note": ("Delivery Note Item", ("warehouse", "target_warehouse")),
	"Purchase Receipt": ("Purchase Receipt Item", ("warehouse", "rejected_warehouse")),
	"Stock Entry": ("Stock Entry Detail", ("s_warehouse", "t_warehouse")),
}


def get_leaf_warehouses(warehouse: str) -> list[str]:
	"""Leaf warehouses under ``warehouse`` (itself when it is a leaf)."""
	wh = frappe.db.get_value("Warehouse", warehouse, ["is_group", "lft", "rgt"], as_dict=True)
	if not wh:
		return []
	if not cint(wh.is_group):
		return [warehouse]
	return frappe.get_all(
		"Warehouse",
		filters={"lft": [">=", wh.lft], "rgt": ["<=", wh.rgt], "is_group": 0, "disabled": 0},
		pluck="name",
		order_by="lft asc",
	)


def get_permitted_warehouses(user: str | None = None, doctype: str = "Bin") -> set[str] | None:
	"""Leaf warehouses the user may read, or ``None`` when the user is unrestricted.

	Unrestricted: Administrator, System Manager, or no User Permission on Warehouse at all. A
	permission on a group warehouse covers every leaf below it (``hide_descendants`` limits it to
	the record itself); permissions restricted via ``applicable_for`` to another DocType than
	``doctype`` are ignored.
	"""
	user = user or frappe.session.user
	if not user or user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return None
	entries = frappe.permissions.get_user_permissions(user).get("Warehouse") or []
	entries = [e for e in entries if not e.get("applicable_for") or e.get("applicable_for") == doctype]
	if not entries:
		return None
	allowed: set[str] = set()
	for entry in entries:
		if entry.get("hide_descendants"):
			allowed.add(entry.doc)
		else:
			allowed.update(get_leaf_warehouses(entry.doc))
	return allowed


def row_warehouse_condition(doctype, user=None):
	"""SQL condition hiding ``doctype`` documents with a row in a warehouse the user may not read."""
	allowed = get_permitted_warehouses(user, doctype)
	if allowed is None:
		return ""
	child, fields = ROW_WAREHOUSE_FIELDS[doctype]
	values = ", ".join(frappe.db.escape(w) for w in sorted(allowed)) or "''"
	outside = " or ".join(f"(ifnull(row.`{f}`, '') != '' and row.`{f}` not in ({values}))" for f in fields)
	return (
		f"not exists (select 1 from `tab{child}` row where row.parent = `tab{doctype}`.name "
		f"and row.parenttype = {frappe.db.escape(doctype)} and ({outside}))"
	)


def delivery_note_query(user=None, doctype=None):
	return row_warehouse_condition("Delivery Note", user)


def purchase_receipt_query(user=None, doctype=None):
	return row_warehouse_condition("Purchase Receipt", user)


def stock_entry_query(user=None, doctype=None):
	return row_warehouse_condition("Stock Entry", user)

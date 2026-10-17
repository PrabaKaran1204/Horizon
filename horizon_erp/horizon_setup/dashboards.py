# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Custom Number Card sources for the Horizon workspaces and the workspace consistency check.

Number Cards / Dashboard Charts / Workspaces themselves are standard JSON records under
``horizon_erp/<module>/{number_card,dashboard_chart,workspace}/`` (synced by ``bench migrate`` and
exported as fixtures). Only the cards that cannot be expressed as a Document Type aggregate call
the whitelisted functions below (``Number Card.type = "Custom"``, ``method = <dotted path>``).

Every function follows the contract Frappe expects for custom cards:
``def fn(filters=None) -> {"value": <number>, "fieldtype": "Int" | "Currency" | "Float" | "Percent"}``.
"""

import frappe
from frappe import _
from frappe.query_builder import CustomFunction
from frappe.query_builder.functions import Coalesce, Count, Sum
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate

DateDiff = CustomFunction("DATEDIFF", ["end", "start"])
AGING_DAYS = 90
TURNOVER_DAYS = 90
PIPELINE_DAYS = 90


def _company(filters):
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	if isinstance(filters, list):  # [[doctype, field, op, value], ...]
		for f in filters:
			if len(f) >= 4 and f[1] == "company":
				return f[3]
		filters = {}
	return filters.get("company") or frappe.defaults.get_user_default("Company")


@frappe.whitelist()
def get_items_below_reorder(filters=None):
	"""Items whose projected qty in a warehouse is below the Item Reorder level set for it."""
	frappe.has_permission("Item", throw=True)
	reorder = frappe.qb.DocType("Item Reorder")
	bin_ = frappe.qb.DocType("Bin")
	item = frappe.qb.DocType("Item")
	count = (
		frappe.qb.from_(reorder)
		.inner_join(item)
		.on((item.name == reorder.parent) & (item.disabled == 0))
		.left_join(bin_)
		.on((bin_.item_code == reorder.parent) & (bin_.warehouse == reorder.warehouse))
		.select(Count(reorder.parent).distinct())
		.where(Coalesce(bin_.projected_qty, 0) < reorder.warehouse_reorder_level)
	).run()
	return {"value": cint(count[0][0]) if count else 0, "fieldtype": "Int"}


@frappe.whitelist()
def get_pos_pending_over_24h(filters=None):
	"""Draft Purchase Orders sitting in a 'Pending ...' workflow state for more than 24 hours."""
	frappe.has_permission("Purchase Order", throw=True)
	po = frappe.qb.DocType("Purchase Order")
	cutoff = add_days(now_datetime(), -1)
	q = (
		frappe.qb.from_(po)
		.select(Count(po.name))
		.where(
			(po.docstatus == 0)
			& (po.workflow_state.like("Pending%"))
			& (Coalesce(po.pending_since, po.creation) <= cutoff)
		)
	)
	company = _company(filters)
	if company:
		q = q.where(po.company == company)
	return {"value": cint(q.run()[0][0]), "fieldtype": "Int"}


@frappe.whitelist()
def get_aging_stock_value(filters=None):
	"""Inventory value not sold for more than 90 days (same logic as Inventory Obsolescence Analysis)."""
	frappe.has_permission("Bin", throw=True)
	from horizon_erp.horizon_stock.report.inventory_obsolescence_analysis.inventory_obsolescence_analysis import (
		get_data,
	)

	company = _company(filters)
	rows = get_data(frappe._dict(company=company, days_threshold=AGING_DAYS)) if company else []
	value = sum(flt(r.inventory_value) for r in rows if r.days_since_last_sale > AGING_DAYS)
	return {"value": value, "fieldtype": "Currency"}


@frappe.whitelist()
def get_stock_turnover(filters=None):
	"""Outgoing stock value over the last 90 days divided by the average stock value in that window."""
	frappe.has_permission("Stock Ledger Entry", throw=True)
	company = _company(filters)
	if not company:
		return {"value": 0, "fieldtype": "Float"}
	sle = frappe.qb.DocType("Stock Ledger Entry")
	start = add_days(nowdate(), -TURNOVER_DAYS)
	base = frappe.qb.from_(sle).where(
		(sle.is_cancelled == 0) & (sle.company == company) & (sle.posting_date >= start)
	)
	outgoing = flt(
		base.select(Sum(-sle.stock_value_difference))
		.where(
			(sle.actual_qty < 0) & (sle.voucher_type.isin(["Delivery Note", "Sales Invoice", "Stock Entry"]))
		)
		.run()[0][0]
	)
	net_change = flt(base.select(Sum(sle.stock_value_difference)).run()[0][0])
	bin_ = frappe.qb.DocType("Bin")
	wh = frappe.qb.DocType("Warehouse")
	current = flt(
		frappe.qb.from_(bin_)
		.inner_join(wh)
		.on(wh.name == bin_.warehouse)
		.select(Sum(bin_.stock_value))
		.where(wh.company == company)
		.run()[0][0]
	)
	opening = current - net_change
	average = (current + opening) / 2
	return {"value": flt(outgoing / average, 2) if average > 0 else 0, "fieldtype": "Float"}


@frappe.whitelist()
def get_quote_to_order_conversion(filters=None):
	"""Share of submitted Quotations (last 90 days) that became Sales Orders."""
	frappe.has_permission("Quotation", throw=True)
	company = _company(filters)
	start = add_days(nowdate(), -PIPELINE_DAYS)
	base = {"docstatus": 1, "transaction_date": [">=", start]}
	if company:
		base["company"] = company
	total = frappe.db.count("Quotation", base)
	ordered = frappe.db.count("Quotation", {**base, "status": "Ordered"})
	return {"value": flt(ordered / total * 100, 1) if total else 0, "fieldtype": "Percent"}


@frappe.whitelist()
def get_avg_days_quote_to_so(filters=None):
	"""Average days between a Quotation and the Sales Order created from it (last 90 days)."""
	frappe.has_permission("Sales Order", throw=True)
	company = _company(filters)
	so = frappe.qb.DocType("Sales Order")
	soi = frappe.qb.DocType("Sales Order Item")
	qtn = frappe.qb.DocType("Quotation")
	start = add_days(nowdate(), -PIPELINE_DAYS)
	sub = (
		frappe.qb.from_(soi)
		.inner_join(so)
		.on(so.name == soi.parent)
		.inner_join(qtn)
		.on(qtn.name == soi.prevdoc_docname)
		.select(so.name.as_("so"), DateDiff(so.transaction_date, qtn.transaction_date).as_("days"))
		.distinct()
		.where((so.docstatus == 1) & (so.transaction_date >= start))
	)
	if company:
		sub = sub.where(so.company == company)
	rows = sub.run(as_dict=True)
	days = [flt(r.days) for r in rows]
	return {"value": flt(sum(days) / len(days), 1) if days else 0, "fieldtype": "Float"}


@frappe.whitelist()
def get_work_orders_overdue(filters=None):
	"""Open Work Orders (not Completed / Stopped / Cancelled / Closed) whose planned end date has passed."""
	frappe.has_permission("Work Order", throw=True)
	wo = frappe.qb.DocType("Work Order")
	q = (
		frappe.qb.from_(wo)
		.select(Count(wo.name))
		.where(
			(wo.docstatus == 1)
			& (wo.status.notin(["Completed", "Stopped", "Cancelled", "Closed"]))
			& (wo.planned_end_date.isnotnull())
			& (wo.planned_end_date < nowdate())
		)
	)
	company = _company(filters)
	if company:
		q = q.where(wo.company == company)
	return {"value": cint(q.run()[0][0]), "fieldtype": "Int"}


@frappe.whitelist()
def get_line_utilisation_today(filters=None):
	"""Booked machine hours of open Work Orders today across every line, as a % of line capacity
	(same booking / capacity logic as the Capacity Utilisation and Sequence report)."""
	frappe.has_permission("Work Order", throw=True)
	from horizon_erp.horizon_manufacturing.report.capacity_utilisation_and_sequence.capacity_utilisation_and_sequence import (
		get_capacity_rows,
		get_open_work_orders,
		get_workstations,
	)

	company = _company(filters)
	if not company:
		return {"value": 0, "fieldtype": "Percent"}
	today = getdate(nowdate())
	report_filters = frappe._dict(company=company, from_date=today, to_date=today, workstation=None)
	workstations = get_workstations(report_filters)
	rows = get_capacity_rows(report_filters, workstations, get_open_work_orders(report_filters))
	capacity = sum(flt(r.capacity_hours) for r in rows)
	booked = sum(flt(r.booked_hours) for r in rows)
	return {"value": flt(booked / capacity * 100, 1) if capacity else 0, "fieldtype": "Percent"}


PARENT_WORKSPACE = "Horizon ERP"
LINK_DOCTYPES = ("DocType", "Report", "Page")


def get_workspace_problems():
	"""Every inconsistency of the Horizon workspaces as a list of strings (empty = consistent).

	Checks: icon set, parent (*Horizon ERP* is the only top-level one, every other workspace is its
	child), every Number Card / Dashboard Chart / DocType / Report / Page they reference exists,
	every ``/app/<route>`` URL shortcut resolves to a Horizon workspace and every content block
	points at a row of the matching child table."""
	problems = []
	names = frappe.get_all("Workspace", filters={"name": ["like", "Horizon%"]}, pluck="name")
	routes = {n.lower().replace(" ", "-"): n for n in names}  # frappe.router.slug of the title
	if PARENT_WORKSPACE not in names:
		problems.append(f"missing parent Workspace {PARENT_WORKSPACE}")
	for name in names:
		ws = frappe.get_doc("Workspace", name)
		if not ws.icon:
			problems.append(f"{name}: no icon")
		expected_parent = "" if name == PARENT_WORKSPACE else PARENT_WORKSPACE
		if (ws.parent_page or "") != expected_parent:
			problems.append(f"{name}: parent_page {ws.parent_page!r}, expected {expected_parent!r}")
		for card in ws.number_cards:
			if not frappe.db.exists("Number Card", card.number_card_name):
				problems.append(f"{name}: missing Number Card {card.number_card_name}")
		for chart in ws.charts:
			if not frappe.db.exists("Dashboard Chart", chart.chart_name):
				problems.append(f"{name}: missing Dashboard Chart {chart.chart_name}")
		for link in ws.links:
			if link.type == "Link" and not (
				link.link_type in LINK_DOCTYPES and frappe.db.exists(link.link_type, link.link_to)
			):
				problems.append(f"{name}: missing {link.link_type} {link.link_to}")
		for shortcut in ws.shortcuts:
			if shortcut.type == "URL":
				route = (shortcut.url or "").removeprefix("/app/")
				if route not in routes:
					problems.append(f"{name}: shortcut {shortcut.label} points to unknown {shortcut.url}")
			elif not frappe.db.exists(shortcut.type, shortcut.link_to):
				problems.append(f"{name}: missing {shortcut.type} {shortcut.link_to}")
		problems.extend(_content_problems(ws))
	return problems


def _content_problems(ws):
	# The desk resolves number_card / chart / shortcut / card blocks by the *label* of the child row
	# (frappe/public/js/frappe/views/workspace/blocks/block.js make()), not by the record name.
	rows = {
		"number_card": ("number_card_name", {c.label or c.number_card_name for c in ws.number_cards}),
		"chart": ("chart_name", {c.label or c.chart_name for c in ws.charts}),
		"shortcut": ("shortcut_name", {s.label for s in ws.shortcuts}),
		"card": ("card_name", {lnk.label for lnk in ws.links if lnk.type == "Card Break"}),
	}
	problems = []
	used = {kind: set() for kind in rows}
	for block in frappe.parse_json(ws.content or "[]"):
		if block.get("type") in rows:
			key, available = rows[block["type"]]
			value = block["data"].get(key)
			used[block["type"]].add(value)
			if value not in available:
				problems.append(f"{ws.name}: {block['type']} block {value!r} has no matching row")
	for kind, (_key, available) in rows.items():
		for missing in available - used[kind]:
			problems.append(f"{ws.name}: {kind} {missing!r} is not placed in the content")
	return problems


def setup_dashboards():
	"""Validate the Horizon workspaces (see ``get_workspace_problems``). Standard JSON records are
	created by ``bench migrate``; this helper is a post-migrate sanity check that can be run with
	``bench --site <site> execute horizon_erp.horizon_setup.dashboards.setup_dashboards``."""
	problems = get_workspace_problems()
	if problems:
		frappe.throw(_("Horizon workspace validation failed:\n{0}").format("\n".join(problems)))
	return _("All Horizon workspaces are consistent.")

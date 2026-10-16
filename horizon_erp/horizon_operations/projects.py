# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Projects document event handlers (Timesheet, Task)."""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_link_to_form, getdate, nowdate

from horizon_erp.horizon_operations import config

MILESTONE_ITEM_CODE = "PROJ-MILESTONE"
MILESTONE_ITEM_SAC = "998731"
STANDARD_HOURS_PER_DAY = 8


# ---------------------------------------------------------------------------------------------
# Timesheet
# ---------------------------------------------------------------------------------------------
def validate_timesheet(doc, method=None):
	"""Timesheet ``validate`` hook.

	- Rows are grouped by the calendar date of ``from_time``; when a day's total exceeds 8 h every
	  row of that day is flagged ``is_overtime`` (the whole day is reviewed, not just the excess).
	- On submit (``docstatus`` == 1, since on_submit is not hooked) the affected projects'
	  ``overhead_amount`` is recomputed best-effort. Project totals are refreshed by ERPNext after
	  this hook, so the rows of this timesheet are added in explicitly.
	"""
	flag_overtime(doc)
	if doc.docstatus == 1:
		recompute_project_overhead(doc)


def flag_overtime(doc):
	hours_by_date = {}
	for row in doc.get("time_logs", []):
		day = getdate(row.from_time) if row.from_time else getdate(doc.get("start_date") or nowdate())
		hours_by_date[day] = hours_by_date.get(day, 0) + flt(row.hours)

	overtime_days = {d: h for d, h in hours_by_date.items() if h > STANDARD_HOURS_PER_DAY}
	for row in doc.get("time_logs", []):
		day = getdate(row.from_time) if row.from_time else getdate(doc.get("start_date") or nowdate())
		row.is_overtime = cint(day in overtime_days)

	if overtime_days:
		summary = ", ".join(
			_("{0}: {1} h").format(frappe.format(d, {"fieldtype": "Date"}), flt(h, 2))
			for d, h in sorted(overtime_days.items())
		)
		frappe.msgprint(
			_("Overtime flagged (more than {0} h/day): {1}").format(STANDARD_HOURS_PER_DAY, summary),
			indicator="orange",
			alert=True,
		)


def recompute_project_overhead(doc):
	projects = {row.project for row in doc.get("time_logs", []) if row.get("project")}
	if doc.get("parent_project"):
		projects.add(doc.parent_project)
	for project in projects:
		values = frappe.db.get_value(
			"Project",
			project,
			["total_costing_amount", "total_consumed_material_cost", "overhead_percent"],
			as_dict=True,
		)
		if not values:
			continue
		this_doc_costing = sum(flt(r.costing_amount) for r in doc.time_logs if r.get("project") == project)
		base = flt(values.total_costing_amount) + flt(values.total_consumed_material_cost) + this_doc_costing
		overhead = flt(base * flt(values.overhead_percent) / 100, 2)
		frappe.db.set_value("Project", project, "overhead_amount", overhead, update_modified=False)


# ---------------------------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------------------------
def on_update_task(doc, method=None):
	"""Task ``on_update`` hook: a completed milestone task with ``billing_percent`` raises ONE
	draft milestone Sales Invoice (linked back in ``milestone_invoice``)."""
	if not (
		cint(doc.get("is_milestone"))
		and doc.status == "Completed"
		and flt(doc.get("billing_percent")) > 0
		and not doc.get("milestone_invoice")
		and doc.get("project")
	):
		return

	try:
		si = create_milestone_invoice(doc)
	except Exception:
		frappe.log_error(title=f"Milestone invoice failed for {doc.name}", message=frappe.get_traceback())
		frappe.msgprint(
			_("The milestone Sales Invoice could not be created automatically; see Error Log."),
			indicator="orange",
			alert=True,
		)
		return
	if not si:
		return

	doc.db_set("milestone_invoice", si.name, update_modified=False)
	doc.milestone_invoice = si.name
	link = get_link_to_form("Sales Invoice", si.name)
	frappe.msgprint(_("Draft milestone invoice {0} created").format(link), alert=True)


def get_milestone_base_amount(project):
	if project.sales_order:
		so_total = flt(frappe.db.get_value("Sales Order", project.sales_order, "grand_total"))
		if so_total:
			return so_total
	return flt(project.estimated_costing) * (1 + flt(project.overhead_percent) / 100)


def create_milestone_invoice(task):
	project = frappe.db.get_value(
		"Project",
		task.project,
		[
			"name",
			"customer",
			"sales_order",
			"estimated_costing",
			"overhead_percent",
			"company",
			"cost_center",
		],
		as_dict=True,
	)
	if not project:
		return None
	customer = project.customer
	if not customer and project.sales_order:
		customer = frappe.db.get_value("Sales Order", project.sales_order, "customer")
	if not customer:
		frappe.msgprint(
			_("Project {0} has no customer; milestone invoice for task {1} was not created").format(
				project.name, task.name
			),
			indicator="orange",
			alert=True,
		)
		return None

	base_amount = get_milestone_base_amount(project)
	rate = flt(base_amount * flt(task.billing_percent) / 100, 2)
	if rate <= 0:
		frappe.msgprint(
			_(
				"Project {0} has neither a Sales Order total nor an estimated cost; milestone invoice "
				"skipped"
			).format(project.name),
			indicator="orange",
			alert=True,
		)
		return None

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = project.company
	si.project = project.name
	si.remarks = _("Milestone billing: {0} ({1}%)").format(task.subject, flt(task.billing_percent))
	si.append(
		"items",
		{
			"item_code": ensure_milestone_item(),
			"qty": 1,
			"rate": rate,
			"description": _("Milestone: {0}").format(task.subject),
			"project": project.name,
			"cost_center": project.cost_center,
		},
	)
	si.flags.ignore_permissions = True
	si.set_missing_values()
	config.apply_default_dimensions(si)
	si.insert()
	return si


def ensure_milestone_item():
	if frappe.db.exists("Item", MILESTONE_ITEM_CODE):
		return MILESTONE_ITEM_CODE
	item = frappe.new_doc("Item")
	item.item_code = MILESTONE_ITEM_CODE
	item.item_name = "Project Milestone Billing"
	item.item_group = "Services" if frappe.db.exists("Item Group", "Services") else "All Item Groups"
	item.stock_uom = "Nos"
	item.is_stock_item = 0
	item.include_item_in_manufacturing = 0
	item.description = "Milestone billing for project work (service, non-stock)"
	if item.meta.has_field("gst_hsn_code") and frappe.db.exists("GST HSN Code", MILESTONE_ITEM_SAC):
		item.gst_hsn_code = MILESTONE_ITEM_SAC
	item.flags.ignore_permissions = True
	item.insert()
	return item.name

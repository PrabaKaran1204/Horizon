# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Manufacturing document event handlers (Work Order)."""

import math

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, date_diff, flt, getdate, nowdate

from horizon_erp.horizon_operations import config

OPEN_WO_STATUSES = ("Not Started", "In Process")


def validate_work_order(doc, method=None):
	"""Work Order ``validate`` hook: machine-hour capacity check per production line.

	``required_machine_hours`` = qty x Item.machine_hours_per_unit (fallback: BOM operation minutes
	x qty) + a fixed setup allowance. The planning window runs from ``planned_start_date`` to
	``expected_delivery_date`` / ``planned_end_date`` / +7 days. Line capacity per day is
	16 h x (1 - downtime). Booked hours are the remaining operation hours of open Work Orders
	whose window overlaps ours (see ``get_booked_hours``; this is an approximation - it does
	not pro-rate partially overlapping windows).

	Over capacity blocks the save with concrete options unless an Operations Head /
	Manufacturing Manager ticks ``capacity_override`` with a reason (audited as a comment).
	Rework Work Orders are checked too; the override is the escape hatch.
	"""
	if doc.docstatus == 2:
		return

	item = (
		frappe.db.get_value(
			"Item", doc.production_item, ["machine_hours_per_unit", "default_line"], as_dict=True
		)
		or frappe._dict()
	)

	per_unit_hours = get_machine_hours_per_unit(doc, item)
	required = flt(per_unit_hours * flt(doc.qty) + config.SETUP_HOURS, 2)
	doc.required_machine_hours = required

	line = resolve_line(doc, item)
	if not line:
		return  # item not assigned to a production line: nothing to check

	start, end = get_planning_window(doc)
	capacity = {ln: get_line_capacity(ln, start, end) for ln in config.PRODUCTION_LINES}
	booked = {ln: get_booked_hours(ln, start, end, exclude=doc.name) for ln in config.PRODUCTION_LINES}
	available = {ln: flt(capacity[ln] - booked[ln], 2) for ln in config.PRODUCTION_LINES}

	if line == "Any":
		line = max(config.PRODUCTION_LINES, key=lambda ln: available[ln])

	if required <= available.get(line, 0):
		return

	if doc.get("capacity_override"):
		validate_capacity_override(doc, line, required, available)
		return

	frappe.throw(
		build_capacity_message(doc, line, required, per_unit_hours, capacity, booked, available, start, end),
		title=_("Line Capacity Exceeded"),
	)


def get_machine_hours_per_unit(doc, item):
	if flt(item.get("machine_hours_per_unit")) > 0:
		return flt(item.machine_hours_per_unit)
	ops = doc.get("operations") or []
	if ops and flt(doc.qty):
		# Work Order Operation minutes are already scaled for the full order quantity
		return flt(sum(flt(op.time_in_mins) for op in ops) / 60 / flt(doc.qty))
	if doc.bom_no:
		minutes = flt(frappe.db.get_value("BOM Operation", {"parent": doc.bom_no}, "sum(time_in_mins)") or 0)
		bom_qty = flt(frappe.db.get_value("BOM", doc.bom_no, "quantity")) or 1
		return flt(minutes / 60 / bom_qty)
	return 0.0


def resolve_line(doc, item):
	line = cstr(item.get("default_line"))
	if line in config.PRODUCTION_LINES or line == "Any":
		return line
	for op in doc.get("operations") or []:
		if op.workstation in config.PRODUCTION_LINES:
			return op.workstation
	return None


def get_planning_window(doc):
	start = getdate(doc.planned_start_date) if doc.planned_start_date else getdate(nowdate())
	end = None
	if doc.get("expected_delivery_date"):
		end = getdate(doc.expected_delivery_date)
	elif doc.get("planned_end_date"):
		end = getdate(doc.planned_end_date)
	if not end or end < start:
		end = add_days(start, config.DEFAULT_PLANNING_WINDOW_DAYS)
	return start, end


def get_window_days(start, end):
	return max(cint(date_diff(end, start)) + 1, 1)


def get_daily_capacity(line):
	return flt(config.LINE_HOURS_PER_DAY * (1 - config.get_line_downtime_pct(line)), 2)


def get_line_capacity(line, start, end):
	return flt(get_daily_capacity(line) * get_window_days(start, end), 2)


def get_booked_hours(line, start, end, exclude=None):
	"""Remaining operation hours of open Work Orders on ``line`` overlapping [start, end].

	Approximation: a Work Order overlapping the window on any day counts fully (no pro-rating),
	and remaining hours scale linearly with (qty - produced_qty) / qty.
	"""
	filters = [
		["docstatus", "=", 1],
		["status", "in", OPEN_WO_STATUSES],
		["planned_start_date", "<=", f"{end} 23:59:59"],
	]
	if exclude:
		filters.append(["name", "!=", exclude])
	work_orders = frappe.get_all(
		"Work Order",
		filters=filters,
		fields=[
			"name",
			"qty",
			"produced_qty",
			"planned_end_date",
			"expected_delivery_date",
			"planned_start_date",
		],
	)
	overlapping = {}
	for wo in work_orders:
		wo_end = wo.expected_delivery_date or wo.planned_end_date or wo.planned_start_date
		if wo_end and getdate(wo_end) < start:
			continue
		overlapping[wo.name] = wo
	if not overlapping:
		return 0.0

	ops = frappe.get_all(
		"Work Order Operation",
		filters={"parent": ["in", list(overlapping)], "workstation": line},
		fields=["parent", "time_in_mins"],
	)
	booked = 0.0
	for op in ops:
		wo = overlapping[op.parent]
		remaining_fraction = 1.0
		if flt(wo.qty) > 0:
			remaining_fraction = max(flt(wo.qty) - flt(wo.produced_qty), 0) / flt(wo.qty)
		booked += flt(op.time_in_mins) / 60 * remaining_fraction
	return flt(booked, 2)


def validate_capacity_override(doc, line, required, available):
	reason = cstr(doc.get("capacity_override_reason")).strip()
	if len(reason) < 10:
		frappe.throw(
			_(
				"Please give a Capacity Override Reason (at least 10 characters) explaining why {0} "
				"should be overloaded"
			).format(frappe.bold(line)),
			title=_("Reason Required"),
		)
	before = doc.get_doc_before_save()
	newly_set = (
		not before or not before.get("capacity_override") or before.get("capacity_override_reason") != reason
	)
	if not newly_set:
		return
	if not config.user_has_any_role(config.CAPACITY_OVERRIDE_ROLES):
		frappe.throw(
			_("Only an Operations Head or Manufacturing Manager may override line capacity").format(),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	config.add_audit_comment(
		doc,
		_("Capacity override by {0} on {1}: required {2} h, available {3} h. Reason: {4}").format(
			frappe.session.user, line, required, available.get(line, 0), reason
		),
	)


def build_capacity_message(doc, line, required, per_unit_hours, capacity, booked, available, start, end):
	other = [ln for ln in config.PRODUCTION_LINES if ln != line]
	lines_html = "".join(
		_("<li>{0}: required {1} h, capacity {2} h, booked {3} h, <b>available {4} h</b></li>").format(
			ln, required, capacity[ln], booked[ln], available[ln]
		)
		for ln in config.PRODUCTION_LINES
	)

	options = []
	for ln in other:
		if required <= available[ln]:
			options.append(
				_("Move this order to {0} (set Item Default Line or operation workstation)").format(
					frappe.bold(ln)
				)
			)
	if per_unit_hours > 0:
		fits_now = int(math.floor(max(available[line] - config.SETUP_HOURS, 0) / per_unit_hours))
		if 0 < fits_now < flt(doc.qty):
			options.append(
				_("Split: {0} now on {1}, remaining {2} in a later Work Order").format(
					frappe.bold(fits_now), line, frappe.bold(flt(doc.qty) - fits_now)
				)
			)
	daily = get_daily_capacity(line)
	if daily > 0:
		days_needed = math.ceil((required + booked[line]) / daily)
		fit_date = add_days(start, max(days_needed - 1, 0))
		if getdate(fit_date) > getdate(end):
			options.append(
				_("Change the delivery date to {0} (window {1} to {2} is too short)").format(
					frappe.bold(frappe.format(fit_date, {"fieldtype": "Date"})),
					frappe.format(start, {"fieldtype": "Date"}),
					frappe.format(end, {"fieldtype": "Date"}),
				)
			)
	options.append(_("An Operations Head may tick <b>Capacity Override</b> on the Horizon tab with a reason"))

	return _(
		"Work Order for {0} x {1} needs {2} machine hours on {3} but only {4} h are free in the "
		"planning window.<ul>{5}</ul>Options:<ul>{6}</ul>"
	).format(
		flt(doc.qty),
		frappe.bold(doc.production_item),
		frappe.bold(required),
		frappe.bold(line),
		frappe.bold(available[line]),
		lines_html,
		"".join(f"<li>{o}</li>" for o in options),
	)

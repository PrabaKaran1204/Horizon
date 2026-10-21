# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Capacity Utilisation and Sequence: workstation load per day and a suggested Work Order sequence."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, formatdate, getdate, nowdate

SHIFT_HOURS = 16
DEFAULT_HORIZON_DAYS = 7
BUSY_PCT = 85
DEFAULT_DOWNTIME = {"Line A": 0.10, "Line B": 0.15}
OPEN_WO_STATUSES = ("Not Started", "In Process")
DOWNTIME_FIELD = "horizon_downtime_pct"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	filters.from_date = getdate(filters.from_date or nowdate())
	filters.to_date = getdate(filters.to_date or add_days(filters.from_date, DEFAULT_HORIZON_DAYS))
	if filters.to_date < filters.from_date:
		filters.to_date = filters.from_date
	columns = get_columns()
	workstations = get_workstations(filters)
	work_orders = get_open_work_orders(filters)
	data = get_capacity_rows(filters, workstations, work_orders)
	sequence = suggest_sequence(filters, workstations, work_orders, data)
	today_rows = [r for r in data if r.date == filters.from_date]
	message = get_message(filters, today_rows, sequence)
	summary = get_summary(filters, today_rows, data, sequence)
	if cint(filters.only_today):
		data = today_rows
	return columns, data, message, get_chart(data), summary


def get_columns():
	return [
		{
			"label": _("Workstation"),
			"fieldname": "workstation",
			"fieldtype": "Link",
			"options": "Workstation",
			"width": 140,
		},
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
		{"label": _("Capacity Hours"), "fieldname": "capacity_hours", "fieldtype": "Float", "width": 110},
		{"label": _("Booked Hours"), "fieldname": "booked_hours", "fieldtype": "Float", "width": 110},
		{"label": _("Utilisation %"), "fieldname": "utilisation_pct", "fieldtype": "Percent", "width": 100},
		{"label": _("Free Hours"), "fieldname": "free_hours", "fieldtype": "Float", "width": 100},
		{"label": _("Work Orders"), "fieldname": "work_orders", "fieldtype": "Data", "width": 220},
	]


def downtime_for(workstation):
	if frappe.db.has_column("Workstation", DOWNTIME_FIELD):
		pct = frappe.db.get_value("Workstation", workstation.name, DOWNTIME_FIELD)
		if pct is not None:
			return flt(pct) / 100
	for key, value in DEFAULT_DOWNTIME.items():
		if (
			key.lower() in (workstation.name or "").lower()
			or key.lower() in (workstation.workstation_name or "").lower()
		):
			return value
	return 0.0


def get_workstations(filters):
	ws_filters = {}
	if filters.workstation:
		ws_filters["name"] = filters.workstation
	workstations = frappe.get_all(
		"Workstation", filters=ws_filters, fields=["name", "workstation_name"], order_by="name"
	)
	for ws in workstations:
		ws.capacity_hours = flt(SHIFT_HOURS * (1 - downtime_for(ws)), 2)
	return workstations


def get_open_work_orders(filters):
	wo = frappe.qb.DocType("Work Order")
	so = frappe.qb.DocType("Sales Order")
	item = frappe.qb.DocType("Item")
	rows = (
		frappe.qb.from_(wo)
		.left_join(so)
		.on(so.name == wo.sales_order)
		.left_join(item)
		.on(item.name == wo.production_item)
		.select(
			wo.name,
			wo.production_item,
			item.item_group,
			item.machine_hours_per_unit,
			item.default_line,
			wo.qty,
			wo.produced_qty,
			wo.planned_start_date,
			wo.planned_end_date,
			wo.expected_delivery_date,
			wo.sales_order,
			so.delivery_date.as_("so_delivery_date"),
			wo.required_machine_hours,
		)
		.where((wo.docstatus == 1) & (wo.company == filters.company) & (wo.status.isin(OPEN_WO_STATUSES)))
		.orderby(wo.planned_start_date)
	).run(as_dict=True)
	if not rows:
		return []
	ops = frappe.get_all(
		"Work Order Operation",
		filters={"parent": ["in", [r.name for r in rows]], "parenttype": "Work Order"},
		fields=["parent", "workstation", "time_in_mins", "completed_qty"],
	)
	ops_by_wo = {}
	for op in ops:
		ops_by_wo.setdefault(op.parent, []).append(op)
	for r in rows:
		r.pending_qty = max(flt(r.qty) - flt(r.produced_qty), 0)
		r.pending_fraction = r.pending_qty / flt(r.qty) if flt(r.qty) else 0
		r.due_date = getdate(
			r.so_delivery_date or r.expected_delivery_date or r.planned_end_date or nowdate()
		)
		r.loads = []  # (workstation, hours)
		for op in ops_by_wo.get(r.name, []):
			if op.workstation:
				r.loads.append((op.workstation, flt(op.time_in_mins) / 60 * r.pending_fraction))
		if not r.loads and flt(r.machine_hours_per_unit):
			r.loads.append((r.default_line, flt(r.machine_hours_per_unit) * r.pending_qty))
		elif not r.loads and flt(r.required_machine_hours):
			r.loads.append((r.default_line, flt(r.required_machine_hours) * r.pending_fraction))
		r.required_hours = flt(sum(h for _w, h in r.loads), 2)
	return rows


def resolve_workstation(name_or_line, workstations):
	"""Map an operation workstation or an Item default line ("Line A") to a known workstation."""
	if not workstations:
		return None
	if not name_or_line or name_or_line == "Any":
		return workstations[0].name
	for ws in workstations:
		if ws.name == name_or_line:
			return ws.name
	for ws in workstations:
		if (
			name_or_line.lower() in ws.name.lower()
			or name_or_line.lower() in (ws.workstation_name or "").lower()
		):
			return ws.name
	return workstations[0].name


def get_capacity_rows(filters, workstations, work_orders):
	days = [add_days(filters.from_date, i) for i in range(date_diff(filters.to_date, filters.from_date) + 1)]
	booked = {}  # (ws, date) -> [hours, set(wo)]
	for wo in work_orders:
		start = getdate(wo.planned_start_date or filters.from_date)
		end = getdate(wo.planned_end_date or start)
		start = max(start, filters.from_date)
		end = max(min(end, filters.to_date), start)
		span = date_diff(end, start) + 1
		if getdate(wo.planned_start_date or start) > filters.to_date:
			continue
		for ws_name, hours in wo.loads:
			ws = resolve_workstation(ws_name, workstations)
			if not ws:
				continue
			for i in range(span):
				key = (ws, add_days(start, i))
				entry = booked.setdefault(key, [0.0, set()])
				entry[0] += hours / span
				entry[1].add(wo.name)
	data = []
	for day in days:  # today's rows first, then workstation
		for ws in workstations:
			hours, wos = booked.get((ws.name, day), (0.0, set()))
			util = hours / ws.capacity_hours * 100 if ws.capacity_hours else 0
			data.append(
				frappe._dict(
					workstation=ws.name,
					date=day,
					capacity_hours=ws.capacity_hours,
					booked_hours=flt(hours, 2),
					utilisation_pct=flt(util, 1),
					free_hours=flt(ws.capacity_hours - hours, 2),
					work_orders=", ".join(sorted(wos)),
				)
			)
	return data


def suggest_sequence(filters, workstations, work_orders, data):
	"""Sort by due date, then item group (fewer changeovers); allocate hours to free capacity."""
	free = {(r.workstation, r.date): r.free_hours for r in data}
	ordered = sorted(work_orders, key=lambda w: (w.due_date, w.item_group or "", w.name))
	sequence = []
	for wo in ordered:
		fits_by = None
		for ws_name, hours in wo.loads:
			ws = resolve_workstation(ws_name, workstations)
			remaining = hours
			day = filters.from_date
			while remaining > 0.0001 and day <= filters.to_date:
				key = (ws, day)
				available = max(free.get(key, 0.0), 0.0)
				used = min(available, remaining)
				free[key] = available - used
				remaining -= used
				if remaining <= 0.0001:
					fits_by = max(fits_by, day) if fits_by else day
				day = add_days(day, 1)
			if remaining > 0.0001:
				fits_by = "beyond"
		sequence.append(
			frappe._dict(
				work_order=wo.name,
				item=wo.production_item,
				item_group=wo.item_group,
				qty=wo.pending_qty,
				line=", ".join(sorted({resolve_workstation(w, workstations) or "-" for w, _h in wo.loads}))
				or "-",
				required_hours=wo.required_hours,
				due_date=wo.due_date,
				fits_by=fits_by,
			)
		)
	return sequence


def status_for(utilisation_pct):
	"""(label, colour) for a utilisation percentage: Free < 85, Busy 85-100, Overloaded > 100."""
	util = flt(utilisation_pct)
	if util > 100:
		return _("Overloaded"), "red"
	if util >= BUSY_PCT:
		return _("Busy"), "orange"
	return _("Free"), "green"


def day_label(filters):
	return _("today") if filters.from_date == getdate(nowdate()) else formatdate(filters.from_date)


def get_message(filters, today_rows, sequence):
	return get_today_table(filters, today_rows) + get_sequence_table(sequence)


def get_today_table(filters, today_rows):
	"""Compact line status for the From Date: this is what a supervisor needs first."""
	heading = (
		_("Today - line status ({0})").format(formatdate(filters.from_date))
		if filters.from_date == getdate(nowdate())
		else _("Line status on {0}").format(formatdate(filters.from_date))
	)
	if not today_rows:
		return f"<h5>{heading}</h5><p class='text-muted'>{_('No workstations found.')}</p>"
	head = "".join(
		f"<th>{_(h)}</th>"
		for h in ("Line", "Capacity h", "Booked h", "Free h", "Running Work Orders", "Status")
	)
	rows = []
	for r in today_rows:
		label, colour = status_for(r.utilisation_pct)
		wos = (
			", ".join(frappe.utils.get_link_to_form("Work Order", w) for w in r.work_orders.split(", ") if w)
			or f"<span class='text-muted'>{_('None')}</span>"
		)
		free = flt(r.free_hours, 1)
		free_html = f"<span style='color:red;font-weight:600'>{free}</span>" if free < 0 else f"<b>{free}</b>"
		rows.append(
			f"<tr><td>{frappe.utils.get_link_to_form('Workstation', r.workstation)}</td>"
			f"<td>{flt(r.capacity_hours, 1)}</td><td>{flt(r.booked_hours, 1)}</td><td>{free_html}</td>"
			f"<td>{wos}</td>"
			f"<td><span class='indicator-pill {colour}'>{label} ({flt(r.utilisation_pct, 1)}%)</span></td></tr>"
		)
	return (
		f"<h5>{heading}</h5>"
		f"<table class='table table-bordered table-sm'><thead><tr>{head}</tr></thead>"
		f"<tbody>{''.join(rows)}</tbody></table>"
	)


def get_sequence_table(sequence):
	heading = f"<h5>{_('Suggested Work Order Sequence')}</h5>"
	if not sequence:
		return f"{heading}<p class='text-muted'>{_('No open Work Orders.')}</p>"
	note = (
		f"<p class='text-muted small'>{_('Ordered by due date, same item group grouped to save setup; ')}"
		f"<span style='color:red;font-weight:600'>{_('Fits By')}</span> {_('in red when after the due date.')}</p>"
	)
	head = "".join(
		f"<th>{_(h)}</th>"
		for h in ("#", "Work Order", "Item", "Group", "Qty", "Line", "Hours", "Due Date", "Fits By")
	)
	rows = []
	for i, s in enumerate(sequence, 1):
		if s.fits_by == "beyond":
			fits = f"<span style='color:red;font-weight:600'>{_('Beyond horizon')}</span>"
		elif s.fits_by and getdate(s.fits_by) > s.due_date:
			fits = f"<span style='color:red;font-weight:600'>{formatdate(s.fits_by)}</span>"
		elif s.fits_by:
			fits = formatdate(s.fits_by)
		else:
			fits = f"<span class='text-muted'>{_('No load')}</span>"
		rows.append(
			f"<tr><td>{i}</td><td>{frappe.utils.get_link_to_form('Work Order', s.work_order)}</td>"
			f"<td>{frappe.utils.escape_html(s.item or '')}</td><td>{frappe.utils.escape_html(s.item_group or '')}</td>"
			f"<td>{flt(s.qty, 2)}</td><td>{frappe.utils.escape_html(s.line)}</td><td>{s.required_hours}</td>"
			f"<td>{formatdate(s.due_date)}</td><td>{fits}</td></tr>"
		)
	return (
		f"{heading}{note}"
		f"<table class='table table-bordered table-sm'><thead><tr>{head}</tr></thead>"
		f"<tbody>{''.join(rows)}</tbody></table>"
	)


def get_chart(data):
	"""Utilisation % per workstation per day: one line per workstation, days on the x-axis."""
	days = sorted({r.date for r in data})
	by_ws = {}
	for r in data:
		by_ws.setdefault(r.workstation, {})[r.date] = r.utilisation_pct
	return {
		"title": _("Utilisation % per workstation per day"),
		"data": {
			"labels": [formatdate(d) for d in days],
			"datasets": [
				{"name": ws, "values": [flt(util.get(d, 0.0), 1) for d in days]} for ws, util in by_ws.items()
			],
			"yMarkers": [{"label": _("100 % capacity"), "value": 100, "options": {"labelPos": "left"}}],
		},
		"type": "line" if len(days) > 1 else "bar",
		"fieldtype": "Percent",
		"colors": ["#5e64ff", "#ff5858", "#28a745", "#ffa00a"],
		"lineOptions": {"regionFill": 1, "hideDots": 0},
	}


def get_summary(filters, today_rows, data, sequence):
	"""One card per workstation with free hours on the From Date first, then the period figures."""
	capacity = sum(r.capacity_hours for r in data)
	booked = sum(r.booked_hours for r in data)
	late = sum(
		1 for s in sequence if s.fits_by == "beyond" or (s.fits_by and getdate(s.fits_by) > s.due_date)
	)
	when = day_label(filters)
	summary = []
	for r in today_rows:
		_label, colour = status_for(r.utilisation_pct)
		summary.append(
			{
				"value": _("{0} h").format(flt(r.free_hours, 1)),
				"label": _("{0} free {1} (of {2} h, {3} h booked)").format(
					r.workstation, when, flt(r.capacity_hours, 1), flt(r.booked_hours, 1)
				),
				"datatype": "Data",
				"indicator": colour.capitalize(),
			}
		)
	summary.extend(
		[
			{
				"value": late,
				"label": _("WOs Not Fitting Before Due"),
				"datatype": "Int",
				"indicator": "Red" if late else "Green",
			},
			{"value": len(sequence), "label": _("Open Work Orders"), "datatype": "Int", "indicator": "Blue"},
			{
				"value": flt(booked / capacity * 100, 1) if capacity else 0,
				"label": _("Avg utilisation, period ({0} days)").format(len({r.date for r in data})),
				"datatype": "Percent",
				"indicator": "Blue",
			},
		]
	)
	return summary

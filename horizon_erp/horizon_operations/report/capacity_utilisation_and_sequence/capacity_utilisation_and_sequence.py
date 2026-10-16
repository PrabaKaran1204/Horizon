# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Capacity Utilisation and Sequence: workstation load per day and a suggested Work Order sequence."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, formatdate, getdate, nowdate

SHIFT_HOURS = 16
DEFAULT_DOWNTIME = {"Line A": 0.10, "Line B": 0.15}
OPEN_WO_STATUSES = ("Not Started", "In Process")
DOWNTIME_FIELD = "horizon_downtime_pct"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	filters.from_date = getdate(filters.from_date or nowdate())
	filters.to_date = getdate(filters.to_date or add_days(filters.from_date, 14))
	if filters.to_date < filters.from_date:
		filters.to_date = filters.from_date
	columns = get_columns()
	workstations = get_workstations(filters)
	work_orders = get_open_work_orders(filters)
	data = get_capacity_rows(filters, workstations, work_orders)
	sequence = suggest_sequence(filters, workstations, work_orders, data)
	return columns, data, get_message(sequence), get_chart(data), get_summary(data, sequence)


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
	for ws in workstations:
		for day in days:
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


def get_message(sequence):
	if not sequence:
		return f"<h5>{_('Suggested Work Order Sequence')}</h5><p class='text-muted'>{_('No open Work Orders.')}</p>"
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
		f"<h5>{_('Suggested Work Order Sequence')} ({_('by due date, grouped by item group')})</h5>"
		f"<table class='table table-bordered table-sm'><thead><tr>{head}</tr></thead>"
		f"<tbody>{''.join(rows)}</tbody></table>"
	)


def get_chart(data):
	by_ws = {}
	for r in data:
		entry = by_ws.setdefault(r.workstation, [0.0, 0.0])
		entry[0] += r.booked_hours
		entry[1] += r.capacity_hours
	labels = list(by_ws.keys())
	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Booked Hours"), "values": [flt(v[0], 1) for v in by_ws.values()]},
				{"name": _("Capacity Hours"), "values": [flt(v[1], 1) for v in by_ws.values()]},
			],
		},
		"type": "bar",
		"colors": ["#ff5858", "#5e64ff"],
	}


def get_summary(data, sequence):
	capacity = sum(r.capacity_hours for r in data)
	booked = sum(r.booked_hours for r in data)
	overloaded = sum(1 for r in data if r.utilisation_pct > 100)
	late = sum(
		1 for s in sequence if s.fits_by == "beyond" or (s.fits_by and getdate(s.fits_by) > s.due_date)
	)
	return [
		{
			"value": booked / capacity * 100 if capacity else 0,
			"label": _("Overall Utilisation %"),
			"datatype": "Percent",
			"indicator": "Blue",
		},
		{
			"value": overloaded,
			"label": _("Overloaded Workstation-Days"),
			"datatype": "Int",
			"indicator": "Red" if overloaded else "Green",
		},
		{"value": len(sequence), "label": _("Open Work Orders"), "datatype": "Int", "indicator": "Blue"},
		{
			"value": late,
			"label": _("WOs Not Fitting Before Due"),
			"datatype": "Int",
			"indicator": "Red" if late else "Green",
		},
	]

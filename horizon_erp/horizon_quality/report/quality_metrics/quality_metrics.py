# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Quality Metrics: first-pass yield, rework cost %, defect-reason trend and the 4 h inspection SLA.

One table, four blocks. Each block starts with a header row (``is_header``, ``indent`` 0) and lists
its detail rows at ``indent`` 1; the four KPIs are returned in ``report_summary`` and the defect
trend in the chart. ``item_group`` narrows Work Orders / Quality Inspections through the Item; Non
Conformances carry no item and are therefore only counted when no item group is selected.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import add_days, cint, flt, formatdate, get_first_day, getdate, nowdate, strip_html

from horizon_erp.horizon_operations import config

DEFAULT_PERIOD_DAYS = 90
INSPECTION_SLA_HOURS = 4
REASON_LENGTH = 60
TOP_REASONS = 10
WORST_INSPECTIONS = 5
CLOSED_ISSUE_STATUSES = ("Cancelled",)


def execute(filters=None):
	filters = get_filters(filters)
	fpy = get_first_pass_yield(filters)
	rework = get_rework_cost(filters)
	defects = get_defect_reasons(filters)
	sla = get_inspection_sla(filters)
	data = build_rows(fpy, rework, defects, sla)
	return get_columns(), data, None, get_chart(defects, filters), get_summary(fpy, rework, defects, sla)


def get_filters(filters):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	filters.to_date = getdate(filters.to_date or nowdate())
	filters.from_date = getdate(filters.from_date or add_days(filters.to_date, -DEFAULT_PERIOD_DAYS))
	filters.to_date_exclusive = add_days(filters.to_date, 1)  # datetime columns: < next day
	return filters


def get_columns():
	return [
		{"label": _("Metric / Document"), "fieldname": "label", "fieldtype": "Data", "width": 260},
		{
			"label": _("Reference"),
			"fieldname": "reference",
			"fieldtype": "Dynamic Link",
			"options": "reference_type",
			"width": 170,
		},
		{"label": _("Type"), "fieldname": "reference_type", "fieldtype": "Data", "width": 120},
		{"label": _("Detail"), "fieldname": "detail", "fieldtype": "Data", "width": 280},
		{"label": _("Month"), "fieldname": "period", "fieldtype": "Data", "width": 90},
		{"label": _("Count"), "fieldname": "count", "fieldtype": "Int", "width": 80},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Hours"), "fieldname": "hours", "fieldtype": "Float", "precision": 2, "width": 80},
		{"label": _("%"), "fieldname": "pct", "fieldtype": "Percent", "width": 90},
	]


# ---------------------------------------------------------------------------------------------
# (a) first-pass yield
# ---------------------------------------------------------------------------------------------
def get_completed_work_orders(filters):
	wo = frappe.qb.DocType("Work Order")
	item = frappe.qb.DocType("Item")
	finished = Coalesce(wo.actual_end_date, wo.modified)
	q = (
		frappe.qb.from_(wo)
		.inner_join(item)
		.on(item.name == wo.production_item)
		.select(wo.name, wo.production_item, finished.as_("finished_on"))
		.where(
			(wo.docstatus == 1)
			& (wo.company == filters.company)
			& (wo.status == "Completed")
			& (finished >= filters.from_date)
			& (finished < filters.to_date_exclusive)
		)
		.orderby(wo.name)
	)
	if filters.item_group:
		q = q.where(item.item_group == filters.item_group)
	return q.run(as_dict=True)


def get_first_pass_yield(filters):
	completed = get_completed_work_orders(filters)
	names = [r.name for r in completed]
	issues = {}  # work order -> [detail, ...]
	if names:
		rework = frappe.get_all(
			"Work Order",
			filters={"rework_of": ["in", names], "docstatus": ["<", 2]},
			fields=["name", "rework_of", "qty"],
			order_by="name",
		)
		for r in rework:
			issues.setdefault(r.rework_of, []).append(_("Rework {0} ({1} units)").format(r.name, flt(r.qty)))
		audits = frappe.get_all(
			"Production Audit",
			filters={
				"work_order": ["in", names],
				"docstatus": 1,
				"audit_score": ["<", config.AUDIT_FAIL_SCORE],
			},
			fields=["name", "work_order", "audit_score"],
			order_by="name",
		)
		for a in audits:
			issues.setdefault(a.work_order, []).append(
				_("Production Audit {0} scored {1}").format(a.name, cint(a.audit_score))
			)
	total = len(completed)
	with_issues = len(issues)
	return frappe._dict(
		completed=completed,
		total=total,
		with_issues=with_issues,
		issues=issues,
		fpy_pct=flt((total - with_issues) / total * 100, 1) if total else 0.0,
	)


# ---------------------------------------------------------------------------------------------
# (b) rework cost %
# ---------------------------------------------------------------------------------------------
def get_work_order_costs(filters):
	"""Every Work Order created in the period with its cost (operating + material)."""
	wo = frappe.qb.DocType("Work Order")
	woi = frappe.qb.DocType("Work Order Item")
	item = frappe.qb.DocType("Item")
	q = (
		frappe.qb.from_(wo)
		.inner_join(item)
		.on(item.name == wo.production_item)
		.left_join(woi)
		.on(woi.parent == wo.name)
		.select(
			wo.name,
			wo.production_item,
			wo.rework_of,
			wo.total_operating_cost,
			wo.planned_operating_cost,
			Sum(woi.amount).as_("material_cost"),
		)
		.where(
			(wo.docstatus < 2)
			& (wo.company == filters.company)
			& (wo.creation >= filters.from_date)
			& (wo.creation < filters.to_date_exclusive)
		)
		.groupby(wo.name)
		.orderby(wo.name)
	)
	if filters.item_group:
		q = q.where(item.item_group == filters.item_group)
	rows = q.run(as_dict=True)
	for r in rows:
		r.cost = (flt(r.total_operating_cost) or flt(r.planned_operating_cost)) + flt(r.material_cost)
	return rows


def get_rework_cost(filters):
	rows = get_work_order_costs(filters)
	rework_rows = [r for r in rows if r.rework_of]
	rework_cost = sum(r.cost for r in rework_rows)
	total_cost = sum(r.cost for r in rows)
	return frappe._dict(
		rows=rework_rows,
		rework_cost=flt(rework_cost, 2),
		total_cost=flt(total_cost, 2),
		work_orders=len(rows),
		rework_pct=flt(rework_cost / total_cost * 100, 1) if total_cost else 0.0,
	)


# ---------------------------------------------------------------------------------------------
# (c) defect reasons
# ---------------------------------------------------------------------------------------------
def month_key(date):
	return getdate(date).strftime("%Y-%m")


def month_label(key):
	year, month = key.split("-")
	return formatdate(f"{year}-{month}-01", "MMM yyyy")


def normalise_reason(text):
	text = " ".join(strip_html(text or "").split())
	return text[:REASON_LENGTH] if text else ""


def get_defect_reasons(filters):
	counts = {}  # reason -> {month: count}

	def add(reason, date):
		reason = normalise_reason(reason)
		if not reason:
			return
		by_month = counts.setdefault(reason, {})
		key = month_key(date)
		by_month[key] = by_month.get(key, 0) + 1

	qi = frappe.qb.DocType("Quality Inspection")
	item = frappe.qb.DocType("Item")
	q = (
		frappe.qb.from_(qi)
		.inner_join(item)
		.on(item.name == qi.item_code)
		.select(qi.name, qi.rejection_reason, qi.report_date)
		.where(
			(qi.docstatus < 2)
			& (qi.rejection_reason.isnotnull())
			& (qi.rejection_reason != "")
			& (qi.report_date >= filters.from_date)
			& (qi.report_date <= filters.to_date)
		)
	)
	if frappe.db.has_column("Quality Inspection", "company"):
		q = q.where((qi.company == filters.company) | qi.company.isnull() | (qi.company == ""))
	if filters.item_group:
		q = q.where(item.item_group == filters.item_group)
	for r in q.run(as_dict=True):
		add(r.rejection_reason, r.report_date)

	if not filters.item_group and frappe.db.exists("DocType", "Non Conformance"):
		for nc in frappe.get_all(
			"Non Conformance",
			filters={"creation": ["between", [filters.from_date, filters.to_date_exclusive]]},
			fields=["name", "subject", "details", "creation"],
		):
			add(nc.subject or nc.details, nc.creation)

	ranked = sorted(counts.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:TOP_REASONS]
	reasons = [
		frappe._dict(reason=reason, total=sum(by_month.values()), by_month=by_month)
		for reason, by_month in ranked
	]
	return frappe._dict(reasons=reasons, total=sum(r.total for r in reasons))


def get_period_months(filters):
	months = []
	start = get_first_day(filters.from_date)
	while start <= filters.to_date:
		months.append(month_key(start))
		start = get_first_day(add_days(start, 32))
	return months


# ---------------------------------------------------------------------------------------------
# (d) inspection SLA
# ---------------------------------------------------------------------------------------------
def get_inspection_sla(filters):
	qi = frappe.qb.DocType("Quality Inspection")
	pr = frappe.qb.DocType("Purchase Receipt")
	item = frappe.qb.DocType("Item")
	q = (
		frappe.qb.from_(qi)
		.inner_join(pr)
		.on(pr.name == qi.reference_name)
		.inner_join(item)
		.on(item.name == qi.item_code)
		.select(
			qi.name,
			qi.reference_name,
			qi.item_code,
			qi.status,
			qi.creation.as_("inspected_at"),
			pr.creation.as_("received_at"),
		)
		.where(
			(qi.docstatus < 2)
			& (qi.reference_type == "Purchase Receipt")
			& (pr.company == filters.company)
			& (qi.creation >= filters.from_date)
			& (qi.creation < filters.to_date_exclusive)
		)
	)
	if filters.item_group:
		q = q.where(item.item_group == filters.item_group)
	rows = q.run(as_dict=True)
	for r in rows:
		delta = r.inspected_at - r.received_at
		r.hours = flt(max(delta.total_seconds(), 0) / 3600, 2)
		r.within_sla = r.hours <= INSPECTION_SLA_HOURS
	total = len(rows)
	within = sum(1 for r in rows if r.within_sla)
	return frappe._dict(
		rows=rows,
		total=total,
		within=within,
		within_pct=flt(within / total * 100, 1) if total else 0.0,
		avg_hours=flt(sum(r.hours for r in rows) / total, 2) if total else 0.0,
		worst=sorted(rows, key=lambda r: r.hours, reverse=True)[:WORST_INSPECTIONS],
	)


# ---------------------------------------------------------------------------------------------
# table / chart / summary
# ---------------------------------------------------------------------------------------------
def header(label, **values):
	return frappe._dict(label=label, indent=0, is_header=1, **values)


def detail(label, **values):
	return frappe._dict(label=label, indent=1, **values)


def build_rows(fpy, rework, defects, sla):
	data = [
		header(
			_("First-pass yield"),
			detail=_("{0} completed, {1} with rework or audit < {2}").format(
				fpy.total, fpy.with_issues, config.AUDIT_FAIL_SCORE
			),
			count=fpy.total,
			pct=fpy.fpy_pct,
		)
	]
	for wo_name, problems in sorted(fpy.issues.items()):
		data.append(
			detail(
				wo_name,
				reference_type="Work Order",
				reference=wo_name,
				detail="; ".join(problems),
				count=len(problems),
			)
		)

	data.append(
		header(
			_("Rework cost %"),
			detail=_("Rework {0} of total production cost {1} across {2} Work Orders").format(
				frappe.format(rework.rework_cost, {"fieldtype": "Currency"}),
				frappe.format(rework.total_cost, {"fieldtype": "Currency"}),
				rework.work_orders,
			),
			count=len(rework.rows),
			amount=rework.rework_cost,
			pct=rework.rework_pct,
		)
	)
	for r in rework.rows:
		data.append(
			detail(
				r.name,
				reference_type="Work Order",
				reference=r.name,
				detail=_("Rework of {0} ({1})").format(r.rework_of, r.production_item),
				amount=flt(r.cost, 2),
				pct=flt(r.cost / rework.total_cost * 100, 1) if rework.total_cost else 0.0,
			)
		)

	data.append(
		header(
			_("Most common defect reasons"),
			detail=_("Top {0} reasons from Quality Inspection rejections and Non Conformances").format(
				TOP_REASONS
			),
			count=defects.total,
		)
	)
	for r in defects.reasons:
		months = ", ".join(f"{month_label(k)}: {v}" for k, v in sorted(r.by_month.items()))
		data.append(
			detail(
				r.reason,
				detail=months,
				count=r.total,
				pct=flt(r.total / defects.total * 100, 1) if defects.total else 0.0,
			)
		)

	data.append(
		header(
			_("Inspection SLA ({0} h)").format(INSPECTION_SLA_HOURS),
			detail=_("{0} of {1} incoming inspections within {2} h; average {3} h").format(
				sla.within, sla.total, INSPECTION_SLA_HOURS, sla.avg_hours
			),
			count=sla.total,
			hours=sla.avg_hours,
			pct=sla.within_pct,
		)
	)
	for r in sla.worst:
		data.append(
			detail(
				r.name,
				reference_type="Quality Inspection",
				reference=r.name,
				detail=_("{0} received {1}, {2}").format(
					r.reference_name, frappe.format(r.received_at, {"fieldtype": "Datetime"}), r.status
				),
				hours=r.hours,
				is_breach=0 if r.within_sla else 1,
			)
		)
	return data


def get_chart(defects, filters):
	months = get_period_months(filters)
	return {
		"data": {
			"labels": [month_label(m) for m in months],
			"datasets": [
				{"name": r.reason[:30], "values": [r.by_month.get(m, 0) for m in months]}
				for r in defects.reasons
			],
		},
		"type": "line",
		"lineOptions": {"regionFill": 0},
	}


def get_summary(fpy, rework, defects, sla):
	top = defects.reasons[0].reason if defects.reasons else _("none")
	return [
		{
			"value": fpy.fpy_pct,
			"label": _("First-pass Yield"),
			"datatype": "Percent",
			"indicator": "Green" if fpy.fpy_pct >= 95 else ("Orange" if fpy.fpy_pct >= 85 else "Red"),
		},
		{
			"value": rework.rework_pct,
			"label": _("Rework Cost %"),
			"datatype": "Percent",
			"indicator": "Green"
			if rework.rework_pct <= 2
			else ("Orange" if rework.rework_pct <= 5 else "Red"),
		},
		{
			"value": defects.total,
			"label": _("Defects (top: {0})").format(top[:30]),
			"datatype": "Int",
			"indicator": "Blue",
		},
		{
			"value": sla.within_pct,
			"label": _("Inspections within {0} h").format(INSPECTION_SLA_HOURS),
			"datatype": "Percent",
			"indicator": "Green" if sla.within_pct >= 90 else ("Orange" if sla.within_pct >= 75 else "Red"),
		},
	]

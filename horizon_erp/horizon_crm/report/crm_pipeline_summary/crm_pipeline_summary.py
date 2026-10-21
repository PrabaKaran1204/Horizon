# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""CRM Pipeline Summary: the Lead -> Opportunity -> Quotation -> Sales Order -> Customer funnel of
the leads created in a period, one row per lead with the latest document of every stage.

Chain (ADR-17): the Opportunity keeps ``opportunity_from = "Lead"``; the Quotation links the
Opportunity (``opportunity``) and, once the Customer exists, is addressed to it; the Customer is
created when the Quotation is made from a qualified Opportunity and carries ``lead_name``; the Sales
Order references the Quotation through ``Sales Order Item.prevdoc_docname``. The report collects the
lead names of the period first and then runs one query per doctype (no per-lead lookups).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

OLD_LEAD_DAYS = 14
STAGE_ORDER = ("Lead", "Opportunity", "Customer", "Quoted", "Ordered")
LOST_STAGE = "Lost"
LOST_LEAD_STATUSES = ("Lost Quotation", "Do Not Contact")
GROUP_FIELDS = {"Source": "source", "Territory": "territory", "Lead Owner": "lead_owner", "Month": "month"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	if not filters.to_date:
		filters.to_date = nowdate()
	if not filters.from_date:
		filters.from_date = add_days(filters.to_date, -90)
	filters.status = parse_list(filters.status)

	columns = get_columns()
	rows = get_data(filters)
	summary = get_summary(rows)
	chart = get_chart(summary)
	data = group_rows(rows, filters.group_by) if filters.group_by and filters.group_by != "None" else rows
	return columns, data, get_message(), chart, summary


def parse_list(value):
	if not value:
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.startswith("[") else [value]
	return [v for v in value if v]


def get_columns():
	return [
		{"label": _("Lead"), "fieldname": "lead", "fieldtype": "Link", "options": "Lead", "width": 170},
		{"label": _("Lead Name / Organisation"), "fieldname": "lead_name", "fieldtype": "Data", "width": 200},
		{
			"label": _("Source"),
			"fieldname": "source",
			"fieldtype": "Link",
			"options": "Lead Source",
			"width": 110,
		},
		{
			"label": _("Territory"),
			"fieldname": "territory",
			"fieldtype": "Link",
			"options": "Territory",
			"width": 100,
		},
		{
			"label": _("Owner"),
			"fieldname": "lead_owner",
			"fieldtype": "Link",
			"options": "User",
			"width": 150,
		},
		{"label": _("Created"), "fieldname": "creation_date", "fieldtype": "Date", "width": 100},
		{"label": _("Lead Status"), "fieldname": "lead_status", "fieldtype": "Data", "width": 110},
		{
			"label": _("Opportunity"),
			"fieldname": "opportunity",
			"fieldtype": "Link",
			"options": "Opportunity",
			"width": 150,
		},
		{"label": _("Opp Status"), "fieldname": "opportunity_status", "fieldtype": "Data", "width": 100},
		{"label": _("Opp Amount"), "fieldname": "opportunity_amount", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Quotation"),
			"fieldname": "quotation",
			"fieldtype": "Link",
			"options": "Quotation",
			"width": 150,
		},
		{"label": _("Quote Status"), "fieldname": "quotation_status", "fieldtype": "Data", "width": 100},
		{"label": _("Quote Amount"), "fieldname": "quotation_amount", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 150,
		},
		{"label": _("SO Amount"), "fieldname": "sales_order_amount", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 160,
		},
		{
			"label": _("Customer Group"),
			"fieldname": "customer_group",
			"fieldtype": "Link",
			"options": "Customer Group",
			"width": 110,
		},
		{"label": _("Stage Reached"), "fieldname": "stage_reached", "fieldtype": "Data", "width": 110},
		{"label": _("Days to Customer / Age"), "fieldname": "days", "fieldtype": "Int", "width": 110},
		{"label": _("Lost Reason"), "fieldname": "lost_reason", "fieldtype": "Data", "width": 180},
	]


# ---------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------
def get_data(filters):
	leads = get_leads(filters)
	if not leads:
		return []
	lead_names = [r.name for r in leads]

	opportunities, lost_opportunities = get_opportunities(lead_names)
	customers = get_customers(lead_names)
	customer_to_lead = {c.name: lead for lead, c in customers.items()}
	quotations, quotation_to_lead = get_quotations(lead_names, opportunities, customer_to_lead)
	sales_orders = get_sales_orders(quotation_to_lead, customer_to_lead)
	as_on = getdate(nowdate())

	rows = []
	for lead in leads:
		opp = opportunities.get(lead.name)
		qtn = quotations.get(lead.name)
		so = sales_orders.get(lead.name)
		customer = customers.get(lead.name)
		row = frappe._dict(
			lead=lead.name,
			lead_name=lead.company_name or lead.lead_name,
			source=lead.source,
			territory=lead.territory,
			lead_owner=lead.lead_owner,
			creation_date=getdate(lead.creation),
			month=getdate(lead.creation).strftime("%Y-%m"),
			lead_status=lead.status,
			opportunity=opp.name if opp else None,
			opportunity_status=opp.status if opp else None,
			# opportunity_amount is typed by hand in v15; the items total is the estimate otherwise
			opportunity_amount=(flt(opp.opportunity_amount) or flt(opp.total)) if opp else 0,
			quotation=qtn.name if qtn else None,
			quotation_status=qtn.status if qtn else None,
			quotation_amount=flt(qtn.grand_total) if qtn else 0,
			sales_order=so.name if so else None,
			sales_order_amount=flt(so.grand_total) if so else 0,
			customer=customer.name if customer else None,
			customer_group=customer.customer_group if customer else None,
			lost_reason=(opp and opp.lost_reason) or (qtn and qtn.lost_reason) or None,
			lost_opportunities=lost_opportunities.get(lead.name, 0),
		)
		row.is_lost = is_lost(row)
		row.stage_reached = get_stage(row)
		row.days = (
			date_diff(customer.creation, lead.creation) if customer else date_diff(as_on, lead.creation)
		)
		rows.append(row)
	return rows


def get_leads(filters):
	lead = frappe.qb.DocType("Lead")
	query = (
		frappe.qb.from_(lead)
		.select(
			lead.name,
			lead.lead_name,
			lead.company_name,
			lead.source,
			lead.territory,
			lead.lead_owner,
			lead.creation,
			lead.status,
		)
		.where(lead.company == filters.company)
		.where(lead.creation >= getdate(filters.from_date))
		.where(lead.creation < add_days(getdate(filters.to_date), 1))
		.orderby(lead.creation, order=frappe.qb.desc)
	)
	if filters.source:
		query = query.where(lead.source == filters.source)
	if filters.territory:
		query = query.where(lead.territory == filters.territory)
	if filters.lead_owner:
		query = query.where(lead.lead_owner == filters.lead_owner)
	if filters.status:
		query = query.where(lead.status.isin(filters.status))
	return query.run(as_dict=True)


def get_opportunities(lead_names):
	"""Latest Opportunity per lead (by creation) and the count of Lost opportunities per lead."""
	opp = frappe.qb.DocType("Opportunity")
	rows = (
		frappe.qb.from_(opp)
		.select(
			opp.name,
			opp.party_name,
			opp.status,
			opp.opportunity_amount,
			opp.total,
			opp.order_lost_reason,
			opp.creation,
		)
		.where((opp.opportunity_from == "Lead") & (opp.party_name.isin(lead_names)))
		.orderby(opp.creation)
	).run(as_dict=True)
	lost = [r.name for r in rows if r.status == "Lost"]
	reasons = get_lost_reasons("Opportunity Lost Reason Detail", lost)
	latest, lost_count = {}, {}
	for r in rows:
		if r.status == "Lost":
			lost_count[r.party_name] = lost_count.get(r.party_name, 0) + 1
			r.lost_reason = join_reasons(reasons.get(r.name), r.order_lost_reason)
		latest[r.party_name] = r  # ordered by creation asc -> the last one wins
	return latest, lost_count


def get_customers(lead_names):
	"""First Customer created from each lead (``Customer.lead_name``)."""
	cust = frappe.qb.DocType("Customer")
	rows = (
		frappe.qb.from_(cust)
		.select(cust.name, cust.lead_name, cust.customer_group, cust.creation)
		.where(cust.lead_name.isin(lead_names))
		.orderby(cust.creation, order=frappe.qb.desc)
	).run(as_dict=True)
	return {r.lead_name: r for r in rows}  # desc -> the earliest one wins


def get_quotations(lead_names, opportunities, customer_to_lead):
	"""Latest non-cancelled Quotation per lead (linked through the Opportunity, addressed to the Lead
	or addressed to the Customer created from the lead) and ``{quotation: lead}`` for all of them."""
	opp_to_lead = {o.name: lead for lead, o in opportunities.items()}
	qtn = frappe.qb.DocType("Quotation")
	condition = (qtn.quotation_to == "Lead") & (qtn.party_name.isin(lead_names))
	if opp_to_lead:
		condition |= qtn.opportunity.isin(list(opp_to_lead))
	if customer_to_lead:
		condition |= (qtn.quotation_to == "Customer") & (qtn.party_name.isin(list(customer_to_lead)))
	rows = (
		frappe.qb.from_(qtn)
		.select(
			qtn.name,
			qtn.opportunity,
			qtn.quotation_to,
			qtn.party_name,
			qtn.status,
			qtn.grand_total,
			qtn.order_lost_reason,
			qtn.creation,
		)
		.where((qtn.docstatus < 2) & condition)
		.orderby(qtn.creation)
	).run(as_dict=True)
	reasons = get_lost_reasons("Quotation Lost Reason Detail", [r.name for r in rows if r.status == "Lost"])
	latest, quotation_to_lead = {}, {}
	for r in rows:
		lead = opp_to_lead.get(r.opportunity)
		if not lead:
			lead = r.party_name if r.quotation_to == "Lead" else customer_to_lead.get(r.party_name)
		if not lead:
			continue
		if r.status == "Lost":
			r.lost_reason = join_reasons(reasons.get(r.name), r.order_lost_reason)
		quotation_to_lead[r.name] = lead
		latest[lead] = r  # ordered by creation asc -> the last one wins
	return latest, quotation_to_lead


def get_sales_orders(quotation_to_lead, customer_to_lead):
	"""Latest submitted Sales Order per lead: made from one of the lead's quotations
	(``Sales Order Item.prevdoc_docname``), else placed by the Customer created from the lead."""
	if not quotation_to_lead and not customer_to_lead:
		return {}
	so = frappe.qb.DocType("Sales Order")
	soi = frappe.qb.DocType("Sales Order Item")
	condition = None
	if quotation_to_lead:
		condition = soi.prevdoc_docname.isin(list(quotation_to_lead))
	if customer_to_lead:
		by_customer = so.customer.isin(list(customer_to_lead))
		condition = by_customer if condition is None else (condition | by_customer)
	rows = (
		frappe.qb.from_(so)
		.inner_join(soi)
		.on(soi.parent == so.name)
		.select(so.name, so.customer, so.grand_total, so.transaction_date, so.creation, soi.prevdoc_docname)
		.where((so.docstatus == 1) & condition)
		.orderby(so.creation)
	).run(as_dict=True)
	latest = {}
	for r in rows:
		lead = quotation_to_lead.get(r.prevdoc_docname) or customer_to_lead.get(r.customer)
		if lead:
			latest[lead] = r  # ordered by creation asc -> the last one wins
	return latest


def get_lost_reasons(child_doctype, parents):
	if not parents:
		return {}
	reasons = {}
	for r in frappe.get_all(
		child_doctype, filters={"parent": ["in", parents]}, fields=["parent", "lost_reason"], order_by="idx"
	):
		reasons.setdefault(r.parent, []).append(r.lost_reason)
	return reasons


def join_reasons(reasons, detail):
	parts = list(reasons or [])
	if detail:
		parts.append(detail)
	return ", ".join(parts) or None


# ---------------------------------------------------------------------------------------------
# stage logic
# ---------------------------------------------------------------------------------------------
def is_lost(row):
	if row.sales_order:
		return False
	if row.opportunity_status == "Lost" or row.quotation_status == "Lost":
		return True
	return row.lead_status in LOST_LEAD_STATUSES


def get_stage(row):
	"""Furthest step of the Horizon chain: Lead < Opportunity < Customer < Quoted < Ordered (ADR-17
	creates the Customer when the Quotation is made, so Customer sits before Quoted); Lost when the
	Opportunity / Quotation was lost or the Lead was closed and no order exists."""
	if row.is_lost:
		return LOST_STAGE
	if row.sales_order:
		return "Ordered"
	if row.quotation:
		return "Quoted"
	if row.customer:
		return "Customer"
	if row.opportunity:
		return "Opportunity"
	return "Lead"


# ---------------------------------------------------------------------------------------------
# grouping, summary, chart
# ---------------------------------------------------------------------------------------------
def funnel_counts(rows):
	return frappe._dict(
		leads=len(rows),
		qualified=sum(1 for r in rows if r.opportunity),
		quoted=sum(1 for r in rows if r.quotation),
		ordered=sum(1 for r in rows if r.sales_order),
		customers=sum(1 for r in rows if r.customer),
		lost=sum(1 for r in rows if r.stage_reached == LOST_STAGE),
		lost_opportunities=sum(cint(r.lost_opportunities) for r in rows),
		old_open_leads=sum(1 for r in rows if r.stage_reached == "Lead" and cint(r.days) > OLD_LEAD_DAYS),
	)


def pct(part, whole):
	return flt(part) / flt(whole) * 100 if flt(whole) else 0


def group_rows(rows, group_by):
	fieldname = GROUP_FIELDS.get(group_by)
	if not fieldname:
		return rows
	groups = {}
	for r in rows:
		groups.setdefault(r.get(fieldname) or "", []).append(r)
	keys = sorted(k for k in groups if k)
	if fieldname == "month":
		keys.reverse()  # newest month first, like the rows
	if "" in groups:
		keys.append("")  # leads without the grouping value last
	data = []
	for key in keys:
		members = groups[key]
		counts = funnel_counts(members)
		label = group_label(fieldname, key)
		header = frappe._dict(
			lead=label,
			lead_name=_("{0} leads, {1} qualified, {2} quoted, {3} ordered, {4} customers").format(
				counts.leads, counts.qualified, counts.quoted, counts.ordered, counts.customers
			),
			opportunity_amount=sum(r.opportunity_amount for r in members),
			quotation_amount=sum(r.quotation_amount for r in members),
			sales_order_amount=sum(r.sales_order_amount for r in members),
			stage_reached=_("{0}% converted").format(flt(pct(counts.customers, counts.leads), 1)),
			indent=0,
			is_group=1,
			group_key=key,
			conversion_pct=flt(pct(counts.customers, counts.leads), 1),
			**counts,
		)
		data.append(header)
		for r in members:
			r.indent = 1
			data.append(r)
	return data


def group_label(fieldname, key):
	if not key:
		return _("Not Set")
	if fieldname == "month":
		year, month = key.split("-")
		return getdate(f"{year}-{month}-01").strftime("%b %Y")
	return key


def get_summary(rows):
	c = funnel_counts(rows)
	converted = [r for r in rows if r.customer]
	avg_days = flt(sum(cint(r.days) for r in converted) / len(converted), 1) if converted else 0
	return [
		{"value": c.leads, "label": _("Leads"), "datatype": "Int", "indicator": "Blue"},
		{"value": c.qualified, "label": _("Qualified (Opportunity)"), "datatype": "Int", "indicator": "Blue"},
		{"value": c.quoted, "label": _("Quoted"), "datatype": "Int", "indicator": "Orange"},
		{"value": c.ordered, "label": _("Ordered"), "datatype": "Int", "indicator": "Green"},
		{"value": c.customers, "label": _("Customers Created"), "datatype": "Int", "indicator": "Green"},
		{
			"value": flt(pct(c.customers, c.leads), 1),
			"label": _("Lead to Customer %"),
			"datatype": "Percent",
			"indicator": "Green" if c.customers else "Grey",
		},
		{
			"value": flt(pct(c.ordered, c.quoted), 1),
			"label": _("Quote to Order %"),
			"datatype": "Percent",
			"indicator": "Green" if c.ordered else "Grey",
		},
		{
			"value": avg_days,
			"label": _("Avg Days Lead to Customer"),
			"datatype": "Float",
			"indicator": "Blue",
		},
		{
			"value": c.old_open_leads,
			"label": _("Open Leads Older Than {0} Days").format(OLD_LEAD_DAYS),
			"datatype": "Int",
			"indicator": "Red" if c.old_open_leads else "Green",
		},
		{
			"value": c.lost_opportunities,
			"label": _("Lost Opportunities"),
			"datatype": "Int",
			"indicator": "Red" if c.lost_opportunities else "Green",
		},
	]


def get_chart(summary):
	by_label = {s["label"]: s["value"] for s in summary}
	stages = [
		(_("Leads"), by_label[_("Leads")]),
		(_("Qualified"), by_label[_("Qualified (Opportunity)")]),
		(_("Quoted"), by_label[_("Quoted")]),
		(_("Ordered"), by_label[_("Ordered")]),
		(_("Customer"), by_label[_("Customers Created")]),
	]
	return {
		"data": {
			"labels": [s[0] for s in stages],
			"datasets": [{"name": _("Leads reaching the stage"), "values": [s[1] for s in stages]}],
		},
		"type": "bar",
		"colors": ["#5e64ff"],
	}


def get_message():
	return _(
		"Journey: Lead → Opportunity (customer details) → Quotation → Sales Order. Under ADR-17 the "
		"Customer is created when the Quotation is made from a qualified Opportunity, so <b>Stage "
		"Reached</b> runs Lead → Opportunity → Customer → Quoted → Ordered (Lost when the Opportunity / "
		"Quotation was lost or the Lead was closed); the funnel cards count the leads of the period that "
		"reached each stage."
	)

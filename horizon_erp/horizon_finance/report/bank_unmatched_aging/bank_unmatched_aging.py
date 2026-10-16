# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Bank Unmatched Aging: submitted Bank Transactions still carrying an unallocated amount, aged
from the transaction date to ``as_on`` and bucketed 0-7 / 8-30 / 31-60 / 60+ days.

The summary also compares the bank GL balance (``get_balance_on``) with the statement closing
balance. ERPNext v15 Bank Transactions carry no running balance column, so the closing balance is
read from a ``balance``-like field only when the statement import added one; otherwise it is blank
and the variance is not computed.
"""

import frappe
from erpnext.accounts.utils import get_balance_on
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, nowdate

BUCKETS = (
	(7, "0-7"),
	(30, "8-30"),
	(60, "31-60"),
	(None, "60+"),
)
FLAG_AFTER_DAYS = 30
BALANCE_FIELDS = ("running_balance", "closing_balance", "balance")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		filters.company = frappe.defaults.get_user_default("Company")
	filters.as_on = getdate(filters.as_on or nowdate())
	data = get_data(filters)
	return get_columns(), data, None, get_chart(data), get_summary(data, filters)


def get_columns():
	return [
		{
			"label": _("Bank Transaction"),
			"fieldname": "bank_transaction",
			"fieldtype": "Link",
			"options": "Bank Transaction",
			"width": 170,
		},
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Bank Account"),
			"fieldname": "bank_account",
			"fieldtype": "Link",
			"options": "Bank Account",
			"width": 180,
		},
		{"label": _("Description"), "fieldname": "description", "fieldtype": "Data", "width": 240},
		{"label": _("Reference"), "fieldname": "reference_number", "fieldtype": "Data", "width": 130},
		{"label": _("Deposit"), "fieldname": "deposit", "fieldtype": "Currency", "width": 120},
		{"label": _("Withdrawal"), "fieldname": "withdrawal", "fieldtype": "Currency", "width": 120},
		{"label": _("Unallocated"), "fieldname": "unallocated_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Age (days)"), "fieldname": "age_days", "fieldtype": "Int", "width": 90},
		{"label": _("Bucket"), "fieldname": "bucket", "fieldtype": "Data", "width": 80},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
	]


def bucket_for(age_days):
	for limit, label in BUCKETS:
		if limit is None or age_days <= limit:
			return label
	return BUCKETS[-1][1]


def get_data(filters):
	bt = frappe.qb.DocType("Bank Transaction")
	q = (
		frappe.qb.from_(bt)
		.select(
			bt.name.as_("bank_transaction"),
			bt.date,
			bt.bank_account,
			bt.description,
			bt.reference_number,
			bt.deposit,
			bt.withdrawal,
			bt.unallocated_amount,
			bt.status,
		)
		.where(
			(bt.docstatus == 1)
			& (bt.company == filters.company)
			& (bt.date <= filters.as_on)
			& ((bt.unallocated_amount > 0) | (bt.status == "Unreconciled"))
		)
		.orderby(bt.date)
		.orderby(bt.name)
	)
	if filters.bank_account:
		q = q.where(bt.bank_account == filters.bank_account)
	rows = q.run(as_dict=True)
	for r in rows:
		r.age_days = cint(date_diff(filters.as_on, r.date))
		r.bucket = bucket_for(r.age_days)
		r.flag = 1 if r.age_days > FLAG_AFTER_DAYS else 0
	return rows


def get_chart(data):
	totals = dict.fromkeys([label for _limit, label in BUCKETS], 0.0)
	for r in data:
		totals[r.bucket] += flt(r.unallocated_amount)
	return {
		"data": {
			"labels": list(totals),
			"datasets": [{"name": _("Unallocated"), "values": [flt(v, 2) for v in totals.values()]}],
		},
		"type": "bar",
		"colors": ["#ff5858"],
	}


def get_bank_accounts(filters):
	account_filters = {"company": filters.company, "is_company_account": 1, "disabled": 0}
	if filters.bank_account:
		account_filters = {"name": filters.bank_account}
	return frappe.get_all("Bank Account", filters=account_filters, fields=["name", "account"])


def get_gl_balance(filters):
	total = 0.0
	for ba in get_bank_accounts(filters):
		if ba.account:
			total += flt(get_balance_on(account=ba.account, date=filters.as_on, company=filters.company))
	return flt(total, 2)


def get_statement_closing_balance(filters):
	"""Running balance of the latest transaction on/before ``as_on`` if the import stored one."""
	meta = frappe.get_meta("Bank Transaction")
	field = next((f for f in BALANCE_FIELDS if meta.has_field(f)), None)
	if not field or not filters.bank_account:
		return None
	latest = frappe.get_all(
		"Bank Transaction",
		filters={"docstatus": 1, "bank_account": filters.bank_account, "date": ["<=", filters.as_on]},
		fields=[field],
		order_by="date desc, creation desc",
		limit=1,
	)
	return flt(latest[0][field]) if latest else None


def get_summary(data, filters):
	unmatched_value = flt(sum(flt(r.unallocated_amount) for r in data), 2)
	over_30 = sum(1 for r in data if r.flag)
	gl_balance = get_gl_balance(filters)
	closing = get_statement_closing_balance(filters)
	summary = [
		{"value": len(data), "label": _("Unmatched Transactions"), "datatype": "Int", "indicator": "Blue"},
		{
			"value": unmatched_value,
			"label": _("Unmatched Value"),
			"datatype": "Currency",
			"indicator": "Orange" if unmatched_value else "Green",
		},
		{
			"value": over_30,
			"label": _("Older than {0} days").format(FLAG_AFTER_DAYS),
			"datatype": "Int",
			"indicator": "Red" if over_30 else "Green",
		},
		{"value": gl_balance, "label": _("Bank GL Balance"), "datatype": "Currency", "indicator": "Blue"},
		{
			"value": closing if closing is not None else "",
			"label": _("Statement Closing Balance"),
			"datatype": "Currency" if closing is not None else "Data",
			"indicator": "Blue",
		},
	]
	if closing is not None:
		variance = flt(closing - gl_balance, 2)
		summary.append(
			{
				"value": variance,
				"label": _("Variance (Statement - GL)"),
				"datatype": "Currency",
				"indicator": "Green" if abs(variance) < 0.005 else "Red",
			}
		)
	return summary

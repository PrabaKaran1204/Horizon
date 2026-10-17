# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Cross-domain scheduler jobs: the 18:00 daily operational summary e-mail.

Scheduled from ``scheduler_events`` in hooks.py. Logging / alerting conventions shared by every job
(``@horizon_job``, Error Log + System Manager alert, retry marker) live in
``horizon_erp.horizon_core.jobs``.
"""

import frappe
from frappe import _
from frappe.utils import (
	cint,
	flt,
	getdate,
	now_datetime,
	today,
)

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.jobs import (
	horizon_company,
	horizon_job,
	safe_sendmail,
	users_with_roles,
)

AUDIT_SCORE_THRESHOLD = config.AUDIT_FAIL_SCORE


# ---------------------------------------------------------------------------
# Daily summary (18:00)
# ---------------------------------------------------------------------------
def get_daily_summary_metrics(date=None):
	"""Today's operational KPIs as a plain dict (also used by ``preview_daily_summary``)."""
	date = getdate(date or today())
	company = horizon_company()
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else "INR"

	def _agg(doctype, filters, sum_field=None):
		rows = frappe.get_all(
			doctype,
			filters=filters,
			fields=["count(name) as n", f"sum({sum_field}) as total"] if sum_field else ["count(name) as n"],
		)
		row = rows[0] if rows else {}
		return cint(row.get("n")), flt(row.get("total"))

	so_count, so_total = _agg("Sales Order", {"docstatus": 1, "transaction_date": date}, "grand_total")
	qtn_count, qtn_total = _agg("Quotation", {"docstatus": 1, "transaction_date": date}, "grand_total")
	dn_count, _dn = _agg("Delivery Note", {"docstatus": 1, "posting_date": date})
	si_count, si_total = _agg("Sales Invoice", {"docstatus": 1, "posting_date": date}, "grand_total")
	wo_count, wo_qty = _agg(
		"Work Order",
		{
			"status": "Completed",
			"docstatus": 1,
			"modified": ["between", [f"{date} 00:00:00", f"{date} 23:59:59"]],
		},
		"produced_qty",
	)
	po_filters = {"docstatus": 0}
	if frappe.db.has_column("Purchase Order", "workflow_state"):
		po_filters["workflow_state"] = ["like", "Pending%"]
	po_pending, _po = _agg("Purchase Order", po_filters)
	audits_low, _a = _agg(
		"Production Audit",
		{"docstatus": ["<", 2], "audit_date": date, "audit_score": ["<", AUDIT_SCORE_THRESHOLD]},
	)

	bin_ = frappe.qb.DocType("Bin")
	reorder = frappe.qb.DocType("Item Reorder")
	low_stock = (
		frappe.qb.from_(bin_)
		.join(reorder)
		.on(
			(reorder.parent == bin_.item_code)
			& (reorder.parenttype == "Item")
			& (reorder.warehouse == bin_.warehouse)
		)
		.select(bin_.item_code, bin_.warehouse, bin_.actual_qty, reorder.warehouse_reorder_level)
		.where(bin_.actual_qty < reorder.warehouse_reorder_level)
		.where(reorder.warehouse_reorder_level > 0)
	).run(as_dict=True)

	return {
		"date": str(date),
		"company": company,
		"currency": currency,
		"sales_orders": {"count": so_count, "total": so_total},
		"quotations_sent": {"count": qtn_count, "total": qtn_total},
		"delivery_notes": {"count": dn_count},
		"sales_invoices": {"count": si_count, "total": si_total},
		"work_orders_completed": {"count": wo_count, "produced_qty": wo_qty},
		"purchase_orders_pending_approval": po_pending,
		"production_audits_below_70": audits_low,
		"low_stock": {"count": len(low_stock), "items": low_stock[:20]},
		"generated_at": str(now_datetime()),
	}


def render_daily_summary(metrics):
	return frappe.render_template("horizon_erp/templates/emails/daily_summary.html", {"m": metrics})


@horizon_job("send_daily_summary")
def send_daily_summary():
	"""18:00 daily (cron). Compute today's KPIs, render ``templates/emails/daily_summary.html``,
	attach it as PDF (skipped with a warning when wkhtmltopdf is unavailable) and email it to
	Finance Director and Operations Head users. Returns the metrics dict (+ ``recipients``)."""
	metrics = get_daily_summary_metrics()
	html = render_daily_summary(metrics)
	attachments = None
	try:
		from frappe.utils.pdf import get_pdf

		attachments = [{"fname": f"daily-summary-{metrics['date']}.pdf", "fcontent": get_pdf(html)}]
	except Exception as exc:
		metrics["pdf_error"] = str(exc)[:200]
		frappe.logger("horizon_jobs").warning(f"send_daily_summary: PDF skipped ({exc!r})")

	recipients = users_with_roles("Finance Director", "Operations Head")
	metrics["recipients"] = recipients
	if recipients and not safe_sendmail(
		"Horizon daily summary: email failed",
		recipients=recipients,
		subject=_("Horizon Daily Summary {0}").format(metrics["date"]),
		message=html,
		attachments=attachments,
	):
		metrics["email_error"] = True
	return metrics


@frappe.whitelist()
def preview_daily_summary(date=None):
	"""Return the rendered daily summary HTML for a manual check (System Manager only)."""
	frappe.only_for("System Manager")
	return render_daily_summary(get_daily_summary_metrics(date))

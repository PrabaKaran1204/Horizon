# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Hourly scheduler tasks (see ``scheduler_events`` in hooks.py).

See ``horizon_erp.tasks`` for the logging / alerting conventions shared by every job.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Abs, IfNull, Sum
from frappe.utils import (
	add_to_date,
	cint,
	flt,
	fmt_money,
	get_datetime,
	get_url_to_form,
	now_datetime,
	time_diff_in_hours,
	today,
)

from horizon_erp.tasks import (
	add_info_comment,
	cache_delete,
	cache_get,
	cache_set,
	horizon_job,
	logger,
	notify_users,
	users_with_roles,
)

# ---------------------------------------------------------------------------
# PO approval SLA configuration
# ---------------------------------------------------------------------------
# One ordered approver chain. Index i of every chain maps to PO_APPROVER_ROLES[i]. Two naming
# families are accepted so the job works whether the workflow developer names the states
# "Pending Dept Head / Procurement Manager / Finance Director" (functional brief) or
# "Pending Level 1/2/3 Approval" (hooks.py fixture list). Escalation always moves to the next
# state of the *same* family. The last approver never escalates further.
PO_APPROVAL_CHAINS = [
	["Pending Dept Head", "Pending Procurement Manager", "Pending Finance Director"],
	["Pending Level 1 Approval", "Pending Level 2 Approval", "Pending Level 3 Approval"],
]
PO_APPROVER_ROLES = ["Department Head", "Procurement Manager", "Finance Director"]
PO_REMINDER_AFTER_HOURS = 24  # first reminder once the PO has waited this long
PO_REMINDER_REPEAT_HOURS = 6  # and again every N hours (cache key TTL)
PO_ESCALATE_AFTER_HOURS = 48  # move to the next approver

try:  # the business-rule developer may centralise thresholds; use theirs when present
	from horizon_erp.horizon_operations import config as _ops_config

	PO_APPROVAL_CHAINS = getattr(_ops_config, "PO_APPROVAL_CHAINS", PO_APPROVAL_CHAINS)
	PO_APPROVER_ROLES = getattr(_ops_config, "PO_APPROVER_ROLES", PO_APPROVER_ROLES)
	PO_REMINDER_AFTER_HOURS = getattr(_ops_config, "PO_REMINDER_AFTER_HOURS", PO_REMINDER_AFTER_HOURS)
	PO_REMINDER_REPEAT_HOURS = getattr(_ops_config, "PO_REMINDER_EVERY_HOURS", PO_REMINDER_REPEAT_HOURS)
	PO_ESCALATE_AFTER_HOURS = getattr(_ops_config, "PO_ESCALATE_AFTER_HOURS", PO_ESCALATE_AFTER_HOURS)
except ImportError:
	pass

STOCK_ACCURACY_TOLERANCE = 0.001  # qty units; Bin vs SLE sum
COUNT_VARIANCE_PCT = 2.0  # Stock Reconciliation qty vs current_qty


# ---------------------------------------------------------------------------
# 1. Reorder + stock accuracy
# ---------------------------------------------------------------------------
@horizon_job("reorder_and_accuracy_check")
def reorder_and_accuracy_check():
	"""Hourly.

	(a) Run ERPNext's own reorder logic (``erpnext.stock.reorder_item.reorder_item``), which
	    respects Stock Settings ``auto_indent`` and the ``Item Reorder`` rows maintained by
	    ``daily.recompute_reorder_levels``; report Material Requests created in the last hour.
	(b) Stock accuracy: every Bin whose ``actual_qty`` differs from the sum of its non-cancelled
	    Stock Ledger Entries is flagged with an Info comment on the Item (once per day), and so is
	    every item on a Stock Reconciliation submitted today whose counted qty deviates more than
	    ``COUNT_VARIANCE_PCT`` from the system qty ("physical count variance").

	Returns ``{"material_requests": n, "bin_mismatches": [...], "count_variances": [...]}``.
	"""
	out = {"material_requests": 0, "bin_mismatches": [], "count_variances": [], "reorder_error": None}

	try:
		from erpnext.stock.reorder_item import reorder_item

		reorder_item()
	except Exception as exc:
		# reorder failures (e.g. missing default supplier) must not block the accuracy check
		out["reorder_error"] = str(exc)[:200]
		frappe.log_error(title="Horizon hourly: ERPNext reorder_item failed")

	out["material_requests"] = frappe.db.count(
		"Material Request", {"creation": [">=", add_to_date(now_datetime(), hours=-1)]}
	)

	out["bin_mismatches"] = _flag_bin_mismatches()
	out["count_variances"] = _flag_count_variances()
	return out


def _flag_bin_mismatches():
	bin_ = frappe.qb.DocType("Bin")
	sle = frappe.qb.DocType("Stock Ledger Entry")
	sle_sum = IfNull(Sum(sle.actual_qty), 0)
	rows = (
		frappe.qb.from_(bin_)
		.left_join(sle)
		.on((sle.item_code == bin_.item_code) & (sle.warehouse == bin_.warehouse) & (sle.is_cancelled == 0))
		.select(bin_.item_code, bin_.warehouse, bin_.actual_qty.as_("bin_qty"), sle_sum.as_("sle_qty"))
		.groupby(bin_.item_code, bin_.warehouse, bin_.actual_qty)
		.having(Abs(bin_.actual_qty - sle_sum) > STOCK_ACCURACY_TOLERANCE)
		.limit(500)
	).run(as_dict=True)

	flagged = []
	for row in rows:
		flagged.append(
			{
				"item_code": row.item_code,
				"warehouse": row.warehouse,
				"bin_qty": flt(row.bin_qty),
				"sle_qty": flt(row.sle_qty),
			}
		)
		add_info_comment(
			"Item",
			row.item_code,
			_("Stock accuracy flag: Bin {0} vs SLE {1} in {2}").format(
				flt(row.bin_qty), flt(row.sle_qty), row.warehouse
			),
			dedupe_prefix="Stock accuracy flag",
		)
	return flagged


def _flag_count_variances():
	sr = frappe.qb.DocType("Stock Reconciliation")
	sri = frappe.qb.DocType("Stock Reconciliation Item")
	rows = (
		frappe.qb.from_(sri)
		.join(sr)
		.on(sri.parent == sr.name)
		.select(sr.name.as_("reconciliation"), sri.item_code, sri.warehouse, sri.qty, sri.current_qty)
		.where((sr.docstatus == 1) & (sr.posting_date == today()))
	).run(as_dict=True)

	flagged = []
	for row in rows:
		counted, system = flt(row.qty), flt(row.current_qty)
		if system:
			variance_pct = abs(counted - system) / abs(system) * 100
		else:
			variance_pct = 100.0 if counted else 0.0
		if variance_pct <= COUNT_VARIANCE_PCT:
			continue
		flagged.append(
			{
				"reconciliation": row.reconciliation,
				"item_code": row.item_code,
				"warehouse": row.warehouse,
				"system_qty": system,
				"counted_qty": counted,
				"variance_pct": round(variance_pct, 2),
			}
		)
		add_info_comment(
			"Item",
			row.item_code,
			_("Physical count variance: counted {0} vs system {1} ({2}%) in {3} ({4})").format(
				counted, system, round(variance_pct, 1), row.warehouse, row.reconciliation
			),
			dedupe_prefix="Physical count variance",
		)
	return flagged


# ---------------------------------------------------------------------------
# 2. PO approval reminders / escalation
# ---------------------------------------------------------------------------
def _locate_state(state):
	"""Return ``(chain, index)`` for a pending workflow state, or ``(None, None)``."""
	for chain in PO_APPROVAL_CHAINS:
		if state in chain:
			return chain, chain.index(state)
	return None, None


@horizon_job("po_approval_reminders")
def po_approval_reminders():
	"""Hourly PO approval SLA.

	For every draft Purchase Order in a ``Pending*`` workflow state, age = now - (``pending_since``
	or ``modified``):

	* age > ``PO_REMINDER_AFTER_HOURS``: remind the approvers of the current state (users holding
	  the mapped role) by Notification Log + email, at most every ``PO_REMINDER_REPEAT_HOURS``
	  (cache key ``horizon:po_reminder:{name}``).
	* age > ``PO_ESCALATE_AFTER_HOURS``: escalate - move ``workflow_state`` to the next approver of
	  the chain via ``frappe.db.set_value`` (no workflow action is applied, nothing is approved),
	  reset ``pending_since``, add a Comment and email both the old and the new approvers.
	  The last approver in the chain is never escalated past; they just keep getting reminders.

	Returns ``{"checked": n, "reminded": n, "escalated": n, "details": [...]}``.
	"""
	out = {"checked": 0, "reminded": 0, "escalated": 0, "details": []}
	if not frappe.db.has_column("Purchase Order", "workflow_state"):
		out["skipped"] = "Purchase Order has no workflow_state field (no workflow installed yet)"
		return out

	fields = ["name", "supplier", "grand_total", "currency", "workflow_state", "modified", "owner"]
	has_pending_since = frappe.db.has_column("Purchase Order", "pending_since")
	if has_pending_since:
		fields.append("pending_since")

	pos = frappe.get_all(
		"Purchase Order",
		filters={"docstatus": 0, "workflow_state": ["like", "Pending%"]},
		fields=fields,
	)
	now = now_datetime()

	for po in pos:
		out["checked"] += 1
		chain, index = _locate_state(po.workflow_state)
		if chain is None:
			logger().warning(f"po_approval_reminders: unknown pending state {po.workflow_state} on {po.name}")
			continue

		since = get_datetime(po.get("pending_since") or po.modified)
		age_hours = flt(time_diff_in_hours(now, since))
		if age_hours <= PO_REMINDER_AFTER_HOURS:
			continue

		role = PO_APPROVER_ROLES[index]
		amount = fmt_money(po.grand_total, currency=po.currency)
		link = get_url_to_form("Purchase Order", po.name)

		if age_hours > PO_ESCALATE_AFTER_HOURS and index < len(chain) - 1:
			new_state = chain[index + 1]
			new_role = PO_APPROVER_ROLES[index + 1]
			values = {"workflow_state": new_state}
			if has_pending_since:
				values["pending_since"] = now
			frappe.db.set_value("Purchase Order", po.name, values, update_modified=False)
			add_info_comment(
				"Purchase Order",
				po.name,
				_("Auto-escalated after {0}h without action: {1} → {2}").format(
					PO_ESCALATE_AFTER_HOURS, po.workflow_state, new_state
				),
			)
			subject = _("PO {0} escalated to {1} after {2}h").format(po.name, new_role, cint(age_hours))
			message = _(
				"Purchase Order <a href='{0}'>{1}</a> for {2} ({3}) waited {4}h in state <b>{5}</b> "
				"and was escalated to <b>{6}</b>."
			).format(link, po.name, po.supplier, amount, cint(age_hours), po.workflow_state, new_state)
			notify_users(
				users_with_roles(role, new_role), subject, message, doctype="Purchase Order", docname=po.name
			)
			cache_delete(f"horizon:po_reminder:{po.name}")
			out["escalated"] += 1
			out["details"].append(
				{"name": po.name, "action": "escalated", "to": new_state, "age_h": age_hours}
			)
			continue

		cache_key = f"horizon:po_reminder:{po.name}"
		if cache_get(cache_key):
			continue  # reminded within the last PO_REMINDER_REPEAT_HOURS

		subject = _("Reminder: PO {0} ({1}) awaiting your approval for {2}h").format(
			po.name, amount, cint(age_hours)
		)
		message = _(
			"Purchase Order <a href='{0}'>{1}</a> for supplier {2}, amount {3}, has been in state "
			"<b>{4}</b> for {5} hours. It will be escalated to the next approver after {6} hours."
		).format(
			link, po.name, po.supplier, amount, po.workflow_state, cint(age_hours), PO_ESCALATE_AFTER_HOURS
		)
		notify_users(users_with_roles(role), subject, message, doctype="Purchase Order", docname=po.name)
		cache_set(cache_key, 1, PO_REMINDER_REPEAT_HOURS * 3600)
		out["reminded"] += 1
		out["details"].append({"name": po.name, "action": "reminded", "role": role, "age_h": age_hours})

	return out

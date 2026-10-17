# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Buying scheduler jobs: hourly Purchase Order approval reminders / escalation.

Scheduled from ``scheduler_events`` in hooks.py. Logging / alerting conventions shared by every job
(``@horizon_job``, Error Log + System Manager alert, retry marker) live in
``horizon_erp.horizon_core.jobs``.
"""

import frappe
from frappe import _
from frappe.utils import (
	cint,
	flt,
	fmt_money,
	get_datetime,
	get_url_to_form,
	now_datetime,
	time_diff_in_hours,
)

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.jobs import (
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
# families are accepted so the job works whether the workflow names the states
# "Pending Dept Head / Procurement Manager / Finance Director" (functional brief) or
# "Pending Level 1/2/3 Approval". Escalation always moves to the next state of the *same*
# family. The last approver never escalates further. Central thresholds: horizon_core.config.
PO_APPROVAL_CHAINS = getattr(
	config,
	"PO_APPROVAL_CHAINS",
	[
		["Pending Dept Head", "Pending Procurement Manager", "Pending Finance Director"],
		["Pending Level 1 Approval", "Pending Level 2 Approval", "Pending Level 3 Approval"],
	],
)
PO_APPROVER_ROLES = getattr(
	config, "PO_APPROVER_ROLES", ["Department Head", "Procurement Manager", "Finance Director"]
)
PO_REMINDER_AFTER_HOURS = config.PO_REMINDER_AFTER_HOURS  # first reminder once the PO waited this long
PO_REMINDER_REPEAT_HOURS = config.PO_REMINDER_EVERY_HOURS  # and again every N hours (cache key TTL)
PO_ESCALATE_AFTER_HOURS = config.PO_ESCALATE_AFTER_HOURS  # move to the next approver


# ---------------------------------------------------------------------------
# PO approval reminders / escalation
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

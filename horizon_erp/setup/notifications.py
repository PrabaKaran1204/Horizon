# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Horizon Notification documents (email + system notifications driven by document events).

``setup_notifications`` is idempotent (create or update by name) and every Notification is
validated by Frappe on save (Jinja in subject / message, condition against an empty document).
They are exported as fixtures (``hooks.py``: Notification ``name like "Horizon%"``) so this
module is the single source of truth when editing them.

Design notes
- "Horizon PO Approval Request" fires on ``Value Change`` of ``workflow_state``. That field is a
  Custom Field created by the "Horizon PO Approval" workflow; until the workflow exists Frappe
  skips the alert silently (``frappe.db.has_column`` check in ``evaluate_alert``).
- Recipients by role each carry their own condition so only the approver of the current state
  is emailed.
- "Horizon Delivery Dispatched" attaches the Delivery Note's default print format (not the
  thermal packing slip, which is an internal warehouse document).
"""

import frappe

MODULE = "Horizon Operations"

PO_APPROVER_STATES = {
	"Department Head": ("Pending Dept Head", "Pending Level 1 Approval"),
	"Procurement Manager": ("Pending Procurement Manager", "Pending Level 2 Approval"),
	"Finance Director": ("Pending Finance Director", "Pending Level 3 Approval"),
}


def _po_recipients():
	rows = []
	for role, states in PO_APPROVER_STATES.items():
		rows.append(
			{
				"receiver_by_role": role,
				"condition": "doc.workflow_state in " + repr(list(states)),
			}
		)
	return rows


def get_notifications():
	return [
		{
			"name": "Horizon Delivery Dispatched",
			"document_type": "Delivery Note",
			"event": "Submit",
			"channel": "Email",
			"send_system_notification": 0,
			"condition": "doc.contact_email",
			"subject": "Your order {{ doc.po_no or doc.name }} has been dispatched",
			"attach_print": 1,
			"print_format": None,
			"recipients": [{"receiver_by_document_field": "contact_email"}],
			"message": """<p>Dear {{ doc.customer_name or doc.customer }},</p>
<p>Your order <b>{{ doc.po_no or doc.name }}</b> was dispatched on {{ frappe.format_date(doc.posting_date) }}
from {{ doc.company }}.</p>
<table border="1" cellpadding="4" cellspacing="0" style="border-collapse: collapse;">
	<tr><th>Item</th><th>Qty</th></tr>
	{% for row in doc.items %}
	<tr><td>{{ row.item_name or row.item_code }}</td><td style="text-align: right;">{{ row.qty }} {{ row.uom }}</td></tr>
	{% endfor %}
</table>
{% if doc.lr_no %}<p>Transporter reference: {{ doc.transporter_name or "" }} {{ doc.lr_no }}</p>{% endif %}
<p>Delivery Note: <a href="{{ frappe.utils.get_url_to_form("Delivery Note", doc.name) }}">{{ doc.name }}</a>
(the delivery note is attached).</p>
<p>Thank you for your business.<br>{{ doc.company }}</p>""",
		},
		{
			"name": "Horizon PO Approval Request",
			"document_type": "Purchase Order",
			"event": "Value Change",
			"value_changed": "workflow_state",
			"channel": "Email",
			"send_system_notification": 1,
			"condition": 'doc.workflow_state and doc.workflow_state.startswith("Pending")',
			"subject": "PO {{ doc.name }} ₹{{ frappe.utils.fmt_money(doc.grand_total) }} awaiting your approval",
			"recipients": _po_recipients(),
			"message": """<p>Purchase Order <a href="{{ frappe.utils.get_url_to_form("Purchase Order", doc.name) }}">{{ doc.name }}</a>
is waiting in state <b>{{ doc.workflow_state }}</b>.</p>
<ul>
	<li>Supplier: <b>{{ doc.supplier_name or doc.supplier }}</b></li>
	<li>Amount: <b>{{ doc.currency }} {{ frappe.utils.fmt_money(doc.grand_total) }}</b></li>
	<li>Approval level required: {{ doc.approval_level_required or "-" }}</li>
	<li>Blacklist override: {% if doc.blacklist_override %}<b style="color: #b71c1c;">YES</b> - {{ doc.override_reason }}{% else %}No{% endif %}</li>
	<li>Requested by: {{ doc.owner }} on {{ frappe.format_date(doc.transaction_date) }}</li>
</ul>
<p>Reminders are sent after 24 h and the PO is escalated to the next approver after 48 h without action.</p>""",
		},
		{
			"name": "Horizon Production Audit Low Score",
			"document_type": "Production Audit",
			"event": "Submit",
			"channel": "Email",
			"send_system_notification": 1,
			"condition": "doc.audit_score < 70",
			"subject": "Production Audit {{ doc.name }} scored {{ doc.audit_score }} on {{ doc.work_order }}",
			"recipients": [{"receiver_by_role": "Operations Head"}],
			"message": """<p>Production Audit <a href="{{ frappe.utils.get_url_to_form("Production Audit", doc.name) }}">{{ doc.name }}</a>
scored <b style="color: #b71c1c;">{{ doc.audit_score }}</b> (threshold 70).</p>
<ul>
	<li>Work Order: {{ doc.work_order }} ({{ doc.item_code }})</li>
	<li>Workstation: {{ doc.workstation or "-" }}</li>
	<li>Audit date: {{ frappe.format_date(doc.audit_date) }}</li>
	<li>Inspector: {{ doc.inspector or "-" }}</li>
</ul>
{% if doc.findings %}<div>{{ doc.findings }}</div>{% endif %}
<p>Please review and record a corrective action.</p>""",
		},
		{
			"name": "Horizon Quotation Expiring",
			"document_type": "Quotation",
			"event": "Days Before",
			"date_changed": "valid_till",
			"days_in_advance": 3,
			"channel": "Email",
			"send_system_notification": 1,
			"condition": 'doc.status == "Open"',
			"subject": "Quotation {{ doc.name }} for {{ doc.customer_name or doc.party_name }} expires on {{ frappe.format_date(doc.valid_till) }}",
			"recipients": [{"receiver_by_document_field": "owner"}],
			"message": """<p>Quotation <a href="{{ frappe.utils.get_url_to_form("Quotation", doc.name) }}">{{ doc.name }}</a>
for <b>{{ doc.customer_name or doc.party_name }}</b> ({{ doc.currency }} {{ frappe.utils.fmt_money(doc.grand_total) }})
is still Open and expires on <b>{{ frappe.format_date(doc.valid_till) }}</b>.</p>
<p>Follow up with the customer or extend the validity.</p>""",
		},
	]


def setup_notifications():
	"""Create / update every Horizon Notification. Returns the list of names processed."""
	done = []
	for spec in get_notifications():
		spec = dict(spec)
		name = spec.pop("name")
		recipients = spec.pop("recipients", [])
		values = {
			"module": MODULE,
			"enabled": 1,
			"is_standard": 0,
			"message_type": "HTML",
			"attach_print": 0,
			"print_format": None,
			"value_changed": None,
			"date_changed": None,
			"days_in_advance": 0,
			"send_system_notification": 0,
			**spec,
		}
		is_new = not frappe.db.exists("Notification", name)
		if is_new:
			doc = frappe.get_doc({"doctype": "Notification", "name": name, **values})
		else:
			doc = frappe.get_doc("Notification", name)
			doc.update(values)
		doc.set("recipients", [])
		for r in recipients:
			doc.append("recipients", r)
		doc.flags.ignore_permissions = True
		if is_new:
			doc.insert()
		else:
			doc.save()
		done.append(doc.name)
	return done

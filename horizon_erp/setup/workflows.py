# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Horizon approval workflows, created in code so they are reproducible on every bench.

Run with ``bench --site <site> execute horizon_erp.setup.workflows.setup_workflows`` or from
``horizon_erp.setup.demo_data.setup_all``. Idempotent: an existing workflow is rebuilt in place
(states / transitions replaced), Workflow State and Workflow Action Master masters are created only
when missing. Workflow names, states and actions used here must also be listed in the fixture
filters in ``hooks.py`` (``horizon_workflows`` / ``horizon_workflow_states`` /
``horizon_workflow_actions``) before ``bench export-fixtures``.

Design notes
- ``allow_self_approval`` = 1 on every transition: demo convenience so one user can walk a document
  through all levels. Set it to 0 for production segregation of duties.
- A direct ``doc.submit()`` from server code bypasses the workflow (Frappe only enforces transitions
  through the UI / ``apply_workflow``). Business rules that must hold regardless are therefore also
  enforced in the ``validate`` hooks (see ``horizon_operations.buying`` / ``selling``).
- ``send_email_alert`` = 1 so the standard Workflow Action emails reach the next approver role.
"""

import frappe

from horizon_erp.horizon_operations import config

WORKFLOW_STATE_STYLES = {
	"Draft": "",
	"Pending Dept Head": "Warning",
	"Pending Procurement Manager": "Warning",
	"Pending Finance Director": "Warning",
	"Pending Discount Approval": "Warning",
	"Approved": "Success",
	"Rejected": "Danger",
	"Submitted": "Primary",
	"Reviewed": "Info",
	"Action Closed": "Success",
}

# state tuples: (state, doc_status, allow_edit role, update_field, update_value)
# transition tuples: (state, action, next_state, allowed role, condition)
PO_L1 = config.PO_LEVEL_1_LIMIT
PO_L2 = config.PO_LEVEL_2_LIMIT

WORKFLOWS = [
	{
		"workflow_name": "Horizon PO Approval",
		"document_type": "Purchase Order",
		"states": [
			("Draft", 0, config.ROLE_PURCHASE_USER),
			("Pending Dept Head", 0, config.ROLE_DEPARTMENT_HEAD),
			("Pending Procurement Manager", 0, config.ROLE_PROCUREMENT_MANAGER),
			("Pending Finance Director", 0, config.ROLE_FINANCE_DIRECTOR),
			("Approved", 1, config.ROLE_PURCHASE_MANAGER),
			("Rejected", 0, config.ROLE_PURCHASE_USER),
		],
		"transitions": [
			("Draft", "Submit for Approval", "Pending Dept Head", config.ROLE_PURCHASE_USER, ""),
			(
				"Pending Dept Head",
				"Approve",
				"Approved",
				config.ROLE_DEPARTMENT_HEAD,
				f"doc.grand_total < {PO_L1} and not doc.blacklist_override",
			),
			(
				"Pending Dept Head",
				"Approve",
				"Pending Procurement Manager",
				config.ROLE_DEPARTMENT_HEAD,
				f"doc.grand_total >= {PO_L1} or doc.blacklist_override",
			),
			("Pending Dept Head", "Reject", "Rejected", config.ROLE_DEPARTMENT_HEAD, ""),
			(
				"Pending Procurement Manager",
				"Approve",
				"Approved",
				config.ROLE_PROCUREMENT_MANAGER,
				f"doc.grand_total <= {PO_L2} and not doc.blacklist_override",
			),
			(
				"Pending Procurement Manager",
				"Approve",
				"Pending Finance Director",
				config.ROLE_PROCUREMENT_MANAGER,
				f"doc.grand_total > {PO_L2} or doc.blacklist_override",
			),
			("Pending Procurement Manager", "Reject", "Rejected", config.ROLE_PROCUREMENT_MANAGER, ""),
			("Pending Finance Director", "Approve", "Approved", config.ROLE_FINANCE_DIRECTOR, ""),
			("Pending Finance Director", "Reject", "Rejected", config.ROLE_FINANCE_DIRECTOR, ""),
			("Rejected", "Revise", "Draft", config.ROLE_PURCHASE_USER, ""),
		],
	},
	{
		"workflow_name": "Horizon Discount Approval",
		"document_type": "Quotation",
		"states": "DISCOUNT",
		"transitions": "DISCOUNT",
	},
	{
		"workflow_name": "Horizon Discount Approval - Sales Order",
		"document_type": "Sales Order",
		"states": "DISCOUNT",
		"transitions": "DISCOUNT",
	},
	{
		"workflow_name": "Horizon Production Audit",
		"document_type": "Production Audit",
		"states": [
			("Draft", 0, config.ROLE_QUALITY_INSPECTOR, "status", "Draft"),
			("Submitted", 1, config.ROLE_QUALITY_INSPECTOR, "status", "Submitted"),
			("Reviewed", 1, config.ROLE_OPERATIONS_HEAD, "status", "Reviewed"),
			("Action Closed", 1, config.ROLE_OPERATIONS_HEAD, "status", "Action Closed"),
		],
		"transitions": [
			("Draft", "Submit", "Submitted", config.ROLE_QUALITY_INSPECTOR, ""),
			("Submitted", "Review", "Reviewed", config.ROLE_QUALITY_MANAGER, ""),
			("Submitted", "Review", "Reviewed", config.ROLE_OPERATIONS_HEAD, ""),
			(
				"Reviewed",
				"Close Action",
				"Action Closed",
				config.ROLE_OPERATIONS_HEAD,
				f"doc.audit_score >= {config.AUDIT_FAIL_SCORE} or doc.corrective_action",
			),
		],
	},
	{
		"workflow_name": "Horizon Payment Approval",
		"document_type": "Payment Entry",
		"states": [
			("Draft", 0, config.ROLE_ACCOUNTS_USER),
			("Pending Finance Director", 0, config.ROLE_FINANCE_DIRECTOR),
			("Approved", 1, "Accounts Manager"),
		],
		"transitions": [
			(
				"Draft",
				"Submit",
				"Approved",
				config.ROLE_ACCOUNTS_USER,
				f"doc.paid_amount < {config.PAYMENT_APPROVAL_LIMIT}",
			),
			(
				"Draft",
				"Submit for Approval",
				"Pending Finance Director",
				config.ROLE_ACCOUNTS_USER,
				f"doc.paid_amount >= {config.PAYMENT_APPROVAL_LIMIT}",
			),
			("Pending Finance Director", "Approve", "Approved", config.ROLE_FINANCE_DIRECTOR, ""),
			("Pending Finance Director", "Reject", "Draft", config.ROLE_FINANCE_DIRECTOR, ""),
		],
	},
]

DISCOUNT_STATES = [
	("Draft", 0, config.ROLE_SALES_USER),
	("Pending Discount Approval", 0, config.ROLE_SALES_MANAGER),
	("Approved", 1, config.ROLE_SALES_MANAGER),
]

DISCOUNT_TRANSITIONS = [
	("Draft", "Submit", "Approved", config.ROLE_SALES_USER, "not doc.needs_discount_approval"),
	(
		"Draft",
		"Submit for Discount Approval",
		"Pending Discount Approval",
		config.ROLE_SALES_USER,
		"doc.needs_discount_approval",
	),
	("Pending Discount Approval", "Approve", "Approved", config.ROLE_SALES_MANAGER, ""),
	("Pending Discount Approval", "Reject", "Draft", config.ROLE_SALES_MANAGER, ""),
]


def get_workflow_definitions():
	"""Resolve the shared DISCOUNT shape and return the full list of workflow definitions."""
	definitions = []
	for wf in WORKFLOWS:
		wf = dict(wf)
		if wf["states"] == "DISCOUNT":
			wf["states"] = DISCOUNT_STATES
		if wf["transitions"] == "DISCOUNT":
			wf["transitions"] = DISCOUNT_TRANSITIONS
		definitions.append(wf)
	return definitions


def get_state_names():
	return sorted({s[0] for wf in get_workflow_definitions() for s in wf["states"]})


def get_action_names():
	return sorted({t[1] for wf in get_workflow_definitions() for t in wf["transitions"]})


def ensure_workflow_states():
	for state in get_state_names():
		if frappe.db.exists("Workflow State", state):
			continue
		doc = frappe.new_doc("Workflow State")
		doc.workflow_state_name = state
		doc.style = WORKFLOW_STATE_STYLES.get(state, "")
		doc.insert(ignore_permissions=True)


def ensure_workflow_actions():
	for action in get_action_names():
		if frappe.db.exists("Workflow Action Master", action):
			continue
		doc = frappe.new_doc("Workflow Action Master")
		doc.workflow_action_name = action
		doc.insert(ignore_permissions=True)


def ensure_roles(definitions):
	"""Roles referenced by the workflows must exist (ERPNext ships most; Horizon roles come
	from ``setup.roles``). Missing custom roles are created so the workflow can be saved."""
	roles = set()
	for wf in definitions:
		roles.update(s[2] for s in wf["states"])
		roles.update(t[3] for t in wf["transitions"])
	for role in roles:
		if not frappe.db.exists("Role", role):
			doc = frappe.new_doc("Role")
			doc.role_name = role
			doc.desk_access = 1
			doc.is_custom = 1
			doc.insert(ignore_permissions=True)


def upsert_workflow(definition):
	name = definition["workflow_name"]
	if frappe.db.exists("Workflow", name):
		workflow = frappe.get_doc("Workflow", name)
	else:
		workflow = frappe.new_doc("Workflow")
		workflow.workflow_name = name

	workflow.document_type = definition["document_type"]
	workflow.workflow_state_field = "workflow_state"
	workflow.is_active = 1
	workflow.send_email_alert = 1
	workflow.override_status = 0
	workflow.set("states", [])
	workflow.set("transitions", [])

	for state in definition["states"]:
		row = {
			"state": state[0],
			"doc_status": str(state[1]),
			"allow_edit": state[2],
		}
		if len(state) > 3:
			row["update_field"] = state[3]
			row["update_value"] = state[4]
		workflow.append("states", row)

	for state, action, next_state, allowed, condition in definition["transitions"]:
		workflow.append(
			"transitions",
			{
				"state": state,
				"action": action,
				"next_state": next_state,
				"allowed": allowed,
				"allow_self_approval": 1,
				"condition": condition or None,
			},
		)

	workflow.flags.ignore_permissions = True
	workflow.save()
	return workflow


def setup_workflows():
	"""Create / refresh every Horizon workflow. Safe to run repeatedly."""
	definitions = get_workflow_definitions()
	ensure_roles(definitions)
	ensure_workflow_states()
	ensure_workflow_actions()
	for definition in definitions:
		upsert_workflow(definition)
	frappe.clear_cache()
	return [d["workflow_name"] for d in definitions]

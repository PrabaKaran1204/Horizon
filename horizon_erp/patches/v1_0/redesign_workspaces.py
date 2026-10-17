# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Remove the workspaces / charts replaced by the per-assignment-section workspace redesign.

Before: six unrelated top-level workspaces (Horizon Quality, Warehouse, Approvals, Inventory Health,
Sales Pipeline, Production) and a "Stock Movement 90d" chart.
After:  one parent *Horizon ERP* with one child per assignment section (Setup & Masters, Selling,
Buying, Inventory, Manufacturing, Quality, Projects & Assets, HR & Payroll, Accounts & Finance,
Integrations). *Horizon Quality* is kept and rewritten in place by the JSON sync.

Runs in ``[post_model_sync]``: ``frappe.model.sync`` has already imported the new workspace JSON, and
``sync_fixtures`` / ``sync_dashboards`` (which run after the patches) no longer ship the deleted
records, so nothing re-creates them. Idempotent - a second run finds nothing to delete.
"""

import frappe

# Workspaces go first: their chart / number card rows link to the records deleted after them.
OBSOLETE = (
	(
		"Workspace",
		(
			"Horizon Warehouse",
			"Horizon Inventory Health",
			"Horizon Approvals",
			"Horizon Sales Pipeline",
			"Horizon Production",
		),
	),
	("Dashboard Chart", ("Horizon Stock Movement 90d",)),
)


def execute():
	for doctype, names in OBSOLETE:
		for name in names:
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.cache.delete_key("bootinfo")

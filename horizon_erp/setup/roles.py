# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Roles used by Horizon workflows, DocType permissions and notifications.

Keep ``HORIZON_ROLES`` in sync with the Role fixture filter in ``hooks.py``.
"""

import frappe

HORIZON_ROLES = [
	"Department Head",
	"Procurement Manager",
	"Finance Director",
	"Operations Head",
	"Sales Manager",  # shipped by ERPNext; created only if missing
	"Warehouse Manager",
	"Quality Inspector",
	"HR Manager",  # shipped by HRMS; created only if missing
]


def setup_roles():
	"""Create every role in ``HORIZON_ROLES`` with desk access. Idempotent."""
	for role_name in HORIZON_ROLES:
		if frappe.db.exists("Role", role_name):
			continue

		role = frappe.new_doc("Role")
		role.role_name = role_name
		role.desk_access = 1
		role.is_custom = 1
		role.insert(ignore_permissions=True)

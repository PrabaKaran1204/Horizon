# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Roles used by Horizon workflows, DocType permissions and notifications.

Keep ``HORIZON_ROLES`` in sync with the Role fixture filter in ``hooks.py``.

``setup_role_permissions`` closes the gaps of the standard ERPNext role matrix that made the
receiving and dispatch flows impossible for the people who own them (QA DEF-02 / DEF-04 / DEF-14):
Batch is "Item Manager only", Serial No create is "Stock Manager only", Address / Contact are
readable only by Sales / Purchase / Accounts users (the ``All`` rule is ``if_owner``), and the
Quality Inspector role has no rule on Quality Inspection. The grants are written as Custom DocPerm
rows (``frappe.permissions.add_permission`` / ``update_permission_property``), never by editing
the standard DocType JSON, so they survive an ERPNext upgrade. The affected Custom DocPerm rows are
exported as fixtures (see ``hooks.py``) and re-applied on every ``bench migrate``.
"""

import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
from frappe.permissions import add_permission, setup_custom_perms, update_permission_property

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

READ = ("read",)
EDIT = ("read", "write", "create")
TRANSACT = ("read", "write", "create", "submit", "cancel")

# {doctype: {role: ptypes}} - permlevel 0 only. Only the listed ptypes are switched ON; nothing is
# ever switched off, so standard grants stay untouched.
ROLE_PERMISSIONS = {
	# receiving / dispatch of batch- and serial-tracked items (DEF-02, DEF-04)
	"Batch": {"Stock User": EDIT, "Purchase User": EDIT, "Manufacturing User": EDIT},
	"Serial No": {"Stock User": EDIT, "Purchase User": EDIT, "Sales User": EDIT, "Manufacturing User": EDIT},
	"Serial and Batch Bundle": {
		"Stock User": TRANSACT,
		"Sales User": TRANSACT,
		"Purchase User": TRANSACT,
		"Manufacturing User": TRANSACT,
	},
	# mapping a PR / DN reads the party's Address and Contact; frappe's Address ``has_permission``
	# additionally requires read on the linked Supplier / Customer
	"Address": {
		"Stock User": READ,
		"Stock Manager": READ,
		"Warehouse Manager": READ,
		"Manufacturing User": READ,
	},
	"Contact": {
		"Stock User": READ,
		"Stock Manager": READ,
		"Warehouse Manager": READ,
		"Manufacturing User": READ,
	},
	"Supplier": {"Stock User": READ, "Stock Manager": READ, "Warehouse Manager": READ},
	"Customer": {"Stock User": READ, "Stock Manager": READ, "Warehouse Manager": READ},
	# a pure Quality Inspector must be able to record inspections (DEF-14)
	"Quality Inspection": {"Quality Inspector": TRANSACT, "Stock User": READ},
	# the draft invoice is created server-side on Delivery Note submit (ignore_permissions); the
	# dispatcher (Sales User or Warehouse Manager, QA OBS-R2-1) only needs to see it
	"Sales Invoice": {"Sales User": READ, "Warehouse Manager": READ},
	# a Warehouse Manager dispatches without holding Stock User
	"Delivery Note": {"Warehouse Manager": TRANSACT},
	# Stock Balance is granted to Accounts Manager, but its prepared run checks read on every
	# linked DocType and UOM is stock-roles only: the Finance Director's run failed
	"UOM": {"Accounts Manager": READ, "Finance Director": READ},
}

# Roles / DocTypes referenced above - used by the Custom DocPerm fixture filter in hooks.py
PERMISSION_ROLES = sorted({role for perms in ROLE_PERMISSIONS.values() for role in perms})
PERMISSION_DOCTYPES = sorted(ROLE_PERMISSIONS)


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


def setup_role_permissions():
	"""Apply ``ROLE_PERMISSIONS`` as Custom DocPerm rows. Idempotent; returns the list of
	``(doctype, role, ptype)`` grants that were actually changed."""
	changed = []
	for doctype, role_perms in ROLE_PERMISSIONS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		_mirror_standard_perms(doctype)
		for role, ptypes in role_perms.items():
			if not frappe.db.exists("Role", role):
				continue
			changed.extend(_grant(doctype, role, ptypes))
		validate_permissions_for_doctype(doctype)
		frappe.clear_cache(doctype=doctype)
	return changed


def _mirror_standard_perms(doctype):
	"""Once a DocType has any Custom DocPerm row, frappe ignores its standard DocPerm rows
	entirely. If the fixture import created only *our* rows (fresh install), the standard roles
	would silently lose access - copy any standard rule that has no custom counterpart first."""
	if setup_custom_perms(doctype):
		return  # nothing existed; frappe copied every standard rule
	custom = {
		(p.role, p.permlevel, p.if_owner)
		for p in frappe.get_all(
			"Custom DocPerm", filters={"parent": doctype}, fields=["role", "permlevel", "if_owner"]
		)
	}
	for perm in frappe.get_all("DocPerm", filters={"parent": doctype}, fields=["*"]):
		if (perm.role, perm.permlevel, perm.if_owner) in custom:
			continue
		custom_perm = frappe.new_doc("Custom DocPerm")
		custom_perm.update(perm)
		custom_perm.insert(ignore_permissions=True)


def _grant(doctype, role, ptypes):
	existing = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
		["name", *ptypes],
		as_dict=True,
	)
	changed = []
	if not existing:
		add_permission(doctype, role, 0, ptypes[0])
		existing = frappe._dict({ptypes[0]: 1})
		changed.append((doctype, role, ptypes[0]))
	for ptype in ptypes:
		if existing.get(ptype):
			continue
		update_permission_property(doctype, role, 0, ptype, 1, validate=False)
		changed.append((doctype, role, ptype))
	return changed

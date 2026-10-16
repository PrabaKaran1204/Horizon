# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Single source of configuration for Horizon operations logic.

Every threshold, role name and warehouse name used by the buying / selling / manufacturing /
quality handlers lives here so a policy change is a one-line edit. ``horizon_erp.utils.get_setting``
is consulted first so these values can later be moved to a "Horizon Settings" Single DocType
without touching the handlers.
"""

import frappe

from horizon_erp.utils import get_setting

# --- Warehouses (name without the company abbreviation; see ``get_warehouse``) -----------------
QC_HOLD_WAREHOUSE_NAME = "HQ QC Hold"
RAW_MATERIAL_WAREHOUSE_NAME = "HQ Raw Materials"
REJECTED_WAREHOUSE_NAME = "HQ Rejected"
FINISHED_GOODS_WAREHOUSE_NAME = "HQ Finished Goods"
SCRAP_WAREHOUSE_NAME = "HQ Scrap"

# --- Selling -----------------------------------------------------------------------------------
DISCOUNT_AUTO_APPROVE_PCT = 15  # discount over pricing-rule rate above this needs Sales Manager
DISCOUNT_REASON_MIN_LENGTH = 15
STOCK_AVAILABLE_LEAD_DAYS = 2  # ex-stock dispatch lead time
WORKING_HOURS_PER_DAY = 8  # used to convert BOM operation minutes into working days

# --- Buying ------------------------------------------------------------------------------------
PO_LEVEL_1_LIMIT = 100000  # grand_total  <  1 L  -> Level 1 (Department Head)
PO_LEVEL_2_LIMIT = 500000  # 1 L <= grand_total <= 5 L -> Level 2 (Procurement Manager)
PO_REMINDER_AFTER_HOURS = 24
PO_REMINDER_EVERY_HOURS = 6
PO_ESCALATE_AFTER_HOURS = 48
OVERRIDE_REASON_MIN_LENGTH = 20

# --- Payments ----------------------------------------------------------------------------------
PAYMENT_APPROVAL_LIMIT = 100000

# --- Quality -----------------------------------------------------------------------------------
AUDIT_FAIL_SCORE = 70
AUDIT_WARN_SCORE = 85
QUALITY_PROCEDURE_NAME = "Horizon Manufacturing QC"

# --- Manufacturing -----------------------------------------------------------------------------
LINE_HOURS_PER_DAY = 16  # two shifts
LINE_DOWNTIME_PCT = {"Line A": 0.10, "Line B": 0.15}
LINE_DEFAULT_DOWNTIME_PCT = 0.10
SETUP_HOURS = 0.75
DEFAULT_PLANNING_WINDOW_DAYS = 7
PRODUCTION_LINES = ("Line A", "Line B")

# --- Roles -------------------------------------------------------------------------------------
ROLE_DEPARTMENT_HEAD = "Department Head"
ROLE_PROCUREMENT_MANAGER = "Procurement Manager"
ROLE_FINANCE_DIRECTOR = "Finance Director"
ROLE_OPERATIONS_HEAD = "Operations Head"
ROLE_SALES_MANAGER = "Sales Manager"
ROLE_WAREHOUSE_MANAGER = "Warehouse Manager"
ROLE_QUALITY_INSPECTOR = "Quality Inspector"
ROLE_QUALITY_MANAGER = "Quality Manager"
ROLE_MANUFACTURING_MANAGER = "Manufacturing Manager"
ROLE_SYSTEM_MANAGER = "System Manager"
ROLE_PURCHASE_USER = "Purchase User"
ROLE_PURCHASE_MANAGER = "Purchase Manager"
ROLE_SALES_USER = "Sales User"
ROLE_ACCOUNTS_USER = "Accounts User"

BLACKLIST_OVERRIDE_ROLES = (ROLE_PROCUREMENT_MANAGER, ROLE_FINANCE_DIRECTOR, ROLE_SYSTEM_MANAGER)
DISCOUNT_APPROVER_ROLES = (ROLE_SALES_MANAGER, ROLE_SYSTEM_MANAGER)
INVOICE_WITHOUT_DN_ROLES = (ROLE_FINANCE_DIRECTOR, ROLE_SYSTEM_MANAGER)
CAPACITY_OVERRIDE_ROLES = (ROLE_OPERATIONS_HEAD, ROLE_MANUFACTURING_MANAGER, ROLE_SYSTEM_MANAGER)


def get_threshold(key, default):
	"""Read a numeric threshold, allowing a future Horizon Settings override."""
	return frappe.utils.flt(get_setting(key, default))


def get_company_abbr(company):
	return frappe.get_cached_value("Company", company, "abbr")


def get_warehouse(base_name, company, must_exist=False):
	"""Return ``"<base_name> - <abbr>"`` for ``company``; ``None`` when it does not exist."""
	name = f"{base_name} - {get_company_abbr(company)}"
	if frappe.db.exists("Warehouse", name):
		return name
	if must_exist:
		frappe.throw(
			frappe._("Warehouse {0} is not set up for company {1}").format(
				frappe.bold(name), frappe.bold(company)
			)
		)
	return None


def get_users_with_role(role):
	"""Enabled, non-system users holding ``role`` (used for in-app notifications and email)."""
	users = frappe.get_all(
		"Has Role",
		filters={"role": role, "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	if not users:
		return []
	return frappe.get_all(
		"User",
		filters=[
			["name", "in", users],
			["name", "not in", ("Administrator", "Guest")],
			["enabled", "=", 1],
			["user_type", "=", "System User"],
		],
		pluck="name",
	)


def user_has_any_role(roles, user=None):
	"""True when ``user`` (default: session user) holds at least one of ``roles``."""
	user_roles = set(frappe.get_roles(user or frappe.session.user))
	return bool(user_roles.intersection(roles))


def get_line_downtime_pct(workstation):
	"""Downtime fraction for a line. Prefers a ``horizon_downtime_pct`` field on Workstation
	(if a later developer adds one) and falls back to the constants above."""
	if frappe.get_meta("Workstation").has_field("horizon_downtime_pct"):
		value = frappe.db.get_value("Workstation", workstation, "horizon_downtime_pct")
		if value is not None:
			return frappe.utils.flt(value) / 100 if frappe.utils.flt(value) > 1 else frappe.utils.flt(value)
	return LINE_DOWNTIME_PCT.get(workstation, LINE_DEFAULT_DOWNTIME_PCT)


def add_audit_comment(doc, content):
	"""Attach a Comment to ``doc`` even from ``validate`` during insert (the document row does not
	exist yet, so the Comment's dynamic link must skip link validation)."""
	comment = frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"comment_email": frappe.session.user,
			"comment_by": frappe.session.user,
			"content": content,
		}
	)
	comment.flags.ignore_links = True
	comment.flags.ignore_permissions = True
	comment.insert()
	return comment


def get_default_dimensions(company):
	"""``{fieldname: default}`` of Accounting Dimensions configured with a default for ``company``
	(only defaults whose target record exists; a dangling default would fail link validation)."""
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_dimensions

	dimensions, defaults = get_dimensions()
	doctype_by_field = {d.fieldname: d.document_type for d in dimensions}
	result = {}
	for fieldname, value in (defaults.get(company) or {}).items():
		if value and fieldname in doctype_by_field and frappe.db.exists(doctype_by_field[fieldname], value):
			result[fieldname] = value
	return result


def apply_default_dimensions(doc, child_fieldname="items"):
	"""Fill blank Accounting Dimension fields on ``doc`` and its ``items`` rows from the company
	defaults. Server-created documents never pass through the client-side dimension defaulting, so
	mandatory P&L dimensions would otherwise block their GL postings."""
	if not doc.get("company"):
		return doc
	defaults = get_default_dimensions(doc.company)
	if not defaults:
		return doc
	for fieldname, value in defaults.items():
		if doc.meta.has_field(fieldname) and not doc.get(fieldname):
			doc.set(fieldname, value)
		for row in doc.get(child_fieldname) or []:
			if row.meta.has_field(fieldname) and not row.get(fieldname):
				row.set(fieldname, value)
	return doc

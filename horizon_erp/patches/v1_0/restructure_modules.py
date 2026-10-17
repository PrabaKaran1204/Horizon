# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Re-home every Horizon record from the four pre-restructure modules to the domain modules.

Before: Horizon Operations, Horizon Quality, Horizon Finance, Horizon Integration.
After:  one module per ERPNext domain (modules.txt), mirroring the kaynes app layout.

Runs in ``[pre_model_sync]``: the DocType / Report / Workspace JSON files already sit in the new
module folders, so the DB ``module`` must point there *before* ``frappe.model.sync`` imports files
and before ``remove_orphan_doctypes`` (which deletes a DocType whose controller cannot be imported
from the module recorded in the DB). Only direct column updates are used: loading a Horizon
controller with a stale module would fail. Idempotent - a second run finds nothing to change.
"""

import glob
import json
import os

import frappe

APP = "horizon_erp"
NEW_MODULES = (
	"Horizon Setup",
	"Horizon Core",
	"Horizon Buying",
	"Horizon Selling",
	"Horizon CRM",
	"Horizon Stock",
	"Horizon Manufacturing",
	"Horizon Quality Management",
	"Horizon Projects",
	"Horizon HR",
	"Horizon Payroll",
	"Horizon Accounts",
	"Horizon Assets",
	"Horizon Integrations",
	"Horizon Workflow",
)
# Fallback for any record not shipped as a file by this app (e.g. a user-made report saved under an
# old module): the closest new module.
OLD_TO_FALLBACK = {
	"Horizon Operations": "Horizon Core",
	"Horizon Quality": "Horizon Quality Management",
	"Horizon Finance": "Horizon Accounts",
	"Horizon Integration": "Horizon Integrations",
}
# Records exported as module JSON: <module>/<folder>/<name>/<name>.json
FILE_DOCTYPES = {
	"doctype": "DocType",
	"report": "Report",
	"workspace": "Workspace",
	"number_card": "Number Card",
	"dashboard_chart": "Dashboard Chart",
}
# Dotted paths stored in DB fields that the restructure moved
METHOD_RENAMES = (
	("Number Card", "method", "horizon_erp.setup.dashboards.", "horizon_erp.horizon_setup.dashboards."),
)


def execute():
	ensure_module_defs()
	for doctype, name, module in shipped_records():
		set_module(doctype, name, module)
	for doctype, name, module in setup_records():
		set_module(doctype, name, module)
	for doctype, fieldname, old, new in METHOD_RENAMES:
		rename_method_prefix(doctype, fieldname, old, new)
	sweep_remaining_references()
	delete_unused_old_module_defs()
	frappe.clear_cache()


def ensure_module_defs():
	for module in NEW_MODULES:
		if frappe.db.exists("Module Def", module):
			if frappe.db.get_value("Module Def", module, "app_name") != APP:
				frappe.db.set_value("Module Def", module, "app_name", APP, update_modified=False)
			continue
		# db_insert: Module Def.on_update would rewrite modules.txt / create folders in developer mode
		frappe.get_doc(
			{"doctype": "Module Def", "module_name": module, "app_name": APP, "custom": 0}
		).db_insert()


def shipped_records():
	"""``(doctype, name, module)`` for every DocType / Report / Workspace / Number Card / Dashboard
	Chart JSON shipped in the module folders (module taken from the file)."""
	root = frappe.get_app_path(APP)
	for folder, doctype in FILE_DOCTYPES.items():
		for path in glob.glob(os.path.join(root, "horizon_*", folder, "*", "*.json")):
			if os.path.basename(os.path.dirname(path)) + ".json" != os.path.basename(path):
				continue
			with open(path, encoding="utf-8") as f:
				data = json.load(f)
			if data.get("doctype") == doctype and data.get("name") and data.get("module"):
				yield doctype, data["name"], data["module"]


def setup_records():
	"""Print Formats and Notifications created from code."""
	from horizon_erp.horizon_setup.notifications import get_notifications
	from horizon_erp.horizon_setup.print_formats import PRINT_FORMATS

	for spec in PRINT_FORMATS:
		yield "Print Format", spec["name"], spec["module"]
	for spec in get_notifications():
		if spec.get("module"):
			yield "Notification", spec["name"], spec["module"]


def set_module(doctype, name, module):
	current = frappe.db.get_value(doctype, name, "module")
	if current is not None and current != module:
		frappe.db.set_value(doctype, name, "module", module, update_modified=False)


def rename_method_prefix(doctype, fieldname, old, new):
	for name, value in frappe.get_all(
		doctype, filters={fieldname: ["like", f"{old}%"]}, fields=["name", fieldname], as_list=True
	):
		frappe.db.set_value(doctype, name, fieldname, new + value[len(old) :], update_modified=False)


def tables_with_module_column():
	return frappe.db.sql_list(
		"""select distinct table_name from information_schema.columns
		where table_schema = database() and column_name = 'module' and table_name like 'tab%%'"""
	)


def sweep_remaining_references():
	"""Anything still pointing at an old module (records not shipped by the app) -> fallback."""
	for table in tables_with_module_column():
		for old, new in OLD_TO_FALLBACK.items():
			# table names come from information_schema, values are parameterised
			frappe.db.sql(f"update `{table}` set module = %s where module = %s", (new, old))


def count_references(module):
	total = 0
	for table in tables_with_module_column():
		if table == "tabModule Def":
			continue
		total += frappe.db.sql(f"select count(*) from `{table}` where module = %s", module)[0][0]
	return total


def delete_unused_old_module_defs():
	for old in OLD_TO_FALLBACK:
		if frappe.db.exists("Module Def", old) and not count_references(old):
			frappe.db.delete("Module Def", {"name": old})

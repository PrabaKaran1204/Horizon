# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Fallback installer for Horizon form scripts as ``Client Script`` documents.

The form scripts live in ``horizon_erp/public/js/<doctype>.js`` and are meant to be loaded through
``doctype_js`` in ``hooks.py`` (built by ``bench build --app horizon_erp``). On a site where the
hook is not wired yet, ``setup_client_scripts`` can install the same files as (non-standard)
``Client Script`` records so the behaviour is available immediately. It refuses to install a script
for a DocType that ``doctype_js`` already covers, so the two mechanisms never double-load.

Run manually:  bench --site <site> execute horizon_erp.horizon_setup.client_scripts.setup_client_scripts
Remove:        bench --site <site> execute horizon_erp.horizon_setup.client_scripts.remove_client_scripts
"""

import os

import frappe

CLIENT_SCRIPTS = {
	"Quotation": "quotation.js",
	"Sales Order": "sales_order.js",
	"Purchase Order": "purchase_order.js",
	"Delivery Note": "delivery_note.js",
	"Work Order": "work_order.js",
}


def _script_name(doctype):
	return f"Horizon {doctype}"


def _read(filename):
	path = os.path.join(frappe.get_app_path("horizon_erp"), "public", "js", filename)
	with open(path, encoding="utf-8") as f:
		return f.read()


def setup_client_scripts():
	"""Install / update Client Scripts for DocTypes not already covered by ``doctype_js``."""
	hooked = set(frappe.get_hooks("doctype_js") or {})
	done, skipped = [], []
	for doctype, filename in CLIENT_SCRIPTS.items():
		if doctype in hooked:
			skipped.append(doctype)
			continue
		name = _script_name(doctype)
		values = {"dt": doctype, "view": "Form", "enabled": 1, "script": _read(filename)}
		if frappe.db.exists("Client Script", name):
			doc = frappe.get_doc("Client Script", name)
			doc.update(values)
		else:
			doc = frappe.get_doc({"doctype": "Client Script", "name": name, "__newname": name, **values})
		doc.flags.ignore_permissions = True
		doc.save()
		done.append(doc.name)
	return {"installed": done, "skipped_hooked": skipped}


def remove_client_scripts():
	"""Delete the Client Scripts installed by ``setup_client_scripts`` (e.g. once ``doctype_js`` is live)."""
	removed = []
	for doctype in CLIENT_SCRIPTS:
		name = _script_name(doctype)
		if frappe.db.exists("Client Script", name):
			frappe.delete_doc("Client Script", name, ignore_permissions=True, force=True)
			removed.append(name)
	return removed

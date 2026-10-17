# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Horizon Print Formats.

Each format is a custom Jinja ``Print Format`` (``standard = "No"``, ``custom_format = 1``) whose
HTML lives in ``horizon_erp/<module>/print_format/<scrub>/<scrub>.html`` of the domain module set in
``PRINT_FORMATS`` (Sales Invoice -> horizon_selling, packing slip -> horizon_stock) - the same folder
layout Frappe uses for standard formats. ``frappe.www.printview.get_print_format`` resolves the file
from the Print Format's ``module``, so the template is read from disk at print time and the DB copy
is only a fallback. ``setup_print_formats``
is idempotent: run it after changing a template (``bench --site <site> execute
horizon_erp.horizon_setup.print_formats.setup_print_formats``). Formats are also exported as fixtures
(``hooks.py``: Print Format ``name like "Horizon%"``).

Jinja helpers used by the templates are registered in ``horizon_erp.utils.jinja_methods``.
"""

import os

import frappe

PRINT_FORMATS = [
	{
		"name": "Horizon Sales Invoice",
		"module": "Horizon Selling",
		"doc_type": "Sales Invoice",
		"font_size": 11,
		"margin_top": 10.0,
		"margin_bottom": 10.0,
		"margin_left": 10.0,
		"margin_right": 10.0,
	},
	{
		"name": "Horizon Packing Slip Thermal",
		"module": "Horizon Stock",
		"doc_type": "Delivery Note",
		"font_size": 10,
		"margin_top": 2.0,
		"margin_bottom": 2.0,
		"margin_left": 2.0,
		"margin_right": 2.0,
		# Print Format has no page-size field; the 80 mm roll size is set by @page in the template.
	},
]


def get_spec(name):
	return next(spec for spec in PRINT_FORMATS if spec["name"] == name)


def get_template_path(name):
	scrub = frappe.scrub(name)
	module_folder = frappe.scrub(get_spec(name)["module"])
	return os.path.join(
		frappe.get_app_path("horizon_erp"), module_folder, "print_format", scrub, f"{scrub}.html"
	)


def read_template(name):
	path = get_template_path(name)
	with open(path, encoding="utf-8") as f:
		return f.read()


def setup_print_formats():
	"""Create / update every Horizon Print Format. Returns the list of names processed."""
	done = []
	for spec in PRINT_FORMATS:
		values = {
			"doc_type": spec["doc_type"],
			"module": spec["module"],
			"standard": "No",
			"custom_format": 1,
			"print_format_type": "Jinja",
			"disabled": 0,
			"html": read_template(spec["name"]),
			"font_size": spec.get("font_size", 0),
			"margin_top": spec.get("margin_top", 15.0),
			"margin_bottom": spec.get("margin_bottom", 15.0),
			"margin_left": spec.get("margin_left", 15.0),
			"margin_right": spec.get("margin_right", 15.0),
			"align_labels_right": 0,
			"show_section_headings": 0,
			"line_breaks": 0,
		}
		if frappe.db.exists("Print Format", spec["name"]):
			doc = frappe.get_doc("Print Format", spec["name"])
			doc.update(values)
			doc.flags.ignore_permissions = True
			doc.save()
		else:
			doc = frappe.get_doc({"doctype": "Print Format", "name": spec["name"], **values})
			doc.flags.ignore_permissions = True
			doc.insert()
		done.append(doc.name)
	frappe.clear_cache(doctype="Print Format")
	return done

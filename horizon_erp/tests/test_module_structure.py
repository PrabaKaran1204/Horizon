# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Guards for the domain-module layout (mirrors the kaynes app).

Run:  bench --site horizon.local run-tests --app horizon_erp --module horizon_erp.tests.test_module_structure
"""

import glob
import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_setup.print_formats import PRINT_FORMATS, get_template_path
from horizon_erp.patches.v1_0 import restructure_modules
from horizon_erp.tests.cleanup import purge_test_residue

APP = "horizon_erp"
OLD_MODULES = tuple(restructure_modules.OLD_TO_FALLBACK)


def app_root():
	return frappe.get_app_path(APP)


def module_list():
	return frappe.get_module_list(APP)


class TestModuleStructure(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()

	def test_every_module_has_package_and_module_def(self):
		self.assertEqual(sorted(module_list()), sorted(restructure_modules.NEW_MODULES))
		for module in module_list():
			folder = os.path.join(app_root(), frappe.scrub(module))
			self.assertTrue(os.path.isfile(os.path.join(folder, "__init__.py")), folder)
			self.assertEqual(frappe.db.get_value("Module Def", module, "app_name"), APP, module)

	def test_old_modules_are_gone(self):
		for old in OLD_MODULES:
			self.assertFalse(frappe.db.exists("Module Def", old), old)
			self.assertEqual(restructure_modules.count_references(old), 0, old)
			self.assertFalse(os.path.exists(os.path.join(app_root(), frappe.scrub(old))), old)

	def test_shipped_json_module_matches_folder_and_db(self):
		records = list(restructure_modules.shipped_records())
		self.assertGreaterEqual(len(records), 65)
		for doctype, name, module in records:
			self.assertEqual(frappe.db.get_value(doctype, name, "module"), module, f"{doctype} {name}")
		for path in glob.glob(os.path.join(app_root(), "horizon_*", "*", "*", "*.json")):
			with open(path, encoding="utf-8") as f:
				data = json.load(f)
			if isinstance(data, dict) and data.get("module"):
				folder = os.path.relpath(path, app_root()).split(os.sep)[0]
				self.assertEqual(frappe.scrub(data["module"]), folder, path)

	def test_print_format_templates_resolve_from_module(self):
		for spec in PRINT_FORMATS:
			self.assertTrue(os.path.isfile(get_template_path(spec["name"])), spec["name"])
			self.assertEqual(frappe.db.get_value("Print Format", spec["name"], "module"), spec["module"])

	def test_hook_paths_resolve(self):
		paths = []
		for events in frappe.get_hooks("doc_events", app_name=APP).values():
			for handlers in events.values():
				paths.extend(handlers if isinstance(handlers, list) else [handlers])
		for key, jobs in frappe.get_hooks("scheduler_events", app_name=APP).items():
			if key == "cron":
				for cron_jobs in jobs.values():
					paths.extend(cron_jobs)
			else:
				paths.extend(jobs)
		paths.extend(frappe.get_hooks("after_install", app_name=APP))
		paths.extend(frappe.get_hooks("after_migrate", app_name=APP))
		for target in frappe.get_hooks("override_whitelisted_methods", app_name=APP).values():
			paths.extend(target)
		self.assertGreater(len(paths), 20)
		for path in paths:
			self.assertTrue(callable(frappe.get_attr(path)), path)

	def test_custom_number_card_methods_resolve(self):
		for name, method in frappe.get_all(
			"Number Card",
			filters={"name": ["like", "Horizon%"], "type": "Custom"},
			fields=["name", "method"],
			as_list=True,
		):
			frappe.is_whitelisted(frappe.get_attr(method))
			self.assertTrue(method.startswith("horizon_erp.horizon_setup.dashboards."), name)

	def test_patch_is_idempotent(self):
		restructure_modules.execute()
		for doctype, name, module in restructure_modules.shipped_records():
			self.assertEqual(frappe.db.get_value(doctype, name, "module"), module)

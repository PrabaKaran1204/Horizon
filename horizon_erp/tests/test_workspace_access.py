# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.desk import desktop
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_core.tests.fixtures import ensure_user
from horizon_erp.overrides.desktop import get_desktop_page, get_workspace_sidebar_items
from horizon_erp.tests.cleanup import purge_test_residue

# persona role -> the workspace that persona must be able to open
PERSONA_WORKSPACE = {
	"Operations Head": "Horizon Manufacturing",
	"Sales Manager": "Horizon Selling",
	"HR Manager": "Horizon HR & Payroll",
	"Warehouse Manager": "Horizon Inventory",
	"Finance Director": "Horizon ERP",
}


def page(name):
	return json.dumps({"name": name, "title": name, "public": 1})


class TestWorkspaceAccess(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)
		super().setUpClass()
		cls.users = {
			role: ensure_user(f"fixtest.ws.{i}@horizon.local", f"FIXTEST WS {i}", [role]).name
			for i, role in enumerate(PERSONA_WORKSPACE)
		}

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_every_horizon_workspace_lists_roles(self):
		for name in frappe.get_all("Workspace", filters={"name": ["like", "Horizon%"]}, pluck="name"):
			roles = {r.role for r in frappe.get_doc("Workspace", name).roles}
			self.assertIn("System Manager", roles, name)

	def test_desk_call_is_routed_to_override(self):
		hooks = frappe.get_hooks("override_whitelisted_methods")
		self.assertEqual(
			hooks["frappe.desk.desktop.get_desktop_page"][-1],
			"horizon_erp.overrides.desktop.get_desktop_page",
		)

	def test_persona_opens_own_workspace(self):
		for role, workspace in PERSONA_WORKSPACE.items():
			frappe.set_user(self.users[role])
			# the standard module gate is what refused these before the override
			self.assertRaises(frappe.PermissionError, desktop.get_desktop_page, page(workspace))
			self.assertIn("shortcuts", get_desktop_page(page(workspace)), f"{role} -> {workspace}")

	def test_sidebar_lists_role_granted_workspaces(self):
		# the desk router only opens routes present in boot.allowed_workspaces (built from this list)
		for role, workspace in PERSONA_WORKSPACE.items():
			frappe.set_user(self.users[role])
			names = [p["name"] for p in get_workspace_sidebar_items()["pages"]]
			self.assertIn(workspace, names, role)
			self.assertNotIn("Welcome Workspace", names, role)
		frappe.set_user(self.users["HR Manager"])
		self.assertNotIn("Horizon Manufacturing", [p["name"] for p in get_workspace_sidebar_items()["pages"]])

	def test_role_outside_workspace_is_refused(self):
		frappe.set_user(self.users["HR Manager"])
		self.assertRaises(frappe.PermissionError, get_desktop_page, page("Horizon Manufacturing"))
		frappe.set_user(self.users["Sales Manager"])
		self.assertRaises(frappe.PermissionError, get_desktop_page, page("Horizon HR & Payroll"))

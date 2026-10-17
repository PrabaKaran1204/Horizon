# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Desk loading of the Horizon workspaces (`override_whitelisted_methods` target).

Frappe opens a workspace only when its module is in the user's ``allow_modules``, i.e. the module owns a
DocType the user can read. Most Horizon modules ship reports, number cards and a workspace but no DocType,
so every user except Administrator got "Not permitted" on Horizon Selling, Inventory, Manufacturing, HR &
Payroll and the Horizon ERP home. A Horizon workspace that lists roles is opened for the users holding
one of them; links, cards and charts inside it keep their own permission checks.
"""

from json import loads

import frappe
from frappe import _
from frappe.desk import desktop
from frappe.exceptions import DoesNotExistError
from frappe.utils import has_common

# fields the standard get_workspace_sidebar_items returns per page
SIDEBAR_FIELDS = [
	"name",
	"title",
	"for_user",
	"parent_page",
	"content",
	"public",
	"module",
	"icon",
	"indicator_color",
	"is_hidden",
]


def get_role_granted_module(workspace):
	"""Module of a Horizon workspace whose roles include one of the session user's roles, else None."""
	if not workspace or not frappe.db.exists("Workspace", workspace):
		return None
	doc = frappe.get_cached_doc("Workspace", workspace)
	if not (doc.module or "").startswith("Horizon "):
		return None
	roles = [d.role for d in doc.roles]
	if roles and has_common(frappe.get_roles(), roles):
		return doc.module
	return None


class HorizonWorkspace(desktop.Workspace):
	def get_cached(self, cache_key, fallback_fn):
		value = super().get_cached(cache_key, fallback_fn)
		if cache_key == "user_allowed_modules":
			module = get_role_granted_module(self.page_name)
			if module and module not in value:
				value = [*value, module]
		return value


@frappe.whitelist()
def get_workspace_sidebar_items():
	"""``frappe.desk.desktop.get_workspace_sidebar_items`` plus the Horizon workspaces granted by role.

	The standard list builds every entry through the module gate, so without this the desk router does
	not know the route and answers "No permission for Page".
	"""
	result = desktop.get_workspace_sidebar_items()
	if result.get("has_access"):
		return result

	pages = [p for p in result["pages"] if p.get("name") != "Welcome Workspace"]
	shown = {p.get("name") for p in pages}
	added = []
	for page in frappe.get_all(
		"Workspace",
		fields=SIDEBAR_FIELDS,
		filters={"public": 1, "is_hidden": 0, "module": ["like", "Horizon %"]},
		ignore_permissions=True,
	):
		if page.name not in shown and get_role_granted_module(page.name):
			page["label"] = _(page.name)
			added.append(page)
	if not added:
		return result

	sequence = dict(frappe.get_all("Workspace", fields=["name", "sequence_id"], as_list=True))
	public = sorted([p for p in pages if p.get("public")] + added, key=lambda p: sequence.get(p["name"]) or 0)
	result["pages"] = public + [p for p in pages if not p.get("public")]
	return result


def extend_bootinfo(bootinfo):
	if "allowed_workspaces" in bootinfo and frappe.session.user != "Guest":
		bootinfo.allowed_workspaces = get_workspace_sidebar_items().get("pages")


@frappe.whitelist()
def get_desktop_page(page):
	"""Same contract as ``frappe.desk.desktop.get_desktop_page``, built with :class:`HorizonWorkspace`."""
	try:
		workspace = HorizonWorkspace(loads(page))
		workspace.build_workspace()
		return {
			"charts": workspace.charts,
			"shortcuts": workspace.shortcuts,
			"cards": workspace.cards,
			"onboardings": workspace.onboardings,
			"quick_lists": workspace.quick_lists,
			"number_cards": workspace.number_cards,
			"custom_blocks": workspace.custom_blocks,
		}
	except DoesNotExistError:
		frappe.log_error("Workspace Missing")
		return {}

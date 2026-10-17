# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Install / migrate hooks (see ``after_install`` and ``after_migrate`` in hooks.py).

Everything called here is idempotent and cheap (a handful of upserts on master records), so it is
safe to run on every ``bench migrate``. Demo data (``horizon_setup.demo_data`` / ``horizon_setup.demo_hr_finance``)
is deliberately *not* part of this routine: it is run explicitly with ``bench execute``.
"""

import frappe

from horizon_erp.horizon_setup.custom_fields import setup_custom_fields
from horizon_erp.horizon_setup.roles import setup_role_permissions, setup_roles


def after_install():
	"""Run once when the app is installed on a site. Failures abort the install.

	Frappe syncs ``<module>/custom/*.json`` only *after* ``after_install`` on install-app, so the
	custom fields are synced here first (workflows / notifications reference them)."""
	_run_setup(raise_on_error=True, sync_custom_fields=True)


def after_migrate():
	"""Run after every ``bench migrate`` to keep roles, workflows, print formats and notifications in
	sync. Custom fields are already synced by ``bench migrate`` itself (``sync_customizations`` runs
	before ``after_migrate``). Failures are logged (Error Log) but do not abort the migration."""
	_run_setup(raise_on_error=False, sync_custom_fields=False)


def _run_setup(raise_on_error, sync_custom_fields):
	# Roles and Custom Fields first: workflows and notifications reference both.
	_run("roles and custom fields", lambda: _setup_roles_and_fields(sync_custom_fields), raise_on_error)
	_run("workflows", _setup_workflows, raise_on_error)
	_run("print formats", _setup_print_formats, raise_on_error)
	_run("notifications", _setup_notifications, raise_on_error)


def _run(label, fn, raise_on_error):
	try:
		fn()
	except Exception:
		frappe.log_error(title=f"Horizon ERP setup failed: {label}", message=frappe.get_traceback())
		if raise_on_error:
			raise


def _setup_roles_and_fields(sync_custom_fields):
	setup_roles()
	if sync_custom_fields:
		setup_custom_fields()
	setup_role_permissions()


def _setup_workflows():
	from horizon_erp.horizon_workflow.workflows import setup_workflows

	setup_workflows()


def _setup_print_formats():
	from horizon_erp.horizon_setup.print_formats import setup_print_formats

	setup_print_formats()


def _setup_notifications():
	from horizon_erp.horizon_setup.notifications import setup_notifications

	setup_notifications()

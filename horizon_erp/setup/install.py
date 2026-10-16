# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Install / migrate hooks (see ``after_install`` and ``after_migrate`` in hooks.py)."""

import frappe

from horizon_erp.setup.custom_fields import setup_custom_fields
from horizon_erp.setup.roles import setup_roles


def after_install():
	"""Run once when the app is installed on a site. Failures abort the install."""
	_run_setup(raise_on_error=True)


def after_migrate():
	"""Run after every ``bench migrate`` to keep roles and custom fields in sync.
	Failures are logged (Error Log) but do not abort the migration."""
	_run_setup(raise_on_error=False)


def _run_setup(raise_on_error):
	try:
		setup_roles()
		setup_custom_fields()
	except Exception:
		frappe.log_error(title="Horizon ERP setup failed", message=frappe.get_traceback())
		if raise_on_error:
			raise

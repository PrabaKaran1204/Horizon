# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Custom Fields added to standard Frappe / ERPNext DocTypes.

Source of truth: Frappe "Export Customizations" files, one per DocType, in the custom/ folder of the
domain module that owns it (same convention as the kaynes app)::

    horizon_stock/custom/item.json                      Item
    horizon_buying/custom/{supplier,purchase_order}.json
    horizon_selling/custom/{quotation,quotation_item,sales_order,sales_order_item,delivery_note}.json
    horizon_quality_management/custom/quality_inspection.json
    horizon_manufacturing/custom/{work_order,bom}.json
    horizon_projects/custom/{project,task,timesheet_detail}.json
    horizon_accounts/custom/bank_account.json

Each file has ``sync_on_migrate: 1`` so ``bench migrate`` (``frappe.modules.utils.sync_customizations``)
creates / updates the fields, and every field carries the ``module`` of its folder. Each DocType gets
a "Horizon" Tab Break (tabbed forms) or Section Break (plain forms / child tables) appended after the
last standard field, so no standard field is pulled into our section. To change a field: edit it in
Customize Form on a developer-mode site and use "Export Customizations" into the same module (then
strip any field that is not ours), or edit the JSON and run ``bench migrate``.

Standard fields deliberately NOT duplicated:
- Company.default_selling_terms already exists -> no terms_and_conditions_text.
- Task.is_milestone already exists -> only billing_percent / milestone_invoice added.
- Sales Order Item.delivery_date already exists -> expected_delivery_date only on Quotation Item.
- Item.safety_stock / lead_time_days exist -> safety_stock_factor is a multiplier on top.
- Supplier.on_hold / hold_type (standard supplier block) exist -> is_blacklisted is a separate,
  override-able flag driven by Supplier Exception Log.
"""

import glob
import json
import os

import frappe
from frappe.modules.utils import sync_customizations

APP = "horizon_erp"


def get_customization_files():
	"""Paths of every ``<module>/custom/*.json`` shipped by this app, sorted."""
	return sorted(glob.glob(os.path.join(frappe.get_app_path(APP), "horizon_*", "custom", "*.json")))


def get_custom_fields():
	"""Return ``{doctype: [field_dict, ...]}`` read from the module custom/ JSON files."""
	out = {}
	for path in get_customization_files():
		with open(path, encoding="utf-8") as f:
			data = json.load(f)
		if data.get("custom_fields"):
			out.setdefault(data["doctype"], []).extend(data["custom_fields"])
	return out


def setup_custom_fields():
	"""Sync this app's custom/ JSON (Custom Fields, Property Setters) into the site. Idempotent.

	``bench migrate`` already does this for every app before ``after_migrate``; on ``install-app``
	Frappe only syncs customizations *after* ``after_install``, so install calls this first because
	the workflows, notifications and print formats set up there reference the custom fields.
	"""
	sync_customizations(APP)
	frappe.clear_cache()

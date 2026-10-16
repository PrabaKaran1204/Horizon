# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Inventory REST endpoints consumed by external systems.

Every call must be recorded in ``Inventory API Log`` (Horizon Integration).
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_inventory_snapshot(warehouse, filter_by_criticality=False):
	"""Return current stock per item for ``warehouse``.

	Intended behaviour:
	- Validate ``warehouse`` exists and the caller can read Bin / Warehouse.
	- Return ``[{item_code, item_name, criticality, actual_qty, reserved_qty, projected_qty}]``.
	- When ``filter_by_criticality`` is truthy, only return criticality "A" items.
	- Enforce a per-API-key rate limit and write an ``Inventory API Log`` row
	  (endpoint, client, parameters, response_time_ms, http_status, status, ip_address).
	"""
	frappe.has_permission("Bin", "read", throw=True)
	# TODO(integration): implement snapshot, rate limiting and API logging
	frappe.throw(_("Not implemented"), frappe.ValidationError)

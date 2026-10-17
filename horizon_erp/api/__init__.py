# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Backward-compatible alias package (pre-restructure public API paths).

The implementation moved to ``horizon_erp.horizon_integrations.inventory_api``. These re-exports
keep ``/api/method/horizon_erp.api.get_inventory_snapshot`` and
``/api/method/horizon_erp.api.inventory.get_inventory_snapshot`` working: Frappe resolves the dotted
path to the very same function object, which is already registered as whitelisted. Do not add new
code here.
"""

from horizon_erp.horizon_integrations.inventory_api import get_inventory_snapshot

__all__ = ["get_inventory_snapshot"]

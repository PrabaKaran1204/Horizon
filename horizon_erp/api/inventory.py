# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Backward-compatible alias for ``/api/method/horizon_erp.api.inventory.get_inventory_snapshot``.

The implementation lives in ``horizon_erp.horizon_integrations.inventory_api``; this module only
re-exports the whitelisted function (same object, so Frappe's whitelist check passes).
"""

from horizon_erp.horizon_integrations.inventory_api import ENDPOINT, get_inventory_snapshot

__all__ = ["ENDPOINT", "get_inventory_snapshot"]

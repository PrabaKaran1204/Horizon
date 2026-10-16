# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Horizon REST API package.

``get_inventory_snapshot`` is re-exported here so the shorter dotted path
``/api/method/horizon_erp.api.get_inventory_snapshot`` resolves to the same whitelisted function
as ``/api/method/horizon_erp.api.inventory.get_inventory_snapshot``.
"""

from horizon_erp.api.inventory import get_inventory_snapshot

__all__ = ["get_inventory_snapshot"]

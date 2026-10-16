# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Buying-side document event handlers (Purchase Order, Purchase Receipt).

Wired from ``hooks.py`` ``doc_events``. Every handler takes ``(doc, method=None)``.
"""

import frappe
from frappe import _


def validate_purchase_order(doc, method=None):
	"""Purchase Order ``validate`` hook.

	Intended behaviour:
	- Block POs against a Supplier with ``is_blacklisted`` = 1 unless ``blacklist_override`` is
	  ticked and ``override_reason`` is given; log the override in ``Supplier Exception Log``.
	- Derive ``approval_level_required`` (Level 1 / 2 / 3) from ``grand_total`` thresholds
	  and stamp ``pending_since`` when the document enters a pending workflow state.
	"""
	# TODO(buying): blacklist check + Supplier Exception Log + approval level derivation
	pass


def on_submit_purchase_receipt(doc, method=None):
	"""Purchase Receipt ``on_submit`` hook.

	Intended behaviour:
	- Update ``actual_ordered_qty`` / ``variance_qty`` on the matching Quarterly Purchase Plan Item.
	- Trigger inbound Quality Inspection requirements for criticality "A" items.
	"""
	# TODO(buying): quarterly plan variance update + QI trigger
	pass

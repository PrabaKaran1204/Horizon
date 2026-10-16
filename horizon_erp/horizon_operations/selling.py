# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Selling-side document event handlers (Quotation, Sales Order, Delivery Note, Sales Invoice).

Wired from ``hooks.py`` ``doc_events``. Every handler takes ``(doc, method=None)``.
"""

import frappe
from frappe import _


def validate_discounts(doc, method=None):
	"""Quotation / Sales Order ``validate`` hook (shared).

	Intended behaviour:
	- For each item row compute ``rule_rate`` (rate after Pricing Rules) and
	  ``discount_over_rule_pct`` = (rule_rate - rate) / rule_rate * 100.
	- Set parent ``needs_discount_approval`` when any row exceeds the allowed discount threshold
	  and require ``discount_reason``; the "Horizon Discount Approval" workflow routes it.
	- Populate ``available_qty`` and ``mfg_lead_days`` on each row for sales visibility.
	"""
	# TODO(selling): pricing rule comparison + discount approval flag + availability enrichment
	pass


def validate_delivery_note(doc, method=None):
	"""Delivery Note ``validate`` hook.

	Intended behaviour:
	- If the linked Sales Order has an open Shipment Decision, enforce its outcome
	  (partial qty / delay / concession) and link it in ``shipment_decision``.
	- Require ``deviation_notes`` when delivered qty differs from ordered qty.
	"""
	# TODO(selling): shipment decision enforcement
	pass


def on_submit_delivery_note(doc, method=None):
	"""Delivery Note ``on_submit`` hook.

	Intended behaviour:
	- Close the linked Shipment Decision (status "Closed") once goods leave the warehouse.
	- Require ``customer_signature`` / ``received_by`` for direct deliveries (POD).
	"""
	# TODO(selling): close shipment decision + POD enforcement
	pass


def validate_sales_invoice(doc, method=None):
	"""Sales Invoice ``validate`` hook.

	Intended behaviour:
	- For project milestone billing, check ``Task.billing_percent`` totals do not exceed 100 %
	  and stamp ``Task.milestone_invoice``.
	- Honour "Invoice Now Ship Later" Shipment Decisions (allow invoice without Delivery Note).
	"""
	# TODO(selling): milestone billing validation
	pass

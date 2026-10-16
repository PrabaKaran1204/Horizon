# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Hourly scheduler tasks (see ``scheduler_events`` in hooks.py)."""

import frappe


def reorder_and_accuracy_check():
	"""Hourly: compare Bin.actual_qty against reorder levels (criticality-weighted via
	``Item.safety_stock_factor``) and raise Material Requests / notify Warehouse Manager.
	Also sample stock accuracy against the latest Stock Reconciliation."""
	# TODO(stock): reorder + accuracy check
	pass


def po_approval_reminders():
	"""Hourly: find Purchase Orders stuck in a "Pending Level N" workflow state longer than the
	SLA (``pending_since``) and remind / escalate the approver."""
	# TODO(buying): PO approval SLA reminders
	pass

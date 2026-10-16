# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Daily scheduler tasks (see ``scheduler_events`` in hooks.py)."""

import frappe


def recompute_reorder_levels():
	"""Daily: recompute ``Item Reorder`` levels from consumption history, ``criticality``
	and ``demand_pattern`` (Seasonal Q4 uplift)."""
	# TODO(stock): reorder level recompute
	pass


def detect_quality_deadline_conflicts():
	"""Daily: find Sales Orders whose delivery_date is at risk because of open / failed
	Quality Inspections or low Production Audits, and open a Shipment Decision for each."""
	# TODO(quality): deadline conflict detection
	pass


def budget_threshold_alerts():
	"""Daily: compare Budget vs actuals per Cost Center / Account and notify Department Heads
	at 80 % / 100 %; surface pending Budget Override Requests to the Finance Director."""
	# TODO(finance): budget threshold alerts
	pass


def send_daily_summary():
	"""18:00 daily (cron): email the Operations Head a summary of today's production audits,
	quality failures, pending approvals and stock-outs."""
	# TODO(operations): daily summary email
	pass

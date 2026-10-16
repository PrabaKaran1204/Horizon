# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Monthly scheduler tasks (see ``scheduler_events`` in hooks.py)."""

import frappe


def send_budget_report():
	"""1st of month 09:00 (cron): email the Finance Director the budget vs actual report
	per Cost Center with override requests for the previous month."""
	# TODO(finance): monthly budget report
	pass

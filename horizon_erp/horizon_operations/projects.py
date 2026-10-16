# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Projects document event handlers (Timesheet, Task)."""

import frappe
from frappe import _


def validate_timesheet(doc, method=None):
	"""Timesheet ``validate`` hook.

	Intended behaviour:
	- Flag ``Timesheet Detail.is_overtime`` for hours beyond the employee's shift / 8 h per day.
	- Recompute Project ``overhead_amount`` = total costing * ``overhead_percent``.
	"""
	# TODO(projects): overtime flagging + project overhead recompute
	pass


def on_update_task(doc, method=None):
	"""Task ``on_update`` hook.

	Intended behaviour:
	- When a milestone Task (``is_milestone``) is set to Completed and has ``billing_percent``,
	  create / link a draft Sales Invoice in ``milestone_invoice`` (enqueue, do not block save).
	"""
	# TODO(projects): milestone invoice creation
	pass

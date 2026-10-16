# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Manufacturing document event handlers (Work Order)."""

import frappe
from frappe import _


def validate_work_order(doc, method=None):
	"""Work Order ``validate`` hook.

	Intended behaviour:
	- Compute ``required_machine_hours`` = qty * Item.machine_hours_per_unit.
	- Compare against Workstation / line capacity for the planned window
	  (Item.default_line: Line A / Line B / Any); block when exceeded unless
	  ``capacity_override`` is ticked with ``capacity_override_reason``.
	"""
	# TODO(manufacturing): machine-hour capacity check
	pass

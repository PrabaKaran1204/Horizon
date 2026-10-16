# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Stock Entry hooks that enforce Production Audit outcomes."""

import frappe
from frappe import _


def validate_stock_entry(doc, method=None):
	"""Stock Entry ``validate`` hook.

	Intended behaviour:
	- For ``purpose`` = "Manufacture" against a Work Order, block the finished-goods entry when
	  the latest submitted Production Audit for that Work Order has ``audit_score`` < 70 and
	  the linked ``corrective_action`` (Quality Action) is not yet closed.
	"""
	# TODO(quality): production audit gate on manufacture entries
	pass

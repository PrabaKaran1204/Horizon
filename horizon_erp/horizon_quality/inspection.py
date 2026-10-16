# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Quality Inspection document event handlers."""

import frappe
from frappe import _


def on_submit_quality_inspection(doc, method=None):
	"""Quality Inspection ``on_submit`` hook.

	Intended behaviour:
	- Map ``qc_result`` to the standard ``status`` (Pass -> Accepted, Fail -> Rejected ...).
	- On "Rework": create a rework Work Order (``Work Order.rework_of`` = source WO) and link it in
	  ``rework_work_order``.
	- On "Fail" with ``evidence_required``: ensure at least one attachment exists.
	- Create a Shipment Decision when the inspection blocks an outbound Sales Order.
	"""
	# TODO(quality): qc_result mapping + rework WO + shipment decision creation
	pass

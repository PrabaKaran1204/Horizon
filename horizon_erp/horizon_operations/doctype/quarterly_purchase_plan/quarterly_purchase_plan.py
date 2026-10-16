# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class QuarterlyPurchasePlan(Document):
	def validate(self):
		"""Intended behaviour (not yet implemented):
		- One plan per Fiscal Year + Quarter.
		- Default ``lead_time_days`` from Item and derive ``planned_order_date`` from the quarter
		  start minus lead time; ``variance_qty`` = planned_qty - actual_ordered_qty.
		"""
		# TODO(buying): plan validation and derived values
		pass

	def on_submit(self):
		"""Intended behaviour: optionally create Material Requests for planned items."""
		# TODO(buying): material request generation
		pass

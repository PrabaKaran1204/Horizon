# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class BudgetOverrideRequest(Document):
	def validate(self):
		"""Intended behaviour (not yet implemented):
		- ``requested_amount`` must be > 0.
		- Only one open request per Cost Center / Account / Fiscal Year.
		- ``requested_by`` defaults to the session user.
		"""
		# TODO(finance): request validation
		pass

	def on_submit(self):
		"""Intended behaviour: when ``status`` is "Approved", raise the matching Budget row
		(or create a Budget) by ``requested_amount`` and stamp ``approved_by``."""
		# TODO(finance): apply approved override to Budget
		pass

	def on_cancel(self):
		"""Intended behaviour: reverse the Budget adjustment made on submit."""
		# TODO(finance): reverse budget adjustment
		pass

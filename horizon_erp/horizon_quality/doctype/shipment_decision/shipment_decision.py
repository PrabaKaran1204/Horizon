# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ShipmentDecision(Document):
	def validate(self):
		"""Intended behaviour (not yet implemented):
		- ``partial_qty`` must be > 0 and <= pending qty on the Sales Order for "Ship Partial".
		- ``new_delivery_date`` must be after the SO ``delivery_date`` for "Delay Delivery".
		- Set ``status`` = "Decided" once ``decision`` and all three approvers are filled.
		"""
		# TODO(quality): decision-specific validation
		pass

	def on_submit(self):
		"""Intended behaviour: push the decision to the Sales Order (update delivery_date,
		reserve partial qty, or allow invoice-before-delivery) and notify Sales / Finance."""
		# TODO(quality): apply decision to Sales Order
		pass

	def on_cancel(self):
		"""Intended behaviour: reverse everything ``on_submit`` did and reopen the decision."""
		# TODO(quality): reverse on_submit effects
		pass

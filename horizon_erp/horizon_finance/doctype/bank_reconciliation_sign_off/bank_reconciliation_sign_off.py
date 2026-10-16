# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class BankReconciliationSignoff(Document):
	def validate(self):
		self.validate_period()
		self.compute_difference()

	def validate_period(self):
		if self.period_start and self.period_end and getdate(self.period_end) < getdate(self.period_start):
			frappe.throw(_("Period End cannot be before Period Start"), title=_("Invalid Period"))

	def compute_difference(self):
		precision = self.precision("difference")
		self.difference = flt(flt(self.bank_balance) - flt(self.gl_balance), precision)

	def on_submit(self):
		"""Intended behaviour (not yet implemented): block sign-off when ``difference`` is
		non-zero without ``remarks``; notify the Finance Director; mark the period reconciled."""
		# TODO(finance): sign-off enforcement
		pass

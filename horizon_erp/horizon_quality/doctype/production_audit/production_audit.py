# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

CLOSED_WORK_ORDER_STATUSES = ("Completed", "Cancelled", "Stopped")
LOW_SCORE_THRESHOLD = 70


class ProductionAudit(Document):
	def validate(self):
		self.validate_audit_score()
		self.validate_work_order_status()

	def on_submit(self):
		self.escalate_if_low()

	def validate_audit_score(self):
		score = cint(self.audit_score)
		if score < 0 or score > 100:
			frappe.throw(_("Audit Score must be between 0 and 100"), title=_("Invalid Score"))

	def validate_work_order_status(self):
		status = frappe.db.get_value("Work Order", self.work_order, "status")
		if status in CLOSED_WORK_ORDER_STATUSES:
			frappe.throw(
				_(
					"Work Order {0} is {1}; a Production Audit can only be recorded against an open Work Order"
				).format(frappe.bold(self.work_order), frappe.bold(_(status))),
				title=_("Work Order Closed"),
			)

	def escalate_if_low(self):
		"""Escalate audits scoring below ``LOW_SCORE_THRESHOLD``.

		Intended behaviour (not yet implemented):
		- Notify the Operations Head (Notification "Horizon Low Production Audit").
		- Create a Quality Action, link it in ``corrective_action`` and set ``escalated`` = 1
		  via ``db_set`` (fields are allow_on_submit).
		- Photos become mandatory when the score is below the threshold (also enforced client-side).
		"""
		# TODO(quality): notify Operations Head + create Quality Action when audit_score < 70
		pass

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_link_to_form

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.jobs import safe_sendmail

CLOSED_WORK_ORDER_STATUSES = ("Completed", "Cancelled", "Stopped")
LOW_SCORE_THRESHOLD = config.AUDIT_FAIL_SCORE


class ProductionAudit(Document):
	def validate(self):
		self.validate_audit_score()
		self.validate_work_order_status()
		self.validate_photos_for_low_score()

	def before_submit(self):
		# submitting straight from the form (without the workflow button) still lands on Submitted
		if not self.status or self.status == "Draft":
			self.status = "Submitted"

	def on_submit(self):
		self.escalate_if_low()

	def on_cancel(self):
		# the Quality Action (if any) stays open for traceability; the audit itself no longer gates
		self.db_set("status", "Draft", update_modified=False)

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

	def validate_photos_for_low_score(self):
		if cint(self.audit_score) < LOW_SCORE_THRESHOLD and not self.get("photos"):
			frappe.throw(
				_("Audit Score {0} is below {1}: attach at least one photo documenting the findings").format(
					frappe.bold(self.audit_score), LOW_SCORE_THRESHOLD
				),
				title=_("Photo Evidence Required"),
			)

	def escalate_if_low(self):
		"""Below the fail score: flag ``escalated``, open a Quality Action (linked in
		``corrective_action``) and alert every Operations Head in-app and by e-mail."""
		if cint(self.audit_score) >= LOW_SCORE_THRESHOLD:
			return

		from horizon_erp.horizon_quality_management.inspection import create_quality_action

		recipients = config.get_users_with_role(config.ROLE_OPERATIONS_HEAD)
		subject = _("Production Audit {0} scored {1} on WO {2}").format(
			self.name, self.audit_score, self.work_order
		)

		if not self.corrective_action:
			qa = create_quality_action(
				description=subject,
				problem=_("{0}\n\nFindings:\n{1}").format(subject, self.findings or ""),
				responsible=recipients[0] if recipients else None,
			)
			qa.add_comment(
				"Comment",
				_("Raised from Production Audit {0}").format(get_link_to_form("Production Audit", self.name)),
			)
			self.db_set("corrective_action", qa.name, update_modified=False)

		self.db_set("escalated", 1, update_modified=False)

		message = _(
			"Production Audit {0} on Work Order {1} ({2}) scored <b>{3}</b>, below the threshold of {4}."
			"<br>Corrective action: {5}<br><br>Findings:<br>{6}"
		).format(
			get_link_to_form("Production Audit", self.name),
			get_link_to_form("Work Order", self.work_order),
			self.item_code or "",
			self.audit_score,
			LOW_SCORE_THRESHOLD,
			get_link_to_form("Quality Action", self.corrective_action) if self.corrective_action else "-",
			self.findings or "-",
		)
		for user in recipients:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": user,
					"from_user": frappe.session.user,
					"type": "Alert",
					"subject": subject,
					"email_content": message,
					"document_type": self.doctype,
					"document_name": self.name,
				}
			).insert(ignore_permissions=True)

		if recipients:
			safe_sendmail(
				"Production Audit escalation email failed",
				recipients=recipients,
				subject=subject,
				message=message,
				reference_doctype=self.doctype,
				reference_name=self.name,
			)

		frappe.msgprint(
			_("Audit escalated to Operations Head; Quality Action {0} opened").format(
				get_link_to_form("Quality Action", self.corrective_action)
			),
			indicator="red",
			alert=True,
		)


@frappe.whitelist()
def get_work_order_context(work_order):
	"""Work Order summary for the audit form (auditors may lack Work Order read permission)."""
	frappe.has_permission("Production Audit", "read", throw=True)
	wo = frappe.db.get_value(
		"Work Order",
		work_order,
		[
			"production_item",
			"item_name",
			"qty",
			"produced_qty",
			"status",
			"planned_start_date",
			"planned_end_date",
			"required_machine_hours",
		],
		as_dict=True,
	)
	if not wo:
		return {}
	wo.workstation = frappe.db.get_value(
		"Work Order Operation", {"parent": work_order}, "workstation", order_by="idx asc"
	)
	return wo

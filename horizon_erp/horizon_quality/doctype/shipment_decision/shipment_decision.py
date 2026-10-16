# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form, getdate, strip_html


class ShipmentDecision(Document):
	def validate(self):
		self.validate_decision_fields()
		if self.docstatus == 0 and not self.status:
			self.status = "Open"

	def validate_decision_fields(self):
		if self.decision == "Ship Partial":
			pending = get_so_pending_qty(self.sales_order)
			if flt(self.partial_qty) <= 0:
				frappe.throw(
					_("Partial Qty must be greater than zero for 'Ship Partial'"), title=_("Partial Qty")
				)
			if pending and flt(self.partial_qty) > pending:
				frappe.throw(
					_("Partial Qty {0} exceeds the {1} units still pending on Sales Order {2}").format(
						flt(self.partial_qty), pending, self.sales_order
					),
					title=_("Partial Qty"),
				)
		elif self.decision == "Delay Delivery":
			if not self.new_delivery_date:
				frappe.throw(
					_("New Delivery Date is required for 'Delay Delivery'"), title=_("Delivery Date")
				)
			if self.delivery_date and getdate(self.new_delivery_date) <= getdate(self.delivery_date):
				frappe.throw(
					_("New Delivery Date must be after the current Sales Order delivery date {0}").format(
						frappe.format(self.delivery_date, {"fieldtype": "Date"})
					),
					title=_("Delivery Date"),
				)
		elif self.decision == "Invoice Now Ship Later":
			if not self.finance_approver:
				frappe.throw(
					_("A Finance Approver must sign off on 'Invoice Now Ship Later'"),
					title=_("Approver Required"),
				)
		elif self.decision == "Ship With Concession":
			if not self.quality_approver:
				frappe.throw(
					_("A Quality Approver must sign off on 'Ship With Concession'"),
					title=_("Approver Required"),
				)

	def on_submit(self):
		self.db_set("status", "Decided", update_modified=False)
		self.status = "Decided"
		self.apply_to_sales_order()

	def on_cancel(self):
		"""Reopen the decision. The Sales Order delivery dates changed by 'Delay Delivery' are
		not reverted automatically (the original dates are only recorded in the comment)."""
		self.db_set("status", "Open", update_modified=False)
		frappe.get_doc("Sales Order", self.sales_order).add_comment(
			"Comment",
			_("Shipment Decision {0} ({1}) was cancelled").format(
				get_link_to_form("Shipment Decision", self.name), self.decision
			),
		)

	def apply_to_sales_order(self):
		so = frappe.get_doc("Sales Order", self.sales_order)
		detail = ""
		if self.decision == "Ship Partial":
			detail = _("ship {0} units now").format(flt(self.partial_qty))
		elif self.decision == "Delay Delivery":
			detail = _("delivery date moved from {0} to {1}").format(
				frappe.format(so.delivery_date, {"fieldtype": "Date"}),
				frappe.format(self.new_delivery_date, {"fieldtype": "Date"}),
			)
			self.push_delivery_date(so)
		elif self.decision == "Invoice Now Ship Later":
			detail = _("invoice now, ship later (finance approver {0})").format(self.finance_approver)
		elif self.decision == "Ship With Concession":
			detail = _("ship with concession (quality approver {0})").format(self.quality_approver)

		so.add_comment(
			"Comment",
			_("Shipment Decision {0}: <b>{1}</b> - {2}. Reason: {3}").format(
				get_link_to_form("Shipment Decision", self.name), self.decision, detail, self.reason
			),
		)

	def push_delivery_date(self, so):
		"""Deliberately bypasses Sales Order re-validation: the order is submitted and
		``delivery_date`` is not allow-on-submit, so ``db_set``/``set_value`` is the only path
		that does not require amending the order."""
		for row in so.items:
			frappe.db.set_value(
				"Sales Order Item", row.name, "delivery_date", self.new_delivery_date, update_modified=False
			)
		frappe.db.set_value("Sales Order", so.name, "delivery_date", self.new_delivery_date)


def get_so_pending_qty(sales_order):
	rows = frappe.get_all(
		"Sales Order Item", filters={"parent": sales_order}, fields=["qty", "delivered_qty"]
	)
	return flt(sum(flt(r.qty) - flt(r.delivered_qty) for r in rows))


@frappe.whitelist()
def make_shipment_decision(sales_order):
	"""Return an unsaved Shipment Decision pre-filled from the Sales Order and its open quality
	blockers (used by a 'Create Shipment Decision' button on the Delivery Note)."""
	frappe.has_permission("Sales Order", "read", doc=sales_order, throw=True)
	frappe.has_permission("Shipment Decision", "create", throw=True)

	from horizon_erp.horizon_operations.selling import get_quality_blockers

	so = frappe.db.get_value("Sales Order", sales_order, ["customer", "delivery_date"], as_dict=True)
	if not so:
		frappe.throw(_("Sales Order {0} not found").format(sales_order))

	blockers = get_quality_blockers({sales_order})
	work_order = frappe.db.get_value("Work Order", {"sales_order": sales_order, "docstatus": 1}, "name")

	doc = frappe.new_doc("Shipment Decision")
	doc.sales_order = sales_order
	doc.customer = so.customer
	doc.delivery_date = so.delivery_date
	doc.work_order = work_order
	doc.quality_issue = "\n".join(strip_html(b) for b in blockers) if blockers else None
	return doc.as_dict()

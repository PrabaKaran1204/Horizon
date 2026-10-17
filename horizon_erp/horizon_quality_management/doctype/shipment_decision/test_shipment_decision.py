# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from horizon_erp.horizon_core.tests.fixtures import (
	ensure_bom,
	ensure_employee,
	make_sales_order,
	make_stock,
	make_work_order,
	setup_common,
)
from horizon_erp.horizon_quality_management.doctype.shipment_decision.shipment_decision import (
	make_shipment_decision,
)
from horizon_erp.tests.cleanup import purge_test_residue


class TestShipmentDecision(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		cls.bom = ensure_bom("BRTEST-FG", "BRTEST-RM", operation_minutes=30)
		cls.employee = ensure_employee()
		make_stock("BRTEST-FG", cls.wh.fg, 20, rate=500)
		cls.so = make_sales_order("BRTEST Customer", "BRTEST-FG", 5, 1000, cls.wh.fg).insert()
		cls.so.submit()
		cls.wo = make_work_order(
			"BRTEST-FG", cls.bom.name, 5, cls.wh.fg, cls.wh.wip, cls.wh.stores, sales_order=cls.so.name
		)
		cls.wo.insert()
		cls.wo.submit()
		cls.audit = frappe.get_doc(
			{
				"doctype": "Production Audit",
				"work_order": cls.wo.name,
				"inspector": cls.employee,
				"audit_score": 50,
				"photos": [{"photo": "/files/brtest-audit.png"}],
			}
		).insert()
		cls.audit.submit()

	def test_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Shipment Decision"))

	def test_decision_validations(self):
		sd = frappe.get_doc(
			{
				"doctype": "Shipment Decision",
				"sales_order": self.so.name,
				"decision": "Ship Partial",
				"reason": "x",
				"partial_qty": 0,
			}
		)
		self.assertRaises(frappe.ValidationError, sd.insert)
		sd.partial_qty = 50  # more than pending
		self.assertRaises(frappe.ValidationError, sd.insert)

		sd = frappe.get_doc(
			{
				"doctype": "Shipment Decision",
				"sales_order": self.so.name,
				"decision": "Delay Delivery",
				"reason": "QC rework",
				"new_delivery_date": nowdate(),
			}
		)
		self.assertRaises(frappe.ValidationError, sd.insert)

		sd = frappe.get_doc(
			{
				"doctype": "Shipment Decision",
				"sales_order": self.so.name,
				"decision": "Invoice Now Ship Later",
				"reason": "x",
			}
		)
		self.assertRaises(frappe.ValidationError, sd.insert)

	def test_make_shipment_decision_prefills(self):
		data = make_shipment_decision(self.so.name)
		self.assertEqual(data["sales_order"], self.so.name)
		self.assertEqual(data["customer"], "BRTEST Customer")
		self.assertEqual(data["work_order"], self.wo.name)
		self.assertIn(self.audit.name, data["quality_issue"])

	def test_delivery_gate_and_delay_decision(self):
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		dn = make_delivery_note(self.so.name)
		with self.assertRaises(frappe.ValidationError) as ctx:
			dn.insert()
		self.assertIn("Shipment Decision", str(ctx.exception))

		new_date = add_days(self.so.delivery_date, 5)
		sd = frappe.get_doc(
			{
				"doctype": "Shipment Decision",
				"sales_order": self.so.name,
				"decision": "Delay Delivery",
				"reason": "Rework of failed audit batch",
				"new_delivery_date": new_date,
			}
		).insert()
		sd.submit()
		self.assertEqual(sd.status, "Decided")
		self.assertEqual(
			str(frappe.db.get_value("Sales Order", self.so.name, "delivery_date")), str(new_date)
		)
		self.assertEqual(
			str(frappe.db.get_value("Sales Order Item", {"parent": self.so.name}, "delivery_date")),
			str(new_date),
		)
		comments = frappe.get_all(
			"Comment",
			filters={
				"reference_doctype": "Sales Order",
				"reference_name": self.so.name,
				"comment_type": "Comment",
			},
			pluck="content",
		)
		self.assertTrue(any(sd.name in c for c in comments))

		dn = make_delivery_note(self.so.name)
		dn.insert()
		self.assertEqual(dn.shipment_decision, sd.name)

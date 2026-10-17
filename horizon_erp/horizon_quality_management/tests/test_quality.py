# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_core.tests.fixtures import (
	ensure_bom,
	ensure_employee,
	make_stock,
	make_work_order,
	setup_common,
)
from horizon_erp.horizon_quality_management.production_audit_hooks import validate_stock_entry
from horizon_erp.tests.cleanup import purge_test_residue


class TestQuality(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		cls.bom = ensure_bom("BRTEST-FG", "BRTEST-RM", operation_minutes=30)
		cls.employee = ensure_employee()
		make_stock("BRTEST-RM", cls.wh.stores, 100)
		cls.wo = make_work_order("BRTEST-FG", cls.bom.name, 2, cls.wh.fg, cls.wh.wip, cls.wh.stores)
		cls.wo.insert()
		cls.wo.submit()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _audit(self, score, photos=True):
		doc = frappe.get_doc(
			{
				"doctype": "Production Audit",
				"work_order": self.wo.name,
				"inspector": self.employee,
				"audit_score": score,
				"findings": "<p>Torque out of spec on station 3</p>",
				"photos": [{"photo": "/files/brtest-audit.png", "caption": "Station 3"}] if photos else [],
			}
		)
		return doc

	def test_low_score_requires_photo(self):
		self.assertRaises(frappe.ValidationError, self._audit(65, photos=False).insert)

	def test_low_score_escalates_and_gates_manufacture(self):
		audit = self._audit(65).insert()
		audit.submit()
		audit.reload()
		self.assertEqual(audit.escalated, 1)
		self.assertEqual(audit.status, "Submitted")
		self.assertTrue(audit.corrective_action)
		self.assertTrue(frappe.db.exists("Quality Action", audit.corrective_action))
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{
					"document_type": "Production Audit",
					"document_name": audit.name,
					"for_user": "brtest-ops@horizon.local",
				},
			)
		)

		stock_entry = frappe._dict(purpose="Manufacture", work_order=self.wo.name)
		with self.assertRaises(frappe.ValidationError) as ctx:
			validate_stock_entry(stock_entry)
		self.assertIn(audit.name, str(ctx.exception))

		audit.db_set("status", "Action Closed")
		validate_stock_entry(stock_entry)  # no exception

	def test_high_score_not_escalated(self):
		audit = self._audit(90, photos=False).insert()
		audit.submit()
		audit.reload()
		self.assertEqual(audit.escalated, 0)
		self.assertFalse(audit.corrective_action)

	def test_rework_quality_inspection_creates_rework_wo(self):
		job_card = frappe.db.get_value("Job Card", {"work_order": self.wo.name}, "name")
		self.assertTrue(job_card, "Work Order with operations should have created a Job Card")

		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "In Process",
				"reference_type": "Job Card",
				"reference_name": job_card,
				"item_code": "BRTEST-FG",
				"sample_size": 1,
				"inspected_by": "Administrator",
				"status": "Rejected",
				"qc_result": "Rework",
				"rejection_reason": "Surface finish below spec",
			}
		).insert()
		qi.submit()
		qi.reload()
		self.assertTrue(qi.rework_work_order)
		rework = frappe.get_doc("Work Order", qi.rework_work_order)
		self.assertEqual(rework.rework_of, self.wo.name)
		self.assertEqual(rework.docstatus, 0)
		self.assertEqual(rework.qty, 1)

	def test_fail_quality_inspection_creates_non_conformance(self):
		job_card = frappe.db.get_value("Job Card", {"work_order": self.wo.name}, "name")
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "In Process",
				"reference_type": "Job Card",
				"reference_name": job_card,
				"item_code": "BRTEST-FG",
				"sample_size": 1,
				"inspected_by": "Administrator",
				"status": "Rejected",
				"qc_result": "Fail",
				"rejection_reason": "Cracked housing",
			}
		).insert()
		qi.submit()
		self.assertTrue(frappe.db.exists("Non Conformance", {"subject": ["like", f"%{self.wo.name}%"]}))

	def test_evidence_required_blocks_submit_without_attachment(self):
		job_card = frappe.db.get_value("Job Card", {"work_order": self.wo.name}, "name")
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "In Process",
				"reference_type": "Job Card",
				"reference_name": job_card,
				"item_code": "BRTEST-FG",
				"sample_size": 1,
				"inspected_by": "Administrator",
				"status": "Accepted",
				"qc_result": "Pass",
				"evidence_required": 1,
			}
		).insert()
		self.assertRaises(frappe.ValidationError, qi.submit)

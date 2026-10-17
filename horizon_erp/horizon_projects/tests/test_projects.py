# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_core.tests.fixtures import COMPANY, ensure_customer, setup_common
from horizon_erp.horizon_projects.projects import MILESTONE_ITEM_CODE
from horizon_erp.tests.cleanup import purge_test_residue


class TestProjects(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		setup_common()
		if not frappe.db.exists("Activity Type", "BRTEST Activity"):
			frappe.get_doc({"doctype": "Activity Type", "activity_type": "BRTEST Activity"}).insert()

	def _project(self, **extra):
		return frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": frappe.generate_hash("BRTEST Project", 6),
				"company": COMPANY,
				"customer": ensure_customer().name,
				"estimated_costing": 100000,
				"overhead_percent": 15,
				**extra,
			}
		).insert()

	def test_overtime_flagging_and_overhead(self):
		project = self._project()
		ts = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"company": COMPANY,
				"parent_project": project.name,
				"time_logs": [
					{
						"activity_type": "BRTEST Activity",
						"from_time": "2026-10-01 09:00:00",
						"hours": 5,
						"project": project.name,
						"costing_rate": 500,
					},
					{
						"activity_type": "BRTEST Activity",
						"from_time": "2026-10-01 14:30:00",
						"hours": 4,
						"project": project.name,
						"costing_rate": 500,
					},
					{
						"activity_type": "BRTEST Activity",
						"from_time": "2026-10-02 09:00:00",
						"hours": 4,
						"project": project.name,
						"costing_rate": 500,
					},
				],
			}
		).insert()
		self.assertEqual([r.is_overtime for r in ts.time_logs], [1, 1, 0])

		ts.submit()
		overhead = frappe.db.get_value("Project", project.name, "overhead_amount")
		self.assertAlmostEqual(overhead, 13 * 500 * 0.15, places=2)

	def test_milestone_invoice(self):
		project = self._project()
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BRTEST Design sign-off",
				"project": project.name,
				"is_milestone": 1,
				"billing_percent": 30,
				"status": "Open",
			}
		).insert()
		self.assertFalse(task.milestone_invoice)

		task.status = "Completed"
		task.save()
		task.reload()
		self.assertTrue(task.milestone_invoice)

		si = frappe.get_doc("Sales Invoice", task.milestone_invoice)
		self.assertEqual(si.docstatus, 0)
		self.assertEqual(si.project, project.name)
		self.assertEqual(si.items[0].item_code, MILESTONE_ITEM_CODE)
		self.assertAlmostEqual(si.items[0].rate, 100000 * 1.15 * 0.30, places=2)

		# saving again must not create a second invoice
		task.save()
		self.assertEqual(frappe.db.count("Sales Invoice", {"project": project.name, "docstatus": 0}), 1)

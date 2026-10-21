# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Work Order form: Create > Production Audit (pre-filled) and the audit status headline."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.tests.fixtures import (
	ensure_employee,
	ensure_item,
	ensure_user,
	ensure_workstations,
	make_stock,
	make_work_order,
	setup_common,
)
from horizon_erp.horizon_quality_management.production_audit_hooks import (
	get_audit_status,
	make_production_audit,
)
from horizon_erp.horizon_quality_management.tests.test_operation_inspection import (
	ensure_operation,
	make_bom,
)
from horizon_erp.tests.cleanup import purge_test_residue

PREFIX = "WOAUDIT-"
OPERATION = "WOAUDIT Assembly"
INSPECTOR_USER = "woaudit-qi@horizon.local"  # Quality Inspector with Work Order read


class TestWorkOrderAuditButton(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		ensure_workstations()
		ensure_operation(OPERATION)  # no template: Job Cards complete without an inspection
		ensure_item(f"{PREFIX}RM", item_group="Raw Material", default_warehouse=cls.wh.stores)
		ensure_item(f"{PREFIX}FG", item_group="Products", default_warehouse=cls.wh.fg)
		ensure_item(f"{PREFIX}FG-NOOP", item_group="Products", default_warehouse=cls.wh.fg)
		cls.bom = make_bom(f"{PREFIX}FG", f"{PREFIX}RM", (OPERATION,))
		cls.bom_noop = make_bom(f"{PREFIX}FG-NOOP", f"{PREFIX}RM")
		cls.employee = ensure_employee()
		ensure_user(INSPECTOR_USER, f"{PREFIX}Inspector", ["Quality Inspector", "Manufacturing User"])
		cls.inspector_employee = ensure_employee(f"{PREFIX}Inspector")
		frappe.db.set_value("Employee", cls.inspector_employee, "user_id", INSPECTOR_USER)
		make_stock(f"{PREFIX}RM", cls.wh.stores, 50)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _work_order(self, item_code=None, bom=None, submit=True):
		wo = make_work_order(
			item_code or f"{PREFIX}FG",
			(bom or self.bom).name,
			1,
			self.wh.fg,
			self.wh.wip,
			self.wh.stores,
			skip_transfer=1,
		)
		wo.insert()
		if submit:
			wo.submit()
		return wo

	def _audit(self, wo, score, status=None):
		audit = frappe.get_doc(
			{
				"doctype": "Production Audit",
				"work_order": wo.name,
				"inspector": self.employee,
				"audit_score": score,
				"findings": f"<p>{PREFIX} finding</p>",
				"photos": [{"photo": "/files/woaudit.png", "caption": "Evidence"}] if score < 70 else [],
			}
		).insert()
		audit.submit()
		if status:
			audit.db_set("status", status)
		return audit

	# -- Create > Production Audit ----------------------------------------------------------

	def test_make_production_audit_prefilled_from_work_order(self):
		wo = self._work_order()
		frappe.set_user(INSPECTOR_USER)
		audit = make_production_audit(wo.name)
		self.assertTrue(audit.get("__islocal"))
		self.assertEqual(audit.doctype, "Production Audit")
		self.assertEqual(audit.work_order, wo.name)
		self.assertEqual(audit.item_code, f"{PREFIX}FG")
		self.assertEqual(audit.workstation, "Line A")  # first operation's workstation
		self.assertEqual(str(audit.audit_date), nowdate())
		self.assertEqual(audit.inspector, self.inspector_employee)

		audit.audit_score = 85
		audit.insert()
		audit.submit()
		self.assertEqual((audit.docstatus, audit.status), (1, "Submitted"))

	def test_make_production_audit_without_operations_or_employee(self):
		wo = self._work_order(f"{PREFIX}FG-NOOP", self.bom_noop)
		audit = make_production_audit(wo.name)  # Administrator: no Employee record
		self.assertEqual(audit.work_order, wo.name)
		self.assertIsNone(audit.workstation)
		self.assertFalse(audit.inspector)

	def test_make_production_audit_refused_for_closed_or_draft_work_order(self):
		wo = self._work_order()
		frappe.db.set_value("Work Order", wo.name, "status", "Completed")
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_production_audit(wo.name)
		self.assertIn("Completed", str(ctx.exception))

		draft = self._work_order(submit=False)
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_production_audit(draft.name)
		self.assertIn("must be submitted", str(ctx.exception))

		with self.assertRaises(frappe.DoesNotExistError):
			make_production_audit(f"{PREFIX}MISSING-WO")

	def test_refused_without_work_order_read(self):
		wo = self._work_order()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			make_production_audit(wo.name)
		with self.assertRaises(frappe.PermissionError):
			get_audit_status(wo.name)

	# -- headline -----------------------------------------------------------------------------

	def test_audit_status_follows_latest_audit(self):
		wo = self._work_order()
		status = get_audit_status(wo.name)
		self.assertEqual(
			{k: status[k] for k in ("audit", "score", "status", "blocking", "can_audit")},
			{"audit": None, "score": None, "status": None, "blocking": False, "can_audit": True},
		)
		self.assertEqual(status["fail_score"], config.AUDIT_FAIL_SCORE)
		self.assertEqual(status["missing_before_finish"], 1)  # the Assembly Job Card is still open

		passed = self._audit(wo, 85)
		status = get_audit_status(wo.name)
		self.assertEqual((status["audit"], status["score"], status["blocking"]), (passed.name, 85, False))

		low = self._audit(wo, 60)
		status = get_audit_status(wo.name)
		self.assertEqual(
			(status["audit"], status["score"], status["status"], status["blocking"]),
			(low.name, 60, "Submitted", True),
		)

		later = self._audit(wo, 90)  # a newer passing audit does not hide the open low one (Finish gate)
		status = get_audit_status(wo.name)
		self.assertEqual((status["audit"], status["score"], status["blocking"]), (low.name, 60, True))

		low.db_set("status", "Action Closed")
		status = get_audit_status(wo.name)
		self.assertEqual((status["audit"], status["score"], status["blocking"]), (later.name, 90, False))

		closed_wo = self._work_order()  # only a closed low audit: "corrective action closed" state
		low = self._audit(closed_wo, 55, status="Action Closed")
		status = get_audit_status(closed_wo.name)
		self.assertEqual(
			(status["audit"], status["score"], status["status"], status["blocking"]),
			(low.name, 55, "Action Closed", False),
		)
		wo = closed_wo
		self.assertEqual(
			(status["audit"], status["status"], status["blocking"]), (low.name, "Action Closed", False)
		)

		frappe.db.set_value("Work Order", wo.name, "status", "Completed")
		status = get_audit_status(wo.name)
		self.assertEqual(
			(status["audit"], status["can_audit"], status["missing_before_finish"]), (low.name, False, 0)
		)

		with self.assertRaises(frappe.DoesNotExistError):
			get_audit_status(f"{PREFIX}MISSING-WO")

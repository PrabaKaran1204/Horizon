# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from horizon_erp.horizon_operations.test_fixtures import ensure_bom, make_work_order, setup_common
from horizon_erp.tests.cleanup import purge_test_residue


class TestManufacturing(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		cls.bom = ensure_bom("BRTEST-FG", "BRTEST-RM", operation_minutes=30)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _wo(self, qty, **extra):
		return make_work_order(
			"BRTEST-FG",
			self.bom.name,
			qty,
			self.wh.fg,
			self.wh.wip,
			self.wh.stores,
			expected_delivery_date=add_days(nowdate(), 1),
			**extra,
		)

	def test_over_capacity_blocked(self):
		frappe.set_user("brtest-mfg@horizon.local")
		wo = self._wo(100)  # 1000.75 h needed vs 2 days x 14.4 h on Line A
		with self.assertRaises(frappe.ValidationError) as ctx:
			wo.insert()
		message = str(ctx.exception)
		self.assertIn("Line A", message)
		self.assertIn("Capacity Override", message)

	def test_override_requires_operations_head(self):
		frappe.set_user("brtest-mfg@horizon.local")
		wo = self._wo(
			100, capacity_override=1, capacity_override_reason="Customer penalty clause, run double shifts"
		)
		self.assertRaises(frappe.PermissionError, wo.insert)

	def test_override_by_operations_head(self):
		frappe.set_user("brtest-ops@horizon.local")
		wo = self._wo(
			100, capacity_override=1, capacity_override_reason="Customer penalty clause, run double shifts"
		)
		wo.insert()
		self.assertAlmostEqual(wo.required_machine_hours, 100 * 10 + 0.75, places=2)
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Work Order", "reference_name": wo.name, "comment_type": "Comment"},
			pluck="content",
		)
		self.assertTrue(any("Capacity override" in c for c in comments))

	def test_small_order_fits(self):
		wo = self._wo(1).insert()
		self.assertAlmostEqual(wo.required_machine_hours, 10.75, places=2)

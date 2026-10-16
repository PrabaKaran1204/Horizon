# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_operations.test_fixtures import make_purchase_order, setup_common


class TestBuying(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _po(self, supplier, qty, rate, **extra):
		return make_purchase_order(supplier, "BRTEST-RM", qty, rate, warehouse=self.wh.stores, **extra)

	def test_approval_levels(self):
		po = self._po("BRTEST Clean", 10, 5000).insert()  # 50,000
		self.assertEqual(po.approval_level_required, "Level 1")

		po = self._po("BRTEST Clean", 10, 30000).insert()  # 3,00,000
		self.assertEqual(po.approval_level_required, "Level 2")

		po = self._po("BRTEST Clean", 10, 70000).insert()  # 7,00,000
		self.assertEqual(po.approval_level_required, "Level 3")

	def test_blacklisted_without_override_blocked(self):
		po = self._po("BRTEST Blacklisted", 10, 5000)
		with self.assertRaises(frappe.ValidationError) as ctx:
			po.insert()
		self.assertIn("blacklisted", str(ctx.exception).lower())

	def test_override_by_procurement_manager(self):
		frappe.set_user("brtest-pm@horizon.local")
		po = self._po(
			"BRTEST Blacklisted",
			10,
			5000,
			blacklist_override=1,
			override_reason="Sole source for critical component; approved by plant head on call",
		).insert()
		self.assertEqual(po.approval_level_required, "Level 3")

		logs = frappe.get_all(
			"Supplier Exception Log",
			filters={"purchase_order": po.name},
			fields=["name", "status", "requested_by"],
		)
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].status, "Pending")
		self.assertEqual(logs[0].requested_by, "brtest-pm@horizon.local")

		# saving again must not create a second log
		po.reload()
		po.save()
		self.assertEqual(frappe.db.count("Supplier Exception Log", {"purchase_order": po.name}), 1)

		# Finance Director was notified in-app
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{
					"document_type": "Purchase Order",
					"document_name": po.name,
					"for_user": "brtest-fd@horizon.local",
				},
			)
		)

	def test_override_short_reason_rejected(self):
		frappe.set_user("brtest-pm@horizon.local")
		po = self._po("BRTEST Blacklisted", 10, 5000, blacklist_override=1, override_reason="too short")
		self.assertRaises(frappe.ValidationError, po.insert)

	def test_override_by_plain_purchase_user_blocked(self):
		frappe.set_user("brtest-pu@horizon.local")
		po = self._po(
			"BRTEST Blacklisted",
			10,
			5000,
			blacklist_override=1,
			override_reason="Sole source for critical component; approved by plant head on call",
		)
		self.assertRaises(frappe.PermissionError, po.insert)

	def test_exception_log_approved_on_submit(self):
		frappe.set_user("brtest-pm@horizon.local")
		po = self._po(
			"BRTEST Blacklisted",
			10,
			5000,
			blacklist_override=1,
			override_reason="Sole source for critical component; approved by plant head on call",
		).insert()
		frappe.set_user("Administrator")
		po.reload()
		po.submit()
		log = frappe.get_doc("Supplier Exception Log", {"purchase_order": po.name})
		self.assertEqual(log.status, "Approved")
		self.assertEqual(log.approver, "Administrator")

	def test_pending_since_tracks_workflow_state(self):
		po = self._po("BRTEST Clean", 10, 5000).insert()
		self.assertFalse(po.pending_since)
		po.workflow_state = "Pending Dept Head"
		po.save()
		self.assertTrue(po.pending_since)

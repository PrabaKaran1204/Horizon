# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Regression tests for the configuration fixes of the live QA round (docs/07_qa_report.md).

Run:  bench --site horizon.local run-tests --app horizon_erp --module horizon_erp.setup.test_setup_fixes --skip-test-records

Everything is prefixed ``FIXTEST`` and rolled back with the class; the setup functions under test
are the same ones a fresh install / ``setup_all`` runs, so they must be idempotent here too.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from horizon_erp.horizon_operations.test_fixtures import (
	COMPANY,
	ensure_bom,
	ensure_employee,
	ensure_supplier,
	ensure_user,
	make_work_order,
	setup_common,
)
from horizon_erp.setup.demo_data import EMAIL_ACCOUNT_NAME, setup_email_account
from horizon_erp.setup.demo_hr_finance import (
	HOLIDAY_LIST,
	LEAVE_BLOCK_DATES,
	LEAVE_BLOCK_LIST,
	complete_first_maintenance_log,
	ensure_leave_block_list,
	scope_employee_user_permissions,
)
from horizon_erp.setup.roles import ROLE_PERMISSIONS, setup_role_permissions
from horizon_erp.tasks import safe_sendmail

USERS = {
	"fixtest-stock@horizon.local": ("FIXTEST Stock User", ["Stock User"]),
	"fixtest-sales@horizon.local": ("FIXTEST Sales User", ["Sales User"]),
	"fixtest-whm@horizon.local": ("FIXTEST Warehouse Manager", ["Warehouse Manager"]),
	"fixtest-qi@horizon.local": ("FIXTEST Quality Inspector", ["Quality Inspector"]),
	"fixtest-ops@horizon.local": ("FIXTEST Operations Head", ["Operations Head", "Employee"]),
}


def _reset_permission_caches(*users):
	frappe.clear_cache()
	frappe.local.role_permissions = {}
	for user in users:
		frappe.cache.hdel("user_permissions", user)


def _can(doctype, ptype, user, doc=None):
	frappe.local.role_permissions = {}
	return frappe.has_permission(doctype, ptype, doc=doc, user=user)


def _employee_linked_to(user, first_name):
	"""Employee with ``user_id`` - ERPNext then creates the catch-all User Permission under test."""
	existing = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if existing:
		return existing
	emp = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first_name,
			"company": COMPANY,
			"status": "Active",
			"gender": "Female",
			"date_of_birth": "1988-05-05",
			"date_of_joining": "2021-01-01",
			"user_id": user,
			"create_user_permission": 1,
		}
	)
	emp.flags.ignore_permissions = True
	emp.insert()
	return emp.name


class TestSetupFixes(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = True
		cls.wh = setup_common()
		for email, (first_name, roles) in USERS.items():
			ensure_user(email, first_name, roles)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------ DEF-02 / 04 / 14
	def test_role_permissions_close_receiving_and_dispatch_gaps(self):
		changed = setup_role_permissions()
		_reset_permission_caches(*USERS)
		self.assertIsInstance(changed, list)

		# receiving: a Stock User creates batches and serial numbers
		self.assertTrue(_can("Batch", "create", "fixtest-stock@horizon.local"))
		self.assertTrue(_can("Serial No", "create", "fixtest-stock@horizon.local"))
		# dispatch: a Sales User submits the Serial and Batch Bundle of a serialised delivery and
		# can read the invoice the server creates for them
		self.assertTrue(_can("Serial and Batch Bundle", "submit", "fixtest-sales@horizon.local"))
		self.assertTrue(_can("Sales Invoice", "read", "fixtest-sales@horizon.local"))
		self.assertFalse(_can("Sales Invoice", "create", "fixtest-sales@horizon.local"))
		# a Warehouse Manager dispatches and reads the customer's / supplier's address
		self.assertTrue(_can("Delivery Note", "submit", "fixtest-whm@horizon.local"))
		supplier = ensure_supplier("FIXTEST Supplier")
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "FIXTEST Supplier",
				"address_type": "Billing",
				"address_line1": "1 Test Road",
				"city": "Mumbai",
				"state": "Maharashtra",
				"pincode": "400001",
				"country": "India",
				"links": [{"link_doctype": "Supplier", "link_name": supplier.name}],
			}
		)
		address.flags.ignore_permissions = True
		address.insert()
		for user in ("fixtest-whm@horizon.local", "fixtest-stock@horizon.local"):
			self.assertTrue(_can("Address", "read", user, doc=address), user)
			self.assertTrue(_can("Contact", "read", user), user)
		# a pure Quality Inspector records inspections
		self.assertTrue(_can("Quality Inspection", "submit", "fixtest-qi@horizon.local"))
		self.assertFalse(_can("Quality Inspection", "create", "fixtest-stock@horizon.local"))

		# standard rules survive the switch to Custom DocPerm (Item Manager keeps Batch create)
		self.assertTrue(
			frappe.db.exists("Custom DocPerm", {"parent": "Batch", "role": "Item Manager", "create": 1})
		)
		# idempotent: a second run changes nothing and adds no rows
		before = frappe.db.count("Custom DocPerm", {"parent": ["in", list(ROLE_PERMISSIONS)]})
		self.assertEqual(setup_role_permissions(), [])
		self.assertEqual(
			frappe.db.count("Custom DocPerm", {"parent": ["in", list(ROLE_PERMISSIONS)]}), before
		)

	# ------------------------------------------------------------------- DEF-01
	def test_email_account_is_default_outgoing_and_sendmail_never_raises(self):
		name = setup_email_account()
		self.assertEqual(name, EMAIL_ACCOUNT_NAME)
		account = frappe.db.get_value(
			"Email Account",
			EMAIL_ACCOUNT_NAME,
			["default_outgoing", "enable_outgoing", "enable_incoming", "email_id"],
			as_dict=True,
		)
		self.assertEqual(account.default_outgoing, 1)
		self.assertEqual(account.enable_outgoing, 1)
		self.assertEqual(account.enable_incoming, 0)
		# exactly one default outgoing account
		self.assertEqual(frappe.db.count("Email Account", {"default_outgoing": 1}), 1)
		self.assertEqual(setup_email_account(), EMAIL_ACCOUNT_NAME)  # idempotent

		frappe.flags.mute_emails = True
		self.assertTrue(
			safe_sendmail(
				"FIXTEST sendmail",
				recipients=["fixtest-stock@horizon.local"],
				subject="FIXTEST notification",
				message="<p>hello</p>",
			)
		)
		# and the wrapper swallows any failure instead of raising (here: frappe.sendmail rejects the call)
		self.assertFalse(
			safe_sendmail(
				"FIXTEST sendmail failure",
				recipients=["fixtest-stock@horizon.local"],
				subject="FIXTEST",
				message="x",
				not_a_sendmail_argument=1,
			)
		)
		self.assertTrue(frappe.db.exists("Error Log", {"method": "FIXTEST sendmail failure"}))

	# ------------------------------------------------------------------- DEF-03
	def test_employee_user_permission_scoped_to_self_service_doctypes(self):
		ops_user = "fixtest-ops@horizon.local"
		own_employee = _employee_linked_to(ops_user, "FIXTEST Ops Head")
		inspector = ensure_employee("FIXTEST Inspector")
		self.assertTrue(
			frappe.db.exists(
				"User Permission",
				{
					"user": ops_user,
					"allow": "Employee",
					"for_value": own_employee,
					"apply_to_all_doctypes": 1,
				},
			),
			"ERPNext should have created the catch-all Employee permission (precondition)",
		)

		bom = ensure_bom("BRTEST-FG", "BRTEST-RM", operation_minutes=30)
		wo = make_work_order("BRTEST-FG", bom.name, 1, self.wh.fg, self.wh.wip, self.wh.stores)
		wo.insert()
		audit = frappe.get_doc(
			{
				"doctype": "Production Audit",
				"work_order": wo.name,
				"inspector": inspector,
				"audit_score": 85,
				"findings": "<p>FIXTEST audit by another inspector</p>",
			}
		)
		audit.flags.ignore_permissions = True
		audit.insert()

		_reset_permission_caches(ops_user)
		self.assertFalse(
			_can("Production Audit", "read", ops_user, doc=audit),
			"catch-all Employee permission must hide another inspector's audit (the defect)",
		)

		scope_employee_user_permissions()
		_reset_permission_caches(ops_user)
		self.assertFalse(
			frappe.db.exists(
				"User Permission",
				{
					"user": ops_user,
					"allow": "Employee",
					"for_value": own_employee,
					"apply_to_all_doctypes": 1,
				},
			)
		)
		applicable = frappe.get_all(
			"User Permission",
			filters={"user": ops_user, "allow": "Employee", "for_value": own_employee},
			pluck="applicable_for",
		)
		self.assertIn("Salary Slip", applicable)
		self.assertIn("Employee", applicable)
		# the Operations Head now reads every Production Audit ...
		self.assertTrue(_can("Production Audit", "read", ops_user, doc=audit))
		# ... but still only their own Employee record
		self.assertTrue(_can("Employee", "read", ops_user, doc=frappe.get_doc("Employee", own_employee)))
		self.assertFalse(_can("Employee", "read", ops_user, doc=frappe.get_doc("Employee", inspector)))
		# idempotent
		self.assertEqual(scope_employee_user_permissions(), 0)

	# ------------------------------------------------------------------- DEF-18
	def test_leave_block_list_on_working_days(self):
		from hrms.hr.doctype.leave_block_list.leave_block_list import get_applicable_block_dates

		name = ensure_leave_block_list()
		self.assertEqual(name, LEAVE_BLOCK_LIST)
		self.assertEqual(ensure_leave_block_list(), LEAVE_BLOCK_LIST)  # idempotent
		dates = {
			getdate(d.block_date)
			for d in frappe.get_all("Leave Block List Date", {"parent": name}, ["block_date"])
		}
		self.assertEqual(dates, {getdate(d) for d in LEAVE_BLOCK_DATES})
		if frappe.db.exists("Holiday List", HOLIDAY_LIST):
			holidays = set(frappe.get_all("Holiday", {"parent": HOLIDAY_LIST}, pluck="holiday_date"))
			self.assertFalse(dates & holidays, "block dates must not be holidays")
		employee = ensure_employee("FIXTEST Inspector")
		blocked = get_applicable_block_dates(LEAVE_BLOCK_DATES[0], LEAVE_BLOCK_DATES[-1], employee, COMPANY)
		self.assertEqual({getdate(b.block_date) for b in blocked}, dates)

	# ------------------------------------------------------------------- DEF-20
	def test_completed_maintenance_log_feeds_asset_register(self):
		from horizon_erp.horizon_finance.report.asset_register_with_maintenance.asset_register_with_maintenance import (
			get_last_maintenance,
		)

		asset = frappe.db.get_value("Asset Maintenance", {"company": COMPANY}, "asset_name")
		if not asset:
			self.skipTest("no Asset Maintenance on this site (demo_hr_finance not run)")
		complete_first_maintenance_log(asset, completion_date="2026-10-10")
		self.assertTrue(
			frappe.db.exists(
				"Asset Maintenance Log",
				{"asset_name": asset, "maintenance_status": "Completed", "docstatus": 1},
			)
		)
		self.assertIsNotNone(get_last_maintenance([asset]).get(asset))
		self.assertIsNone(complete_first_maintenance_log(asset))  # idempotent

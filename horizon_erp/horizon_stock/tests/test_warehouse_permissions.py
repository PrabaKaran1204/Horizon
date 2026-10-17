# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from erpnext.stock.utils import get_or_make_bin
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from horizon_erp.horizon_core.tests.fixtures import (
	ABBR,
	COMPANY,
	ensure_customer,
	ensure_item,
	ensure_user,
	ensure_users,
)
from horizon_erp.horizon_setup import dashboards
from horizon_erp.horizon_stock import permissions
from horizon_erp.horizon_stock.report.inventory_obsolescence_analysis import inventory_obsolescence_analysis
from horizon_erp.tests.cleanup import purge_test_residue

GROUP = "FIXTEST WP Group"
INSIDE = "FIXTEST WP Inside"
OUTSIDE = "FIXTEST WP Outside"
ITEM = "FIXTEST-WP-ITEM"
USER = "fixtest.wp@horizon.local"


def wh(name):
	return f"{name} - {ABBR}"


class TestWarehousePermissions(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)
		super().setUpClass()
		for name, parent, is_group in (
			(GROUP, wh("All Warehouses"), 1),
			(INSIDE, wh(GROUP), 0),
			(OUTSIDE, wh("All Warehouses"), 0),
		):
			if not frappe.db.exists("Warehouse", wh(name)):
				frappe.get_doc(
					{
						"doctype": "Warehouse",
						"warehouse_name": name,
						"company": COMPANY,
						"parent_warehouse": parent,
						"is_group": is_group,
					}
				).insert(ignore_permissions=True)
		ensure_item(ITEM)
		for warehouse, qty, rate in ((wh(INSIDE), 10, 100), (wh(OUTSIDE), 5, 200)):
			frappe.db.set_value(
				"Bin",
				get_or_make_bin(ITEM, warehouse),
				{"actual_qty": qty, "projected_qty": qty, "valuation_rate": rate, "stock_value": qty * rate},
				update_modified=False,
			)
		ensure_user(USER, "FIXTEST WP", ["Stock User"])
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": USER,
				"allow": "Warehouse",
				"for_value": wh(GROUP),
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		customer = ensure_customer()
		cls.dn_inside = cls._delivery_note(customer, wh(INSIDE))
		cls.dn_outside = cls._delivery_note(customer, wh(OUTSIDE))

	@staticmethod
	def _delivery_note(customer, warehouse):
		"""A Delivery Note with the warehouse on its row only (no Set Source Warehouse)."""
		dn = frappe.get_doc(
			{
				"doctype": "Delivery Note",
				"company": COMPANY,
				"customer": customer,
				"posting_date": nowdate(),
				"items": [{"item_code": ITEM, "qty": 1, "rate": 1, "uom": "Nos", "warehouse": warehouse}],
			}
		)
		dn.flags.ignore_validate = dn.flags.ignore_mandatory = dn.flags.ignore_links = True
		dn.insert(ignore_permissions=True)
		return dn.name

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_permitted_warehouses_expand_group(self):
		self.assertEqual(permissions.get_permitted_warehouses(USER), {wh(INSIDE)})
		self.assertIsNone(permissions.get_permitted_warehouses("Administrator"))

	def test_delivery_note_list_hides_rows_outside_permission(self):
		names = [self.dn_inside, self.dn_outside]
		frappe.set_user(USER)
		self.assertEqual(
			frappe.get_list("Delivery Note", filters={"name": ["in", names]}, pluck="name"), [self.dn_inside]
		)
		frappe.set_user("Administrator")
		self.assertEqual(
			sorted(frappe.get_list("Delivery Note", filters={"name": ["in", names]}, pluck="name")),
			sorted(names),
		)

	def test_obsolescence_report_and_cards_stay_in_permission(self):
		frappe.set_user(USER)
		rows = inventory_obsolescence_analysis.get_data(frappe._dict(company=COMPANY))
		self.assertEqual({r.warehouse for r in rows}, {wh(INSIDE)})
		# the cards only count what the user may see; they must not error for a restricted user
		self.assertIsNotNone(dashboards.get_stock_turnover({"company": COMPANY})["value"])
		self.assertIsNotNone(dashboards.get_items_below_reorder({"company": COMPANY})["value"])
		frappe.set_user("Administrator")
		rows = inventory_obsolescence_analysis.get_data(frappe._dict(company=COMPANY))
		self.assertTrue({wh(INSIDE), wh(OUTSIDE)} <= {r.warehouse for r in rows})

	def test_finance_director_reads_uom_for_stock_balance(self):
		ensure_users()
		self.assertTrue(
			frappe.permissions.get_role_permissions("UOM", user="brtest-fd@horizon.local").get("read")
		)

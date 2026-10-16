# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import json
import pathlib

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from horizon_erp.horizon_operations.test_fixtures import ensure_bom, make_work_order, setup_common
from horizon_erp.setup import dashboards
from horizon_erp.tests.cleanup import purge_test_residue

COMPANY = "Horizon Manufacturing Ltd"
APP_ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestDashboards(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		cls.bom = ensure_bom("BRTEST-FG", "BRTEST-RM", operation_minutes=30)

	def _wo(self, **extra):
		wo = make_work_order("BRTEST-FG", self.bom.name, 1, self.wh.fg, self.wh.wip, self.wh.stores, **extra)
		wo.insert()
		wo.submit()
		return wo

	def test_work_orders_overdue_counts_only_open_past_due(self):
		before = dashboards.get_work_orders_overdue({"company": COMPANY})["value"]
		overdue = self._wo()
		overdue.db_set("planned_end_date", add_days(now_datetime(), -2), update_modified=False)
		on_time = self._wo()
		on_time.db_set("planned_end_date", add_days(now_datetime(), 2), update_modified=False)
		closed = self._wo()
		closed.db_set(
			{"planned_end_date": add_days(now_datetime(), -2), "status": "Completed"}, update_modified=False
		)
		result = dashboards.get_work_orders_overdue({"company": COMPANY})
		self.assertEqual(result["fieldtype"], "Int")
		self.assertEqual(result["value"], before + 1)

	def test_line_utilisation_today_is_a_percentage(self):
		self._wo()  # one open Work Order booked on Line A today
		result = dashboards.get_line_utilisation_today({"company": COMPANY})
		self.assertEqual(result["fieldtype"], "Percent")
		self.assertGreater(result["value"], 0)
		self.assertLessEqual(result["value"], 100 * 10)  # bounded (over-booking is possible)
		self.assertEqual(dashboards.get_line_utilisation_today({})["value"] >= 0, True)

	def test_production_workspace_references_exist(self):
		path = (
			APP_ROOT / "horizon_operations" / "workspace" / "horizon_production" / "horizon_production.json"
		)
		ws = json.loads(path.read_text())
		self.assertEqual(ws["module"], "Horizon Operations")
		for card in ws["number_cards"]:
			folder = frappe.scrub(card["number_card_name"])
			files = list(APP_ROOT.glob(f"*/number_card/{folder}/{folder}.json"))
			self.assertEqual(len(files), 1, f"missing JSON for Number Card {card['number_card_name']}")
		for link in ws["links"]:
			if link.get("link_type") == "Report":
				self.assertTrue(frappe.db.exists("Report", link["link_to"]), link["link_to"])
			elif link.get("link_type") == "DocType":
				self.assertTrue(frappe.db.exists("DocType", link["link_to"]), link["link_to"])
		content = json.loads(ws["content"])
		cards_in_content = {b["data"]["number_card_name"] for b in content if b["type"] == "number_card"}
		self.assertEqual(cards_in_content, {c["number_card_name"] for c in ws["number_cards"]})
		shortcuts_in_content = {b["data"]["shortcut_name"] for b in content if b["type"] == "shortcut"}
		self.assertEqual(shortcuts_in_content, {s["label"] for s in ws["shortcuts"]})

	def test_setup_dashboards_consistent(self):
		self.assertIn("consistent", dashboards.setup_dashboards())

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import json
import pathlib
import re

import frappe
from frappe.desk.desktop import get_desktop_page
from frappe.desk.doctype.dashboard_chart.dashboard_chart import get as chart_get
from frappe.desk.doctype.number_card.number_card import get_result
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from horizon_erp.horizon_core.tests.fixtures import ensure_bom, make_work_order, setup_common
from horizon_erp.horizon_setup import dashboards
from horizon_erp.tests.cleanup import purge_test_residue

COMPANY = "Horizon Manufacturing Ltd"
APP_ROOT = pathlib.Path(__file__).resolve().parents[2]  # horizon_erp/horizon_erp
EXPECTED_WORKSPACES = {
	"Horizon ERP",
	"Horizon Setup & Masters",
	"Horizon Selling",
	"Horizon Buying",
	"Horizon Inventory",
	"Horizon Manufacturing",
	"Horizon Quality",
	"Horizon Projects & Assets",
	"Horizon HR & Payroll",
	"Horizon Accounts & Finance",
	"Horizon Integrations",
}


def available_icons():
	"""Icon names of the desk sidebar sprite (an unknown name renders as an empty space)."""
	svg = pathlib.Path(frappe.get_app_path("frappe", "public", "icons", "timeless", "icons.svg")).read_text()
	return set(re.findall(r'id="icon-([a-z0-9-]+)"', svg))


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

	def test_workspace_json_is_consistent(self):
		files = sorted(APP_ROOT.glob("*/workspace/*/*.json"))
		names = set()
		icons = available_icons()
		for path in files:
			ws = json.loads(path.read_text())
			name = ws["name"]
			names.add(name)
			self.assertEqual(frappe.scrub(ws["module"]), path.parts[-4], path)
			self.assertEqual((ws["title"], ws["label"], ws["public"]), (name, name, 1), name)
			self.assertIn(ws["icon"], icons, f"{name}: icon {ws['icon']!r} is not in the desk icon set")
			expected_parent = "" if name == dashboards.PARENT_WORKSPACE else dashboards.PARENT_WORKSPACE
			self.assertEqual(ws["parent_page"], expected_parent, name)
			for card in ws["number_cards"]:
				folder = frappe.scrub(card["number_card_name"])
				card_files = list(APP_ROOT.glob(f"*/number_card/{folder}/{folder}.json"))
				self.assertEqual(
					len(card_files), 1, f"missing JSON for Number Card {card['number_card_name']}"
				)
				card_label = json.loads(card_files[0].read_text())["label"]
				self.assertEqual(card["label"], card_label, name)
				self.assertLessEqual(len(card_label), 28, card_label)
				self.assertFalse(card_label.lower().startswith("horizon"), card_label)
			for chart in ws["charts"]:
				folder = frappe.scrub(chart["chart_name"])
				self.assertEqual(len(list(APP_ROOT.glob(f"*/dashboard_chart/{folder}/{folder}.json"))), 1)
				self.assertLessEqual(len(chart["label"]), 28, chart["label"])
			self.assertLessEqual(len(ws["charts"]), 2, name)
			for link in ws["links"]:
				if link["type"] == "Link":
					self.assertTrue(frappe.db.exists(link["link_type"], link["link_to"]), link["link_to"])
			# content blocks are resolved by the *label* of the child row (desk blocks/block.js)
			content = json.loads(ws["content"])
			by_type = {}
			for block in content:
				by_type.setdefault(block["type"], []).append(block["data"])
			self.assertEqual(by_type["header"][0]["col"], 12, name)
			self.assertTrue(by_type.get("paragraph"), f"{name}: no explanatory paragraph")
			self.assertEqual(
				sorted(b["number_card_name"] for b in by_type.get("number_card", [])),
				sorted(c["label"] for c in ws["number_cards"]),
				name,
			)
			self.assertEqual(
				sorted(b["chart_name"] for b in by_type.get("chart", [])),
				sorted(c["label"] for c in ws["charts"]),
				name,
			)
			self.assertEqual(
				[b["shortcut_name"] for b in by_type.get("shortcut", [])],
				[s["label"] for s in ws["shortcuts"]],
			)
			self.assertEqual(
				[b["card_name"] for b in by_type.get("card", [])],
				[lnk["label"] for lnk in ws["links"] if lnk["type"] == "Card Break"],
			)
		self.assertEqual(names, EXPECTED_WORKSPACES)

	def test_parent_links_every_child_workspace(self):
		children = frappe.get_all(
			"Workspace", filters={"parent_page": dashboards.PARENT_WORKSPACE}, pluck="title"
		)
		urls = {
			s.url
			for s in frappe.get_doc("Workspace", dashboards.PARENT_WORKSPACE).shortcuts
			if s.type == "URL"
		}
		self.assertEqual(len(children), len(EXPECTED_WORKSPACES) - 1)
		self.assertEqual(urls, {"/app/" + t.lower().replace(" ", "-") for t in children})

	def test_obsolete_records_are_gone(self):
		from horizon_erp.patches.v1_0 import redesign_workspaces

		redesign_workspaces.execute()  # idempotent
		for doctype, names in redesign_workspaces.OBSOLETE:
			for name in names:
				self.assertFalse(frappe.db.exists(doctype, name), name)
				folder = frappe.scrub(name)
				self.assertFalse(list(APP_ROOT.glob(f"*/{frappe.scrub(doctype)}/{folder}")), name)

	def test_dashboard_charts_are_not_fixtures(self):
		# fixture import validates, and DashboardChart.validate rejects standard charts when
		# developer_mode is off (production, and any migrate that runs a patch)
		fixture_doctypes = {
			f["dt"] if isinstance(f, dict) else f
			for f in frappe.get_hooks("fixtures", app_name="horizon_erp")
		}
		self.assertNotIn("Dashboard Chart", fixture_doctypes)
		self.assertFalse((APP_ROOT / "fixtures" / "dashboard_chart.json").exists())

	def test_stock_value_chart_has_short_labels(self):
		from horizon_erp.horizon_stock.dashboard_chart_source.horizon_stock_value_by_warehouse import (
			horizon_stock_value_by_warehouse as source,
		)

		data = source.get_data({"company": COMPANY})
		self.assertEqual(len(data["labels"]), len(data["datasets"][0]["values"]))
		for label, value in zip(data["labels"], data["datasets"][0]["values"], strict=True):
			self.assertFalse(label.endswith(" - HML"), label)
			self.assertGreater(value, 0)
		chart = frappe.get_doc("Dashboard Chart", "Horizon Stock Value by Warehouse")
		self.assertEqual((chart.chart_type, chart.source), ("Custom", "Horizon Stock Value by Warehouse"))

	def test_every_card_and_chart_evaluates(self):
		for ws_name in EXPECTED_WORKSPACES:
			page = get_desktop_page(json.dumps({"name": ws_name, "title": ws_name, "public": 1}))
			for card in page["number_cards"]["items"]:
				doc = frappe.get_doc("Number Card", card.number_card_name)
				if doc.type == "Custom":
					value = frappe.get_attr(doc.method)(filters={"company": COMPANY})["value"]
				else:
					value = get_result(doc.as_dict(), doc.filters_json)
				self.assertIsNotNone(value, card.number_card_name)
			for chart in page["charts"]["items"]:
				doc = frappe.get_doc("Dashboard Chart", chart.chart_name)
				if doc.chart_type != "Custom":
					self.assertTrue(chart_get(chart_name=chart.chart_name, refresh=1), chart.chart_name)

	def test_setup_dashboards_consistent(self):
		self.assertIn("consistent", dashboards.setup_dashboards())

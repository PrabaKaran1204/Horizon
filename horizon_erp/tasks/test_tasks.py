# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Tests for the Horizon scheduler jobs, print formats and notifications.

Run:  bench --site horizon.local run-tests --app horizon_erp --module horizon_erp.tasks.test_tasks --skip-test-records

All test data is prefixed ``SCHTEST-`` and created against the Horizon company (abbr HML) when
it exists. Emails are muted. The class rolls the DB back at the end (FrappeTestCase).

Side effect kept on purpose: when Purchase Order has no ``workflow_state`` column (no workflow
installed yet) the PO SLA test creates that Custom Field with exactly the spec Frappe's Workflow
would create, so the later "Horizon PO Approval" workflow finds it and skips creation.
"""

import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from horizon_erp.setup.notifications import get_notifications, setup_notifications
from horizon_erp.setup.print_formats import PRINT_FORMATS, setup_print_formats
from horizon_erp.tasks import cache_delete, cache_get, daily, hourly, monthly
from horizon_erp.tasks.daily import preview_daily_summary

PREFIX = "SCHTEST-"
PREVIEW_DIR = (
	"/tmp/claude-1000/-home-praba-kaynes-frappe-bench-apps/7201e109-2075-4986-973f-a2dc8263dd0f/"
	"scratchpad/print_preview"
)


def _company():
	return frappe.db.get_value("Company", {"abbr": "HML"}, "name") or frappe.defaults.get_global_default(
		"company"
	)


def _warehouse(company):
	abbr = frappe.get_cached_value("Company", company, "abbr")
	for name in (f"HQ Raw Materials - {abbr}", f"Stores - {abbr}"):
		if frappe.db.exists("Warehouse", name):
			return name
	return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")


def _hsn_code():
	"""Any 8-digit GST HSN Code (India Compliance makes HSN mandatory on Item)."""
	if not frappe.db.exists("DocType", "GST HSN Code"):
		return None
	codes = frappe.get_all("GST HSN Code", filters={"name": ["like", "________"]}, limit=1, pluck="name")
	return codes[0] if codes else frappe.db.get_value("GST HSN Code", {}, "name")


def _ensure_item(item_code, company, warehouse, **props):
	if frappe.db.exists("Item", item_code):
		return frappe.get_doc("Item", item_code)
	if _hsn_code():
		props.setdefault("gst_hsn_code", _hsn_code())
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"is_sales_item": 1,
			"is_purchase_item": 1,
			"valuation_rate": 100,
			"criticality": "B",
			"item_defaults": [{"company": company, "default_warehouse": warehouse}],
			**props,
		}
	)
	item.insert(ignore_permissions=True)
	return item


def _ensure_party(doctype, name, **props):
	if frappe.db.exists(doctype, name):
		return frappe.get_doc(doctype, name)
	doc = frappe.get_doc({"doctype": doctype, **props})
	doc.insert(ignore_permissions=True)
	return doc


def _dimension_values(company):
	"""{fieldname: value} for every enabled Accounting Dimension mandatory on P&L / BS accounts of
	``company`` (the site has a mandatory "Branch" dimension), using the default or first record."""
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		get_checks_for_pl_and_bs_accounts,
	)

	out = {}
	for dim in get_checks_for_pl_and_bs_accounts():
		if dim.company != company or not (dim.mandatory_for_pl or dim.mandatory_for_bs):
			continue
		doctype = frappe.db.get_value("Accounting Dimension", {"fieldname": dim.fieldname}, "document_type")
		value = dim.default_dimension or frappe.db.get_value(doctype, {}, "name")
		if value:
			out[dim.fieldname] = value
	return out


def _apply_dimensions(doc, company):
	dims = _dimension_values(company)
	for fieldname, value in dims.items():
		if doc.meta.has_field(fieldname):
			doc.set(fieldname, value)
		for row in doc.get("items") or []:
			if row.meta.has_field(fieldname):
				row.set(fieldname, value)
	return doc


def _stock_entry(purpose, item_code, qty, company, warehouse, rate=100):
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"purpose": purpose,
			"stock_entry_type": purpose,
			"company": company,
			"posting_date": today(),
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"basic_rate": rate,
					"s_warehouse": warehouse if purpose != "Material Receipt" else None,
					"t_warehouse": warehouse if purpose == "Material Receipt" else None,
				}
			],
		}
	)
	_apply_dimensions(se, company)
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	return se


class TestHorizonTasks(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.flags.mute_emails = True
		frappe.set_user("Administrator")
		# Workflow Action emails attach a PDF; wkhtmltopdf cannot resolve the site host in this
		# environment and workflow emails are not under test here (rolled back with the class).
		for wf in frappe.get_all("Workflow", {"is_active": 1}, pluck="name"):
			frappe.db.set_value("Workflow", wf, "send_email_alert", 0, update_modified=False)
		cls.company = _company()
		cls.warehouse = _warehouse(cls.company)
		cls.item = _ensure_item(f"{PREFIX}ITEM-1", cls.company, cls.warehouse, lead_time_days=0)
		cls.item2 = _ensure_item(f"{PREFIX}ITEM-2", cls.company, cls.warehouse)
		cls.supplier = _ensure_party(
			"Supplier",
			f"{PREFIX}SUPPLIER",
			supplier_name=f"{PREFIX}SUPPLIER",
			supplier_group=frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
			is_blacklisted=0,
		)
		cls.customer = _ensure_party(
			"Customer",
			f"{PREFIX}CUSTOMER",
			customer_name=f"{PREFIX}CUSTOMER",
			customer_group=frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			territory=frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			# Customer-level "allow without Sales Order / Delivery Note" flags keep the fixtures
			# self-contained regardless of the site's Selling Settings so_required / dn_required
			so_required=1,
			dn_required=1,
		)
		# selling.validate_discounts compares row rates with Item Price -> give both items a list price
		price_list = (
			frappe.db.get_single_value("Selling Settings", "selling_price_list") or "Standard Selling"
		)
		for item, rate in ((cls.item.name, 100), (cls.item2.name, 500)):
			if not frappe.db.exists(
				"Item Price", {"item_code": item, "price_list": price_list, "selling": 1}
			):
				frappe.get_doc(
					{
						"doctype": "Item Price",
						"item_code": item,
						"price_list": price_list,
						"price_list_rate": rate,
					}
				).insert(ignore_permissions=True)
		_stock_entry("Material Receipt", cls.item.name, 100, cls.company, cls.warehouse)
		_stock_entry("Material Receipt", cls.item2.name, 20, cls.company, cls.warehouse)

	# ------------------------------------------------------------------ hourly
	def test_reorder_and_accuracy_check_returns_keys(self):
		out = hourly.reorder_and_accuracy_check()
		self.assertNotIn("error", out, out.get("error"))
		for key in ("material_requests", "bin_mismatches", "count_variances"):
			self.assertIn(key, out)
		self.assertIsInstance(out["bin_mismatches"], list)

	def test_po_approval_reminders_escalates_after_48h(self):
		self._ensure_workflow_state_field()
		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"company": self.company,
				"supplier": self.supplier.name,
				"schedule_date": add_days(today(), 7),
				"set_warehouse": self.warehouse,
				"items": [
					{
						"item_code": self.item.name,
						"qty": 5,
						"rate": 1000,
						"schedule_date": add_days(today(), 7),
						"warehouse": self.warehouse,
					}
				],
			}
		)
		_apply_dimensions(po, self.company)
		po.flags.ignore_permissions = True
		try:
			po.insert()
		except frappe.ValidationError:
			po.flags.ignore_validate = True
			po.insert()

		po.db_set("workflow_state", "Pending Dept Head", update_modified=False)
		po.db_set("pending_since", add_to_date(now_datetime(), hours=-50), update_modified=False)
		cache_delete(f"horizon:po_reminder:{po.name}")

		out = hourly.po_approval_reminders()
		self.assertNotIn("error", out, out.get("error"))
		self.assertGreaterEqual(out["escalated"], 1)
		self.assertEqual(
			frappe.db.get_value("Purchase Order", po.name, "workflow_state"), "Pending Procurement Manager"
		)
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{
					"reference_doctype": "Purchase Order",
					"reference_name": po.name,
					"content": ["like", "Auto-escalated after%"],
				},
			)
		)

		# second PO only 30 h old -> reminder, not escalation
		po.db_set("workflow_state", "Pending Dept Head", update_modified=False)
		po.db_set("pending_since", add_to_date(now_datetime(), hours=-30), update_modified=False)
		out = hourly.po_approval_reminders()
		self.assertGreaterEqual(out["reminded"], 1)
		self.assertTrue(cache_get(f"horizon:po_reminder:{po.name}"))
		# repeat run within 6 h -> no second reminder for this PO
		out = hourly.po_approval_reminders()
		self.assertFalse([d for d in out["details"] if d["name"] == po.name])

	def _ensure_workflow_state_field(self):
		if frappe.db.has_column("Purchase Order", "workflow_state"):
			return
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Purchase Order",
				"fieldname": "workflow_state",
				"label": "Workflow State",
				"hidden": 1,
				"allow_on_submit": 1,
				"no_copy": 1,
				"fieldtype": "Link",
				"options": "Workflow State",
				"owner": "Administrator",
			}
		).insert(ignore_permissions=True)
		frappe.clear_cache(doctype="Purchase Order")

	# ------------------------------------------------------------------- daily
	def test_recompute_reorder_levels_inserts_row(self):
		# dedicated item so consumption from other tests (Delivery Notes) cannot skew the numbers
		rl_item = _ensure_item(
			f"{PREFIX}ITEM-RL-{frappe.generate_hash(length=6)}", self.company, self.warehouse
		)
		_stock_entry("Material Receipt", rl_item.name, 100, self.company, self.warehouse)
		_stock_entry("Material Issue", rl_item.name, 30, self.company, self.warehouse)
		frappe.db.delete("Item Reorder", {"parent": rl_item.name})
		out = daily.recompute_reorder_levels()
		self.assertNotIn("error", out, out.get("error"))
		for key in ("updated", "inserted", "skipped_no_usage", "samples"):
			self.assertIn(key, out)
		row = frappe.db.get_value(
			"Item Reorder",
			{"parent": rl_item.name, "warehouse": self.warehouse, "material_request_type": "Purchase"},
			["warehouse_reorder_level", "warehouse_reorder_qty"],
			as_dict=True,
		)
		self.assertIsNotNone(row, "Item Reorder row should have been inserted")
		# usage 30/90 = 0.333/day, lead 7, factor B 0.3 -> ceil(2.333 * 1.3) = 4 ; qty ceil(4.67) = 5
		self.assertEqual(row.warehouse_reorder_level, 4)
		self.assertEqual(row.warehouse_reorder_qty, 5)
		self.assertEqual(frappe.db.get_value("Item", rl_item.name, "safety_stock_factor"), 0.3)

		# second run updates instead of inserting a duplicate
		out = daily.recompute_reorder_levels()
		self.assertEqual(
			frappe.db.count("Item Reorder", {"parent": rl_item.name, "warehouse": self.warehouse}), 1
		)
		# zero-usage item keeps no row (manual level untouched)
		self.assertFalse(frappe.db.exists("Item Reorder", {"parent": self.item2.name}))

	def test_detect_quality_deadline_conflicts(self):
		out = daily.detect_quality_deadline_conflicts()
		self.assertNotIn("error", out, out.get("error"))
		self.assertIn("flagged", out)
		self.assertIsInstance(out["flagged"], list)

	def test_budget_threshold_alerts(self):
		out = daily.budget_threshold_alerts()
		self.assertNotIn("error", out, out.get("error"))
		self.assertIn("alerts", out)

	def test_send_daily_summary(self):
		out = daily.send_daily_summary()
		self.assertNotIn("error", out, out.get("error"))
		for key in (
			"sales_orders",
			"quotations_sent",
			"delivery_notes",
			"sales_invoices",
			"work_orders_completed",
			"purchase_orders_pending_approval",
			"production_audits_below_70",
			"low_stock",
		):
			self.assertIn(key, out)
		self.assertNotIn("pdf_error", out, out.get("pdf_error"))

	def test_preview_daily_summary(self):
		html = preview_daily_summary()
		self.assertIn("Sales Orders", html)
		self.assertIn("Horizon Daily Summary", html)

	# ----------------------------------------------------------------- monthly
	def test_send_budget_report(self):
		out = monthly.send_budget_report()
		self.assertNotIn("error", out, out.get("error"))
		for key in ("month", "rows", "cost_centers"):
			self.assertIn(key, out)
		html = monthly.preview_budget_report()
		self.assertIn("Budget vs Actual", html)

	# ------------------------------------------------------------ job wrapper
	def test_horizon_job_wrapper_logs_and_sets_retry_marker(self):
		from horizon_erp.tasks import RETRY_MARKER, horizon_job

		@horizon_job("schtest_failing")
		def failing():
			raise ValueError("boom")

		key = RETRY_MARKER.format(job="schtest_failing")
		cache_delete(key)
		out = failing()
		self.assertEqual(out.get("error"), "boom")
		self.assertTrue(cache_get(key))
		self.assertTrue(frappe.db.exists("Error Log", {"method": "Horizon job failed: schtest_failing"}))
		# next run clears the marker
		out = horizon_job("schtest_failing")(lambda: {"ok": 1})()
		self.assertEqual(out, {"ok": 1})
		self.assertFalse(cache_get(key))

	# ------------------------------------------------------- print / notify
	def test_setup_print_formats_and_render(self):
		names = setup_print_formats()
		self.assertEqual(sorted(names), sorted(p["name"] for p in PRINT_FORMATS))
		frappe.flags.ignore_print_permissions = True
		os.makedirs(PREVIEW_DIR, exist_ok=True)

		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer.name,
				"posting_date": today(),
				"due_date": add_days(today(), 30),
				"items": [
					{"item_code": self.item.name, "qty": 2, "rate": 30000, "warehouse": self.warehouse},
					{"item_code": self.item2.name, "qty": 1, "rate": 500, "warehouse": self.warehouse},
				],
			}
		)
		_apply_dimensions(si, self.company)
		si.flags.ignore_permissions = True
		si.insert()
		si.submit()
		html = frappe.get_print("Sales Invoice", si.name, "Horizon Sales Invoice")
		self.assertIn("High value", html)
		self.assertIn("Customer outstanding", html)
		self.assertIn(si.name, html)
		with open(os.path.join(PREVIEW_DIR, "horizon_sales_invoice.html"), "w") as f:
			f.write(html)

		# Selling Settings on this site require a Sales Order for every Delivery Note
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		so = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": self.company,
				"customer": self.customer.name,
				"transaction_date": today(),
				"delivery_date": add_days(today(), 2),
				"set_warehouse": self.warehouse,
				"items": [
					{
						"item_code": self.item.name,
						"qty": 3,
						"price_list_rate": 100,
						"rate": 100,
						"warehouse": self.warehouse,
					}
				],
			}
		)
		_apply_dimensions(so, self.company)
		so.flags.ignore_permissions = True
		so.insert()
		so.submit()
		dn = make_delivery_note(so.name)
		dn.set_warehouse = self.warehouse
		_apply_dimensions(dn, self.company)
		dn.flags.ignore_permissions = True
		dn.insert()
		dn.submit()
		html = frappe.get_print("Delivery Note", dn.name, "Horizon Packing Slip Thermal")
		self.assertIn(dn.name, html)
		self.assertIn("80mm", html)
		self.assertIn(so.name, html)  # SO ref printed on the slip
		self.assertNotIn(">Rate<", html)
		with open(os.path.join(PREVIEW_DIR, "horizon_packing_slip_thermal.html"), "w") as f:
			f.write(html)

	def test_setup_notifications(self):
		names = setup_notifications()
		self.assertEqual(sorted(names), sorted(n["name"] for n in get_notifications()))
		for name in names:
			self.assertTrue(frappe.db.exists("Notification", name))
		po = frappe.get_doc("Notification", "Horizon PO Approval Request")
		self.assertEqual(po.event, "Value Change")
		self.assertEqual(po.value_changed, "workflow_state")
		self.assertEqual(len(po.recipients), 3)

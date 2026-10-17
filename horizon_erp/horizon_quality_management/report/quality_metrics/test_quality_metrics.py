# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.tests.fixtures import (
	ensure_bom,
	ensure_employee,
	ensure_item,
	ensure_warehouse,
	make_purchase_receipt,
	make_work_order,
	setup_common,
)
from horizon_erp.horizon_quality_management.report.quality_metrics.quality_metrics import execute
from horizon_erp.tests.cleanup import purge_test_residue

COMPANY = "Horizon Manufacturing Ltd"
ITEM_GROUP = "GAPTEST Quality Metrics"
FG = "GAPTEST-QM-FG"
RM = "GAPTEST-QM-RM"
REASON = "Weld porosity on flange GAPTEST"


class TestQualityMetrics(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		frappe.db.set_single_value("Buying Settings", "po_required", "No")
		if not frappe.db.exists("Item Group", ITEM_GROUP):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": ITEM_GROUP,
					"parent_item_group": "All Item Groups",
				}
			).insert(ignore_permissions=True)
		ensure_item(
			RM, item_group=ITEM_GROUP, default_warehouse=cls.wh.stores, inspection_required_before_purchase=1
		)
		ensure_item(FG, item_group=ITEM_GROUP, valuation_rate=500, default_warehouse=cls.wh.fg)
		cls.bom = ensure_bom(FG, RM, operation_minutes=30)
		cls.employee = ensure_employee()
		cls.filters = {
			"company": COMPANY,
			"from_date": add_days(nowdate(), -1),
			"to_date": nowdate(),
			"item_group": ITEM_GROUP,
		}
		cls._make_work_orders()
		cls._make_inspection()

	@classmethod
	def _wo(cls, **extra):
		wo = make_work_order(FG, cls.bom.name, 1, cls.wh.fg, cls.wh.wip, cls.wh.stores, **extra)
		wo.insert()
		return wo

	@classmethod
	def _complete(cls, wo):
		wo.submit()
		wo.db_set({"status": "Completed", "actual_end_date": now_datetime()}, update_modified=False)

	@classmethod
	def _make_work_orders(cls):
		# WO 1: completed, then reworked
		cls.wo_rework_source = cls._wo()
		cls._complete(cls.wo_rework_source)
		cls.rework = cls._wo(rework_of=cls.wo_rework_source.name)
		# WO 2: completed with a failed audit (audit recorded while the WO is still open)
		cls.wo_audit = cls._wo()
		cls.wo_audit.submit()
		audit = frappe.get_doc(
			{
				"doctype": "Production Audit",
				"work_order": cls.wo_audit.name,
				"inspector": cls.employee,
				"audit_score": 65,
				"findings": "<p>GAPTEST torque out of spec</p>",
				"photos": [{"photo": "/files/gaptest-audit.png", "caption": "Station 3"}],
			}
		).insert()
		audit.submit()
		cls.wo_audit.db_set({"status": "Completed", "actual_end_date": now_datetime()}, update_modified=False)
		# WO 3: clean
		cls.wo_clean = cls._wo()
		cls._complete(cls.wo_clean)

	@classmethod
	def _make_inspection(cls):
		ensure_warehouse(config.QC_HOLD_WAREHOUSE_NAME)
		cls.pr = make_purchase_receipt("BRTEST Clean", RM, 5, 100, warehouse=cls.wh.stores)
		cls.pr.insert()
		cls.qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": "Purchase Receipt",
				"reference_name": cls.pr.name,
				"item_code": RM,
				"sample_size": 1,
				"inspected_by": "Administrator",
				"status": "Rejected",
				"qc_result": "Fail",
				"rejection_reason": REASON,
			}
		).insert()
		received = add_to_date(cls.qi.creation, hours=-1)
		frappe.db.set_value("Purchase Receipt", cls.pr.name, "creation", received, update_modified=False)

	def _rows(self):
		columns, data, _message, chart, summary = execute(self.filters)
		return columns, data, chart, {s["label"]: s for s in summary}

	def _header(self, data, prefix):
		return next(r for r in data if r.get("is_header") and r.label.startswith(prefix))

	def test_first_pass_yield(self):
		_c, data, _chart, summary = self._rows()
		fpy = self._header(data, "First-pass yield")
		self.assertEqual(fpy["count"], 3)
		self.assertAlmostEqual(fpy["pct"], 33.3, places=1)
		self.assertAlmostEqual(summary["First-pass Yield"]["value"], 33.3, places=1)
		issue_rows = {
			r.reference: r.detail for r in data if r.get("reference_type") == "Work Order" and r.indent == 1
		}
		self.assertIn(self.rework.name, issue_rows[self.wo_rework_source.name])
		self.assertIn("scored 65", issue_rows[self.wo_audit.name])
		self.assertNotIn(self.wo_clean.name, issue_rows)

	def test_rework_cost_pct(self):
		_c, data, _chart, summary = self._rows()
		header = self._header(data, "Rework cost %")
		self.assertEqual(header["count"], 1)
		self.assertGreater(header["amount"], 0)
		rework_row = next(r for r in data if r.get("reference") == self.rework.name and r.indent == 1)
		rework_cost = rework_row["amount"]
		# four Work Orders with identical BOM cost -> the rework one is 25 % of production cost
		self.assertAlmostEqual(header["pct"], 25.0, places=1)
		self.assertAlmostEqual(header["amount"], rework_cost, places=2)
		self.assertAlmostEqual(summary["Rework Cost %"]["value"], 25.0, places=1)

	def test_defect_reasons_and_chart(self):
		_c, data, chart, summary = self._rows()
		header = self._header(data, "Most common defect reasons")
		self.assertEqual(header["count"], 1)
		reason_row = next(r for r in data if r.label == REASON[:60])
		self.assertEqual(reason_row["count"], 1)
		self.assertEqual(len(chart["data"]["datasets"]), 1)
		self.assertEqual(sum(chart["data"]["datasets"][0]["values"]), 1)
		self.assertIn(REASON[:30], summary[next(k for k in summary if k.startswith("Defects"))]["label"])

	def test_inspection_sla(self):
		_c, data, _chart, summary = self._rows()
		header = self._header(data, "Inspection SLA")
		self.assertEqual(header["count"], 1)
		self.assertAlmostEqual(header["hours"], 1.0, delta=0.05)
		self.assertAlmostEqual(header["pct"], 100.0, places=1)
		qi_row = next(r for r in data if r.get("reference") == self.qi.name)
		self.assertAlmostEqual(qi_row["hours"], 1.0, delta=0.05)
		self.assertEqual(qi_row["is_breach"], 0)
		self.assertAlmostEqual(summary["Inspections within 4 h"]["value"], 100.0, places=1)

	def test_default_filters_run(self):
		columns, data, _m, chart, summary = execute({"company": COMPANY})
		self.assertEqual(len(columns), 9)
		self.assertEqual(len([r for r in data if r.get("is_header")]), 4)
		self.assertEqual(len(summary), 4)
		self.assertIn("labels", chart["data"])

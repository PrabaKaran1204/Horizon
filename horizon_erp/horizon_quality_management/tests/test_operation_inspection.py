# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""ADR-19 / DEF-25: inspection is mandatory per operation before a Work Order can finish."""

import frappe
from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime

from horizon_erp.horizon_core.tests.fixtures import (
	COMPANY,
	ensure_employee,
	ensure_item,
	ensure_workstations,
	make_stock,
	make_work_order,
	setup_common,
	with_dimensions,
)
from horizon_erp.horizon_quality_management.operation_inspection import (
	get_inspection_status,
	get_missing_before_finish,
	make_quality_inspection,
)
from horizon_erp.horizon_quality_management.operation_inspection import make_stock_entry as finish_entry
from horizon_erp.tests.cleanup import purge_test_residue

TEMPLATE = "QCGATE Inspection"
PARAMETER = "QCGATE Resistance"
OPERATIONS = ("QCGATE Wiring", "QCGATE Testing")


def ensure_template():
	if not frappe.db.exists("Quality Inspection Parameter", PARAMETER):
		frappe.get_doc({"doctype": "Quality Inspection Parameter", "parameter": PARAMETER}).insert(
			ignore_permissions=True
		)
	if not frappe.db.exists("Quality Inspection Template", TEMPLATE):
		frappe.get_doc(
			{
				"doctype": "Quality Inspection Template",
				"quality_inspection_template_name": TEMPLATE,
				"item_quality_inspection_parameter": [
					{"specification": PARAMETER, "numeric": 1, "min_value": 1, "max_value": 10}
				],
			}
		).insert(ignore_permissions=True)


def ensure_operation(name, template=None):
	if not frappe.db.exists("Operation", name):
		frappe.get_doc(
			{
				"doctype": "Operation",
				"name": name,
				"workstation": "Line A",
				"quality_inspection_template": template,
			}
		).insert(ignore_permissions=True)
	return name


def make_bom(item_code, rm_item_code, operations=()):
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": item_code,
			"company": COMPANY,
			"quantity": 1,
			"currency": "INR",
			"conversion_rate": 1,
			"rm_cost_as_per": "Valuation Rate",
			"with_operations": 1 if operations else 0,
			"is_default": 1,
			"is_active": 1,
			"operations": [
				{"operation": op, "workstation": "Line A", "time_in_mins": 10, "hour_rate": 100}
				for op in operations
			],
			"items": [{"item_code": rm_item_code, "qty": 1, "rate": 100, "uom": "Nos"}],
		}
	)
	bom.flags.ignore_permissions = True
	bom.insert()
	bom.submit()
	return bom


class TestOperationInspectionGate(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		ensure_workstations()
		ensure_template()
		ensure_operation(OPERATIONS[0], TEMPLATE)
		ensure_operation(OPERATIONS[1], TEMPLATE)
		ensure_operation("QCGATE Deburr")  # no template: not inspection-controlled
		ensure_item("QCGATE-RM", item_group="Raw Material", default_warehouse=cls.wh.stores)
		ensure_item("QCGATE-FG", item_group="Products", default_warehouse=cls.wh.fg)
		ensure_item("QCGATE-FG-NOOP", item_group="Products", default_warehouse=cls.wh.fg)
		ensure_item("QCGATE-FG-PLAIN", item_group="Products", default_warehouse=cls.wh.fg)
		cls.bom = make_bom("QCGATE-FG", "QCGATE-RM", OPERATIONS)
		cls.bom_noop = make_bom("QCGATE-FG-NOOP", "QCGATE-RM")
		cls.bom_plain = make_bom("QCGATE-FG-PLAIN", "QCGATE-RM", ("QCGATE Deburr",))
		cls.employee = ensure_employee()
		make_stock("QCGATE-RM", cls.wh.stores, 100)
		cls._slot = get_datetime("2020-06-30 23:00:00")  # clear of real Job Card time logs

	def tearDown(self):
		frappe.set_user("Administrator")

	# -- helpers ----------------------------------------------------------------------------

	def _work_order(self, item_code="QCGATE-FG", bom=None, qty=1, **extra):
		wo = make_work_order(
			item_code,
			(bom or self.bom).name,
			qty,
			self.wh.fg,
			self.wh.wip,
			self.wh.stores,
			skip_transfer=1,
			**extra,
		)
		wo.insert()
		wo.submit()
		return wo

	def _cards(self, wo):
		return {
			row.operation: row.name
			for row in frappe.get_all(
				"Job Card",
				filters={"work_order": wo.name},
				fields=["name", "operation"],
				order_by="sequence_id asc, creation asc",
			)
		}

	def _complete(self, job_card, submit=True):
		TestOperationInspectionGate._slot = add_to_date(self._slot, hours=-2)
		jc = frappe.get_doc("Job Card", job_card)
		if jc.time_logs:  # an earlier blocked submit already saved the time log
			if submit:
				jc.submit()
			return jc
		jc.append(
			"time_logs",
			{
				# one free hour per card on the shared workstation (ERPNext rejects overlapping logs)
				"from_time": add_to_date(self._slot, hours=-1),
				"to_time": self._slot,
				"time_in_mins": 60,
				"completed_qty": jc.for_quantity,
			},
		)
		jc.save()
		if submit:
			jc.submit()
		return jc

	def _inspect(self, job_card, reading="5", qc_result="Pass"):
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "In Process",
				"reference_type": "Job Card",
				"reference_name": job_card,
				"item_code": frappe.db.get_value("Job Card", job_card, "production_item"),
				"sample_size": 1,
				"inspected_by": "Administrator",
				"quality_inspection_template": TEMPLATE,
				"qc_result": qc_result,
				"rejection_reason": "QCGATE out of spec" if qc_result in ("Fail", "Rework") else None,
				"readings": [
					{
						"specification": PARAMETER,
						"numeric": 1,
						"min_value": 1,
						"max_value": 10,
						"reading_1": reading,
					}
				],
			}
		).insert()
		qi.submit()
		return qi

	def _inspect_and_complete(self, wo):
		for card in self._cards(wo).values():
			self._inspect(card)
			self._complete(card)

	def _set_operation_template(self, operation, template):
		frappe.db.set_value("Operation", operation, "quality_inspection_template", template)
		frappe.clear_document_cache("Operation", operation)

	def _manufacture(self, wo, qty=None, finish_button=True):
		"""``finish_button``: through the overridden endpoint the Work Order "Finish" button calls;
		otherwise ERPNext's own builder, so the Stock Entry ``before_validate`` gate is exercised."""
		build = finish_entry if finish_button else make_stock_entry
		se = frappe.get_doc(build(wo.name, "Manufacture", qty or wo.qty))
		with_dimensions(se)
		return se

	# -- Job Card gate ----------------------------------------------------------------------

	def test_job_card_template_from_operation(self):
		wo = self._work_order()
		card = self._cards(wo)[OPERATIONS[0]]
		self.assertEqual(frappe.db.get_value("Job Card", card, "quality_inspection_template"), TEMPLATE)

	def test_job_card_submit_blocked_without_qi(self):
		wo = self._work_order()
		card = self._cards(wo)[OPERATIONS[0]]
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._complete(card)
		self.assertIn("cannot be completed without an Accepted Quality Inspection", str(ctx.exception))
		self.assertIn(OPERATIONS[0], str(ctx.exception))

	def test_job_card_submit_blocked_by_rejected_and_rework_qi(self):
		wo = self._work_order()
		card = self._cards(wo)[OPERATIONS[0]]
		rejected = self._inspect(card, reading="50", qc_result="")  # out of range -> Rejected
		self.assertEqual(rejected.status, "Rejected")
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._complete(card)
		self.assertIn(rejected.name, str(ctx.exception))

		rework = self._inspect(card, reading="5", qc_result="Rework")  # Accepted readings, Rework
		self.assertEqual(rework.status, "Accepted")
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._complete(card)
		self.assertIn("Rework", str(ctx.exception))

		self._inspect(card, reading="5", qc_result="Conditional Pass")  # accepted re-inspection
		self.assertEqual(self._complete(card).docstatus, 1)

	def test_job_card_without_template_unaffected(self):
		wo = self._work_order("QCGATE-FG-PLAIN", self.bom_plain)
		card = self._cards(wo)["QCGATE Deburr"]
		self.assertEqual(self._complete(card).docstatus, 1)
		self.assertEqual(get_missing_before_finish(wo.name), [])

	# -- Job Card form: Create > Quality Inspection and status headline ----------------------

	def test_make_quality_inspection_prefilled_from_job_card(self):
		wo = self._work_order(qty=3)
		card = self._cards(wo)[OPERATIONS[0]]
		qi = make_quality_inspection(card)
		self.assertTrue(qi.get("__islocal"))
		self.assertEqual(qi.inspection_type, "In Process")
		self.assertEqual((qi.reference_type, qi.reference_name), ("Job Card", card))
		self.assertEqual(qi.item_code, "QCGATE-FG")
		self.assertEqual(qi.bom_no, self.bom.name)
		self.assertEqual(qi.quality_inspection_template, TEMPLATE)
		self.assertEqual(qi.sample_size, 3)
		self.assertEqual(qi.inspected_by, "Administrator")
		self.assertEqual([r.specification for r in qi.readings], [PARAMETER])
		self.assertEqual((qi.readings[0].min_value, qi.readings[0].max_value), (1, 10))

		qi.readings[0].reading_1 = "5"
		qi.insert()
		qi.submit()
		self.assertEqual(qi.status, "Accepted")
		self.assertEqual(frappe.db.get_value("Job Card", card, "quality_inspection"), qi.name)
		self.assertEqual(self._complete(card).docstatus, 1)

	def test_make_quality_inspection_refused_without_template_or_permission(self):
		wo = self._work_order("QCGATE-FG-PLAIN", self.bom_plain)
		card = self._cards(wo)["QCGATE Deburr"]
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_quality_inspection(card)
		self.assertIn("no Quality Inspection Template", str(ctx.exception))

		gated = self._cards(self._work_order())[OPERATIONS[0]]
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			make_quality_inspection(gated)
		with self.assertRaises(frappe.PermissionError):
			get_inspection_status(gated)

	def test_inspection_status_follows_latest_inspection(self):
		wo = self._work_order()
		cards = self._cards(wo)
		card = cards[OPERATIONS[0]]
		status = get_inspection_status(card)
		self.assertEqual(
			status,
			{"template": TEMPLATE, "required": True, "inspection": None, "result": None, "accepted": False},
		)

		rework = self._inspect(card, reading="5", qc_result="Rework")
		status = get_inspection_status(card)
		self.assertEqual(
			(status["inspection"], status["result"], status["accepted"]), (rework.name, "Rework", False)
		)

		accepted = self._inspect(card, reading="5", qc_result="Pass")
		status = get_inspection_status(card)
		self.assertEqual(
			(status["inspection"], status["result"], status["accepted"]), (accepted.name, "Pass", True)
		)

		plain = self._cards(self._work_order("QCGATE-FG-PLAIN", self.bom_plain))["QCGATE Deburr"]
		self.assertFalse(get_inspection_status(plain)["required"])
		with self.assertRaises(frappe.DoesNotExistError):
			get_inspection_status("PO-JOB-QCGATE-MISSING")

	def test_job_card_links_accepted_inspection_on_save(self):
		"""Fallback for ERPNext's update_qc_reference, which skips cards whose production_item
		differs from the inspection's item_code."""
		wo = self._work_order()
		card = self._cards(wo)[OPERATIONS[0]]
		qi = self._inspect(card)
		frappe.db.set_value("Job Card", card, "quality_inspection", None)
		jc = frappe.get_doc("Job Card", card)
		self.assertFalse(jc.quality_inspection)
		jc.save()
		self.assertEqual(jc.quality_inspection, qi.name)

	# -- Manufacture (Finish) gate -----------------------------------------------------------

	def test_manufacture_blocked_lists_every_missing_item(self):
		wo = self._work_order()
		cards = self._cards(wo)
		# Wiring completed before its Operation had a template (legacy card, as PO-JOB00011)
		self._set_operation_template(OPERATIONS[0], None)
		jc = self._complete(cards[OPERATIONS[0]], submit=False)
		jc.db_set("quality_inspection_template", None)
		jc.reload()
		jc.submit()
		self._set_operation_template(OPERATIONS[0], TEMPLATE)

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._manufacture(wo).insert()
		message = str(ctx.exception)
		self.assertIn("Missing before finish", message)
		self.assertIn(f"Quality Inspection for <strong>{OPERATIONS[0]}</strong>", message)
		self.assertIn(jc.name, message)
		self.assertIn(f"Job Card for <strong>{OPERATIONS[1]}</strong> not completed", message)

	def test_manufacture_blocked_by_rejected_or_rework_qi(self):
		wo = self._work_order()
		self._inspect_and_complete(wo)
		testing = self._cards(wo)[OPERATIONS[1]]
		rework = self._inspect(testing, reading="5", qc_result="Rework")  # later QI decides
		with self.assertRaises(frappe.ValidationError) as ctx:  # Stock Entry before_validate gate
			self._manufacture(wo, finish_button=False).insert()
		self.assertIn(rework.name, str(ctx.exception))

		rejected = self._inspect(testing, reading="0", qc_result="")
		self.assertEqual(rejected.status, "Rejected")
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._manufacture(wo).insert()
		self.assertIn(rejected.name, str(ctx.exception))
		self.assertIn("Rejected", str(ctx.exception))

	def test_manufacture_allowed_with_accepted_qis(self):
		wo = self._work_order(qty=2)
		self._inspect_and_complete(wo)
		self.assertEqual(get_missing_before_finish(wo.name), [])
		se = self._manufacture(wo, qty=1).insert()  # partial manufacture: qty is not the gate's
		se.submit()
		self.assertEqual(se.docstatus, 1)
		self.assertEqual(frappe.db.get_value("Work Order", wo.name, "produced_qty"), 1)

	def test_rework_work_order_same_rules(self):
		source = self._work_order()
		rework = self._work_order(rework_of=source.name)
		self.assertTrue(get_missing_before_finish(rework.name))
		self._inspect_and_complete(rework)
		self.assertEqual(get_missing_before_finish(rework.name), [])

	def test_work_order_without_operations_unaffected(self):
		wo = self._work_order("QCGATE-FG-NOOP", self.bom_noop)
		se = self._manufacture(wo).insert()
		se.submit()
		self.assertEqual(se.docstatus, 1)

	def test_open_low_audit_still_blocks_with_qis(self):
		wo = self._work_order()
		self._inspect_and_complete(wo)
		audit = frappe.get_doc(
			{
				"doctype": "Production Audit",
				"work_order": wo.name,
				"inspector": self.employee,
				"audit_score": 60,
				"findings": "<p>QCGATE loose terminal</p>",
				"photos": [{"photo": "/files/qcgate-audit.png", "caption": "Terminal block"}],
			}
		).insert()
		audit.submit()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._manufacture(wo).insert()
		self.assertIn(audit.name, str(ctx.exception))

		audit.db_set("status", "Action Closed")
		self.assertEqual(self._manufacture(wo).insert().docstatus, 0)

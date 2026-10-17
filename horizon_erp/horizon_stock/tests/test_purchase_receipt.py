# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Receipt -> Quality Check -> GRN (``horizon_erp.horizon_stock.purchase_receipt``, ADR-2).

``TestPurchaseReceiptStandardFlow``: default mode (QC Hold routing off) - the draft is the receipt,
submit is the GRN and posts accepted / rejected qty straight to their warehouses.
``TestPurchaseReceiptQCHold``: the optional QC Hold routing (switched on through site config).
"""

from unittest.mock import patch

import frappe
from erpnext.controllers.stock_controller import QualityInspectionRequiredError
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.tests.fixtures import (
	ensure_item,
	ensure_warehouse,
	make_purchase_receipt,
	setup_common,
)
from horizon_erp.tests.cleanup import purge_test_residue

INSP_ITEM = "GAPTEST-INSP-RM"
PLAIN_ITEM = "GAPTEST-PLAIN-RM"
SUPPLIER = "BRTEST Clean"


class PurchaseReceiptTestMixin:
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		# these tests receive without a Purchase Order; rolled back with the test transaction
		frappe.db.set_single_value("Buying Settings", "po_required", "No")
		# as configured by demo_data (ADR-2)
		frappe.db.set_single_value(
			"Stock Settings",
			{
				"action_if_quality_inspection_is_not_submitted": "Stop",
				"action_if_quality_inspection_is_rejected": "Warn",
				"allow_to_make_quality_inspection_after_purchase_or_delivery": 0,
				config.QC_HOLD_SETTINGS_FIELD: 0,
			},
		)
		cls.qc_hold = ensure_warehouse(config.QC_HOLD_WAREHOUSE_NAME)
		cls.raw_materials = ensure_warehouse(config.RAW_MATERIAL_WAREHOUSE_NAME)
		cls.rejected = ensure_warehouse(config.REJECTED_WAREHOUSE_NAME)
		ensure_item(INSP_ITEM, default_warehouse=cls.raw_materials, inspection_required_before_purchase=1)
		ensure_item(PLAIN_ITEM, default_warehouse=cls.raw_materials, inspection_required_before_purchase=0)

	def setUp(self):
		patcher = patch.dict(frappe.local.conf, {config.QC_HOLD_SITE_CONFIG_KEY: self.QC_HOLD})
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _receipt(self, accepted, rejected=0, item_code=INSP_ITEM):
		pr = make_purchase_receipt(SUPPLIER, item_code, accepted, 100, warehouse=self.raw_materials)
		row = pr.items[0]
		row.received_qty = accepted + rejected
		row.rejected_qty = rejected
		return pr.insert()

	def _inspect(self, pr, status="Accepted"):
		qi = frappe.get_doc(
			{
				"doctype": "Quality Inspection",
				"inspection_type": "Incoming",
				"reference_type": "Purchase Receipt",
				"reference_name": pr.name,
				"item_code": pr.items[0].item_code,
				"child_row_reference": pr.items[0].name,
				"sample_size": 1,
				"inspected_by": "Administrator",
				"status": status,
				"manual_inspection": 1,
			}
		).insert()
		qi.submit()
		pr.reload()
		self.assertEqual(pr.items[0].quality_inspection, qi.name)
		return qi

	def _stock_moves(self, voucher_no):
		moves = {}
		for sle in frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": voucher_no, "is_cancelled": 0},
			fields=["warehouse", "actual_qty"],
		):
			moves[sle.warehouse] = moves.get(sle.warehouse, 0) + sle.actual_qty
		return moves

	def _release_entries(self, pr_name):
		return frappe.get_all(
			"Stock Entry", filters={"remarks": ["like", f"%{pr_name}%"], "docstatus": 1}, pluck="name"
		)

	def _draft_return(self, pr_name):
		returns = frappe.get_all(
			"Purchase Receipt",
			filters={"return_against": pr_name, "is_return": 1},
			fields=["name", "docstatus"],
		)
		self.assertEqual(len(returns), 1)
		self.assertEqual(returns[0].docstatus, 0)
		return frappe.get_doc("Purchase Receipt", returns[0].name)


class TestPurchaseReceiptStandardFlow(PurchaseReceiptTestMixin, FrappeTestCase):
	QC_HOLD = None  # no site-config override: Stock Settings (0) decides

	def test_mode_is_off_by_default(self):
		self.assertFalse(config.use_qc_hold())

	def test_mode_follows_stock_settings_then_site_config(self):
		frappe.db.set_single_value("Stock Settings", config.QC_HOLD_SETTINGS_FIELD, 1)
		self.assertTrue(config.use_qc_hold())
		with patch.dict(frappe.local.conf, {config.QC_HOLD_SITE_CONFIG_KEY: 0}):
			self.assertFalse(config.use_qc_hold())  # site config wins
		frappe.db.set_single_value("Stock Settings", config.QC_HOLD_SETTINGS_FIELD, 0)
		self.assertFalse(config.use_qc_hold())

	def test_row_keeps_warehouse_and_gets_rejected_warehouse(self):
		pr = self._receipt(5)
		self.assertEqual(pr.items[0].warehouse, self.raw_materials)
		self.assertEqual(pr.items[0].rejected_warehouse, self.rejected)
		self.assertEqual(self._stock_moves(pr.name), {})  # the draft (receipt) posts no stock

	def test_rejected_qty_on_first_save_gets_rejected_warehouse(self):
		# ERPNext's own check runs in the controller validate: the default must come first
		pr = self._receipt(8, rejected=2, item_code=PLAIN_ITEM)
		self.assertEqual(pr.items[0].rejected_warehouse, self.rejected)

	def test_submit_blocked_without_quality_inspection(self):
		pr = self._receipt(5)
		with self.assertRaises(QualityInspectionRequiredError):
			pr.submit()

	def test_accepted_and_rejected_post_directly(self):
		pr = self._receipt(90, rejected=10)
		self._inspect(pr)
		pr.submit()
		self.assertEqual(self._stock_moves(pr.name), {self.raw_materials: 90, self.rejected: 10})
		self.assertEqual(self._release_entries(pr.name), [])  # no QC Hold -> Raw Materials transfer
		pr_return = self._draft_return(pr.name)
		self.assertEqual([(r.item_code, r.qty) for r in pr_return.items], [(INSP_ITEM, -10)])
		self.assertEqual(pr_return.items[0].warehouse, self.rejected)

	def test_fully_rejected_lot_submits_with_warning_and_return(self):
		pr = self._receipt(0, rejected=10)
		self._inspect(pr, status="Rejected")
		frappe.clear_messages()
		pr.submit()
		messages = " ".join(str(m) for m in frappe.message_log)
		self.assertIn("was rejected", messages)  # Stock Settings: QI rejected = Warn
		self.assertEqual(self._stock_moves(pr.name), {self.rejected: 10})
		self.assertEqual([r.qty for r in self._draft_return(pr.name).items], [-10])

	def test_non_inspection_item_keeps_warehouse(self):
		pr = self._receipt(5, item_code=PLAIN_ITEM)
		self.assertEqual(pr.items[0].warehouse, self.raw_materials)
		self.assertFalse(pr.items[0].rejected_warehouse)

	def test_qc_hold_row_is_not_released_when_mode_off(self):
		pr = make_purchase_receipt(SUPPLIER, INSP_ITEM, 5, 100, warehouse=self.qc_hold).insert()
		self.assertEqual(pr.items[0].warehouse, self.qc_hold)  # chosen by hand: left as is
		self._inspect(pr)
		pr.submit()
		self.assertEqual(self._release_entries(pr.name), [])
		self.assertEqual(self._stock_moves(pr.name), {self.qc_hold: 5})


class TestPurchaseReceiptQCHold(PurchaseReceiptTestMixin, FrappeTestCase):
	QC_HOLD = 1  # optional QC Hold routing switched on through site config

	def test_inspection_item_rerouted_to_qc_hold(self):
		pr = self._receipt(5)
		row = pr.items[0]
		self.assertEqual(row.warehouse, self.qc_hold)
		self.assertEqual(row.rejected_warehouse, self.rejected)
		# re-saving keeps it there without re-routing again
		pr.reload()
		pr.save()
		self.assertEqual(pr.items[0].warehouse, self.qc_hold)

	def test_non_inspection_item_keeps_warehouse(self):
		pr = self._receipt(5, item_code=PLAIN_ITEM)
		self.assertEqual(pr.items[0].warehouse, self.raw_materials)
		self.assertFalse(pr.items[0].rejected_warehouse)

	def test_return_receipt_not_rerouted(self):
		pr = make_purchase_receipt(SUPPLIER, INSP_ITEM, -1, 100, warehouse=self.raw_materials, is_return=1)
		from horizon_erp.horizon_stock.purchase_receipt import validate_purchase_receipt

		validate_purchase_receipt(pr)  # must not touch a return
		self.assertEqual(pr.items[0].warehouse, self.raw_materials)

	def test_accepted_stock_released_from_qc_hold(self):
		pr = self._receipt(90, rejected=10)
		self._inspect(pr)
		pr.submit()
		self.assertEqual(self._stock_moves(pr.name), {self.qc_hold: 90, self.rejected: 10})
		releases = self._release_entries(pr.name)
		self.assertEqual(len(releases), 1)
		self.assertEqual(self._stock_moves(releases[0]), {self.qc_hold: -90, self.raw_materials: 90})
		self.assertEqual([r.qty for r in self._draft_return(pr.name).items], [-10])

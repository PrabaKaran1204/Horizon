# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Purchase Receipt QC Hold routing (``horizon_erp.horizon_stock.purchase_receipt``)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.tests.fixtures import (
	ensure_item,
	ensure_warehouse,
	make_purchase_receipt,
	setup_common,
)
from horizon_erp.tests.cleanup import purge_test_residue


class TestPurchaseReceiptQCHold(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		# the QC Hold tests receive without a Purchase Order; rolled back with the test transaction
		frappe.db.set_single_value("Buying Settings", "po_required", "No")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _qc_warehouses(self):
		return (
			ensure_warehouse(config.QC_HOLD_WAREHOUSE_NAME),
			ensure_warehouse(config.RAW_MATERIAL_WAREHOUSE_NAME),
			ensure_warehouse(config.REJECTED_WAREHOUSE_NAME),
		)

	def test_inspection_item_rerouted_to_qc_hold(self):
		qc_hold, raw_materials, rejected = self._qc_warehouses()
		ensure_item("GAPTEST-INSP-RM", default_warehouse=raw_materials, inspection_required_before_purchase=1)
		pr = make_purchase_receipt("BRTEST Clean", "GAPTEST-INSP-RM", 5, 100, warehouse=raw_materials)
		pr.insert()
		row = pr.items[0]
		self.assertEqual(row.warehouse, qc_hold)
		self.assertEqual(row.rejected_warehouse, rejected)
		# re-saving keeps it there without re-routing again
		pr.reload()
		pr.save()
		self.assertEqual(pr.items[0].warehouse, qc_hold)

	def test_non_inspection_item_keeps_warehouse(self):
		_qc_hold, raw_materials, _rejected = self._qc_warehouses()
		ensure_item(
			"GAPTEST-PLAIN-RM", default_warehouse=raw_materials, inspection_required_before_purchase=0
		)
		pr = make_purchase_receipt("BRTEST Clean", "GAPTEST-PLAIN-RM", 5, 100, warehouse=raw_materials)
		pr.insert()
		self.assertEqual(pr.items[0].warehouse, raw_materials)
		self.assertFalse(pr.items[0].rejected_warehouse)

	def test_return_receipt_not_rerouted(self):
		_qc_hold, raw_materials, _rejected = self._qc_warehouses()
		ensure_item("GAPTEST-INSP-RM", default_warehouse=raw_materials, inspection_required_before_purchase=1)
		pr = make_purchase_receipt(
			"BRTEST Clean", "GAPTEST-INSP-RM", -1, 100, warehouse=raw_materials, is_return=1
		)
		from horizon_erp.horizon_stock.purchase_receipt import validate_purchase_receipt

		validate_purchase_receipt(pr)  # must not touch a return
		self.assertEqual(pr.items[0].warehouse, raw_materials)

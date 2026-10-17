# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Standard ERPNext Supplier Scorecard configuration (``demo_data.setup_supplier_scorecards``).

Self-contained: two ``BRTEST`` suppliers receive the same item, one with rejections; the standard
scoring engine must rank the rejecting supplier lower. Rolled back with the class.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from horizon_erp.horizon_core import config
from horizon_erp.horizon_core.tests.fixtures import (
	ensure_supplier,
	ensure_warehouse,
	make_purchase_receipt,
	setup_common,
)
from horizon_erp.horizon_setup.demo_data import (
	SCORECARD_CRITERIA,
	SCORECARD_PERIOD,
	setup_supplier_scorecards,
)
from horizon_erp.tests.cleanup import purge_test_residue

CLEAN = "BRTEST Clean"
REJECTS = "BRTEST Scorecard Rejects"


class TestSupplierScorecard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		frappe.db.set_single_value("Buying Settings", "po_required", "No")
		ensure_warehouse(config.REJECTED_WAREHOUSE_NAME)
		ensure_supplier(REJECTS)
		cls._receive(CLEAN, accepted=10, rejected=0)
		cls._receive(REJECTS, accepted=4, rejected=6)
		cls.scores = setup_supplier_scorecards([CLEAN, REJECTS])

	@classmethod
	def _receive(cls, supplier, accepted, rejected):
		pr = make_purchase_receipt(supplier, "BRTEST-RM", accepted, 100, warehouse=cls.wh.stores)
		pr.items[0].received_qty = accepted + rejected
		pr.items[0].rejected_qty = rejected
		pr.insert()
		pr.submit()
		return pr

	def test_every_supplier_has_a_scorecard_with_weights_summing_to_100(self):
		self.assertEqual(sum(c["weight"] for c in SCORECARD_CRITERIA), 100)
		for supplier in (CLEAN, REJECTS):
			sc = frappe.get_doc("Supplier Scorecard", supplier)
			self.assertEqual(sc.period, SCORECARD_PERIOD)
			self.assertEqual(
				{c.criteria_name: flt(c.weight) for c in sc.criteria},
				{c["criteria_name"]: c["weight"] for c in SCORECARD_CRITERIA},
			)
			self.assertTrue(
				frappe.db.exists("Supplier Scorecard Period", {"scorecard": supplier, "docstatus": 1})
			)
			self.assertTrue(sc.status)  # a standing is always resolved, also for a perfect 100

	def test_rejecting_supplier_scores_lower(self):
		clean_score, clean_standing = self.scores[CLEAN]
		rejects_score, _standing = self.scores[REJECTS]
		self.assertEqual(clean_score, 100)
		self.assertEqual(clean_standing, "Excellent")
		# quality 40 % x 50 + delivery 100 x 30 + price 100 x 20 = 70
		self.assertAlmostEqual(flt(rejects_score), 70, places=1)
		self.assertLess(flt(rejects_score), flt(clean_score))

	def test_poor_standings_warn_but_do_not_block_pos(self):
		sc = frappe.get_doc("Supplier Scorecard", REJECTS)
		standings = {s.standing_name: s for s in sc.standings}
		for name in ("Poor", "Very Poor"):
			self.assertEqual(standings[name].warn_pos, 1, name)
			self.assertEqual(standings[name].prevent_pos, 0, name)

	def test_setup_is_idempotent(self):
		again = setup_supplier_scorecards([CLEAN, REJECTS])
		self.assertEqual(again, self.scores)
		self.assertEqual(
			frappe.db.count("Supplier Scorecard Period", {"scorecard": REJECTS, "docstatus": 1}), 1
		)

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from horizon_erp.horizon_accounts.report.bank_unmatched_aging.bank_unmatched_aging import (
	bucket_for,
	execute,
)
from horizon_erp.tests.cleanup import purge_test_residue

COMPANY = "Horizon Manufacturing Ltd"
BANK = "GAPTEST Bank"
GL_ACCOUNT_NAME = "GAPTEST Bank Current"
BANK_ACCOUNT_NAME = "GAPTEST Current"


class TestBankUnmatchedAging(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.bank_account = cls._ensure_bank_account()
		cls.old = cls._transaction(add_days(nowdate(), -40), withdrawal=1000, description="GAPTEST old debit")
		cls.new = cls._transaction(add_days(nowdate(), -3), deposit=500, description="GAPTEST new credit")

	@classmethod
	def _ensure_bank_account(cls):
		if not frappe.db.exists("Bank", BANK):
			frappe.get_doc({"doctype": "Bank", "bank_name": BANK}).insert(ignore_permissions=True)
		parent = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_type": "Bank", "is_group": 1}, "name"
		) or frappe.db.get_value("Account", {"company": COMPANY, "root_type": "Asset", "is_group": 1}, "name")
		gl = frappe.db.get_value("Account", {"account_name": GL_ACCOUNT_NAME, "company": COMPANY}, "name")
		if not gl:
			gl = (
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": GL_ACCOUNT_NAME,
						"parent_account": parent,
						"company": COMPANY,
						"account_type": "Bank",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		existing = frappe.db.get_value(
			"Bank Account", {"account_name": BANK_ACCOUNT_NAME, "bank": BANK}, "name"
		)
		if existing:
			return existing
		return (
			frappe.get_doc(
				{
					"doctype": "Bank Account",
					"account_name": BANK_ACCOUNT_NAME,
					"bank": BANK,
					"account": gl,
					"company": COMPANY,
					"is_company_account": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	@classmethod
	def _transaction(cls, date, deposit=0, withdrawal=0, description=""):
		bt = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": date,
				"bank_account": cls.bank_account,
				"company": COMPANY,
				"deposit": deposit,
				"withdrawal": withdrawal,
				"description": description,
				"reference_number": f"GAPTEST-{date}",
			}
		)
		bt.flags.ignore_permissions = True
		bt.insert()
		bt.submit()
		return bt

	def test_buckets(self):
		self.assertEqual(bucket_for(0), "0-7")
		self.assertEqual(bucket_for(7), "0-7")
		self.assertEqual(bucket_for(8), "8-30")
		self.assertEqual(bucket_for(30), "8-30")
		self.assertEqual(bucket_for(31), "31-60")
		self.assertEqual(bucket_for(61), "60+")

	def test_rows_aging_and_summary(self):
		columns, data, _m, chart, summary = execute(
			{"company": COMPANY, "bank_account": self.bank_account, "as_on": nowdate()}
		)
		self.assertEqual(len(columns), 11)
		by_name = {r.bank_transaction: r for r in data}
		self.assertEqual(set(by_name), {self.old.name, self.new.name})
		old = by_name[self.old.name]
		self.assertEqual(old.age_days, 40)
		self.assertEqual(old.bucket, "31-60")
		self.assertEqual(old.flag, 1)
		self.assertAlmostEqual(old.unallocated_amount, 1000)
		new = by_name[self.new.name]
		self.assertEqual(new.age_days, 3)
		self.assertEqual(new.bucket, "0-7")
		self.assertEqual(new.flag, 0)
		self.assertEqual(new.status, "Unreconciled")

		labels = {s["label"]: s["value"] for s in summary}
		self.assertEqual(labels["Unmatched Transactions"], 2)
		self.assertAlmostEqual(labels["Unmatched Value"], 1500)
		self.assertEqual(labels["Older than 30 days"], 1)
		self.assertIn("Bank GL Balance", labels)
		self.assertIn("Statement Closing Balance", labels)

		buckets = dict(zip(chart["data"]["labels"], chart["data"]["datasets"][0]["values"], strict=True))
		self.assertAlmostEqual(buckets["31-60"], 1000)
		self.assertAlmostEqual(buckets["0-7"], 500)

	def test_as_on_before_transaction_excludes_it(self):
		_c, data, _m, _chart, _s = execute(
			{"company": COMPANY, "bank_account": self.bank_account, "as_on": add_days(nowdate(), -10)}
		)
		self.assertEqual([r.bank_transaction for r in data], [self.old.name])
		self.assertEqual(data[0].age_days, 30)
		self.assertEqual(data[0].bucket, "8-30")

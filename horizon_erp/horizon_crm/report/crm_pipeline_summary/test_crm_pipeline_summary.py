# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""CRM Pipeline Summary report. Fixture prefix ``CRMRPT``.

Run:  bench --site horizon.local run-tests --app horizon_erp --skip-test-records \
	--module horizon_erp.horizon_crm.report.crm_pipeline_summary.test_crm_pipeline_summary
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from horizon_erp.horizon_core.tests.fixtures import (
	COMPANY,
	SELLING_PRICE_LIST,
	ensure_item,
	ensure_item_price,
	setup_common,
	with_dimensions,
)
from horizon_erp.horizon_crm.report.crm_pipeline_summary.crm_pipeline_summary import (
	OLD_LEAD_DAYS,
	execute,
	get_stage,
)
from horizon_erp.horizon_setup.demo_data import make_gstin
from horizon_erp.tests.cleanup import purge_test_residue

PREFIX = "CRMRPT"
ITEM_GROUP = "CRMRPT Equipment"
ITEM = "CRMRPT-EQUIP"
PRICE = 100000
PREMIUM = "Premium"
LOST_REASON = "CRMRPT Price too high"
LOST_DETAIL = "CRMRPT budget cut for this year"
GSTIN_MH = make_gstin("27", "AAACR0002T")  # Maharashtra, checksum-valid
SALES_MANAGER = "brtest-sm@horizon.local"
COLD_LEAD_AGE = OLD_LEAD_DAYS + 6


def ensure_master(doctype, name, **values):
	if not frappe.db.exists(doctype, name):
		doc = frappe.get_doc({"doctype": doctype, **values})
		doc.flags.ignore_permissions = True
		doc.insert()
	return name


def make_lead(company_name, first_name, source):
	lead = frappe.get_doc(
		{
			"doctype": "Lead",
			"first_name": first_name,
			"company_name": company_name,
			"email_id": f"{frappe.scrub(first_name)}@crmrpt.example.com",
			"source": source,
			"territory": "West",
			"lead_owner": SALES_MANAGER,
			"company": COMPANY,
		}
	)
	lead.insert()
	return lead


def make_opportunity(lead, **details):
	opp = frappe.get_doc(
		{
			"doctype": "Opportunity",
			"opportunity_from": "Lead",
			"party_name": lead,
			"company": COMPANY,
			"transaction_date": nowdate(),
			"items": [{"item_code": ITEM, "qty": 1, "rate": PRICE}],
			**details,
		}
	)
	opp.insert()
	return opp


def qualified_details():
	return {
		"customer_group": PREMIUM,
		"territory": "West",
		"horizon_gst_category": "Registered Regular",
		"horizon_gstin": GSTIN_MH,
		"horizon_billing_address_line1": "CRMRPT Plot 7, MIDC Chakan",
		"city": "Pune",
		"state": "Maharashtra",
		"country": "India",
		"horizon_billing_pincode": "410501",
		"horizon_credit_limit": 2500000,
		"horizon_payment_terms": "Net 30",
	}


def quotation_from_opportunity(opp_name):
	from erpnext.crm.doctype.opportunity.opportunity import make_quotation

	qtn = make_quotation(opp_name)
	qtn.transaction_date = nowdate()
	qtn.selling_price_list = SELLING_PRICE_LIST
	return with_dimensions(qtn)


def sales_order_from_quotation(quotation, warehouse):
	from erpnext.selling.doctype.quotation.quotation import make_sales_order

	so = make_sales_order(quotation)
	so.delivery_date = add_days(nowdate(), 7)
	for row in so.items:
		row.delivery_date = so.delivery_date
		row.warehouse = warehouse
	return with_dimensions(so)


class TestCRMPipelineSummary(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wh = setup_common()
		ensure_master(
			"Customer Group",
			PREMIUM,
			customer_group_name=PREMIUM,
			parent_customer_group="All Customer Groups",
		)
		ensure_master("Territory", "West", territory_name="West", parent_territory="All Territories")
		ensure_master(
			"Payment Terms Template",
			"Net 30",
			template_name="Net 30",
			terms=[
				{"invoice_portion": 100, "due_date_based_on": "Day(s) after invoice date", "credit_days": 30}
			],
		)
		for source in ("Campaign", "Exhibition"):
			ensure_master("Lead Source", source, source_name=source)
		ensure_master("Opportunity Lost Reason", LOST_REASON, lost_reason=LOST_REASON)
		ensure_master(
			"Item Group", ITEM_GROUP, item_group_name=ITEM_GROUP, parent_item_group="All Item Groups"
		)
		ensure_item(ITEM, item_group=ITEM_GROUP)
		ensure_item_price(ITEM, PRICE)

		frappe.set_user(SALES_MANAGER)
		# 1. a cold lead, 20 days old, nothing happened
		cls.cold = make_lead("CRMRPT Cold Storage Ltd", "CRMRPT Cold", "Campaign")
		frappe.db.set_value(
			"Lead",
			cls.cold.name,
			"creation",
			add_to_date(now_datetime(), days=-COLD_LEAD_AGE),
			update_modified=False,
		)
		# 2. the full chain: Lead -> qualified Opportunity -> Quotation (Customer created, ADR-17) -> SO
		cls.won = make_lead("CRMRPT Pumps Pvt Ltd", "CRMRPT Karthik", "Exhibition")
		cls.won_opp = make_opportunity(cls.won.name, **qualified_details())
		cls.qtn = quotation_from_opportunity(cls.won_opp.name)
		cls.qtn.insert()
		cls.qtn.submit()
		cls.customer = frappe.db.get_value("Customer", {"lead_name": cls.won.name}, "name")
		cls.so = sales_order_from_quotation(cls.qtn.name, cls.wh.fg)
		cls.so.insert()
		cls.so.submit()
		# 3. a lead whose Opportunity was lost
		cls.lost = make_lead("CRMRPT Lost Cause Ltd", "CRMRPT Lost", "Exhibition")
		cls.lost_opp = make_opportunity(cls.lost.name)
		cls.lost_opp.declare_enquiry_lost([{"lost_reason": LOST_REASON}], [], LOST_DETAIL)
		cls.lost_opp.reload()
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.set_user(SALES_MANAGER)

	def tearDown(self):
		frappe.set_user("Administrator")

	@staticmethod
	def filters(**overrides):
		filters = {
			"company": COMPANY,
			"from_date": add_days(nowdate(), -30),
			"to_date": nowdate(),
			"lead_owner": SALES_MANAGER,
		}
		filters.update(overrides)
		return filters

	def run_report(self, **overrides):
		columns, data, message, chart, summary = execute(self.filters(**overrides))
		return columns, data, message, chart, {s["label"]: s["value"] for s in summary}

	def rows_by_lead(self, data):
		return {r.lead: r for r in data if not r.get("is_group")}

	# --- fixture sanity -------------------------------------------------------------------------
	def test_fixture_chain(self):
		self.assertTrue(self.customer)
		self.assertEqual((self.qtn.quotation_to, self.qtn.party_name), ("Customer", self.customer))
		self.assertEqual(self.qtn.opportunity, self.won_opp.name)
		self.assertEqual(self.so.docstatus, 1)
		self.assertEqual(self.so.items[0].prevdoc_docname, self.qtn.name)
		self.assertEqual(self.lost_opp.status, "Lost")
		self.assertEqual(frappe.db.get_value("Lead", self.won.name, "status"), "Converted")

	# --- rows ---------------------------------------------------------------------------------------
	def test_one_row_per_lead_with_stage(self):
		columns, data, message, chart, summary = self.run_report()
		self.assertEqual(len(columns), 20)
		self.assertIn("ADR-17", message)
		rows = self.rows_by_lead(data)
		self.assertEqual(set(rows), {self.cold.name, self.won.name, self.lost.name})
		self.assertEqual(
			[r.lead for r in data], [self.lost.name, self.won.name, self.cold.name]
		)  # newest first

		cold = rows[self.cold.name]
		self.assertEqual(cold.stage_reached, "Lead")
		self.assertEqual(cold.lead_name, "CRMRPT Cold Storage Ltd")
		self.assertEqual((cold.source, cold.territory, cold.lead_owner), ("Campaign", "West", SALES_MANAGER))
		self.assertEqual(cold.days, COLD_LEAD_AGE)
		self.assertFalse(cold.opportunity or cold.quotation or cold.sales_order or cold.customer)

		won = rows[self.won.name]
		self.assertEqual(won.stage_reached, "Ordered")
		self.assertEqual(won.lead_status, "Converted")
		self.assertEqual(won.opportunity, self.won_opp.name)
		self.assertEqual(
			won.opportunity_status, frappe.db.get_value("Opportunity", self.won_opp.name, "status")
		)
		self.assertGreater(won.opportunity_amount, 0)
		self.assertEqual(won.quotation, self.qtn.name)
		self.assertEqual(won.quotation_status, "Ordered")
		self.assertAlmostEqual(won.quotation_amount, self.qtn.grand_total, places=2)
		self.assertEqual(won.sales_order, self.so.name)
		self.assertAlmostEqual(won.sales_order_amount, self.so.grand_total, places=2)
		self.assertEqual((won.customer, won.customer_group), (self.customer, PREMIUM))
		self.assertEqual(won.days, 0)  # Customer created today from today's Lead
		self.assertIsNone(won.lost_reason)

		lost = rows[self.lost.name]
		self.assertEqual(lost.stage_reached, "Lost")
		self.assertEqual((lost.opportunity, lost.opportunity_status), (self.lost_opp.name, "Lost"))
		self.assertEqual(lost.lost_reason, f"{LOST_REASON}, {LOST_DETAIL}")
		self.assertFalse(lost.quotation or lost.sales_order or lost.customer)

	def test_stage_logic(self):
		def stage(**kw):
			row = frappe._dict(kw)
			row.is_lost = kw.get("is_lost", False)
			return get_stage(row)

		self.assertEqual(stage(), "Lead")
		self.assertEqual(stage(opportunity="O"), "Opportunity")
		self.assertEqual(stage(opportunity="O", customer="C"), "Customer")
		self.assertEqual(stage(opportunity="O", customer="C", quotation="Q"), "Quoted")
		self.assertEqual(stage(opportunity="O", customer="C", quotation="Q", sales_order="S"), "Ordered")
		self.assertEqual(stage(opportunity="O", quotation="Q", is_lost=True), "Lost")

	# --- summary and chart ---------------------------------------------------------------------------
	def test_summary_counts_and_conversion(self):
		_c, _d, _m, chart, summary = self.run_report()
		self.assertEqual(summary["Leads"], 3)
		self.assertEqual(summary["Qualified (Opportunity)"], 2)
		self.assertEqual(summary["Quoted"], 1)
		self.assertEqual(summary["Ordered"], 1)
		self.assertEqual(summary["Customers Created"], 1)
		self.assertAlmostEqual(summary["Lead to Customer %"], 33.3, places=1)
		self.assertAlmostEqual(summary["Quote to Order %"], 100.0, places=1)
		self.assertEqual(summary["Avg Days Lead to Customer"], 0)
		self.assertEqual(summary[f"Open Leads Older Than {OLD_LEAD_DAYS} Days"], 1)
		self.assertEqual(summary["Lost Opportunities"], 1)
		self.assertEqual(chart["type"], "bar")
		self.assertEqual(chart["data"]["labels"], ["Leads", "Qualified", "Quoted", "Ordered", "Customer"])
		self.assertEqual(chart["data"]["datasets"][0]["values"], [3, 2, 1, 1, 1])

	def test_empty_period_has_no_division_by_zero(self):
		_c, data, _m, chart, summary = self.run_report(lead_owner="nobody@crmrpt.example.com")
		self.assertEqual(data, [])
		self.assertEqual(summary["Leads"], 0)
		self.assertEqual((summary["Lead to Customer %"], summary["Quote to Order %"]), (0, 0))
		self.assertEqual(chart["data"]["datasets"][0]["values"], [0, 0, 0, 0, 0])

	# --- grouping --------------------------------------------------------------------------------------
	def test_group_by_source(self):
		_c, data, _m, _chart, _s = self.run_report(group_by="Source")
		headers = {r.lead: r for r in data if r.get("is_group")}
		self.assertEqual(list(headers), ["Campaign", "Exhibition"])
		campaign, exhibition = headers["Campaign"], headers["Exhibition"]
		self.assertEqual((campaign.leads, campaign.qualified, campaign.customers), (1, 0, 0))
		self.assertEqual(campaign.conversion_pct, 0)
		self.assertEqual(
			(
				exhibition.leads,
				exhibition.qualified,
				exhibition.quoted,
				exhibition.ordered,
				exhibition.customers,
			),
			(2, 2, 1, 1, 1),
		)
		self.assertEqual(exhibition.conversion_pct, 50.0)
		self.assertEqual(exhibition.lead_name, "2 leads, 2 qualified, 1 quoted, 1 ordered, 1 customers")
		self.assertEqual(exhibition.stage_reached, "50.0% converted")
		self.assertAlmostEqual(exhibition.sales_order_amount, self.so.grand_total, places=2)
		self.assertTrue(all(r.indent == 0 for r in headers.values()))
		# every lead row sits under its own group, indented
		sequence = [(r.lead, r.indent, bool(r.get("is_group"))) for r in data]
		self.assertEqual(
			sequence,
			[
				("Campaign", 0, True),
				(self.cold.name, 1, False),
				("Exhibition", 0, True),
				(self.lost.name, 1, False),
				(self.won.name, 1, False),
			],
		)

	def test_group_by_month_and_owner(self):
		_c, data, _m, _chart, _s = self.run_report(group_by="Lead Owner")
		headers = [r for r in data if r.get("is_group")]
		self.assertEqual([(h.lead, h.leads) for h in headers], [(SALES_MANAGER, 3)])

		_c, data, _m, _chart, _s = self.run_report(group_by="Month")
		headers = [r for r in data if r.get("is_group")]
		self.assertEqual(sum(h.leads for h in headers), 3)
		self.assertTrue(headers[0].lead)  # "Oct 2026" style label
		self.assertEqual(data[0].get("is_group"), 1)

	# --- filters ---------------------------------------------------------------------------------------
	def test_filters(self):
		_c, data, _m, _chart, summary = self.run_report(source="Campaign")
		self.assertEqual(list(self.rows_by_lead(data)), [self.cold.name])
		self.assertEqual(summary["Leads"], 1)

		_c, data, _m, _chart, _s = self.run_report(status=["Converted"])
		self.assertEqual(list(self.rows_by_lead(data)), [self.won.name])
		_c, data, _m, _chart, _s = self.run_report(status=json.dumps(["Converted", "Lead"]))
		self.assertEqual(set(self.rows_by_lead(data)), {self.won.name, self.cold.name})

		# the period is the Lead creation date: the 20-day-old cold lead drops out of a 10-day window
		_c, data, _m, _chart, summary = self.run_report(from_date=add_days(nowdate(), -10))
		self.assertEqual(set(self.rows_by_lead(data)), {self.won.name, self.lost.name})
		self.assertEqual(summary[f"Open Leads Older Than {OLD_LEAD_DAYS} Days"], 0)

		_c, data, _m, _chart, _s = self.run_report(territory="North")
		self.assertEqual(data, [])

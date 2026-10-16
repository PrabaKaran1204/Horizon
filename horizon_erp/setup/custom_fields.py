# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Custom Fields added to standard Frappe / ERPNext DocTypes.

Fields are created in code (not exported as fixtures) so that ``after_install`` and
``after_migrate`` keep them in sync on every bench. Each DocType gets a "Horizon" Tab Break
(tabbed forms) or Section Break (plain forms / child tables) appended after the last standard
field, so no standard field is pulled into our section.

Standard fields deliberately NOT duplicated:
- Company.default_selling_terms already exists -> no terms_and_conditions_text.
- Task.is_milestone already exists -> only billing_percent / milestone_invoice added.
- Sales Order Item.delivery_date already exists -> expected_delivery_date only on Quotation Item.
- Item.safety_stock / lead_time_days exist -> safety_stock_factor is a multiplier on top.
- Supplier.on_hold / hold_type (standard supplier block) exist -> is_blacklisted is a separate,
  override-able flag driven by Supplier Exception Log.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _tab(fieldname, insert_after):
	return {
		"fieldname": fieldname,
		"fieldtype": "Tab Break",
		"label": "Horizon",
		"insert_after": insert_after,
	}


def _section(fieldname, insert_after):
	return {
		"fieldname": fieldname,
		"fieldtype": "Section Break",
		"label": "Horizon",
		"insert_after": insert_after,
		"collapsible": 0,
	}


def _sales_item_fields(with_expected_delivery_date):
	fields = [
		{
			"fieldname": "available_qty",
			"fieldtype": "Float",
			"label": "Available Qty",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "horizon_section",
		},
		{
			"fieldname": "mfg_lead_days",
			"fieldtype": "Int",
			"label": "Mfg Lead Days",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "available_qty",
		},
	]
	last = "mfg_lead_days"
	if with_expected_delivery_date:
		fields.append(
			{
				"fieldname": "expected_delivery_date",
				"fieldtype": "Date",
				"label": "Expected Delivery Date",
				"insert_after": last,
			}
		)
		last = "expected_delivery_date"
	fields += [
		{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": last},
		{
			"fieldname": "rule_rate",
			"fieldtype": "Currency",
			"label": "Rule Rate",
			"options": "currency",
			"read_only": 1,
			"no_copy": 1,
			"description": "rate after pricing rules",
			"insert_after": "horizon_cb_1",
		},
		{
			"fieldname": "discount_over_rule_pct",
			"fieldtype": "Percent",
			"label": "Discount Over Rule %",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "rule_rate",
		},
	]
	return fields


def _sales_parent_fields(insert_after):
	return [
		_tab("horizon_tab", insert_after),
		{
			"fieldname": "needs_discount_approval",
			"fieldtype": "Check",
			"label": "Needs Discount Approval",
			"read_only": 1,
			"allow_on_submit": 1,
			"no_copy": 1,
			"insert_after": "horizon_tab",
		},
		{
			"fieldname": "discount_reason",
			"fieldtype": "Small Text",
			"label": "Discount Reason",
			"depends_on": "needs_discount_approval",
			"mandatory_depends_on": "needs_discount_approval",
			"insert_after": "needs_discount_approval",
		},
	]


def get_custom_fields():
	"""Return ``{doctype: [field_dict, ...]}`` for ``create_custom_fields``."""
	return {
		"Item": [
			_tab("horizon_tab", "total_projected_qty"),
			{
				"fieldname": "criticality",
				"fieldtype": "Select",
				"label": "Criticality",
				"options": "A\nB\nC",
				"default": "B",
				"in_standard_filter": 1,
				"insert_after": "horizon_tab",
			},
			{
				"fieldname": "demand_pattern",
				"fieldtype": "Select",
				"label": "Demand Pattern",
				"options": "Stable\nSeasonal Q4",
				"default": "Stable",
				"insert_after": "criticality",
			},
			{
				"fieldname": "safety_stock_factor",
				"fieldtype": "Float",
				"label": "Safety Stock Factor",
				"read_only": 1,
				"description": "derived from criticality",
				"insert_after": "demand_pattern",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "safety_stock_factor"},
			{
				"fieldname": "machine_hours_per_unit",
				"fieldtype": "Float",
				"label": "Machine Hours per Unit",
				"insert_after": "horizon_cb_1",
			},
			{
				"fieldname": "default_line",
				"fieldtype": "Select",
				"label": "Default Line",
				"options": "\nLine A\nLine B\nAny",
				"insert_after": "machine_hours_per_unit",
			},
		],
		"Supplier": [
			_tab("horizon_tab", "column_break_1mqv"),
			{
				"fieldname": "is_blacklisted",
				"fieldtype": "Check",
				"label": "Is Blacklisted",
				"in_standard_filter": 1,
				"insert_after": "horizon_tab",
			},
			{
				"fieldname": "blacklisted_on",
				"fieldtype": "Date",
				"label": "Blacklisted On",
				"depends_on": "is_blacklisted",
				"insert_after": "is_blacklisted",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "blacklisted_on"},
			{
				"fieldname": "blacklist_reason",
				"fieldtype": "Small Text",
				"label": "Blacklist Reason",
				"depends_on": "is_blacklisted",
				"mandatory_depends_on": "is_blacklisted",
				"insert_after": "horizon_cb_1",
			},
		],
		"Purchase Order": [
			_tab("horizon_tab", "connections_tab"),
			{
				"fieldname": "blacklist_override",
				"fieldtype": "Check",
				"label": "Blacklist Override",
				"no_copy": 1,
				"insert_after": "horizon_tab",
			},
			{
				"fieldname": "override_reason",
				"fieldtype": "Small Text",
				"label": "Override Reason",
				"depends_on": "blacklist_override",
				"mandatory_depends_on": "blacklist_override",
				"no_copy": 1,
				"insert_after": "blacklist_override",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "override_reason"},
			{
				"fieldname": "approval_level_required",
				"fieldtype": "Select",
				"label": "Approval Level Required",
				"options": "\nLevel 1\nLevel 2\nLevel 3",
				"read_only": 1,
				"allow_on_submit": 1,
				"no_copy": 1,
				"in_standard_filter": 1,
				"insert_after": "horizon_cb_1",
			},
			{
				"fieldname": "pending_since",
				"fieldtype": "Datetime",
				"label": "Pending Since",
				"read_only": 1,
				"allow_on_submit": 1,
				"hidden": 1,
				"no_copy": 1,
				"insert_after": "approval_level_required",
			},
		],
		"Quotation Item": [
			_section("horizon_section", "page_break"),
			*_sales_item_fields(with_expected_delivery_date=True),
		],
		"Sales Order Item": [
			_section("horizon_section", "project"),
			# expected_delivery_date intentionally omitted: standard delivery_date exists
			*_sales_item_fields(with_expected_delivery_date=False),
		],
		"Quotation": _sales_parent_fields("connections_tab"),
		"Sales Order": _sales_parent_fields("connections_tab"),
		"Delivery Note": [
			_tab("horizon_tab", "connections_tab"),
			{
				"fieldname": "shipment_decision",
				"fieldtype": "Link",
				"label": "Shipment Decision",
				"options": "Shipment Decision",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "horizon_tab",
			},
			{
				"fieldname": "deviation_notes",
				"fieldtype": "Small Text",
				"label": "Deviation Notes",
				"no_copy": 1,
				"insert_after": "shipment_decision",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "deviation_notes"},
			{
				"fieldname": "received_by",
				"fieldtype": "Data",
				"label": "Received By",
				"no_copy": 1,
				"insert_after": "horizon_cb_1",
			},
			{
				"fieldname": "customer_signature",
				"fieldtype": "Signature",
				"label": "Customer Signature",
				"no_copy": 1,
				"insert_after": "received_by",
			},
		],
		"Quality Inspection": [
			_section("horizon_section", "letter_head"),
			{
				"fieldname": "qc_result",
				"fieldtype": "Select",
				"label": "QC Result",
				"options": "\nPass\nFail\nConditional Pass\nRework",
				"in_standard_filter": 1,
				"insert_after": "horizon_section",
			},
			{
				"fieldname": "rejection_reason",
				"fieldtype": "Small Text",
				"label": "Rejection Reason",
				"depends_on": "eval:['Fail', 'Rework', 'Conditional Pass'].includes(doc.qc_result)",
				"insert_after": "qc_result",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "rejection_reason"},
			{
				"fieldname": "evidence_required",
				"fieldtype": "Check",
				"label": "Evidence Required",
				"insert_after": "horizon_cb_1",
			},
			{
				"fieldname": "rework_work_order",
				"fieldtype": "Link",
				"label": "Rework Work Order",
				"options": "Work Order",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "evidence_required",
			},
		],
		"Work Order": [
			_tab("horizon_tab", "connections_tab"),
			{
				"fieldname": "required_machine_hours",
				"fieldtype": "Float",
				"label": "Required Machine Hours",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "horizon_tab",
			},
			{
				"fieldname": "rework_of",
				"fieldtype": "Link",
				"label": "Rework Of",
				"options": "Work Order",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "required_machine_hours",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "rework_of"},
			{
				"fieldname": "capacity_override",
				"fieldtype": "Check",
				"label": "Capacity Override",
				"no_copy": 1,
				"insert_after": "horizon_cb_1",
			},
			{
				"fieldname": "capacity_override_reason",
				"fieldtype": "Small Text",
				"label": "Capacity Override Reason",
				"depends_on": "capacity_override",
				"mandatory_depends_on": "capacity_override",
				"no_copy": 1,
				"insert_after": "capacity_override",
			},
		],
		"Project": [
			_section("horizon_section", "message"),
			{
				"fieldname": "overhead_percent",
				"fieldtype": "Percent",
				"label": "Overhead %",
				"default": "15",
				"insert_after": "horizon_section",
			},
			{
				"fieldname": "overhead_amount",
				"fieldtype": "Currency",
				"label": "Overhead Amount",
				"options": "Company:company:default_currency",
				"read_only": 1,
				"insert_after": "overhead_percent",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "overhead_amount"},
			{
				"fieldname": "budgeted_margin_percent",
				"fieldtype": "Percent",
				"label": "Budgeted Margin %",
				"insert_after": "horizon_cb_1",
			},
		],
		"Task": [
			# is_milestone is a standard Task field; only billing fields are added
			_section("horizon_section", "template_task"),
			{
				"fieldname": "billing_percent",
				"fieldtype": "Percent",
				"label": "Billing %",
				"depends_on": "is_milestone",
				"insert_after": "horizon_section",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "billing_percent"},
			{
				"fieldname": "milestone_invoice",
				"fieldtype": "Link",
				"label": "Milestone Invoice",
				"options": "Sales Invoice",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "horizon_cb_1",
			},
		],
		"Timesheet Detail": [
			_section("horizon_section", "costing_amount"),
			{
				"fieldname": "is_overtime",
				"fieldtype": "Check",
				"label": "Is Overtime",
				"read_only": 1,
				"no_copy": 1,
				"insert_after": "horizon_section",
			},
		],
		"Bank Account": [
			_section("horizon_section", "mask"),
			{
				"fieldname": "reconciliation_frequency",
				"fieldtype": "Select",
				"label": "Reconciliation Frequency",
				"options": "Daily\nWeekly\nMonthly",
				"depends_on": "is_company_account",
				"insert_after": "horizon_section",
			},
		],
		"BOM": [
			_tab("horizon_tab", "connections_tab"),
			{
				"fieldname": "revision_reason",
				"fieldtype": "Select",
				"label": "Revision Reason",
				"options": "\nDesign Change\nCost Update\nSupplier Change\nQuality Issue",
				"insert_after": "horizon_tab",
			},
			{"fieldname": "horizon_cb_1", "fieldtype": "Column Break", "insert_after": "revision_reason"},
			{
				"fieldname": "approved_by",
				"fieldtype": "Link",
				"label": "Approved By",
				"options": "User",
				"insert_after": "horizon_cb_1",
			},
		],
		# Company: default_selling_terms / default_buying_terms already exist -> nothing added
	}


def setup_custom_fields():
	"""Create or update all Horizon custom fields. Idempotent (``update=True``)."""
	create_custom_fields(get_custom_fields())

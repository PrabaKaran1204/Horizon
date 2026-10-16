// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Approval Audit Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{
			fieldname: "state",
			label: __("Workflow State"),
			fieldtype: "Link",
			options: "Workflow State",
		},
		{
			fieldname: "only_overrides",
			label: __("Only Blacklist Overrides"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (
			column.fieldname === "hours_in_previous_state" &&
			flt(data.hours_in_previous_state) > 24
		) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (
			column.fieldname === "workflow_state" &&
			data.workflow_state &&
			data.workflow_state.startsWith("Pending")
		) {
			value = `<span style="color:orange;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "blacklist_override" && cint(data.blacklist_override)) {
			value = `<span style="color:red;font-weight:600">${__("Yes")}</span>`;
		}
		return value;
	},
};

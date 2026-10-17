// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Project Profitability"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Open", "Completed", "Cancelled"],
			default: "Open",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (["margin", "margin_pct"].includes(column.fieldname) && cint(data.margin_alert)) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "schedule_variance" && cint(data.schedule_alert)) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "hours_variance_pct" && flt(data.hours_variance_pct) > 10) {
			value = `<span style="color:orange;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

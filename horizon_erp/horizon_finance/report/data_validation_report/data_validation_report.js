// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Data Validation Report"] = {
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
			fieldname: "severity",
			label: __("Severity"),
			fieldtype: "Select",
			options: ["", "High", "Medium", "Low"],
		},
		{
			fieldname: "entity_type",
			label: __("Entity Type"),
			fieldtype: "Select",
			options: [
				"",
				"Customer",
				"Supplier",
				"Item",
				"Purchase Invoice",
				"Sales Invoice",
				"Employee",
			],
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data || column.fieldname !== "severity") return value;
		const color =
			{ High: "red", Medium: "orange", Low: "#5e64ff" }[data.severity] || "inherit";
		return `<span style="color:${color};font-weight:600">${value}</span>`;
	},
};

// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Quality Metrics"] = {
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
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -90),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.is_header) {
			value = `<span style="font-weight:700">${value}</span>`;
		}
		if (column.fieldname === "hours" && cint(data.is_breach)) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "pct" && data.is_header && data.label === __("Rework cost %")) {
			const colour = flt(data.pct) > 5 ? "red" : flt(data.pct) > 2 ? "orange" : "green";
			value = `<span style="color:${colour};font-weight:600">${value}</span>`;
		}
		return value;
	},
};

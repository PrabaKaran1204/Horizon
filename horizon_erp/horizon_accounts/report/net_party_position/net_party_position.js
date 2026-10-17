// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Net Party Position"] = {
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
			fieldname: "as_on",
			label: __("As On"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{ fieldname: "party", label: __("Party (name)"), fieldtype: "Data" },
		{
			fieldname: "party_link_only",
			label: __("Party Links Only"),
			fieldtype: "Check",
			default: 1,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "net" || column.fieldname === "direction") {
			const color = flt(data.net) < 0 ? "red" : "green";
			value = `<span style="color:${color};font-weight:600">${value}</span>`;
		}
		return value;
	},
};

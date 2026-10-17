// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Forecast vs Actual Demand"] = {
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
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{ fieldname: "item", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "months_back", label: __("Months Back"), fieldtype: "Int", default: 12 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "variance_pct") {
			if (flt(data.variance_pct) > 50)
				value = `<span style="color:red;font-weight:600">${value}</span>`;
			else if (flt(data.variance_pct) > 20)
				value = `<span style="color:orange;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "demand_pattern" && data.demand_pattern === "Seasonal Q4") {
			value = `<span style="color:#5e64ff;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

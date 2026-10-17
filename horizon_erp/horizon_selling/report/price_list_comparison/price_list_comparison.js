// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Price List Comparison"] = {
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
		{
			fieldname: "price_list",
			label: __("Base Price List"),
			fieldtype: "Link",
			options: "Price List",
			default: "Standard Selling",
			get_query: () => ({ filters: { selling: 1 } }),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data || column.fieldtype !== "Currency") return value;
		const base = flt(data.base_rate);
		const rate = flt(data[column.fieldname]);
		if (base && rate && column.fieldname !== "standard_selling" && rate < base) {
			const pct = ((base - rate) / base) * 100;
			value = `<span style="color:green;font-weight:600" title="${__(
				"Discount"
			)} ${pct.toFixed(1)}%">${value}</span>`;
		} else if (base && rate > base) {
			value = `<span style="color:orange" title="${__("Above list rate")}">${value}</span>`;
		}
		return value;
	},
};

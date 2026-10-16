// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Asset Register with Maintenance"] = {
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
			fieldname: "asset_category",
			label: __("Asset Category"),
			fieldtype: "Link",
			options: "Asset Category",
		},
		{ fieldname: "location", label: __("Location"), fieldtype: "Link", options: "Location" },
		{
			fieldname: "include_disposed",
			label: __("Include Scrapped / Sold"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "replacement_candidate" && cint(data.replacement_candidate)) {
			value = `<span style="color:red;font-weight:600">${__("Yes")}</span>`;
		}
		if (column.fieldname === "maintenance_pct" && flt(data.maintenance_pct) > 20) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (
			column.fieldname === "nbv" &&
			flt(data.gross_cost) &&
			flt(data.nbv) < flt(data.gross_cost) * 0.05
		) {
			value = `<span style="color:orange;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

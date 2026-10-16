// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Supplier Quality Scorecard"] = {
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
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[1],
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "score") {
			if (flt(data.score) < 60)
				value = `<span style="color:red;font-weight:600">${value}</span>`;
			else if (flt(data.score) < 80)
				value = `<span style="color:orange;font-weight:600">${value}</span>`;
			else value = `<span style="color:green;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "is_blacklisted" && cint(data.is_blacklisted)) {
			value = `<span style="color:red;font-weight:600">${__("Yes")}</span>`;
		}
		if (column.fieldname === "rejection_pct" && flt(data.rejection_pct) > 5) {
			value = `<span style="color:red">${value}</span>`;
		}
		return value;
	},
};

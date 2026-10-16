// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Quality vs Deadline Conflicts"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{ fieldname: "days_ahead", label: __("Days Ahead"), fieldtype: "Int", default: 7 },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{
			fieldname: "from_date",
			label: __("Cost Period From"),
			fieldtype: "Date",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[1],
		},
		{
			fieldname: "to_date",
			label: __("Cost Period To"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "status") {
			if (data.status === "Conflict - Undecided")
				value = `<span style="color:red;font-weight:600">${value}</span>`;
			else if (data.status && data.status.startsWith("Decided"))
				value = `<span style="color:orange;font-weight:600">${value}</span>`;
			else value = `<span style="color:green">${value}</span>`;
		}
		if (column.fieldname === "days_to_delivery" && cint(data.days_to_delivery) < 0) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (
			(column.fieldname === "low_audits" || column.fieldname === "qi_rejected") &&
			cint(data[column.fieldname]) > 0
		) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

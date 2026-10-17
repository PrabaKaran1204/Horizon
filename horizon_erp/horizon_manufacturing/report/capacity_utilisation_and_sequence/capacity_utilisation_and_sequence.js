// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Capacity Utilisation and Sequence"] = {
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
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), 14),
			reqd: 1,
		},
		{
			fieldname: "workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "utilisation_pct") {
			const util = flt(data.utilisation_pct);
			if (util > 100) value = `<span style="color:red;font-weight:600">${value}</span>`;
			else if (util > 85)
				value = `<span style="color:orange;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "free_hours" && flt(data.free_hours) < 0) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

const HORIZON_DAYS = 7;

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
			on_change() {
				// keep the horizon ahead of the day being looked at
				const from_date = frappe.query_report.get_filter_value("from_date");
				const to_date = frappe.query_report.get_filter_value("to_date");
				if (from_date && (!to_date || to_date < from_date)) {
					frappe.query_report.set_filter_value(
						"to_date",
						frappe.datetime.add_days(from_date, HORIZON_DAYS),
					);
				}
				frappe.query_report.refresh();
			},
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), HORIZON_DAYS),
			reqd: 1,
		},
		{
			fieldname: "workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{
			fieldname: "only_today",
			label: __("Only today"),
			fieldtype: "Check",
			default: 0,
			description: __("Show only the From Date rows in the table"),
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

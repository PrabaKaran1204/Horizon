// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Order Status Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "status",
			label: __("SO Status"),
			fieldtype: "Select",
			options: [
				"",
				"Draft",
				"On Hold",
				"To Deliver and Bill",
				"To Bill",
				"To Deliver",
				"Completed",
				"Cancelled",
				"Closed",
			],
		},
		{ fieldname: "only_pending", label: __("Only Pending"), fieldtype: "Check", default: 0 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "days_overdue" && cint(data.days_overdue) > 5) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "status") {
			if (data.status && data.status.startsWith("Overdue")) {
				value = `<span style="color:red;font-weight:600">${value}</span>`;
			} else if (data.status === "Partial") {
				value = `<span style="color:orange;font-weight:600">${value}</span>`;
			} else if (data.status === "Fully Delivered") {
				value = `<span style="color:green">${value}</span>`;
			}
		}
		return value;
	},
};

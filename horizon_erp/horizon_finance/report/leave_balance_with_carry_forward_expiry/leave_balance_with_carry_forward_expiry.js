// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Leave Balance with Carry-forward Expiry"] = {
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
			reqd: 1,
		},
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{
			fieldname: "leave_type",
			label: __("Leave Type"),
			fieldtype: "Link",
			options: "Leave Type",
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "days_to_expiry" && data.days_to_expiry !== null) {
			const days = cint(data.days_to_expiry);
			if (days < 0) value = `<span style="color:#8d99a6">${__("Expired")}</span>`;
			else if (days <= 30 && flt(data.carry_forwarded) > 0)
				value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "available" && flt(data.available) < 0) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

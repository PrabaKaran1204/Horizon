// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Audit Findings Dashboard"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -30),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{ fieldname: "inspector", label: __("Inspector"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "min_score", label: __("Minimum Score"), fieldtype: "Int" },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "audit_score") {
			const score = cint(data.audit_score);
			if (score < 70) value = `<span style="color:red;font-weight:600">${value}</span>`;
			else if (score < 85)
				value = `<span style="color:orange;font-weight:600">${value}</span>`;
			else value = `<span style="color:green;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "escalated" && cint(data.escalated)) {
			value = `<span style="color:red;font-weight:600">${__("Yes")}</span>`;
		}
		if (
			column.fieldname === "ca_status" &&
			data.corrective_action &&
			data.ca_status !== "Completed"
		) {
			value = `<span style="color:orange;font-weight:600">${value || __("Open")}</span>`;
		}
		return value;
	},
};

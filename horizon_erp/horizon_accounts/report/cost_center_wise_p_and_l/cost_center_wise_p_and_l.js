// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Cost Center Wise P and L"] = {
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
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today()),
			on_change() {
				const fy = frappe.query_report.get_filter_value("fiscal_year");
				if (!fy) return;
				frappe.model.with_doc("Fiscal Year", fy, () => {
					const doc = frappe.model.get_doc("Fiscal Year", fy);
					frappe.query_report.set_filter_value("from_date", doc.year_start_date);
					const today = frappe.datetime.get_today();
					frappe.query_report.set_filter_value(
						"to_date",
						today < doc.year_end_date ? today : doc.year_end_date
					);
				});
			},
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
		{
			fieldname: "period",
			label: __("Period"),
			fieldtype: "Select",
			options: ["YTD", "Monthly"],
			default: "YTD",
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center (Monthly view)"),
			fieldtype: "Link",
			options: "Cost Center",
			depends_on: "eval:doc.period === 'Monthly'",
			get_query: () => ({
				filters: { company: frappe.query_report.get_filter_value("company") },
			}),
		},
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.is_header || data.is_total) {
			value = `<span style="font-weight:600">${value}</span>`;
		}
		if (data.is_net && column.fieldtype === "Currency" && flt(data[column.fieldname]) < 0) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

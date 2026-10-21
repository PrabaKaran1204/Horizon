// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

const LEAD_STATUSES = [
	"Lead",
	"Open",
	"Replied",
	"Opportunity",
	"Quotation",
	"Lost Quotation",
	"Interested",
	"Converted",
	"Do Not Contact",
];

const STAGE_COLOURS = {
	Lead: "#7c7c7c",
	Opportunity: "#5e64ff",
	Customer: "green",
	Quoted: "orange",
	Ordered: "green",
	Lost: "red",
};

frappe.query_reports["CRM Pipeline Summary"] = {
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
			label: __("From Date (Lead created)"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -90),
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
			fieldname: "source",
			label: __("Lead Source"),
			fieldtype: "Link",
			options: "Lead Source",
		},
		{
			fieldname: "territory",
			label: __("Territory"),
			fieldtype: "Link",
			options: "Territory",
		},
		{ fieldname: "lead_owner", label: __("Lead Owner"), fieldtype: "Link", options: "User" },
		{
			fieldname: "status",
			label: __("Lead Status"),
			fieldtype: "MultiSelectList",
			get_data(txt) {
				return LEAD_STATUSES.filter(
					(s) => !txt || s.toLowerCase().includes(txt.toLowerCase())
				).map((s) => ({ value: s, description: "" }));
			},
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["None", "Source", "Territory", "Lead Owner", "Month"],
			default: "None",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		if (data && data.is_group) {
			// the group label sits in the Lead column: plain bold text, not a link to a Lead
			const text =
				column.fieldname === "lead"
					? frappe.utils.escape_html(value || "")
					: default_formatter(value, row, column, data);
			return `<span style="font-weight:600">${text}</span>`;
		}
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		const colour = STAGE_COLOURS[data.stage_reached];
		if (column.fieldname === "stage_reached" && colour) {
			value = `<span style="color:${colour};font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "days" && data.stage_reached === "Lead" && cint(data.days) > 14) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

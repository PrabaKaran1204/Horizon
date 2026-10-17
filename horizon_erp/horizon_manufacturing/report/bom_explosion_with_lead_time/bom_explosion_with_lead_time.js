// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["BOM Explosion with Lead Time"] = {
	filters: [
		{
			fieldname: "bom",
			label: __("BOM"),
			fieldtype: "Link",
			options: "BOM",
			reqd: 1,
			get_query: () => ({ filters: { docstatus: 1, is_active: 1 } }),
		},
		{
			fieldname: "qty",
			label: __("Qty to Manufacture"),
			fieldtype: "Float",
			default: 1,
			reqd: 1,
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			default: "HQ Raw Materials - HML",
			get_query: () => ({ filters: { is_group: 0 } }),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "shortage" && flt(data.shortage) > 0) {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "criticality" && data.criticality === "A") {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "available_on" && flt(data.shortage) > 0) {
			value = `<span style="color:orange;font-weight:600">${value}</span>`;
		}
		return value;
	},
};

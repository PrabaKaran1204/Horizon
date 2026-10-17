// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Horizon Stock Value by Warehouse"] = {
	method: "horizon_erp.horizon_stock.dashboard_chart_source.horizon_stock_value_by_warehouse.horizon_stock_value_by_warehouse.get",
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
	],
};

// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Inventory Obsolescence Analysis"] = {
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
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			get_query: () => ({
				filters: { company: frappe.query_report.get_filter_value("company"), is_group: 0 },
			}),
		},
		{
			fieldname: "days_threshold",
			label: __("Days Threshold"),
			fieldtype: "Int",
			default: 90,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "days_since_last_sale" && data) {
			const threshold = cint(frappe.query_report.get_filter_value("days_threshold")) || 90;
			const days = cint(data.days_since_last_sale);
			if (days > threshold) {
				value = `<span style="color:red;font-weight:600">${value}</span>`;
			} else if (days > 30) {
				value = `<span style="color:orange;font-weight:600">${value}</span>`;
			}
		}
		if (column.fieldname === "aging_bucket" && data && data.aging_bucket === "180+") {
			value = `<span style="color:red;font-weight:600">${value}</span>`;
		}
		return value;
	},

	get_datatable_options(options) {
		return Object.assign(options, { checkboxColumn: true });
	},

	onload(report) {
		report.page.add_inner_button(__("Mark for Scrap"), () => {
			const rows = frappe.query_report.get_checked_items();
			if (!rows.length) {
				frappe.msgprint(__("Select at least one row to mark for scrap."));
				return;
			}
			frappe.db.exists("Warehouse", "HQ Scrap - HML").then((exists) => {
				const dialog = new frappe.ui.Dialog({
					title: __("Mark {0} item(s) for Scrap", [rows.length]),
					fields: [
						{
							fieldname: "scrap_pct",
							label: __("Scrap Qty %"),
							fieldtype: "Percent",
							default: 100,
							reqd: 1,
						},
						{
							fieldname: "reason",
							label: __("Reason"),
							fieldtype: "Select",
							options: ["Obsolete", "Damaged", "Expired", "Slow-moving"],
							default: "Obsolete",
							reqd: 1,
						},
						{
							fieldname: "scrap_warehouse",
							label: __("Scrap Warehouse"),
							fieldtype: "Link",
							options: "Warehouse",
							default: exists ? "HQ Scrap - HML" : "",
							description: __(
								"Leave empty to create a Material Issue instead of a transfer."
							),
							get_query: () => ({
								filters: {
									company: frappe.query_report.get_filter_value("company"),
									is_group: 0,
								},
							}),
						},
					],
					primary_action_label: __("Create Draft Stock Entry"),
					primary_action(values) {
						dialog.hide();
						frappe.call({
							method: "horizon_erp.horizon_stock.scrap.mark_for_scrap",
							args: {
								rows: rows.map((r) => ({
									item_code: r.item_code,
									warehouse: r.warehouse,
									actual_qty: r.actual_qty,
								})),
								reason: values.reason,
								scrap_warehouse: values.scrap_warehouse,
								scrap_pct: values.scrap_pct,
							},
							freeze: true,
							callback(r) {
								if (!r.exc && r.message) {
									const link = frappe.utils.get_form_link(
										"Stock Entry",
										r.message,
										true
									);
									frappe.show_alert(
										{
											message: __("Draft Stock Entry {0} created", [link]),
											indicator: "green",
										},
										10
									);
									frappe.query_report.refresh();
								}
							},
						});
					},
				});
				dialog.show();
			});
		});
	},
};

// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

// Work Order form script (hooks.py doctype_js: "Work Order": "public/js/work_order.js").
// Shows the machine-hour requirement and the production line as dashboard indicators. Capacity
// violations are raised server-side by horizon_operations.manufacturing.validate_work_order.

frappe.ui.form.on("Work Order", {
	refresh(frm) {
		if (flt(frm.doc.required_machine_hours)) {
			frm.dashboard.add_indicator(
				__("Machine hours: {0}", [format_number(frm.doc.required_machine_hours, null, 2)]),
				frm.doc.capacity_override ? "red" : "blue"
			);
		}
		if (frm.doc.production_item) {
			frappe.db.get_value("Item", frm.doc.production_item, "default_line").then((r) => {
				const line = r && r.message && r.message.default_line;
				if (line) {
					frm.dashboard.add_indicator(__("Line: {0}", [line]), "gray");
				}
			});
		}
		if (frm.doc.rework_of) {
			frm.dashboard.set_headline_alert(
				__("Rework of {0}", [frappe.utils.get_form_link("Work Order", frm.doc.rework_of, true)]),
				"orange"
			);
		}
	},
});

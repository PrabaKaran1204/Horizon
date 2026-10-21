// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

// Work Order form script (hooks.py doctype_js: "Work Order": "public/js/work_order.js").
// Shows the machine-hour requirement and the production line as dashboard indicators. Capacity
// violations are raised server-side by horizon_manufacturing.manufacturing.validate_work_order.
// For submitted, open Work Orders it also offers Create > Production Audit (pre-filled server-side
// by production_audit_hooks.make_production_audit, like ERPNext's own Create buttons) and a
// headline from get_audit_status: no audit yet (optional), latest score, or Finish blocked while a
// low-score audit's corrective action is open.

const AUDIT_METHOD = "horizon_erp.horizon_quality_management.production_audit_hooks";
const AUDITABLE_STATUSES = ["Not Started", "In Process"];

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
			set_headline(frm, "", "orange");
		}
		if (frm.doc.docstatus === 1) {
			show_audit_status(frm);
		}
	},
});

function show_audit_status(frm) {
	const work_order = frm.doc.name;
	frappe.xcall(`${AUDIT_METHOD}.get_audit_status`, { work_order }).then((status) => {
		// asynchronous: drop a reply that arrives after the user moved to another Work Order
		if (!status || frm.doc.name !== work_order) {
			return;
		}
		show_audit_headline(frm, status);
		if (status.missing_before_finish) {
			frm.dashboard.add_indicator(
				__("Missing before Finish: {0}", [status.missing_before_finish]),
				"orange"
			);
		}
		if (AUDITABLE_STATUSES.includes(frm.doc.status)) {
			frm.add_custom_button(
				__("Production Audit"),
				() => {
					frappe.model.open_mapped_doc({
						method: `${AUDIT_METHOD}.make_production_audit`,
						frm: frm,
						freeze_message: __("Preparing Production Audit"),
					});
				},
				__("Create")
			);
		}
	});
}

function show_audit_headline(frm, status) {
	if (!status.audit) {
		if (status.can_audit) {
			set_headline(
				frm,
				__(
					"No Production Audit yet for this Work Order (optional; score below {0} blocks Finish)",
					[status.fail_score]
				),
				"blue"
			);
		}
		return;
	}
	const link = frappe.utils.get_form_link("Production Audit", status.audit, true);
	if (status.score >= status.fail_score) {
		set_headline(frm, __("Production Audit {0} scored {1}", [link, status.score]), "green");
	} else if (status.blocking) {
		set_headline(
			frm,
			__(
				"Production Audit {0} scored {1}: Finish is blocked until the corrective action is closed",
				[link, status.score]
			),
			"red"
		);
	} else {
		set_headline(
			frm,
			__("Production Audit {0} scored {1}: corrective action closed", [link, status.score]),
			"green"
		);
	}
}

function set_headline(frm, text, color) {
	// the rework headline stays as the first line when an audit headline replaces it
	const lines = [];
	if (frm.doc.rework_of) {
		lines.push(
			__("Rework of {0}", [
				frappe.utils.get_form_link("Work Order", frm.doc.rework_of, true),
			])
		);
	}
	if (text) {
		lines.push(text);
	}
	frm.dashboard.set_headline_alert(lines.join("<br>"), color);
}

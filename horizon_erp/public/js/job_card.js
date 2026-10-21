// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

// Job Card form script (hooks.py doctype_js: "Job Card": "public/js/job_card.js").
// ERPNext v15 only filters the quality_inspection link on this form; the ADR-19 gate
// (horizon_quality_management.operation_inspection) refuses completion without an Accepted
// inspection, so the form shows where the card stands and offers Create > Quality Inspection,
// pre-filled server-side (reference, item, template, readings) like ERPNext's own Create buttons.

const QI_METHOD = "horizon_erp.horizon_quality_management.operation_inspection";

frappe.ui.form.on("Job Card", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus > 1) {
			return;
		}
		const job_card = frm.doc.name;
		frappe.xcall(`${QI_METHOD}.get_inspection_status`, { job_card }).then((status) => {
			// asynchronous: drop a reply that arrives after the user moved to another card
			if (!status || !status.required || frm.doc.name !== job_card) {
				return;
			}
			show_inspection_headline(frm, status);
			frm.add_custom_button(
				__("Quality Inspection"),
				() => {
					frappe.model.open_mapped_doc({
						method: `${QI_METHOD}.make_quality_inspection`,
						frm: frm,
						freeze_message: __("Preparing Quality Inspection"),
					});
				},
				__("Create")
			);
		});
	},
});

function show_inspection_headline(frm, status) {
	if (status.accepted) {
		frm.dashboard.set_headline_alert(
			__("Quality Inspection {0} accepted", [
				frappe.utils.get_form_link("Quality Inspection", status.inspection, true),
			]),
			"green"
		);
	} else if (status.inspection) {
		frm.dashboard.set_headline_alert(
			__(
				"Latest Quality Inspection {0} is {1}: an Accepted re-inspection is required before this Job Card can be completed",
				[
					frappe.utils.get_form_link("Quality Inspection", status.inspection, true),
					frappe.utils.escape_html(status.result),
				]
			),
			"red"
		);
	} else {
		frm.dashboard.set_headline_alert(
			__("Accepted Quality Inspection required before this Job Card can be completed"),
			"red"
		);
	}
}

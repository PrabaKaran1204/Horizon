// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

const LOW_SCORE_THRESHOLD = 70;

frappe.ui.form.on("Production Audit", {
	setup(frm) {
		frm.set_query("work_order", () => ({
			filters: { status: ["not in", ["Completed", "Cancelled", "Stopped"]], docstatus: 1 },
		}));
	},

	refresh(frm) {
		// TODO(quality): render Work Order context (item, qty, planned dates, operations) as HTML
		// in a dashboard section via frm.dashboard.add_section / frappe.render_template.
		frm.trigger("audit_score");
	},

	audit_score(frm) {
		// TODO(quality): replace the Int control with a slider and colour-code it
		// (red < 70, amber 70-85, green > 85) via frm.fields_dict.audit_score.$wrapper.
		// TODO(quality): toggle the photos table mandatory when audit_score < LOW_SCORE_THRESHOLD.
		frm.toggle_reqd("photos", cint(frm.doc.audit_score) < LOW_SCORE_THRESHOLD);
	},
});

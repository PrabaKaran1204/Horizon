// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

const LOW_SCORE_THRESHOLD = 70;
const WARN_SCORE_THRESHOLD = 85;

frappe.ui.form.on("Production Audit", {
	setup(frm) {
		frm.set_query("work_order", () => ({
			filters: { status: ["not in", ["Completed", "Cancelled", "Stopped"]], docstatus: 1 },
		}));
	},

	refresh(frm) {
		frm.trigger("render_score_slider");
		frm.trigger("audit_score");
		frm.trigger("render_work_order_context");

		if (frm.doc.docstatus === 1 && frm.doc.corrective_action) {
			frm.add_custom_button(__("Quality Action"), () => {
				frappe.set_route("Form", "Quality Action", frm.doc.corrective_action);
			}, __("View"));
		}
	},

	work_order(frm) {
		frm.trigger("render_work_order_context");
	},

	audit_score(frm) {
		const score = cint(frm.doc.audit_score);
		frm.toggle_reqd("photos", score < LOW_SCORE_THRESHOLD);
		horizon_audit.colour_score(frm, score);
		horizon_audit.sync_slider(frm, score);
	},

	render_score_slider(frm) {
		const field = frm.fields_dict.audit_score;
		if (!field || !field.$wrapper || field.$wrapper.find(".horizon-score-slider").length) {
			return;
		}
		const $slider = $(`
			<div class="horizon-score-slider" style="margin-top: 6px;">
				<input type="range" min="0" max="100" step="1" style="width: 100%;"
					${frm.doc.docstatus ? "disabled" : ""} />
				<div class="text-muted small" style="display: flex; justify-content: space-between;">
					<span>0</span><span>${LOW_SCORE_THRESHOLD}</span><span>${WARN_SCORE_THRESHOLD}</span><span>100</span>
				</div>
			</div>`);
		$slider.find("input").on("input change", (e) => {
			const value = cint(e.target.value);
			if (value !== cint(frm.doc.audit_score)) {
				frm.set_value("audit_score", value);
			}
		});
		field.$wrapper.append($slider);
		horizon_audit.sync_slider(frm, cint(frm.doc.audit_score));
	},

	render_work_order_context(frm) {
		if (!frm.doc.work_order) {
			horizon_audit.set_context(frm, "");
			return;
		}
		frappe.call({
			method: "horizon_erp.horizon_quality_management.doctype.production_audit.production_audit.get_work_order_context",
			args: { work_order: frm.doc.work_order },
		}).then((r) => {
			const wo = r.message || {};
			const rows = [
				[__("Item"), `${wo.production_item || ""} ${wo.item_name ? "- " + wo.item_name : ""}`],
				[__("Status"), wo.status || ""],
				[__("Qty / Produced"), `${flt(wo.qty)} / ${flt(wo.produced_qty)}`],
				[__("Planned"), `${frappe.datetime.str_to_user(wo.planned_start_date) || "-"} to ${
					frappe.datetime.str_to_user(wo.planned_end_date) || "-"
				}`],
				[__("Workstation"), wo.workstation || __("No operations")],
				[__("Required Machine Hours"), flt(wo.required_machine_hours)],
			];
			const html = `<table class="table table-bordered table-sm" style="margin: 0;">${rows
				.map(([k, v]) => `<tr><td style="width: 35%;"><b>${k}</b></td><td>${v}</td></tr>`)
				.join("")}</table>`;
			horizon_audit.set_context(frm, html);
			if (!frm.doc.workstation && wo.workstation && frm.doc.docstatus === 0) {
				frm.set_value("workstation", wo.workstation);
			}
		});
	},
});

const horizon_audit = {
	colour_score(frm, score) {
		const field = frm.fields_dict.audit_score;
		if (!field || !field.$wrapper) return;
		let colour = "var(--green-100, #d4f5e4)";
		let indicator = "green";
		if (score < LOW_SCORE_THRESHOLD) {
			colour = "var(--red-100, #fde8e8)";
			indicator = "red";
		} else if (score < WARN_SCORE_THRESHOLD) {
			colour = "var(--yellow-100, #fff4ce)";
			indicator = "orange";
		}
		field.$wrapper.find("input[data-fieldname='audit_score'], .control-value").css("background-color", colour);
		if (frm.doc.audit_score !== undefined && frm.doc.audit_score !== null) {
			frm.dashboard.set_headline(
				`<span class="indicator-pill ${indicator}">${__("Audit Score")}: ${score}</span>`
			);
		}
	},

	sync_slider(frm, score) {
		const field = frm.fields_dict.audit_score;
		if (!field || !field.$wrapper) return;
		const $input = field.$wrapper.find(".horizon-score-slider input");
		if ($input.length && cint($input.val()) !== score) {
			$input.val(score);
		}
		let accent = "#28a745";
		if (score < LOW_SCORE_THRESHOLD) accent = "#dc3545";
		else if (score < WARN_SCORE_THRESHOLD) accent = "#ffc107";
		$input.css("accent-color", accent);
	},

	set_context(frm, html) {
		// add_section() returns the section body; the label is rendered by the Section itself
		if (!frm.horizon_context_body) {
			frm.horizon_context_body = frm.dashboard.add_section("", __("Work Order Context"));
		}
		frm.horizon_context_body.html(html || "");
		frm.horizon_context_body.closest(".form-dashboard-section").toggle(Boolean(html));
		if (html) {
			frm.dashboard.show();
		}
	},
};

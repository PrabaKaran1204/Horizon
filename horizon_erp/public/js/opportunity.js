// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

// Opportunity form script (hooks.py doctype_js: "Opportunity": "public/js/opportunity.js").
// Customer created from a qualified Opportunity (ADR-17): Create > Customer runs the Horizon
// conversion (group, GSTIN, billing address, credit limit, payment terms) instead of ERPNext's
// blank Customer form; State is set from the GSTIN's first two digits.

frappe.provide("horizon_erp.crm");

horizon_erp.crm.ENSURE_CUSTOMER_METHOD = "horizon_erp.horizon_crm.opportunity.ensure_customer_from_opportunity";
horizon_erp.crm.STATE_NUMBERS_METHOD = "horizon_erp.horizon_crm.opportunity.get_gst_state_numbers";

horizon_erp.crm.get_state_numbers = function () {
	if (!horizon_erp.crm._state_numbers) {
		horizon_erp.crm._state_numbers = frappe
			.call({ method: horizon_erp.crm.STATE_NUMBERS_METHOD })
			.then((r) => r.message || {});
	}
	return horizon_erp.crm._state_numbers;
};

horizon_erp.crm.create_customer = function (frm) {
	const run = () =>
		frappe.call({
			method: horizon_erp.crm.ENSURE_CUSTOMER_METHOD,
			args: { opportunity: frm.doc.name },
			freeze: true,
			freeze_message: __("Creating Customer..."),
			callback: (r) => {
				if (r.message) {
					frappe.show_alert({ message: __("Customer {0} ready", [r.message]), indicator: "green" });
					frappe.set_route("Form", "Customer", r.message);
				}
			},
		});
	// save pending edits first so the server sees the details on the form
	frm.is_dirty() ? frm.save().then(run) : run();
};

frappe.ui.form.on("Opportunity", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.opportunity_from !== "Lead") return;

		if (frm.doc.horizon_customer) {
			frm.remove_custom_button(__("Customer"), __("Create"));
			frm.dashboard.add_indicator(__("Customer: {0}", [frm.doc.horizon_customer]), "green");
			frm.add_custom_button(
				__("Customer"),
				() => frappe.set_route("Form", "Customer", frm.doc.horizon_customer),
				__("View")
			);
			return;
		}

		if (frm.doc.status !== "Lost") {
			// replaces ERPNext's Create > Customer (blank form without GST / credit / terms)
			frm.remove_custom_button(__("Customer"), __("Create"));
			frm.add_custom_button(__("Customer"), () => horizon_erp.crm.create_customer(frm), __("Create"));
		}
		if (!frm.doc.customer_group) {
			frm.dashboard.add_indicator(__("No Customer Group: quotations stay on the Lead"), "orange");
		}
	},

	horizon_gstin(frm) {
		const gstin = (frm.doc.horizon_gstin || "").toUpperCase().trim();
		if (gstin !== (frm.doc.horizon_gstin || "")) {
			frm.set_value("horizon_gstin", gstin);
			return; // re-triggered by set_value
		}
		if (gstin.length < 2) return;
		if (!frm.doc.horizon_gst_category) frm.set_value("horizon_gst_category", "Registered Regular");
		horizon_erp.crm.get_state_numbers().then((numbers) => {
			const state = Object.keys(numbers).find((name) => numbers[name] === gstin.slice(0, 2));
			if (state && frm.doc.state !== state) {
				frm.set_value("state", state);
				frm.set_value("country", "India");
			}
		});
	},
});

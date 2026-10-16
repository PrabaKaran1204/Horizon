// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

// Purchase Order form script (hooks.py doctype_js: "Purchase Order": "public/js/purchase_order.js").
// Supplier blacklist warning + approval level indicator.

frappe.provide("horizon_erp.buying");

horizon_erp.buying.check_blacklist = function (frm) {
	if (!frm.doc.supplier) {
		frm.dashboard.clear_headline();
		frm.set_df_property("blacklist_override", "reqd", 0);
		return;
	}
	frappe.db.get_value("Supplier", frm.doc.supplier, ["is_blacklisted", "blacklist_reason"]).then((r) => {
		const s = (r && r.message) || {};
		if (cint(s.is_blacklisted)) {
			frm.dashboard.set_headline_alert(
				__("Supplier {0} is blacklisted: {1}", [
					frappe.utils.escape_html(frm.doc.supplier),
					frappe.utils.escape_html(s.blacklist_reason || __("no reason recorded")),
				]),
				"red"
			);
			frm.toggle_display("blacklist_override", true);
			frm.set_df_property("blacklist_override", "reqd", 1);
		} else {
			frm.dashboard.clear_headline();
			frm.set_df_property("blacklist_override", "reqd", 0);
		}
	});
};

frappe.ui.form.on("Purchase Order", {
	refresh(frm) {
		if (frm.doc.approval_level_required) {
			const colour = { "Level 1": "green", "Level 2": "orange", "Level 3": "red" }[
				frm.doc.approval_level_required
			];
			frm.dashboard.add_indicator(
				__("Approval required: {0}", [frm.doc.approval_level_required]),
				colour || "blue"
			);
		}
		if (frm.doc.workflow_state && frm.doc.workflow_state.startsWith("Pending") && frm.doc.pending_since) {
			frm.dashboard.add_indicator(
				__("Pending since {0}", [frappe.datetime.prettyDate(frm.doc.pending_since)]),
				"orange"
			);
		}
		horizon_erp.buying.check_blacklist(frm);
	},
	supplier(frm) {
		horizon_erp.buying.check_blacklist(frm);
	},
});

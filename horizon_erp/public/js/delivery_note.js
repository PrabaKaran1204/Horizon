// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

// Delivery Note form script (hooks.py doctype_js: "Delivery Note": "public/js/delivery_note.js").
// "Create > Shipment Decision" for deliveries against a Sales Order; headline when a Shipment
// Decision is already linked.

frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		const so_row = (frm.doc.items || []).find((d) => d.against_sales_order);
		if (so_row && frm.doc.docstatus < 2) {
			frm.add_custom_button(
				__("Shipment Decision"),
				() => {
					frappe.new_doc("Shipment Decision", {
						sales_order: so_row.against_sales_order,
						customer: frm.doc.customer,
					});
				},
				__("Create")
			);
		}
		if (frm.doc.shipment_decision) {
			frm.dashboard.set_headline_alert(
				__("Governed by Shipment Decision {0}", [
					frappe.utils.get_form_link("Shipment Decision", frm.doc.shipment_decision, true),
				]),
				"orange"
			);
		}
	},
});

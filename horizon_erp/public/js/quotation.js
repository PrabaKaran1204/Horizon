// Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
// For license information, please see license.txt

// Quotation form script (hooks.py doctype_js: "Quotation": "public/js/quotation.js").
// Availability enrichment of item rows + discount approval banner.

frappe.provide("horizon_erp.sales");

if (!horizon_erp.sales.fetch_availability) {
	horizon_erp.sales.AVAILABILITY_METHOD = "horizon_erp.horizon_operations.selling.get_item_availability";

	horizon_erp.sales.fetch_availability = function (frm, cdt, cdn, with_delivery_date) {
		const row = locals[cdt][cdn];
		if (!row || !row.item_code) return;

		frappe.call({
			method: horizon_erp.sales.AVAILABILITY_METHOD,
			args: { item_code: row.item_code, qty: row.qty || 1, company: frm.doc.company },
			silent: true, // method may not be deployed yet; never bother the user
			error: () => {},
			callback: (r) => {
				if (!r || !r.message) return;
				const d = r.message;
				frappe.model.set_value(cdt, cdn, "available_qty", flt(d.available_qty));
				frappe.model.set_value(cdt, cdn, "mfg_lead_days", cint(d.mfg_lead_days));
				if (with_delivery_date && d.expected_delivery_date) {
					frappe.model.set_value(cdt, cdn, "expected_delivery_date", d.expected_delivery_date);
				}
				horizon_erp.sales.colour_availability(frm, cdn, flt(d.available_qty) >= flt(row.qty || 1));
			},
		});
	};

	horizon_erp.sales.colour_availability = function (frm, cdn, is_available) {
		const grid_row = frm.fields_dict.items && frm.fields_dict.items.grid.get_row(cdn);
		if (grid_row && grid_row.columns && grid_row.columns.available_qty) {
			$(grid_row.columns.available_qty).css({
				"background-color": is_available ? "#d1f0d1" : "#f8d7da",
				color: is_available ? "#0b5d0b" : "#842029",
			});
		} else {
			frappe.show_alert({
				message: is_available ? __("Item available in stock") : __("Insufficient stock – check lead time"),
				indicator: is_available ? "green" : "red",
			});
		}
	};

	horizon_erp.sales.show_discount_approval_intro = function (frm) {
		if (frm.doc.needs_discount_approval) {
			frm.set_intro(__("This quotation needs Sales Manager approval (discount over 15%)"), "orange");
		}
	};
}

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		horizon_erp.sales.show_discount_approval_intro(frm);
	},
});

frappe.ui.form.on("Quotation Item", {
	item_code(frm, cdt, cdn) {
		horizon_erp.sales.fetch_availability(frm, cdt, cdn, true);
	},
	qty(frm, cdt, cdn) {
		horizon_erp.sales.fetch_availability(frm, cdt, cdn, true);
	},
});

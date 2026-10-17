# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Quality Inspection document event handlers."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_link_to_form, now_datetime, nowdate, strip_html

from horizon_erp.horizon_core import config


def on_submit_quality_inspection(doc, method=None):
	"""Quality Inspection ``on_submit`` hook.

	- ``evidence_required``: at least one file must be attached.
	- Inspections on manufacturing references (Job Card / Stock Entry - Quality Inspection has no
	  "Work Order" reference type in v15, so the Work Order is resolved from the reference):
	  * ``qc_result`` = Rework (or status Rejected without an explicit Fail): create a DRAFT rework
	    Work Order for ``sample_size`` (Quality Inspection carries no rejected-qty field) with
	    ``rework_of`` = source Work Order and link it in ``rework_work_order``.
	  * ``qc_result`` = Fail: raise a Non Conformance under the "Horizon Manufacturing QC" procedure.
	- Purchase Receipt rejections are handled when the receipt is submitted
	  (``horizon_stock.purchase_receipt.on_submit_purchase_receipt``).
	"""
	validate_evidence(doc)

	work_order = resolve_work_order(doc)
	if not work_order:
		return

	failed = doc.status == "Rejected" or doc.get("qc_result") in ("Fail", "Rework")
	if not failed:
		return

	if doc.get("qc_result") == "Fail":
		create_non_conformance(doc, work_order)
	else:
		create_rework_work_order(doc, work_order)


def validate_evidence(doc):
	if not doc.get("evidence_required"):
		return
	attached = frappe.db.exists(
		"File", {"attached_to_doctype": "Quality Inspection", "attached_to_name": doc.name}
	)
	if not attached:
		frappe.throw(
			_(
				"Evidence is required for this inspection: attach at least one photo or document "
				"before submitting"
			),
			title=_("Evidence Missing"),
		)


def resolve_work_order(doc):
	if doc.reference_type == "Job Card" and doc.reference_name:
		return frappe.db.get_value("Job Card", doc.reference_name, "work_order")
	if doc.reference_type == "Stock Entry" and doc.reference_name:
		return frappe.db.get_value("Stock Entry", doc.reference_name, "work_order")
	if doc.reference_type == "Work Order":  # future-proof if the option is ever added
		return doc.reference_name
	return None


def create_rework_work_order(doc, work_order):
	source = frappe.get_doc("Work Order", work_order)
	qty = flt(doc.sample_size) or 1

	wo = frappe.new_doc("Work Order")
	wo.production_item = source.production_item
	wo.bom_no = source.bom_no
	wo.company = source.company
	wo.qty = qty
	wo.fg_warehouse = source.fg_warehouse
	wo.wip_warehouse = source.wip_warehouse
	wo.source_warehouse = source.source_warehouse
	wo.skip_transfer = source.skip_transfer
	wo.use_multi_level_bom = source.use_multi_level_bom
	wo.transfer_material_against = source.transfer_material_against
	wo.planned_start_date = now_datetime()
	wo.rework_of = source.name
	wo.description = _("Rework of {0} after Quality Inspection {1} ({2})").format(
		source.name, doc.name, doc.get("qc_result") or doc.status
	)
	wo.flags.ignore_permissions = True
	try:
		wo.set_work_order_operations()
		wo.insert()
	except Exception:
		frappe.log_error(title=f"Rework Work Order failed for {doc.name}", message=frappe.get_traceback())
		frappe.msgprint(
			_(
				"The rework Work Order could not be created automatically (see Error Log); "
				"create it manually with Rework Of = {0}"
			).format(source.name),
			indicator="orange",
			alert=True,
		)
		return None

	doc.db_set("rework_work_order", wo.name, update_modified=False)
	link = get_link_to_form("Work Order", wo.name)
	doc.add_comment("Comment", _("Rework Work Order {0} created for {1} units").format(link, qty))
	frappe.msgprint(_("Rework Work Order {0} created (draft)").format(link), alert=True)
	return wo


def ensure_quality_procedure():
	name = config.QUALITY_PROCEDURE_NAME
	if frappe.db.exists("Quality Procedure", name):
		return name
	qp = frappe.new_doc("Quality Procedure")
	qp.quality_procedure_name = name
	qp.append("processes", {"process_description": "Horizon in-process and final QC"})
	qp.flags.ignore_permissions = True
	qp.insert()
	return qp.name


def create_non_conformance(doc, work_order):
	nc = frappe.new_doc("Non Conformance")
	nc.subject = _("QC failure on Work Order {0} ({1})").format(work_order, doc.item_code)
	nc.procedure = ensure_quality_procedure()
	nc.status = "Open"
	nc.process_owner = frappe.session.user
	nc.details = _(
		"<p>Quality Inspection {0} failed on Work Order {1}.</p><p>Item: {2}, sample size: {3}</p>"
		"<p>Rejection reason: {4}</p>"
	).format(
		get_link_to_form("Quality Inspection", doc.name),
		get_link_to_form("Work Order", work_order),
		doc.item_code,
		flt(doc.sample_size),
		frappe.utils.escape_html(doc.get("rejection_reason") or _("not recorded")),
	)
	nc.flags.ignore_permissions = True
	nc.insert()
	link = get_link_to_form("Non Conformance", nc.name)
	doc.add_comment("Comment", _("Non Conformance {0} raised").format(link))
	frappe.msgprint(_("Non Conformance {0} raised").format(link), alert=True)
	return nc


def create_quality_action(description, problem, procedure=None, responsible=None):
	"""Shared helper (also used by Production Audit): a Quality Action with one open resolution."""
	qa = frappe.new_doc("Quality Action")
	qa.corrective_preventive = "Corrective"
	qa.date = nowdate()
	qa.procedure = procedure or ensure_quality_procedure()
	qa.append(
		"resolutions",
		{
			"problem": strip_html(problem or description),
			"status": "Open",
			"responsible": responsible,
			"completion_by": add_days(nowdate(), 7),
		},
	)
	qa.flags.ignore_permissions = True
	qa.insert()
	return qa

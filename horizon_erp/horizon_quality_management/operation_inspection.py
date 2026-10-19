# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Mandatory in-process inspection per Work Order operation (ADR-19).

ERPNext v15 carries the data model (Operation / Job Card ``quality_inspection_template``, the Job
Card ``quality_inspection`` link and Quality Inspection reference type "Job Card") but enforces
nothing: a Job Card submits and the Manufacture entry posts without any inspection. Horizon adds:

- Job Card ``before_submit``: an operation with a Quality Inspection Template cannot be completed
  until a submitted, Accepted Quality Inspection references the Job Card.
- Manufacture Stock Entry (called from ``production_audit_hooks.validate_stock_entry``): every
  operation of the Work Order needs a completed Job Card and each of those cards an Accepted
  inspection; everything missing is reported in one message.

"Accepted" means the latest submitted inspection of the card has status Accepted and a QC result
other than Fail / Rework (blank, Pass and Conditional Pass are accepted). Fail and Rework route
the quantity to a Non Conformance / rework Work Order (``inspection.on_submit_quality_inspection``),
so they never release the card; a later Accepted re-inspection does.
"""

import frappe
from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry as _make_stock_entry
from frappe import _
from frappe.utils import get_link_to_form

REJECTED_QC_RESULTS = ("Fail", "Rework")


def get_required_template(job_card):
	"""Template the card must be inspected against: the card's own, else its Operation's."""
	template = job_card.get("quality_inspection_template")
	if not template and job_card.get("operation"):
		template = frappe.get_cached_value("Operation", job_card.operation, "quality_inspection_template")
	return template


def is_accepted(inspection):
	return bool(
		inspection
		and inspection.status == "Accepted"
		and (inspection.get("qc_result") or "") not in REJECTED_QC_RESULTS
	)


def get_latest_inspections(job_cards):
	"""``{job_card: latest submitted Quality Inspection}`` in one query."""
	if not job_cards:
		return {}
	latest = {}
	for row in frappe.get_all(
		"Quality Inspection",
		filters={"reference_type": "Job Card", "reference_name": ["in", list(job_cards)], "docstatus": 1},
		fields=["name", "reference_name", "status", "qc_result"],
		order_by="creation desc",
	):
		latest.setdefault(row.reference_name, row)
	return latest


def describe_result(inspection):
	return inspection.get("qc_result") or inspection.status


# ---------------------------------------------------------------------------
# Job Card
# ---------------------------------------------------------------------------


def before_validate_job_card(doc, method=None):
	"""Draft Job Cards created before their Operation had a template pick it up, so the
	standard "+ Create Quality Inspection" route on the form pre-fills the right template."""
	if doc.docstatus == 0 and not doc.get("quality_inspection_template"):
		template = get_required_template(doc)
		if template:
			doc.quality_inspection_template = template


def before_submit_job_card(doc, method=None):
	"""Job Card ``before_submit``: no completion without an Accepted inspection."""
	template = get_required_template(doc)
	if not template:
		return

	inspection = get_latest_inspections([doc.name]).get(doc.name)
	if is_accepted(inspection):
		return

	if not inspection:
		frappe.throw(
			_(
				"Operation {0} on Job Card {1} cannot be completed without an Accepted Quality "
				"Inspection (template {2}).<br><br>Create it from this Job Card: in the Quality "
				"Inspection section use the Quality Inspection field > Create a new Quality Inspection "
				"(Inspection Type In Process, Reference Type Job Card, Reference {1}), enter the readings "
				"and submit it as Accepted."
			).format(frappe.bold(doc.operation), frappe.bold(doc.name), frappe.bold(template)),
			title=_("Quality Inspection Required"),
		)

	frappe.throw(
		_(
			"Operation {0} on Job Card {1} cannot be completed: the latest Quality Inspection {2} is "
			"{3}.<br><br>The rejected quantity is handled by the rework Work Order / Non Conformance "
			"raised from that inspection. Once the parts are corrected, submit an Accepted "
			"re-inspection against this Job Card."
		).format(
			frappe.bold(doc.operation),
			frappe.bold(doc.name),
			get_link_to_form("Quality Inspection", inspection.name),
			frappe.bold(describe_result(inspection)),
		),
		title=_("Quality Inspection Not Accepted"),
	)


# ---------------------------------------------------------------------------
# Manufacture Stock Entry ("Finish")
# ---------------------------------------------------------------------------


def get_missing_before_finish(work_order):
	"""Human-readable list of what still blocks the Manufacture entry of ``work_order``.

	Per Work Order operation: at least one submitted (Completed) Job Card - quantities are left
	to ERPNext's own completed-qty check so partial manufacture keeps working - and, for every
	submitted card whose operation has a template, an Accepted inspection. Draft cards for the
	remaining quantity of a partially completed operation do not block.
	"""
	operations = frappe.get_all(
		"Work Order Operation",
		filters={"parent": work_order, "parenttype": "Work Order"},
		fields=["name", "operation"],
		order_by="idx",
	)
	if not operations:
		return []

	cards = frappe.get_all(
		"Job Card",
		filters={"work_order": work_order, "docstatus": ["<", 2]},
		fields=["name", "operation", "operation_id", "docstatus", "quality_inspection_template"],
		order_by="creation",
	)
	latest = get_latest_inspections([c.name for c in cards if c.docstatus == 1])

	missing = []
	for op in operations:
		op_cards = [c for c in cards if c.operation_id == op.name] or [
			c for c in cards if not c.operation_id and c.operation == op.operation
		]
		submitted = [c for c in op_cards if c.docstatus == 1]
		if not submitted:
			drafts = ", ".join(get_link_to_form("Job Card", c.name) for c in op_cards)
			missing.append(
				_("Job Card for {0} not completed ({1})").format(frappe.bold(op.operation), drafts)
				if drafts
				else _("Job Card for {0} not created").format(frappe.bold(op.operation))
			)
			continue

		for card in submitted:
			if not get_required_template(card):
				continue
			inspection = latest.get(card.name)
			if not inspection:
				missing.append(
					_("Quality Inspection for {0} ({1})").format(
						frappe.bold(op.operation), get_link_to_form("Job Card", card.name)
					)
				)
			elif not is_accepted(inspection):
				missing.append(
					_("Accepted Quality Inspection for {0} ({1}): {2} is {3}").format(
						frappe.bold(op.operation),
						get_link_to_form("Job Card", card.name),
						get_link_to_form("Quality Inspection", inspection.name),
						describe_result(inspection),
					)
				)
	return missing


def validate_manufacture_inspections(doc):
	"""Throw one message listing every missing Job Card completion / inspection."""
	throw_if_missing(doc.work_order)


def throw_if_missing(work_order):
	missing = get_missing_before_finish(work_order)
	if not missing:
		return
	frappe.throw(
		_(
			"Work Order {0} cannot be finished.<br>Missing before finish: {1}.<br><br>Complete each "
			"Job Card and submit an Accepted Quality Inspection against it (Inspection Type In "
			"Process, Reference Type Job Card) before creating the Manufacture entry."
		).format(frappe.bold(work_order), "; ".join(missing)),
		title=_("Inspection Missing"),
	)


@frappe.whitelist()
def make_stock_entry(work_order_id, purpose, qty=None, target_warehouse=None):
	"""``override_whitelisted_methods`` wrapper of the Work Order "Finish" / "Start" endpoint.

	ERPNext's ``make_stock_entry`` already runs the Stock Entry's ``validate_work_order`` (via
	``get_items``), whose per-operation completed-qty check would otherwise answer the Finish
	button with only the first incomplete operation. For Manufacture the consolidated gate runs
	first; the Stock Entry ``before_validate`` hook re-checks on save / submit.
	"""
	frappe.has_permission("Work Order", "read", doc=work_order_id, throw=True)
	if purpose == "Manufacture":
		throw_if_missing(work_order_id)
	return _make_stock_entry(work_order_id, purpose, qty=qty, target_warehouse=target_warehouse)

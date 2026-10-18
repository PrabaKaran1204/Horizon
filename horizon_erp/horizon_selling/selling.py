# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Selling-side document event handlers (Quotation, Sales Order, Delivery Note, Sales Invoice).

Wired from ``hooks.py`` ``doc_events``. Every handler takes ``(doc, method=None)``.
"""

import math

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, flt, get_link_to_form, getdate

from horizon_erp.horizon_core import config

DEFAULT_VALID_TILL_DAYS = 30
MAX_BOM_DEPTH = 5  # sub-assembly levels explored by get_mfg_lead_days
MAX_MFG_LEAD_DAYS = 365
# Rate difference (in transaction currency) still treated as "the pricing-rule rate"
RATE_TOLERANCE = 0.01
# Pricing fields copied from the Sales Order row onto Delivery Note / Sales Invoice rows (price
# locked at order time; see lock_rates_to_sales_order)
SO_LOCKED_RATE_FIELDS = (
	"price_list_rate",
	"discount_percentage",
	"discount_amount",
	"margin_type",
	"margin_rate_or_amount",
	"rate",
)


# ---------------------------------------------------------------------------------------------
# Quotation / Sales Order: discount governance + availability
# ---------------------------------------------------------------------------------------------
def validate_discounts(doc, method=None):
	"""Quotation / Sales Order ``validate`` hook (shared).

	- ``rule_rate``: price list rate after the Pricing Rules recorded on the row.
	- ``discount_over_rule_pct``: extra discount the user granted below the rule rate.
	- ``needs_discount_approval`` when any row (or the document-level discount) exceeds
	  ``DISCOUNT_AUTO_APPROVE_PCT``; a ``discount_reason`` is then mandatory and only a Sales
	  Manager / System Manager may submit.
	- Ad-hoc pricing (``ignore_pricing_rule`` or a hand-edited ``price_list_rate``) is reserved
	  for Sales Managers.
	- Quotation rows additionally get ``available_qty`` / ``mfg_lead_days`` / ``expected_delivery_date``.
	"""
	threshold = config.get_threshold("discount_auto_approve_pct", config.DISCOUNT_AUTO_APPROVE_PCT)
	is_manager = config.user_has_any_role(config.DISCOUNT_APPROVER_ROLES)

	if doc.get("ignore_pricing_rule") and not is_manager:
		frappe.throw(
			_(
				"Only a Sales Manager may untick 'Ignore Pricing Rule'; prices must come from the "
				"price list and pricing rules"
			),
			title=_("Ad-hoc Pricing Not Allowed"),
		)

	if not is_manager:
		validate_price_list_rates_untouched(doc)

	needs_approval = flt(doc.get("additional_discount_percentage")) > threshold
	rule_cache = {}
	for row in doc.get("items", []):
		row.rule_rate = get_rule_rate(row, rule_cache)
		row.discount_over_rule_pct = get_discount_over_rule_pct(row.rule_rate, row.rate)
		sync_agreed_rate(row)
		if flt(row.discount_over_rule_pct) > threshold:
			needs_approval = True

	doc.needs_discount_approval = cint(needs_approval)

	if needs_approval:
		reason = cstr(doc.get("discount_reason")).strip()
		if len(reason) < config.DISCOUNT_REASON_MIN_LENGTH:
			frappe.throw(
				_(
					"Discount exceeds {0}% below the pricing-rule rate. Please give a Discount Reason of at "
					"least {1} characters on the Horizon tab; the document will route to a Sales Manager"
				).format(threshold, config.DISCOUNT_REASON_MIN_LENGTH),
				title=_("Discount Reason Required"),
			)
		if doc.docstatus == 1 and not is_manager:
			frappe.throw(
				_(
					"This {0} needs Sales Manager approval before it can be submitted (discount above {1}%). "
					"Use 'Submit for Discount Approval'."
				).format(_(doc.doctype), threshold),
				frappe.PermissionError,
				title=_("Approval Required"),
			)
	else:
		doc.discount_reason = None

	if doc.doctype == "Quotation":
		set_quotation_valid_till(doc)
		set_quotation_availability(doc)


def set_quotation_valid_till(doc):
	"""Server-created / mapped quotations never pass through the form script that applies CRM
	Settings ``default_valid_till``; without a date the "Quotation Expiring" notification can never
	fire. Blank ``valid_till`` -> transaction date + default (30 days when the setting is empty)."""
	if doc.get("valid_till"):
		return
	days = cint(frappe.db.get_single_value("CRM Settings", "default_valid_till")) or DEFAULT_VALID_TILL_DAYS
	doc.valid_till = add_days(getdate(doc.get("transaction_date") or frappe.utils.nowdate()), days)


def get_rule_rate(row, rule_cache=None):
	"""Price list rate after the pricing rules applied on the row (``pricing_rules`` JSON list).
	Without rules the rule rate is simply the price list rate.

	Mirrors ERPNext's ``apply_price_discount_rule`` with ``apply_multiple_pricing_rules``: discount
	percentages (and amounts) of stacked rules are **added** (5 + 8 + 10 = 23 %), not compounded; a
	rule with ``apply_discount_on_rate`` is applied on the already discounted rate; a "Rate" rule
	replaces the price list rate and resets earlier discounts.
	"""
	price_list_rate = flt(row.get("price_list_rate"))
	if not price_list_rate:
		return 0.0

	terms = get_rule_terms(row, rule_cache)
	base_rate = flt(terms.rule_price) if terms.rule_price else price_list_rate
	rule_rate = base_rate * (1 - terms.discount_pct / 100) - terms.discount_amount
	return flt(rule_rate, get_row_precision(row, "rule_rate"))


def get_rule_terms(row, rule_cache=None):
	"""``{rule_price, discount_pct, discount_amount}`` of the Price rules recorded on the row.

	``rule_price`` is the rate of the last "Rate" rule (it replaces the price list rate), else 0;
	``get_rule_rate`` and the agreed-price gross-up (``agreed_price.py``) share this reading so the
	Item Price written for an agreed rate nets to exactly that rate again.
	"""
	from erpnext.accounts.doctype.pricing_rule.utils import get_applied_pricing_rules

	terms = frappe._dict(rule_price=0.0, discount_pct=0.0, discount_amount=0.0)
	rule_cache = rule_cache if rule_cache is not None else {}
	for rule_name in get_applied_pricing_rules(row.get("pricing_rules")) or []:
		if rule_name not in rule_cache:
			rule_cache[rule_name] = frappe.db.get_value(
				"Pricing Rule",
				rule_name,
				[
					"price_or_product_discount",
					"rate_or_discount",
					"rate",
					"discount_percentage",
					"discount_amount",
					"apply_discount_on_rate",
				],
				as_dict=True,
			)
		rule = rule_cache[rule_name]
		if not rule or rule.price_or_product_discount != "Price":
			continue
		if rule.rate_or_discount == "Rate" and flt(rule.rate):
			terms.rule_price = flt(rule.rate)
			terms.discount_pct = 0.0
			terms.discount_amount = 0.0
		elif rule.rate_or_discount == "Discount Percentage":
			if cint(rule.apply_discount_on_rate) and terms.discount_pct:
				terms.discount_pct += (100 - terms.discount_pct) * flt(rule.discount_percentage) / 100
			else:
				terms.discount_pct += flt(rule.discount_percentage)
		elif rule.rate_or_discount == "Discount Amount":
			terms.discount_amount += flt(rule.discount_amount)
	return terms


def get_row_precision(row, fieldname):
	precision_fn = getattr(row, "precision", None)  # child-table row; plain dicts have none
	return precision_fn(fieldname) if callable(precision_fn) else 2


# ---------------------------------------------------------------------------------------------
# Agreed rate above the pricing-rule rate (Opportunity rate / customer-agreed price)
# ---------------------------------------------------------------------------------------------
def set_agreed_rate(row, rate):
	"""Represent ``rate`` (at or above the rule rate) on a Quotation / Sales Order row so that
	ERPNext's ``calculate_taxes_and_totals`` keeps it and ``price_list_rate`` stays the list price;
	``horizon_agreed_rate`` records it so later saves (and the Sales Order) keep it too.

	- No pricing rule on the row: ``margin_type = "Amount"``, ``margin_rate_or_amount = rate - list``
	  (what ERPNext's own ``calculate_margin`` writes for a rate above the list price).
	- Pricing rules on the row (e.g. Premium 5 %): ``discount_percentage = 0`` and
	  ``discount_amount = list - rate`` (negative above the list price); ``calculate_item_values``
	  then derives ``rate = price_list_rate - discount_amount``. A margin would be wiped by
	  ``calculate_margin``, which keeps only margins defined on the rules themselves.
	"""
	price_list_rate = flt(row.get("price_list_rate"))
	rate = flt(rate, get_row_precision(row, "rate"))
	row.rate = rate
	if row.meta.has_field("horizon_agreed_rate"):
		row.horizon_agreed_rate = rate
	row.discount_percentage = 0
	row.discount_amount = flt(price_list_rate - rate, get_row_precision(row, "discount_amount"))
	if not row.get("pricing_rules") and rate > price_list_rate:
		row.margin_type = "Amount"
		row.margin_rate_or_amount = flt(
			rate - price_list_rate, get_row_precision(row, "margin_rate_or_amount")
		)
	else:
		row.margin_type = None
		row.margin_rate_or_amount = 0


def keep_agreed_rate(row, pricing_rule_args=None):
	"""Called by the Quotation / Sales Order controllers (``overrides/selling_controllers.py``) right
	after ERPNext applied the pricing rules to a row: a row's ``horizon_agreed_rate`` (the rate the
	customer agreed, set from the Opportunity) above the rate the rules give is put back; ERPNext
	alone would lower it to the rule rate on every save. Only the explicit agreed rate counts: a
	server / API document that posts the list price as ``rate`` still gets its rule discounts.
	Returns True when the agreed rate was kept.
	"""
	args = pricing_rule_args or {}
	if args.get("validate_applied_rule") or args.get("price_or_product_discount") != "Price":
		return False
	agreed_rate = flt(row.get("horizon_agreed_rate"))
	if not agreed_rate or not flt(row.get("price_list_rate")):
		return False
	if agreed_rate <= flt(row.get("rate")) + RATE_TOLERANCE:
		return False
	set_agreed_rate(row, agreed_rate)
	return True


def sync_agreed_rate(row):
	"""``validate``: a rate typed over an agreed rate (rows without rules keep typed rates) becomes the
	new agreed rate when it is still above the rule rate; at or below it the agreed rate is dropped
	and the row is an ordinary (possibly discounted) row for ``validate_discounts``."""
	agreed_rate = flt(row.get("horizon_agreed_rate"))
	if not agreed_rate or abs(flt(row.rate) - agreed_rate) <= RATE_TOLERANCE:
		return
	row.horizon_agreed_rate = flt(row.rate) if flt(row.rate) > flt(row.rule_rate) + RATE_TOLERANCE else 0


def get_discount_over_rule_pct(rule_rate, rate):
	rule_rate, rate = flt(rule_rate), flt(rate)
	if rule_rate <= 0 or rate >= rule_rate:
		return 0.0
	return flt((rule_rate - rate) / rule_rate * 100, 2)


def validate_price_list_rates_untouched(doc):
	"""Non-managers may not type over ``price_list_rate``. Compared against Item Price for the
	document's selling price list / currency (rows whose UOM differs from the Item Price UOM are
	skipped to avoid conversion false positives). Only general prices and the document customer's
	own prices count: a customer-agreed Item Price (ADR-18) is no list price for anyone else."""
	price_list = doc.get("selling_price_list")
	if not price_list:
		return
	item_codes = list({row.item_code for row in doc.get("items", []) if row.item_code})
	if not item_codes:
		return

	customer = get_document_customer(doc)
	prices = frappe.get_all(
		"Item Price",
		filters={
			"price_list": price_list,
			"item_code": ["in", item_codes],
			"currency": doc.currency,
		},
		fields=["item_code", "uom", "customer", "price_list_rate", "valid_from", "valid_upto"],
	)
	by_item = {}
	for p in prices:
		if p.customer and p.customer != customer:
			continue
		by_item.setdefault(p.item_code, []).append(p)

	for row in doc.get("items", []):
		candidates = [
			p
			for p in by_item.get(row.item_code, [])
			if not p.uom or p.uom == row.uom or p.uom == row.stock_uom
		]
		if not candidates or not flt(row.price_list_rate):
			continue
		expected = [flt(p.price_list_rate) for p in candidates]
		if any(abs(flt(row.price_list_rate) - e) < 0.005 for e in expected):
			continue
		if row.uom != row.stock_uom:
			continue
		frappe.throw(
			_(
				"Row {0}: Price List Rate for {1} was changed manually ({2} instead of {3}). Only a Sales "
				"Manager may override list prices; use a discount instead."
			).format(
				row.idx,
				frappe.bold(row.item_code),
				frappe.format(row.price_list_rate, {"fieldtype": "Currency"}),
				frappe.format(expected[0], {"fieldtype": "Currency"}),
			),
			frappe.PermissionError,
			title=_("Ad-hoc Pricing Not Allowed"),
		)


def get_document_customer(doc):
	"""Customer of a Quotation (only when addressed to a Customer) or Sales Order."""
	if doc.doctype == "Quotation":
		return doc.get("party_name") if doc.get("quotation_to") == "Customer" else None
	return doc.get("customer")


# --- availability ----------------------------------------------------------------------------
def set_quotation_availability(doc):
	cache = {}
	base_date = getdate(doc.get("transaction_date") or frappe.utils.nowdate())
	for row in doc.get("items", []):
		if not row.item_code:
			continue
		if row.item_code not in cache:
			cache[row.item_code] = get_item_availability(row.item_code, qty=row.qty, company=doc.company)
		info = cache[row.item_code]
		row.available_qty = info["available_qty"]
		row.mfg_lead_days = info["mfg_lead_days"]
		lead = (
			config.STOCK_AVAILABLE_LEAD_DAYS
			if flt(info["available_qty"]) >= flt(row.qty)
			else info["mfg_lead_days"]
		)
		computed = add_days(base_date, cint(lead))
		if not row.get("expected_delivery_date") or getdate(row.expected_delivery_date) < computed:
			row.expected_delivery_date = computed


@frappe.whitelist()
def get_item_availability(item_code, qty=1, company=None):
	"""Free stock across the company's warehouses plus the manufacturing lead time of an item.

	Returns ``{available_qty, warehouses: {warehouse: free_qty}, mfg_lead_days, is_stock_item}``.
	"""
	frappe.has_permission("Item", "read", throw=True)
	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("Item {0} not found").format(item_code))

	filters = {"item_code": item_code}
	bins = frappe.get_all(
		"Bin", filters=filters, fields=["warehouse", "actual_qty", "reserved_qty", "projected_qty"]
	)
	if company:
		company_warehouses = set(frappe.get_all("Warehouse", filters={"company": company}, pluck="name"))
		bins = [b for b in bins if b.warehouse in company_warehouses]

	warehouses = {}
	for b in bins:
		free = flt(b.actual_qty) - flt(b.reserved_qty)
		if free:
			warehouses[b.warehouse] = flt(free, 3)

	return {
		"item_code": item_code,
		"requested_qty": flt(qty),
		"available_qty": flt(sum(warehouses.values()), 3),
		"warehouses": warehouses,
		"mfg_lead_days": get_mfg_lead_days(item_code),
		"is_stock_item": cint(frappe.get_cached_value("Item", item_code, "is_stock_item")),
	}


def get_mfg_lead_days(item_code, _depth=0, _cache=None):
	"""Manufacturing lead days of an item, exploded through its default BOM.

	For an item without a default BOM the lead time is its own ``lead_time_days`` (purchase lead).
	For a BOM item: ceil(operation minutes / 60 / working hours per day) **plus** the longest lead
	of its components, where sub-assemblies are themselves exploded the same way (up to
	``MAX_BOM_DEPTH`` levels; deeper levels fall back to the item's own lead time). The result is
	capped at ``MAX_MFG_LEAD_DAYS``. Items whose BOMs all finish on stock components therefore get
	the critical path of the whole tree, not just the first level.
	"""
	cache = _cache if _cache is not None else {}
	if item_code in cache:
		return cache[item_code]

	item = frappe.db.get_value("Item", item_code, ["default_bom", "lead_time_days"], as_dict=True)
	if not item:
		return 0
	if not item.default_bom or _depth >= MAX_BOM_DEPTH:
		cache[item_code] = cint(item.lead_time_days)
		return cache[item_code]

	op_minutes = flt(
		frappe.db.get_value("BOM Operation", {"parent": item.default_bom}, "sum(time_in_mins)") or 0
	)
	op_days = math.ceil(op_minutes / 60 / config.WORKING_HOURS_PER_DAY) if op_minutes else 0

	components = frappe.get_all(
		"BOM Item", filters={"parent": item.default_bom}, pluck="item_code", distinct=True
	)
	component_lead = 0
	for component in components:
		if component == item_code:
			continue  # defensive: a BOM must not contain its own item
		component_lead = max(component_lead, get_mfg_lead_days(component, _depth + 1, cache))

	cache[item_code] = min(cint(op_days + component_lead), MAX_MFG_LEAD_DAYS)
	return cache[item_code]


# ---------------------------------------------------------------------------------------------
# Delivery Note
# ---------------------------------------------------------------------------------------------
def lock_rates_to_sales_order(doc, method=None):
	"""Delivery Note / Sales Invoice ``before_validate`` hook: the price agreed on the Sales Order
	is the price delivered and invoiced.

	ERPNext re-runs the pricing engine on every mapped document at the *document's* quantity, so a
	partial delivery of a volume-discounted line (60 ordered at -8 % volume discount, 30 shipped)
	is re-priced without the volume rule and the invoice then fails "Cannot overbill". Rows that
	reference a Sales Order row (``so_detail``) copy ``SO_LOCKED_RATE_FIELDS`` from it; Sales
	Invoice rows that only reference a Delivery Note row (``dn_detail``) copy from that row, whose
	rates were locked the same way. ``pricing_rules`` is cleared on the copy and
	``ignore_pricing_rule`` is set so the engine neither re-evaluates nor "removes" the rules on a
	later save (``remove_pricing_rule_for_item`` would reset the rate to list price) - the Sales
	Order row keeps the record of the rules that produced the price. Runs before the controller's
	validate, so Selling Settings "Maintain Same Rate Throughout Sales Cycle" sees equal rates.
	Returns and documents without any order / delivery reference are untouched.
	"""
	if doc.get("is_return"):
		return
	items = doc.get("items") or []
	so_details = {row.so_detail for row in items if row.get("so_detail")}
	dn_details = {row.dn_detail for row in items if row.get("dn_detail") and not row.get("so_detail")}
	if not so_details and not dn_details:
		return

	source_rows = {}
	if so_details:
		for src in frappe.get_all(
			"Sales Order Item",
			filters={"name": ["in", list(so_details)]},
			fields=["name", *SO_LOCKED_RATE_FIELDS],
		):
			source_rows[src.name] = src
	if dn_details:
		for src in frappe.get_all(
			"Delivery Note Item",
			filters={"name": ["in", list(dn_details)]},
			fields=["name", *SO_LOCKED_RATE_FIELDS],
		):
			source_rows[src.name] = src

	locked = 0
	for row in items:
		src = source_rows.get(row.get("so_detail")) or source_rows.get(row.get("dn_detail"))
		if not src or not flt(src.rate):
			continue
		for fieldname in SO_LOCKED_RATE_FIELDS:
			if row.meta.has_field(fieldname):
				row.set(fieldname, src.get(fieldname))
		if row.meta.has_field("pricing_rules"):
			row.pricing_rules = None
		locked += 1
	if locked and doc.meta.has_field("ignore_pricing_rule"):
		doc.ignore_pricing_rule = 1


def validate_delivery_note(doc, method=None):
	"""Delivery Note ``validate`` hook.

	1. Short shipment (row qty below the Sales Order's pending qty) requires ``deviation_notes``.
	2. Quality gate: if any Work Order feeding the Sales Order has a failed Production Audit that
	   is not Action Closed, or a Rejected / Fail / Rework Quality Inspection without a later
	   Accepted one, a submitted Shipment Decision for that Sales Order is required and linked.
	3. ``received_by`` is mandatory once a ``customer_signature`` is captured.
	"""
	if doc.get("is_return"):
		return

	validate_short_shipment(doc)
	enforce_quality_gate(doc)

	if doc.get("customer_signature") and not cstr(doc.get("received_by")).strip():
		frappe.throw(
			_("Please record who received the goods (Received By) along with the customer signature"),
			title=_("Received By Required"),
		)


def get_so_pending_qty_map(so_detail_names):
	if not so_detail_names:
		return {}
	rows = frappe.get_all(
		"Sales Order Item",
		filters={"name": ["in", list(so_detail_names)]},
		fields=["name", "qty", "delivered_qty"],
	)
	return {r.name: flt(r.qty) - flt(r.delivered_qty) for r in rows}


def validate_short_shipment(doc):
	so_rows = [row for row in doc.get("items", []) if row.get("so_detail")]
	if not so_rows:
		return
	pending = get_so_pending_qty_map({row.so_detail for row in so_rows})
	short = []
	for row in so_rows:
		pending_qty = pending.get(row.so_detail)
		if pending_qty is None:
			continue
		if flt(row.qty) + 0.000001 < pending_qty:
			short.append(f"{row.item_code}: {flt(row.qty)} / {pending_qty}")
	if short and not cstr(doc.get("deviation_notes")).strip():
		frappe.throw(
			_(
				"This delivery is short against the Sales Order ({0}). Please explain the deviation in "
				"'Deviation Notes' on the Horizon tab."
			).format("; ".join(short)),
			title=_("Deviation Notes Required"),
		)


def get_quality_blockers(sales_orders, item_codes=None):
	"""Return a list of human-readable blockers for the Work Orders behind ``sales_orders``."""
	if not sales_orders:
		return []
	wo_filters = {"sales_order": ["in", list(sales_orders)], "docstatus": 1}
	if item_codes:
		wo_filters["production_item"] = ["in", list(item_codes)]
	work_orders = frappe.get_all("Work Order", filters=wo_filters, pluck="name")
	if not work_orders:
		return []

	blockers = []
	audits = frappe.get_all(
		"Production Audit",
		filters={
			"work_order": ["in", work_orders],
			"docstatus": 1,
			"audit_score": ["<", config.AUDIT_FAIL_SCORE],
			"status": ["!=", "Action Closed"],
		},
		fields=["name", "work_order", "audit_score"],
	)
	for a in audits:
		blockers.append(
			_("Production Audit {0} scored {1} on Work Order {2} and is not Action Closed").format(
				get_link_to_form("Production Audit", a.name), a.audit_score, a.work_order
			)
		)

	# Quality Inspections referencing Job Cards / Stock Entries of these Work Orders
	job_cards = frappe.get_all(
		"Job Card", filters={"work_order": ["in", work_orders]}, fields=["name", "work_order"]
	)
	stock_entries = frappe.get_all(
		"Stock Entry",
		filters={"work_order": ["in", work_orders], "docstatus": ["!=", 2]},
		fields=["name", "work_order"],
	)
	ref_to_wo = {jc.name: jc.work_order for jc in job_cards}
	ref_to_wo.update({se.name: se.work_order for se in stock_entries})
	if not ref_to_wo:
		return blockers

	inspections = frappe.get_all(
		"Quality Inspection",
		filters={"reference_name": ["in", list(ref_to_wo)], "docstatus": 1},
		fields=["name", "reference_name", "status", "qc_result", "report_date", "creation"],
		order_by="report_date asc, creation asc",
	)
	latest_by_wo = {}
	for qi in inspections:
		wo = ref_to_wo.get(qi.reference_name)
		failed = qi.status == "Rejected" or qi.qc_result in ("Fail", "Rework")
		if failed:
			latest_by_wo[wo] = qi
		elif qi.status == "Accepted":
			latest_by_wo.pop(wo, None)  # a later Accepted inspection clears the earlier failure
	for wo, qi in latest_by_wo.items():
		blockers.append(
			_("Quality Inspection {0} on Work Order {1} is {2}").format(
				get_link_to_form("Quality Inspection", qi.name), wo, qi.qc_result or qi.status
			)
		)
	return blockers


def enforce_quality_gate(doc):
	sales_orders = {row.against_sales_order for row in doc.get("items", []) if row.get("against_sales_order")}
	if not sales_orders:
		return
	item_codes = {row.item_code for row in doc.get("items", [])}
	blockers = get_quality_blockers(sales_orders, item_codes)
	if not blockers:
		return

	decision = get_valid_shipment_decision(doc.get("shipment_decision"), sales_orders)
	if not decision:
		decision = frappe.db.get_value(
			"Shipment Decision",
			{"sales_order": ["in", list(sales_orders)], "docstatus": 1, "decision": ["!=", ""]},
			"name",
			order_by="creation desc",
		)
	if not decision:
		frappe.throw(
			_(
				"Goods for this Sales Order have open quality issues:<br>- {0}<br><br>"
				"A submitted Shipment Decision for {1} is required before delivery. {2}"
			).format(
				"<br>- ".join(blockers),
				", ".join(sorted(sales_orders)),
				_("Create one here: {0}").format(
					f'<a href="/app/shipment-decision/new?sales_order={next(iter(sales_orders))}">'
					+ _("New Shipment Decision")
					+ "</a>"
				),
			),
			title=_("Shipment Decision Required"),
		)
	doc.shipment_decision = decision


def get_valid_shipment_decision(name, sales_orders):
	if not name:
		return None
	sd = frappe.db.get_value(
		"Shipment Decision", name, ["sales_order", "docstatus", "decision"], as_dict=True
	)
	if sd and sd.docstatus == 1 and sd.decision and sd.sales_order in sales_orders:
		return name
	return None


def on_submit_delivery_note(doc, method=None):
	"""Delivery Note ``on_submit`` hook: raise a DRAFT Sales Invoice so billing never lags
	dispatch. Skipped for returns and internal (inter-company) customers. Customer e-mail is
	handled by the "Horizon" Notification, not here."""
	if doc.get("is_return"):
		return
	if frappe.db.get_value("Customer", doc.customer, "is_internal_customer"):
		return

	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

	try:
		# The dispatcher (Sales User / Warehouse Manager) has no Sales Invoice create permission;
		# get_mapped_doc checks it on the target document, so the target carries the ignore flag.
		target = frappe.new_doc("Sales Invoice")
		target.flags.ignore_permissions = True
		si = make_sales_invoice(doc.name, target_doc=target)
		if not si.get("items"):
			return
		config.apply_default_dimensions(si)
		si.flags.ignore_permissions = True
		si.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title=f"Auto Sales Invoice failed for {doc.name}", message=frappe.get_traceback())
		frappe.msgprint(
			_("The draft Sales Invoice could not be created automatically; see Error Log."),
			indicator="orange",
			alert=True,
		)
		return

	link = get_link_to_form("Sales Invoice", si.name)
	doc.add_comment("Comment", _("Draft Sales Invoice {0} created automatically").format(link))
	frappe.msgprint(_("Draft Sales Invoice {0} created").format(link), alert=True)


# ---------------------------------------------------------------------------------------------
# Sales Invoice
# ---------------------------------------------------------------------------------------------
def validate_sales_invoice(doc, method=None):
	"""Sales Invoice ``validate`` hook: a stock invoice must come from a Delivery Note unless a
	Finance Director authorises it (audited via a comment). Returns, POS, update-stock invoices,
	internal customers and service / milestone invoices (any non-stock row) are exempt."""
	if doc.get("is_return") or doc.get("is_pos") or cint(doc.get("update_stock")):
		return
	if frappe.db.get_value("Customer", doc.customer, "is_internal_customer"):
		return
	items = doc.get("items", [])
	if not items or any(row.get("delivery_note") for row in items):
		return

	item_codes = {row.item_code for row in items if row.item_code}
	if not item_codes:
		return
	stock_flags = frappe.get_all(
		"Item", filters={"name": ["in", list(item_codes)]}, fields=["name", "is_stock_item"]
	)
	if any(not cint(f.is_stock_item) for f in stock_flags) or len(stock_flags) < len(item_codes):
		return  # service / milestone invoice

	if config.user_has_any_role(config.INVOICE_WITHOUT_DN_ROLES):
		if not doc.flags.horizon_dn_bypass_logged:
			config.add_audit_comment(
				doc, _("Invoice without Delivery Note authorised by {0}").format(frappe.session.user)
			)
			doc.flags.horizon_dn_bypass_logged = True
		return

	frappe.throw(
		_(
			"Sales Invoices for stock items must be created from a submitted Delivery Note "
			"(use 'Create > Sales Invoice' on the Delivery Note). A Finance Director can authorise an "
			"exception."
		),
		frappe.PermissionError,
		title=_("Delivery Note Required"),
	)

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Self-contained test masters for Horizon tests (prefix ``BRTEST``).

Tests run with ``--skip-test-records`` and must not depend on the demo data; everything they need
is created here, idempotently, inside the test transaction (rolled back by FrappeTestCase).
"""

import frappe
from frappe.utils import add_days, nowdate

COMPANY = "Horizon Manufacturing Ltd"
ABBR = "HML"
HSN_CODE = "84138190"
SELLING_PRICE_LIST = "Standard Selling"

USERS = {
	"brtest-pu@horizon.local": ("BRTEST Purchase User", ["Purchase User"]),
	"brtest-pm@horizon.local": ("BRTEST Procurement Manager", ["Purchase User", "Procurement Manager"]),
	"brtest-fd@horizon.local": (
		"BRTEST Finance Director",
		["Finance Director", "Accounts User", "Purchase User"],
	),
	"brtest-sales@horizon.local": ("BRTEST Sales User", ["Sales User"]),
	"brtest-sm@horizon.local": ("BRTEST Sales Manager", ["Sales User", "Sales Manager"]),
	"brtest-acc@horizon.local": ("BRTEST Accounts User", ["Accounts User"]),
	"brtest-ops@horizon.local": (
		"BRTEST Operations Head",
		["Operations Head", "Manufacturing Manager", "Manufacturing User", "Stock User"],
	),
	"brtest-mfg@horizon.local": ("BRTEST Manufacturing User", ["Manufacturing User", "Stock User"]),
	"brtest-qi@horizon.local": ("BRTEST Quality Inspector", ["Quality Inspector", "Quality Manager"]),
}


def ensure_users():
	for email, (first_name, roles) in USERS.items():
		ensure_user(email, first_name, roles)


def ensure_user(email, first_name, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		existing = {r.role for r in user.roles}
		missing = [r for r in roles if r not in existing]
		if missing:
			for role in missing:
				user.append("roles", {"role": role})
			user.flags.ignore_permissions = True
			user.save()
		return user
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"send_welcome_email": 0,
			"enabled": 1,
			"user_type": "System User",
			"roles": [{"role": r} for r in roles],
		}
	)
	user.flags.ignore_permissions = True
	user.insert()
	return user


def ensure_warehouse(base_name):
	name = f"{base_name} - {ABBR}"
	if frappe.db.exists("Warehouse", name):
		return name
	wh = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": base_name,
			"company": COMPANY,
			"parent_warehouse": f"All Warehouses - {ABBR}",
		}
	)
	wh.flags.ignore_permissions = True
	wh.insert()
	return wh.name


def ensure_item(item_code, item_group="Raw Material", valuation_rate=100, default_warehouse=None, **extra):
	if frappe.db.exists("Item", item_code):
		item = frappe.get_doc("Item", item_code)
		changed = False
		for key, value in extra.items():
			if item.get(key) != value:
				item.set(key, value)
				changed = True
		if changed:
			item.flags.ignore_permissions = True
			item.save()
		return item
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": item_group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"include_item_in_manufacturing": 1,
			"valuation_rate": valuation_rate,
			"gst_hsn_code": HSN_CODE,
			"item_defaults": [
				{
					"company": COMPANY,
					"default_warehouse": default_warehouse or ensure_warehouse("BRTEST Stores"),
				}
			],
			**extra,
		}
	)
	item.flags.ignore_permissions = True
	item.insert()
	return item


def ensure_supplier(name, blacklisted=False, reason=None):
	if frappe.db.exists("Supplier", name):
		return frappe.get_doc("Supplier", name)
	supplier = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": name,
			"supplier_group": "Raw Material",
			"supplier_type": "Company",
			"country": "India",
			"gst_category": "Unregistered",
			"is_blacklisted": 1 if blacklisted else 0,
			"blacklist_reason": reason or ("Repeated quality failures" if blacklisted else None),
			"blacklisted_on": nowdate() if blacklisted else None,
		}
	)
	supplier.flags.ignore_permissions = True
	supplier.insert()
	return supplier


def ensure_customer(name="BRTEST Customer"):
	if frappe.db.exists("Customer", name):
		return frappe.get_doc("Customer", name)
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": "Commercial",
			"territory": "India",
			"gst_category": "Unregistered",
		}
	)
	customer.flags.ignore_permissions = True
	customer.insert()
	return customer


def ensure_item_price(item_code, rate, price_list=SELLING_PRICE_LIST):
	existing = frappe.db.exists("Item Price", {"item_code": item_code, "price_list": price_list})
	if existing:
		frappe.db.set_value("Item Price", existing, "price_list_rate", rate)
		return existing
	price = frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": price_list,
			"price_list_rate": rate,
		}
	)
	price.flags.ignore_permissions = True
	price.insert()
	return price.name


def ensure_workstations():
	for name in ("Line A", "Line B"):
		if frappe.db.exists("Workstation", name):
			continue
		ws = frappe.get_doc(
			{
				"doctype": "Workstation",
				"workstation_name": name,
				"production_capacity": 1,
				"hour_rate": 100,
			}
		)
		ws.flags.ignore_permissions = True
		ws.insert()


def ensure_operation(name="BRTEST Assembly", workstation="Line A"):
	if frappe.db.exists("Operation", name):
		return name
	op = frappe.get_doc({"doctype": "Operation", "name": name, "workstation": workstation})
	op.flags.ignore_permissions = True
	op.insert()
	return op.name


def ensure_bom(item_code, rm_item_code, operation_minutes=30, rm_qty=1):
	existing = frappe.db.get_value("BOM", {"item": item_code, "docstatus": 1, "is_active": 1}, "name")
	if existing:
		return frappe.get_doc("BOM", existing)
	ensure_workstations()
	operation = ensure_operation()
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": item_code,
			"company": COMPANY,
			"quantity": 1,
			"currency": "INR",
			"conversion_rate": 1,
			"rm_cost_as_per": "Valuation Rate",
			"with_operations": 1,
			"is_default": 1,
			"is_active": 1,
			"operations": [
				{
					"operation": operation,
					"workstation": "Line A",
					"time_in_mins": operation_minutes,
					"hour_rate": 100,
				}
			],
			"items": [{"item_code": rm_item_code, "qty": rm_qty, "rate": 100, "uom": "Nos"}],
		}
	)
	bom.flags.ignore_permissions = True
	bom.insert()
	bom.submit()
	return bom


def make_stock(item_code, warehouse, qty, rate=100):
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"company": COMPANY,
			"stock_entry_type": "Material Receipt",
			"purpose": "Material Receipt",
			"items": [{"item_code": item_code, "qty": qty, "t_warehouse": warehouse, "basic_rate": rate}],
		}
	)
	with_dimensions(se)
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()
	return se


def ensure_employee(first_name="BRTEST Inspector"):
	existing = frappe.db.get_value("Employee", {"first_name": first_name, "company": COMPANY}, "name")
	if existing:
		return existing
	emp = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first_name,
			"company": COMPANY,
			"status": "Active",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2020-01-01",
		}
	)
	emp.flags.ignore_permissions = True
	emp.insert()
	return emp.name


def make_purchase_order(supplier, item_code, qty, rate, warehouse=None, **extra):
	po = frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"supplier": supplier,
			"company": COMPANY,
			"transaction_date": nowdate(),
			"schedule_date": add_days(nowdate(), 7),
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"rate": rate,
					"schedule_date": add_days(nowdate(), 7),
					"warehouse": warehouse or ensure_warehouse("BRTEST Stores"),
				}
			],
			**extra,
		}
	)
	return with_dimensions(po)


def make_purchase_receipt(supplier, item_code, qty, rate, warehouse=None, **extra):
	pr = frappe.get_doc(
		{
			"doctype": "Purchase Receipt",
			"supplier": supplier,
			"company": COMPANY,
			"posting_date": nowdate(),
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"received_qty": qty,
					"rate": rate,
					"warehouse": warehouse or ensure_warehouse("BRTEST Stores"),
				}
			],
			**extra,
		}
	)
	return with_dimensions(pr)


def make_quotation(customer, item_code, qty, rate, **extra):
	return with_dimensions(
		frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": customer,
				"company": COMPANY,
				"transaction_date": nowdate(),
				"selling_price_list": SELLING_PRICE_LIST,
				"items": [{"item_code": item_code, "qty": qty, "rate": rate}],
				**extra,
			}
		)
	)


def make_sales_order(customer, item_code, qty, rate, warehouse, delivery_days=7, **extra):
	so = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"customer": customer,
			"company": COMPANY,
			"transaction_date": nowdate(),
			"delivery_date": add_days(nowdate(), delivery_days),
			"selling_price_list": SELLING_PRICE_LIST,
			"items": [
				{
					"item_code": item_code,
					"qty": qty,
					"rate": rate,
					"warehouse": warehouse,
					"delivery_date": add_days(nowdate(), delivery_days),
				}
			],
			**extra,
		}
	)
	return with_dimensions(so)


def make_work_order(item_code, bom_no, qty, fg_warehouse, wip_warehouse, source_warehouse, **extra):
	wo = frappe.get_doc(
		{
			"doctype": "Work Order",
			"production_item": item_code,
			"bom_no": bom_no,
			"company": COMPANY,
			"qty": qty,
			"fg_warehouse": fg_warehouse,
			"wip_warehouse": wip_warehouse,
			"source_warehouse": source_warehouse,
			"planned_start_date": frappe.utils.now_datetime(),
			**extra,
		}
	)
	wo.set_work_order_operations()  # the form does this client-side via get_items_and_operations_from_bom
	return wo


def ensure_dimension_defaults():
	"""The demo data declares Accounting Dimensions with company defaults; make sure the default
	records exist so GL postings inside the tests can satisfy mandatory dimensions."""
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_dimensions

	dimensions, defaults = get_dimensions()
	doctype_by_field = {d.fieldname: d.document_type for d in dimensions}
	for fieldname, value in (defaults.get(COMPANY) or {}).items():
		doctype = doctype_by_field.get(fieldname)
		if not (doctype and value) or frappe.db.exists(doctype, value):
			continue
		meta = frappe.get_meta(doctype)
		doc = frappe.new_doc(doctype)
		name_field = meta.autoname.split(":", 1)[1] if (meta.autoname or "").startswith("field:") else None
		if name_field:
			doc.set(name_field, value)
		else:
			doc.name = value
		for df in meta.fields:
			if df.reqd and not doc.get(df.fieldname):
				if df.fieldtype == "Link" and df.options == "Company":
					doc.set(df.fieldname, COMPANY)
				elif df.fieldtype in ("Data", "Small Text"):
					doc.set(df.fieldname, value)
		doc.flags.ignore_permissions = True
		doc.insert()


def with_dimensions(doc):
	"""Apply the company's default Accounting Dimensions to a transactional test document."""
	from horizon_erp.horizon_operations.config import apply_default_dimensions

	return apply_default_dimensions(doc)


def setup_common():
	"""Masters shared by every Horizon test module.

	Selling Settings ``so_required`` / ``dn_required`` are switched off for the test transaction:
	the Horizon rules are enforced (and tested) in our own hooks with the Finance Director bypass,
	which the global standard switch would make unreachable.
	"""
	from horizon_erp.setup.workflows import setup_workflows

	frappe.db.set_single_value("Selling Settings", "so_required", "No")
	frappe.db.set_single_value("Selling Settings", "dn_required", "No")
	# as configured by demo_data: rates must stay equal through SO -> DN -> SI (DEF-05)
	frappe.db.set_single_value("Selling Settings", "maintain_same_sales_rate", 1)
	frappe.db.set_single_value("Selling Settings", "maintain_same_rate_action", "Stop")
	ensure_dimension_defaults()
	for workflow in setup_workflows():
		# Workflow Action e-mails attach a PDF print; wkhtmltopdf is not usable inside the test runner
		frappe.db.set_value("Workflow", workflow, "send_email_alert", 0, update_modified=False)
	ensure_users()
	stores = ensure_warehouse("BRTEST Stores")
	ensure_warehouse("BRTEST WIP")
	ensure_warehouse("BRTEST FG")
	ensure_item("BRTEST-RM", item_group="Raw Material", valuation_rate=100, default_warehouse=stores)
	ensure_item(
		"BRTEST-FG",
		item_group="Products",
		valuation_rate=500,
		default_warehouse=ensure_warehouse("BRTEST FG"),
		machine_hours_per_unit=10,
		default_line="Line A",
	)
	ensure_item_price("BRTEST-FG", 1000)
	ensure_supplier("BRTEST Blacklisted", blacklisted=True)
	ensure_supplier("BRTEST Clean")
	ensure_customer("BRTEST Customer")
	ensure_workstations()
	return frappe._dict(
		stores=stores,
		wip=f"BRTEST WIP - {ABBR}",
		fg=f"BRTEST FG - {ABBR}",
	)

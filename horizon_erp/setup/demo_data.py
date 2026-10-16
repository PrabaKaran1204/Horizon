# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Reproducible demo-data / configuration script for Horizon Manufacturing Ltd.

Run with::

	bench --site horizon.local execute horizon_erp.setup.demo_data.setup_all

Every step is idempotent (``frappe.db.exists`` before insert, update where sensible) and
commits at its end, so the script can be re-run after a partial failure. The Python data
structures below are also the source of truth for the CSV exports in ``horizon_erp/data/``
(see :func:`export_csvs`).

Design notes
- GSTINs: the assignment brief's ``27AABCU9602H1Z0`` fails the GST check-digit algorithm, so
  the checksum-valid variants with the same PAN are used (``27AABCU9602H1Z9`` / ``07AABCU9602H1ZB``).
  Party GSTINs are generated from a per-party PAN with :func:`make_gstin` and verified with
  India Compliance's ``validate_gstin`` before use.
- Item-group GST rates (Equipment 5 %, Spares 12 %, Components 5 %, Raw Material / Sub
  Assemblies 18 %) come from the brief and MUST be confirmed against HSN by the client's CA.
- Cost Center Allocation is created from the leaf ``Mfg - Shared - HML`` (transactions can only
  post to leaf cost centres, so allocating from the ``Manufacturing - HML`` group is meaningless).
- The serialised motor is received through a Stock Entry (Material Receipt, ``is_opening=Yes``)
  because that path auto-creates Serial Nos from ``serial_no`` text; batch and plain items go
  through a Stock Reconciliation (purpose Opening Stock).
"""

import csv
import os
import traceback

import frappe
from frappe.utils import flt

COMPANY = "Horizon Manufacturing Ltd"
ABBR = "HML"
CURRENCY = "INR"
OPENING_DATE = "2026-04-01"
DEMO_PASSWORD = "Horizon@123"

RM_WAREHOUSE = f"HQ Raw Materials - {ABBR}"
FG_WAREHOUSE = f"HQ Finished Goods - {ABBR}"
WIP_WAREHOUSE = f"HQ Work In Progress - {ABBR}"
DEL_FG_WAREHOUSE = f"DEL Finished Goods - {ABBR}"

# ---------------------------------------------------------------------------
# GSTIN helpers
# ---------------------------------------------------------------------------

_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(gstin_without_check_digit):
	"""Standard GSTIN mod-36 check digit (same algorithm as India Compliance)."""
	factor = 1
	total = 0
	mod = len(_GSTIN_CHARS)
	for char in gstin_without_check_digit:
		digit = factor * _GSTIN_CHARS.find(char)
		digit = (digit // mod) + (digit % mod)
		total += digit
		factor = 2 if factor == 1 else 1
	return _GSTIN_CHARS[(mod - (total % mod)) % mod]


def make_gstin(state_code, pan, entity_no="1"):
	"""Build a checksum-valid GSTIN ``<state><PAN><entity>Z<check>``."""
	base = f"{state_code}{pan}{entity_no}Z"
	return base + gstin_check_digit(base)


def is_valid_gstin(gstin):
	"""Verify with India Compliance's validator (falls back to local checksum)."""
	try:
		from india_compliance.gst_india.utils import validate_gstin

		validate_gstin(gstin)
		return True
	except ImportError:
		return gstin[-1] == gstin_check_digit(gstin[:-1])
	except Exception:
		return False


# ---------------------------------------------------------------------------
# Master data (source of truth for the site AND the CSV exports)
# ---------------------------------------------------------------------------

COMPANY_ADDRESSES = [
	{
		"address_title": "Horizon HQ Mumbai",
		"address_line1": "Plot 14, MIDC Andheri East",
		"city": "Mumbai",
		"state": "Maharashtra",
		"pincode": "400093",
		"gstin": "27AABCU9602H1Z9",
		"branch": "Mumbai HQ",
	},
	{
		"address_title": "Horizon DC Delhi",
		"address_line1": "Khasra 22, Okhla Industrial Area Phase II",
		"city": "New Delhi",
		"state": "Delhi",
		"pincode": "110020",
		"gstin": "07AABCU9602H1ZB",
		"branch": "Delhi DC",
	},
]

COST_CENTERS = [
	{"cost_center_name": "Manufacturing", "parent": None, "is_group": 1},
	{"cost_center_name": "Mfg - Equipment", "parent": "Manufacturing", "is_group": 0},
	{"cost_center_name": "Mfg - Spares", "parent": "Manufacturing", "is_group": 0},
	{"cost_center_name": "Mfg - Components", "parent": "Manufacturing", "is_group": 0},
	{"cost_center_name": "Mfg - Shared", "parent": "Manufacturing", "is_group": 0},
	{"cost_center_name": "Sales", "parent": None, "is_group": 0},
	{"cost_center_name": "Admin", "parent": None, "is_group": 0},
	{"cost_center_name": "R&D", "parent": None, "is_group": 0},
]

COST_CENTER_ALLOCATION = {
	"main_cost_center": "Mfg - Shared",
	"valid_from": OPENING_DATE,
	"allocation_percentages": [
		{"cost_center": "Mfg - Equipment", "percentage": 50},
		{"cost_center": "Mfg - Spares", "percentage": 30},
		{"cost_center": "Mfg - Components", "percentage": 20},
	],
}

WAREHOUSES = [
	{
		"warehouse_name": "Mumbai HQ",
		"parent": "All Warehouses",
		"is_group": 1,
		"address": "Horizon HQ Mumbai",
	},
	{"warehouse_name": "Delhi DC", "parent": "All Warehouses", "is_group": 1, "address": "Horizon DC Delhi"},
	{
		"warehouse_name": "HQ Raw Materials",
		"parent": "Mumbai HQ",
		"is_group": 0,
		"address": "Horizon HQ Mumbai",
	},
	{"warehouse_name": "HQ QC Hold", "parent": "Mumbai HQ", "is_group": 0, "address": "Horizon HQ Mumbai"},
	{
		"warehouse_name": "HQ Work In Progress",
		"parent": "Mumbai HQ",
		"is_group": 0,
		"address": "Horizon HQ Mumbai",
	},
	{
		"warehouse_name": "HQ Finished Goods",
		"parent": "Mumbai HQ",
		"is_group": 0,
		"address": "Horizon HQ Mumbai",
	},
	{
		"warehouse_name": "HQ Rejected",
		"parent": "Mumbai HQ",
		"is_group": 0,
		"address": "Horizon HQ Mumbai",
		"is_rejected_warehouse": 1,
	},
	{"warehouse_name": "HQ Scrap", "parent": "Mumbai HQ", "is_group": 0, "address": "Horizon HQ Mumbai"},
	{
		"warehouse_name": "DEL Finished Goods",
		"parent": "Delhi DC",
		"is_group": 0,
		"address": "Horizon DC Delhi",
	},
	{
		"warehouse_name": "DEL Goods In Transit",
		"parent": "Delhi DC",
		"is_group": 0,
		"address": "Horizon DC Delhi",
		"warehouse_type": "Transit",
	},
]

# Item groups: (name, gst template title). Rates from the brief; confirm against HSN with the CA.
ITEM_GROUPS = [
	{"item_group_name": "Equipment", "gst_template": "GST 5%"},
	{"item_group_name": "Spares", "gst_template": "GST 12%"},
	{"item_group_name": "Components", "gst_template": "GST 5%"},
	{"item_group_name": "Sub Assemblies", "gst_template": "GST 18%"},
	{"item_group_name": "Raw Material", "gst_template": "GST 18%"},
	{"item_group_name": "Fixed Assets", "gst_template": None},
]

UOMS = ["Nos", "Kg", "Meter", "Litre", "Set"]

# kind: raw | component | sub_assembly | equipment | spare | fixed_asset
ITEMS = [
	# --- Raw Material ---------------------------------------------------------
	{
		"item_code": "RM-STEEL-PLATE",
		"item_name": "MS Steel Plate 6mm",
		"item_group": "Raw Material",
		"kind": "raw",
		"stock_uom": "Kg",
		"valuation_rate": 65,
		"lead_time_days": 28,
		"criticality": "A",
		"reorder_level": 400,
		"reorder_qty": 1000,
		"gst_hsn_code": "72085110",
		"default_supplier": "Mumbai Steel Traders",
		"qi_template": "RM Steel Incoming",
	},
	{
		"item_code": "RM-MS-CHANNEL",
		"item_name": "MS Channel 75x40",
		"item_group": "Raw Material",
		"kind": "raw",
		"stock_uom": "Meter",
		"valuation_rate": 180,
		"lead_time_days": 21,
		"criticality": "A",
		"reorder_level": 150,
		"reorder_qty": 400,
		"gst_hsn_code": "72163100",
		"default_supplier": "Mumbai Steel Traders",
		"qi_template": "RM Steel Incoming",
	},
	{
		"item_code": "RM-WELD-ROD",
		"item_name": "Welding Rod E6013",
		"item_group": "Raw Material",
		"kind": "raw",
		"stock_uom": "Kg",
		"valuation_rate": 120,
		"lead_time_days": 2,
		"criticality": "C",
		"reorder_level": 50,
		"reorder_qty": 100,
		"has_batch_no": 1,
		"create_new_batch": 1,
		"batch_number_series": "WR-.####",
		"gst_hsn_code": "83111000",
		"default_supplier": "ABC Supplies",
	},
	{
		"item_code": "RM-PAINT-GREY",
		"item_name": "Industrial Paint Grey",
		"item_group": "Raw Material",
		"kind": "raw",
		"stock_uom": "Litre",
		"valuation_rate": 350,
		"lead_time_days": 7,
		"criticality": "B",
		"reorder_level": 40,
		"reorder_qty": 100,
		"has_batch_no": 1,
		"create_new_batch": 1,
		"batch_number_series": "PG-.####",
		"gst_hsn_code": "32081010",
	},
	{
		"item_code": "RM-BOLT-M10",
		"item_name": "Hex Bolt M10x40",
		"item_group": "Raw Material",
		"kind": "raw",
		"stock_uom": "Nos",
		"valuation_rate": 8,
		"lead_time_days": 2,
		"criticality": "C",
		"reorder_level": 500,
		"reorder_qty": 2000,
		"gst_hsn_code": "73181500",
		"default_supplier": "Delhi Fastener House",
		"qi_template": "Fastener Incoming",
	},
	{
		"item_code": "RM-BOLT-M8",
		"item_name": "Hex Bolt M8x25",
		"item_group": "Raw Material",
		"kind": "raw",
		"stock_uom": "Nos",
		"valuation_rate": 5,
		"lead_time_days": 2,
		"criticality": "C",
		"reorder_level": 500,
		"reorder_qty": 2000,
		"gst_hsn_code": "73181500",
		"default_supplier": "Delhi Fastener House",
		"qi_template": "Fastener Incoming",
	},
	# --- Components ------------------------------------------------------------
	{
		"item_code": "CMP-MOTOR-5HP",
		"item_name": "Electric Motor 5HP",
		"item_group": "Components",
		"kind": "component",
		"stock_uom": "Nos",
		"valuation_rate": 18000,
		"lead_time_days": 14,
		"criticality": "A",
		"reorder_level": 5,
		"reorder_qty": 10,
		"has_serial_no": 1,
		"serial_no_series": "MOT-.####",
		"gst_hsn_code": "85015210",
		"default_supplier": "Pune Electricals",
		"qi_template": "Electrical Incoming",
	},
	{
		"item_code": "CMP-GEARBOX",
		"item_name": "Worm Gearbox 1:20",
		"item_group": "Components",
		"kind": "component",
		"stock_uom": "Nos",
		"valuation_rate": 12000,
		"lead_time_days": 21,
		"criticality": "A",
		"reorder_level": 3,
		"reorder_qty": 6,
		"gst_hsn_code": "84834000",
		"default_supplier": "Bharat Castings Ltd",
	},
	{
		"item_code": "CMP-BEARING-6205",
		"item_name": "Ball Bearing 6205",
		"item_group": "Components",
		"kind": "component",
		"stock_uom": "Nos",
		"valuation_rate": 250,
		"lead_time_days": 5,
		"criticality": "B",
		"reorder_level": 100,
		"reorder_qty": 200,
		"gst_hsn_code": "84821011",
		"default_supplier": "ABC Corp",
	},
	{
		"item_code": "CMP-SHAFT-25",
		"item_name": "Drive Shaft 25mm",
		"item_group": "Components",
		"kind": "component",
		"stock_uom": "Nos",
		"valuation_rate": 1400,
		"lead_time_days": 10,
		"criticality": "B",
		"reorder_level": 10,
		"reorder_qty": 20,
		"gst_hsn_code": "84831091",
	},
	{
		"item_code": "CMP-SEAL-KIT",
		"item_name": "Mechanical Seal Kit",
		"item_group": "Components",
		"kind": "component",
		"stock_uom": "Nos",
		"valuation_rate": 900,
		"lead_time_days": 7,
		"criticality": "B",
		"reorder_level": 20,
		"reorder_qty": 40,
		"gst_hsn_code": "84842000",
		"default_supplier": "ABC Corp",
	},
	{
		"item_code": "CMP-CONTACTOR",
		"item_name": "Contactor 25A",
		"item_group": "Components",
		"kind": "component",
		"stock_uom": "Nos",
		"valuation_rate": 1100,
		"lead_time_days": 5,
		"criticality": "B",
		"reorder_level": 10,
		"reorder_qty": 20,
		"gst_hsn_code": "85364900",
		"default_supplier": "Pune Electricals",
		"qi_template": "Electrical Incoming",
	},
	{
		"item_code": "CMP-CASTING",
		"item_name": "Pump Casing Casting",
		"item_group": "Components",
		"kind": "component",
		"stock_uom": "Nos",
		"valuation_rate": 4500,
		"lead_time_days": 28,
		"criticality": "A",
		"reorder_level": 6,
		"reorder_qty": 12,
		"gst_hsn_code": "84139190",
		"default_supplier": "Bharat Castings Ltd",
	},
	{
		"item_code": "CMP-BELT-1M",
		"item_name": "Conveyor Belt 1m",
		"item_group": "Components",
		"kind": "component",
		"stock_uom": "Nos",
		"valuation_rate": 2200,
		"lead_time_days": 10,
		"criticality": "B",
		"reorder_level": 5,
		"reorder_qty": 10,
		"gst_hsn_code": "84314990",
	},
	# --- Sub Assemblies (manufactured) ------------------------------------------
	{
		"item_code": "SA-MOTOR-01",
		"item_name": "Motor Assembly",
		"item_group": "Sub Assemblies",
		"kind": "sub_assembly",
		"stock_uom": "Nos",
		"valuation_rate": 0,
		"machine_hours_per_unit": 1.5,
		"gst_hsn_code": "85015210",
	},
	{
		"item_code": "SA-HOUSING-01",
		"item_name": "Pump Housing Assembly",
		"item_group": "Sub Assemblies",
		"kind": "sub_assembly",
		"stock_uom": "Nos",
		"valuation_rate": 0,
		"machine_hours_per_unit": 2.5,
		"gst_hsn_code": "84139190",
	},
	{
		"item_code": "SA-PANEL-01",
		"item_name": "Control Panel",
		"item_group": "Sub Assemblies",
		"kind": "sub_assembly",
		"stock_uom": "Nos",
		"valuation_rate": 0,
		"machine_hours_per_unit": 1.5,
		"gst_hsn_code": "85364900",
	},
	{
		"item_code": "SA-FRAME-01",
		"item_name": "Conveyor Frame",
		"item_group": "Sub Assemblies",
		"kind": "sub_assembly",
		"stock_uom": "Nos",
		"valuation_rate": 0,
		"machine_hours_per_unit": 3,
		"gst_hsn_code": "84314990",
	},
	{
		"item_code": "SA-DRIVE-01",
		"item_name": "Drive Unit",
		"item_group": "Sub Assemblies",
		"kind": "sub_assembly",
		"stock_uom": "Nos",
		"valuation_rate": 0,
		"machine_hours_per_unit": 2,
		"gst_hsn_code": "84834000",
	},
	# --- Equipment (make-to-order) ----------------------------------------------
	{
		"item_code": "HZ-PUMP-100",
		"item_name": "Industrial Pump Unit 100",
		"item_group": "Equipment",
		"kind": "equipment",
		"stock_uom": "Nos",
		"valuation_rate": 0,
		"standard_rate": 185000,
		"machine_hours_per_unit": 6,
		"default_line": "Any",
		"lead_time_days": 21,
		"has_serial_no": 1,
		"serial_no_series": "PMP-.####",
		"gst_hsn_code": "84137010",
		"qi_delivery_template": "Assembly Inspection",
	},
	{
		"item_code": "HZ-CONV-200",
		"item_name": "Conveyor Module 200",
		"item_group": "Equipment",
		"kind": "equipment",
		"stock_uom": "Nos",
		"valuation_rate": 0,
		"standard_rate": 240000,
		"machine_hours_per_unit": 8,
		"default_line": "Line A",
		"lead_time_days": 28,
		"has_serial_no": 1,
		"serial_no_series": "CNV-.####",
		"gst_hsn_code": "84283900",
		"qi_delivery_template": "Assembly Inspection",
	},
	# --- Spares (make-to-stock, seasonal) ---------------------------------------
	{
		"item_code": "SP-IMPELLER",
		"item_name": "Pump Impeller",
		"item_group": "Spares",
		"kind": "spare",
		"stock_uom": "Nos",
		"valuation_rate": 3200,
		"standard_rate": 6500,
		"machine_hours_per_unit": 0.5,
		"criticality": "B",
		"demand_pattern": "Seasonal Q4",
		"reorder_level": 20,
		"reorder_qty": 50,
		"gst_hsn_code": "84139190",
	},
	{
		"item_code": "SP-SEAL-SET",
		"item_name": "Seal Replacement Set",
		"item_group": "Spares",
		"kind": "spare",
		"stock_uom": "Nos",
		"valuation_rate": 1100,
		"standard_rate": 2400,
		"criticality": "B",
		"demand_pattern": "Seasonal Q4",
		"reorder_level": 30,
		"reorder_qty": 60,
		"gst_hsn_code": "84842000",
	},
	{
		"item_code": "SP-BELT-KIT",
		"item_name": "Belt Replacement Kit",
		"item_group": "Spares",
		"kind": "spare",
		"stock_uom": "Nos",
		"valuation_rate": 2600,
		"standard_rate": 5200,
		"criticality": "C",
		"demand_pattern": "Seasonal Q4",
		"reorder_level": 10,
		"reorder_qty": 30,
		"gst_hsn_code": "84314990",
	},
	# --- Fixed asset -------------------------------------------------------------
	{
		"item_code": "FA-CNC-LATHE",
		"item_name": "CNC Lathe 2m",
		"item_group": "Fixed Assets",
		"kind": "fixed_asset",
		"stock_uom": "Nos",
		"valuation_rate": 0,
		"asset_category": "Production Equipment",
		"gst_hsn_code": "84581100",
	},
]

KIND_DEFAULTS = {
	# kind: (default warehouse, cost centre name without abbr, reorder warehouse)
	"raw": (RM_WAREHOUSE, "Mfg - Components", RM_WAREHOUSE),
	"component": (RM_WAREHOUSE, "Mfg - Components", RM_WAREHOUSE),
	"sub_assembly": (WIP_WAREHOUSE, "Mfg - Equipment", None),
	"equipment": (FG_WAREHOUSE, "Mfg - Equipment", None),
	"spare": (FG_WAREHOUSE, "Mfg - Spares", FG_WAREHOUSE),
	"fixed_asset": (None, "Admin", None),
}

SELLING_KINDS = {"equipment", "spare"}
BUYING_KINDS = {"raw", "component"}

CUSTOMER_GROUPS = ["Premium", "Standard"]
TERRITORIES = ["North", "West"]

CUSTOMERS = [
	{
		"customer_name": "Tata Precision Works",
		"customer_group": "Premium",
		"territory": "West",
		"state": "Maharashtra",
		"state_code": "27",
		"pan": "AABCT4512Q",
		"address_line1": "Gat 118, Chakan MIDC Phase II",
		"city": "Pune",
		"pincode": "410501",
		"contact": {"first_name": "Rohan", "last_name": "Deshmukh", "email": "rohan@tataprecision.example"},
		"credit_limit": 2500000,
	},
	{
		"customer_name": "Larsen Industrial Supplies",
		"customer_group": "Premium",
		"territory": "West",
		"state": "Maharashtra",
		"state_code": "27",
		"pan": "AABCL7823R",
		"address_line1": "Unit 9, Taloja Industrial Estate",
		"city": "Navi Mumbai",
		"pincode": "410208",
		"contact": {"first_name": "Meera", "last_name": "Iyer", "email": "meera@larsenind.example"},
		"credit_limit": 2500000,
	},
	{
		"customer_name": "Delhi Metro Fabricators",
		"customer_group": "Standard",
		"territory": "North",
		"state": "Delhi",
		"state_code": "07",
		"pan": "AADCD3391K",
		"address_line1": "B-44, Mayapuri Industrial Area Phase I",
		"city": "New Delhi",
		"pincode": "110064",
		"contact": {"first_name": "Sandeep", "last_name": "Kapoor", "email": "sandeep@dmfab.example"},
		"default_price_list": "North Selling",
	},
	{
		"customer_name": "Haryana Agro Machines",
		"customer_group": "Standard",
		"territory": "North",
		"state": "Haryana",
		"state_code": "06",
		"pan": "AAECH5520M",
		"address_line1": "Plot 31, Sector 37, HSIIDC",
		"city": "Gurugram",
		"pincode": "122001",
		"contact": {"first_name": "Vikram", "last_name": "Yadav", "email": "vikram@haryanaagro.example"},
		"default_price_list": "North Selling",
	},
	{
		"customer_name": "Bharat Mining Co",
		"customer_group": "Standard",
		"territory": "West",
		"state": "Gujarat",
		"state_code": "24",
		"pan": "AACCB6618N",
		"address_line1": "Survey 77, GIDC Makarpura",
		"city": "Vadodara",
		"pincode": "390010",
		"contact": {"first_name": "Kiran", "last_name": "Patel", "email": "kiran@bharatmining.example"},
	},
	{
		"customer_name": "ABC Corp",
		"customer_group": "Standard",
		"territory": "West",
		"state": "Maharashtra",
		"state_code": "27",
		"pan": "AAACA1234B",
		"address_line1": "12, Bhandup Industrial Estate",
		"city": "Mumbai",
		"pincode": "400078",
		"contact": {"first_name": "Anil", "last_name": "Bhatia", "email": "anil@abccorp.example"},
	},
]

SUPPLIERS = [
	{
		"supplier_name": "ABC Supplies",
		"supplier_group": "Raw Material",
		"state": "Maharashtra",
		"state_code": "27",
		"pan": "AABCA9981C",
		"address_line1": "Shed 5, Bhiwandi Industrial Park",
		"city": "Thane",
		"pincode": "421302",
		"contact": {"first_name": "Suresh", "last_name": "Rane", "email": "suresh@abcsupplies.example"},
		"is_blacklisted": 1,
		"blacklist_reason": "Repeated weld-quality rejections Q1 FY26-27",
		"blacklisted_on": "2026-07-15",
	},
	{
		"supplier_name": "ABC Corp",
		"supplier_group": "Raw Material",
		"state": "Maharashtra",
		"state_code": "27",
		"pan": "AAACA1234B",  # same party as the customer "ABC Corp"
		"address_line1": "12, Bhandup Industrial Estate",
		"city": "Mumbai",
		"pincode": "400078",
		"contact": {"first_name": "Anil", "last_name": "Bhatia", "email": "anil@abccorp.example"},
	},
	{
		"supplier_name": "Mumbai Steel Traders",
		"supplier_group": "Raw Material",
		"state": "Maharashtra",
		"state_code": "27",
		"pan": "AAFCM2210D",
		"address_line1": "Darukhana, Reay Road",
		"city": "Mumbai",
		"pincode": "400010",
		"contact": {"first_name": "Haresh", "last_name": "Shah", "email": "haresh@mumbaisteel.example"},
	},
	{
		"supplier_name": "Pune Electricals",
		"supplier_group": "Electrical",
		"state": "Maharashtra",
		"state_code": "27",
		"pan": "AAHCP4471E",
		"address_line1": "J-Block, MIDC Bhosari",
		"city": "Pune",
		"pincode": "411026",
		"contact": {"first_name": "Prakash", "last_name": "Kulkarni", "email": "prakash@puneelec.example"},
	},
	{
		"supplier_name": "Delhi Fastener House",
		"supplier_group": "Raw Material",
		"state": "Delhi",
		"state_code": "07",
		"pan": "AAJCD8865F",
		"address_line1": "Shop 3, Chawri Bazar",
		"city": "New Delhi",
		"pincode": "110006",
		"contact": {"first_name": "Rakesh", "last_name": "Gupta", "email": "rakesh@delhifastener.example"},
	},
	{
		"supplier_name": "Bharat Castings Ltd",
		"supplier_group": "Raw Material",
		"state": "Gujarat",
		"state_code": "24",
		"pan": "AABCB7732G",
		"address_line1": "Plot 210, GIDC Rajkot",
		"city": "Rajkot",
		"pincode": "360003",
		"contact": {"first_name": "Jayesh", "last_name": "Mehta", "email": "jayesh@bharatcastings.example"},
	},
]

SUPPLIER_GROUPS = ["Raw Material", "Services", "Electrical"]

PRICE_LISTS = [{"price_list_name": "North Selling", "selling": 1, "buying": 0, "currency": CURRENCY}]
NORTH_PRICE_FACTOR = 1.03

PRICING_RULES = [
	{
		"title": "PR-PREMIUM-5",
		"apply_on": "Item Group",
		"item_groups": ["Equipment", "Spares", "Components"],
		"applicable_for": "Customer Group",
		"customer_group": "Premium",
		"discount_percentage": 5,
		"priority": "1",
		"apply_multiple_pricing_rules": 1,
	},
	{
		"title": "PR-COMPONENTS-3",
		"apply_on": "Item Group",
		"item_groups": ["Components"],
		"discount_percentage": 3,
		"priority": "1",
		"apply_multiple_pricing_rules": 1,
	},
	{
		"title": "PR-VOLUME-8",
		"apply_on": "Item Group",
		"item_groups": ["Spares", "Components"],
		"min_qty": 51,
		"discount_percentage": 8,
		"priority": "2",
		"apply_multiple_pricing_rules": 1,
	},
	{
		"title": "PR-Q4-SPARES-10",
		"apply_on": "Item Group",
		"item_groups": ["Spares"],
		"valid_from": "2026-10-01",
		"valid_upto": "2026-12-31",
		"discount_percentage": 10,
		"priority": "3",
		"apply_multiple_pricing_rules": 1,
	},
]

WORKSTATIONS = [
	{
		"workstation_name": "Line A",
		"hour_rate": 1200,
		"description": "Main assembly / welding / paint line. Planned downtime 10%, setup 45 min per changeover.",
		"working_hours": [("06:00:00", "14:00:00"), ("14:01:00", "22:00:00")],
	},
	{
		"workstation_name": "Line B",
		"hour_rate": 1000,
		"description": "Cutting / machining / wiring line. Planned downtime 15%, setup 30 min per changeover.",
		"working_hours": [("06:00:00", "14:00:00"), ("14:01:00", "22:00:00")],
	},
]

OPERATIONS = [
	{
		"name": "Cutting",
		"workstation": "Line B",
		"description": "Plasma / shear cutting of plate and channel",
	},
	{"name": "Welding", "workstation": "Line A", "description": "MIG / arc welding of frames and housings"},
	{"name": "Painting", "workstation": "Line A", "description": "Primer + industrial grey top coat"},
	{"name": "Machining", "workstation": "Line B", "description": "Turning / boring of castings and shafts"},
	{"name": "Assembly", "workstation": "Line A", "description": "Mechanical assembly and fastening"},
	{"name": "Wiring", "workstation": "Line B", "description": "Control panel wiring and termination"},
	{"name": "Testing", "workstation": "Line A", "description": "Functional / load test before release"},
]

QI_TEMPLATES = {
	"RM Steel Incoming": [
		{"specification": "Thickness mm", "numeric": 1, "min_value": 5.8, "max_value": 6.2},
		{"specification": "Surface Finish", "numeric": 0, "value": "No rust/scale"},
		{"specification": "Hardness HB", "numeric": 1, "min_value": 120, "max_value": 160},
	],
	"Electrical Incoming": [
		{"specification": "Insulation Test MOhm", "numeric": 1, "min_value": 1, "max_value": 10000},
		{"specification": "Visual", "numeric": 0, "value": "No damage, nameplate legible"},
		{"specification": "Voltage Rating", "numeric": 0, "value": "415V 3Ph 50Hz"},
	],
	"Fastener Incoming": [
		{"specification": "Thread Gauge Go/No-Go", "numeric": 0, "value": "Go passes, No-Go fails"},
		{"specification": "Count", "numeric": 0, "value": "Matches packing slip"},
	],
	"Weld Inspection": [
		{"specification": "Weld Depth mm", "numeric": 1, "min_value": 4, "max_value": 6},
		{"specification": "Bead Visual", "numeric": 0, "value": "Uniform, no undercut/porosity"},
		{"specification": "Crack Test", "numeric": 0, "value": "No cracks (DPT)"},
	],
	"Paint Inspection": [
		{"specification": "DFT um", "numeric": 1, "min_value": 60, "max_value": 80},
	],
	"Assembly Inspection": [
		{"specification": "Torque Nm", "numeric": 1, "min_value": 45, "max_value": 50},
		{"specification": "Alignment", "numeric": 0, "value": "Within 0.05 mm TIR"},
	],
}

# BOMs are listed bottom-up: sub-assemblies first so their BOM names exist for the parents.
BOMS = [
	{
		"item": "SA-MOTOR-01",
		"items": [("CMP-MOTOR-5HP", 1), ("RM-BOLT-M10", 8), ("CMP-CONTACTOR", 1)],
		"operations": [("Assembly", "Line A", 45), ("Testing", "Line A", 15)],
	},
	{
		"item": "SA-HOUSING-01",
		"items": [("CMP-CASTING", 1), ("CMP-SEAL-KIT", 1), ("RM-BOLT-M8", 12), ("RM-PAINT-GREY", 0.5)],
		"operations": [("Machining", "Line B", 60), ("Painting", "Line A", 30), ("Assembly", "Line A", 30)],
	},
	{
		"item": "SA-PANEL-01",
		"items": [("CMP-CONTACTOR", 2), ("RM-BOLT-M8", 6)],
		"operations": [("Wiring", "Line B", 40)],
	},
	{
		"item": "SA-FRAME-01",
		"items": [("RM-MS-CHANNEL", 12), ("RM-STEEL-PLATE", 15), ("RM-WELD-ROD", 2), ("RM-PAINT-GREY", 1.5)],
		"operations": [("Cutting", "Line B", 30), ("Welding", "Line A", 90), ("Painting", "Line A", 45)],
	},
	{
		"item": "SA-DRIVE-01",
		"items": [("CMP-GEARBOX", 1), ("CMP-SHAFT-25", 1), ("CMP-BEARING-6205", 2), ("CMP-MOTOR-5HP", 1)],
		"operations": [("Assembly", "Line A", 60)],
	},
	{
		"item": "HZ-PUMP-100",
		"items": [("SA-MOTOR-01", 1), ("SA-HOUSING-01", 1), ("SA-PANEL-01", 1), ("RM-BOLT-M10", 16)],
		"operations": [("Assembly", "Line A", 120), ("Testing", "Line A", 60)],
		"top_level": 1,
	},
	{
		"item": "HZ-CONV-200",
		"items": [("SA-FRAME-01", 1), ("SA-DRIVE-01", 1), ("CMP-BELT-1M", 3), ("RM-BOLT-M10", 24)],
		"operations": [("Assembly", "Line A", 180), ("Testing", "Line A", 60)],
		"top_level": 1,
	},
	{
		# 0.2 casting per impeller: "Nos" must be a whole number, so the BOM is for a batch of 5
		"item": "SP-IMPELLER",
		"quantity": 5,
		"items": [("CMP-CASTING", 1), ("RM-BOLT-M8", 10)],
		"operations": [("Machining", "Line B", 200)],
		"top_level": 1,
	},
]

# Opening stock for spares: (item, HQ Finished Goods qty, DEL Finished Goods qty)
SPARES_OPENING = [("SP-IMPELLER", 30, 10), ("SP-SEAL-SET", 40, 8), ("SP-BELT-KIT", 12, 3)]

USERS = [
	{
		"email": "dept.head@horizon.local",
		"first_name": "Dept Head",
		"roles": ["Department Head", "Purchase User", "Stock User", "Employee"],
	},
	{
		"email": "procure@horizon.local",
		"first_name": "Procurement",
		"roles": ["Procurement Manager", "Purchase Manager", "Purchase User", "Stock User"],
	},
	{
		"email": "rajesh@horizon.local",
		"first_name": "Rajesh",
		"roles": ["Finance Director", "Accounts Manager", "Accounts User", "Purchase Manager"],
	},
	{
		"email": "priya@horizon.local",
		"first_name": "Priya",
		"roles": [
			"Operations Head",
			"Manufacturing Manager",
			"Manufacturing User",
			"Stock Manager",
			"Stock User",
		],
	},
	{"email": "amit@horizon.local", "first_name": "Amit", "roles": ["Sales Manager", "Sales User"]},
	{
		"email": "wh.delhi@horizon.local",
		"first_name": "Delhi Warehouse",
		"roles": ["Warehouse Manager", "Stock User", "Stock Manager"],
	},
	{
		"email": "qc@horizon.local",
		"first_name": "QC",
		"roles": ["Quality Inspector", "Quality Manager", "Manufacturing User", "Stock User"],
	},
	{
		"email": "neha@horizon.local",
		"first_name": "Neha",
		# "Payroll User" does not exist in this HRMS build; added only if present
		"roles": ["HR Manager", "HR User", "Payroll User"],
	},
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _log(message):
	print(f"[horizon demo] {message}", flush=True)


def _warn(message):
	print(f"[horizon demo] WARNING: {message}", flush=True)


def _abbr(name):
	return f"{name} - {ABBR}"


def _has_field(doctype, fieldname):
	return bool(frappe.get_meta(doctype).get_field(fieldname))


def _set_single(doctype, values):
	"""Set fields on a Single DocType and save, skipping unknown fieldnames."""
	doc = frappe.get_single(doctype)
	changed = False
	for fieldname, value in values.items():
		if not _has_field(doctype, fieldname):
			_warn(f"{doctype}.{fieldname} does not exist in this version; skipped")
			continue
		if doc.get(fieldname) != value:
			doc.set(fieldname, value)
			changed = True
	if changed:
		doc.flags.ignore_permissions = True
		doc.save()
	return changed


def _find_account(account_name_like, root_type=None, is_group=None):
	filters = {"company": COMPANY, "account_name": ["like", account_name_like]}
	if root_type:
		filters["root_type"] = root_type
	if is_group is not None:
		filters["is_group"] = is_group
	names = frappe.get_all("Account", filters=filters, pluck="name", order_by="lft")
	return names[0] if names else None


def _ensure_account(account_name, parent_account, account_type=None, is_group=0):
	existing = frappe.db.get_value("Account", {"company": COMPANY, "account_name": account_name}, "name")
	if existing:
		return existing
	if not parent_account:
		_warn(f"no parent found for account '{account_name}'; skipped")
		return None
	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent_account,
			"company": COMPANY,
			"is_group": is_group,
			"account_type": account_type,
		}
	)
	account.insert(ignore_permissions=True)
	return account.name


def _ensure_address(address_title, values, links):
	"""Create (or update) an Address with the given Dynamic Links. Returns the name."""
	name = frappe.db.get_value(
		"Address", {"address_title": address_title, "address_type": values["address_type"]}
	)
	if name:
		doc = frappe.get_doc("Address", name)
		doc.update(values)
		for link in links:
			if not any(
				row.link_doctype == link["link_doctype"] and row.link_name == link["link_name"]
				for row in doc.links
			):
				doc.append("links", link)
		doc.flags.ignore_permissions = True
		doc.save()
		return doc.name
	doc = frappe.get_doc({"doctype": "Address", "address_title": address_title, **values, "links": links})
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_contact(party_doctype, party_name, contact):
	email = contact["email"]
	existing = frappe.db.get_value(
		"Dynamic Link",
		{"parenttype": "Contact", "link_doctype": party_doctype, "link_name": party_name},
		"parent",
	)
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": contact["first_name"],
			"last_name": contact.get("last_name"),
			"is_primary_contact": 1,
			"email_ids": [{"email_id": email, "is_primary": 1}],
			"links": [{"link_doctype": party_doctype, "link_name": party_name}],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _party_gstin(party):
	"""Checksum-valid GSTIN for a party row, or None (-> Unregistered) if it fails validation."""
	gstin = make_gstin(party["state_code"], party["pan"])
	if is_valid_gstin(gstin):
		return gstin
	_warn(
		f"generated GSTIN {gstin} for {party.get('customer_name') or party.get('supplier_name')} is invalid"
	)
	return None


def _ensure_item_price(item_code, price_list, rate, selling):
	existing = frappe.db.get_value("Item Price", {"item_code": item_code, "price_list": price_list}, "name")
	if existing:
		if flt(frappe.db.get_value("Item Price", existing, "price_list_rate")) != flt(rate):
			frappe.db.set_value("Item Price", existing, "price_list_rate", flt(rate))
		return
	frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": price_list,
			"price_list_rate": flt(rate),
			"currency": CURRENCY,
			"selling": 1 if selling else 0,
			"buying": 0 if selling else 1,
		}
	).insert(ignore_permissions=True)


def _stock_qty(item_code, warehouse):
	return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))


# ---------------------------------------------------------------------------
# 1. Company / global settings
# ---------------------------------------------------------------------------


def setup_company_settings():
	terms_title = "Horizon Standard Terms"
	if not frappe.db.exists("Terms and Conditions", terms_title):
		frappe.get_doc(
			{
				"doctype": "Terms and Conditions",
				"title": terms_title,
				"selling": 1,
				"buying": 1,
				"terms": (
					"<ol><li>Prices are ex-works Mumbai unless stated otherwise.</li>"
					"<li>Payment: 30 days from invoice date; 1.5% per month on overdue amounts.</li>"
					"<li>Delivery dates are indicative and subject to material availability.</li>"
					"<li>Goods once sold will only be accepted back against a Quality Inspection report.</li>"
					"<li>Disputes are subject to Mumbai jurisdiction.</li></ol>"
				),
			}
		).insert(ignore_permissions=True)

	company_values = {"default_selling_terms": terms_title, "default_buying_terms": terms_title}
	for fieldname, value in company_values.items():
		if _has_field("Company", fieldname):
			frappe.db.set_value("Company", COMPANY, fieldname, value)

	# Selling Settings so_required / dn_required stay "No" on purpose. ERPNext's standard check is
	# all-or-nothing and runs before our doc_events hook: with "Yes" it would (a) block the audited
	# Finance Director bypass (invoice without Delivery Note, logged as a comment) and (b) reject
	# milestone / service invoices that legitimately have no Delivery Note. The Horizon rule
	# "Delivery Note before Invoice for stock items" is enforced instead by
	# horizon_erp.horizon_operations.selling.validate_sales_invoice (Sales Invoice validate hook).
	_set_single("Selling Settings", {"so_required": "No", "dn_required": "No"})
	# Quotation validity lives in CRM Settings in v15 (not Selling Settings)
	_set_single("CRM Settings", {"default_valid_till": 30})
	_set_single("Buying Settings", {"po_required": "Yes", "pr_required": "Yes"})

	stock_values = {
		"auto_indent": 1,
		"reorder_email_notify": 1,
		"allow_negative_stock": 0,
		"action_if_quality_inspection_is_not_submitted": "Stop",
		"action_if_quality_inspection_is_rejected": "Stop",
		"use_serial_batch_fields": 1,
	}
	try:
		_set_single("Stock Settings", {**stock_values, "valuation_method": "Moving Average"})
	except Exception as exc:
		# ERPNext refuses a global valuation-method change once Stock Ledger Entries exist;
		# every demo item carries valuation_method = Moving Average explicitly instead.
		_warn(f"could not set Stock Settings.valuation_method: {exc}; applying the rest")
		_set_single("Stock Settings", stock_values)

	_set_single(
		"Accounts Settings",
		{
			"book_asset_depreciation_entry_automatically": 1,
			"enable_common_party_accounting": 1,
			# credit_controller = role allowed to bypass credit-limit checks
			"credit_controller": "Finance Director",
		},
	)


# ---------------------------------------------------------------------------
# 2. Branches + Accounting Dimension
# ---------------------------------------------------------------------------


def setup_branches_and_dimension():
	for branch in ("Mumbai HQ", "Delhi DC"):
		if not frappe.db.exists("Branch", branch):
			frappe.get_doc({"doctype": "Branch", "branch": branch}).insert(ignore_permissions=True)

	dimension_name = frappe.db.get_value("Accounting Dimension", {"document_type": "Branch"}, "name")
	if dimension_name:
		dimension = frappe.get_doc("Accounting Dimension", dimension_name)
		row = next((d for d in dimension.dimension_defaults if d.company == COMPANY), None)
		if not row:
			dimension.append(
				"dimension_defaults",
				{
					"company": COMPANY,
					"reference_document": "Branch",
					"default_dimension": "Mumbai HQ",
					"mandatory_for_pl": 1,
				},
			)
			dimension.save(ignore_permissions=True)
	else:
		dimension = frappe.get_doc(
			{
				"doctype": "Accounting Dimension",
				"document_type": "Branch",
				"label": "Branch",
				"dimension_defaults": [
					{
						"company": COMPANY,
						"reference_document": "Branch",
						"default_dimension": "Mumbai HQ",
						"mandatory_for_pl": 1,
					}
				],
			}
		)
		dimension.insert(ignore_permissions=True)
		frappe.db.commit()

	# after_insert only enqueues the custom-field creation; run it inline so later steps
	# (and other developers' scripts) see the fields. The function is idempotent.
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		make_dimension_in_accounting_doctypes,
	)

	_log("creating 'branch' dimension fields on accounting doctypes (slow, one-off)")
	make_dimension_in_accounting_doctypes(doc=dimension)
	frappe.clear_cache()


# ---------------------------------------------------------------------------
# 3. Company addresses
# ---------------------------------------------------------------------------


def setup_addresses():
	for row in COMPANY_ADDRESSES:
		try:
			_ensure_address(
				row["address_title"],
				{
					"address_type": "Office",
					"address_line1": row["address_line1"],
					"city": row["city"],
					"state": row["state"],
					"pincode": row["pincode"],
					"country": "India",
					"gstin": row["gstin"],
					"gst_category": "Registered Regular",
					"is_your_company_address": 1,
				},
				[{"link_doctype": "Company", "link_name": COMPANY}],
			)
		except Exception as exc:
			_warn(f"address {row['address_title']} rejected: {exc}")


# ---------------------------------------------------------------------------
# 4. Cost centres + allocation
# ---------------------------------------------------------------------------


def setup_cost_centers():
	root = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 1, "parent_cost_center": ""})
	if not root:
		root = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 1}, "name", order_by="lft")
	for row in COST_CENTERS:
		name = _abbr(row["cost_center_name"])
		if frappe.db.exists("Cost Center", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": row["cost_center_name"],
				"parent_cost_center": _abbr(row["parent"]) if row["parent"] else root,
				"company": COMPANY,
				"is_group": row["is_group"],
			}
		).insert(ignore_permissions=True)

	main = _abbr(COST_CENTER_ALLOCATION["main_cost_center"])
	if not frappe.db.exists("Cost Center Allocation", {"main_cost_center": main, "docstatus": 1}):
		allocation = frappe.get_doc(
			{
				"doctype": "Cost Center Allocation",
				"main_cost_center": main,
				"company": COMPANY,
				"valid_from": COST_CENTER_ALLOCATION["valid_from"],
				"allocation_percentages": [
					{"cost_center": _abbr(d["cost_center"]), "percentage": d["percentage"]}
					for d in COST_CENTER_ALLOCATION["allocation_percentages"]
				],
			}
		)
		allocation.insert(ignore_permissions=True)
		allocation.submit()

	frappe.db.set_value("Company", COMPANY, "cost_center", _abbr("Admin"))


# ---------------------------------------------------------------------------
# 5. Accounts
# ---------------------------------------------------------------------------


def setup_accounts():
	direct_income = _find_account("Direct Income", "Income", 1) or _find_account("Income", "Income", 1)
	direct_expense = _find_account("Direct Expenses", "Expense", 1) or _find_account("Expenses", "Expense", 1)
	indirect_expense = _find_account("Indirect Expenses", "Expense", 1) or direct_expense
	stock_expense = _find_account("Stock Expenses", "Expense", 1) or direct_expense
	duties = _find_account("Duties and Taxes", "Liability", 1) or _find_account(
		"Current Liabilities", "Liability", 1
	)
	fixed_assets = _find_account("Fixed Assets", "Asset", 1)
	# "Standard with Numbers" ships 1780 - Accumulated Depreciation as a LEAF, so the per-class
	# accumulated-depreciation accounts go directly under Fixed Assets unless a group exists.
	accumulated_group = _find_account("Accumulated Depreciation%", "Asset", 1) or fixed_assets

	for name in ("Sales - Equipment", "Sales - Spares", "Sales - Components"):
		_ensure_account(name, direct_income)
	_ensure_account("Factory Overhead", indirect_expense)
	_ensure_account("Rework Cost", direct_expense)
	_ensure_account("Scrap Loss", direct_expense)
	_ensure_account("Stock Adjustment - Migration", stock_expense, account_type="Stock Adjustment")
	for name in ("PF Payable", "ESI Payable", "Professional Tax Payable"):
		_ensure_account(name, duties)
	for asset_class in ("Production Equipment", "Vehicles", "IT Equipment"):
		_ensure_account(asset_class, fixed_assets, account_type="Fixed Asset")
		_ensure_account(
			f"Accumulated Depreciation - {asset_class}",
			accumulated_group,
			account_type="Accumulated Depreciation",
		)


# ---------------------------------------------------------------------------
# 6. Warehouses
# ---------------------------------------------------------------------------


def setup_warehouses():
	addresses = {a["address_title"]: a for a in COMPANY_ADDRESSES}
	for row in WAREHOUSES:
		name = _abbr(row["warehouse_name"])
		address = addresses[row["address"]]
		values = {
			"warehouse_name": row["warehouse_name"],
			"company": COMPANY,
			"is_group": row["is_group"],
			"parent_warehouse": _abbr(row["parent"]),
			"address_line_1": address["address_line1"],
			"city": address["city"],
			"state": address["state"],
			"pin": address["pincode"],
			"is_rejected_warehouse": row.get("is_rejected_warehouse", 0),
		}
		if row.get("warehouse_type") and frappe.db.exists("Warehouse Type", row["warehouse_type"]):
			values["warehouse_type"] = row["warehouse_type"]
		if frappe.db.exists("Warehouse", name):
			doc = frappe.get_doc("Warehouse", name)
			doc.update(
				{
					k: v
					for k, v in values.items()
					if k not in ("warehouse_name", "is_group", "parent_warehouse")
				}
			)
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc({"doctype": "Warehouse", **values}).insert(ignore_permissions=True)

	if _has_field("Company", "default_in_transit_warehouse"):
		frappe.db.set_value("Company", COMPANY, "default_in_transit_warehouse", _abbr("DEL Goods In Transit"))


# ---------------------------------------------------------------------------
# 7. Item groups + GST item tax templates
# ---------------------------------------------------------------------------


def _ensure_gst_templates():
	"""Create India Compliance's default GST accounts / templates for HML if missing."""
	if frappe.db.exists("Item Tax Template", _abbr("GST 18%")) and frappe.db.exists(
		"Account", _abbr("Output Tax CGST")
	):
		return
	from india_compliance.gst_india.overrides.company import make_default_tax_templates

	_log("creating GST accounts and tax templates via India Compliance")
	make_default_tax_templates(COMPANY)


def _ensure_item_tax_template(title, gst_rate):
	"""Fallback when India Compliance did not create a template: build it from the GST accounts."""
	name = _abbr(title)
	if frappe.db.exists("Item Tax Template", name):
		return name
	rows = []
	for account_name, factor in (("Output Tax CGST", 0.5), ("Output Tax SGST", 0.5), ("Output Tax IGST", 1)):
		account = _abbr(account_name)
		if frappe.db.exists("Account", account):
			rows.append({"tax_type": account, "tax_rate": flt(gst_rate * factor, 3)})
	if not rows:
		_warn(f"no GST output accounts for {COMPANY}; cannot create {name}")
		return None
	doc = frappe.get_doc(
		{
			"doctype": "Item Tax Template",
			"title": title,
			"company": COMPANY,
			"gst_treatment": "Taxable",
			"gst_rate": gst_rate,
			"taxes": rows,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def setup_item_groups_and_taxes():
	try:
		_ensure_gst_templates()
	except Exception as exc:
		_warn(f"India Compliance GST template creation failed: {exc}")

	for row in ITEM_GROUPS:
		name = row["item_group_name"]
		if not frappe.db.exists("Item Group", name):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": name,
					"parent_item_group": "All Item Groups",
					"is_group": 0,
				}
			).insert(ignore_permissions=True)

		if not row["gst_template"]:
			continue
		gst_rate = flt(row["gst_template"].replace("GST ", "").replace("%", ""))
		template = _ensure_item_tax_template(row["gst_template"], gst_rate)
		if not template:
			continue
		group = frappe.get_doc("Item Group", name)
		if not any(t.item_tax_template == template for t in group.taxes):
			group.append("taxes", {"item_tax_template": template})
			group.save(ignore_permissions=True)


# ---------------------------------------------------------------------------
# 8. UOMs
# ---------------------------------------------------------------------------


def setup_uoms():
	for uom in UOMS:
		if not frappe.db.exists("UOM", uom):
			frappe.get_doc({"doctype": "UOM", "uom_name": uom, "enabled": 1}).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# 9. Items + Item Prices
# ---------------------------------------------------------------------------


def _item_values(row):
	default_warehouse, cost_center, _reorder_wh = KIND_DEFAULTS[row["kind"]]
	values = {
		"item_name": row["item_name"],
		"item_group": row["item_group"],
		"stock_uom": row["stock_uom"],
		"description": row["item_name"],
		"is_stock_item": 0 if row["kind"] == "fixed_asset" else 1,
		"include_item_in_manufacturing": 1 if row["kind"] in ("raw", "component", "sub_assembly") else 0,
		"valuation_rate": flt(row.get("valuation_rate")),
		"standard_rate": flt(row.get("standard_rate")),
		"lead_time_days": row.get("lead_time_days", 0),
		"valuation_method": "Moving Average",
		"is_purchase_item": 1 if row["kind"] in ("raw", "component", "fixed_asset") else 0,
		"is_sales_item": 1 if row["kind"] in SELLING_KINDS else 0,
		"gst_hsn_code": row.get("gst_hsn_code"),
	}
	for fieldname in (
		"criticality",
		"demand_pattern",
		"machine_hours_per_unit",
		"default_line",
		"has_batch_no",
		"create_new_batch",
		"batch_number_series",
		"has_serial_no",
		"serial_no_series",
	):
		if fieldname in row and _has_field("Item", fieldname):
			values[fieldname] = row[fieldname]

	if row["kind"] == "fixed_asset":
		if frappe.db.exists("Asset Category", row["asset_category"]):
			values["is_fixed_asset"] = 1
			values["asset_category"] = row["asset_category"]
	return values, default_warehouse, cost_center


def _sync_item_children(doc, row):
	default_warehouse, cost_center, reorder_wh = KIND_DEFAULTS[row["kind"]]
	cost_center = _abbr(cost_center)
	defaults = next((d for d in doc.item_defaults if d.company == COMPANY), None)
	if not defaults:
		defaults = doc.append("item_defaults", {"company": COMPANY})
	defaults.default_warehouse = default_warehouse
	defaults.buying_cost_center = cost_center
	defaults.selling_cost_center = cost_center
	if row.get("default_supplier") and frappe.db.exists("Supplier", row["default_supplier"]):
		defaults.default_supplier = row["default_supplier"]

	if reorder_wh and row.get("reorder_level"):
		reorder = next((d for d in doc.reorder_levels if d.warehouse == reorder_wh), None)
		if not reorder:
			reorder = doc.append("reorder_levels", {"warehouse": reorder_wh})
		reorder.warehouse_group = reorder_wh
		reorder.warehouse_reorder_level = row["reorder_level"]
		reorder.warehouse_reorder_qty = row["reorder_qty"]
		reorder.material_request_type = "Purchase"


def setup_items():
	for row in ITEMS:
		if (
			row["kind"] == "fixed_asset"
			and not frappe.db.exists("Asset Category", row["asset_category"])
			and not frappe.db.exists("Item", row["item_code"])
		):
			# The fixed-asset item needs its Asset Category, which demo_hr_finance.setup_hr_finance
			# creates (together with the item) later in setup_all. On the next run this step
			# only updates the item. TODO(finance): keep ASSET_ITEM in sync between both scripts.
			_warn(
				f"Asset Category {row['asset_category']} missing; {row['item_code']} left to demo_hr_finance"
			)
			continue
		values, _wh, _cc = _item_values(row)
		if frappe.db.exists("Item", row["item_code"]):
			doc = frappe.get_doc("Item", row["item_code"])
			# serial/batch/uom flags cannot change once stock exists: keep the stored values
			for fieldname in ("has_serial_no", "has_batch_no", "stock_uom", "is_stock_item"):
				values.pop(fieldname, None)
			doc.update(values)
		else:
			doc = frappe.get_doc({"doctype": "Item", "item_code": row["item_code"], **values})
		_sync_item_children(doc, row)
		doc.flags.ignore_permissions = True
		doc.save()

	for row in ITEMS:
		if row["kind"] in SELLING_KINDS and row.get("standard_rate"):
			_ensure_item_price(row["item_code"], "Standard Selling", row["standard_rate"], selling=True)
		elif row["kind"] in BUYING_KINDS and row.get("valuation_rate"):
			_ensure_item_price(row["item_code"], "Standard Buying", row["valuation_rate"], selling=False)


# ---------------------------------------------------------------------------
# 10. Parties
# ---------------------------------------------------------------------------


def _ensure_party_address_and_contact(doctype, party_name, party, gstin):
	gst_category = "Registered Regular" if gstin else "Unregistered"
	try:
		_ensure_address(
			party_name,
			{
				"address_type": "Billing",
				"address_line1": party["address_line1"],
				"city": party["city"],
				"state": party["state"],
				"pincode": party["pincode"],
				"country": "India",
				"gstin": gstin,
				"gst_category": gst_category,
				"is_primary_address": 1,
				"is_shipping_address": 1,
			},
			[{"link_doctype": doctype, "link_name": party_name}],
		)
	except Exception as exc:
		_warn(f"address for {doctype} {party_name} rejected: {exc}")
	_ensure_contact(doctype, party_name, party["contact"])


def setup_parties():
	for group in CUSTOMER_GROUPS:
		if not frappe.db.exists("Customer Group", group):
			frappe.get_doc(
				{
					"doctype": "Customer Group",
					"customer_group_name": group,
					"parent_customer_group": "All Customer Groups",
				}
			).insert(ignore_permissions=True)
	territory_parent = "India" if frappe.db.exists("Territory", "India") else "All Territories"
	for territory in TERRITORIES:
		if not frappe.db.exists("Territory", territory):
			frappe.get_doc(
				{"doctype": "Territory", "territory_name": territory, "parent_territory": territory_parent}
			).insert(ignore_permissions=True)
	for group in SUPPLIER_GROUPS:
		if not frappe.db.exists("Supplier Group", group):
			frappe.get_doc(
				{
					"doctype": "Supplier Group",
					"supplier_group_name": group,
					"parent_supplier_group": "All Supplier Groups",
				}
			).insert(ignore_permissions=True)

	generated = {}
	for party in CUSTOMERS:
		gstin = _party_gstin(party)
		generated[f"Customer {party['customer_name']}"] = gstin
		values = {
			"customer_name": party["customer_name"],
			"customer_type": "Company",
			"customer_group": party["customer_group"],
			"territory": party["territory"],
			"gstin": gstin,
			"gst_category": "Registered Regular" if gstin else "Unregistered",
		}
		if party.get("default_price_list") and frappe.db.exists("Price List", party["default_price_list"]):
			values["default_price_list"] = party["default_price_list"]
		if frappe.db.exists("Customer", party["customer_name"]):
			doc = frappe.get_doc("Customer", party["customer_name"])
			doc.update(values)
		else:
			doc = frappe.get_doc({"doctype": "Customer", **values})
		if party.get("credit_limit"):
			limit_row = next((d for d in doc.credit_limits if d.company == COMPANY), None)
			if not limit_row:
				limit_row = doc.append("credit_limits", {"company": COMPANY})
			limit_row.credit_limit = flt(party["credit_limit"])
		doc.flags.ignore_permissions = True
		doc.save()
		_ensure_party_address_and_contact("Customer", doc.name, party, gstin)

	for party in SUPPLIERS:
		gstin = _party_gstin(party)
		generated[f"Supplier {party['supplier_name']}"] = gstin
		values = {
			"supplier_name": party["supplier_name"],
			"supplier_type": "Company",
			"supplier_group": party["supplier_group"],
			"gstin": gstin,
			"gst_category": "Registered Regular" if gstin else "Unregistered",
		}
		for fieldname in ("is_blacklisted", "blacklist_reason", "blacklisted_on"):
			if _has_field("Supplier", fieldname):
				values[fieldname] = party.get(fieldname) or (0 if fieldname == "is_blacklisted" else None)
		if frappe.db.exists("Supplier", party["supplier_name"]):
			doc = frappe.get_doc("Supplier", party["supplier_name"])
			doc.update(values)
		else:
			doc = frappe.get_doc({"doctype": "Supplier", **values})
		doc.flags.ignore_permissions = True
		doc.save()
		_ensure_party_address_and_contact("Supplier", doc.name, party, gstin)

	# default supplier per item (Item Default + Item Supplier rows)
	for row in ITEMS:
		supplier = row.get("default_supplier")
		if (
			not supplier
			or not frappe.db.exists("Supplier", supplier)
			or not frappe.db.exists("Item", row["item_code"])
		):
			continue
		item = frappe.get_doc("Item", row["item_code"])
		changed = False
		if not any(d.supplier == supplier for d in item.supplier_items):
			item.append("supplier_items", {"supplier": supplier})
			changed = True
		defaults = next((d for d in item.item_defaults if d.company == COMPANY), None)
		if defaults and defaults.default_supplier != supplier:
			defaults.default_supplier = supplier
			changed = True
		if changed:
			item.flags.ignore_permissions = True
			item.save()

	if not frappe.db.exists(
		"Party Link", {"primary_role": "Customer", "primary_party": "ABC Corp", "secondary_role": "Supplier"}
	):
		frappe.get_doc(
			{
				"doctype": "Party Link",
				"primary_role": "Customer",
				"primary_party": "ABC Corp",
				"secondary_role": "Supplier",
				"secondary_party": "ABC Corp",
			}
		).insert(ignore_permissions=True)

	for party, gstin in generated.items():
		_log(f"GSTIN {party}: {gstin or 'Unregistered'}")


# ---------------------------------------------------------------------------
# 11. Pricing
# ---------------------------------------------------------------------------


def setup_pricing():
	for row in PRICE_LISTS:
		if not frappe.db.exists("Price List", row["price_list_name"]):
			frappe.get_doc({"doctype": "Price List", "enabled": 1, **row}).insert(ignore_permissions=True)

	for row in ITEMS:
		if row["kind"] in SELLING_KINDS and row.get("standard_rate"):
			_ensure_item_price(
				row["item_code"],
				"North Selling",
				flt(row["standard_rate"]) * NORTH_PRICE_FACTOR,
				selling=True,
			)

	for rule in PRICING_RULES:
		if frappe.db.exists("Pricing Rule", {"title": rule["title"]}):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": rule["title"],
				"apply_on": rule["apply_on"],
				"price_or_product_discount": "Price",
				"selling": 1,
				"buying": 0,
				"company": COMPANY,
				"currency": CURRENCY,
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": rule["discount_percentage"],
				"applicable_for": rule.get("applicable_for"),
				"customer_group": rule.get("customer_group"),
				"min_qty": rule.get("min_qty", 0),
				"valid_from": rule.get("valid_from"),
				"valid_upto": rule.get("valid_upto"),
				"has_priority": 1,
				"priority": rule["priority"],
				"apply_multiple_pricing_rules": rule.get("apply_multiple_pricing_rules", 0),
				"item_groups": [{"item_group": g} for g in rule["item_groups"]],
			}
		)
		doc.insert(ignore_permissions=True)

	# Territory-based price list: ERPNext resolves it via Customer.default_price_list, which is
	# set to "North Selling" on the North customers in setup_parties().
	for party in CUSTOMERS:
		if party.get("default_price_list") and frappe.db.exists("Customer", party["customer_name"]):
			frappe.db.set_value(
				"Customer", party["customer_name"], "default_price_list", party["default_price_list"]
			)

	_set_single("Selling Settings", {"validate_selling_price": 0})


# ---------------------------------------------------------------------------
# 12. Manufacturing masters + BOMs
# ---------------------------------------------------------------------------


def _ensure_workstations_and_operations():
	for row in WORKSTATIONS:
		if frappe.db.exists("Workstation", row["workstation_name"]):
			doc = frappe.get_doc("Workstation", row["workstation_name"])
		else:
			doc = frappe.new_doc("Workstation")
			doc.workstation_name = row["workstation_name"]
		# Workstation.before_save recomputes hour_rate from its components
		doc.hour_rate_labour = row["hour_rate"]
		doc.hour_rate_electricity = 0
		doc.hour_rate_consumable = 0
		doc.hour_rate_rent = 0
		doc.description = row["description"]
		if _has_field("Workstation", "working_hours") and not doc.get("working_hours"):
			for start, end in row["working_hours"]:
				doc.append("working_hours", {"start_time": start, "end_time": end, "enabled": 1})
		doc.flags.ignore_permissions = True
		doc.save()

	for row in OPERATIONS:
		if frappe.db.exists("Operation", row["name"]):
			frappe.db.set_value(
				"Operation",
				row["name"],
				{"workstation": row["workstation"], "description": row["description"]},
			)
			continue
		frappe.get_doc(
			{
				"doctype": "Operation",
				"__newname": row["name"],
				"name": row["name"],
				"workstation": row["workstation"],
				"description": row["description"],
			}
		).insert(ignore_permissions=True)


def _ensure_qi_templates():
	for template_name, parameters in QI_TEMPLATES.items():
		for param in parameters:
			if not frappe.db.exists("Quality Inspection Parameter", param["specification"]):
				frappe.get_doc(
					{"doctype": "Quality Inspection Parameter", "parameter": param["specification"]}
				).insert(ignore_permissions=True)
		if frappe.db.exists("Quality Inspection Template", template_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Quality Inspection Template",
				"quality_inspection_template_name": template_name,
				"item_quality_inspection_parameter": [
					{
						"specification": p["specification"],
						"numeric": p.get("numeric", 0),
						"min_value": p.get("min_value"),
						"max_value": p.get("max_value"),
						"value": p.get("value"),
					}
					for p in parameters
				],
			}
		).insert(ignore_permissions=True)

	for row in ITEMS:
		updates = {}
		if row.get("qi_template"):
			updates = {
				"inspection_required_before_purchase": 1,
				"quality_inspection_template": row["qi_template"],
			}
		elif row.get("qi_delivery_template"):
			updates = {
				"inspection_required_before_delivery": 1,
				"quality_inspection_template": row["qi_delivery_template"],
			}
		if updates and frappe.db.exists("Item", row["item_code"]):
			frappe.db.set_value("Item", row["item_code"], updates)


def _ensure_boms():
	created = {}
	for spec in BOMS:
		existing = frappe.db.get_value(
			"BOM", {"item": spec["item"], "docstatus": 1, "is_active": 1}, "name", order_by="is_default desc"
		)
		if existing:
			created[spec["item"]] = existing
			continue
		bom = frappe.new_doc("BOM")
		bom.item = spec["item"]
		bom.company = COMPANY
		bom.quantity = spec.get("quantity", 1)
		bom.currency = CURRENCY
		bom.with_operations = 1
		bom.rm_cost_as_per = "Valuation Rate"
		bom.is_active = 1
		bom.is_default = 1
		if _has_field("BOM", "revision_reason"):
			bom.revision_reason = "Design Change"
		for item_code, qty in spec["items"]:
			row = {
				"item_code": item_code,
				"qty": qty,
				"uom": frappe.db.get_value("Item", item_code, "stock_uom"),
			}
			if item_code in created:
				row["bom_no"] = created[item_code]
			bom.append("items", row)
		for operation, workstation, minutes in spec["operations"]:
			bom.append(
				"operations", {"operation": operation, "workstation": workstation, "time_in_mins": minutes}
			)
		bom.flags.ignore_permissions = True
		bom.insert()
		bom.submit()
		created[spec["item"]] = bom.name

	for spec in BOMS:
		if spec.get("top_level") and spec["item"] in created:
			bom = frappe.get_doc("BOM", created[spec["item"]])
			bom.update_cost(update_parent=False, from_child_bom=False, update_hour_rate=True, save=True)


def setup_manufacturing_masters():
	_ensure_workstations_and_operations()
	_ensure_qi_templates()
	frappe.db.commit()
	_ensure_boms()


# ---------------------------------------------------------------------------
# 13. Opening stock
# ---------------------------------------------------------------------------


def _opening_account():
	return frappe.db.get_value(
		"Account", {"company": COMPANY, "account_type": "Temporary", "is_group": 0}, "name"
	) or frappe.db.get_value("Company", COMPANY, "stock_adjustment_account")


def _ensure_batch(item_code):
	batch = frappe.db.get_value("Batch", {"item": item_code}, "name")
	if batch:
		return batch
	doc = frappe.get_doc({"doctype": "Batch", "item": item_code})
	doc.insert(ignore_permissions=True)
	return doc.name


def _submit_opening_reconciliation(label, branch, rows):
	rows = [r for r in rows if _stock_qty(r["item_code"], r["warehouse"]) <= 0]
	if not rows:
		_log(f"opening stock {label}: already present, skipped")
		return
	reco = frappe.new_doc("Stock Reconciliation")
	reco.company = COMPANY
	reco.purpose = "Opening Stock"
	reco.set_posting_time = 1
	reco.posting_date = OPENING_DATE
	reco.posting_time = "09:00:00"
	reco.expense_account = _opening_account()
	reco.cost_center = _abbr("Admin")
	if _has_field("Stock Reconciliation", "branch"):
		reco.branch = branch
	for row in rows:
		reco.append("items", row)
	reco.flags.ignore_permissions = True
	reco.insert()
	reco.submit()
	_log(f"opening stock {label}: {reco.name} ({len(rows)} rows)")


def _receive_serialised_opening(item_code, qty, warehouse, rate, serial_prefix, branch):
	if _stock_qty(item_code, warehouse) > 0:
		return
	serial_nos = [f"{serial_prefix}{i:04d}" for i in range(1, qty + 1)]
	entry = frappe.new_doc("Stock Entry")
	entry.company = COMPANY
	entry.stock_entry_type = "Material Receipt"
	entry.purpose = "Material Receipt"
	entry.set_posting_time = 1
	entry.posting_date = OPENING_DATE
	entry.posting_time = "09:00:00"
	entry.is_opening = "Yes"
	entry.to_warehouse = warehouse
	if _has_field("Stock Entry", "branch"):
		entry.branch = branch
	entry.append(
		"items",
		{
			"item_code": item_code,
			"qty": qty,
			"t_warehouse": warehouse,
			"basic_rate": rate,
			"use_serial_batch_fields": 1,
			"serial_no": "\n".join(serial_nos),
			"expense_account": _opening_account(),
			"cost_center": _abbr("Admin"),
		},
	)
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()
	_log(f"opening stock serialised {item_code}: {entry.name} ({qty} serial nos)")


def setup_opening_stock():
	hq_rows = []
	for row in ITEMS:
		if row["kind"] not in BUYING_KINDS or not row.get("reorder_level"):
			continue
		if row.get("has_serial_no"):
			continue  # received via Stock Entry below
		item_row = {
			"item_code": row["item_code"],
			"warehouse": RM_WAREHOUSE,
			"qty": row["reorder_level"] * 2,
			"valuation_rate": row["valuation_rate"],
		}
		if row.get("has_batch_no"):
			item_row["use_serial_batch_fields"] = 1
			item_row["batch_no"] = _ensure_batch(row["item_code"])
		hq_rows.append(item_row)

	spare_rates = {r["item_code"]: r["valuation_rate"] for r in ITEMS if r["kind"] == "spare"}
	del_rows = []
	for item_code, hq_qty, del_qty in SPARES_OPENING:
		hq_rows.append(
			{
				"item_code": item_code,
				"warehouse": FG_WAREHOUSE,
				"qty": hq_qty,
				"valuation_rate": spare_rates[item_code],
			}
		)
		del_rows.append(
			{
				"item_code": item_code,
				"warehouse": DEL_FG_WAREHOUSE,
				"qty": del_qty,
				"valuation_rate": spare_rates[item_code],
			}
		)

	_submit_opening_reconciliation("Mumbai HQ", "Mumbai HQ", hq_rows)
	frappe.db.commit()
	_submit_opening_reconciliation("Delhi DC", "Delhi DC", del_rows)
	frappe.db.commit()

	for row in ITEMS:
		if row["kind"] in BUYING_KINDS and row.get("has_serial_no") and row.get("reorder_level"):
			prefix = row["serial_no_series"].split(".")[0]
			_receive_serialised_opening(
				row["item_code"],
				row["reorder_level"] * 2,
				RM_WAREHOUSE,
				row["valuation_rate"],
				prefix,
				"Mumbai HQ",
			)


# ---------------------------------------------------------------------------
# 14. Users
# ---------------------------------------------------------------------------


def setup_users():
	for spec in USERS:
		roles = [r for r in spec["roles"] if frappe.db.exists("Role", r)]
		missing = sorted(set(spec["roles"]) - set(roles))
		if missing:
			_warn(f"{spec['email']}: roles not found and skipped: {', '.join(missing)}")
		if frappe.db.exists("User", spec["email"]):
			user = frappe.get_doc("User", spec["email"])
			user.add_roles(*roles)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": spec["email"],
					"first_name": spec["first_name"],
					"send_welcome_email": 0,
					"new_password": DEMO_PASSWORD,
					"enabled": 1,
					"user_type": "System User",
					"roles": [{"role": r} for r in roles],
				}
			)
			user.flags.ignore_permissions = True
			user.insert()

	from frappe.permissions import add_user_permission

	add_user_permission(
		"Warehouse", _abbr("Delhi DC"), "wh.delhi@horizon.local", ignore_permissions=True, is_default=1
	)


# ---------------------------------------------------------------------------
# 15. CSV exports
# ---------------------------------------------------------------------------


def _data_dir():
	path = frappe.get_app_path("horizon_erp", "data")
	os.makedirs(path, exist_ok=True)
	return path


def _write_csv(filename, header, rows):
	path = os.path.join(_data_dir(), filename)
	with open(path, "w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)
		writer.writerow(header)
		writer.writerows(rows)
	return path


def export_csvs():
	item_rows = []
	for row in ITEMS:
		default_warehouse, cost_center, reorder_wh = KIND_DEFAULTS[row["kind"]]
		item_rows.append(
			[
				row["item_code"],
				row["item_name"],
				row["item_group"],
				row["stock_uom"],
				0 if row["kind"] == "fixed_asset" else 1,
				flt(row.get("valuation_rate")),
				flt(row.get("standard_rate")),
				row.get("lead_time_days", 0),
				row.get("gst_hsn_code", ""),
				row.get("criticality", ""),
				row.get("demand_pattern", ""),
				row.get("machine_hours_per_unit", ""),
				row.get("default_line", ""),
				row.get("has_batch_no", 0),
				row.get("batch_number_series", ""),
				row.get("has_serial_no", 0),
				row.get("serial_no_series", ""),
				COMPANY,
				default_warehouse or "",
				_abbr(cost_center),
				row.get("default_supplier", ""),
				reorder_wh or "",
				row.get("reorder_level", ""),
				row.get("reorder_qty", ""),
				row.get("qi_template") or row.get("qi_delivery_template") or "",
			]
		)
	_write_csv(
		"items.csv",
		[
			"Item Code",
			"Item Name",
			"Item Group",
			"Default Unit of Measure",
			"Maintain Stock",
			"Valuation Rate",
			"Standard Selling Rate",
			"Lead Time in days",
			"HSN/SAC",
			"Criticality",
			"Demand Pattern",
			"Machine Hours per Unit",
			"Default Line",
			"Has Batch No",
			"Batch Number Series",
			"Has Serial No",
			"Serial Number Series",
			"Company (Item Defaults)",
			"Default Warehouse (Item Defaults)",
			"Default Cost Center (Item Defaults)",
			"Default Supplier (Item Defaults)",
			"Check in (group) (Item Reorder)",
			"Re-order Level (Item Reorder)",
			"Re-order Qty (Item Reorder)",
			"Quality Inspection Template",
		],
		item_rows,
	)

	_write_csv(
		"customers.csv",
		[
			"Customer Name",
			"Customer Type",
			"Customer Group",
			"Territory",
			"GSTIN / UIN",
			"GST Category",
			"Default Price List",
			"Credit Limit",
			"Address Line 1",
			"City/Town",
			"State/Province",
			"Postal Code",
			"Contact First Name",
			"Contact Last Name",
			"Contact Email",
		],
		[
			[
				c["customer_name"],
				"Company",
				c["customer_group"],
				c["territory"],
				make_gstin(c["state_code"], c["pan"]),
				"Registered Regular",
				c.get("default_price_list", ""),
				c.get("credit_limit", ""),
				c["address_line1"],
				c["city"],
				c["state"],
				c["pincode"],
				c["contact"]["first_name"],
				c["contact"]["last_name"],
				c["contact"]["email"],
			]
			for c in CUSTOMERS
		],
	)

	_write_csv(
		"suppliers.csv",
		[
			"Supplier Name",
			"Supplier Type",
			"Supplier Group",
			"GSTIN / UIN",
			"GST Category",
			"Is Blacklisted",
			"Blacklisted On",
			"Blacklist Reason",
			"Address Line 1",
			"City/Town",
			"State/Province",
			"Postal Code",
			"Contact First Name",
			"Contact Last Name",
			"Contact Email",
		],
		[
			[
				s["supplier_name"],
				"Company",
				s["supplier_group"],
				make_gstin(s["state_code"], s["pan"]),
				"Registered Regular",
				s.get("is_blacklisted", 0),
				s.get("blacklisted_on", ""),
				s.get("blacklist_reason", ""),
				s["address_line1"],
				s["city"],
				s["state"],
				s["pincode"],
				s["contact"]["first_name"],
				s["contact"]["last_name"],
				s["contact"]["email"],
			]
			for s in SUPPLIERS
		],
	)

	bom_rows = []
	for spec in BOMS:
		for item_code, qty in spec["items"]:
			bom_rows.append(
				[spec["item"], COMPANY, spec.get("quantity", 1), "Material", item_code, qty, "", "", ""]
			)
		for idx, (operation, workstation, minutes) in enumerate(spec["operations"], start=1):
			bom_rows.append(
				[
					spec["item"],
					COMPANY,
					spec.get("quantity", 1),
					"Operation",
					operation,
					"",
					workstation,
					minutes,
					idx,
				]
			)
	_write_csv(
		"bom_lines.csv",
		[
			"Item (BOM)",
			"Company",
			"Quantity",
			"Line Type",
			"Item Code / Operation",
			"Qty (BOM Item)",
			"Workstation (BOM Operation)",
			"Operation Time (mins)",
			"Sequence ID",
		],
		bom_rows,
	)

	price_rows = []
	for row in ITEMS:
		if row["kind"] in SELLING_KINDS and row.get("standard_rate"):
			price_rows.append(
				[row["item_code"], "Standard Selling", flt(row["standard_rate"]), CURRENCY, 1, 0]
			)
			price_rows.append(
				[
					row["item_code"],
					"North Selling",
					flt(row["standard_rate"]) * NORTH_PRICE_FACTOR,
					CURRENCY,
					1,
					0,
				]
			)
		elif row["kind"] in BUYING_KINDS and row.get("valuation_rate"):
			price_rows.append(
				[row["item_code"], "Standard Buying", flt(row["valuation_rate"]), CURRENCY, 0, 1]
			)
	_write_csv(
		"item_prices.csv", ["Item Code", "Price List", "Rate", "Currency", "Selling", "Buying"], price_rows
	)

	_write_csv(
		"pricing_rules.csv",
		[
			"Title",
			"Apply On",
			"Item Groups",
			"Applicable For",
			"Customer Group",
			"Min Qty",
			"Discount Percentage",
			"Priority",
			"Valid From",
			"Valid Upto",
			"Selling",
			"Company",
			"Currency",
		],
		[
			[
				r["title"],
				r["apply_on"],
				"; ".join(r["item_groups"]),
				r.get("applicable_for", ""),
				r.get("customer_group", ""),
				r.get("min_qty", 0),
				r["discount_percentage"],
				r["priority"],
				r.get("valid_from", ""),
				r.get("valid_upto", ""),
				1,
				COMPANY,
				CURRENCY,
			]
			for r in PRICING_RULES
		],
	)

	addresses = {a["address_title"]: a for a in COMPANY_ADDRESSES}
	_write_csv(
		"warehouses.csv",
		[
			"Warehouse Name",
			"Parent Warehouse",
			"Is Group",
			"Company",
			"Is Rejected Warehouse",
			"Warehouse Type",
			"Address Line 1",
			"City",
			"State",
			"PIN",
		],
		[
			[
				w["warehouse_name"],
				_abbr(w["parent"]),
				w["is_group"],
				COMPANY,
				w.get("is_rejected_warehouse", 0),
				w.get("warehouse_type", ""),
				addresses[w["address"]]["address_line1"],
				addresses[w["address"]]["city"],
				addresses[w["address"]]["state"],
				addresses[w["address"]]["pincode"],
			]
			for w in WAREHOUSES
		],
	)

	_write_csv(
		"cost_centers.csv",
		["Cost Center Name", "Parent Cost Center", "Is Group", "Company"],
		[
			[
				c["cost_center_name"],
				_abbr(c["parent"]) if c["parent"] else _abbr(COMPANY),
				c["is_group"],
				COMPANY,
			]
			for c in COST_CENTERS
		],
	)

	readme = os.path.join(_data_dir(), "README.md")
	with open(readme, "w", encoding="utf-8") as f:
		f.write(
			"# Horizon demo data (CSV)\n\n"
			"Generated by `horizon_erp.setup.demo_data.export_csvs()` from the Python data\n"
			"structures in `horizon_erp/setup/demo_data.py`, which is the source of truth.\n"
			"Column labels follow the Data Import template labels where practical; child-table\n"
			"columns carry the child DocType in brackets.\n\n"
			"## Import order\n\n"
			"1. `cost_centers.csv` - Cost Center (parents before children)\n"
			"2. `warehouses.csv` - Warehouse (groups before leaves)\n"
			"3. `items.csv` - Item (Item Groups, UOMs and Suppliers must exist first)\n"
			"4. `suppliers.csv` - Supplier (+ Address / Contact)\n"
			"5. `customers.csv` - Customer (+ Address / Contact, credit limits)\n"
			"6. `item_prices.csv` - Item Price (Price Lists Standard Selling / Standard Buying / North Selling)\n"
			"7. `pricing_rules.csv` - Pricing Rule\n"
			"8. `bom_lines.csv` - BOM (bottom-up: sub-assemblies before HZ-PUMP-100 / HZ-CONV-200)\n\n"
			"GST rates per item group (Equipment 5%, Spares 12%, Components 5%, Raw Material /\n"
			"Sub Assemblies 18%) come from the brief and must be confirmed against HSN by the client's CA.\n"
		)
	_log(f"CSVs written to {_data_dir()}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

STEPS = [
	("company_settings", setup_company_settings),
	("branches_and_dimension", setup_branches_and_dimension),
	("addresses", setup_addresses),
	("cost_centers", setup_cost_centers),
	("accounts", setup_accounts),
	("warehouses", setup_warehouses),
	("item_groups_and_taxes", setup_item_groups_and_taxes),
	("uoms", setup_uoms),
	("items", setup_items),
	("parties", setup_parties),
	("pricing", setup_pricing),
	("manufacturing_masters", setup_manufacturing_masters),
	("opening_stock", setup_opening_stock),
	("users", setup_users),
	("export_csvs", export_csvs),
]


def _run_step(name, fn, results):
	_log(f"step {name} ...")
	try:
		fn()
		frappe.db.commit()
		results[name] = "ok"
		_log(f"step {name} ok")
	except Exception as exc:
		frappe.db.rollback()
		summary = traceback.format_exc().strip().splitlines()
		results[name] = f"error: {exc}"
		_log(f"step {name} FAILED: {exc}")
		for line in summary[-6:]:
			print(f"    {line}", flush=True)


def _run_optional_module(results, key, module_path, function_name):
	try:
		module = frappe.get_module(module_path)
	except ImportError:
		_log(f"{module_path} not present yet")
		results[key] = "skipped: module not present"
		return
	fn = getattr(module, function_name, None)
	if not fn:
		results[key] = f"skipped: {function_name} not found"
		return
	_run_step(key, fn, results)


def setup_all():
	"""Create / update all Horizon demo masters, settings and opening stock. Idempotent."""
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	results = {}
	for name, fn in STEPS:
		_run_step(name, fn, results)

	_run_optional_module(results, "workflows", "horizon_erp.setup.workflows", "setup_workflows")
	_run_optional_module(results, "hr_finance", "horizon_erp.setup.demo_hr_finance", "setup_hr_finance")

	_log("summary: " + ", ".join(f"{k}={v}" for k, v in results.items()))
	return results

# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Demo data for HR, Payroll, Projects, Assets, Budget and Bank for Horizon Manufacturing Ltd.

Run with::

	bench --site horizon.local execute horizon_erp.setup.demo_hr_finance.setup_hr_finance

Every step is idempotent (exists-before-insert), commits on success, rolls back and
continues on failure, and reports ``{step: "ok" | "error: ..."}``.

The script never assumes masters created by ``horizon_erp.setup.demo_data`` (cost centres,
branches, users, items, customers) exist: it looks them up at runtime and creates a minimal
fallback where a value is mandatory.
"""

import csv
import os
import traceback
from datetime import datetime, timedelta

import frappe
from frappe.utils import (
	add_days,
	add_months,
	cint,
	flt,
	get_first_day,
	get_last_day,
	getdate,
	now_datetime,
	nowdate,
)

COMPANY = "Horizon Manufacturing Ltd"
ABBR = "HML"
CURRENCY = "INR"
FISCAL_YEAR = "2026-2027"
FY_START = "2026-04-01"
FY_END = "2027-03-31"

HOLIDAY_LIST = "Horizon Holidays 2026-27"
MORNING_SHIFT = "Morning Shift"
AFTERNOON_SHIFT = "Afternoon Shift"
LEAVE_POLICY = "Horizon Standard Leave Policy"
LEAVE_PERIOD_TITLE = "FY 2026-27 Leave Period"
PAYROLL_PERIOD = "FY 2026-27"
TAX_SLAB = "India New Regime FY 2026-27"
SS_SALARIED = "Horizon Salaried"
SS_WAGE = "Horizon Wage Earner"
SS_CONTRACT = "Horizon Contractual"
PROJECT_NAME = "Custom Conveyor - Bharat Mining"
ASSET_NAME = "CNC Lathe 2m"
ASSET_ITEM = "FA-CNC-LATHE"
BANK_NAME = "HDFC Bank"
BANK_ACCOUNT_NAME = "Horizon Current Account - HDFC"
MONTHLY_DISTRIBUTION = "Manufacturing Seasonal"

LOCK_ERRORS = ("Deadlock", "Lock wait timeout", "1205", "1213")


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _is_lock_error(exc):
	msg = str(exc)
	return isinstance(exc, frappe.QueryDeadlockError | frappe.QueryTimeoutError) or any(
		k in msg for k in LOCK_ERRORS
	)


def _run_step(name, fn, results):
	"""Run ``fn`` with retry on DB lock errors; commit on success, rollback + continue on error."""
	for attempt in range(1, 4):
		try:
			fn()
			frappe.db.commit()
			results[name] = "ok"
			print(f"[ok] {name}")
			return
		except Exception as e:
			frappe.db.rollback()
			if _is_lock_error(e) and attempt < 3:
				print(f"[retry {attempt}] {name}: lock error, retrying")
				continue
			tb = traceback.format_exc().strip().splitlines()
			short = "\n    ".join(tb[-4:])
			results[name] = f"error: {e!s}"[:300]
			print(f"[error] {name}: {e!s}\n    {short}")
			return


def _exists(doctype, filters):
	return frappe.db.get_value(doctype, filters, "name")


def _get_or_insert(doctype, filters, values=None, submit=False):
	"""Return name of the doc matching ``filters``; insert ``filters + values`` if missing."""
	name = _exists(doctype, filters)
	if name:
		return name
	doc = frappe.new_doc(doctype)
	doc.update(filters)
	if values:
		doc.update(values)
	doc.insert()
	if submit:
		doc.submit()
	return doc.name


def _insert_named(doctype, name, values, submit=False):
	"""Insert a doc with autoname=Prompt/field style explicit name."""
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.new_doc(doctype)
	doc.update(values)
	doc.name = name
	doc.flags.name_set = True
	doc.insert()
	if submit:
		doc.submit()
	return doc.name


def _company_defaults():
	return frappe.db.get_value(
		"Company",
		COMPANY,
		[
			"default_payroll_payable_account",
			"default_holiday_list",
			"cost_center",
			"depreciation_cost_center",
			"abbr",
		],
		as_dict=True,
	)


def _get_account(account_name, parent_name=None, account_type=None, like=False):
	"""Look up an HML account by ``account_name``; create under ``parent_name`` if missing."""
	filters = {"company": COMPANY, "account_name": account_name}
	if like:
		filters["account_name"] = ["like", f"%{account_name}%"]
	name = frappe.db.get_value("Account", filters, "name", order_by="is_group asc, name asc")
	if name or not parent_name:
		return name
	parent = frappe.db.get_value("Account", {"company": COMPANY, "account_name": parent_name, "is_group": 1})
	if not parent:
		print(f"    account parent '{parent_name}' not found; cannot create '{account_name}'")
		return None
	acc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": account_name,
			"parent_account": parent,
			"company": COMPANY,
			"account_type": account_type or "",
			"is_group": 0,
		}
	)
	acc.insert()
	print(f"    created account {acc.name}")
	return acc.name


def _get_cost_center(cc_name, parent_name=None, is_group=0):
	"""Look up an HML cost centre by ``cost_center_name``; create it under ``parent_name`` if missing."""
	name = frappe.db.get_value("Cost Center", {"company": COMPANY, "cost_center_name": cc_name}, "name")
	if name:
		return name
	root = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 1, "parent_cost_center": ""})
	if not root:
		root = frappe.db.get_value("Cost Center", {"company": COMPANY, "is_group": 1}, "name")
	parent = root
	if parent_name:
		parent = _get_cost_center(parent_name, is_group=1) or root
	doc = frappe.get_doc(
		{
			"doctype": "Cost Center",
			"cost_center_name": cc_name,
			"parent_cost_center": parent,
			"company": COMPANY,
			"is_group": is_group,
		}
	)
	doc.insert()
	print(f"    created cost centre {doc.name}")
	return doc.name


def _cc_map():
	"""Return the posting cost centres this script uses, creating fallbacks where missing."""
	return {
		"equipment": _get_cost_center("Mfg - Equipment", "Manufacturing"),
		"spares": _get_cost_center("Mfg - Spares", "Manufacturing"),
		"components": _get_cost_center("Mfg - Components", "Manufacturing"),
		"sales": _get_cost_center("Sales"),
		"admin": _get_cost_center("Admin"),
		"rnd": _get_cost_center("R&D"),
	}


def _user_exists(email):
	return bool(email and frappe.db.exists("User", {"name": email, "enabled": 1}))


def _branch(name):
	return name if frappe.db.exists("Branch", name) else None


def _department(dept_name):
	return frappe.db.get_value("Department", {"department_name": dept_name, "company": COMPANY}, "name")


def _employee_by_name(employee_name):
	return frappe.db.get_value("Employee", {"employee_name": employee_name, "company": COMPANY}, "name")


def _last_month():
	first = get_first_day(add_months(getdate(nowdate()), -1))
	return first, get_last_day(first)


def _working_days(count, before=None):
	"""Return the last ``count`` working days (per the Horizon holiday list) before ``before``."""
	holidays = set(frappe.get_all("Holiday", filters={"parent": HOLIDAY_LIST}, pluck="holiday_date"))
	day = add_days(getdate(before or nowdate()), -1)
	days = []
	while len(days) < count:
		if day not in holidays and day.weekday() != 6:
			days.append(day)
		day = add_days(day, -1)
	return sorted(days)


# ---------------------------------------------------------------------------
# Employee definitions
# ---------------------------------------------------------------------------

DEPARTMENTS = {
	# department_name: cost centre key for payroll_cost_center
	"Manufacturing": "equipment",
	"Sales": "sales",
	"Admin": "admin",
	"R&D": "rnd",
	"Quality": "equipment",
	"Stores": "admin",
}

DESIGNATIONS = [
	"Welder",
	"Machine Operator",
	"Assembler",
	"Production Supervisor",
	"Sales Executive",
	"Accountant",
	"HR Executive",
	"Quality Inspector",
	"Design Engineer",
	"Store Keeper",
	"Finance Director",
	"Operations Head",
	"Sales Director",
	"HR Manager",
]

EMPLOYMENT_TYPES = ["Wage Earner", "Salaried", "Contractual"]

GRADES = {"Grade W1": 18000, "Grade S2": 45000, "Grade S3": 75000, "Grade C1": 30000}

GRADE_STRUCTURE = {
	"Grade W1": SS_WAGE,
	"Grade S2": SS_SALARIED,
	"Grade S3": SS_SALARIED,
	"Grade C1": SS_CONTRACT,
}

EMPLOYMENT_TYPE_STRUCTURE = {
	"Wage Earner": SS_WAGE,
	"Salaried": SS_SALARIED,
	"Contractual": SS_CONTRACT,
}


def _employees():
	"""Static employee definitions. ``shift`` only for wage earners; ``user`` linked if the User exists."""
	w = {
		"grade": "Grade W1",
		"etype": "Wage Earner",
		"dept": "Manufacturing",
		"cc": "equipment",
		"branch": "Mumbai HQ",
	}
	return [
		{**w, "first": "Ravi", "last": "Kumar", "gender": "Male", "dob": "1990-03-12", "doj": "2024-06-01", "designation": "Welder", "shift": MORNING_SHIFT},
		{**w, "first": "Suresh", "last": "Patil", "gender": "Male", "dob": "1988-07-25", "doj": "2024-08-15", "designation": "Welder", "shift": MORNING_SHIFT},
		{**w, "first": "Manoj", "last": "Yadav", "gender": "Male", "dob": "1992-11-02", "doj": "2025-01-10", "designation": "Machine Operator", "shift": MORNING_SHIFT},
		{**w, "first": "Ganesh", "last": "Jadhav", "gender": "Male", "dob": "1995-05-18", "doj": "2025-03-01", "designation": "Machine Operator", "shift": AFTERNOON_SHIFT},
		{**w, "first": "Sunita", "last": "Pawar", "gender": "Female", "dob": "1997-09-09", "doj": "2025-06-16", "designation": "Assembler", "shift": AFTERNOON_SHIFT},
		{**w, "first": "Deepak", "last": "Sharma", "gender": "Male", "dob": "1999-01-30", "doj": "2026-01-05", "designation": "Assembler", "shift": AFTERNOON_SHIFT},
		# salaried
		{"first": "Vikram", "last": "Singh", "gender": "Male", "dob": "1985-04-14", "doj": "2024-04-01", "designation": "Production Supervisor", "dept": "Manufacturing", "cc": "equipment", "grade": "Grade S3", "etype": "Salaried", "branch": "Mumbai HQ"},
		{"first": "Anjali", "last": "Desai", "gender": "Female", "dob": "1993-12-05", "doj": "2025-02-01", "designation": "Sales Executive", "dept": "Sales", "cc": "sales", "grade": "Grade S2", "etype": "Salaried", "branch": "Delhi DC"},
		{"first": "Rohit", "last": "Iyer", "gender": "Male", "dob": "1991-08-21", "doj": "2024-10-01", "designation": "Accountant", "dept": "Admin", "cc": "admin", "grade": "Grade S2", "etype": "Salaried", "branch": "Mumbai HQ"},
		{"first": "Kavita", "last": "Joshi", "gender": "Female", "dob": "1994-02-17", "doj": "2025-07-01", "designation": "Quality Inspector", "dept": "Quality", "cc": "equipment", "grade": "Grade S2", "etype": "Salaried", "branch": "Mumbai HQ", "user": "qc@horizon.local"},
		# contractual
		{"first": "Arjun", "last": "Reddy", "gender": "Male", "dob": "1996-06-23", "doj": "2025-09-01", "designation": "Design Engineer", "dept": "R&D", "cc": "rnd", "grade": "Grade C1", "etype": "Contractual", "branch": "Mumbai HQ"},
		{"first": "Meena", "last": "Pillai", "gender": "Female", "dob": "1989-10-11", "doj": "2024-05-01", "designation": "Store Keeper", "dept": "Stores", "cc": "admin", "grade": "Grade C1", "etype": "Contractual", "branch": "Mumbai HQ"},
		# management (linked to users when they exist)
		{"first": "Rajesh", "last": "Menon", "gender": "Male", "dob": "1980-01-15", "doj": "2024-04-01", "designation": "Finance Director", "dept": "Admin", "cc": "admin", "grade": "Grade S3", "etype": "Salaried", "branch": "Mumbai HQ", "user": "rajesh@horizon.local"},
		{"first": "Priya", "last": "Nair", "gender": "Female", "dob": "1983-05-20", "doj": "2024-04-01", "designation": "Operations Head", "dept": "Manufacturing", "cc": "equipment", "grade": "Grade S3", "etype": "Salaried", "branch": "Mumbai HQ", "user": "priya@horizon.local"},
		{"first": "Amit", "last": "Shah", "gender": "Male", "dob": "1982-09-09", "doj": "2024-04-01", "designation": "Sales Director", "dept": "Sales", "cc": "sales", "grade": "Grade S3", "etype": "Salaried", "branch": "Delhi DC", "user": "amit@horizon.local"},
		{"first": "Neha", "last": "Verma", "gender": "Female", "dob": "1987-03-03", "doj": "2024-04-01", "designation": "HR Manager", "dept": "Admin", "cc": "admin", "grade": "Grade S3", "etype": "Salaried", "branch": "Mumbai HQ", "user": "neha@horizon.local"},
	]  # fmt: skip


def _wage_earners():
	return [e for e in _employees() if e["etype"] == "Wage Earner"]


def _full_name(e):
	return f"{e['first']} {e['last']}"


# ---------------------------------------------------------------------------
# A. HR masters
# ---------------------------------------------------------------------------


def step_hr_masters():
	cc = _cc_map()
	for dept_name, cc_key in DEPARTMENTS.items():
		name = _department(dept_name)
		if not name:
			doc = frappe.get_doc(
				{
					"doctype": "Department",
					"department_name": dept_name,
					"company": COMPANY,
					"parent_department": "All Departments",
				}
			)
			doc.insert()
			name = doc.name
		if frappe.get_meta("Department").has_field("payroll_cost_center"):
			frappe.db.set_value("Department", name, "payroll_cost_center", cc[cc_key])

	for d in DESIGNATIONS:
		_get_or_insert("Designation", {"designation_name": d})

	for et in EMPLOYMENT_TYPES:
		_get_or_insert("Employment Type", {"employee_type_name": et})

	for grade, base in GRADES.items():
		if not frappe.db.exists("Employee Grade", grade):
			_insert_named("Employee Grade", grade, {"default_base_pay": base, "currency": CURRENCY})
		else:
			frappe.db.set_value("Employee Grade", grade, {"default_base_pay": base, "currency": CURRENCY})
	print(f"    departments={len(DEPARTMENTS)} designations={len(DESIGNATIONS)} grades={len(GRADES)}")


def step_holiday_list():
	holidays = {
		"2026-08-15": "Independence Day",
		"2026-10-02": "Gandhi Jayanti",
		"2026-10-20": "Diwali",
		"2026-10-21": "Diwali (Govardhan Puja)",
		"2026-12-25": "Christmas",
		"2027-01-26": "Republic Day",
		"2027-03-29": "Holi",
	}
	for i in range(4):
		holidays[add_days(getdate("2026-12-28"), i).isoformat()] = "Plant Shutdown"

	if frappe.db.exists("Holiday List", HOLIDAY_LIST):
		doc = frappe.get_doc("Holiday List", HOLIDAY_LIST)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": HOLIDAY_LIST,
				"from_date": FY_START,
				"to_date": FY_END,
				"weekly_off": "Sunday",
			}
		)
	existing = {getdate(h.holiday_date) for h in doc.holidays}
	if not any(h.weekly_off for h in doc.holidays):
		doc.get_weekly_off_dates()
		existing = {getdate(h.holiday_date) for h in doc.holidays}
	for date, desc in holidays.items():
		if getdate(date) not in existing:
			doc.append("holidays", {"holiday_date": date, "description": desc})
	doc.save()
	frappe.db.set_value("Company", COMPANY, "default_holiday_list", HOLIDAY_LIST)
	print(f"    {HOLIDAY_LIST}: {doc.total_holidays} holidays (incl. Sundays); company default set")


def step_shift_types():
	shifts = {
		MORNING_SHIFT: ("06:00:00", "14:00:00", "Blue"),
		AFTERNOON_SHIFT: ("14:00:00", "22:00:00", "Orange"),
	}
	common = {
		"enable_auto_attendance": 1,
		"determine_check_in_and_check_out": "Alternating entries as IN and OUT during the same shift",
		"working_hours_calculation_based_on": "First Check-in and Last Check-out",
		# HRMS fieldnames: enable_late_entry_marking / enable_early_exit_marking
		# (the brief's enable_entry_grace_period / enable_exit_grace_period do not exist)
		"enable_late_entry_marking": 1,
		"late_entry_grace_period": 5,
		"enable_early_exit_marking": 1,
		"early_exit_grace_period": 5,
		"working_hours_threshold_for_half_day": 4,
		"working_hours_threshold_for_absent": 2,
		"begin_check_in_before_shift_start_time": 60,
		"allow_check_out_after_shift_end_time": 120,
		"holiday_list": HOLIDAY_LIST,
		"process_attendance_after": "2026-10-01",
		"last_sync_of_checkin": now_datetime(),
		"mark_auto_attendance_on_holidays": 0,
	}
	for name, (start, end, color) in shifts.items():
		values = {"start_time": start, "end_time": end, "color": color, **common}
		if frappe.db.exists("Shift Type", name):
			doc = frappe.get_doc("Shift Type", name)
			doc.update(values)
			doc.save()
		else:
			_insert_named("Shift Type", name, values)
	print(f"    shift types: {', '.join(shifts)}")


def step_employees():
	cc = _cc_map()
	emp_meta = frappe.get_meta("Employee")
	created = 0
	for e in _employees():
		full = _full_name(e)
		if _employee_by_name(full):
			continue
		base = GRADES[e["grade"]]
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": e["first"],
				"last_name": e["last"],
				"gender": e["gender"],
				"date_of_birth": e["dob"],
				"date_of_joining": e["doj"],
				"company": COMPANY,
				"status": "Active",
				"department": _department(e["dept"]),
				"designation": e["designation"],
				"holiday_list": HOLIDAY_LIST,
				"branch": _branch(e["branch"]),
				"ctc": base * 12,
				"salary_currency": CURRENCY,
				"salary_mode": "Bank",
			}
		)
		for fieldname, value in (
			("grade", e["grade"]),
			("employment_type", e["etype"]),
			("payroll_cost_center", cc[e["cc"]]),
			("default_shift", e.get("shift")),
		):
			if emp_meta.has_field(fieldname) and value:
				doc.set(fieldname, value)
		if _user_exists(e.get("user")):
			doc.user_id = e["user"]
		doc.insert()
		created += 1

	# second pass: reporting lines and leave approvers
	supervisor = _employee_by_name("Vikram Singh")
	priya = "priya@horizon.local" if _user_exists("priya@horizon.local") else None
	rajesh = "rajesh@horizon.local" if _user_exists("rajesh@horizon.local") else None
	for e in _employees():
		name = _employee_by_name(_full_name(e))
		if not name:
			continue
		updates = {}
		if e["etype"] == "Wage Earner" and supervisor and name != supervisor:
			updates["reports_to"] = supervisor
		if emp_meta.has_field("leave_approver"):
			approver = priya if e["dept"] in ("Manufacturing", "Quality", "Stores", "R&D") else rajesh
			if approver and approver != frappe.db.get_value("Employee", name, "user_id"):
				updates["leave_approver"] = approver
		if updates:
			# save through the controller so the Employee nested-set tree (reports_to) stays valid
			emp_doc = frappe.get_doc("Employee", name)
			emp_doc.update(updates)
			emp_doc.save()
	total = frappe.db.count("Employee", {"company": COMPANY, "status": "Active"})
	print(f"    employees created={created}, active HML employees={total}")


def step_shift_assignments():
	count = 0
	for e in _wage_earners():
		emp = _employee_by_name(_full_name(e))
		if not emp:
			continue
		filters = {"employee": emp, "shift_type": e["shift"], "start_date": "2026-10-01", "docstatus": 1}
		if _exists("Shift Assignment", filters):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Shift Assignment",
				"employee": emp,
				"shift_type": e["shift"],
				"company": COMPANY,
				"start_date": "2026-10-01",
				"status": "Active",
			}
		)
		doc.insert()
		doc.submit()
		count += 1
	print(f"    shift assignments created={count}")


def step_leave():
	leave_types = {
		"Casual Leave": {"max_leaves_allowed": 12, "is_carry_forward": 0, "is_lwp": 0},
		"Sick Leave": {"max_leaves_allowed": 8, "is_carry_forward": 0, "is_lwp": 0},
		"Earned Leave": {
			"max_leaves_allowed": 21,
			"is_carry_forward": 1,
			"maximum_carry_forwarded_leaves": 10,
			"allow_encashment": 0,
			"is_lwp": 0,
		},
	}
	allocations = {"Casual Leave": 12, "Sick Leave": 8, "Earned Leave": 21}
	for lt, values in leave_types.items():
		if frappe.db.exists("Leave Type", lt):
			doc = frappe.get_doc("Leave Type", lt)
			doc.update(values)
			doc.save()
		else:
			frappe.get_doc({"doctype": "Leave Type", "leave_type_name": lt, **values}).insert()

	leave_period = _exists("Leave Period", {"company": COMPANY, "from_date": FY_START, "to_date": FY_END})
	if not leave_period:
		lp = frappe.get_doc(
			{
				"doctype": "Leave Period",
				"company": COMPANY,
				"from_date": FY_START,
				"to_date": FY_END,
				"is_active": 1,
			}
		)
		lp.insert()
		leave_period = lp.name
	# Leave Period has no title field; the brief's name is recorded as a comment on the record
	print(f"    leave period {leave_period} ({LEAVE_PERIOD_TITLE})")

	policy = _exists("Leave Policy", {"title": LEAVE_POLICY, "docstatus": ["<", 2]})
	if not policy:
		doc = frappe.get_doc(
			{
				"doctype": "Leave Policy",
				"title": LEAVE_POLICY,
				"leave_policy_details": [
					{"leave_type": lt, "annual_allocation": n} for lt, n in allocations.items()
				],
			}
		)
		doc.insert()
		doc.submit()
		policy = doc.name
	elif frappe.db.get_value("Leave Policy", policy, "docstatus") == 0:
		frappe.get_doc("Leave Policy", policy).submit()

	from hrms.hr.doctype.leave_policy_assignment.leave_policy_assignment import (
		create_assignment_for_multiple_employees,
	)

	pending = []
	for e in _employees():
		emp = _employee_by_name(_full_name(e))
		if not emp:
			continue
		if _exists(
			"Leave Policy Assignment",
			{"employee": emp, "leave_period": leave_period, "docstatus": 1},
		):
			continue
		pending.append(emp)
	if pending:
		create_assignment_for_multiple_employees(
			pending,
			frappe._dict(
				{
					"assignment_based_on": "Leave Period",
					"leave_policy": policy,
					"leave_period": leave_period,
					"carry_forward": 0,
				}
			),
		)
	alloc = frappe.db.count("Leave Allocation", {"company": COMPANY, "docstatus": 1})
	print(f"    leave policy assignments created={len(pending)}; leave allocations={alloc}")

	block_name = "Plant Shutdown Dec 2026"
	if not frappe.db.exists("Leave Block List", block_name):
		frappe.get_doc(
			{
				"doctype": "Leave Block List",
				"leave_block_list_name": block_name,
				"company": COMPANY,
				"applies_to_all_departments": 1,
				"leave_block_list_dates": [
					{"block_date": add_days("2026-12-28", i), "reason": "Annual plant shutdown"}
					for i in range(4)
				],
			}
		).insert()

	hr_settings = frappe.get_doc("HR Settings")
	if not cint(hr_settings.leave_approver_mandatory_in_leave_application):
		hr_settings.leave_approver_mandatory_in_leave_application = 1
		hr_settings.save()


def step_attendance():
	days = _working_days(5)
	workers = []
	for e in _wage_earners():
		emp = _employee_by_name(_full_name(e))
		if emp:
			workers.append((emp, e["shift"]))
	shift_start = {MORNING_SHIFT: 6, AFTERNOON_SHIFT: 14}
	in_offsets = [-3, 2, 1, -4, 3]  # minutes relative to shift start
	out_offsets = [15, 40, 5, 90, 25]  # minutes after shift end
	created = 0
	for wi, (emp, shift) in enumerate(workers):
		for di, day in enumerate(days):
			start = datetime.combine(day, datetime.min.time()).replace(hour=shift_start[shift])
			in_time = start + timedelta(minutes=in_offsets[(wi + di) % 5])
			out_time = start + timedelta(hours=8, minutes=out_offsets[(wi + di) % 5])
			if wi == 0 and di == 2:
				in_time = start + timedelta(minutes=8)  # 8 min late -> late_entry flag
			if wi == 1 and di == 1:
				in_time = start - timedelta(minutes=5)
				out_time = start + timedelta(hours=9, minutes=55)  # 10 working hours -> overtime
			for log_type, time in (("IN", in_time), ("OUT", out_time)):
				if _exists("Employee Checkin", {"employee": emp, "time": time, "log_type": log_type}):
					continue
				frappe.get_doc(
					{
						"doctype": "Employee Checkin",
						"employee": emp,
						"log_type": log_type,
						"time": time,
						"device_id": "DEMO-BIOMETRIC-01",
					}
				).insert()
				created += 1
	frappe.db.commit()
	print(f"    checkins created={created} for {len(workers)} workers on {[d.isoformat() for d in days]}")

	for shift in (MORNING_SHIFT, AFTERNOON_SHIFT):
		frappe.db.set_value("Shift Type", shift, "last_sync_of_checkin", now_datetime())
		doc = frappe.get_doc("Shift Type", shift)
		doc.process_auto_attendance()
	frappe.db.commit()

	late = frappe.get_all(
		"Attendance",
		filters={"late_entry": 1, "company": COMPANY, "docstatus": 1},
		fields=["name", "employee_name", "attendance_date", "in_time"],
	)
	worker_att = frappe.db.count(
		"Attendance", {"employee": ["in", [w[0] for w in workers]], "docstatus": 1, "status": "Present"}
	)
	print(f"    auto attendance: worker Present rows={worker_att}; late_entry rows={late}")
	if not late:
		print("    WARNING: no late_entry attendance found")

	staff = 0
	for e in _employees():
		if e["etype"] == "Wage Earner":
			continue
		emp = _employee_by_name(_full_name(e))
		if not emp:
			continue
		for day in days:
			if _exists("Attendance", {"employee": emp, "attendance_date": day, "docstatus": ["<", 2]}):
				continue
			doc = frappe.get_doc(
				{
					"doctype": "Attendance",
					"employee": emp,
					"attendance_date": day,
					"status": "Present",
					"company": COMPANY,
				}
			)
			doc.insert()
			doc.submit()
			staff += 1
	print(f"    staff attendance created={staff}")


# ---------------------------------------------------------------------------
# B. Payroll
# ---------------------------------------------------------------------------


def _salary_components():
	"""(name, abbr, type, flags, account_key)."""
	return [
		("Basic", "B", "Earning", {"depends_on_payment_days": 1, "is_tax_applicable": 1}, "salary"),
		("Dearness Allowance", "DA", "Earning", {"depends_on_payment_days": 0, "is_tax_applicable": 1}, "salary"),
		("House Rent Allowance", "HRA", "Earning", {"depends_on_payment_days": 0, "is_tax_applicable": 1}, "salary"),
		("Medical Allowance", "MA", "Earning", {"depends_on_payment_days": 1, "is_tax_applicable": 1}, "salary"),
		("Conveyance Allowance", "CA", "Earning", {"depends_on_payment_days": 1, "is_tax_applicable": 1}, "salary"),
		("Overtime", "OT", "Earning", {"depends_on_payment_days": 0, "is_tax_applicable": 1}, "salary"),
		("Production Incentive", "PI", "Earning", {"depends_on_payment_days": 0, "is_tax_applicable": 1}, "salary"),
		("Contract Fee", "CF", "Earning", {"depends_on_payment_days": 1, "is_tax_applicable": 1}, "salary"),
		("Hourly Wages", "HW", "Earning", {"depends_on_payment_days": 1, "is_tax_applicable": 1}, "salary"),
		("Provident Fund", "PF", "Deduction", {"depends_on_payment_days": 0}, "pf"),
		("ESI", "ESI", "Deduction", {"depends_on_payment_days": 0}, "esi"),
		("Professional Tax", "PT", "Deduction", {"depends_on_payment_days": 0}, "pt"),
		(
			"Income Tax",
			"IT",
			"Deduction",
			{"variable_based_on_taxable_salary": 1, "is_income_tax_component": 1, "depends_on_payment_days": 0},
			"tds",
		),
		("Insurance Premium", "INS", "Deduction", {"depends_on_payment_days": 0}, "insurance"),
		("Loan Recovery", "LR", "Deduction", {"depends_on_payment_days": 0}, "loan"),
		("Employer PF", "EPF", "Earning", {"statistical_component": 1, "depends_on_payment_days": 0}, None),
		("Employer ESI", "EESI", "Earning", {"statistical_component": 1, "depends_on_payment_days": 0}, None),
	]  # fmt: skip


def _payroll_accounts():
	duties = "Duties and Taxes"
	liabilities = "Current Liabilities"
	return {
		"salary": _get_account("Salary", "Indirect Expenses"),
		"pf": _get_account("PF Payable", duties),
		"esi": _get_account("ESI Payable", duties),
		"pt": _get_account("Professional Tax Payable", duties),
		"tds": _get_account("TDS Payable", duties, account_type="Tax"),
		"insurance": _get_account("Insurance Premium Payable", liabilities),
		"loan": _get_account("Employee Loan Recovery", liabilities),
	}


def step_salary_components():
	accounts = _payroll_accounts()
	for name, abbr, ctype, flags, acc_key in _salary_components():
		if frappe.db.exists("Salary Component", name):
			doc = frappe.get_doc("Salary Component", name)
		else:
			doc = frappe.new_doc("Salary Component")
			doc.salary_component = name
		doc.salary_component_abbr = abbr
		doc.type = ctype
		doc.update(flags)
		account = accounts.get(acc_key) if acc_key else None
		if account and not any(a.company == COMPANY for a in doc.accounts):
			doc.append("accounts", {"company": COMPANY, "account": account})
		doc.save()
	print(f"    salary components={len(_salary_components())}; accounts={accounts}")


def _row(component, formula=None, amount=None, condition=None):
	row = {"salary_component": component}
	if formula:
		row.update({"amount_based_on_formula": 1, "formula": formula})
	elif amount is not None:
		row["amount"] = amount
	if condition:
		row["condition"] = condition
	return row


def _structures():
	# Statutory formulas. ``min()`` is not whitelisted in salary slip formulas, so the PF
	# wage ceiling (15,000) is expressed as a conditional expression.
	pf = "(B + DA) * 0.12 if (B + DA) <= 15000 else 1800"
	esi = "gross_pay * 0.0075 if gross_pay <= 21000 else 0"
	# Professional Tax: Maharashtra slab (200/month, 300 in February); Delhi has no PT.
	# TODO(payroll): condition on Employee.branch once the Delhi branch goes live.
	pt = "200 if gross_pay > 10000 else 0"
	employer_pf = pf
	return {
		SS_SALARIED: {
			"earnings": [
				_row("Basic", "base * 0.40"),
				_row("Dearness Allowance", "B * 0.10"),
				_row("House Rent Allowance", "B * 0.50"),
				_row("Medical Allowance", amount=1250),
				_row("Conveyance Allowance", amount=1600),
				_row("Employer PF", employer_pf),
			],
			"deductions": [
				_row("Provident Fund", pf),
				_row("ESI", esi),
				_row("Professional Tax", pt),
				_row("Income Tax"),
			],
		},
		# Wage earners: base = hourly rate x 208 standard hours; payment days prorate Basic.
		# OT / Production Incentive are 0 here and filled by Additional Salary (overtime job).
		SS_WAGE: {
			"earnings": [
				_row("Basic", "base"),
				_row("Dearness Allowance", "B * 0.10"),
				_row("Overtime", amount=0),
				_row("Production Incentive", amount=0),
				_row("Employer PF", employer_pf),
			],
			"deductions": [
				_row("Provident Fund", pf),
				_row("ESI", esi),
				_row("Professional Tax", pt),
			],
		},
		# Contractual: no PF / ESI (contract-dependent; confirm with HR), PT + TDS apply.
		SS_CONTRACT: {
			"earnings": [_row("Contract Fee", "base")],
			"deductions": [_row("Professional Tax", pt), _row("Income Tax")],
		},
	}


def step_salary_structures():
	payroll_payable = _company_defaults().default_payroll_payable_account
	for name, tables in _structures().items():
		if frappe.db.exists("Salary Structure", name):
			doc = frappe.get_doc("Salary Structure", name)
			if doc.docstatus == 0:
				doc.submit()
			continue
		doc = frappe.new_doc("Salary Structure")
		doc.update(
			{
				"company": COMPANY,
				"currency": CURRENCY,
				"payroll_frequency": "Monthly",
				"is_active": "Yes",
				"salary_slip_based_on_timesheet": 0,
				"payment_account": payroll_payable,
				"earnings": tables["earnings"],
				"deductions": tables["deductions"],
			}
		)
		doc.name = name
		doc.flags.name_set = True
		doc.insert()
		doc.submit()
	print(f"    salary structures: {', '.join(_structures())}")


def step_tax_slab_and_payroll_period():
	if not frappe.db.exists("Income Tax Slab", TAX_SLAB):
		slabs = [
			(0, 400000, 0),
			(400000, 800000, 5),
			(800000, 1200000, 10),
			(1200000, 1600000, 15),
			(1600000, 2000000, 20),
			(2000000, 2400000, 25),
			(2400000, 0, 30),
		]
		doc = frappe.new_doc("Income Tax Slab")
		doc.update(
			{
				"effective_from": FY_START,
				"company": COMPANY,
				"currency": CURRENCY,
				"allow_tax_exemption": 1,
				"standard_tax_exemption_amount": 75000,
				"slabs": [{"from_amount": f, "to_amount": t, "percent_deduction": p} for f, t, p in slabs],
				"other_taxes_and_charges": [
					{"description": "Health and Education Cess", "percent": 4, "min_taxable_income": 0}
				],
			}
		)
		doc.name = TAX_SLAB
		doc.flags.name_set = True
		doc.insert()
		doc.submit()
	elif frappe.db.get_value("Income Tax Slab", TAX_SLAB, "docstatus") == 0:
		frappe.get_doc("Income Tax Slab", TAX_SLAB).submit()

	if not frappe.db.exists("Payroll Period", PAYROLL_PERIOD):
		_insert_named(
			"Payroll Period",
			PAYROLL_PERIOD,
			{"company": COMPANY, "start_date": FY_START, "end_date": FY_END},
		)
	print(f"    tax slab '{TAX_SLAB}', payroll period '{PAYROLL_PERIOD}'")


def step_salary_structure_assignments():
	payroll_payable = _company_defaults().default_payroll_payable_account
	created = 0
	for e in _employees():
		emp = _employee_by_name(_full_name(e))
		if not emp:
			continue
		if _exists("Salary Structure Assignment", {"employee": emp, "from_date": FY_START, "docstatus": 1}):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": emp,
				"salary_structure": EMPLOYMENT_TYPE_STRUCTURE[e["etype"]],
				"from_date": FY_START,
				"company": COMPANY,
				"currency": CURRENCY,
				"base": GRADES[e["grade"]],
				"income_tax_slab": TAX_SLAB,
				"payroll_payable_account": payroll_payable,
			}
		)
		doc.insert()
		doc.submit()
		created += 1

	for grade, structure in GRADE_STRUCTURE.items():
		if frappe.db.exists("Employee Grade", grade):
			frappe.db.set_value("Employee Grade", grade, "default_salary_structure", structure)
	print(f"    salary structure assignments created={created}; grade default structures set")


def step_payroll_run():
	start, end = _last_month()
	defaults = _company_defaults()
	cc = _cc_map()

	# Additional Salary: overtime for one wage earner, flows into the slip via the OT component
	ravi = _employee_by_name("Ravi Kumar")
	if ravi and not _exists(
		"Additional Salary",
		{
			"employee": ravi,
			"salary_component": "Overtime",
			"payroll_date": add_days(start, 14),
			"docstatus": 1,
		},
	):
		frappe.get_doc(
			{
				"doctype": "Additional Salary",
				"employee": ravi,
				"company": COMPANY,
				"salary_component": "Overtime",
				"amount": 1800,
				"currency": CURRENCY,
				"overwrite_salary_structure_amount": 1,
				"payroll_date": add_days(start, 14),
			}
		).submit()
		print("    additional salary: Overtime 1,800 for Ravi Kumar")

	_cancel_failed_payroll_entries(start, end)

	failed = []
	for branch in _payroll_branches():
		pe = _run_payroll_entry(start, end, defaults, cc, branch)
		if pe.status != "Submitted" or pe.error_message:
			failed.append(f"{pe.name} ({branch or 'all branches'}): {pe.status} {pe.error_message or ''}")

	for structure in (SS_SALARIED, SS_WAGE, SS_CONTRACT):
		filters = {"start_date": start, "end_date": end, "salary_structure": structure, "docstatus": 1}
		slips = frappe.get_all(
			"Salary Slip", filters=filters, fields=["name", "employee_name", "gross_pay", "net_pay"], limit=1
		)
		n = frappe.db.count("Salary Slip", filters)
		print(f"    {structure}: {n} submitted slips; sample={slips[0] if slips else None}")
	if failed:
		raise frappe.ValidationError("Payroll Entry failed: " + "; ".join(failed))


def _payroll_branches():
	"""Return the list of Payroll Entry ``branch`` filters to run.

	HRMS copies accounting dimension values on the payroll accrual JE from the Payroll Entry's own
	fields (``PayrollEntry.update_accounting_dimensions``). When a dimension that is mandatory for
	P&L accounts maps to a Payroll Entry field (the Branch dimension -> ``branch``), payroll has to
	be run once per branch; otherwise a single run with ``branch=None`` is enough.
	"""
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		get_checks_for_pl_and_bs_accounts,
	)

	frappe.flags.accounting_dimensions_details = None
	pe_meta = frappe.get_meta("Payroll Entry")
	for dim in get_checks_for_pl_and_bs_accounts() or []:
		if dim.company != COMPANY or not cint(dim.mandatory_for_pl) or cint(dim.disabled):
			continue
		if not pe_meta.has_field(dim.fieldname):
			print(
				f"    mandatory P&L dimension '{dim.label}' is not a Payroll Entry filter; accrual JE may fail"
			)
			continue
		employees = frappe.get_all(
			"Employee", filters={"company": COMPANY, "status": "Active"}, fields=["name", dim.fieldname]
		)
		missing = [e.name for e in employees if not e.get(dim.fieldname)]
		if missing and dim.default_dimension:
			for name in missing:
				frappe.db.set_value("Employee", name, dim.fieldname, dim.default_dimension)
			print(f"    set {dim.fieldname}={dim.default_dimension} on {len(missing)} employees without one")
		values = sorted({e.get(dim.fieldname) or dim.default_dimension for e in employees} - {None})
		if values:
			print(f"    mandatory P&L dimension '{dim.label}': running payroll per {dim.fieldname} {values}")
			return values
	return [None]


def _cancel_failed_payroll_entries(start, end):
	"""Cancel Payroll Entries of this period left in status Failed by an earlier run (their accrual
	JE never posted), so the period can be re-run. Only touches entries created by this script."""
	for name in frappe.get_all(
		"Payroll Entry",
		filters={
			"company": COMPANY,
			"start_date": start,
			"end_date": end,
			"docstatus": 1,
			"status": "Failed",
		},
		pluck="name",
	):
		if frappe.db.exists(
			"Journal Entry Account",
			{"reference_type": "Payroll Entry", "reference_name": name, "docstatus": 1},
		):
			print(f"    payroll entry {name} is Failed but has a posted JE; leaving it alone")
			continue
		print(f"    cancelling failed payroll entry {name} (slips are cancelled and deleted by HRMS)")
		frappe.get_doc("Payroll Entry", name).cancel()
		frappe.db.commit()


def _run_payroll_entry(start, end, defaults, cc, branch=None):
	filters = {"company": COMPANY, "start_date": start, "end_date": end, "docstatus": 1}
	filters["branch"] = branch if branch else ["is", "not set"]
	pe_name = _exists("Payroll Entry", filters)
	if pe_name:
		pe = frappe.get_doc("Payroll Entry", pe_name)
	else:
		frappe.flags.enqueue_payroll_entry = False
		pe = frappe.get_doc(
			{
				"doctype": "Payroll Entry",
				"company": COMPANY,
				"branch": branch,
				"posting_date": nowdate(),
				"payroll_frequency": "Monthly",
				"start_date": start,
				"end_date": end,
				"payroll_payable_account": defaults.default_payroll_payable_account,
				"cost_center": cc["admin"],
				"currency": CURRENCY,
				"exchange_rate": 1,
				"salary_slip_based_on_timesheet": 0,
				"validate_attendance": 0,
			}
		)
		pe.insert()
		pe.fill_employee_details()
		pe.save()
		pe.submit()  # on_submit -> create_salary_slips (inline for <= 30 employees)
		pe.reload()
		frappe.db.commit()
	if not pe.salary_slips_submitted and pe.status != "Failed":
		pe.submit_salary_slips()
		pe.reload()
		frappe.db.commit()

	for name in frappe.get_all(
		"Salary Slip", filters={"payroll_entry": pe.name, "docstatus": 0}, pluck="name"
	):
		# submit_salary_slips() silently skips slips that threw; surface the reason here
		try:
			frappe.get_doc("Salary Slip", name).submit()
		except Exception as e:
			print(f"    slip {name} could not be submitted: {e}")
	n = frappe.db.count("Salary Slip", {"payroll_entry": pe.name, "docstatus": 1})
	print(f"    payroll entry {pe.name} branch={branch} status={pe.status} slips={n}")
	return pe


# ---------------------------------------------------------------------------
# C. Projects
# ---------------------------------------------------------------------------


def step_projects():
	for name, costing, billing in (
		("Fabrication", 400, 900),
		("Design", 800, 1500),
		("Installation", 500, 1000),
		("Testing", 450, 900),
	):
		if frappe.db.exists("Activity Type", name):
			frappe.db.set_value("Activity Type", name, {"costing_rate": costing, "billing_rate": billing})
		else:
			frappe.get_doc(
				{
					"doctype": "Activity Type",
					"activity_type": name,
					"costing_rate": costing,
					"billing_rate": billing,
				}
			).insert()
	_get_or_insert("Project Type", {"project_type": "Custom Manufacturing"})

	project = _exists("Project", {"project_name": PROJECT_NAME, "company": COMPANY})
	if not project:
		customer = "Bharat Mining Co" if frappe.db.exists("Customer", "Bharat Mining Co") else None
		doc = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": PROJECT_NAME,
				"company": COMPANY,
				"customer": customer,
				"project_type": "Custom Manufacturing",
				"status": "Open",
				"expected_start_date": "2026-10-05",
				"expected_end_date": "2026-11-30",
				"estimated_costing": 1800000,
				"overhead_percent": 15,
				"budgeted_margin_percent": 20,
				"collect_progress": 0,
				"percent_complete_method": "Task Completion",
			}
		)
		doc.insert()
		project = doc.name

	tasks = [
		("Design & Drawings", 40, 1, 20, "2026-10-05", "2026-10-12"),
		("Frame Fabrication", 120, 0, 0, "2026-10-12", "2026-11-05"),
		("Drive Assembly", 60, 1, 40, "2026-11-02", "2026-11-16"),
		("Site Installation", 80, 1, 40, "2026-11-16", "2026-11-30"),
	]
	task_names = {}
	for subject, hours, milestone, billing_pct, start, end in tasks:
		name = _exists("Task", {"subject": subject, "project": project})
		if not name:
			doc = frappe.get_doc(
				{
					"doctype": "Task",
					"subject": subject,
					"project": project,
					"company": COMPANY,
					"status": "Open",
					"expected_time": hours,
					"is_milestone": milestone,
					"billing_percent": billing_pct if milestone else 0,
					"exp_start_date": start,
					"exp_end_date": end,
				}
			)
			doc.insert()
			name = doc.name
		task_names[subject] = name

	timesheets = [
		("Arjun Reddy", "Design", "Design & Drawings", "2026-10-06 09:00:00", 8),
		("Ravi Kumar", "Fabrication", "Frame Fabrication", "2026-10-07 06:00:00", 9),
	]
	created = 0
	for emp_name, activity, task, from_time, hours in timesheets:
		emp = _employee_by_name(emp_name)
		if not emp:
			continue
		day = getdate(from_time)
		if _exists(
			"Timesheet",
			{"employee": emp, "start_date": day, "parent_project": project, "docstatus": ["<", 2]},
		):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": emp,
				"company": COMPANY,
				"parent_project": project,
				"time_logs": [
					{
						"activity_type": activity,
						"from_time": from_time,
						"hours": hours,
						"project": project,
						"task": task_names[task],
						"is_billable": 1,
						"billing_hours": hours,
						"description": f"{task} - {hours} h day",
					}
				],
			}
		)
		doc.insert()
		doc.submit()
		created += 1
	print(f"    project {project}, tasks={len(task_names)}, timesheets created={created}")


# ---------------------------------------------------------------------------
# D. Assets
# ---------------------------------------------------------------------------


def _account_by_type(account_type, preferred_names=()):
	"""First non-group HML account of ``account_type``, preferring exact ``account_name`` matches."""
	for name in preferred_names:
		found = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_type": account_type, "is_group": 0, "account_name": name}
		)
		if found:
			return found
	return frappe.db.get_value("Account", {"company": COMPANY, "account_type": account_type, "is_group": 0})


def _asset_accounts(fixed_asset_name):
	return {
		"company_name": COMPANY,
		"fixed_asset_account": _get_account(fixed_asset_name, "Fixed Assets", account_type="Fixed Asset"),
		# per-class accumulated depreciation account when the chart has one, else the generic one
		"accumulated_depreciation_account": _account_by_type(
			"Accumulated Depreciation",
			(f"Accumulated Depreciation - {fixed_asset_name}", "Accumulated Depreciation"),
		),
		"depreciation_expense_account": _account_by_type("Depreciation", ("Depreciation",)),
		"capital_work_in_progress_account": _account_by_type(
			"Capital Work in Progress", ("Capital Work in Progress", "CWIP Account")
		),
	}


def _sync_asset_category_accounts(category, fixed_asset_name):
	"""Make the HML account row of an existing Asset Category match ``_asset_accounts``."""
	wanted = _asset_accounts(fixed_asset_name)
	doc = frappe.get_doc("Asset Category", category)
	row = next((r for r in doc.accounts if r.company_name == COMPANY), None)
	if not row:
		doc.append("accounts", wanted)
	elif any(row.get(k) != v for k, v in wanted.items()):
		row.update(wanted)
	else:
		return False
	doc.save()
	print(
		f"    asset category {category}: HML accounts updated -> {wanted['accumulated_depreciation_account']}"
	)
	return True


def _repost_mislinked_depreciation(asset):
	"""Cancel depreciation JEs of ``asset`` that credit a different accumulated depreciation account
	than the asset category now specifies (an earlier run picked the wrong per-class account); the
	schedule rows are unlinked by ``JournalEntry.unlink_asset_reference`` and re-posted by the caller."""
	category = frappe.db.get_value("Asset", asset, "asset_category")
	correct = frappe.db.get_value(
		"Asset Category Account",
		{"parent": category, "company_name": COMPANY},
		"accumulated_depreciation_account",
	)
	schedules = frappe.get_all(
		"Asset Depreciation Schedule", filters={"asset": asset, "docstatus": 1}, pluck="name"
	)
	jes = frappe.get_all(
		"Depreciation Schedule",
		filters={"parent": ["in", schedules], "journal_entry": ["is", "set"]},
		pluck="journal_entry",
	)
	wrong = frappe.get_all(
		"Journal Entry Account",
		filters={"parent": ["in", jes], "credit": [">", 0], "account": ["!=", correct], "docstatus": 1},
		pluck="parent",
		distinct=True,
	)
	for je in wrong:
		frappe.get_doc("Journal Entry", je).cancel()
	if wrong:
		frappe.db.commit()
		print(f"    cancelled {len(wrong)} depreciation JEs credited to the wrong account; re-posting")
	return len(wrong)


def _fixed_asset_item():
	"""Return a fixed-asset Item for the lathe.

	Uses ``FA-CNC-LATHE`` when it exists as a fixed asset. If the demo-data script created it as a
	plain item (no Asset Category existed yet), convert it in place when no stock ledger exists;
	otherwise create ``FA-CNC-LATHE-2M``.
	"""
	if frappe.db.get_value("Item", ASSET_ITEM, "is_fixed_asset"):
		return ASSET_ITEM
	if frappe.db.exists("Item", ASSET_ITEM):
		item = frappe.get_doc("Item", ASSET_ITEM)
		if not item.is_stock_item and not item.stock_ledger_created():
			item.is_fixed_asset = 1
			item.asset_category = "Production Equipment"
			item.save()
			print(f"    converted existing item {ASSET_ITEM} to fixed asset (Production Equipment)")
			return ASSET_ITEM
		code = f"{ASSET_ITEM}-2M"
		print(f"    {ASSET_ITEM} is a stock item; using {code} instead")
	else:
		code = ASSET_ITEM
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": ASSET_NAME,
				"item_group": "Products" if frappe.db.exists("Item Group", "Products") else "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"is_fixed_asset": 1,
				"asset_category": "Production Equipment",
			}
		).insert()
	return code


def _maintenance_users(count=2):
	"""Users for the maintenance team: wage earners' user_id first, then known Horizon users."""
	users = []
	for e in _wage_earners():
		uid = frappe.db.get_value("Employee", {"employee_name": _full_name(e), "company": COMPANY}, "user_id")
		if uid and uid not in users:
			users.append(uid)
	for fallback in ("priya@horizon.local", "neha@horizon.local", "admin@horizon.local", "Administrator"):
		if len(users) >= count:
			break
		if _user_exists(fallback) and fallback not in users:
			users.append(fallback)
	return users[:count]


def step_assets():
	categories = {
		"Production Equipment": {
			"account": "Production Equipment",
			"fb": {"depreciation_method": "Straight Line", "frequency_of_depreciation": 1, "total_number_of_depreciations": 180},
		},
		"Vehicles": {
			"account": "Vehicles",
			"fb": {"depreciation_method": "Written Down Value", "frequency_of_depreciation": 12, "total_number_of_depreciations": 8, "rate_of_depreciation": 15},
		},
		"IT Equipment": {
			"account": "IT Equipment",
			"fb": {"depreciation_method": "Straight Line", "frequency_of_depreciation": 1, "total_number_of_depreciations": 36},
		},
	}  # fmt: skip
	for name, spec in categories.items():
		if frappe.db.exists("Asset Category", name):
			_sync_asset_category_accounts(name, spec["account"])
			continue
		frappe.get_doc(
			{
				"doctype": "Asset Category",
				"asset_category_name": name,
				"enable_cwip_accounting": 0,
				"finance_books": [spec["fb"]],
				"accounts": [_asset_accounts(spec["account"])],
			}
		).insert()

	_get_or_insert("Location", {"location_name": "Mumbai HQ"})

	item = _fixed_asset_item()

	users = _maintenance_users()
	team = "Plant Maintenance"
	if not frappe.db.exists("Asset Maintenance Team", team):
		if not users:
			raise frappe.ValidationError("No User available for Asset Maintenance Team members")
		frappe.get_doc(
			{
				"doctype": "Asset Maintenance Team",
				"maintenance_team_name": team,
				"company": COMPANY,
				"maintenance_manager": users[0],
				"maintenance_team_members": [
					{"team_member": u, "maintenance_role": "Maintenance User"} for u in users
				],
			}
		).insert()
		print(f"    maintenance team members (Users): {users}")

	cc = _cc_map()
	branch = _branch("Mumbai HQ")
	asset = _exists("Asset", {"asset_name": ASSET_NAME, "company": COMPANY, "docstatus": ["<", 2]})
	if not asset:
		doc = frappe.get_doc(
			{
				"doctype": "Asset",
				"asset_name": ASSET_NAME,
				"item_code": item,
				"asset_category": "Production Equipment",
				"company": COMPANY,
				"asset_owner": "Company",
				"location": "Mumbai HQ",
				"cost_center": cc["equipment"],
				"purchase_date": "2026-04-15",
				"available_for_use_date": "2026-05-01",
				"gross_purchase_amount": 4800000,
				"is_existing_asset": 1,
				"opening_accumulated_depreciation": 0,
				"opening_number_of_booked_depreciations": 0,
				"calculate_depreciation": 1,
				"finance_books": [
					{
						"depreciation_method": "Straight Line",
						"frequency_of_depreciation": 1,
						"total_number_of_depreciations": 180,
						"expected_value_after_useful_life": 240000,
						"depreciation_start_date": "2026-05-31",
					}
				],
			}
		)
		if branch and frappe.get_meta("Asset").has_field("branch"):
			doc.branch = branch  # Branch accounting dimension -> copied onto depreciation JEs
		doc.insert()
		doc.submit()
		asset = doc.name
	elif frappe.db.get_value("Asset", asset, "docstatus") == 0:
		frappe.get_doc("Asset", asset).submit()
	if (
		branch
		and frappe.get_meta("Asset").has_field("branch")
		and not frappe.db.get_value("Asset", asset, "branch")
	):
		frappe.db.set_value("Asset", asset, "branch", branch)
	frappe.db.commit()

	from erpnext.assets.doctype.asset.depreciation import (
		make_depreciation_entry_for_all_asset_depr_schedules,
		post_depreciation_entries,
	)

	_repost_mislinked_depreciation(asset)
	if cint(frappe.db.get_single_value("Accounts Settings", "book_asset_depreciation_entry_automatically")):
		post_depreciation_entries(date=nowdate())
	else:
		print("    Accounts Settings.book_asset_depreciation_entry_automatically is off; posting per asset")
		make_depreciation_entry_for_all_asset_depr_schedules(frappe.get_doc("Asset", asset), nowdate())
		frappe.db.commit()
	je_count = frappe.db.count(
		"Depreciation Schedule",
		{"parent": ["in", frappe.get_all("Asset Depreciation Schedule", filters={"asset": asset}, pluck="name")], "journal_entry": ["is", "set"]},
	)  # fmt: skip
	print(f"    asset {asset}; depreciation JEs posted={je_count}")
	if not je_count:
		print(
			f"    WARNING: no depreciation JE; depr_entry_posting_status={frappe.db.get_value('Asset', asset, 'depr_entry_posting_status')}"
		)

	if not frappe.db.exists("Asset Maintenance", asset):
		from erpnext.assets.doctype.asset_maintenance.asset_maintenance import calculate_next_due_date

		tasks = []
		for task, periodicity, mtype in (
			("Monthly lubrication", "Monthly", "Preventive Maintenance"),
			("Quarterly spindle calibration", "Quarterly", "Calibration"),
		):
			tasks.append(
				{
					"maintenance_task": task,
					"maintenance_type": mtype,
					"maintenance_status": "Planned",
					"start_date": "2026-10-01",
					"periodicity": periodicity,
					"assign_to": users[0],
					"next_due_date": calculate_next_due_date(periodicity, start_date="2026-10-01"),
				}
			)
		try:
			frappe.get_doc(
				{
					"doctype": "Asset Maintenance",
					"asset_name": asset,
					"company": COMPANY,
					"maintenance_team": team,
					"asset_maintenance_tasks": tasks,
				}
			).insert()
		except frappe.DuplicateEntryError:
			# Asset Maintenance is named after the asset; a concurrent run won the race
			frappe.db.rollback()
			print(f"    asset maintenance for {asset} already exists (created concurrently)")

	failure = "2026-09-10 09:30:00"
	if not _exists("Asset Repair", {"asset": asset, "failure_date": failure, "docstatus": ["<", 2]}):
		repair = frappe.get_doc(
			{
				"doctype": "Asset Repair",
				"asset": asset,
				"company": COMPANY,
				"failure_date": failure,
				"completion_date": "2026-09-12 17:00:00",
				"repair_status": "Completed",
				"repair_cost": 35000,
				"description": "Spindle bearing replacement",
				"capitalize_repair_cost": 0,
				"cost_center": cc["equipment"],
			}
		)
		if branch and frappe.get_meta("Asset Repair").has_field("branch"):
			repair.branch = branch
		repair.insert()
		repair.submit()


# ---------------------------------------------------------------------------
# E. Budget & bank
# ---------------------------------------------------------------------------

MONTHLY_PERCENTAGES = [
	("April", 7), ("May", 7.5), ("June", 7.5), ("July", 7.5), ("August", 7.5), ("September", 8),
	("October", 8.5), ("November", 8.5), ("December", 8), ("January", 10), ("February", 10), ("March", 10),
]  # fmt: skip


def step_budgets():
	if not frappe.db.exists("Monthly Distribution", MONTHLY_DISTRIBUTION):
		frappe.get_doc(
			{
				"doctype": "Monthly Distribution",
				"distribution_id": MONTHLY_DISTRIBUTION,
				"fiscal_year": FISCAL_YEAR,
				"percentages": [{"month": m, "percentage_allocation": p} for m, p in MONTHLY_PERCENTAGES],
			}
		).insert()

	cc = _cc_map()
	acc = {
		"cogs": _get_account("Cost of Goods Sold"),
		"overhead": _get_account("Factory Overhead", like=True),
		"salary": _get_account("Salary"),
		"marketing": _get_account("Marketing Expenses", like=True),
		"travel": _get_account("Travel Expenses", like=True),
		"rent": _get_account("Office Rent", like=True) or _get_account("Rent", like=True),
		"utility": _get_account("Utility Expenses", like=True) or _get_account("Electricity", like=True),
		"misc": _get_account("Miscellaneous Expenses", like=True),
	}
	plan = {
		"equipment": [("cogs", 18000000), ("overhead", 2400000), ("salary", 9000000)],
		"spares": [("cogs", 6000000), ("salary", 3000000)],
		"components": [("cogs", 4000000), ("salary", 2000000)],
		"sales": [("salary", 3600000), ("marketing", 1200000), ("travel", 600000)],
		"admin": [("salary", 4800000), ("rent", 2400000), ("utility", 1800000)],
		"rnd": [("salary", 2400000), ("misc", 600000)],
	}
	created = 0
	for cc_key, rows in plan.items():
		cost_center = cc[cc_key]
		if _exists(
			"Budget",
			{
				"cost_center": cost_center,
				"fiscal_year": FISCAL_YEAR,
				"company": COMPANY,
				"docstatus": ["<", 2],
			},
		):
			continue
		accounts = []
		for acc_key, amount in rows:
			if not acc[acc_key]:
				print(f"    budget {cost_center}: account '{acc_key}' not found, row skipped")
				continue
			accounts.append({"account": acc[acc_key], "budget_amount": amount})
		if not accounts:
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Budget",
				"budget_against": "Cost Center",
				"company": COMPANY,
				"cost_center": cost_center,
				"fiscal_year": FISCAL_YEAR,
				"monthly_distribution": MONTHLY_DISTRIBUTION,
				"applicable_on_material_request": 1,
				"action_if_annual_budget_exceeded_on_mr": "Warn",
				"action_if_accumulated_monthly_budget_exceeded_on_mr": "Warn",
				"applicable_on_purchase_order": 1,
				"action_if_annual_budget_exceeded_on_po": "Warn",
				"action_if_accumulated_monthly_budget_exceeded_on_po": "Warn",
				"applicable_on_booking_actual_expenses": 1,
				"action_if_annual_budget_exceeded": "Stop",
				"action_if_accumulated_monthly_budget_exceeded": "Warn",
				"accounts": accounts,
			}
		)
		doc.insert()
		doc.submit()
		created += 1
	print(f"    budgets created={created}")


def _csv_path():
	return os.path.join(frappe.get_app_path("horizon_erp"), "data", "bank_statement_sample.csv")


def step_bank():
	_get_or_insert("Bank", {"bank_name": BANK_NAME})
	gl_account = frappe.db.get_value(
		"Account",
		{"company": COMPANY, "account_type": "Bank", "is_group": 0, "account_name": BANK_NAME},
		"name",
	) or frappe.db.get_value("Account", {"company": COMPANY, "account_type": "Bank", "is_group": 0}, "name")
	if not gl_account:
		gl_account = _get_account(BANK_NAME, "Bank Accounts", account_type="Bank")

	bank_account = f"{BANK_ACCOUNT_NAME} - {BANK_NAME}"
	if not frappe.db.exists("Bank Account", bank_account):
		doc = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": BANK_ACCOUNT_NAME,
				"bank": BANK_NAME,
				"account": gl_account,
				"is_company_account": 1,
				"company": COMPANY,
				"bank_account_no": "50200012345678",
				"branch_code": "HDFC0000123",
			}
		)
		if frappe.get_meta("Bank Account").has_field("reconciliation_frequency"):
			doc.reconciliation_frequency = "Weekly"
		doc.insert()
		bank_account = doc.name

	created = 0
	with open(_csv_path(), newline="") as f:
		for row in csv.DictReader(f):
			txn_id = row["Reference Number"].strip()
			if _exists("Bank Transaction", {"transaction_id": txn_id, "docstatus": ["<", 2]}):
				continue
			doc = frappe.get_doc(
				{
					"doctype": "Bank Transaction",
					"date": row["Date"],
					"bank_account": bank_account,
					"company": COMPANY,
					"currency": CURRENCY,
					"description": row["Description"],
					"reference_number": txn_id,
					"transaction_id": txn_id,
					"withdrawal": flt(row["Debit"]),
					"deposit": flt(row["Credit"]),
				}
			)
			doc.insert()
			doc.submit()
			created += 1
	total = frappe.db.count("Bank Transaction", {"bank_account": bank_account, "docstatus": 1})
	print(f"    bank account {bank_account}; transactions created={created}, total={total}")


def step_recurring_journal_entries():
	cc = _cc_map()
	rent_expense = _get_account("Office Rent", like=True) or _get_account(
		"Rent", "Indirect Expenses", like=True
	)
	rent_payable = _get_account("Rent Payable", "Current Liabilities")
	power_expense = (
		_get_account("Electricity", like=True)
		or _get_account("Utility Expenses", like=True)
		or _get_account("Electricity Expenses", "Indirect Expenses")
	)
	power_payable = _get_account("Electricity Payable", "Current Liabilities")
	posting_date = add_days(_last_month()[0], 4)
	has_branch = frappe.get_meta("Journal Entry Account").has_field("branch")
	branch = "Mumbai HQ" if has_branch and frappe.db.exists("Branch", "Mumbai HQ") else None
	if not has_branch:
		print("    Journal Entry Account has no 'branch' dimension field; skipping branch")

	entries = {
		"Factory Rent": (
			rent_expense,
			rent_payable,
			[
				("admin", 25000),
				("sales", 15000),
				("equipment", 30000),
				("spares", 20000),
				("components", 10000),
			],
		),
		"Factory Electricity": (
			power_expense,
			power_payable,
			[("equipment", 40000), ("spares", 24000), ("components", 16000)],
		),
	}
	_dedupe_recurring_journal_entries([f"{t} - monthly recurring accrual" for t in entries])
	for title, (expense, payable, splits) in entries.items():
		# JournalEntry.validate overwrites ``title`` on insert, so identify our JEs by user_remark
		remark = f"{title} - monthly recurring accrual"
		je = _exists("Journal Entry", {"user_remark": remark, "company": COMPANY, "docstatus": 1})
		if not je:
			rows = []
			for cc_key, amount in splits:
				row = {"account": expense, "debit_in_account_currency": amount, "cost_center": cc[cc_key]}
				if branch:
					row["branch"] = branch
				rows.append(row)
			total = sum(a for _, a in splits)
			credit = {"account": payable, "credit_in_account_currency": total, "cost_center": cc["admin"]}
			if branch:
				credit["branch"] = branch
			rows.append(credit)
			doc = frappe.get_doc(
				{
					"doctype": "Journal Entry",
					"title": title,
					"voucher_type": "Journal Entry",
					"company": COMPANY,
					"posting_date": posting_date,
					"user_remark": remark,
					"accounts": rows,
				}
			)
			doc.insert()
			doc.submit()
			je = doc.name

		if _exists("Auto Repeat", {"reference_doctype": "Journal Entry", "reference_document": je}):
			continue
		try:
			frappe.get_doc(
				{
					"doctype": "Auto Repeat",
					"reference_doctype": "Journal Entry",
					"reference_document": je,
					"frequency": "Monthly",
					"start_date": posting_date,
					"submit_on_creation": 0,
				}
			).insert()
		except Exception as e:
			print(f"    auto repeat for {title} ({je}) skipped: {e}")
	ar = frappe.db.count("Auto Repeat", {"reference_doctype": "Journal Entry", "status": "Active"})
	print(f"    recurring JEs on {posting_date}; active auto repeats={ar}")


def _dedupe_recurring_journal_entries(remarks):
	"""Keep the oldest submitted JE per remark; cancel duplicates created by earlier runs (before
	the lookup keyed on ``user_remark``) and remove their Auto Repeats so they stop generating."""
	for remark in remarks:
		jes = frappe.get_all(
			"Journal Entry",
			filters={"user_remark": remark, "company": COMPANY, "docstatus": 1},
			fields=["name", "auto_repeat"],
			order_by="creation asc",
		)
		for dup in jes[1:]:
			for ar in frappe.get_all(
				"Auto Repeat",
				filters={"reference_doctype": "Journal Entry", "reference_document": dup.name},
				pluck="name",
			):
				frappe.delete_doc("Auto Repeat", ar, ignore_permissions=True)
			frappe.get_doc("Journal Entry", dup.name).cancel()
			print(f"    cancelled duplicate recurring JE {dup.name} ({remark})")
	# Auto Repeats pointing at cancelled JEs would keep generating entries
	for ar in frappe.get_all(
		"Auto Repeat",
		filters={"reference_doctype": "Journal Entry", "status": "Active"},
		fields=["name", "reference_document"],
	):
		if frappe.db.get_value("Journal Entry", ar.reference_document, "docstatus") == 2:
			frappe.delete_doc("Auto Repeat", ar.name, ignore_permissions=True)
			print(f"    removed auto repeat {ar.name} of cancelled JE {ar.reference_document}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

STEPS = [
	("hr_masters", step_hr_masters),
	("holiday_list", step_holiday_list),
	("shift_types", step_shift_types),
	("employees", step_employees),
	("shift_assignments", step_shift_assignments),
	("leave", step_leave),
	("attendance", step_attendance),
	("salary_components", step_salary_components),
	("salary_structures", step_salary_structures),
	("tax_slab_and_payroll_period", step_tax_slab_and_payroll_period),
	("salary_structure_assignments", step_salary_structure_assignments),
	("payroll_run", step_payroll_run),
	("projects", step_projects),
	("assets", step_assets),
	("budgets", step_budgets),
	("bank", step_bank),
	("recurring_journal_entries", step_recurring_journal_entries),
]


def setup_hr_finance():
	"""Create HR / payroll / projects / assets / budget / bank demo data for HML. Idempotent."""
	if not frappe.db.exists("Company", COMPANY):
		frappe.throw(f"Company {COMPANY} not found")
	frappe.flags.mute_emails = True
	results = {}
	for name, fn in STEPS:
		_run_step(name, fn, results)
	print(results)
	return results


def verify():
	"""Print counts for the hand-off report."""
	emp = frappe.get_all("Employee", filters={"company": COMPANY, "status": "Active"}, pluck="name")
	out = {
		"employees": len(emp),
		"attendance": frappe.db.count("Attendance", {"company": COMPANY, "docstatus": 1}),
		"late_entry": frappe.get_all(
			"Attendance", filters={"company": COMPANY, "late_entry": 1, "docstatus": 1},
			fields=["employee_name", "attendance_date", "in_time", "working_hours"],
		),
		"ten_hour_days": frappe.get_all(
			"Attendance", filters={"company": COMPANY, "working_hours": [">=", 9.5], "docstatus": 1},
			fields=["employee_name", "attendance_date", "working_hours"],
		),
		"leave_allocations": frappe.db.count("Leave Allocation", {"company": COMPANY, "docstatus": 1}),
		"salary_slips": {
			s: frappe.get_all(
				"Salary Slip", filters={"salary_structure": s, "docstatus": 1},
				fields=["count(name) as n", "max(gross_pay) as gross", "max(net_pay) as net"],
			)[0]
			for s in (SS_SALARIED, SS_WAGE, SS_CONTRACT)
		},
		"assets": frappe.db.count("Asset", {"company": COMPANY, "docstatus": 1}),
		"depreciation_jes": frappe.db.count(
			"Journal Entry", {"company": COMPANY, "voucher_type": "Depreciation Entry", "docstatus": 1}
		),
		"budgets": frappe.db.count("Budget", {"company": COMPANY, "docstatus": 1}),
		"bank_transactions": frappe.db.count("Bank Transaction", {"company": COMPANY, "docstatus": 1}),
		"projects": frappe.db.count("Project", {"company": COMPANY}),
		"tasks": frappe.db.count("Task", {"company": COMPANY}),
		"timesheets": frappe.db.count("Timesheet", {"company": COMPANY, "docstatus": 1}),
		"auto_repeats": frappe.db.count("Auto Repeat", {"reference_doctype": "Journal Entry", "status": "Active"}),
		"payroll_entries": frappe.get_all("Payroll Entry", filters={"company": COMPANY, "docstatus": 1}, fields=["name", "branch", "status"]),
	}  # fmt: skip
	for k, v in out.items():
		print(f"{k}: {v}")
	return out

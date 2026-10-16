# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""API Usage Report: one row per (client, endpoint) over ``Inventory API Log``.

P95 is computed in Python (nearest-rank) because MariaDB has no percentile aggregate.
"""

import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

STATUS_SUCCESS = "Success"
STATUS_RATE_LIMITED = "Rate Limited"
FAILED_STATUSES = ("Invalid Input", "Error")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.from_date = getdate(filters.from_date or add_days(today(), -7))
	filters.to_date = getdate(filters.to_date or today())
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	logs = get_logs(filters)
	data = build_rows(logs)
	chart = build_chart(logs, filters)
	summary = build_summary(logs)
	return get_columns(), data, None, chart, summary


def get_columns():
	return [
		{"fieldname": "client", "label": _("Client"), "fieldtype": "Data", "width": 200},
		{"fieldname": "endpoint", "label": _("Endpoint"), "fieldtype": "Data", "width": 320},
		{"fieldname": "calls", "label": _("Calls"), "fieldtype": "Int", "width": 80},
		{"fieldname": "success", "label": _("Success"), "fieldtype": "Int", "width": 90},
		{"fieldname": "failed", "label": _("Failed"), "fieldtype": "Int", "width": 80},
		{"fieldname": "rate_limited", "label": _("Rate Limited"), "fieldtype": "Int", "width": 110},
		{
			"fieldname": "avg_ms",
			"label": _("Avg Response ms"),
			"fieldtype": "Float",
			"precision": 1,
			"width": 130,
		},
		{
			"fieldname": "p95_ms",
			"label": _("P95 Response ms"),
			"fieldtype": "Float",
			"precision": 1,
			"width": 130,
		},
		{"fieldname": "last_call", "label": _("Last Call"), "fieldtype": "Datetime", "width": 170},
	]


def get_logs(filters):
	conditions = {
		"timestamp": ["between", [f"{filters.from_date} 00:00:00", f"{filters.to_date} 23:59:59"]],
	}
	if filters.client:
		conditions["client"] = filters.client
	if filters.status:
		conditions["status"] = filters.status
	return frappe.get_all(
		"Inventory API Log",
		filters=conditions,
		fields=["client", "endpoint", "status", "response_time_ms", "timestamp"],
		order_by="timestamp asc",
	)


def percentile(values, pct):
	"""Nearest-rank percentile; ``values`` need not be sorted."""
	if not values:
		return 0.0
	ordered = sorted(values)
	rank = max(int(math.ceil(pct / 100.0 * len(ordered))), 1)
	return flt(ordered[rank - 1])


def build_rows(logs):
	groups = defaultdict(
		lambda: {"calls": 0, "success": 0, "failed": 0, "rate_limited": 0, "times": [], "last": None}
	)
	for row in logs:
		g = groups[(row.client or "", row.endpoint or "")]
		g["calls"] += 1
		if row.status == STATUS_SUCCESS:
			g["success"] += 1
		elif row.status == STATUS_RATE_LIMITED:
			g["rate_limited"] += 1
		elif row.status in FAILED_STATUSES:
			g["failed"] += 1
		if row.status != STATUS_RATE_LIMITED:  # rejected calls do no work; keep latency honest
			g["times"].append(flt(row.response_time_ms))
		if row.timestamp and (g["last"] is None or row.timestamp > g["last"]):
			g["last"] = row.timestamp

	data = []
	for (client, endpoint), g in sorted(groups.items(), key=lambda kv: (-kv[1]["calls"], kv[0])):
		times = g["times"]
		data.append(
			{
				"client": client,
				"endpoint": endpoint,
				"calls": g["calls"],
				"success": g["success"],
				"failed": g["failed"],
				"rate_limited": g["rate_limited"],
				"avg_ms": flt(sum(times) / len(times), 1) if times else 0.0,
				"p95_ms": flt(percentile(times, 95), 1),
				"last_call": g["last"],
			}
		)
	return data


def build_chart(logs, filters):
	per_day = defaultdict(lambda: {"calls": 0, "ms": []})
	for row in logs:
		day = getdate(row.timestamp)
		per_day[day]["calls"] += 1
		if row.status != STATUS_RATE_LIMITED:
			per_day[day]["ms"].append(flt(row.response_time_ms))

	labels, calls, avg_ms = [], [], []
	day = filters.from_date
	while day <= filters.to_date:
		bucket = per_day.get(day, {"calls": 0, "ms": []})
		labels.append(day.strftime("%d-%m"))
		calls.append(bucket["calls"])
		avg_ms.append(flt(sum(bucket["ms"]) / len(bucket["ms"]), 1) if bucket["ms"] else 0)
		day = add_days(day, 1)

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Calls"), "values": calls},
				{"name": _("Avg Response ms"), "values": avg_ms},
			],
		},
		"type": "line",
		"colors": ["#5e64ff", "#ff9f43"],
	}


def build_summary(logs):
	total = len(logs)
	success = sum(1 for r in logs if r.status == STATUS_SUCCESS)
	rate_limited = sum(1 for r in logs if r.status == STATUS_RATE_LIMITED)
	failed = sum(1 for r in logs if r.status in FAILED_STATUSES)
	times = [flt(r.response_time_ms) for r in logs if r.status != STATUS_RATE_LIMITED]
	return [
		{"value": total, "label": _("Total Calls"), "datatype": "Int", "indicator": "Blue"},
		{"value": success, "label": _("Success"), "datatype": "Int", "indicator": "Green"},
		{"value": failed, "label": _("Failed"), "datatype": "Int", "indicator": "Red" if failed else "Green"},
		{
			"value": rate_limited,
			"label": _("Rate Limited"),
			"datatype": "Int",
			"indicator": "Orange" if rate_limited else "Green",
		},
		{
			"value": flt(sum(times) / len(times), 1) if times else 0,
			"label": _("Avg Response ms"),
			"datatype": "Float",
		},
		{"value": flt(percentile(times, 95), 1), "label": _("P95 Response ms"), "datatype": "Float"},
	]

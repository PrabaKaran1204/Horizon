# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

import datetime
import json

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime_in_timezone, get_system_timezone, now_datetime

STATUS_SUCCESS = "Success"
STATUS_INVALID_INPUT = "Invalid Input"
STATUS_RATE_LIMITED = "Rate Limited"
STATUS_ERROR = "Error"
MAX_ERROR_LENGTH = 5000


class InventoryAPILog(Document):
	pass


def iso_now() -> str:
	"""Current time in the site timezone as ISO-8601 with offset, e.g. ``2026-10-16T10:30:00+05:30``."""
	return get_datetime_in_timezone(get_system_timezone()).isoformat(timespec="seconds")


def log_api_call(
	endpoint: str,
	client: str,
	parameters,
	response_time_ms: float,
	http_status: int,
	status: str,
	error: str | None = None,
	ip_address: str | None = None,
	commit: bool = False,
) -> str | None:
	"""Insert an ``Inventory API Log`` row. Never raises: a logging failure must not break the API.

	:param commit: commit right away. Use only on paths that re-raise an exception afterwards,
	        because Frappe rolls the transaction back when a request ends in an exception.
	        Normal paths rely on the framework commit; ``frappe.local.flags.commit`` is set so GET
	        requests (which Frappe otherwise rolls back) persist the row too.
	:return: the log name, or ``None`` when logging failed.
	"""
	try:
		if not isinstance(parameters, str):
			parameters = json.dumps(parameters, default=str, sort_keys=True)
		if error:
			error = str(error)[:MAX_ERROR_LENGTH]

		log = frappe.get_doc(
			{
				"doctype": "Inventory API Log",
				"timestamp": now_datetime(),
				"endpoint": endpoint,
				"client": client,
				"parameters": parameters,
				"response_time_ms": round(float(response_time_ms or 0), 2),
				"http_status": int(http_status or 0),
				"status": status,
				"error": error,
				"ip_address": ip_address or getattr(frappe.local, "request_ip", None),
			}
		)
		log.flags.ignore_permissions = True
		log.insert(ignore_permissions=True)
		frappe.local.flags.commit = True
		if commit:
			frappe.db.commit()  # nosemgrep: the request ends in an exception right after this
		return log.name
	except Exception:
		frappe.log_error(title="Inventory API Log insert failed")
		return None


def truncate_traceback(text: str | None) -> str | None:
	return str(text)[:MAX_ERROR_LENGTH] if text else None


def serialise(value):
	"""JSON-safe scalar: datetimes become ISO strings."""
	if isinstance(value, datetime.datetime | datetime.date):
		return value.isoformat()
	return value

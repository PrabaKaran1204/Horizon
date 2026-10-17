# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Shared infrastructure for Horizon scheduler jobs.

Logging decision
----------------
The functional brief asks to "log findings to Integration Log". Frappe v15 / ERPNext v15 ship no
DocType by that name (Frappe has ``Integration Request`` which is for outbound API calls, and
``Scheduled Job Log`` which the scheduler already writes for every ``scheduler_events`` run).
We therefore:

* rely on Frappe's own ``Scheduled Job Log`` for the per-run record,
* write failures to ``Error Log`` (``frappe.log_error``) and raise an Alert to System Managers,
* write per-document findings as ``Comment`` (``comment_type="Info"``) on the affected document
  (e.g. stock-accuracy flags on the Item, escalations on the Purchase Order),
* return a summary dict from every job so tests and ``bench execute`` can inspect the outcome,
* and emit the summary through ``frappe.logger("horizon_jobs")``.
"""

import functools
import json

import frappe
from frappe import _
from frappe.utils import cstr, get_url_to_form, nowdate, today
from frappe.utils.user import get_users_with_role

RETRY_MARKER = "horizon:retry:{job}"
RETRY_MARKER_TTL = 86400


def logger():
	return frappe.logger("horizon_jobs", allow_site=True, file_count=10)


# Cache helpers for keys with a TTL. ``expires=True`` is essential: without it frappe.cache()
# memoises the value (even ``None``) in ``frappe.local.cache`` and a later ``set_value`` with
# ``expires_in_sec`` only writes to Redis, so the same request keeps reading the stale copy.
def cache_get(key):
	return frappe.cache().get_value(key, expires=True)


def cache_set(key, value, ttl_seconds):
	frappe.cache().set_value(key, value, expires_in_sec=ttl_seconds)


def cache_delete(key):
	frappe.cache().delete_value(key)


def horizon_job(name):
	"""Decorator for scheduler entry points.

	* On entry: if a retry marker from a previous failed run exists, log
	  "retrying after previous failure" and clear it.
	* On success: log the returned summary and return it unchanged.
	* On failure: write an Error Log, alert System Managers (Notification Log + email),
	  set the retry marker (24 h TTL) and return ``{"error": <message>}`` so the scheduler
	  does not mark every other job in the same tick as failed.
	"""

	def decorator(func):
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			key = RETRY_MARKER.format(job=name)
			if cache_get(key):
				logger().warning(f"{name}: retrying after previous failure")
				cache_delete(key)

			try:
				result = func(*args, **kwargs)
			except Exception as exc:
				title = f"Horizon job failed: {name}"
				frappe.log_error(title=title, message=frappe.get_traceback())
				_alert_system_managers(title, exc)
				cache_set(key, 1, RETRY_MARKER_TTL)
				logger().error(f"{name}: failed with {exc!r}")
				return {"error": cstr(exc), "job": name}

			try:
				logger().info(f"{name}: {json.dumps(result, default=str)[:2000]}")
			except Exception:
				logger().info(f"{name}: {result!r}"[:2000])
			return result

		return wrapper

	return decorator


def _alert_system_managers(title, exc):
	"""Alert to all enabled System Managers. Never raises."""
	try:
		users = get_users_with_role("System Manager")
		message = _("Scheduled job failed: {0}<br>{1}<br>See Error Log for the traceback.").format(
			title, frappe.utils.escape_html(cstr(exc))[:500]
		)
		notify_users(users, title, message, doctype="Error Log", docname=None, email=True)
	except Exception:
		frappe.log_error(title="Horizon job: could not alert System Managers")


def notify_users(users, subject, message, doctype=None, docname=None, email=True, attachments=None):
	"""Create one Notification Log (bell) per user and optionally one email to all of them.

	``users`` are User ids (emails). Disabled users and empty lists are ignored. Email errors
	(no outgoing account configured) are logged, not raised, so a job never fails on SMTP.
	Returns the list of users actually notified.
	"""
	users = [u for u in dict.fromkeys(users or []) if u and u not in ("Administrator", "Guest")]
	if users:
		enabled = frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name")
		users = [u for u in users if u in enabled]
	if not users:
		return []

	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	log = {
		"type": "Alert",
		"subject": subject,
		"email_content": message,
		"document_type": doctype,
		"document_name": docname,
		"from_user": frappe.session.user,
	}
	if doctype and docname:
		log["link"] = get_url_to_form(doctype, docname)
	enqueue_create_notification(users, log)

	if email:
		safe_sendmail(
			f"Horizon notify: email failed for '{subject}'",
			recipients=users,
			subject=subject,
			message=message,
			reference_doctype=doctype if docname else None,
			reference_name=docname,
			attachments=attachments,
		)
	return users


def safe_sendmail(error_title, **sendmail_kwargs):
	"""``frappe.sendmail`` that never raises.

	Any failure (no default outgoing Email Account -> ``OutgoingEmailError``; a placeholder account
	with ``mute_emails`` on -> ``AttributeError`` deep in the queue builder; SMTP errors) is written
	to Error Log once under ``error_title`` and ``False`` is returned, so a business transaction or
	a scheduler job never fails because of e-mail. Returns ``True`` when the mail was queued.
	"""
	try:
		frappe.sendmail(**sendmail_kwargs)
		return True
	except Exception:
		frappe.log_error(title=error_title, message=frappe.get_traceback())
		return False


def users_with_roles(*roles):
	"""Return the de-duplicated list of enabled users having any of ``roles``."""
	out = []
	for role in roles:
		if role and frappe.db.exists("Role", role):
			out.extend(get_users_with_role(role))
	return list(dict.fromkeys(out))


def once_per_day(key, user_or_doc=""):
	"""Return True the first time this (key, day) pair is seen; subsequent calls on the same day
	return False. Backed by the cache with a 24 h TTL."""
	cache_key = f"horizon:dedupe:{key}:{user_or_doc}:{nowdate()}"
	if cache_get(cache_key):
		return False
	cache_set(cache_key, 1, 86400)
	return True


def add_info_comment(doctype, docname, content, dedupe_prefix=None):
	"""Add an Info comment; when ``dedupe_prefix`` is given, skip if a comment starting with
	it was already added today on the same document."""
	if dedupe_prefix:
		exists = frappe.db.exists(
			"Comment",
			{
				"reference_doctype": doctype,
				"reference_name": docname,
				"comment_type": "Info",
				"content": ["like", f"{dedupe_prefix}%"],
				"creation": [">=", today()],
			},
		)
		if exists:
			return None
	comment = frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": doctype,
			"reference_name": docname,
			"content": content,
		}
	)
	comment.insert(ignore_permissions=True)
	return comment.name


def horizon_company():
	"""The Horizon company (abbr HML) or the default company, or None on an empty site."""
	company = frappe.db.get_value("Company", {"abbr": "HML"}, "name")
	return company or frappe.defaults.get_global_default("company")


def first_existing_warehouse(*names):
	for name in names:
		if name and frappe.db.exists("Warehouse", name):
			return name
	return None

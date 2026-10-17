# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Tests for ``horizon_erp.horizon_integrations.inventory_api.get_inventory_snapshot`` (and its
legacy ``horizon_erp.api`` aliases) and the sync client.

Run:
	bench --site horizon.local run-tests --app horizon_erp \
	    --module horizon_erp.horizon_integrations.tests.test_inventory_api --skip-test-records

Fixtures are created here (prefix ``APITEST-``) and committed once in ``setUpClass`` because
``test_permission_denied_log_survives_rollback`` issues a real ``frappe.db.rollback()`` (the API
itself commits the 403 log row before re-raising, so the fixtures would be committed by that test
anyway). Everything persisted is removed again by the class cleanups registered *before*
``super().setUpClass()`` so that they run after ``FrappeTestCase``'s own rollback: ``_cleanup``
drops the fixtures, their Users and the Contacts ``User.after_insert`` creates, then
``purge_test_residue`` removes Error Log / Comment / Deleted Document rows mentioning the prefixes.
Stock is written straight into ``tabBin`` (``get_or_make_bin`` + ``db.set_value``) instead of
posting a Stock Entry: the API reads Bin only, and this keeps the test independent of the
company's accounting setup and trivially cleanable.
"""

import importlib.util
import json
import pathlib
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from horizon_erp.horizon_integrations import inventory_api as inventory
from horizon_erp.horizon_integrations.doctype.inventory_api_log.inventory_api_log import (
	STATUS_ERROR,
	STATUS_INVALID_INPUT,
	STATUS_RATE_LIMITED,
	STATUS_SUCCESS,
)
from horizon_erp.horizon_integrations.rate_limit import CONF_LIMIT_KEY, check_rate_limit, reset_rate_limit
from horizon_erp.tests.cleanup import purge_test_residue

COMPANY = "Horizon Manufacturing Ltd"
ABBR = "HML"
PREFIX = "APITEST-"
GROUP_WH = f"{PREFIX}Group"
LEAF_WH_1 = f"{PREFIX}Main"
LEAF_WH_2 = f"{PREFIX}Second"
ITEM_A = f"{PREFIX}ITEM-A"
ITEM_C = f"{PREFIX}ITEM-C"
ITEM_DISABLED = f"{PREFIX}ITEM-DISABLED"
API_USER = "apitest-sync@example.com"
NOPERM_USER = "apitest-noperm@example.com"
WHPERM_USER = "gaptest-whperm@example.com"  # Stock User limited to LEAF_WH_1 by a User Permission


def wh(name):
	return f"{name} - {ABBR}"


class TestInventoryAPI(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		# LIFO: both run after FrappeTestCase._rollback_db -> _cleanup first, then the residue purge
		cls.addClassCleanup(purge_test_residue, ("APITEST", "GAPTEST"))
		cls.addClassCleanup(cls._cleanup)
		super().setUpClass()
		frappe.set_user("Administrator")
		cls._cleanup()
		cls._make_users()
		cls._make_warehouses()
		cls._make_warehouse_permission()
		cls._make_items()
		cls._make_bins()
		# the only commit of test state: test_permission_denied_log_survives_rollback needs the
		# fixtures to survive a real rollback (see module docstring)
		frappe.db.commit()  # nosemgrep

	def setUp(self):
		# every API call in the tests runs as the dedicated test client so that cleanup never
		# touches log rows written by real users (e.g. Administrator) on the same site
		frappe.set_user(API_USER)
		frappe.local.response = frappe._dict()
		frappe.local.flags.commit = False
		for user in (API_USER, NOPERM_USER, WHPERM_USER):
			reset_rate_limit(user)

	def tearDown(self):
		frappe.set_user("Administrator")
		for user in (API_USER, NOPERM_USER, WHPERM_USER):
			reset_rate_limit(user)

	# ------------------------------------------------------------------ fixtures
	@classmethod
	def _make_users(cls):
		for email, roles in (
			(API_USER, ["System Manager", "Stock User"]),
			(NOPERM_USER, []),
			(WHPERM_USER, ["Stock User"]),
		):
			if frappe.db.exists("User", email):
				continue
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@")[0],
					"send_welcome_email": 0,
					"roles": [{"role": r} for r in roles],
				}
			)
			user.insert(ignore_permissions=True)

	@classmethod
	def _make_warehouse_permission(cls):
		if frappe.db.exists("User Permission", {"user": WHPERM_USER, "allow": "Warehouse"}):
			return
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": WHPERM_USER,
				"allow": "Warehouse",
				"for_value": wh(LEAF_WH_1),
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)

	@classmethod
	def _make_warehouses(cls):
		for name, parent, is_group in (
			(GROUP_WH, wh("All Warehouses"), 1),
			(LEAF_WH_1, wh(GROUP_WH), 0),
			(LEAF_WH_2, wh(GROUP_WH), 0),
		):
			if frappe.db.exists("Warehouse", wh(name)):
				continue
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": name,
					"company": COMPANY,
					"parent_warehouse": parent,
					"is_group": is_group,
				}
			).insert(ignore_permissions=True)

	@classmethod
	def _make_items(cls):
		if not frappe.get_meta("Item").has_field("criticality"):
			from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

			create_custom_fields(
				{
					"Item": [
						{
							"fieldname": "criticality",
							"fieldtype": "Select",
							"label": "Criticality",
							"options": "A\nB\nC",
							"default": "B",
							"insert_after": "item_group",
						}
					]
				}
			)
		specs = (
			# item, criticality, disabled, reorder rows [(warehouse, level, qty)]
			(ITEM_A, "A", 0, [(wh(LEAF_WH_1), 20, 50)]),
			(ITEM_C, "C", 0, [(wh("Stores"), 5, 10)]),  # fallback: no row for the test warehouse
			(ITEM_DISABLED, "A", 1, []),
		)
		# India Compliance makes gst_hsn_code mandatory on Item; reuse any existing HSN master row
		hsn_code = (
			frappe.db.get_value("GST HSN Code", {}, "name")
			if frappe.db.exists("DocType", "GST HSN Code")
			else None
		)
		for code, criticality, disabled, reorder in specs:
			if frappe.db.exists("Item", code):
				continue
			item = frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": f"{code} name",
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"gst_hsn_code": hsn_code,
					"criticality": criticality,
					"reorder_levels": [
						{
							"warehouse_group": wh("All Warehouses"),
							"warehouse": w,
							"warehouse_reorder_level": level,
							"warehouse_reorder_qty": qty,
							"material_request_type": "Purchase",
						}
						for w, level, qty in reorder
					],
				}
			)
			item.flags.ignore_mandatory = True
			item.insert(ignore_permissions=True)
			if disabled:
				frappe.db.set_value("Item", code, "disabled", 1)

	@classmethod
	def _make_bins(cls):
		from erpnext.stock.utils import get_or_make_bin

		# item, warehouse, actual, reserved, rate
		for code, warehouse, actual, reserved, rate in (
			(ITEM_A, wh(LEAF_WH_1), 15, 5, 100),
			(ITEM_A, wh(LEAF_WH_2), 5, 0, 100),
			(ITEM_C, wh(LEAF_WH_1), 8, 0, 50),
			(ITEM_DISABLED, wh(LEAF_WH_1), 99, 0, 1),
		):
			name = get_or_make_bin(code, warehouse)
			frappe.db.set_value(
				"Bin",
				name,
				{
					"actual_qty": actual,
					"reserved_qty": reserved,
					"projected_qty": actual - reserved,
					"valuation_rate": rate,
					"stock_value": actual * rate,
				},
				update_modified=False,
			)

	@classmethod
	def _cleanup(cls):
		"""Remove every persisted fixture; runs before setUpClass and again after the class rollback."""
		frappe.set_user("Administrator")
		users = [API_USER, NOPERM_USER, WHPERM_USER]
		frappe.db.delete("Inventory API Log", {"client": ["in", users]})
		frappe.db.delete("User Permission", {"user": WHPERM_USER})
		frappe.db.delete("Bin", {"item_code": ["like", f"{PREFIX}%"]})
		for code in (ITEM_A, ITEM_C, ITEM_DISABLED):
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True, delete_permanently=True)
		for name in (LEAF_WH_1, LEAF_WH_2, GROUP_WH):
			if frappe.db.exists("Warehouse", wh(name)):
				frappe.delete_doc(
					"Warehouse", wh(name), force=True, ignore_permissions=True, delete_permanently=True
				)
		# User.after_insert creates a Contact per user; User.on_trash does not remove it
		for contact in frappe.get_all(
			"Contact", filters=[["Contact", "email_id", "in", users]], pluck="name"
		) + frappe.get_all("Contact", filters={"user": ["in", users]}, pluck="name"):
			if frappe.db.exists("Contact", contact):
				frappe.delete_doc(
					"Contact", contact, force=True, ignore_permissions=True, delete_permanently=True
				)
		for email in users:
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True, delete_permanently=True)
			reset_rate_limit(email)
		frappe.db.commit()  # nosemgrep: persisted fixtures must really be gone

	# ------------------------------------------------------------------ helpers
	def call(self, **kwargs):
		frappe.local.response = frappe._dict()
		return inventory.get_inventory_snapshot(**kwargs)

	def status_code(self):
		return frappe.local.response.get("http_status_code") or 200

	def last_log(self, client=API_USER):
		rows = frappe.get_all(
			"Inventory API Log",
			filters={"client": client},
			fields=["name", "status", "http_status", "endpoint", "parameters", "error", "response_time_ms"],
			order_by="creation desc, name desc",
			limit=1,
		)
		return rows[0] if rows else None

	@staticmethod
	def by_code(body):
		return {i["item_code"]: i for i in body["items"]}

	# ------------------------------------------------------------------ tests
	def test_warehouse_resolution(self):
		self.assertEqual(inventory.resolve_warehouse(wh(GROUP_WH)), wh(GROUP_WH))
		self.assertEqual(inventory.resolve_warehouse(GROUP_WH), wh(GROUP_WH))  # name + " - HML"
		self.assertEqual(inventory.resolve_warehouse(LEAF_WH_1), wh(LEAF_WH_1))  # warehouse_name
		self.assertIsNone(inventory.resolve_warehouse("APITEST-does-not-exist"))
		self.assertEqual(inventory.get_leaf_warehouses(wh(GROUP_WH)), [wh(LEAF_WH_1), wh(LEAF_WH_2)])
		self.assertEqual(inventory.get_leaf_warehouses(wh(LEAF_WH_1)), [wh(LEAF_WH_1)])

	def test_leaf_snapshot_fields_and_math(self):
		body = self.call(warehouse=LEAF_WH_1)
		self.assertEqual(self.status_code(), 200)
		self.assertEqual(body["warehouse"], wh(LEAF_WH_1))
		self.assertEqual(body["warehouses_included"], [wh(LEAF_WH_1)])
		self.assertRegex(body["timestamp"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
		self.assertGreater(body["generated_in_ms"], 0)

		items = self.by_code(body)
		self.assertNotIn(ITEM_DISABLED, items, "disabled items must be excluded")
		a = items[ITEM_A]
		self.assertEqual(a["item_name"], f"{ITEM_A} name")
		self.assertEqual(a["item_group"], "All Item Groups")
		self.assertEqual(a["criticality"], "A")
		self.assertAlmostEqual(a["actual_qty"], 15)
		self.assertAlmostEqual(a["reserved_qty"], 5)
		self.assertAlmostEqual(a["available_qty"], 10)  # actual - reserved
		self.assertAlmostEqual(a["projected_qty"], 10)
		self.assertAlmostEqual(a["reorder_point"], 20)
		self.assertAlmostEqual(a["reorder_qty"], 50)
		self.assertTrue(a["below_reorder"])
		self.assertAlmostEqual(a["valuation_rate"], 100)

		c = items[ITEM_C]
		self.assertEqual(c["criticality"], "C")
		self.assertAlmostEqual(c["available_qty"], 8)
		self.assertAlmostEqual(c["reorder_point"], 5, msg="falls back to any Item Reorder row")
		self.assertFalse(c["below_reorder"])

		self.assertEqual(body["summary"]["item_count"], 2)
		self.assertEqual(body["summary"]["low_stock_count"], 1)
		self.assertAlmostEqual(body["summary"]["total_stock_value"], 15 * 100 + 8 * 50)

		alerts = body["low_stock_alerts"]
		self.assertEqual(len(alerts), 1)
		self.assertEqual(alerts[0]["item_code"], ITEM_A)
		self.assertAlmostEqual(alerts[0]["shortfall"], 10)
		self.assertEqual(alerts[0]["criticality"], "A")

		log = self.last_log()
		self.assertEqual(log.status, STATUS_SUCCESS)
		self.assertEqual(log.http_status, 200)
		self.assertEqual(log.endpoint, inventory.ENDPOINT)
		self.assertEqual(json.loads(log.parameters)["warehouse"], LEAF_WH_1)
		self.assertGreater(flt(log.response_time_ms), 0)

	def test_group_warehouse_aggregates_children(self):
		body = self.call(warehouse=GROUP_WH)
		self.assertEqual(body["warehouse"], wh(GROUP_WH))
		self.assertEqual(body["warehouses_included"], [wh(LEAF_WH_1), wh(LEAF_WH_2)])
		a = self.by_code(body)[ITEM_A]
		self.assertAlmostEqual(a["actual_qty"], 20)
		self.assertAlmostEqual(a["available_qty"], 15)
		self.assertTrue(a["below_reorder"])
		self.assertAlmostEqual(body["low_stock_alerts"][0]["shortfall"], 5)
		self.assertAlmostEqual(body["summary"]["total_stock_value"], 20 * 100 + 8 * 50)

	def test_filter_by_criticality(self):
		for truthy in (True, "true", "1", 1):
			body = self.call(warehouse=LEAF_WH_1, filter_by_criticality=truthy)
			self.assertEqual([i["item_code"] for i in body["items"]], [ITEM_A], msg=f"value={truthy!r}")
		for falsy in (False, "false", "0", 0, None):
			body = self.call(warehouse=LEAF_WH_1, filter_by_criticality=falsy)
			self.assertEqual(body["summary"]["item_count"], 2, msg=f"value={falsy!r}")

	def test_invalid_warehouse_returns_404(self):
		body = self.call(warehouse="APITEST-does-not-exist")
		self.assertEqual(self.status_code(), 404)
		self.assertEqual(body["error"], "invalid_warehouse")
		self.assertIn("APITEST-does-not-exist", body["message"])
		self.assertIn("hint", body)
		self.assertIn("timestamp", body)
		log = self.last_log()
		self.assertEqual((log.status, log.http_status), (STATUS_INVALID_INPUT, 404))

	def test_missing_warehouse_returns_400(self):
		for value in (None, "", "   "):
			body = self.call(warehouse=value)
			self.assertEqual(self.status_code(), 400)
			self.assertEqual(body["error"], "missing_warehouse")
		self.assertEqual(self.last_log().http_status, 400)

	def test_simulated_failure_returns_503_and_logs_error(self):
		self.assertTrue(frappe.conf.developer_mode, "developer_mode must be on for _simulate_failure")
		body = self.call(warehouse=LEAF_WH_1, _simulate_failure=1)
		self.assertEqual(self.status_code(), 503)
		self.assertEqual(body["error"], "temporary_failure")
		self.assertEqual(body["retry_after_seconds"], 30)
		log = self.last_log()
		self.assertEqual((log.status, log.http_status), (STATUS_ERROR, 503))
		self.assertIn("simulated database failure", log.error)
		self.assertLessEqual(len(log.error), 5000)
		# fixtures must survive the savepoint rollback used on the error path
		self.assertTrue(frappe.db.exists("Warehouse", wh(LEAF_WH_1)))

	def test_permission_denied_log_survives_rollback(self):
		frappe.set_user(NOPERM_USER)
		with self.assertRaises(frappe.PermissionError):
			self.call(warehouse=LEAF_WH_1)
		self.assertEqual(self.status_code(), 403)
		# Frappe rolls back the transaction when a request ends in an exception; emulate that
		frappe.db.rollback()
		frappe.set_user("Administrator")
		log = self.last_log(client=NOPERM_USER)
		self.assertIsNotNone(log, "403 log row must be committed before the exception is raised")
		self.assertEqual((log.status, log.http_status), (STATUS_ERROR, 403))

	def test_unrestricted_user_sees_every_leaf(self):
		self.assertIsNone(inventory.get_permitted_warehouses(API_USER))  # System Manager
		body = self.call(warehouse=GROUP_WH)
		self.assertEqual(body["warehouses_excluded"], [])

	def test_warehouse_user_permission_trims_group(self):
		frappe.set_user(WHPERM_USER)
		self.assertEqual(inventory.get_permitted_warehouses(), {wh(LEAF_WH_1)})
		body = self.call(warehouse=GROUP_WH)
		self.assertEqual(self.status_code(), 200)
		self.assertEqual(body["warehouses_included"], [wh(LEAF_WH_1)])
		self.assertEqual(body["warehouses_excluded"], [wh(LEAF_WH_2)])
		a = self.by_code(body)[ITEM_A]
		self.assertAlmostEqual(a["actual_qty"], 15, msg="stock of the excluded leaf must not be counted")
		frappe.set_user("Administrator")
		log = self.last_log(client=WHPERM_USER)
		self.assertEqual((log.status, log.http_status), (STATUS_SUCCESS, 200))

	def test_warehouse_user_permission_denies_other_leaf(self):
		frappe.set_user(WHPERM_USER)
		body = self.call(warehouse=LEAF_WH_2)
		self.assertEqual(self.status_code(), 403)
		self.assertEqual(body["error"], "warehouse_not_permitted")
		self.assertEqual(body["warehouse"], wh(LEAF_WH_2))
		self.assertIn("timestamp", body)
		frappe.set_user("Administrator")
		log = self.last_log(client=WHPERM_USER)
		self.assertEqual((log.status, log.http_status), (STATUS_ERROR, 403))
		self.assertIn("not permitted", log.error)

	def test_rate_limit_returns_429_and_logs(self):
		frappe.db.delete("Inventory API Log", {"client": API_USER})  # count only this test's rows
		frappe.set_user(API_USER)
		limit = 5
		frappe.conf[CONF_LIMIT_KEY] = limit
		try:
			for _ in range(limit):
				body = self.call(warehouse=LEAF_WH_1)
				self.assertEqual(self.status_code(), 200)
				self.assertIn("items", body)
			body = self.call(warehouse=LEAF_WH_1)
		finally:
			frappe.conf.pop(CONF_LIMIT_KEY, None)

		self.assertEqual(self.status_code(), 429)
		self.assertEqual(body["error"], "rate_limited")
		self.assertEqual(body["limit"], limit)
		self.assertEqual(body["remaining"], 0)
		self.assertGreater(body["retry_after_seconds"], 0)
		self.assertLessEqual(body["retry_after_seconds"], 3600)

		# headers exposed through frappe.local.rate_limiter (picked up by frappe.app.process_response)
		headers = frappe.local.rate_limiter.headers()
		self.assertEqual(headers["X-RateLimit-Limit"], limit)
		self.assertEqual(headers["X-RateLimit-Remaining"], 0)
		self.assertEqual(headers["Retry-After"], body["retry_after_seconds"])

		frappe.set_user("Administrator")
		log = self.last_log(client=API_USER)
		self.assertEqual((log.status, log.http_status), (STATUS_RATE_LIMITED, 429))
		counts = frappe.get_all(
			"Inventory API Log",
			filters={"client": API_USER},
			fields=["status", "count(name) as n"],
			group_by="status",
		)
		self.assertEqual({c.status: c.n for c in counts}, {STATUS_SUCCESS: limit, STATUS_RATE_LIMITED: 1})

	def test_rate_limit_default_is_100_per_hour(self):
		reset_rate_limit("apitest-counter")
		for i in range(1, 101):
			state = check_rate_limit("apitest-counter", 100, 3600)
			self.assertFalse(state.rejected, msg=f"call {i} must pass")
		self.assertEqual(state.remaining, 0)
		self.assertTrue(check_rate_limit("apitest-counter", 100, 3600).rejected)
		self.assertGreater(frappe.cache.ttl(state.key), 0, "bucket key must expire")
		reset_rate_limit("apitest-counter")


# ---------------------------------------------------------------------------
# standalone client: backoff schedule (no network, no frappe)
# ---------------------------------------------------------------------------


def _load_client_module():
	path = pathlib.Path(__file__).resolve().parents[1] / "client" / "inventory_sync_client.py"
	spec = importlib.util.spec_from_file_location("inventory_sync_client", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class _FakeResponse:
	def __init__(self, status_code, payload=None, headers=None):
		self.status_code = status_code
		self._payload = payload if payload is not None else {}
		self.headers = headers or {}
		self.text = json.dumps(self._payload)

	def json(self):
		return self._payload


class _FakeSession:
	def __init__(self, outcomes):
		self.outcomes = list(outcomes)
		self.calls = []

	def post(self, url, **kwargs):
		self.calls.append((url, kwargs))
		outcome = self.outcomes.pop(0)
		if isinstance(outcome, Exception):
			raise outcome
		return outcome


class TestSyncClientBackoff(unittest.TestCase):
	def setUp(self):
		self.client = _load_client_module()
		self.sleeps = []

	def fetch(self, outcomes, **kwargs):
		session = _FakeSession(outcomes)
		result = self.client.fetch_snapshot(
			base_url="http://horizon.local:8000",
			api_key="k",
			api_secret="s",
			warehouse="Delhi DC",
			filter_by_criticality=True,
			session=session,
			sleep=self.sleeps.append,
			**kwargs,
		)
		return result, session

	def test_retries_on_429_then_5xx_then_connection_error_with_fixed_backoff(self):
		import requests

		ok = _FakeResponse(200, {"message": {"items": [], "low_stock_alerts": [], "summary": {}}})
		outcomes = [
			_FakeResponse(429, {"error": "rate_limited", "retry_after_seconds": 7}, {"Retry-After": "7"}),
			_FakeResponse(503, {"error": "temporary_failure", "retry_after_seconds": 30}),
			requests.ConnectionError("boom"),
			ok,
		]
		result, session = self.fetch(outcomes)
		self.assertEqual(self.sleeps, [1, 5, 25])
		self.assertEqual(len(session.calls), 4)
		self.assertEqual(result["items"], [])
		self.assertEqual(self.client.BACKOFF_SCHEDULE, (1, 5, 25))

	def test_gives_up_after_three_retries(self):
		outcomes = [_FakeResponse(503, {"error": "temporary_failure"})] * 4
		with self.assertRaises(self.client.SnapshotError) as ctx:
			self.fetch(outcomes)
		self.assertEqual(self.sleeps, [1, 5, 25])
		self.assertEqual(ctx.exception.status_code, 503)

	def test_does_not_retry_other_4xx(self):
		outcomes = [_FakeResponse(404, {"error": "invalid_warehouse", "message": "Warehouse 'X' not found"})]
		with self.assertRaises(self.client.SnapshotError) as ctx:
			self.fetch(outcomes)
		self.assertEqual(self.sleeps, [])
		self.assertEqual(ctx.exception.status_code, 404)
		self.assertIn("invalid_warehouse", str(ctx.exception))

	def test_request_payload_and_auth_header(self):
		ok = _FakeResponse(200, {"message": {"items": [], "low_stock_alerts": [], "summary": {}}})
		_, session = self.fetch([ok])
		url, kwargs = session.calls[0]
		self.assertEqual(
			url, "http://horizon.local:8000/api/method/horizon_erp.api.inventory.get_inventory_snapshot"
		)
		self.assertEqual(kwargs["json"], {"warehouse": "Delhi DC", "filter_by_criticality": True})
		self.assertEqual(kwargs["headers"]["Authorization"], "token k:s")


class TestInventoryApiAliases(FrappeTestCase):
	"""The module restructure moved the endpoint; every published path must still resolve to the same
	whitelisted function (frappe.handler -> frappe.get_attr -> frappe.is_whitelisted)."""

	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase's rollback
		super().setUpClass()

	CANONICAL = "horizon_erp.horizon_integrations.inventory_api.get_inventory_snapshot"
	LEGACY = (
		"horizon_erp.api.inventory.get_inventory_snapshot",
		"horizon_erp.api.get_inventory_snapshot",
	)

	def test_legacy_dotted_paths_resolve_to_whitelisted_endpoint(self):
		canonical = frappe.get_attr(self.CANONICAL)
		frappe.is_whitelisted(canonical)  # raises PermissionError when not whitelisted
		for path in self.LEGACY:
			self.assertIs(frappe.get_attr(path), canonical, path)

	def test_short_alias_points_at_canonical_path(self):
		overrides = frappe.get_hooks("override_whitelisted_methods")
		self.assertEqual(overrides.get("get_inventory_snapshot"), [self.CANONICAL])

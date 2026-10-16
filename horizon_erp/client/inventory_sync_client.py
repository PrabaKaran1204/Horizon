#!/usr/bin/env python3
"""Horizon inventory sync client (standalone - only needs ``requests``).

Fetches ``get_inventory_snapshot`` from a Horizon ERP site with token auth and retries on
429 / 5xx / connection errors using a fixed exponential backoff of 1 s, 5 s, 25 s (3 retries,
4 attempts in total). Other 4xx responses are not retried. Every attempt is logged with a
timestamp to stdout and to ``inventory_sync.log``.

Usage::

	python inventory_sync_client.py --url http://horizon.local:8000 --key KEY --secret SECRET \\
	    --warehouse "Delhi DC" --criticality

Library use::

	from inventory_sync_client import fetch_snapshot
	snapshot = fetch_snapshot("http://horizon.local:8000", "KEY", "SECRET", "Delhi DC", True)
"""

import argparse
import datetime
import json
import logging
import sys
import time

import requests

ENDPOINT = "/api/method/horizon_erp.api.inventory.get_inventory_snapshot"
BACKOFF_SCHEDULE = (1, 5, 25)  # seconds before retry 1, 2, 3
RETRY_STATUSES = frozenset({429})
TIMEOUT_SECONDS = 30
LOG_FILE = "inventory_sync.log"

log = logging.getLogger("inventory_sync")


class SnapshotError(Exception):
	"""Raised when the snapshot could not be fetched (after retries, or on a non-retryable 4xx)."""

	def __init__(self, message, status_code=None, body=None):
		super().__init__(message)
		self.status_code = status_code
		self.body = body


def configure_logging(log_file=LOG_FILE, level=logging.INFO):
	if log.handlers:
		return
	fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
	for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")):
		handler.setFormatter(fmt)
		log.addHandler(handler)
	log.setLevel(level)


def _should_retry(status_code):
	return status_code in RETRY_STATUSES or status_code >= 500


def _parse_body(response):
	try:
		return response.json()
	except ValueError:
		return {"raw": getattr(response, "text", "")}


def _error_summary(body):
	if not isinstance(body, dict):
		return str(body)[:200]
	return body.get("error") or body.get("exc_type") or body.get("message") or str(body)[:200]


def fetch_snapshot(
	base_url,
	api_key,
	api_secret,
	warehouse,
	filter_by_criticality=False,
	session=None,
	sleep=time.sleep,
	backoff=BACKOFF_SCHEDULE,
	timeout=TIMEOUT_SECONDS,
):
	"""Return the snapshot dict (the ``message`` payload) or raise :class:`SnapshotError`.

	:param session: object with ``post(url, json=..., headers=..., timeout=...)`` (``requests.Session``
	        by default; injectable for tests)
	:param sleep: callable used between retries (injectable for tests)
	"""
	session = session or requests.Session()
	url = base_url.rstrip("/") + ENDPOINT
	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
		"Accept": "application/json",
	}
	payload = {"warehouse": warehouse, "filter_by_criticality": bool(filter_by_criticality)}
	max_attempts = len(backoff) + 1

	last_error = None
	for attempt in range(1, max_attempts + 1):
		started = time.monotonic()
		log.info("attempt %d/%d POST %s warehouse=%r", attempt, max_attempts, url, warehouse)
		try:
			response = session.post(url, json=payload, headers=headers, timeout=timeout)
		except (requests.ConnectionError, requests.Timeout) as exc:
			last_error = SnapshotError(f"connection error: {exc}")
			log.warning("attempt %d failed: %s", attempt, exc)
		else:
			elapsed_ms = (time.monotonic() - started) * 1000
			body = _parse_body(response)
			if response.status_code == 200 and isinstance(body, dict) and "message" in body:
				log.info("attempt %d succeeded in %.0f ms", attempt, elapsed_ms)
				return body["message"]

			summary = _error_summary(body)
			last_error = SnapshotError(
				f"HTTP {response.status_code}: {summary}", status_code=response.status_code, body=body
			)
			if not _should_retry(response.status_code):
				log.error(
					"attempt %d: HTTP %d (%s) - not retryable, giving up",
					attempt,
					response.status_code,
					summary,
				)
				raise last_error

			retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
			if retry_after is None and isinstance(body, dict):
				retry_after = body.get("retry_after_seconds")
			log.warning(
				"attempt %d: HTTP %d (%s) after %.0f ms; server Retry-After=%s",
				attempt,
				response.status_code,
				summary,
				elapsed_ms,
				retry_after,
			)

		if attempt < max_attempts:
			delay = backoff[attempt - 1]
			log.info("backing off %ss before retry %d", delay, attempt)
			sleep(delay)

	log.error("giving up after %d attempts: %s", max_attempts, last_error)
	raise last_error


def format_alerts(snapshot):
	alerts = snapshot.get("low_stock_alerts") or []
	if not alerts:
		return "No low-stock alerts."
	rows = [("Item", "Crit", "Available", "Reorder Pt", "Shortfall")]
	for a in alerts:
		rows.append(
			(
				str(a.get("item_code")),
				str(a.get("criticality") or "-"),
				f"{a.get('available_qty', 0):g}",
				f"{a.get('reorder_point', 0):g}",
				f"{a.get('shortfall', 0):g}",
			)
		)
	widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
	lines = []
	for n, r in enumerate(rows):
		lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
		if n == 0:
			lines.append("  ".join("-" * w for w in widths))
	return "\n".join(lines)


def main(argv=None):
	parser = argparse.ArgumentParser(description="Fetch a Horizon ERP inventory snapshot with retries.")
	parser.add_argument("--url", required=True, help="site base URL, e.g. http://horizon.local:8000")
	parser.add_argument("--key", required=True, help="API key (User.api_key)")
	parser.add_argument("--secret", required=True, help="API secret (User.api_secret)")
	parser.add_argument("--warehouse", required=True, help="warehouse name, e.g. 'Delhi DC'")
	parser.add_argument("--criticality", action="store_true", help="only criticality A/B items")
	parser.add_argument("--json", action="store_true", help="print the full snapshot JSON")
	parser.add_argument("--log-file", default=LOG_FILE)
	args = parser.parse_args(argv)

	configure_logging(args.log_file)
	try:
		snapshot = fetch_snapshot(args.url, args.key, args.secret, args.warehouse, args.criticality)
	except SnapshotError as exc:
		print(f"ERROR: {exc}", file=sys.stderr)
		return 1

	summary = snapshot.get("summary", {})
	print(
		f"\nSnapshot {snapshot.get('timestamp')} for {snapshot.get('warehouse')} "
		f"({len(snapshot.get('warehouses_included') or [])} warehouse(s)), "
		f"{summary.get('item_count', 0)} items, {summary.get('low_stock_count', 0)} low-stock, "
		f"stock value {summary.get('total_stock_value', 0)}, generated in {snapshot.get('generated_in_ms')} ms\n"
	)
	print(format_alerts(snapshot))
	if args.json:
		print(json.dumps(snapshot, indent=2))
	log.info("done at %s", datetime.datetime.now().isoformat(timespec="seconds"))
	return 0


if __name__ == "__main__":
	sys.exit(main())

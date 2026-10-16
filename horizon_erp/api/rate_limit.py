# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Per-client rate limiting for Horizon REST endpoints.

Why not ``frappe.rate_limiter.rate_limit``?
	Frappe's built-in decorator keys on ``request_ip`` and/or an arbitrary ``form_dict`` field, raises
	``RateLimitExceededError`` (HTTP 417, not 429), gives the caller no ``Retry-After`` /
	``X-RateLimit-*`` information and offers no hook to record the rejected call. The site-wide
	``frappe.conf.rate_limit`` limiter is global (one bucket for the whole site, measured in CPU
	micro-seconds) rather than per API client. We therefore keep a small decorator of our own that:

	- identifies the client by the authenticated user (the owner of the ``Authorization: token
	  key:secret`` pair), falling back to the request IP;
	- counts calls in Redis with ``INCR`` + ``EXPIRE`` under
	  ``horizon:ratelimit:{client}:{bucket}`` (fixed window; ``bucket = epoch // window``);
	- answers HTTP 429 with a clean JSON body and ``Retry-After`` / ``X-RateLimit-*`` headers;
	- lets the endpoint log the rejected call through an ``on_exceed`` callback.

Headers
	Whitelisted methods cannot set response headers directly in Frappe v15 (``as_json`` only honours
	``frappe.local.response["http_status_code"]``). ``frappe.app.process_response`` does, however,
	append ``frappe.local.rate_limiter.headers()`` to every response, so we expose a duck-typed
	limiter object through that attribute (wrapping the site-wide limiter when one is active).
	The same values are also returned in the JSON body so clients that cannot read headers still
	get them.
"""

import functools
import time
from collections.abc import Callable

import frappe
from frappe import _

DEFAULT_LIMIT = 100
DEFAULT_WINDOW_SECONDS = 3600
CONF_LIMIT_KEY = "horizon_api_rate_limit"
KEY_PREFIX = "horizon:ratelimit"


class RateLimitState:
	"""Result of one rate-limit check; also acts as ``frappe.local.rate_limiter`` for headers."""

	__slots__ = ("client", "count", "inner", "key", "limit", "rejected", "remaining", "reset", "window")

	def __init__(self, client, key, limit, count, window, reset, inner=None):
		self.client = client
		self.key = key
		self.limit = int(limit)
		self.count = int(count)
		self.window = int(window)
		self.reset = int(reset)
		self.remaining = max(self.limit - self.count, 0)
		self.rejected = self.count > self.limit
		# site-wide frappe.rate_limiter.RateLimiter, if frappe.conf.rate_limit is configured
		self.inner = inner

	# -- duck-typing frappe.rate_limiter.RateLimiter (used by frappe.app.process_response) --
	def headers(self):
		headers = dict(self.inner.headers()) if self.inner else {}
		headers.update(
			{
				"X-RateLimit-Limit": self.limit,
				"X-RateLimit-Remaining": self.remaining,
				"X-RateLimit-Reset": self.reset,
			}
		)
		if self.rejected:
			headers["Retry-After"] = self.reset
		return headers

	def update(self):
		if self.inner:
			self.inner.update()

	def respond(self):
		if self.inner:
			return self.inner.respond()

	def apply(self):
		if self.inner:
			self.inner.apply()

	def as_dict(self):
		return {
			"limit": self.limit,
			"remaining": self.remaining,
			"reset_seconds": self.reset,
			"window_seconds": self.window,
		}


def get_client_identity() -> str:
	"""API client = authenticated user (token owner); IP for anonymous callers."""
	user = getattr(frappe.session, "user", None) if getattr(frappe.local, "session", None) else None
	if user and user != "Guest":
		return user
	return getattr(frappe.local, "request_ip", None) or "unknown"


def get_configured_limit(default: int = DEFAULT_LIMIT) -> int:
	"""Limit from ``site_config.json`` (``horizon_api_rate_limit``), else ``default``."""
	try:
		value = int(frappe.conf.get(CONF_LIMIT_KEY) or 0)
	except (TypeError, ValueError):
		value = 0
	return value if value > 0 else int(default)


def check_rate_limit(client: str, limit: int, window_seconds: int = DEFAULT_WINDOW_SECONDS) -> RateLimitState:
	"""Count one call for ``client`` and return the resulting state (never raises for limit)."""
	now = time.time()
	bucket = int(now // window_seconds)
	key = frappe.cache.make_key(f"{KEY_PREFIX}:{client}:{bucket}")

	count = frappe.cache.incr(key)
	# first call of this window (or TTL lost in a crash): arm the expiry, one window + a little slack
	if count == 1 or frappe.cache.ttl(key) < 0:
		frappe.cache.expire(key, window_seconds + 60)

	reset = max(int(window_seconds - (now % window_seconds)), 1)
	inner = getattr(frappe.local, "rate_limiter", None)
	if isinstance(inner, RateLimitState):
		inner = inner.inner
	state = RateLimitState(client, key, limit, count, window_seconds, reset, inner=inner)
	frappe.local.rate_limiter = state
	return state


def reset_rate_limit(client: str) -> None:
	"""Forget every bucket for ``client`` (tests / ops)."""
	frappe.cache.delete_keys(f"{KEY_PREFIX}:{client}:")


def rate_limited(
	limit: int | Callable[[], int] | None = None,
	window_seconds: int = DEFAULT_WINDOW_SECONDS,
	key_fn: Callable[[], str] | None = None,
	on_exceed: Callable[..., None] | None = None,
):
	"""Decorator: allow ``limit`` calls per ``window_seconds`` per client.

	:param limit: int, zero-arg callable, or ``None`` for ``frappe.conf.horizon_api_rate_limit`` / 100
	:param key_fn: returns the client identity (default: :func:`get_client_identity`)
	:param on_exceed: ``on_exceed(state, *args, **kwargs)`` called before the 429 body is returned
	        (e.g. to write a log row). Exceptions raised inside it are swallowed.

	On exceed the wrapped function is **not** called; ``frappe.local.response["http_status_code"]``
	is set to 429 and the JSON body below is returned::

	        {
	            "error": "rate_limited",
	            "message": "...",
	            "retry_after_seconds": n,
	            "limit": 100,
	            "remaining": 0,
	            "reset_seconds": n,
	            "window_seconds": 3600,
	            "timestamp": "...",
	        }
	"""

	def decorator(fn):
		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			if callable(limit):
				_limit = int(limit())
			elif limit is None:
				_limit = get_configured_limit()
			else:
				_limit = int(limit)

			client = key_fn() if key_fn else get_client_identity()
			state = check_rate_limit(client, _limit, window_seconds)

			if state.rejected:
				if on_exceed:
					try:
						on_exceed(state, *args, **kwargs)
					except Exception:
						frappe.log_error(title="horizon rate_limited on_exceed failed")
				return rate_limited_response(state)

			return fn(*args, **kwargs)

		return wrapper

	return decorator


def rate_limited_response(state: RateLimitState) -> dict:
	from horizon_erp.horizon_integration.doctype.inventory_api_log.inventory_api_log import iso_now

	frappe.local.response["http_status_code"] = 429
	body = {
		"error": "rate_limited",
		"message": _("Rate limit of {0} requests per {1} seconds exceeded for client {2}").format(
			state.limit, state.window, state.client
		),
		"retry_after_seconds": state.reset,
		"timestamp": iso_now(),
	}
	body.update(state.as_dict())
	return body

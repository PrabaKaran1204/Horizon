# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Shared helpers for Horizon ERP."""

import frappe


def jinja_methods():
	"""Methods exposed to Jinja (print formats, email templates).

	Return a dict of ``{"name": callable}``. Referenced from ``hooks.py`` ``jinja["methods"]``.
	"""
	# TODO(print): expose helpers for Horizon print formats
	return {}


def get_setting(key, default=None):
	"""Read a Horizon-wide configuration value.

	Intended behaviour: look up ``key`` on a future "Horizon Settings" Single DocType and fall
	back to ``default``. Until that DocType exists this always returns ``default``.
	"""
	# TODO(settings): back with a "Horizon Settings" Single DocType
	return default

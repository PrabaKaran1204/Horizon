# Copyright (c) 2026, Horizon Manufacturing Ltd and contributors
# For license information, please see license.txt

"""Remove rows that unit tests persist outside the test transaction.

Every horizon_erp test module creates its fixtures under one of the prefixes in
``DEFAULT_PREFIXES``; ``FrappeTestCase`` rolls the fixtures back at class end. A few side effects
escape that rollback because the framework commits them itself: ``Error Log`` rows written by
``execute_job`` / ``frappe.log_error`` on failing scheduler jobs, ``Contact`` rows created by
``User.after_insert``, ``Deleted Document`` rows written by ``frappe.delete_doc`` and
``Comment`` / ``Email Queue`` rows produced by notifications. ``purge_test_residue`` deletes
exactly those rows and nothing else.

Registration pattern (used by every test module):

	@classmethod
	def setUpClass(cls):
		cls.addClassCleanup(purge_test_residue)  # LIFO: runs after FrappeTestCase._rollback_db
		super().setUpClass()

The cleanup must be registered *before* ``super().setUpClass()`` so that unittest runs it after
the rollback FrappeTestCase registers; otherwise the commit below would persist the class's
uncommitted fixtures.

``after_tests`` is wired in ``hooks.py`` for runners that fire it; the Frappe v15 test runner only
knows ``before_tests``, which is why the per-class registration above exists.
"""

import frappe

DEFAULT_PREFIXES = ("BRTEST", "APITEST", "SCHTEST", "RPTTEST", "GAPTEST", "FIXTEST", "LEADTEST")

# doctype -> columns that carry the fixture prefix when a row is test residue
RESIDUE_FIELDS = {
	"Error Log": ("method", "error"),
	"Comment": ("reference_name", "content", "comment_email"),
	"Deleted Document": ("deleted_name", "data"),
	"Email Queue": ("message",),
	"Contact": ("name", "email_id", "user"),
}

# doctypes whose child tables must go too -> delete through the document API
_DELETE_VIA_DOC = {"Contact", "Email Queue"}


def find_test_residue(prefixes=DEFAULT_PREFIXES, doctypes=None):
	"""Return ``{doctype: [names]}`` of rows mentioning any prefix in a residue column."""
	residue = {}
	for doctype, columns in RESIDUE_FIELDS.items():
		if doctypes and doctype not in doctypes:
			continue
		if not frappe.db.table_exists(doctype):
			continue
		names = set()
		for column in columns:
			if not frappe.get_meta(doctype).has_field(column) and column != "name":
				continue
			for prefix in prefixes:
				names.update(
					frappe.get_all(doctype, filters={column: ["like", f"%{prefix}%"]}, pluck="name", limit=0)
				)
		if names:
			residue[doctype] = sorted(names)
	return residue


def purge_test_residue(prefixes=DEFAULT_PREFIXES, commit=True):
	"""Delete every residue row for ``prefixes`` and return ``{doctype: deleted_count}``.

	Commits by default because the callers run after the test transaction has been rolled back
	and nothing else would persist the deletes.
	"""
	frappe.set_user("Administrator")
	deleted = {}
	for doctype, names in find_test_residue(prefixes).items():
		if doctype in _DELETE_VIA_DOC:
			for name in names:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
		else:
			frappe.db.delete(doctype, {"name": ["in", names]})
		deleted[doctype] = len(names)
	if commit and deleted:
		frappe.db.commit()  # nosemgrep: test-only helper, runs outside the test transaction
	return deleted


def after_tests():
	"""``after_tests`` hook entry point: purge and report."""
	deleted = purge_test_residue()
	if deleted:
		print("horizon_erp: purged test residue", deleted)

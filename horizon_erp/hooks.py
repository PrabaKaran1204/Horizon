app_name = "horizon_erp"
app_title = "Horizon ERP"
app_publisher = "Horizon Manufacturing Ltd"
app_description = "Horizon Manufacturing ERPNext implementation customisations"
app_email = "prabakaran.b@finstein.ai"
app_license = "mit"

# Apps
# ------------------
required_apps = ["erpnext"]

# Folder layout (mirrors the kaynes app): one Frappe module per ERPNext domain, listed in
# modules.txt - horizon_setup, horizon_core, horizon_buying, horizon_selling, horizon_crm,
# horizon_stock, horizon_manufacturing, horizon_quality_management, horizon_projects, horizon_hr,
# horizon_payroll, horizon_accounts, horizon_assets, horizon_integrations, horizon_workflow.
# Each module keeps its own custom/ (Custom Fields as JSON), doctype/, report/, workspace/,
# number_card/, dashboard_chart/, print_format/, tests/ and domain hook modules.

# Installation / Migration
# ------------------------
# install.py syncs <module>/custom/*.json first (Frappe only syncs them *after* after_install on a
# fresh site), then roles, role permissions, workflows, print formats and notifications.
after_install = "horizon_erp.horizon_setup.install.after_install"
after_migrate = "horizon_erp.horizon_setup.install.after_migrate"

# Testing
# -------
# Frappe v15's test runner fires only before_tests; every horizon_erp test class therefore also
# registers horizon_erp.tests.cleanup.purge_test_residue as a class cleanup (see that module).
after_tests = ["horizon_erp.tests.cleanup.after_tests"]

# Desk assets
# -----------
# Form scripts (public/js, built by ``bench build --app horizon_erp``)
doctype_js = {
	"Quotation": "public/js/quotation.js",
	"Sales Order": "public/js/sales_order.js",
	"Purchase Order": "public/js/purchase_order.js",
	"Delivery Note": "public/js/delivery_note.js",
	"Work Order": "public/js/work_order.js",
}

# Jinja
# -----
# ``horizon_erp.utils`` is a package; ``utils/jinja_methods.py`` re-exports every helper so that
# frappe.utils.jinja.get_jinja_hooks registers each function as a Jinja global.
jinja = {"methods": ["horizon_erp.utils.jinja_methods"]}

# DocType Class
# -------------
# No standard controller is overridden today. Override classes go in horizon_erp/overrides/
# (same convention as kaynes/overrides), e.g.
# override_doctype_class = {"Purchase Receipt": "horizon_erp.overrides.purchase_receipt.CustomPR"}

# Overriding Methods
# ------------------
# Short alias so the integration contract ``POST /api/method/get_inventory_snapshot`` resolves to
# the whitelisted endpoint. The pre-restructure dotted paths
# ``horizon_erp.api.inventory.get_inventory_snapshot`` and ``horizon_erp.api.get_inventory_snapshot``
# stay valid through the re-export shims in horizon_erp/api/.
override_whitelisted_methods = {
	"get_inventory_snapshot": "horizon_erp.horizon_integrations.inventory_api.get_inventory_snapshot",
}

# Document Events
# ---------------
doc_events = {
	# Buying
	"Purchase Order": {"validate": "horizon_erp.horizon_buying.buying.validate_purchase_order"},
	# Stock
	"Purchase Receipt": {
		"validate": "horizon_erp.horizon_stock.purchase_receipt.validate_purchase_receipt",
		"on_submit": "horizon_erp.horizon_stock.purchase_receipt.on_submit_purchase_receipt",
	},
	# Quality Management
	"Quality Inspection": {
		"on_submit": "horizon_erp.horizon_quality_management.inspection.on_submit_quality_inspection"
	},
	"Stock Entry": {
		"validate": "horizon_erp.horizon_quality_management.production_audit_hooks.validate_stock_entry"
	},
	# Selling
	"Quotation": {"validate": "horizon_erp.horizon_selling.selling.validate_discounts"},
	"Sales Order": {"validate": "horizon_erp.horizon_selling.selling.validate_discounts"},
	# before_validate runs ahead of the ERPNext controller's validate (pricing engine, totals,
	# "maintain same rate" check): rates of rows mapped from a Sales Order are locked there
	"Delivery Note": {
		"before_validate": "horizon_erp.horizon_selling.selling.lock_rates_to_sales_order",
		"validate": "horizon_erp.horizon_selling.selling.validate_delivery_note",
		"on_submit": "horizon_erp.horizon_selling.selling.on_submit_delivery_note",
	},
	"Sales Invoice": {
		"before_validate": "horizon_erp.horizon_selling.selling.lock_rates_to_sales_order",
		"validate": "horizon_erp.horizon_selling.selling.validate_sales_invoice",
	},
	# Manufacturing
	"Work Order": {"validate": "horizon_erp.horizon_manufacturing.manufacturing.validate_work_order"},
	# Projects
	"Timesheet": {"validate": "horizon_erp.horizon_projects.projects.validate_timesheet"},
	"Task": {"on_update": "horizon_erp.horizon_projects.projects.on_update_task"},
}

# Scheduled Tasks
# ---------------
# Jobs live in the domain module they belong to (<module>/tasks.py), as in kaynes; the shared
# @horizon_job wrapper (Error Log, System Manager alert, retry marker) is horizon_core/jobs.py.
scheduler_events = {
	"hourly": [
		"horizon_erp.horizon_stock.tasks.reorder_and_accuracy_check",
		"horizon_erp.horizon_buying.tasks.po_approval_reminders",
	],
	"daily": [
		"horizon_erp.horizon_stock.tasks.recompute_reorder_levels",
		"horizon_erp.horizon_quality_management.tasks.detect_quality_deadline_conflicts",
		"horizon_erp.horizon_accounts.tasks.budget_threshold_alerts",
	],
	"cron": {
		"0 18 * * *": ["horizon_erp.horizon_core.tasks.send_daily_summary"],
		"0 9 1 * *": ["horizon_erp.horizon_accounts.tasks.send_budget_report"],
	},
}

# Fixtures
# --------
# Custom Fields and Property Setters are NOT fixtures: they are Frappe "Export Customizations"
# files in <module>/custom/<doctype>.json (sync_on_migrate = 1), synced by bench migrate and by
# horizon_setup.install on install. Workflow State and Workflow Action Master are shared DocTypes,
# so they are filtered by explicit name lists; add every new Horizon state / action to these lists.
horizon_roles = [
	"Department Head",
	"Procurement Manager",
	"Finance Director",
	"Operations Head",
	"Sales Manager",
	"Warehouse Manager",
	"Quality Inspector",
	"HR Manager",
]

horizon_workflows = [
	"Horizon PO Approval",
	"Horizon Discount Approval",
	"Horizon Discount Approval - Sales Order",
	"Horizon Production Audit",
	"Horizon Payment Approval",
]

horizon_workflow_states = [
	"Draft",
	"Pending Dept Head",
	"Pending Procurement Manager",
	"Pending Finance Director",
	"Pending Discount Approval",
	"Approved",
	"Rejected",
	"Submitted",
	"Reviewed",
	"Action Closed",
]

horizon_workflow_actions = [
	"Submit for Approval",
	"Approve",
	"Reject",
	"Revise",
	"Submit",
	"Submit for Discount Approval",
	"Review",
	"Close Action",
]

# Custom DocPerm rows written by horizon_setup/roles.py::setup_role_permissions (keep both lists in
# sync with ROLE_PERMISSIONS there). setup_role_permissions also mirrors the standard rules into
# Custom DocPerm on the target site, so importing only these rows can never strip a standard role.
horizon_permission_roles = [
	"Manufacturing User",
	"Purchase User",
	"Quality Inspector",
	"Sales User",
	"Stock Manager",
	"Stock User",
	"Warehouse Manager",
]
horizon_permission_doctypes = [
	"Address",
	"Batch",
	"Contact",
	"Customer",
	"Delivery Note",
	"Quality Inspection",
	"Sales Invoice",
	"Serial No",
	"Serial and Batch Bundle",
	"Supplier",
]

fixtures = [
	# Roles and permissions
	{"dt": "Role", "filters": [["role_name", "in", horizon_roles]]},
	{
		"dt": "Custom DocPerm",
		"filters": [
			["role", "in", horizon_permission_roles],
			["parent", "in", horizon_permission_doctypes],
		],
	},
	# Workflows and workflow components
	{"dt": "Workflow", "filters": [["name", "in", horizon_workflows]]},
	{"dt": "Workflow State", "filters": [["name", "in", horizon_workflow_states]]},
	{"dt": "Workflow Action Master", "filters": [["name", "in", horizon_workflow_actions]]},
	# Print formats and notifications (source of truth: horizon_setup/print_formats.py, notifications.py)
	{"dt": "Print Format", "filters": [["name", "like", "Horizon%"]]},
	{"dt": "Notification", "filters": [["name", "like", "Horizon%"]]},
	# UI (also shipped as module JSON under <module>/workspace|number_card/). Dashboard Charts are
	# NOT fixtures: fixture import validates the record, and DashboardChart.validate refuses a
	# standard chart whenever developer_mode is off - which is always the case on production and
	# inside any migrate that runs a patch (patch_handler.run_single sets developer_mode = 0). They
	# ship only as <module>/dashboard_chart/ JSON, synced by bench migrate (sync_dashboards).
	{"dt": "Workspace", "filters": [["name", "like", "Horizon%"]]},
	{"dt": "Number Card", "filters": [["name", "like", "Horizon%"]]},
]

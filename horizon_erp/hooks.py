app_name = "horizon_erp"
app_title = "Horizon ERP"
app_publisher = "Horizon Manufacturing Ltd"
app_description = "Horizon Manufacturing ERPNext implementation customisations"
app_email = "prabakaran.b@finstein.ai"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "horizon_erp",
# 		"logo": "/assets/horizon_erp/logo.png",
# 		"title": "Horizon ERP",
# 		"route": "/horizon_erp",
# 		"has_permission": "horizon_erp.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/horizon_erp/css/horizon_erp.css"
# app_include_js = "/assets/horizon_erp/js/horizon_erp.js"

# include js, css files in header of web template
# web_include_css = "/assets/horizon_erp/css/horizon_erp.css"
# web_include_js = "/assets/horizon_erp/js/horizon_erp.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "horizon_erp/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "horizon_erp/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "horizon_erp.utils.jinja_methods",
# 	"filters": "horizon_erp.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "horizon_erp.install.before_install"
# after_install = "horizon_erp.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "horizon_erp.uninstall.before_uninstall"
# after_uninstall = "horizon_erp.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "horizon_erp.utils.before_app_install"
# after_app_install = "horizon_erp.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "horizon_erp.utils.before_app_uninstall"
# after_app_uninstall = "horizon_erp.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "horizon_erp.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"horizon_erp.tasks.all"
# 	],
# 	"daily": [
# 		"horizon_erp.tasks.daily"
# 	],
# 	"hourly": [
# 		"horizon_erp.tasks.hourly"
# 	],
# 	"weekly": [
# 		"horizon_erp.tasks.weekly"
# 	],
# 	"monthly": [
# 		"horizon_erp.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "horizon_erp.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "horizon_erp.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "horizon_erp.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["horizon_erp.utils.before_request"]
# after_request = ["horizon_erp.utils.after_request"]

# Job Events
# ----------
# before_job = ["horizon_erp.utils.before_job"]
# after_job = ["horizon_erp.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"horizon_erp.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


# ---------------------------------------------------------------------------
# Horizon ERP active hooks
# ---------------------------------------------------------------------------
# Every dotted path below is a stub that another developer fills in. Keep this
# block authoritative: add the hook here first, then implement the function.

# Installation / migration
after_install = "horizon_erp.setup.install.after_install"
after_migrate = "horizon_erp.setup.install.after_migrate"

# Document Events
doc_events = {
	"Purchase Order": {"validate": "horizon_erp.horizon_operations.buying.validate_purchase_order"},
	"Purchase Receipt": {
		"validate": "horizon_erp.horizon_operations.buying.validate_purchase_receipt",
		"on_submit": "horizon_erp.horizon_operations.buying.on_submit_purchase_receipt",
	},
	"Quality Inspection": {
		"on_submit": "horizon_erp.horizon_quality.inspection.on_submit_quality_inspection"
	},
	"Quotation": {"validate": "horizon_erp.horizon_operations.selling.validate_discounts"},
	"Sales Order": {"validate": "horizon_erp.horizon_operations.selling.validate_discounts"},
	# before_validate runs ahead of the ERPNext controller's validate (pricing engine, totals,
	# "maintain same rate" check): rates of rows mapped from a Sales Order are locked there
	"Delivery Note": {
		"before_validate": "horizon_erp.horizon_operations.selling.lock_rates_to_sales_order",
		"validate": "horizon_erp.horizon_operations.selling.validate_delivery_note",
		"on_submit": "horizon_erp.horizon_operations.selling.on_submit_delivery_note",
	},
	"Sales Invoice": {
		"before_validate": "horizon_erp.horizon_operations.selling.lock_rates_to_sales_order",
		"validate": "horizon_erp.horizon_operations.selling.validate_sales_invoice",
	},
	"Work Order": {"validate": "horizon_erp.horizon_operations.manufacturing.validate_work_order"},
	"Stock Entry": {"validate": "horizon_erp.horizon_quality.production_audit_hooks.validate_stock_entry"},
	"Timesheet": {"validate": "horizon_erp.horizon_operations.projects.validate_timesheet"},
	"Task": {"on_update": "horizon_erp.horizon_operations.projects.on_update_task"},
}

# Scheduled Tasks
scheduler_events = {
	"hourly": [
		"horizon_erp.tasks.hourly.reorder_and_accuracy_check",
		"horizon_erp.tasks.hourly.po_approval_reminders",
	],
	"daily": [
		"horizon_erp.tasks.daily.recompute_reorder_levels",
		"horizon_erp.tasks.daily.detect_quality_deadline_conflicts",
		"horizon_erp.tasks.daily.budget_threshold_alerts",
	],
	"cron": {
		"0 18 * * *": ["horizon_erp.tasks.daily.send_daily_summary"],
		"0 9 1 * *": ["horizon_erp.tasks.monthly.send_budget_report"],
	},
}

# Form scripts (public/js, built by ``bench build --app horizon_erp``)
doctype_js = {
	"Quotation": "public/js/quotation.js",
	"Sales Order": "public/js/sales_order.js",
	"Purchase Order": "public/js/purchase_order.js",
	"Delivery Note": "public/js/delivery_note.js",
	"Work Order": "public/js/work_order.js",
}

# Jinja
# ``horizon_erp.utils`` is a package; ``utils/jinja_methods.py`` re-exports every helper so that
# frappe.utils.jinja.get_jinja_hooks registers each function as a Jinja global.
jinja = {"methods": ["horizon_erp.utils.jinja_methods"]}

# Overriding Methods
# Short alias so the integration contract ``POST /api/method/get_inventory_snapshot`` resolves to
# the whitelisted endpoint (also reachable by its full dotted path).
override_whitelisted_methods = {
	"get_inventory_snapshot": "horizon_erp.api.inventory.get_inventory_snapshot",
}

# Fixtures
# Custom Fields are NOT fixtures: they are created in code by
# horizon_erp.setup.custom_fields.setup_custom_fields (after_install / after_migrate).
# Workflow State and Workflow Action Master are shared DocTypes, so they are filtered
# by explicit name lists; add every new Horizon state / action to these lists.
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

horizon_modules = ["Horizon Quality", "Horizon Integration", "Horizon Operations", "Horizon Finance"]
# Custom DocPerm rows written by setup/roles.py::setup_role_permissions (keep both lists in sync
# with ROLE_PERMISSIONS there). setup_role_permissions also mirrors the standard rules into Custom
# DocPerm on the target site, so importing only these rows can never strip a standard role.
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
	{"dt": "Role", "filters": [["role_name", "in", horizon_roles]]},
	{"dt": "Workflow", "filters": [["name", "in", horizon_workflows]]},
	{"dt": "Workflow State", "filters": [["name", "in", horizon_workflow_states]]},
	{"dt": "Workflow Action Master", "filters": [["name", "in", horizon_workflow_actions]]},
	{"dt": "Property Setter", "filters": [["module", "in", horizon_modules]]},
	{
		"dt": "Custom DocPerm",
		"filters": [
			["role", "in", horizon_permission_roles],
			["parent", "in", horizon_permission_doctypes],
		],
	},
	{"dt": "Print Format", "filters": [["name", "like", "Horizon%"]]},
	{"dt": "Notification", "filters": [["name", "like", "Horizon%"]]},
	{"dt": "Workspace", "filters": [["name", "like", "Horizon%"]]},
	{"dt": "Number Card", "filters": [["name", "like", "Horizon%"]]},
	{"dt": "Dashboard Chart", "filters": [["name", "like", "Horizon%"]]},
]

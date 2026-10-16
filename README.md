# Horizon ERP

ERPNext v15 customisations for **Horizon Manufacturing Ltd** (company abbreviation `HML`, GST
branches Mumbai HQ and Delhi DC). Frappe / ERPNext 15.9x, HRMS 15, India Compliance 15.

## What's in this app

Horizon ERP packages the Horizon Manufacturing implementation as code so it can be re-created on
any bench: 7 custom DocTypes (Production Audit, Shipment Decision, Supplier Exception Log,
Quarterly Purchase Plan, Inventory API Log, Budget Override Request, Bank Reconciliation Sign-off,
plus two child tables), 4 approval workflows (PO approval, discount approval for Quotation and
Sales Order, production audit review, payment approval - 5 Workflow records), 17 tested Script
Reports (+ the API Usage Report), 5 workspaces backed by 18 number cards and 7 dashboard charts,
2 Jinja print formats, 4 notifications, 7 scheduler jobs, 1 REST API
(`get_inventory_snapshot`, rate limited and logged) and 5 form client scripts loaded through
`doctype_js`. Business rules (PO approval limits, blacklisted suppliers, discount caps, Delivery
Note before Invoice, Work Order capacity, quality gates, timesheet / task rules) live in
`doc_events` hooks and are covered by the test suite. Design documents and the full API contract
are in `docs/` (`docs/api.md` for the endpoint).

## Setup

Run from the bench root (`frappe-bench/`). The site used throughout is `horizon.local`.

```bash
# 0. fetch the app (skip if already in apps/)
bench get-app horizon_erp <git-url>

# 1. install (after_install creates roles, custom fields, workflows, print formats, notifications)
bench --site horizon.local install-app horizon_erp

# 2. demo masters, settings, opening stock; also runs setup_workflows + setup_hr_finance
bench --site horizon.local execute horizon_erp.setup.demo_data.setup_all

# 3. HR / finance demo data (idempotent; already called by setup_all, safe to re-run alone)
bench --site horizon.local execute horizon_erp.setup.demo_hr_finance.setup_hr_finance

# 4. validate workspaces / number cards / charts after migrate synced them
bench --site horizon.local execute horizon_erp.setup.dashboards.setup_dashboards

# 5. assets (public/js form scripts) and caches
bench build --app horizon_erp
bench --site horizon.local clear-cache

# 6. scheduler (hourly / daily / cron jobs in hooks.py)
bench --site horizon.local enable-scheduler
```

After every pull: `bench --site horizon.local migrate` (DocTypes, fixtures, after_migrate sync),
`bench build --app horizon_erp` when `public/` changed, `bench restart` after Python changes.

On this development bench `bench start` serves another site on port 8000; `horizon.local` is
served by a separate `bench serve --port 8001` process (with reload). Use
`http://127.0.0.1:8001` for UI and API smoke checks.

### API alias

The integration contract is `POST /api/method/get_inventory_snapshot`. `hooks.py` maps that short
name through `override_whitelisted_methods` to
`horizon_erp.api.inventory.get_inventory_snapshot`, which is also reachable as
`horizon_erp.api.get_inventory_snapshot`. Authenticate with `Authorization: token KEY:SECRET`.

```bash
curl -s -X POST http://127.0.0.1:8001/api/method/get_inventory_snapshot \
  -H "Content-Type: application/json" -H "Authorization: token KEY:SECRET" \
  -d '{"warehouse": "Delhi DC"}'
```

## Tests

```bash
bench --site horizon.local run-tests --app horizon_erp --skip-test-records
```

`--skip-test-records` is required: Frappe would otherwise try to create ERPNext's generic
`test_records` for every dependency DocType (Company `_Test Company`, items, warehouses, ...),
which collide with the Horizon demo masters and the India Compliance validations on this site.
Every Horizon test module builds its own fixtures (prefixes `BRTEST-`, `APITEST-`, `SCHTEST-`,
`RPTTEST-`) inside the test transaction, so nothing else is needed.

Development checks (run from `apps/horizon_erp`):

```bash
../../env/bin/python -m compileall -q horizon_erp
../../env/bin/python -c "import horizon_erp.hooks"
ruff check horizon_erp && ruff format --check horizon_erp
for f in horizon_erp/public/js/*.js horizon_erp/*/report/*/*.js; do node --check "$f"; done
```

## App layout

```
horizon_erp/
  hooks.py                      doc_events, scheduler_events, doctype_js, jinja, fixtures,
                                override_whitelisted_methods, after_install / after_migrate
  modules.txt                   Horizon Quality | Horizon Integration | Horizon Operations | Horizon Finance
  utils/__init__.py             Jinja helper implementations + get_setting()
  utils/jinja_methods.py        re-exports the helpers; target of the `jinja` hook (every function
                                in the module becomes a Jinja global in print formats / emails)
  api/inventory.py              @frappe.whitelist get_inventory_snapshot (logs to Inventory API Log)
  api/rate_limit.py             @rate_limited decorator (per API key / user, Redis backed)
  client/inventory_sync_client.py  reference consumer of the API
  setup/install.py              after_install / after_migrate -> roles, custom fields, workflows,
                                print formats, notifications (idempotent)
  setup/roles.py                HORIZON_ROLES, setup_roles()
  setup/custom_fields.py        get_custom_fields(), setup_custom_fields()  (NOT fixtures)
  setup/workflows.py            setup_workflows() - workflow definitions as code
  setup/print_formats.py        setup_print_formats() - HTML in horizon_operations/print_format/
  setup/notifications.py        setup_notifications()
  setup/client_scripts.py       fallback installer as Client Script records (not needed with doctype_js)
  setup/dashboards.py           number card sources + setup_dashboards() consistency check
  setup/demo_data.py            setup_all(): company settings, masters, opening stock, users, CSV export
  setup/demo_hr_finance.py      setup_hr_finance(): HR, payroll, projects, assets, budgets, bank
  tasks/hourly.py daily.py monthly.py budget.py   scheduler entry points
  public/js/*.js                form scripts (Quotation, Sales Order, Purchase Order, Delivery Note, Work Order)
  templates/emails/             daily_summary.html, budget_report.html
  data/*.csv                    exported demo masters (items, customers, suppliers, BOM lines, ...)
  horizon_quality/              inspection.py, production_audit_hooks.py, doctype/, report/, workspace/
  horizon_operations/           buying.py, selling.py, manufacturing.py, projects.py, scrap.py, config.py,
                                doctype/, report/, workspace/, number_card/, dashboard_chart/, print_format/
  horizon_integration/          doctype/inventory_api_log, report/api_usage_report
  horizon_finance/              doctype/budget_override_request, bank_reconciliation_sign_off, report/, number_card/
  patches/ + patches.txt        data / schema patches
docs/                           design documents (business rules, API contract, data model, test plan)
```

## Module map

| Module | DocTypes | Hooks / code | Reports |
| --- | --- | --- | --- |
| Horizon Quality | Production Audit (+ Photo), Shipment Decision | `horizon_quality.inspection`, `horizon_quality.production_audit_hooks` | Audit Findings Dashboard, Quality vs Deadline Conflicts, Supplier Quality Scorecard |
| Horizon Operations | Supplier Exception Log, Quarterly Purchase Plan (+ Item) | `horizon_operations.buying / selling / manufacturing / projects / scrap`, `public/js/*.js` | Approval Audit, BOM Explosion with Lead Time, Capacity Utilisation and Sequence, Forecast vs Actual Demand, Inventory Obsolescence Analysis, Order Status, Price List Comparison, Project Profitability |
| Horizon Integration | Inventory API Log | `api.inventory`, `api.rate_limit`, `client.inventory_sync_client` | API Usage Report |
| Horizon Finance | Budget Override Request, Bank Reconciliation Sign-off | `tasks.daily.budget_threshold_alerts`, `tasks.budget`, `tasks.monthly.send_budget_report` | Asset Register with Maintenance, Cost Center-wise P&L, Data Validation, Leave Balance with Carry Forward Expiry, Net Party Position, Salary Cost Analysis |

Shared helpers: `utils/` (Jinja globals `horizon_customer_outstanding`, `horizon_similar_items_in_stock`,
`horizon_due_date`, `horizon_company_gst`, `horizon_dn_row_serials`, `horizon_pan_from_gstin`).

## Conventions

- Custom Fields on standard DocTypes are defined in `setup/custom_fields.py` and applied on
  install / migrate. Do not export them as fixtures.
- Workflows, Workflow States, Workflow Action Masters, Print Formats, Notifications, Workspaces,
  Number Cards and Dashboard Charts are fixtures. Prefix names with `Horizon` and add new
  Workflow States / Actions to the name lists in `hooks.py` before `bench export-fixtures`.
  Workflows / print formats / notifications are *also* created in code (`setup/*.py`) so a fresh
  site is complete right after `install-app`.
- Selling Settings `so_required` / `dn_required` are kept at `No`: ERPNext's all-or-nothing check
  would block the audited Finance Director bypass and reject service / milestone invoices. The
  "Delivery Note before Invoice" rule for stock items is enforced by
  `horizon_operations.selling.validate_sales_invoice`. Buying Settings `po_required` /
  `pr_required` stay `Yes`.
- Roles: Department Head, Procurement Manager, Finance Director, Operations Head, Sales Manager,
  Warehouse Manager, Quality Inspector, HR Manager (`setup/roles.py`).
- Style: tabs, double quotes, line length 110, ruff-sorted imports (`pre-commit run --all-files`).

## License

MIT

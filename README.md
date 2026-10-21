# Horizon ERP

ERPNext v15 customisations for **Horizon Manufacturing Ltd** (company abbreviation `HML`, GST
branches Mumbai HQ and Delhi DC). Frappe / ERPNext 15.9x, HRMS 15, India Compliance 15.

## What's in this app

Horizon ERP packages the Horizon Manufacturing implementation as code so it can be re-created on
any bench: 7 custom DocTypes (Production Audit, Shipment Decision, Supplier Exception Log,
Quarterly Purchase Plan, Inventory API Log, Budget Override Request, Bank Reconciliation Sign-off,
plus two child tables), 4 approval workflows (PO approval, discount approval for Quotation and
Sales Order, production audit review, payment approval - 5 Workflow records), 20 tested Script
Reports (+ the API Usage Report = 21), 12 workspaces (a *Horizon ERP* home + one per assignment section, CRM & Selling split in two) backed by 26 number cards and
8 dashboard charts (1 custom chart source),
2 Jinja print formats, 4 notifications, 7 scheduler jobs, 1 REST API
(`get_inventory_snapshot`, rate limited and logged) and 7 form client scripts loaded through
`doctype_js`. Business rules (PO approval limits, blacklisted suppliers, discount caps, Delivery
Note before Invoice, Work Order capacity, quality gates, timesheet / task rules) live in
`doc_events` hooks and are covered by the test suite. The inventory API honours Warehouse User
Permissions (`warehouses_excluded` / 403 `warehouse_not_permitted`), the receipt flow is standard
ERPNext (Purchase Receipt draft = receipt, submit = GRN, blocked until the Quality Inspection is
submitted; QC Hold routing optional), suppliers carry a standard Supplier Scorecard, and the monthly budget email carries the year-end
forecast columns (the standard *Budget Variance Report* stays untouched). Design documents and the
full API contract are in `docs/` (`docs/api.md` for the endpoint). The folder layout mirrors the
`kaynes` app: one Frappe module per ERPNext domain (see *Folder structure*).

## The assignment and how it is delivered

**Brief.** Replace Horizon Manufacturing's legacy ERP and spreadsheets with ERPNext, acting as the
techno-functional lead: design the architecture, configure interconnected modules, build the
customisations, handle edge cases and conflicting requirements, and document every trade-off.
Horizon: industrial equipment maker, ~500 employees, INR 50 Cr revenue, Mumbai HQ (factory) and
Delhi DC (distribution). Stakeholders: Rajesh (Finance Director), Priya (Operations Head), Amit
(Sales Director), Neha (HR Manager).

### Pain points and what was achieved

| Pain point (brief) | Delivered | Where |
| --- | --- | --- |
| No real-time inventory visibility across 3 warehouses | One company, two GSTINs, Branch dimension; warehouse tree; consolidated stock; reorder formula + auto Material Request; inventory API for Delhi DC | `horizon_stock/`, `horizon_integrations/`, *Horizon Inventory* workspace |
| Sales and production in silos | Quotation delivery date from multi-level BOM lead time; Sales Order → Production Plan → Work Order with a capacity check | `horizon_selling/`, `horizon_manufacturing/` |
| No approval workflows, weak financial controls | PO approval by amount (INR 1 L / 5 L), blacklisted-supplier override to the Finance Director with an exception log, discount > 15 % approval, payment approval, budget Stop / Warn, 24 h reminders / 48 h escalation, audit trail | `horizon_buying/`, `horizon_workflow/`, `horizon_accounts/` |
| Manual payroll, no project time tracking | Shifts and late marking, leave policy, three salary structures in one payroll (PF / ESI / PT / TDS), timesheets with overtime, project costing, milestone invoices | `horizon_hr/`, `horizon_payroll/`, `horizon_projects/` |
| Quote generation not linked to manufacturing | Lead → qualified Opportunity (customer details) → Quotation (Customer created, pricing rules, agreed rates) → Sales Order (rates locked to the SO) → Work Order | `horizon_crm/`, `horizon_selling/` (ADR-14, 17, 18) |
| Quality tracked in e-mail | Inspection before GRN, operation inspections, Production Audit (< 70 blocks completion), rework Work Orders, Non Conformance + Quality Action, Shipment Decision, Supplier Scorecard | `horizon_quality_management/` |

Open item: customer-complaint intake (standard Warranty Claim / Issue linked to Non Conformance)
is designed, not configured.

### Assignment sections → implementation

| Assignment section | Implementation | Design / evidence |
| --- | --- | --- |
| Setup & Masters, Chart of Accounts, cost centres | Company, GST addresses, Branch dimension, warehouses, cost-centre tree with allocation, CoA additions, permission model (`horizon_setup/demo_data.py`) | docs/01 §1–3, ADR-1 |
| CRM & Selling: lead-to-quote, pricing, order-to-delivery | Opportunity → Customer automation, 4 pricing rules, discount approval, Delivery Note before invoice, auto draft invoice, Order Status report | docs/01 §5, ADR-14/17/18 |
| Buying: approvals, blacklist, receipt → QC → GRN | PO workflow, Supplier Exception Log, Purchase Receipt draft = receipt, submit = GRN after Quality Inspection, auto return / debit note, Supplier Scorecard | ADR-2 |
| Inventory reorder & MRP | Daily reorder-level formula, auto Material Request, Forecast vs Actual, Inventory Obsolescence | docs/01 §5 |
| Manufacturing: BOM, capacity, QC | 8 three-level BOMs, capacity check, Capacity Utilisation report, rework loop, Quality Metrics; an inspection template on every operation, Job Card and Work Order *Finish* blocked until each operation has an Accepted Quality Inspection (Job Card *Create > Quality Inspection* pre-fills it) | ADR-4, ADR-19 |
| Projects & Assets | Overtime flag, overhead %, milestone billing, asset depreciation, maintenance | docs/01 |
| HR & Payroll | Shifts, leave, three salary structures, statutory deductions, Salary Cost Analysis | docs/01 |
| Accounts: bank, budget, GST | Bank import + sign-off, budgets + forecast mail, India Compliance GST | docs/01 |
| Development tasks (5) | Production Audit DocType, inventory REST API, print formats, scheduler jobs, Obsolescence report | `docs/api.md` |
| Strategic challenges (4) | One company vs multi-company, customer-supplier overlap, quality vs deadline, data migration | docs/03 |
| Bonus | E-commerce portal design (design only) | docs/09 |

### Submission contents

| Deliverable (brief) | Location |
| --- | --- |
| ERPNext instance | Database backup + restore guide (`docs/06`), demo data reproducible with `setup_all`; screenshots PDF and walkthrough video supplied separately |
| Code repository | This repository (`horizon_erp` app) |
| Documentation | `docs/01`–`09`: configuration design, decision log (ADR-1…18), strategic challenges, requirements challenged, test plan and evidence, deployment guide, QA report, screenshot guide, e-commerce design, API contract |
| Test data & scripts | `horizon_erp/data/*.csv`, `horizon_setup/demo_data.py`, `demo_hr_finance.py`; automated tests (`bench run-tests --app horizon_erp --skip-test-records`) |
| Users and roles | `docs/users_roles.md` (demo logins) |

## Setup

Run from the bench root (`frappe-bench/`). The site used throughout is `horizon.local`.

```bash
# 0. fetch the dependencies (version-15) and this app
bench get-app erpnext --branch version-15
bench get-app payments --branch version-15
bench get-app hrms --branch version-15
bench get-app india_compliance --branch version-15
bench get-app https://github.com/PrabaKaran1204/Horizon.git --branch master
bench new-site horizon.local --admin-password admin
bench --site horizon.local install-app erpnext payments hrms india_compliance

# 1. install (after_install syncs <module>/custom/*.json, then roles, role permissions,
#    workflows, print formats, notifications)
bench --site horizon.local install-app horizon_erp

# 2. demo masters, settings, opening stock; also runs setup_workflows + setup_hr_finance
bench --site horizon.local execute horizon_erp.horizon_setup.demo_data.setup_all

# 3. HR / finance demo data (idempotent; already called by setup_all, safe to re-run alone)
bench --site horizon.local execute horizon_erp.horizon_setup.demo_hr_finance.setup_hr_finance

# 4. validate workspaces / number cards / charts after migrate synced them
bench --site horizon.local execute horizon_erp.horizon_setup.dashboards.setup_dashboards

# 5. assets (public/js form scripts) and caches
bench build --app horizon_erp
bench --site horizon.local clear-cache

# 6. scheduler (hourly / daily / cron jobs in hooks.py)
bench --site horizon.local enable-scheduler
```

After every pull: `bench --site horizon.local migrate` (patches, DocTypes, `custom/` JSON, fixtures,
after_migrate sync), `bench build --app horizon_erp` when `public/` changed, `bench restart` after
Python changes. Sites installed before the module restructure are converted by the
`patches/v1_0/restructure_modules.py` patch on that migrate (see docs/06).

On this development bench `bench start` serves another site on port 8000; `horizon.local` is
served by a separate `bench serve --port 8001` process (with reload). Use
`http://127.0.0.1:8001` for UI and API smoke checks.

### API alias

The integration contract is `POST /api/method/get_inventory_snapshot`. `hooks.py` maps that short
name through `override_whitelisted_methods` to
`horizon_erp.horizon_integrations.inventory_api.get_inventory_snapshot`. The pre-restructure paths
`horizon_erp.api.inventory.get_inventory_snapshot` and `horizon_erp.api.get_inventory_snapshot`
keep working through re-export shims in `horizon_erp/api/`. Authenticate with
`Authorization: token KEY:SECRET`.

```bash
curl -s -X POST http://127.0.0.1:8001/api/method/get_inventory_snapshot \
  -H "Content-Type: application/json" -H "Authorization: token KEY:SECRET" \
  -d '{"warehouse": "Delhi DC"}'
```

## Tests

```bash
bench --site horizon.local run-tests --app horizon_erp --skip-test-records
# one module, e.g. the layout guard or the selling rules
bench --site horizon.local run-tests --app horizon_erp --module horizon_erp.tests.test_module_structure
bench --site horizon.local run-tests --app horizon_erp --module horizon_erp.horizon_selling.tests.test_selling --skip-test-records
```

`--skip-test-records` is required: Frappe would otherwise try to create ERPNext's generic
`test_records` for every dependency DocType (Company `_Test Company`, items, warehouses, ...),
which collide with the Horizon demo masters and the India Compliance validations on this site.
Every Horizon test module builds its own fixtures (prefixes `BRTEST-`, `APITEST-`, `SCHTEST-`,
`RPTTEST-`, `GAPTEST-`) inside the test transaction; shared builders are in
`horizon_core/tests/fixtures.py`.

Development checks (run from `apps/horizon_erp`):

```bash
../../env/bin/python -m compileall -q horizon_erp
../../env/bin/python -c "import horizon_erp.hooks"
ruff check horizon_erp && ruff format --check horizon_erp
for f in horizon_erp/public/js/*.js horizon_erp/*/report/*/*.js horizon_erp/*/doctype/*/*.js; do node --check "$f"; done
```

## Folder structure

Same convention as the `kaynes` app (`apps/kaynes/kaynes`): `modules.txt` lists one module per
ERPNext domain, and every module folder owns everything of that domain.

| kaynes | horizon_erp | Holds |
| --- | --- | --- |
| `kaynes_<domain>/custom/<doctype>.json` | `horizon_<domain>/custom/<doctype>.json` | Custom Fields / Property Setters ("Export Customizations" shape, `sync_on_migrate: 1`) |
| `kaynes_<domain>/doctype/`, `report/`, `print_format/`, `workspace/` | `horizon_<domain>/doctype/`, `report/`, `print_format/`, `workspace/`, `number_card/`, `dashboard_chart/` | standard Frappe records of the domain |
| `kaynes_<domain>/*.py`, `utils.py`, `api.py` | `horizon_<domain>/<domain>.py`, `tasks.py` | `doc_events` handlers, whitelisted methods, scheduler jobs of the domain |
| `kaynes_<domain>/tests/` | `horizon_<domain>/tests/` (+ `doctype/*/test_*.py`, `report/*/test_*.py`) | tests next to the code |
| `kaynes_setup/install.py` | `horizon_setup/install.py` | `after_install` / `after_migrate` |
| `kaynes_core/` | `horizon_core/` | shared config, job wrapper, cross-domain jobs |
| `overrides/`, `patches/` + `patches.txt`, `fixtures/`, `tests/`, `utils/`, `config/`, `public/`, `templates/`, `www/` | same | app-wide pieces |

```
horizon_erp/
  hooks.py  modules.txt  patches.txt
  api/                          legacy alias shims -> horizon_integrations.inventory_api (do not extend)
  config/  www/                 Frappe app scaffolding (empty)
  data/*.csv                    exported demo masters (items, customers, suppliers, BOM lines, ...)
  fixtures/*.json               bench export-fixtures: roles, custom docperm, workflows, workflow
                                states / actions, print formats, notifications, workspaces,
                                number cards (no Custom Field / Property Setter; Dashboard Charts
                                ship only as module JSON, see ADR-16)
  overrides/                    override_doctype_class targets (none yet)
  patches/v1_0/restructure_modules.py   re-homes records from the four pre-restructure modules
  patches/v1_0/redesign_workspaces.py   deletes the workspaces / chart replaced by ADR-16
  public/js/*.js                doctype_js form scripts (Quotation, Sales Order, Purchase Order,
                                Delivery Note, Work Order)
  templates/emails/             daily_summary.html, budget_report.html
  tests/                        cleanup.py (residue purge), test_tasks.py (all scheduler jobs, print
                                formats, notifications), test_module_structure.py (layout guard)
  utils/                        Jinja helpers + get_setting(); jinja_methods.py is the jinja hook
  horizon_setup/                install.py, roles.py, custom_fields.py (sync wrapper), demo_data.py,
                                demo_hr_finance.py, print_formats.py, notifications.py,
                                client_scripts.py, dashboards.py (custom number card sources), tests/
  horizon_core/                 config.py (thresholds, roles, warehouses), jobs.py (@horizon_job,
                                notify_users, safe_sendmail), tasks.py (18:00 daily summary),
                                tests/fixtures.py (shared test builders)
  horizon_workflow/             workflows.py (5 workflows as code), custom/
  horizon_buying/               buying.py (PO approval level, blacklist override), tasks.py (PO SLA
                                reminders), custom/, doctype/ (supplier_exception_log,
                                quarterly_purchase_plan[_item]), report/approval_audit_report,
                                number_card/, dashboard_chart/, tests/
  horizon_selling/              selling.py (discount governance, availability, DN / SI rules),
                                custom/, report/ (order_status_report, price_list_comparison),
                                print_format/horizon_sales_invoice, workspace/horizon_selling,
                                number_card/, dashboard_chart/, tests/
  horizon_crm/                  opportunity.py (Opportunity -> Customer, Lead quotation switch), custom/opportunity.json,
                                workspace/horizon_crm, number_card/ (open leads, leads > 14 days, open
                                opportunities + value, leads converted 90d), dashboard_chart/,
                                report/crm_pipeline_summary, tests/
  horizon_stock/                purchase_receipt.py (rejection paperwork, optional QC Hold), scrap.py,
                                tasks.py (reorder + accuracy, reorder recompute), custom/{item,stock_settings}.json,
                                report/ (inventory_obsolescence_analysis, forecast_vs_actual_demand),
                                print_format/horizon_packing_slip_thermal, workspace/horizon_inventory,
                                number_card/, dashboard_chart/, dashboard_chart_source/
                                (stock value by warehouse), tests/
  horizon_manufacturing/        manufacturing.py (capacity check), custom/, report/
                                (capacity_utilisation_and_sequence, bom_explosion_with_lead_time),
                                workspace/horizon_manufacturing, number_card/, dashboard_chart/, tests/
  horizon_quality_management/   inspection.py, production_audit_hooks.py, tasks.py (quality vs
                                deadline), custom/, doctype/ (production_audit[_photo],
                                shipment_decision), report/ (4), workspace/horizon_quality,
                                number_card/, dashboard_chart/, tests/
  horizon_projects/             projects.py (timesheet / milestone rules), custom/, report/project_profitability, tests/
  horizon_hr/                   report/leave_balance_with_carry_forward_expiry
  horizon_payroll/              report/salary_cost_analysis
  horizon_accounts/             tasks.py (budget alerts, monthly budget report), budget.py, custom/,
                                doctype/ (budget_override_request, bank_reconciliation_sign_off),
                                report/ (4), workspace/horizon_accounts_&_finance, number_card/
  horizon_assets/               report/asset_register_with_maintenance
  horizon_integrations/         inventory_api.py (get_inventory_snapshot), rate_limit.py,
                                client/inventory_sync_client.py, doctype/inventory_api_log,
                                report/api_usage_report, tests/
docs/                           design documents (business rules, API contract, data model, test plan)
```

## Module map

| Module | DocTypes | Hooks / code | Reports | Workspace |
| --- | --- | --- | --- | --- |
| Horizon Setup | - | `horizon_setup.install`, `roles`, `custom_fields`, `demo_data`, `demo_hr_finance`, `print_formats`, `notifications`, `dashboards` | - | Horizon Setup & Masters |
| Horizon Core | - | `horizon_core.config`, `horizon_core.jobs`, `horizon_core.tasks.send_daily_summary` | - | Horizon ERP (home, parent of all) |
| Horizon Workflow | - | `horizon_workflow.workflows.setup_workflows` | - | - |
| Horizon Buying | Supplier Exception Log, Quarterly Purchase Plan (+ Item) | `horizon_buying.buying`, `horizon_buying.tasks.po_approval_reminders`, `public/js/purchase_order.js` | Approval Audit | Horizon Buying |
| Horizon Selling | - | `horizon_selling.selling`, `public/js/{quotation,sales_order,delivery_note}.js` | Order Status, Price List Comparison | Horizon Selling |
| Horizon CRM | - | `horizon_crm.opportunity` (Customer created from the qualified Opportunity with group, GSTIN, billing address, credit limit and payment terms; Lead quotations moved to that Customer before pricing - ADR-17), `public/js/opportunity.js`, `custom/opportunity.json`; lead / opportunity cards and charts | - | Horizon CRM |
| Horizon Stock | - | `horizon_stock.purchase_receipt`, `horizon_stock.scrap`, `horizon_stock.tasks` | Forecast vs Actual Demand, Inventory Obsolescence Analysis | Horizon Inventory |
| Horizon Manufacturing | - | `horizon_manufacturing.manufacturing`, `public/js/work_order.js` | BOM Explosion with Lead Time, Capacity Utilisation and Sequence | Horizon Manufacturing |
| Horizon Quality Management | Production Audit (+ Photo), Shipment Decision | `horizon_quality_management.inspection`, `production_audit_hooks`, `tasks.detect_quality_deadline_conflicts` | Audit Findings Dashboard, Quality Metrics, Quality vs Deadline Conflicts, Supplier Quality Scorecard | Horizon Quality |
| Horizon Projects | - | `horizon_projects.projects` | Project Profitability | Horizon Projects & Assets |
| Horizon HR | - | - | Leave Balance with Carry-forward Expiry | Horizon HR & Payroll |
| Horizon Payroll | - | - | Salary Cost Analysis | - |
| Horizon Accounts | Budget Override Request, Bank Reconciliation Sign-off | `horizon_accounts.tasks` (budget alerts, monthly budget report with year-end run-rate forecast), `horizon_accounts.budget` | Bank Unmatched Aging, Cost Center-wise P&L, Data Validation, Net Party Position | Horizon Accounts & Finance (Finance Director's queue) |
| Horizon Assets | - | - | Asset Register with Maintenance | - |
| Horizon Integrations | Inventory API Log | `horizon_integrations.inventory_api`, `rate_limit`, `client.inventory_sync_client` | API Usage Report | Horizon Integrations |

Shared helpers: `utils/` (Jinja globals `horizon_customer_outstanding`, `horizon_similar_items_in_stock`,
`horizon_due_date`, `horizon_company_gst`, `horizon_dn_row_serials`, `horizon_pan_from_gstin`).

## Workspaces

The desk sidebar starts with **Horizon ERP** (`/app/horizon-erp`): headline KPIs, a link to every
module workspace and the three demo flows with their document names. Its eleven children follow the
assignment sections in order (the CRM & Selling section is split into *CRM*, Lead -> Opportunity ->
Quotation, and *Selling*, pricing and order to delivery), each with a one-paragraph scope, the process flow, KPIs, shortcuts in
process order and Transactions / Masters / Reports cards (ADR-16):

| # | Workspace | Module | Route |
| --- | --- | --- | --- |
| 0 | Horizon ERP | Horizon Core | `/app/horizon-erp` |
| 1 | Horizon Setup & Masters | Horizon Setup | `/app/horizon-setup-&-masters` |
| 2 | Horizon CRM | Horizon CRM | `/app/horizon-crm` |
| 3 | Horizon Selling | Horizon Selling | `/app/horizon-selling` |
| 4 | Horizon Buying | Horizon Buying | `/app/horizon-buying` |
| 5 | Horizon Inventory | Horizon Stock | `/app/horizon-inventory` |
| 6 | Horizon Manufacturing | Horizon Manufacturing | `/app/horizon-manufacturing` |
| 7 | Horizon Quality | Horizon Quality Management | `/app/horizon-quality` |
| 8 | Horizon Projects & Assets | Horizon Projects | `/app/horizon-projects-&-assets` |
| 9 | Horizon HR & Payroll | Horizon HR | `/app/horizon-hr-&-payroll` |
| 10 | Horizon Accounts & Finance | Horizon Accounts | `/app/horizon-accounts-&-finance` |
| 11 | Horizon Integrations | Horizon Integrations | `/app/horizon-integrations` |

`bench --site horizon.local execute horizon_erp.horizon_setup.dashboards.setup_dashboards` checks
icons, parents, every referenced card / chart / DocType / Report / Page / child-workspace URL and
that every content block resolves (the desk matches blocks by the child row *label*).

## Conventions

- New code goes into the module of its ERPNext domain (`horizon_<domain>/`), never into a
  catch-all package. Scheduler jobs go into that module's `tasks.py`, decorated with
  `horizon_core.jobs.horizon_job`, and are registered in `hooks.py` `scheduler_events`.
- Custom Fields on standard DocTypes live in `horizon_<domain>/custom/<doctype>.json` (Frappe
  Export Customizations shape, `sync_on_migrate: 1`, `custom_perms` always empty, `module` set to the
  folder's module). `bench migrate` syncs them; `install-app` syncs them in `after_install`. Do not
  export them as fixtures.
- Workflows, Workflow States, Workflow Action Masters, Roles, Custom DocPerm, Print Formats,
  Notifications, Workspaces and Number Cards are fixtures
  (`bench --site horizon.local export-fixtures --app horizon_erp`). Dashboard Charts are module JSON
  only (fixture import would validate them and fail without developer mode). Prefix names with `Horizon` and
  add new Workflow States / Actions to the name lists in `hooks.py` before exporting.
  Workflows / print formats / notifications are *also* created in code (`horizon_workflow/`,
  `horizon_setup/`) so a fresh site is complete right after `install-app`.
- Selling Settings `so_required` / `dn_required` are kept at `No`: ERPNext's all-or-nothing check
  would block the audited Finance Director bypass and reject service / milestone invoices. The
  "Delivery Note before Invoice" rule for stock items is enforced by
  `horizon_selling.selling.validate_sales_invoice`. Buying Settings `po_required` /
  `pr_required` stay `Yes`.
- Roles: Department Head, Procurement Manager, Finance Director, Operations Head, Sales Manager,
  Warehouse Manager, Quality Inspector, HR Manager (`horizon_setup/roles.py`).
- Style: tabs, double quotes, line length 110, ruff-sorted imports (`pre-commit run --all-files`).

## License

MIT

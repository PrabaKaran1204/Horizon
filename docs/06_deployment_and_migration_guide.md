# Horizon ERP - Deployment and Migration Guide

Target stack: Frappe 15.96, ERPNext 15.94, HRMS 15.55, India Compliance 15.25, Python 3.10+,
MariaDB 10.6+, Redis, Node 18, wkhtmltopdf 0.12.6 (patched Qt) for PDFs.

## 1. Fresh bench

```bash
# 1. bench and apps (version-15 branches)
bench init frappe-bench --frappe-branch version-15
cd frappe-bench
bench get-app erpnext --branch version-15
bench get-app payments --branch version-15
bench get-app hrms --branch version-15
bench get-app india_compliance --branch version-15
bench get-app horizon_erp <git-url>          # or copy the folder into apps/ and `bench setup requirements`

# 2. site
bench new-site horizon.local --db-name horizon --admin-password <admin-pw>
bench --site horizon.local set-config developer_mode 1       # dev / demo only (enables _simulate_failure)

# 3. install order matters: erpnext -> payments -> hrms -> india_compliance -> horizon_erp
bench --site horizon.local install-app erpnext
bench --site horizon.local install-app payments
bench --site horizon.local install-app hrms
bench --site horizon.local install-app india_compliance
bench --site horizon.local install-app horizon_erp         # after_install: custom/ JSON fields, roles, workflows, print formats, notifications

# 4. company
# Run the Setup Wizard once (Company "Horizon Manufacturing Ltd", abbr HML, country India,
# currency INR, fiscal year 01-04-2026 to 31-03-2027, chart "Standard with Numbers" or Standard).
# Select "India" so India Compliance creates GST accounts; otherwise demo_data creates them.

# 5. configuration + demo data (idempotent, re-runnable; prints a per-step summary)
bench --site horizon.local execute horizon_erp.horizon_setup.demo_data.setup_all
#   -> settings, Branch dimension, addresses/GSTINs, cost centres + allocation, accounts, warehouses,
#      item groups + GST templates, items, parties (ABC Corp Party Link, ABC Supplies blacklisted),
#      pricing, workstations/operations/QI templates/BOMs, opening stock, users (Horizon@123),
#      CSV export, then optional modules: horizon_workflow.workflows.setup_workflows and
#      horizon_setup.demo_hr_finance.setup_hr_finance (HR, payroll, project, asset, budgets, bank, recurring JEs)

# optional: run HR/finance alone or again
bench --site horizon.local execute horizon_erp.horizon_setup.demo_hr_finance.setup_hr_finance
bench --site horizon.local execute horizon_erp.horizon_setup.demo_hr_finance.verify

# 6. notifications, print formats, client scripts (not part of setup_all)
bench --site horizon.local execute horizon_erp.horizon_setup.notifications.setup_notifications
bench --site horizon.local execute horizon_erp.horizon_setup.print_formats.setup_print_formats
bench build --app horizon_erp
#   hooks.py wires the form scripts through doctype_js (public/js/*.js), so they need the asset
#   build. setup_client_scripts is only a fallback that installs the same files as Client Script
#   records; do not run it on a site that serves them via doctype_js.
bench --site horizon.local execute horizon_erp.horizon_setup.dashboards.setup_dashboards   # workspace sanity check

# 7. scheduler and services
bench --site horizon.local enable-scheduler
bench --site horizon.local set-config horizon_api_rate_limit 100      # optional override
bench --site horizon.local migrate
bench restart        # or `bench start` in development
```

Email: `demo_data.setup_email_account` creates the default outgoing Email Account **Horizon
Notifications** (`notifications@horizon.local`, SMTP `localhost:25`, no authentication) as a
placeholder so workflow / notification / scheduler e-mails can be queued; replace its server, port,
TLS and login with the client's SMTP relay before go-live (the step never overwrites an existing
account's connection settings). Without a default outgoing account every `frappe.sendmail` raises and
ERPNext logs one Error Log per notification; Horizon's own mails go through
`horizon_core.jobs.safe_sendmail` and never block a transaction either way.

### Reaching the site from Windows (WSL2)

- `bench start` serves port 8000. Port 8000 serves the **default site**; if `horizon.local` is not
  the default, either `bench use horizon.local` or run `bench --site horizon.local serve --port 8001`
  and use `http://localhost:8001`.
- Host name resolution: add `127.0.0.1 horizon.local` to `C:\Windows\System32\drivers\etc\hosts`
  (and to `/etc/hosts` inside WSL). Alternatively `bench --site horizon.local add-to-hosts` inside WSL.
- Check `sites/currentsite.txt` and `serve_default_site` in `sites/common_site_config.json`.

## 2. Restore from backup

```bash
bench --site horizon.local restore /path/to/<timestamp>-horizon_local-database.sql.gz \
    --with-public-files  /path/to/<timestamp>-horizon_local-files.tar \
    --with-private-files /path/to/<timestamp>-horizon_local-private-files.tar \
    --mariadb-root-password <root-pw>
bench --site horizon.local migrate
bench --site horizon.local set-admin-password <admin-pw>
bench --site horizon.local clear-cache
bench --site horizon.local enable-scheduler
bench restart
```

### Upgrading a site from the pre-restructure layout

Sites installed before the domain-module restructure have their Horizon records under the modules
Horizon Operations / Horizon Quality / Horizon Finance / Horizon Integration. `bench migrate` runs
`horizon_erp.patches.v1_0.restructure_modules` (`[pre_model_sync]`, idempotent): it creates the 15
new Module Defs, re-homes every DocType, Report, Workspace, Number Card, Dashboard Chart, Print Format,
Notification and Custom Field to its domain module, rewrites the Number Card `method` paths
(`horizon_erp.setup.dashboards.*` -> `horizon_erp.horizon_setup.dashboards.*`), moves anything else
still on an old module to the closest new one and deletes the four old Module Defs once nothing
references them. Scheduled Job Types are re-synced from `hooks.py` by migrate itself. Run
`bench --site <site> clear-cache` first (Frappe caches the app -> modules map in Redis). Orphan check
after migrate (expect 0 rows from every table that has a `module` column):

```sql
select table_name from information_schema.columns
where table_schema = database() and column_name = 'module';
-- then for each table: select count(*) from `<table>` where module in
--   ('Horizon Operations', 'Horizon Quality', 'Horizon Finance', 'Horizon Integration');
```

`bench --site <site> run-tests --app horizon_erp --module horizon_erp.tests.test_module_structure`
asserts the same (plus file / DB module agreement for every shipped JSON).

### Post-restore checklist

| # | Check | How |
| --- | --- | --- |
| 1 | App versions match | `bench version` shows frappe 15.96, erpnext 15.94, hrms 15.55, india_compliance 15.25, horizon_erp |
| 2 | Custom fields and roles present | Custom Fields come from `horizon_erp/<module>/custom/*.json` and are synced by `bench --site horizon.local migrate`; re-sync on demand with `bench --site horizon.local execute horizon_erp.horizon_setup.custom_fields.setup_custom_fields`; roles / permissions / workflows with `bench --site horizon.local execute horizon_erp.horizon_setup.install.after_migrate` (idempotent) |
| 3 | Workflows active | Workflow list: Horizon PO Approval, Horizon Discount Approval, Horizon Discount Approval - Sales Order, Horizon Production Audit, Horizon Payment Approval |
| 4 | Notifications enabled | Notification list filter `Horizon%` (4 records) |
| 5 | Print formats render | Open a Sales Invoice, choose *Horizon Sales Invoice*; a Delivery Note with *Horizon Packing Slip Thermal* |
| 6 | Scheduler running | `bench --site horizon.local scheduler status`; Scheduled Job Log shows `horizon_erp.horizon_*.tasks.*` (stock, buying, quality_management, accounts, core) |
| 7 | Workspaces consistent | `bench --site horizon.local execute horizon_erp.horizon_setup.dashboards.setup_dashboards` |
| 7b | Role matrix applied | `bench --site horizon.local execute horizon_erp.horizon_setup.roles.setup_role_permissions` (also runs on every `bench migrate`); Custom DocPerm rows for Batch, Serial No, Serial and Batch Bundle, Address, Contact, Supplier, Customer, Quality Inspection, Sales Invoice, Delivery Note |
| 8 | API keys regenerated | Backups do not carry usable secrets for new users; regenerate on the integration user |
| 9 | Email account and site URL | Replace the placeholder SMTP settings of Email Account *Horizon Notifications*; `host_name` in `site_config.json` so links in emails resolve |
| 10 | Redis counters | Rate-limit buckets live in Redis, not the DB: `bench --site horizon.local execute horizon_erp.horizon_integrations.rate_limit.reset_rate_limit --args '["<client>"]'` if needed |
| 11 | Demo passwords | Change `Horizon@123` on the eight demo users before any shared environment |
| 12 | Developer mode off | `developer_mode 0` in production (disables `_simulate_failure`) |
| 13 | Receipt / QC settings | Stock Settings > Quality: *Action if Quality Inspection is not Submitted* = Stop, *Action if Quality Inspection is Rejected* = Warn, *Allow to Make Quality Inspection after Purchase / Delivery* = 0, *Route Inspected Receipts via QC Hold* (`horizon_use_qc_hold`, Horizon section) = 0. Set by `demo_data.setup_company_settings` |
| 14 | Supplier Scorecards | One standard *Supplier Scorecard* per supplier: `bench --site horizon.local execute horizon_erp.horizon_setup.demo_data.setup_supplier_scorecards` (idempotent; also the last step of `setup_all`). ERPNext's daily `refresh_scorecards` job adds each completed month |

## 3. Data import order (CSV, `horizon_erp/data/`)

The CSVs are generated from `demo_data.py` (`export_csvs`) and follow Data Import labels. Use
*Data Import* (Insert New Records) in this order; masters referenced by a file must already exist.

| Order | File | DocType | Prerequisites |
| --- | --- | --- | --- |
| 1 | `cost_centers.csv` | Cost Center | Company; parents before children |
| 2 | `warehouses.csv` | Warehouse | Company; groups before leaves |
| 3 | `items.csv` | Item (+ Item Defaults, Item Reorder) | Item Groups, UOMs, Suppliers (for default supplier) - run `setup_item_groups_and_taxes` / `setup_uoms` first |
| 4 | `suppliers.csv` | Supplier (+ Address, Contact) | Supplier Groups |
| 5 | `customers.csv` | Customer (+ Address, Contact, Credit Limit) | Customer Groups, Territories, Price List North Selling |
| 6 | `item_prices.csv` | Item Price | Price Lists Standard Selling / Standard Buying / North Selling |
| 7 | `pricing_rules.csv` | Pricing Rule | Item Groups, Customer Group Premium |
| 8 | `bom_lines.csv` | BOM (two line types: Material / Operation) | Items, Workstations, Operations; import bottom-up (sub-assemblies before HZ-PUMP-100 / HZ-CONV-200) |
| 9 | `bank_statement_sample.csv` | Bank Statement Import -> Bank Transaction | Bank Account *Horizon Current Account - HDFC* |

For a client migration add, before step 3: Chart of Accounts (Account importer), Employees
(`Employee`), opening stock (Stock Reconciliation, purpose Opening Stock, expense account
`Stock Adjustment - Migration - HML`), opening receivables / payables (Opening Invoice Creation
Tool), and run the *Data Validation Report* after each batch.

## 4. Known caveats

| Caveat | Detail |
| --- | --- |
| Test fixtures | Several tests create their own masters (`APITEST-*` warehouses, test items) and delete them in `tearDownClass`; run with `--skip-test-records` as shown in `docs/api.md`. Tests assume the HML company exists. |
| wkhtmltopdf | Daily summary PDF and print-format PDFs need wkhtmltopdf with patched Qt; without it the summary email is sent without the attachment and `pdf_error` is returned. |
| Port 8000 | Serves the default site; use `bench use horizon.local` or `serve --port 8001`. |
| Valuation method | `Stock Settings.valuation_method` cannot be switched after ledger entries exist; items carry Moving Average explicitly. |
| GSTIN | The brief's `27AABCU9602H1Z0` is invalid; `27AABCU9602H1Z9` / `07AABCU9602H1ZB` are used. Party GSTINs are generated from PANs and validated. |
| GST rates | 5 / 12 / 18 % templates are per the brief; confirm per HSN with the CA. 12 % slab was withdrawn in Sept 2025. |
| Payroll per branch | Because Branch is mandatory for P&L, run Payroll Entry once per branch (the demo script does this). |
| Workstation hours | Second window starts 14:01 (ERPNext inclusive overlap check); HRMS shifts use 14:00. |
| Client scripts | `doctype_js` is active in `hooks.py` (Quotation, Sales Order, Purchase Order, Delivery Note, Work Order); run `bench build --app horizon_erp` after pulling. `horizon_setup/client_scripts.py` is only a fallback installer (Client Script records) for benches that cannot build assets - never enable both. |
| Fixtures | `hooks.py` fixture filters list Workflows, Workflow States and Workflow Action Masters by name; the lists match the five workflows and their states / actions. Add any new workflow, state or action to the lists, then `bench --site horizon.local export-fixtures --app horizon_erp` (writes `horizon_erp/fixtures/*.json`). Custom Fields / Property Setters are **not** fixtures: they live in `<module>/custom/<doctype>.json` (`sync_on_migrate: 1`). |
| Bare API URL | `/api/method/get_inventory_snapshot` needs `override_whitelisted_methods` in `hooks.py` (see `docs/api.md`); the full dotted path works without it. |
| QC Hold toggle | Default flow is standard ERPNext: Purchase Receipt draft = receipt, submit = GRN (ADR-2). To route inspected items through `HQ QC Hold - HML` with an automatic release transfer instead, tick Stock Settings *Route Inspected Receipts via QC Hold* or set `"horizon_use_qc_hold": 1` in `site_config.json` (site config wins over the setting, `0` there forces it off). Switch only when no inspected-item receipts are in draft: a draft saved in one mode and submitted in the other keeps its row warehouse (in standard mode a QC Hold row is not released automatically; a warning says so). The `HQ QC Hold - HML` warehouse stays in the tree for this optional mode. The Stock Settings field ships in `horizon_stock/custom/stock_settings.json` (synced by `bench migrate`). |
| Supplier Scorecard periods | ERPNext only scores completed periods from the supplier's creation date; `setup_supplier_scorecards` adds a month-to-date period (a standard Supplier Scorecard Period) and replaces it on the next run, so re-run it (or let the month close) to refresh scores. |
| Email in demos | With `frappe.flags.mute_emails` set by the setup scripts, nothing is sent during setup; scheduler emails need an outgoing account. |

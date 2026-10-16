# Horizon ERP

ERPNext v15 customisations for **Horizon Manufacturing Ltd** (company abbreviation `HML`, GST
branches Mumbai HQ and Delhi DC). Frappe / ERPNext 15.9x, HRMS 15, India Compliance 15.

## Setup

```bash
cd frappe-bench

# 1. fetch the app (skip if already in apps/)
bench get-app horizon_erp <git-url>

# 2. create the site and install the stack
bench new-site horizon.local
bench --site horizon.local install-app erpnext hrms india_compliance
bench --site horizon.local install-app horizon_erp      # runs after_install: roles + custom fields

# 3. after every pull
bench --site horizon.local migrate                       # DocTypes, fixtures, after_migrate sync
bench build --app horizon_erp                            # only when public/ assets change
bench restart                                            # after hooks.py / python changes

# 4. demo data (script owned by the demo-data developer; placeholder path)
bench --site horizon.local execute horizon_erp.setup.demo_data.setup_all
```

Development checks (run from `apps/horizon_erp`):

```bash
../../env/bin/python -m compileall -q horizon_erp
../../env/bin/python -c "import horizon_erp.hooks"
ruff check horizon_erp
bench --site horizon.local run-tests --app horizon_erp
```

## App layout

```
horizon_erp/
  hooks.py                      every hook pre-declared (doc_events, scheduler, fixtures, install)
  modules.txt                   Horizon Quality | Horizon Integration | Horizon Operations | Horizon Finance
  utils.py                      jinja_methods(), get_setting()
  api/inventory.py              @frappe.whitelist get_inventory_snapshot (logs to Inventory API Log)
  setup/install.py              after_install / after_migrate -> setup_roles + setup_custom_fields
  setup/roles.py                HORIZON_ROLES, setup_roles()
  setup/custom_fields.py        get_custom_fields(), setup_custom_fields()  (NOT fixtures)
  tasks/hourly.py daily.py monthly.py   scheduler entry points
  horizon_quality/              inspection.py, production_audit_hooks.py, doctype/
  horizon_operations/           buying.py, selling.py, manufacturing.py, projects.py, doctype/
  horizon_integration/          doctype/inventory_api_log
  horizon_finance/              doctype/budget_override_request, bank_reconciliation_sign_off
  patches/ + patches.txt        data / schema patches
```

## Module map

| Module | DocTypes | Hooks / code |
| --- | --- | --- |
| Horizon Quality | Production Audit (+ Production Audit Photo), Shipment Decision | `horizon_quality.inspection`, `horizon_quality.production_audit_hooks` |
| Horizon Operations | Supplier Exception Log, Quarterly Purchase Plan (+ Item) | `horizon_operations.buying / selling / manufacturing / projects` |
| Horizon Integration | Inventory API Log | `api.inventory` |
| Horizon Finance | Budget Override Request, Bank Reconciliation Sign-off | `tasks.daily.budget_threshold_alerts`, `tasks.monthly.send_budget_report` |

## Conventions

- Business logic lives behind the stubs declared in `hooks.py`; look for `# TODO(<area>)`.
- Custom Fields on standard DocTypes are defined in `setup/custom_fields.py` and applied on
  install / migrate. Do not export them as fixtures.
- Workflows, Workflow States, Workflow Action Masters, Print Formats, Notifications, Workspaces,
  Number Cards and Dashboard Charts are fixtures. Prefix names with `Horizon` and add new
  Workflow States / Actions to the name lists in `hooks.py` before `bench export-fixtures`.
- Roles: Department Head, Procurement Manager, Finance Director, Operations Head, Sales Manager,
  Warehouse Manager, Quality Inspector, HR Manager (`setup/roles.py`).
- Style: tabs, double quotes, line length 110, ruff-sorted imports (`pre-commit run --all-files`).

## License

MIT

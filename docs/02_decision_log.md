# Horizon ERP - Architecture Decision Log

Format: Context / Options / Decision / Consequences / Status. Status values: **Accepted**
(built and in the code), **Accepted - partially built**, **Proposed** (documented only).

---

## ADR-1 One company with a Branch accounting dimension

**Context.** Finance wants a P&L per location; Operations wants one inventory picture. Horizon is one
legal entity with two GST registrations (Maharashtra, Delhi).

**Options.**
1. Two ERPNext companies - clean P&L, but every HQ-to-DC movement becomes an inter-company sale and
   purchase (two invoices, two ledgers, elimination at consolidation), duplicated masters, and a
   legal fiction.
2. One company, Cost Center per location - cost centres are already needed for departments and
   product lines; using them for location too forces a 2 x 7 matrix of cost centres.
3. **One company, Branch as a mandatory P&L Accounting Dimension** - location is orthogonal to
   department; one stock ledger; standard P&L with a Branch filter.

**Decision.** Option 3. `Accounting Dimension` on `Branch` (`Mumbai HQ`, `Delhi DC`), default
`Mumbai HQ`, `mandatory_for_pl = 1`, in `demo_data.setup_branches_and_dimension`.

**Consequences.** Every P&L posting must carry a branch (see ADR-5). Balance-sheet items (stock,
receivables) are not split by branch; if the board wants a branch balance sheet later, that is a
migration to Option 1 (memo 1 in `03_strategic_challenges.md`). Inter-branch GST still has to be
handled (ADR-10).

**Status.** Accepted.

---

## ADR-2 GRN = Purchase Receipt, with a QC Hold warehouse

**Context.** The brief asks for "PO -> Receipt -> Inspection -> GRN, only GRN updates inventory",
i.e. a fourth document after the receipt.

**Options.**
1. New custom "GRN" DocType after Purchase Receipt - duplicates Purchase Receipt (stock ledger,
   valuation, landed cost, returns, invoice linkage all live on PR), breaks Purchase Invoice
   `pr_required`, and every standard report ignores it.
2. **Purchase Receipt is the GRN**; inspection is forced before submit (Stock Settings Stop / Stop)
   and the physical state "received but not released" is a warehouse (`HQ QC Hold - HML`).

**Decision.** Option 2. `purchase_receipt.on_submit_purchase_receipt` moves accepted qty from QC Hold to the
item's default warehouse and raises the Purchase Return / Debit Note for `rejected_qty`.

**Consequences.** Stock is visible (and valued) in QC Hold between receipt and release, which is
the truth. Material in QC Hold is not available to Work Orders because it is not in Raw Materials.
The receipt warehouse must be QC Hold: `purchase_receipt.validate_purchase_receipt` enforces it - every
Purchase Receipt row whose Item requires inspection before purchase is routed to `HQ QC Hold - HML`
(with `HQ Rejected - HML` defaulted as the rejected warehouse) and the user is told which rows were
moved; rows for items without inspection keep their warehouse (follow-up closed).

**Status.** Accepted.

---

## ADR-3 Extend standard Quotation / Delivery Note / Purchase Receipt instead of new DocTypes

**Context.** The brief says "Create a Quotation DocType", "Delivery Note DocType", "Purchase Receipt
DocType".

**Options.** New DocTypes versus Custom Fields + hooks on the standard ones.

**Decision.** Custom Fields plus `doc_events` hooks. Originally defined in code (`setup/custom_fields.py`,
applied on install / migrate, not as fixtures); since ADR-15 they are Frappe customization JSON files
in `<module>/custom/<doctype>.json`. Quotation Item gets `available_qty`, `mfg_lead_days`,
`expected_delivery_date`, `rule_rate`, `discount_over_rule_pct`; Delivery Note gets
`customer_signature`, `received_by`, `deviation_notes`, `shipment_decision`; Quality Inspection
gets `qc_result`, `rejection_reason`, `evidence_required`, `rework_work_order`.

**Consequences.** Pricing rules, taxes, stock ledger, GST e-invoicing, print formats and every
standard report keep working. Fields sit on a "Horizon" tab so standard layouts are untouched.
Trade-off: custom fields on busy DocTypes must be re-verified at each ERPNext minor upgrade
(`bench migrate` re-syncs them idempotently).

**Status.** Accepted.

---

## ADR-4 Make-to-order vs make-to-stock trigger

**Context.** The brief says "Auto-create Work Order from Sales Order for made-to-stock items; manual
creation for make-to-order". That is reversed: a make-to-stock item is produced to a stock level,
not to an order; a make-to-order item is produced because an order exists.

**Options.**
1. Implement literally: a hook creating a WO on SO submit for spares.
2. **Standard flows by item type**: equipment (`HZ-*`, serialised, `lead_time_days` 21-28) is
   make-to-order - Production Plan "Get Items from Sales Order" creates WOs; spares (`SP-*`,
   `demand_pattern = Seasonal Q4`, reorder levels) are make-to-stock - reorder / Material Request
   drives the Production Plan.

**Decision.** Option 2. No auto-WO hook. The capacity check (`manufacturing.validate_work_order`)
applies to both.

**Consequences.** Sales promises on equipment are visible in the Production Plan before a WO is
created, which is where the capacity conversation should happen. The spares reorder rows in
`demo_data.ITEMS` are created with `material_request_type = Manufacture`, so the reorder raises a
production request rather than a Purchase Order (follow-up closed; `setup_all` updates existing rows).

**Status.** Accepted.

---

## ADR-5 Branch mandatory for P&L, and its side effects

**Context.** ADR-1 only delivers a branch P&L if no P&L posting can escape without a branch.

**Decision.** `mandatory_for_pl = 1` on the Branch dimension with company default `Mumbai HQ`.

**Consequences observed while building.**
- Server-created documents (QC release Stock Entry, auto Sales Invoice from Delivery Note, milestone
  invoices) never pass through client-side dimension defaulting; `config.apply_default_dimensions`
  fills the branch on the parent and item rows before insert.
- HRMS copies dimension values from the Payroll Entry onto the accrual journal, so payroll is run
  **once per branch** (`demo_hr_finance._payroll_branches`); employees without a branch are set to
  the default.
- Assets carry `branch` so depreciation journals post; recurring rent / electricity journals carry
  branch on every row.
- Any future custom posting must call `apply_default_dimensions` or it will fail at GL.

**Status.** Accepted.

---

## ADR-6 ABC Corp: separate Customer and Supplier linked by Party Link

**Context.** ABC Corp buys from and sells to Horizon. Receivable INR 10 L, payable INR 5 L.

**Options.**
1. One party record - ERPNext has no shared party; receivable and payable sit on different account
   types anyway.
2. **Separate Customer and Supplier, same PAN/GSTIN, linked by `Party Link` with
   `enable_common_party_accounting = 1`** - ERPNext then posts an automatic transfer journal when
   an invoice is raised on the secondary party, so the net exposure is visible in one ledger.

**Decision.** Option 2 (`demo_data.setup_parties`). Report *Net Party Position* shows receivable,
payable, net, direction and suggested settlement per linked pair.

**Consequences.** Settlement is a Journal Entry (Dr Creditors ABC 5 L / Cr Debtors ABC 5 L) with the
net 5 L collected as a Payment Entry; GST is unaffected because supplies were invoiced at gross.
Governance: netting needs a written agreement because it changes the legal set-off position
(memo 2).

**Status.** Accepted.

---

## ADR-7 Custom rate limiter instead of Frappe's built-in

**Context.** API must allow 100 requests per hour per client and answer **429**.

**Options.**
1. `frappe.rate_limiter.rate_limit` decorator - keys on IP or a form field, raises HTTP **417**, no
   `Retry-After`, no hook to log the rejected call.
2. Site-wide `frappe.conf.rate_limit` - one CPU-time budget for the whole site, not per client.
3. **Own decorator** `horizon_integrations/rate_limit.py`: client = authenticated user (API key owner), Redis
   `INCR` + `EXPIRE`, 429 JSON body, `Retry-After` / `X-RateLimit-*` headers through a duck-typed
   `frappe.local.rate_limiter`, `on_exceed` callback writes the *Inventory API Log* row.

**Decision.** Option 3. Limit configurable via `site_config.json` `horizon_api_rate_limit`.

**Consequences.** About 170 lines to own; Frappe upgrades that change `process_response` header
handling must be re-tested (`horizon_integrations/tests/test_inventory_api.py` covers it).

**Status.** Accepted.

---

## ADR-8 Fixed hourly bucket rather than a sliding window

**Context.** "100 per hour" can mean a rolling 60 minutes or a calendar hour.

**Options.** Sliding window (sorted-set per client, O(log n) per call, trims old entries) versus
**fixed bucket** `epoch // 3600` (one `INCR`, exact reset time).

**Decision.** Fixed bucket. A client can burst up to 200 calls across a boundary, which is
acceptable for a 4-hourly snapshot consumer; in exchange the limiter is one Redis command and the
client gets an exact `Retry-After`.

**Consequences.** Documented in `docs/api.md`; switch to a sliding window if a client ever abuses
the boundary.

**Status.** Accepted.

---

## ADR-9 Valuation method: Moving Average

**Context.** Steel and castings have volatile prices; the finance team wants a cost that reflects
current purchase prices without FIFO layer explanations.

**Options.** FIFO (precise layers, harder to explain, sensitive to back-dated entries) versus
**Moving Average** (one rate per item-warehouse, stable COGS, standard in Indian manufacturing).

**Decision.** Moving Average, set per item (`valuation_method` on every demo item) and attempted
globally in Stock Settings (ERPNext refuses the global change once ledgers exist, handled in
`setup_company_settings`).

**Consequences.** Back-dated receipts trigger a repost of later entries (ERPNext handles this);
inter-branch transfers carry the HQ average rate to Delhi (ADR-10).

**Status.** Accepted.

---

## ADR-10 Inter-branch transfer at cost; IGST applies because GSTINs differ

**Context.** HQ (27) to DC (07) is a movement between "distinct persons" under GST, so it is a
taxable supply even inside one company.

**Options.**
1. Stock Entry only, no tax document - simplest, non-compliant.
2. **Stock Entry (Material Transfer via `DEL Goods In Transit - HML`) at Moving Average cost for
   the books, plus the GST document for the movement** (tax invoice / delivery challan with IGST
   on the open-market or cost-plus value per Rule 28, e-way bill as applicable). In ERPNext this is
   modelled with an internal customer / supplier pair representing the Delhi registration
   (`selling.py` already exempts `is_internal_customer` from the DN / SI gates).

**Decision.** Option 2 for the design; the demo posts the Stock Entry only. Transfer value for
management accounts = cost (no internal profit, no elimination needed).

**Consequences.** The internal customer/supplier, IGST posting and ITC claim at Delhi are
**Designed only - verify with the client's CA** before go-live.

**Status.** Proposed (stock movement built; tax document not built).

---

## ADR-11 SP-IMPELLER BOM per batch of 5

**Context.** One impeller consumes 0.2 of a casting. `Nos` is a whole-number UOM in ERPNext
(`must_be_whole_number`), so a BOM line of 0.2 Nos is rejected.

**Options.** Change the casting UOM to a fractional unit (wrong physically), create a sub-item
"casting slice", or **set the BOM quantity to 5** (1 casting + 10 bolts per 5 impellers).

**Decision.** BOM `quantity = 5` (`demo_data.BOMS`). Capacity check divides BOM operation minutes
by BOM quantity (`manufacturing.get_machine_hours_per_unit`).

**Consequences.** Work Orders for impellers should be in multiples of 5; smaller orders get
proportional material with rounding - acceptable for a machined spare.

**Status.** Accepted.

---

## ADR-12 Workstation second shift starts at 14:01

**Context.** Two shifts 06:00-14:00 and 14:00-22:00. ERPNext's Workstation working-hours overlap
validation treats the boundary as inclusive, so 14:00-22:00 is rejected as overlapping 06:00-14:00.

**Options.** Single 06:00-22:00 window (loses the shift split in Job Card scheduling) versus
**14:01-22:00** (one minute of unschedulable time per day).

**Decision.** `demo_data.WORKSTATIONS` uses 14:01. HRMS Shift Types keep the real 14:00-22:00 for
attendance.

**Consequences.** Job Card time slots lose one minute per day (0.1 %); documented so nobody "fixes"
it back and hits the validation.

**Status.** Accepted.

---

## ADR-13 Employee user permissions scoped to self-service DocTypes

**Context.** ERPNext links an Employee to a User by creating a User Permission (allow = Employee,
"apply to all document types"). For an operator that is the right default. For the demo managers
(Operations Head, Finance Director, Sales Manager, HR Manager, QC) it hid every record that links
*another* employee: a Production Audit whose `inspector` is not the reviewer, an Employee Checkin for
a shop-floor worker, another employee's Leave Application (QA DEF-03) - the escalation workflow could
only be completed by Administrator.

**Options.** (a) Remove the Employee permission for managers altogether (they then see every
employee's Salary Slip / Expense Claim). (b) Give every manager System Manager (no). (c) Keep the
permission but restrict it to the self-service DocTypes where "only my own record" is the intent.

**Decision.** (c). `demo_hr_finance.scope_employee_user_permissions` replaces the catch-all row
with one User Permission row per DocType in `EMPLOYEE_SELF_SERVICE_DOCTYPES` (Employee, Salary
Slip, Expense Claim, Employee Tax Exemption Declaration) - Frappe stores "applies to these DocTypes
only" as one row per `applicable_for`. Applied to every HML employee with a `user_id`, on install
and on every re-run; ERPNext does not re-create the catch-all row because it only acts when
`user_id` changes.

**Consequences.** Managers read / review documents of other employees according to their roles
(Production Audit via Operations Head, Employee Checkin via HR Manager, Leave Application via Leave
Approver); payslips, expense claims and tax declarations remain visible only to their owner (plus
HR / Accounts roles). Leave Application is deliberately *not* in the list: approvers must see
others' applications; HRMS already restricts employees to their own via `leave_approver` / owner
checks. Adding a new self-service DocType means adding it to the tuple and re-running the step.

**Status.** Accepted.

---

## ADR-14 Prices are locked at the Sales Order; stacked rule discounts are additive

**Context.** ERPNext re-runs the pricing engine on every mapped document at that document's
quantity. A Sales Order line of 60 impellers earns the volume rule (>= 51); a partial Delivery Note
of 30 is re-priced without it, and the Sales Invoice mapped from that delivery then fails ERPNext's
over-billing check against the Sales Order (QA DEF-05). Setting "Ignore Pricing Rule" after mapping
does not help: on the next save ERPNext *removes* the recorded rules and resets the rate to list
price (`remove_pricing_rule_for_item`). The documentation also described stacked rules as
compounding, while the engine adds percentages (QA DEF-10).

**Options.** Over-billing allowance in Accounts Settings (hides the problem, allows real
over-billing); `validate_applied_rule` on every rule (warns only); copy the Sales Order rates onto
the Delivery Note / Sales Invoice rows before the controller validates (chosen).

**Decision.** `selling.lock_rates_to_sales_order`, wired as `before_validate` on Delivery Note and
Sales Invoice (it must run *before* the ERPNext controller's `validate`, which hosts the pricing
engine, totals and the "Maintain Same Rate" check - a `validate` doc_event runs after it). Rows
referencing a Sales Order row (`so_detail`) copy `price_list_rate`, `discount_percentage`,
`discount_amount`, `margin_type`, `margin_rate_or_amount` and `rate` from it; invoice rows that
only reference a Delivery Note row copy from that (already locked) row. `pricing_rules` is cleared
on the copy and `ignore_pricing_rule` is set on the document, so the engine neither re-evaluates
nor removes anything on later saves; the Sales Order row keeps the audit record of the rules that
produced the price. Selling Settings "Maintain Same Rate Throughout Sales Cycle" = Stop is switched
on as the standard safety net (`demo_data.setup_company_settings`). The draft invoice is created
server-side on Delivery Note submit with `ignore_permissions` on the mapped target, so a Sales User
or Warehouse Manager who may not create invoices still triggers it (DEF-06); Sales User gets read
on Sales Invoice to see it. `get_rule_rate` now adds the percentages of stacked rules exactly as
ERPNext does (5 + 8 + 10 = 23 %), compounding only a rule flagged `apply_discount_on_rate`.

**Consequences.** Partial deliveries and their invoices carry the ordered price; the over-billing
check passes. Limitation: on a Delivery Note / Sales Invoice that carries Sales Order rows, a row
added by hand without an order reference is priced at list price (the engine is off for the whole
document) - add the item to the Sales Order instead. Returns are untouched. Price changes after
order confirmation are made on the Sales Order (amend) and flow from there.

**Status.** Accepted.

---

## ADR-15 Domain modules mirroring the kaynes app; Custom Fields as module custom/ JSON

**Context.** The app grew inside four broad modules (Horizon Operations, Quality, Finance,
Integration) plus `setup/`, `tasks/`, `api/` and `client/` packages. Horizon Operations alone held
buying, selling, stock, manufacturing and projects code, and Custom Fields were a 440-line Python
dict. The team's reference app (kaynes) uses one Frappe module per ERPNext domain, each owning its
`custom/` customization JSON, doctypes, reports, print formats and scheduler jobs.

**Options.** Keep the layout; split only Horizon Operations; or adopt the kaynes layout fully.

**Decision.** Adopt the kaynes layout. Fifteen modules (`modules.txt`): Horizon Setup, Core, Buying,
Selling, CRM, Stock, Manufacturing, Quality Management, Projects, HR, Payroll, Accounts, Assets,
Integrations, Workflow. Files moved with `git mv`. Custom Fields are Export-Customizations JSON per
DocType in the owning module's `custom/` (`sync_on_migrate: 1`, `custom_perms: []`, every field
carries its `module`); `horizon_setup.custom_fields.setup_custom_fields()` calls
`frappe.modules.utils.sync_customizations("horizon_erp")` on install because Frappe only syncs them
after `after_install`. Scheduler jobs sit in `<module>/tasks.py` (stock, buying,
quality_management, accounts, core) with the shared `@horizon_job` wrapper in
`horizon_core/jobs.py`. Purchase Receipt QC-hold hooks moved from buying to
`horizon_stock/purchase_receipt.py` (kaynes keeps receipt logic in stock). The Approvals workspace
lives in Horizon Accounts (it is the Finance Director's queue). Existing sites are migrated by
`patches/v1_0/restructure_modules.py` (`[pre_model_sync]`). The public API keeps the short alias
`get_inventory_snapshot` (now pointing at `horizon_erp.horizon_integrations.inventory_api`) and
re-export shims at `horizon_erp.api.inventory` / `horizon_erp.api` so published URLs do not change.

**Consequences.** Code is found where an ERPNext consultant expects it; customizations can be
re-exported from Customize Form into the right module; the module filter on desk lists is
meaningful. Costs: one-time migration patch, longer dotted paths, and the legacy `api/` shim
package must stay until every integration uses the short alias. `tests/test_module_structure.py`
guards module/file/DB agreement, hook paths and the API aliases.

**Status.** Accepted.

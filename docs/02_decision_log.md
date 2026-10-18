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

## ADR-2 Receipt = Purchase Receipt draft, GRN = Purchase Receipt submit (QC Hold optional)

**Context.** The brief asks for "Receipt -> Quality Check -> GRN -> Inventory Update", "only GRN
submission updates inventory" and an inspection SLA of 4 hours from receipt, i.e. seemingly a
fourth document after the receipt.

**Options.**
1. New custom "GRN" DocType after Purchase Receipt - duplicates Purchase Receipt (stock ledger,
   valuation, landed cost, returns, invoice linkage all live on PR), breaks Purchase Invoice
   `pr_required`, and every standard report ignores it.
2. Purchase Receipt is the GRN and the state "received but not released" is a warehouse: post the
   receipt into `HQ QC Hold - HML`, auto-transfer the accepted qty to Raw Materials (the original
   decision, 16-Oct-2026). Stock is posted *before* inspection, which contradicts "only GRN
   updates inventory", and it adds a second stock movement per receipt.
3. **Standard ERPNext flow**: the Purchase Receipt *draft* is the receipt (its `creation` is the
   receipt time; nothing is posted), the Quality Inspection is raised against it, and *submitting*
   the Purchase Receipt is the GRN - the only step that posts stock. Stock Settings *Action if
   Quality Inspection is not Submitted* = **Stop** guarantees no stock before inspection.

**Decision.** Option 3 (revised 17-Oct-2026). Settings: QI not submitted = Stop, QI rejected =
**Warn** (a fully or partly rejected lot is still booked, with the qty in `rejected_qty` posted to
`HQ Rejected - HML`), *Allow QI after purchase* = 0. `purchase_receipt.before_validate_purchase_receipt`
defaults `HQ Rejected - HML` as the rejected warehouse; `on_submit_purchase_receipt` raises the draft
Purchase Return and, if a submitted Purchase Invoice exists, the draft Debit Note for `rejected_qty`.
The QC Hold routing of option 2 is kept as an **optional mode** (Stock Settings *Route Inspected
Receipts via QC Hold* / `horizon_use_qc_hold`, or the same key in `site_config.json`; default off) for
a site that wants the received-but-uninspected lot visible as stock.

**Consequences.** One stock movement per receipt; items in Raw Materials are always inspected. A lot
waiting for inspection is visible as a draft Purchase Receipt, not as stock. The inspection SLA is measured from Purchase Receipt `creation` (draft
saved) to Quality Inspection `creation` (*Quality Metrics*). The `HQ QC Hold - HML` warehouse stays in
the tree, used only by the optional mode. Supplier performance uses the standard *Supplier
Scorecard* (Horizon Quality 50 / Delivery 30 / Price 20), complemented by the custom *Supplier
Quality Scorecard* report for price trend and blacklist.

**Status.** Accepted (revised 17-Oct-2026; supersedes the QC Hold default).

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
`horizon_stock/purchase_receipt.py` (kaynes keeps receipt logic in stock). The Finance Director's
queue workspace lives in Horizon Accounts (see ADR-16 for the current workspace set). Existing sites are migrated by
`patches/v1_0/restructure_modules.py` (`[pre_model_sync]`). The public API keeps the short alias
`get_inventory_snapshot` (now pointing at `horizon_erp.horizon_integrations.inventory_api`) and
re-export shims at `horizon_erp.api.inventory` / `horizon_erp.api` so published URLs do not change.

**Consequences.** Code is found where an ERPNext consultant expects it; customizations can be
re-exported from Customize Form into the right module; the module filter on desk lists is
meaningful. Costs: one-time migration patch, longer dotted paths, and the legacy `api/` shim
package must stay until every integration uses the short alias. `tests/test_module_structure.py`
guards module/file/DB agreement, hook paths and the API aliases.

**Status.** Accepted.

## ADR-16 Workspaces mirror the assignment sections

**Context.** Six unrelated top-level workspaces (Horizon Quality, Warehouse, Approvals, Inventory
Health, Sales Pipeline, Production) sat between the standard ones in the sidebar; one had no icon,
card titles repeated a "HORIZON" prefix and truncated, the Stock Value by Warehouse bar chart cut
its labels to "HQ ..." and a Stock Movement chart summed signed quantities into a meaningless spike.
Nothing told a reviewer what each workspace was for or in which order to read them.

**Options.** Polish the six; fold everything into the standard ERPNext workspaces; or one Horizon
home with one child workspace per assignment section.

**Decision.** One public parent *Horizon ERP* (Horizon Core, sequence 0.5 so it is first in the
sidebar) and ten children (`parent_page = "Horizon ERP"`), in brief order: Setup & Masters, Selling,
Buying, Inventory, Manufacturing, Quality, Projects & Assets, HR & Payroll, Accounts & Finance,
Integrations. Every workspace has an icon from the desk sprite, a header, a paragraph naming the
assignment section and docs/01 matrix IDs, the process flow line, its KPIs, shortcuts in process
order and link cards grouped Transactions / Masters / Reports. The home carries the six headline
KPIs, a URL shortcut to every child and the three demo flows with their document names. Number Card
`label`s are short Title Case without the prefix (names stay `Horizon ...` for the fixture filter);
at most two charts per workspace and only ones that draw something with the demo data. Stock Value
by Warehouse became a `Custom` chart backed by the `Horizon Stock Value by Warehouse` Dashboard Chart
Source (labels = `warehouse_name`, empty warehouses skipped, read through `frappe.get_list` so
Warehouse User Permissions apply) shown full width; Stock Movement 90d was dropped; Audit Score Trend
is a monthly bar (a line through empty days read as a drop to 0). `patches/v1_0/redesign_workspaces.py`
(`[post_model_sync]`) deletes the five replaced workspaces and the dropped chart on existing sites.
Dashboard Charts are no longer fixtures: fixture import validates and `DashboardChart.validate`
rejects a standard chart whenever `developer_mode` is off (production, and any migrate that runs a
patch); they ship only as module JSON, which `bench migrate` syncs without validation.

**Consequences.** A reviewer can walk the implementation module by module from one page; each
workspace explains itself. Costs: child titles keep the `Horizon` prefix (a workspace title must not
clash with the standard *Selling*, *Buying*, ... routes), so the longest ones are truncated in the
sidebar; the content blocks resolve cards / charts by the child-row *label* (desk
`blocks/block.js`), which `setup_dashboards` and `test_dashboards` now check.

**Status.** Accepted.

## ADR-17 Customer created from the qualified Opportunity, before quotation pricing, not at Sales Order

**Context.** ERPNext v15 creates the Customer of a Lead only when a Sales Order is made from the
Quotation (`quotation._make_customer` -> `create_customer_from_lead`), using the Selling Settings
default Customer Group / Territory (empty on horizon.local, so the conversion fails as *Mandatory
Missing*) and no GSTIN, billing address, credit limit or payment terms. Until then the Quotation is
addressed to the Lead: the Premium 5 % rule (keyed on Customer Group) does not fire, GST is computed
without the customer's GSTIN / state (a Tamil Nadu buyer got the in-state CGST + SGST template from
the Lead), and credit control and due dates have nothing to work on.

**Options.** (a) Keep the standard: create the Customer by hand before quoting. (b) Capture the
customer data on the Lead and convert early. (c) Capture it on the Opportunity - the stage at which
a lead is qualified - and create the Customer from there before the first quotation is priced.

**Decision.** (c). Customer details are captured on the qualified Opportunity; the Customer is
created before quotation pricing, not at Sales Order; leads that never qualify create no customer
and the Lead stays light (standard fields only). The Opportunity reuses standard `customer_group`
(Property Setter `depends_on = eval:doc.party_name` so it shows for Lead opportunities), `city`,
`state`, `country`, `territory`, `company` (copied from the Lead by `Opportunity.map_fields`) and adds
GST Category, GSTIN, billing address line 1, pincode, credit limit, payment terms (Net 30) and the
read-only `horizon_customer`. `ensure_customer_from_opportunity` (form button, or automatically from
`Quotation.before_validate`) is idempotent and builds the Customer with ERPNext's own Lead mapper so
`lead_name` is set: the Lead turns Converted, its Contact / Address move to the Customer and the
Sales Order path finds this Customer instead of creating a second one. `before_validate` runs before
the controller's `validate` -> `set_missing_values` -> pricing rules (verified by trace: hook first,
then `apply_pricing_rule_on_items` with `quotation_to = Customer`), so the first save already carries
Premium pricing, the customer's GSTIN / place of supply and the IGST or CGST + SGST template. The
Opportunity keeps `opportunity_from = Lead`: funnel reports stay Lead -> Opportunity -> Quotation,
ERPNext's Opportunity -> Quotation mapper keeps working unchanged (it copies `opportunity_from` into
`quotation_to`, which the hook then switches), and the detail section stays visible for reference.
Permission: the caller needs Customer *create* or the Sales User / Sales Manager role; Customer,
Address and Contact links are then written with `ignore_permissions`. A Lead quotation without
details is not blocked: it stays on the Lead with a warning that Premium / GST / credit will not apply.

**Consequences.** One data-entry point for the commercial terms; the first quotation is priced and
taxed like every later one. Costs: a Quotation typed directly against a Lead (no Opportunity) is only
switched once that Lead has a Customer; ERPNext's standard *Create > Customer* on the Opportunity is
replaced by the Horizon action; a billing state different from the organisation state must be typed
over the State copied from the Lead.

**Status.** Accepted.

## ADR-18 Agreed rates above the rule rate are kept; the customer's agreed price is a grossed-up customer Item Price

**Context.** The Opportunity Item `rate` is mandatory and free-typed. DEF-23 re-priced every mapped
row to the price list + pricing-rule rate because a low estimate read as a discount. The user then
typed **2,00,000** for HZ-PUMP-100 (list 1,85,000) because the customer had agreed a higher price,
and the quotation came out at 1,85,000. Two ERPNext v15 behaviours matter:

- On a row **without** a pricing rule, a rate above `price_list_rate` is stable: `calculate_margin`
  stores it as `margin_type = "Amount"`, `margin_rate_or_amount = rate - list` (verified: insert,
  re-save, reload + save all keep 2,00,000).
- On a row **with** a rule (Premium 5 %, Components 3 %, Q4 Spares, volume) the engine re-applies
  the rules on every `validate` (`set_missing_item_details` -> `apply_pricing_rule_on_items`, with the
  stored `pricing_rules` or a new search when none are stored): a posted 1,80,000 or 2,00,000 for
  Tata Precision Works (Premium) was saved as 1,75,750, even with a margin on the row
  (`calculate_margin` keeps only margins defined on the rules).

**Decision 1 - Option B.** The Horizon `make_quotation` mapper compares the Opportunity rate with
the row's rule rate for the quotation's party / qty / date (`get_rule_rate` on the
`price_list_rate` / `pricing_rules` the mapper fetched). The rate is read from the Opportunity Item,
because ERPNext's mapper has already run the rules on the row (the Opportunity's `customer_group`
is mapped too). If the Opportunity rate is above the rule rate, it is kept (`selling.set_agreed_rate`)
and recorded in the new Custom Field **`horizon_agreed_rate`** ("Agreed Rate", Quotation Item and
Sales Order Item, editable, copied to the Sales Order by fieldname). `price_list_rate` stays the
list price. A row without rules uses
ERPNext's own margin representation. A row with rules gets `discount_percentage = 0` and
`discount_amount = list - rate` (negative above the list price): `calculate_item_values` then gives
`rate = price_list_rate - discount_amount`. A lower Opportunity rate is re-priced to the rule rate and
announced (DEF-23 behaviour). A row without an Item Price keeps the Opportunity rate.
`overrides/selling_controllers.py` (`override_doctype_class` for Quotation and Sales Order) wraps only
`apply_pricing_rule_on_items`: after ERPNext applied the rules, the row's `horizon_agreed_rate` is
put back when it is above the resulting rate. That is the one point ahead of India Compliance's
`validate` (taxable values) where the rate can be fixed. Re-imposing it in a later `validate` hook
would leave GST values stale. Only the explicit field counts. Keeping *any* posted rate above the
rule rate was tried and rejected: server / API documents that post the list price as `rate` lost
their rule discounts (the 8 % volume Sales Order stayed at 1,000; a Lead row at list kept 1,00,000
after the switch to Premium). Those rows are priced exactly as in standard ERPNext, and a typed
rate below the rule rate is still reverted (DEF-13 unchanged). `validate_discounts` syncs the field
(`sync_agreed_rate`). A rate typed on a row without rules that stays above the rule rate becomes the
new agreed rate. At or below the rule rate the field is cleared and the row is an ordinary,
possibly discounted, row. `validate_discounts`
already reads a rate above the rule rate as 0 % extra discount, so no approval is needed. No
`price_list_rate` is edited and `ignore_pricing_rule` is not set, so the ad-hoc pricing guards do
not fire for a Sales User. On the Lead -> Customer switch, `reset_rule_priced_rows` only clears rows
at their rule rate, so the agreed rate survives and is kept against the Customer's Premium rule. The
Sales Order copies the row and keeps it the same way. Delivery Note / Sales Invoice are locked to
the Sales Order (ADR-14).

**Decision 2 - customer agreed Item Price (kaynes `CustomQuotation.create_item_price` pattern).** On
`Quotation.on_submit` with `quotation_to = Customer`, every row whose rate is above its rule rate
creates or updates a customer-specific Item Price on the quotation's selling price list
(`customer`, `item_code`, `uom`, `valid_from = transaction_date`). The next quotation or Sales Order
for that customer starts from it. Options for the Premium customer, whose 5 % Customer Group rule
also applies to a customer Item Price:

- (a) **Gross-up** `price_list_rate = (agreed + rule discount amounts) / (1 - rule discount % / 100)`,
  using the Price rules on the agreed row read with `get_rule_terms` (the same reading `get_rule_rate`
  uses, additive as in ADR-14), rounded to currency precision and checked to net back exactly.
  1,80,000 / 0.95 = **1,89,473.68**, and 5 % off gives **1,80,000.00**. A Standard customer has no
  rule: 2,00,000 is stored as is.
- (b) A customer-specific "Rate" Pricing Rule with higher priority. Rejected. PR-PREMIUM-5 has
  `apply_multiple_pricing_rules`, so ERPNext stacks every matching rule (`get_pricing_rules` ->
  `apply_multiple_pricing_rules` is true when *any* match has the flag). The result then depends on
  the order the rules are applied in: a Rate rule resets the discount only if applied last, and
  `apply_pricing_rule_on_items` writes the Rate rule's rate into `price_list_rate`, which no Item
  Price backs, so `validate_price_list_rates_untouched` would block Sales Users. It would also add a
  Pricing Rule per customer and item, created with elevated rights.
- (c) An Item Price at the agreed rate with the group rule applied on top. Rejected: the Premium
  customer would net 1,71,000, not 1,80,000.

(a) is chosen. ERPNext selects a customer's own Item Price before the general one and, among those
valid on the date, the newest `valid_from` (`get_item_details.get_item_price`). The pricing rule
still applies and is recorded on the row. `get_rule_rate` reproduces the net, so `rule_rate` equals
the agreed rate and there is 0 % extra discount. Evidence: `test_premium_agreed_rate_kept_recorded_and_reused`
(fresh quotation: price list rate 1,89,473.68, discount 5 %, rate 1,80,000.00, rule rate 1,80,000.00,
no approval; another Premium customer still gets 1,75,750 and a Standard one 1,85,000).
`validate_price_list_rates_untouched` now accepts only general prices and the document customer's
own prices, so one customer's agreed price is no list price for another.

Idempotence and history: if the customer's active price already equals the grossed-up value,
nothing is written. A price with the same `valid_from` is updated in place. Item Price tracks
changes, and the replaced rate / note is kept in a machine-readable trailer of `note`, because
Version stores formatted values. A later date creates a new Item Price, so history is kept by
`valid_from`. A newer agreed price is never overwritten by an older quotation. Rows at or below the
rule rate, rows priced by a "Rate" rule, and quotations in a currency other than the price list's
create nothing. The `note` starts with `Quotation <name>: `. ERPNext overwrites `reference` with the
customer, so `note` is the link. `on_cancel` deletes the prices the quotation created and restores
the ones it updated. A timeline comment and a message list the prices. Item Prices are written with
`ignore_permissions` (Sales Users submit quotations but hold no Item Price rights). A failure rolls
back to a savepoint, logs an Error Log and never blocks the submit (kaynes pattern).

Lead quotations create nothing: there is no customer yet. A qualified Lead quotation is moved to its
Customer before submit (ADR-17) and is handled. A quotation that stays on the Lead gets its Customer
only at Sales Order time (`quotation._make_customer`). The agreed price is recorded by the next
quotation submitted for that Customer. Sales Order submit does **not** record prices: the quotation
is the commercial agreement, as in kaynes, and a Sales Order typed above the rule rate keeps its rate
without becoming the customer's price.

**Consequences.** Agreed higher prices survive save, submit, the Lead -> Customer switch and the Sales
Order, without approval or manager rights. The customer's next quotation nets the agreed price under
the same rules. Costs and limits:

- The gross-up bakes in the rules active on the agreed row. If they change (rule edited, Q4 Spares
  expires, volume tier not reached at another quantity), the net moves by that rule's effect, as it
  would for any list price. The Item Price note names the rules and the percentage, so a Sales
  Manager can re-base it.
- The customer's quotations show the grossed-up figure as their Price List Rate (1,89,473.68, then
  5 %).
- Changing qty / UOM / price list on the form re-runs the pricing rules in the browser. The rate
  shown drops to the rule rate until save; the server then restores the agreed rate. To give up an
  agreed rate, clear *Agreed Rate* on the row.
- On a Lead quotation the mapper compares against the Lead's rule rate (list). An Opportunity rate
  between the Premium rule rate and the list price is therefore re-priced, and then gets the Premium
  rate after the switch, which favours the customer.
- One Custom Field per row table (`bench migrate`).
- Two Quotation / Sales Order controller classes are overridden. Another app overriding the same
  DocTypes would need to subclass these.

**Status.** Accepted.

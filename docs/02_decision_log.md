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

**Decision.** Option 2. `buying.on_submit_purchase_receipt` moves accepted qty from QC Hold to the
item's default warehouse and raises the Purchase Return / Debit Note for `rejected_qty`.

**Consequences.** Stock is visible (and valued) in QC Hold between receipt and release, which is
the truth. Material in QC Hold is not available to Work Orders because it is not in Raw Materials.
The receipt warehouse must be QC Hold: `buying.validate_purchase_receipt` enforces it - every
Purchase Receipt row whose Item requires inspection before purchase is routed to `HQ QC Hold - HML`
(with `HQ Rejected - HML` defaulted as the rejected warehouse) and the user is told which rows were
moved; rows for items without inspection keep their warehouse (follow-up closed).

**Status.** Accepted.

---

## ADR-3 Extend standard Quotation / Delivery Note / Purchase Receipt instead of new DocTypes

**Context.** The brief says "Create a Quotation DocType", "Delivery Note DocType", "Purchase Receipt
DocType".

**Options.** New DocTypes versus Custom Fields + hooks on the standard ones.

**Decision.** Custom Fields in code (`setup/custom_fields.py`, applied on install / migrate, not as
fixtures) plus `doc_events` hooks. Quotation Item gets `available_qty`, `mfg_lead_days`,
`expected_delivery_date`, `rule_rate`, `discount_over_rule_pct`; Delivery Note gets
`customer_signature`, `received_by`, `deviation_notes`, `shipment_decision`; Quality Inspection
gets `qc_result`, `rejection_reason`, `evidence_required`, `rework_work_order`.

**Consequences.** Pricing rules, taxes, stock ledger, GST e-invoicing, print formats and every
standard report keep working. Fields sit on a "Horizon" tab so standard layouts are untouched.
Trade-off: custom fields on busy DocTypes must be re-verified at each ERPNext minor upgrade
(`after_migrate` re-applies them idempotently).

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
3. **Own decorator** `api/rate_limit.py`: client = authenticated user (API key owner), Redis
   `INCR` + `EXPIRE`, 429 JSON body, `Retry-After` / `X-RateLimit-*` headers through a duck-typed
   `frappe.local.rate_limiter`, `on_exceed` callback writes the *Inventory API Log* row.

**Decision.** Option 3. Limit configurable via `site_config.json` `horizon_api_rate_limit`.

**Consequences.** About 170 lines to own; Frappe upgrades that change `process_response` header
handling must be re-tested (`api/test_inventory_api.py` covers it).

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

# 08 - Screenshot guide for the annotated PDF and the demo recording

All URLs are relative to the dev server `http://localhost:8001` (site `horizon.local`). Open the URL,
wait for the page to settle, capture the full browser window, and add the one-line annotation given
in the last column as a caption. Document names below were read from the site on 2026-10-16 and are
stable (the demo data is idempotent; `setup_all` never renumbers submitted documents).

## Logins

| Login as | Password | Why |
| --- | --- | --- |
| `Administrator` | `Horizon@Test123` | Default for every screen unless the table says otherwise |
| `rajesh@horizon.local` | `Horizon@Test123` | Finance Director (Level 3 approver, Accounts Manager) |
| `procure@horizon.local` | `Horizon@Test123` | Procurement Manager (Level 2), Purchase User |
| `dept.head@horizon.local` | `Horizon@Test123` | Department Head (Level 1) |
| `priya@horizon.local` | `Horizon@Test123` | Operations Head, Manufacturing / Stock Manager |
| `qc@horizon.local` | `Horizon@Test123` | Quality Inspector / Quality Manager |
| `amit@horizon.local` | `Horizon@Test123` | Sales Manager (discount approver) |
| `wh.delhi@horizon.local` | `Horizon@Test123` | Warehouse Manager restricted to *Delhi DC - HML* by a User Permission |
| `neha@horizon.local` | `Horizon@Test123` | HR Manager |

Use a private window per user so the sessions do not mix. The same screen is only re-captured as a
second user where the table says so.

## Workspaces (desk sidebar, *Horizon ERP* and its children)

| Route | Workspace | Assignment section |
| --- | --- | --- |
| `/app/horizon-erp` | Horizon ERP (home) | Overview, headline KPIs, module index, the three demo flows |
| `/app/horizon-setup-&-masters` | 1. Setup & Masters | Structure, CoA / cost centres, permissions (5.1-5.2) |
| `/app/horizon-crm` | 2. CRM | Lead-to-quote: Lead -> Opportunity (customer details) -> Quotation, Customer created on the Quotation (5.3, ADR-17) |
| `/app/horizon-selling` | 3. Selling | Pricing and discounts, order to delivery (5.4-5.5) |
| `/app/horizon-buying` | 4. Buying | Supplier quality and purchase approval (5.6) |
| `/app/horizon-inventory` | 5. Inventory | Receipt / inspection / GRN, reorder and MRP, inventory dashboard (5.7-5.8) |
| `/app/horizon-manufacturing` | 6. Manufacturing | BOM, production planning and capacity (5.9-5.10) |
| `/app/horizon-quality` | 7. Quality | Quality control, Production Audit, quality vs deadline (5.11, DV) |
| `/app/horizon-projects-&-assets` | 8. Projects & Assets | Projects, assets (5.12-5.13) |
| `/app/horizon-hr-&-payroll` | 9. HR & Payroll | Attendance and leave, payroll (5.14-5.15) |
| `/app/horizon-accounts-&-finance` | 10. Accounts & Finance | Bank and payments, budgets, GST (5.16-5.18) |
| `/app/horizon-integrations` | 11. Integrations | Inventory API, scheduled jobs (5.19 API / SJ) |

Capture `/app/horizon-erp` first as the title slide of the demo.

## A. Structure (configuration design, docs/01 section 1-3)

| # | Screen | URL | Login | Annotation |
| --- | --- | --- | --- | --- |
| 1 | Company | `/app/company/Horizon%20Manufacturing%20Ltd` | Administrator | One legal entity, abbreviation HML, INR, default payment terms *Net 30*, chart of accounts with Indian GST heads |
| 2 | Company addresses with two GSTINs | `/app/address?is_your_company_address=1` then open `Horizon%20HQ%20Mumbai-Office` and `Horizon%20DC%20Delhi-Office` | Administrator | One company, two registrations: 27AABCU9602H1Z9 (Maharashtra) and 07AABCU9602H1ZB (Delhi); inter-branch transfers are GST documents |
| 3 | Branch dimension | `/app/accounting-dimension/Branch` | Administrator | *Branch* is an Accounting Dimension, mandatory on P&L accounts, so location P&L comes from one ledger (ADR-1: not two companies) |
| 4 | Branch list | `/app/branch` | Administrator | Two branches: Mumbai HQ (plant) and Delhi DC (distribution) |
| 5 | Cost-centre tree | `/app/cost-center/view/tree?company=Horizon%20Manufacturing%20Ltd` (expand *Manufacturing - HML*) | Administrator | Product-line cost centres Equipment / Spares / Components plus *Mfg - Shared* allocated 50/30/20 by the monthly job |
| 6 | Warehouse tree | `/app/warehouse/view/tree?company=Horizon%20Manufacturing%20Ltd` (expand *Mumbai HQ - HML* and *Delhi DC - HML*) | Administrator | Receiving goes to *HQ Raw Materials* (PR submit = GRN); *HQ QC Hold* only in the optional QC Hold mode; rejections to *HQ Rejected*, inter-branch stock via *Goods In Transit*; no sellable stock without an accepted inspection |
| 7 | Chart of accounts | `/app/account/view/tree?company=Horizon%20Manufacturing%20Ltd` | Administrator | Standard Indian CoA; GST input/output heads per registration, no custom accounts needed |
| 8 | Item with criticality and reorder level | `/app/item/RM-WELD-ROD` (Inventory tab, *Auto re-order* table) | Administrator | Custom field *Criticality* (A/B/C) drives API filtering and reorder; reorder level 50 / qty 100 at HQ Raw Materials; batch-tracked |
| 9 | Serialised item | `/app/item/HZ-PUMP-100` | Administrator | Finished pumps are serialised; `use_serial_batch_fields` on; BOM-HZ-PUMP-100-001 is default |
| 10 | Role matrix | `/app/role-permission-manager` (DocType *Delivery Note*, then *Sales Invoice*) | Administrator | Custom DocPerm rows from `horizon_setup/roles.py`: Warehouse Manager submits Delivery Notes and reads the invoice the hook creates (QA OBS-R2-1) |

## B. Purchasing - approvals and the blacklisted sole supplier (Demo 1)

| # | Screen | URL | Login | Annotation |
| --- | --- | --- | --- | --- |
| 11 | Workflow definition | `/app/workflow/Horizon%20PO%20Approval` | Administrator | Draft -> Pending Dept Head -> Pending Procurement Manager -> Pending Finance Director -> Approved; level is forced by amount or by a blacklist override |
| 12 | Supplier master, blacklisted | `/app/supplier/ABC%20Supplies` | Administrator | *Is Blacklisted* ticked; a PO on this supplier is blocked unless *Blacklist Override* with a reason is set |
| 13 | 3-level approval, INR 7 L | `/app/purchase-order/PUR-ORD-2026-00003` (scroll to the timeline) | rajesh@horizon.local | Bharat Castings, INR 700 000: workflow history shows dept.head -> procure -> rajesh (Finance Director) before Approved |
| 14 | Blacklist override PO | `/app/purchase-order/PUR-ORD-2026-00005` (Horizon tab + timeline) | procure@horizon.local | INR 12 000 to ABC Supplies with *Blacklist Override* and reason "Sole stockist of E6013 rods in Thane"; Level 3 was forced despite the low amount |
| 15 | Supplier Exception Log | `/app/supplier-exception-log/SEL-00001` | rajesh@horizon.local | The override is written to an audit log the Finance Director is notified about; cannot be edited by the requester |
| 16 | PO awaiting action | `/app/purchase-order/PUR-ORD-2026-00004` | procure@horizon.local | *Pending Procurement Manager*: the Actions button shows Approve / Reject only to the role that owns the state |
| 17 | Buying workspace | `/app/horizon-buying` | rajesh@horizon.local | Approval rule on the page; cards *POs Awaiting Approval*, *POs Pending Over 24h*, *Blacklist Overrides (30d)*; Pending PO by State; 24 h reminder / 48 h escalation jobs feed the queue age |
| 18 | Approval Audit Report | `/app/query-report/Approval%20Audit%20Report` | Administrator | Every transition with user, timestamp and hours in state; filter by document type or approver |
| 19 | Payment approval | `/app/payment-entry/ACC-PAY-2026-00001` | rajesh@horizon.local | *Horizon Payment Approval* workflow: payments of INR 1 00 000 or more need the Finance Director before submit (`config.PAYMENT_APPROVAL_LIMIT`) |

## C. Receiving and quality

| # | Screen | URL | Login | Annotation |
| --- | --- | --- | --- | --- |
| 20 | Purchase Receipt (GRN) with Rejected qty | `/app/purchase-receipt/PR-26-00009` (Items table: Accepted Warehouse / Rejected Warehouse columns) | procure@horizon.local | 18 to HQ Raw Materials, 2 to HQ Rejected, QI MAT-QA-2026-00007, draft return PR-26-00010 |
| 21 | Incoming Quality Inspection | `/app/quality-inspection/MAT-QA-2026-00001` | qc@horizon.local | Template *RM Steel Incoming*; readings per parameter; Stock Settings stop a submit when inspection is missing or rejected |
| 22 | In-process inspection -> rework | `/app/quality-inspection/MAT-QA-2026-00005` then `/app/work-order/MFG-WO-2026-00003` | qc@horizon.local | Job Card PO-JOB00009 (Machining, Line B) inspected with *QC Result = Rework*; the hook created draft Work Order MFG-WO-2026-00003 with `rework_of = MFG-WO-2026-00002` |
| 23 | Production Audit, low score | `/app/production-audit/PA-2026-00002` | priya@horizon.local | Score 65 on MFG-WO-2026-00002: photo mandatory, Operations Head alerted, Quality Action QA-ACT-00014 opened, Manufacture entry blocked until *Action Closed* |
| 24 | Shipment Decision | `/app/shipment-decision/SD-2026-00001` | amit@horizon.local | Quality vs deadline made explicit: *Ship Partial* 5 of SAL-ORD-2026-00003, estimated quality cost 8 000 vs delay cost 25 000, sales and quality approvers recorded |
| 25 | Delivery Note carrying the decision | `/app/delivery-note/DN-26-00002` (field *Shipment Decision*) | Administrator | The partial delivery of 5 impellers is only possible because it links SD-2026-00001 |
| 26 | Quality workspace | `/app/horizon-quality` | qc@horizon.local | Audit < 70 rule and Shipment Decision on the page; cards *Audits Today*, *Open Low-Score Audits*, *Audits Below 70 (30d)*, *QI Rejected (30d)*, *Open Corrective Actions*; monthly audit score chart; the four quality reports |
| 27 | Quality Metrics report | `/app/query-report/Quality%20Metrics` | Administrator | First-pass yield, rework cost %, defect trend, inspection SLA in one script report |
| 28 | Quality vs Deadline Conflicts | `/app/query-report/Quality%20vs%20Deadline%20Conflicts` | Administrator | Open orders whose Work Order has a low audit or rework and a delivery date inside 7 days |
| 29 | Supplier Quality Scorecard | `/app/query-report/Supplier%20Quality%20Scorecard` | Administrator | Rejection %, on-time delivery and price stability per supplier; ABC Supplies visible with its override |
| 29a | Supplier Scorecard (standard) | `/app/supplier-scorecard` | Administrator | Standard Supplier Scorecard, one per demo supplier; criteria Quality 50 / Delivery 30 / Price 20 |

## D. Manufacturing

| # | Screen | URL | Login | Annotation |
| --- | --- | --- | --- | --- |
| 30 | Multi-level BOM | `/app/bom/BOM-HZ-PUMP-100-001` (click *BOM Explorer* in the sidebar) or the tree `/app/bom/view/tree` | priya@horizon.local | Pump -> SA-MOTOR-01 / SA-HOUSING-01 / SA-DRIVE-01 sub-assemblies -> raw material; operations on Line A / Line B |
| 31 | BOM Explosion with Lead Time | `/app/query-report/BOM%20Explosion%20with%20Lead%20Time?bom=BOM-HZ-PUMP-100-001` | Administrator | Exploded leaf items vs stock on hand with procurement lead time per item; the longest lead time is the real promise date |
| 32 | Work Order with job cards | `/app/work-order/MFG-WO-2026-00001` (Operations table, *Job Cards* connection) | priya@horizon.local | Completed order for 2 pumps; job cards per operation; In-process inspection required at Assembly |
| 33 | Manufacturing workspace | `/app/horizon-manufacturing` | priya@horizon.local | Flow SO -> Production Plan -> Work Order (capacity check) -> Job Card + QI -> Production Audit; *Work Orders In Progress*, *Overdue*, *Line Utilisation Today %*; Work Orders by Status |
| 34 | Capacity Utilisation and Sequence | `/app/query-report/Capacity%20Utilisation%20and%20Sequence` | Administrator | Top of page: one card per line with today's free hours (e.g. *Line A free today (of 14.4 h, 2.0 h booked)* = 12.4 h), *Today - line status* table (capacity / booked / free / running WOs / Free-Busy-Overloaded), then the suggested Work Order sequence, utilisation % per line per day chart and the day-by-line rows (16 h shift net of downtime 10 % / 15 %) |

## E. Selling - discounts, volume pricing, dispatch, invoice (Demo flows and docs/01 section 4)

| # | Screen | URL | Login | Annotation |
| --- | --- | --- | --- | --- |
| 35 | Quotation needing discount approval | `/app/quotation/SAL-QTN-2026-00002` (timeline) | amit@horizon.local | 15 % line + 20 % additional discount on impellers: *Horizon Discount Approval* moved it to Pending Discount Approval; approved by the Sales Manager |
| 35a | Opportunity -> Customer | `/app/opportunity/CRM-OPP-2026-00003` (section *Customer Details (for new customer)*, green *Customer* indicator, timeline) then `/app/quotation/SAL-QTN-2026-00004` | amit@horizon.local | Lead CRM-LEAD-2026-00003 stays light; group Premium, GSTIN 33AAFCS4521K1ZF, credit 15,00,000, Net 30 captured on the Opportunity created Customer *Sundaram Pumps Pvt Ltd* before pricing: quotation priced Premium 5 % / 23 %, IGST (ADR-17) |
| 36 | Volume Sales Order, stacked pricing rules | `/app/sales-order/SAL-ORD-2026-00009` (Items row, *Pricing Rules* field) | amit@horizon.local | 60 impellers: PR-PREMIUM-5 + PR-VOLUME-8 + PR-Q4-SPARES-10 applied additively = 23 % (ADR-14); rate 5 005 locked for the whole cycle |
| 37 | Pricing Rules | `/app/pricing-rule` | Administrator | Four rules: customer group, item group, quantity slab, seasonal; priority and additive precedence documented in docs/02 |
| 38 | Delivery Note auto-creating the invoice | `/app/delivery-note/DN-26-00008` (timeline comment) | wh.delhi@horizon.local | Submitted by a Warehouse Manager: the hook created draft SINV-26-00009 and left the comment; dispatch e-mail *Horizon Delivery Dispatched* queued |
| 39 | Sales Invoice | `/app/sales-invoice/SINV-26-00006` | rajesh@horizon.local | INR 537 243, Branch Mumbai HQ, due date +30 from *Net 30*; GST split from the customer's state |
| 40 | Sales Invoice print | `/printview?doctype=Sales%20Invoice&name=SINV-26-00006&format=Horizon%20Sales%20Invoice` | Administrator | Custom print format: GSTIN of the issuing branch, HSN-wise tax table, bank details, terms |
| 41 | Thermal packing slip | `/printview?doctype=Delivery%20Note&name=DN-26-00008&format=Horizon%20Packing%20Slip%20Thermal` | Administrator | 80 mm packing slip for the dispatch bay |
| 41a | CRM workspace | `/app/horizon-crm` | amit@horizon.local | Flow Lead -> Opportunity (customer details) -> Quotation (customer auto-created) -> Sales Order; open leads, leads older than 14 days, open opportunities, open opportunity value, leads converted (90d), quote-to-order %; Leads by Status, Opportunities by Status |
| 42 | Selling workspace | `/app/horizon-selling` | amit@horizon.local | Flow Quotation (from 2. CRM) -> Sales Order -> Delivery Note -> Sales Invoice; open quotation value, quote-to-order %, avg days quote to SO, deliveries due today; Quotation Value Trend |
| 43 | Order Status Report | `/app/query-report/Order%20Status%20Report` | Administrator | Fulfilment of every Sales Order line (ordered / delivered / billed) with an overdue flag after 5 days |

## F. Inventory, Delhi warehouse user, API (Demo 3)

| # | Screen | URL | Login | Annotation |
| --- | --- | --- | --- | --- |
| 44 | User Permission for the Delhi user | `/app/user-permission?user=wh.delhi%40horizon.local` | Administrator | *Warehouse = Delhi DC - HML*, applies to all doctypes: the Delhi Warehouse Manager sees only Delhi stock |
| 45 | Stock Balance as the Delhi user | `/app/query-report/Stock%20Balance?company=Horizon%20Manufacturing%20Ltd` | wh.delhi@horizon.local | Only *DEL Finished Goods* / *DEL Goods In Transit* rows appear; HQ warehouses are filtered out by the permission |
| 46 | Same report as Administrator | `/app/query-report/Stock%20Balance?company=Horizon%20Manufacturing%20Ltd` | Administrator | Contrast with 45: all 15 warehouses |
| 47 | Inventory workspace as the Delhi user | `/app/horizon-inventory` | wh.delhi@horizon.local | Same workspace, Stock Value by Warehouse shows only Delhi warehouses (User Permission) |
| 48 | Inventory workspace | `/app/horizon-inventory` | Administrator | Receipt (draft PR) -> Quality Inspection -> GRN (PR submit) -> Raw Materials / Rejected + Purchase Return flow and reorder formula; *Items Below Reorder*, *Aging Stock Value (90d+)*, *Stock Turnover (90d)*, *Open Pick Lists*; Stock Value by Warehouse with readable labels |
| 49 | Auto reorder Material Request | `/app/material-request/MAT-MR-2026-00001` | Administrator | Created by the reorder job for RM-WELD-ROD below level 50; purchase type, criticality C |
| 50 | Inventory Obsolescence Analysis | `/app/query-report/Inventory%20Obsolescence%20Analysis` | Administrator | Stock on hand aged by last sale (or first receipt) into 0-30 / 31-90 / 91-180 / 180+ day buckets with value per item / warehouse |
| 51 | Inventory API Log | `/app/inventory-api-log?status=Rate%20Limited` then `/app/inventory-api-log` | Administrator | Every call logged with client, parameters, status, HTTP code and response time; 429 and 503 rows visible |
| 52 | API Usage Report | `/app/query-report/API%20Usage%20Report` | Administrator | One row per client and endpoint: success / rate-limited / failed counts and p95 response time |
| 53 | API response (terminal) | `curl -s -H "Authorization: token <key>:<secret>" "http://localhost:8001/api/method/get_inventory_snapshot?warehouse=Delhi%20DC&filter_by_criticality=1" \| python3 -m json.tool` | API key of Administrator (User form > Settings > API Access) | JSON snapshot: items, available / projected qty, reorder point, low-stock alerts, `X-RateLimit-*` headers (`curl -i`) |

## G. HR and finance (docs/01 section 6-7)

| # | Screen | URL | Login | Annotation |
| --- | --- | --- | --- | --- |
| 54 | Salary Slip | `/app/salary-slip/Sal%20Slip%2FHR-EMP-00001%2F00001` | neha@horizon.local | Structure *Horizon Wage Earner* with branch cost centre; three structures (Salaried / Wage Earner / Contractual) |
| 55 | Salary Cost Analysis | `/app/query-report/Salary%20Cost%20Analysis` | Administrator | Submitted Salary Slips grouped by department / branch / grade / employment type |
| 56 | Leave Balance with Carry-forward Expiry | `/app/query-report/Leave%20Balance%20with%20Carry-forward%20Expiry` | neha@horizon.local | Balance per leave type with the carry-forward portion and its expiry date |
| 57 | Asset | `/app/asset/ACC-ASS-2026-00001` (Depreciation schedule) | rajesh@horizon.local | CNC Lathe 2m, INR 48 L, cost centre Mfg - Equipment, location Mumbai HQ; automatic depreciation booking enabled |
| 58 | Asset Register with Maintenance | `/app/query-report/Asset%20Register%20with%20Maintenance` | Administrator | NBV, maintenance spend and replacement candidates (maintenance over 20 % of cost or NBV under 5 %) |
| 59 | Budget | `/app/budget/BUDGET-2026-00001` | rajesh@horizon.local | Budget per cost centre: Warn on Material Request / Purchase Order, *Stop* on actual GL beyond the annual budget; monthly forecast e-mail from the budget job |
| 60 | Cost Center Wise P and L | `/app/query-report/Cost%20Center%20Wise%20P%20and%20L` | Administrator | Income / expense accounts pivoted by cost centre (YTD or by month); product-line P&L after the 50/30/20 shared allocation |
| 61 | Bank Reconciliation Tool | `/app/bank-reconciliation-tool` (Bank Account *Horizon Current Account - HDFC - HDFC Bank*) | rajesh@horizon.local | Imported statement lines vs payments; unreconciled lines left on purpose feed the aging report |
| 62 | Bank Unmatched Aging | `/app/query-report/Bank%20Unmatched%20Aging` | Administrator | Submitted Bank Transactions still carrying an unallocated amount, aged in 0-7 / 8-30 / ... buckets, plus bank GL vs statement balance |
| 63 | Bank Reconciliation Sign-off | `/app/bank-reconciliation-sign-off/BRS-00001` | rajesh@horizon.local | Period sign-off record with closing balance and reviewer |
| 64 | Net Party Position | `/app/query-report/Net%20Party%20Position` | Administrator | ABC Corp is both customer and supplier: receivable, payable and net exposure on one line (common party accounting enabled) |
| 65 | Data Validation Report | `/app/query-report/Data%20Validation%20Report` | Administrator | Post-migration data issues with severity and suggested action: GSTIN missing / failing checksum, negative stock, invoices without PO, stock items invoiced without a Delivery Note |
| 66 | Project Profitability | `/app/query-report/Project%20Profitability` and `/app/project/PROJ-0001` | Administrator | Custom Conveyor - Bharat Mining: cost, margin and schedule variance per project (alert below -10 %) |

Items 1-6, 11-18, 20-29a, 30-32, 35-41, 44-47, 51-53 are the ~30 core screens for the PDF; the rest
are optional supporting evidence.

## Recording the demo

Record at 1920x1080, one browser window, three private windows pre-logged-in (rajesh, procure or
dept.head, qc), the terminal for the API. Keep each flow under three minutes; the order and the
talking points follow the 12-minute outline in [README.md](README.md).

1. **Demo 1 - INR 7 L PO for the blacklisted sole supplier** (screens 12 -> 14 -> 15 -> 16/17 -> 18).
   As `dept.head`: open a new Purchase Order on ABC Supplies, show the blocking message. As
   `procure`: tick *Blacklist Override*, give the reason, save; show that the required level jumps to
   3 and that a Supplier Exception Log appears. Approve as `rajesh`. Talking point: legitimate
   exceptions are allowed, visible and audited; the 24 h reminder / 48 h escalation jobs
   (`horizon_erp.horizon_buying.tasks`) make the queue age visible in the Horizon Buying workspace.
2. **Demo 2 - weld QC fail -> rework -> Shipment Decision** (screens 22 -> 23 -> 24 -> 25 -> 28).
   Open MAT-QA-2026-00005 and the draft rework Work Order it created; open PA-2026-00002 and
   explain photo mandatory / Operations Head alert / blocked Manufacture entry. Try to submit a
   Delivery Note for SAL-ORD-2026-00003 without a decision to show the refusal, then open
   SD-2026-00001 and DN-26-00002. Talking point: the quality-vs-Friday conflict becomes a documented
   business decision with a cost on each side.
3. **Demo 3 - Inventory API** (screens 53 -> 51 -> 52). Run the curl for Delhi DC with
   `filter_by_criticality=1`, show the JSON and the `X-RateLimit-*` headers (`curl -i`); run the loop
   `for i in $(seq 1 101); do curl -s -o /dev/null -w "%{http_code}\n" ...; done | sort | uniq -c`
   to reach the 429 with `Retry-After`; open the Inventory API Log and the API Usage Report. Talking
   point: secure (token + Bin permission + warehouse User Permission), rate-limited, logged, with a
   retrying client in `horizon_erp/horizon_integrations/client/inventory_sync_client.py`.

Close with screens 10, 27 and 62 for the "Standard / Configuration / Custom" slide (docs/01 section
5) and the challenged requirements in docs/04.

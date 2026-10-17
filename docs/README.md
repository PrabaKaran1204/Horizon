# Horizon Manufacturing Ltd - ERPNext Implementation Documentation

Deliverables for the Horizon Manufacturing Ltd techno-functional assignment. Platform: Frappe 15.96,
ERPNext 15.94, HRMS 15.55, India Compliance 15.25; site `horizon.local`; custom app `horizon_erp`.

## Index

| File | Content | Read it if you want to know |
| --- | --- | --- |
| [01_configuration_design.md](01_configuration_design.md) | Company / branch / warehouse structure, CoA and cost-centre design with two worked cost flows, permission model, Mermaid workflows (Purchasing, Manufacturing, Projects), requirement matrix with Standard / Configuration / Custom code / Designed only for every numbered requirement | What was built, how, and where in the code |
| [02_decision_log.md](02_decision_log.md) | 15 ADRs: company structure, GRN = Purchase Receipt, extend standard DocTypes, MTO/MTS trigger, mandatory Branch dimension, Party Link, custom rate limiter, fixed window, Moving Average, inter-branch transfer at cost with IGST, impeller BOM per 5, 14:01 shift, employee permissions, price lock at SO, domain modules mirroring kaynes | Why each architectural choice was made and what it costs |
| [03_strategic_challenges.md](03_strategic_challenges.md) | Four one-page memos: multi-company vs cost centre, ABC Corp customer-supplier overlap, quality vs deadline (Shipment Decision, report, KPI, Ind AS 115 caution), data migration clean-up | How the four strategic challenges are handled |
| [04_requirements_challenged.md](04_requirements_challenged.md) | 13 requirements that were questioned, why, and the alternative built | Where the brief and good practice diverge |
| [05_test_plan_and_evidence.md](05_test_plan_and_evidence.md) | 60 test scenarios across purchasing, quality, selling, manufacturing, API, jobs, permissions, HR, finance; evidence column for the test run | How to verify the critical flows |
| [06_deployment_and_migration_guide.md](06_deployment_and_migration_guide.md) | Fresh bench, restore from backup, post-restore checklist, CSV import order, known caveats | How to stand the system up |
| [api.md](api.md) | Inventory Sync API contract, rate limiting, logging, retry client, curl examples | How to integrate |

Code entry points: `horizon_erp/hooks.py` (doc_events, scheduler_events, fixtures),
`horizon_erp/horizon_setup/` (install, roles, demo data, print formats, notifications, dashboards),
`horizon_erp/horizon_<domain>/` (one module per ERPNext domain like the kaynes app: buying, selling,
crm, stock, manufacturing, quality_management, projects, hr, payroll, accounts, assets, integrations,
workflow - each with `custom/` Custom Field JSON, doctypes, reports, workspaces and its scheduler
jobs in `tasks.py`), `horizon_erp/horizon_core/` (config, `@horizon_job`, daily summary),
`horizon_erp/horizon_integrations/` (inventory API, rate limiter, sync client; legacy
`horizon_erp/api/` alias shims), `horizon_erp/*/report/` (19 script reports + the API Usage Report = 20;
11 workspaces: the *Horizon ERP* home plus one child per assignment section - Setup & Masters,
Selling, Buying, Inventory, Manufacturing, Quality, Projects & Assets, HR & Payroll, Accounts &
Finance, Integrations; ADR-16).

## 12-minute presentation outline

| Min | Segment | What to show | Point to land |
| --- | --- | --- | --- |
| 0-1 | Problem | Horizon's four tensions: location P&L vs one inventory; purchasing control vs a blacklisted sole supplier; quality vs Friday; spreadsheets vs statutory compliance | The brief is about forcing decisions, not hiding them |
| 1-3 | Structure decision | Company tree, Branch dimension (mandatory for P&L), cost-centre tree with the 50/30/20 allocation, warehouse tree with QC Hold / Rejected / Transit | One company, two GSTINs, three dimensions; and why not two companies (ADR-1) |
| 3-6 | Demo 1 - INR 7 L PO for ABC Supplies | As dept.head: blocked (blacklisted). As procure: Blacklist Override + reason -> Supplier Exception Log, Finance Director notified, Level 3 forced. Walk Pending Dept Head -> Procurement Manager -> Finance Director. Show the *Horizon Buying* workspace and Approval Audit Report; mention 24 h reminders / 48 h escalation | Legitimate exceptions are allowed, visible and audited |
| 6-9 | Demo 2 - weld QC fail -> rework -> Shipment Decision | Quality Inspection on the weld Job Card with `qc_result = Rework` -> draft rework Work Order (`rework_of`). Production Audit score 65 -> photo mandatory, Operations Head alerted, Quality Action, Manufacture entry blocked. Delivery Note refused until a Shipment Decision; record *Ship Partial* with estimated costs; Delivery Note now links the decision. Open *Quality vs Deadline Conflicts* | The conflict becomes a documented business decision with a cost on each side |
| 9-10 | Demo 3 - Inventory API | curl the snapshot for Delhi DC (criticality filter), show headers; loop to the 101st call -> 429 with `Retry-After`; open *Inventory API Log* and *API Usage Report* | Secure, rate-limited, logged, with a retrying client |
| 10-11 | Standard / Configuration / Custom matrix | Section 5 of the configuration design: count per type, highlight the honest "Designed only" rows; show *Quality Metrics* (FPY, rework cost %, defect trend, inspection SLA), *Bank Unmatched Aging*, the budget forecast email and the *Horizon Manufacturing* workspace (open everything from the *Horizon ERP* home) | Most value came from configuration; custom code is small, tested and sits behind hooks |
| 11-12 | Challenged requirements, risks, Phase 2 | GRN step, reversed MTO/MTS, invalid GSTIN, 12 % slab, GSTR-2, "Integration Log", invoice-before-ship. Risks: inter-branch GST document, payroll per branch. Phase 2: Quarterly Purchase Plan logic, Budget Override application, bank sign-off lock, units-of-production depreciation, portal, BI | A consultant's answer: what is live, what is designed, what needs the client's CA |

## Bonus designs (Designed only)

### E-commerce portal

Architecture: ERPNext Webshop (`Website Item` per sellable Item, Standard Selling price list for
guests, customer-specific price lists and Pricing Rules applied after login) on the same site, with
customers as **Website Users** linked to their Customer record through Contact and Portal User, so
every page is scoped by the standard portal permission ("show only my documents"). Catalogue and
cart come from Webshop; real-time stock uses the same pattern as the Inventory API - a whitelisted,
rate-limited, logged method returning `available_qty` per item for `HQ Finished Goods - HML` and
`DEL Finished Goods - HML` (quantity bands such as "in stock / low / made to order" for guests,
exact quantities only for logged-in customers). Instant quote = Quotation created from the cart
with the pricing engine, exposed on the portal's Quotation page with the 30-day validity; order
placement = Sales Order through the standard checkout, which then flows into the existing
Production Plan / capacity check; order tracking reads Sales Order `per_delivered`, Delivery Note
status and the Horizon Delivery Dispatched email. Data flowing out: Website Item, Item Price for the
customer's list, stock bands, Quotation, Sales Order, Delivery Note, Sales Invoice, payment status.
Security: customer-scoped permission queries on Quotation / Sales Order / Delivery Note / Sales
Invoice (standard portal rules), no price-list leakage (Premium rates served only to Premium
customers, never in a public JSON), stock quantities banded for guests, rate limit per portal user,
API keys never issued to browsers (session auth only), credit-limit and blacklist checks remain
server-side, and GSTIN capture on the portal address form validated by India Compliance.
Implementation sketch: enable Webshop, publish items, configure Webshop Settings, add the stock
endpoint next to `horizon_integrations/inventory_api.py`, add the quote-from-cart button as a portal page, UAT with two
customer users (Premium, Standard).

### BI and profitability dashboard

Dashboard (Frappe Insights or an external BI reading the MariaDB replica): Top 10 products by
contribution margin %, Top 10 customers by profit after direct cost and allocated overhead, sales
trend by quarter with a 3-month moving-average forecast (the same method as *Forecast vs Actual
Demand*). Data sources and joins: revenue from Sales Invoice Item (item, customer, cost centre,
branch, net amount); COGS from Stock Ledger Entry `stock_value_difference` on Delivery Note /
Sales Invoice vouchers (Moving Average valuation, so it reflects current purchase prices);
manufacturing conversion cost from Job Card operating cost and Work Order `total_operating_cost`
per production item; direct labour from Salary Slip by `payroll_cost_center` and Timesheet costing
for projects; overhead from GL Entry on Factory Overhead / Admin accounts allocated by the Cost
Center Allocation ratios; quality cost from Rework Cost, Scrap Loss and rework Work Orders.
Supporting reports already in the app: Cost Center Wise P and L, Project Profitability, Quality vs
Deadline Conflicts (CoPQ), Inventory Obsolescence Analysis (carrying cost). Data gaps that prevent
"true" profitability today: no activity-based overhead per product (allocation is a fixed 50/30/20
by product line, not by machine hours consumed - Job Card hours could drive it), landed cost is not
applied on every Purchase Receipt (freight and duty sit in expense accounts, understating COGS on
imported castings), no customer-level cost-to-serve (freight, returns, sales effort are not tagged
to customers), spares demand history is under two years so seasonal indices are assumed (1.5x) not
fitted, and discounts granted outside pricing rules are captured (`discount_over_rule_pct`) but not
yet aggregated per customer. Closing these gaps is master-data and process work (Landed Cost
Voucher discipline, a cost-to-serve item on freight invoices, machine-hour-based allocation), not
new DocTypes.

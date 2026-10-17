# Horizon ERP - Strategic Implementation Challenges

Four one-page decision memos. Each states the recommendation first, then the reasoning, what was
built, and the open risks.

---

## Memo 1 - Multi-company vs cost-centre structure

**Recommendation.** One ERPNext company (`Horizon Manufacturing Ltd`, abbr `HML`) with:
- `Branch` as an Accounting Dimension that is **mandatory for P&L accounts** (Mumbai HQ, Delhi DC);
- cost centres for *function and product line* (Manufacturing -> Equipment / Spares / Components /
  Shared, Sales, Admin, R&D);
- two GST registrations on two company addresses;
- group warehouses per site.

**Why not two companies.** Horizon is one legal entity. A second company would force inter-company
invoicing for every pallet moved to Delhi, two payroll runs, two sets of masters and a consolidation
step - all to produce a report that a dimension filter gives for free.

**GL structure.**

| Axis | Object | Used for |
| --- | --- | --- |
| What | Account (Sales - Equipment / Spares / Components, COGS, Factory Overhead, Rework Cost, Scrap Loss ...) | Nature of income / expense |
| Who | Cost Center (department, product line) | Bonus and budget by department; product-line margin |
| Where | Branch dimension | Location profitability, GST registration |
| For which job | Project | Custom manufacturing margin |

Allocation: shared plant cost is posted once to `Mfg - Shared - HML` and split 50 / 30 / 20 by a
submitted Cost Center Allocation (ERPNext applies it at GL time). Recurring journals (rent,
electricity) carry cost centre and branch on every line and repeat monthly (Auto Repeat).

**Reporting strategy.**

| Audience | Question | Report |
| --- | --- | --- |
| Finance (Rajesh) | Is Delhi profitable? | Profit and Loss Statement, filter Branch = Delhi DC |
| Finance | Department performance for bonus | Cost Center Wise P and L (monthly / YTD), Budget Variance Report |
| Finance | Product-line margin | Cost Center Wise P and L on Mfg - Equipment / Spares / Components plus Sales - <line> accounts |
| Operations (Priya) | Where is stock, what is short? | Horizon Inventory workspace, Stock Balance (all warehouses), Inventory API for Delhi |
| Operations | Can we make it by Friday? | Capacity Utilisation and Sequence, Quality vs Deadline Conflicts |
| Delhi warehouse | My stock only | Same reports, restricted by User Permission on `Delhi DC - HML` |

**Assumptions.** Delhi does not manufacture; Delhi stock is replenished only from HQ; one set of
books is filed; the board does not need a branch balance sheet in FY 2026-27.

**Risks.**

| Risk | Mitigation |
| --- | --- |
| A P&L posting without a branch is rejected at save (payroll, auto invoices, depreciation) | `apply_default_dimensions` on every server-side posting; payroll per branch; asset carries branch (ADR-5) |
| Branch defaults to Mumbai HQ, so a Delhi expense keyed by an HQ accountant silently lands in Mumbai | Branch shown on all accounting forms; monthly review of Delhi P&L against Delhi head-count and rent |
| Inter-branch GST is a taxable supply between distinct persons | Internal customer/supplier with IGST (ADR-10) - to be confirmed with the CA |

**Migration path if Delhi becomes a legal entity.** (1) Create company `Horizon Distribution Delhi`
with its own CoA from the same template; (2) move `Delhi DC - HML` warehouses by transferring stock
out to a transit account and receiving into the new company (Stock Reconciliation opening); (3)
mark the Delhi Customer / Supplier pair as internal and switch replenishment to inter-company
Sales / Purchase Orders; (4) the Branch dimension stays - it becomes `Mumbai HQ` only; historical
Delhi P&L remains filterable; (5) re-run payroll setup for Delhi employees under the new company.
No GL history is rewritten.

---

## Memo 2 - Customer-supplier overlap (ABC Corp)

**Recommendation.** Keep **two records** - Customer `ABC Corp` and Supplier `ABC Corp` (same PAN
`AAACA1234B`, same GSTIN) - and link them with a `Party Link` (primary Customer, secondary
Supplier) with Accounts Settings *Enable Common Party Accounting* on. ERPNext does not support a
single party acting on both sides; the link is the supported pattern.

**Accounting treatment of an offset (ABC owes 10 L, Horizon owes 5 L).**

1. Invoices are raised at gross on each side (GST on the full supply value both ways).
2. With common party accounting, when the Purchase Invoice for 5 L is posted against the secondary
   party, ERPNext automatically creates a Journal Entry transferring the payable into the customer
   ledger, so the customer ledger already shows the net 5 L receivable.
3. If common party accounting were off, the manual settlement journal is:

| Journal Entry | Debit | Credit |
| --- | --- | --- |
| Creditors - HML, party Supplier ABC Corp (against the 5 L Purchase Invoice) | 5,00,000 | |
| Debtors - HML, party Customer ABC Corp (against the 10 L Sales Invoice) | | 5,00,000 |

4. The remaining 5 L is collected by a Payment Entry against the Sales Invoice.
5. TDS / TCS obligations are unaffected by the set-off and are computed on the gross invoices.

**Report.** *Net Party Position* (`horizon_accounts/report/net_party_position`): for every Party
Link pair (optionally same-name pairs too) it shows receivable, open sales invoices, payable, open
purchase invoices, net, direction (Net Receivable / Net Payable) and the suggested settlement amount,
with totals. Use it in the settlement negotiation.

**Governance rule.** Netting changes the legal position of both parties (a set-off right is only
enforceable if agreed, and insolvency practitioners challenge undocumented set-offs). Therefore:
- a written **netting agreement** signed by both companies, naming the frequency (monthly),
  cut-off date, and dispute handling;
- the settlement journal references the agreement and lists the invoices settled;
- only the Finance Director posts set-off journals (Payment approval workflow >= 1 L already routes
  to the FD);
- never net GST or TDS - those are settled with the government at gross.

**Risks.** Credit limit on the Customer must consider the payable side (ERPNext does not); the Net
Party Position report is the control. If ABC Supplies (blacklisted) and ABC Corp are related, the
blacklist flag must be reviewed on both records - they are different PANs in the demo data.

---

## Memo 3 - Quality vs deadline conflict

**The situation.** Wednesday: 30 % of units for a Friday order fail weld inspection. Sales wants to
ship, Operations has no rework capacity, Quality refuses defective goods, Finance wants the invoice
in Q4.

**Design principle.** The system must not silently pick one side; it must surface the conflict
early and record who decided what, at what estimated cost.

**Detection rules (built).**

| Where | Rule | Code |
| --- | --- | --- |
| Quality Inspection on a Job Card / Stock Entry | `qc_result = Rework` creates a draft rework Work Order (`rework_of`), `Fail` opens a Non Conformance | `horizon_quality_management/inspection.py` |
| Production Audit | score < 70 notifies the Operations Head, opens a Quality Action and blocks the Manufacture Stock Entry until the audit is *Action Closed* | `production_audit.py`, `production_audit_hooks.py` |
| Daily job `detect_quality_deadline_conflicts` | Sales Orders due within 3 days (or overdue), not fully delivered, with an unfinished WO, an open audit < 70 or a rejected QI, and **no submitted Shipment Decision** -> one alert per SO per day to Sales Manager, Operations Head, Quality Manager | `horizon_quality_management/tasks.py` |
| Delivery Note validate | Same blockers at delivery time -> submit is refused until a submitted Shipment Decision for that Sales Order exists; the decision is linked on the Delivery Note | `selling.enforce_quality_gate` |

**The decision point - `Shipment Decision` (SD-YYYY-#####).** Pre-filled from the Sales Order and
its blockers (`make_shipment_decision`, or *Create > Shipment Decision* on the Delivery Note).

| Decision | Mandatory data | Named approver | Effect on submit |
| --- | --- | --- | --- |
| Ship Partial | `partial_qty` > 0 and <= pending qty | Sales approver | Delivery Note for the good units may proceed; rest stays open |
| Delay Delivery | `new_delivery_date` after current date | Sales approver | Delivery dates on the Sales Order and its rows are moved; comment records old and new |
| Invoice Now Ship Later | Finance Approver | Finance Director | Allows the invoice before dispatch (see the Ind AS 115 caution below) |
| Ship With Concession | Quality Approver | Quality | Delivery of units outside spec with a documented concession |

Every decision requires a `reason`, carries `estimated_quality_cost` and `estimated_delay_cost`,
and writes a Comment on the Sales Order ("Shipment Decision SD-... : Delay Delivery - delivery
date moved from ... to ... Reason: ..."). Cancelling a decision re-opens it and comments again. That
is the audit trail: who, when, which option, why, at what estimated cost.

**Report - Quality vs Deadline Conflicts** (`horizon_quality_management/report/quality_vs_deadline_conflicts`):
near-due Sales Orders with their Work Orders, WO status, open audits < 70, rejected QIs, the linked
decision, estimated costs and a status of *OK*, *Conflict - Undecided* or *Decided: <option>*;
summary cards for undecided, decided, OK, Cost of Poor Quality (period) and Cost of Delay.

**Recommended KPI - Cost of Poor Quality vs Cost of Delay (ratio, monthly).**

```
CoPQ = rework WO material + rework WO operating cost        (Work Orders with rework_of, period)
     + Scrap Loss postings
     + concession credits / price reductions granted
     + Shipment Decision.estimated_quality_cost

CoD  = contractual penalties / liquidated damages
     + expedite freight and overtime caused by the delay
     + margin lost on cancelled or discounted lines
     + Shipment Decision.estimated_delay_cost

KPI  = CoPQ / (CoPQ + CoD)   tracked per month and per customer
```

Reading: if the ratio drifts toward 1, quality failures are costing more than late deliveries -
invest in process control (weld parameters, incoming steel inspection). If it drifts toward 0,
delays dominate - invest in capacity or renegotiate lead times. The first two terms of each side
are already in the system (rework WOs, Scrap Loss account, the two estimate fields); penalties and
concession credits need a Sales Invoice credit note reason code (follow-up).

**Caution - "invoice Friday, ship next week" (Ind AS 115).** Revenue is recognised when control
of the goods passes to the customer, not when the invoice is printed. An invoice without dispatch
is only revenue if the **bill-and-hold** tests are met: a substantive reason (the customer asked),
the goods are identified separately as the customer's, they are ready for physical transfer, and
Horizon cannot redirect them. Units that failed weld inspection are, by definition, not ready for
transfer, so invoicing them on Friday books revenue that the auditor will reverse and that GST will
tax immediately. The *Invoice Now Ship Later* option therefore (a) needs the Finance Director as the
named approver, (b) is logged on the Sales Order, and (c) should only be used for the units that
passed inspection and are physically segregated. The default system behaviour - invoice only from a
submitted Delivery Note - remains the safe path.

---

## Memo 4 - Data migration clean-up

| Problem (legacy) | Auto-fix or human review | Treatment before go-live | Prevention control in the new system |
| --- | --- | --- | --- |
| 50 customers with invalid GSTINs | **Human review** - a checksum fix cannot be guessed; one wrong character changes the registered person | Run the *Data Validation Report* (GSTIN format / checksum via India Compliance `validate_gstin`); send the list to Sales for confirmation against the GST portal; parties that cannot be confirmed are imported as *Unregistered* (no ITC passed to them) until corrected. The brief's own HQ GSTIN `27AABCU9602H1Z0` failed this check and was replaced with the checksum-valid `27AABCU9602H1Z9` | India Compliance validates GSTIN checksum and state code on Address / Customer / Supplier save; GST category is derived from the GSTIN; the report stays available for periodic re-runs |
| 100 items with negative stock | **Auto-fix for the posting, human review for the cause** | Physical count of the 100 items; opening Stock Reconciliation at counted quantities and agreed valuation; the difference is posted to the dedicated account `Stock Adjustment - Migration - HML` so operational stock adjustments are not polluted; items with no count are imported at zero and flagged | Stock Settings `allow_negative_stock = 0`; Purchase Receipt mandatory before invoice (`pr_required`); hourly stock-accuracy check flags Bin vs ledger drift and count variances > 2 % |
| Purchase Invoices without a linked PO | **Human review** by category: recurring utilities / rent (legitimate, convert to Auto Repeat journals), one-off direct purchases (document and close), everything else (match to a PO or raise a retrospective one) | Import historical invoices as opening balances per supplier (not line by line) so no unlinked documents enter the new ledger; keep the legacy register as an attachment | Buying Settings `po_required = Yes` and `pr_required = Yes`; PO approval workflow by amount; budget check on Purchase Order (Warn) and on actual expense (Stop) |

**Data Validation Report** (`horizon_accounts/report/data_validation_report`): one row per issue
with Entity Type, Name, Issue, Severity (High / Medium / Low) and Suggested Action, bar chart by
entity type and severity counts. Checks implemented:
- Customer / Supplier: GST category Registered Regular with empty GSTIN; GSTIN failing checksum;
- Item: negative stock per warehouse (High); stock item with no valuation rate and no reorder level (Low);
- Purchase Invoice: no Purchase Order on any line (Medium);
- Sales Invoice: stock item invoiced without a Delivery Note and without Update Stock (Medium);
- Employee: active employee without a payroll cost centre (Medium).

**Sequence.** Export legacy -> run the report on a staging site -> fix masters at source -> re-import
-> report must be empty for High before cut-over; Medium items get an owner and a date.

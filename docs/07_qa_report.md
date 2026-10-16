# Horizon ERP – Live QA Report (16-Oct-2026)

## 1. Environment

| | |
| --- | --- |
| Site | `horizon.local` (Frappe 15.96 / ERPNext 15.94 / HRMS 15.55 / India Compliance 15.25), dev server http://127.0.0.1:8001 (auto-reload, not restarted) |
| App under test | `horizon_erp` – commit as checked out on 16-Oct-2026 |
| Method | Python scripts run with `frappe.connect()` + `frappe.set_user(<demo user>)`; workflow transitions through `frappe.model.workflow.apply_workflow`; REST checks with `curl` against port 8001 using API tokens of the real users; `frappe.flags.mute_emails = True`; scheduler disabled (Email Queue rows stay 'Not Sent') |
| Users exercised | dept.head@, procure@, rajesh@, priya@, amit@, wh.delhi@, qc@, neha@ (all `Horizon@123`); throwaway `qa.sales@` (Sales User only), `qa.accounts@` (Accounts User only), `qa.api@` (Stock User, API client) – all three disabled at the end, none owns a kept document |
| Data kept | Everything that passed is left on the site as sample data (section 3). Failed attempts were rolled back with savepoints; a handful of documents were completed by Administrator where no demo role could (flagged below). |
| Not restarted / not changed | No product code was changed. Two environment changes were made and are declared: (1) Email Account **Horizon Notifications (QA outgoing)** created (default outgoing, `localhost`, no auth) because the site had none and every notification failed (DEF-01); (2) `Shift Type Morning Shift.last_sync_of_checkin` advanced to now while processing auto attendance. |
| Fix round (16-Oct-2026, after QA) | Defects fixed in commit `fix: QA defects - permissions, price lock at SO, auto invoice, stock accuracy, reorder recompute, email account`; per-defect status in section 4 ("Fix status"). The QA e-mail account was kept but is no longer the default: `demo_data.setup_email_account` created **Horizon Notifications** (`notifications@horizon.local`, placeholder SMTP `localhost:25`) as the single default outgoing account. |
| Regression | `bench --site horizon.local run-tests --app horizon_erp --skip-test-records` → **Ran 120 tests in 55.676s — OK** (after all live changes) |

## 2. Summary

| Area | Scenarios | Pass | Fail | Partial | Not run |
| --- | --- | --- | --- | --- | --- |
| Purchasing | 11 | 10 | 0 | 0 | 1 |
| Receipt and quality | 11 | 8 | 2 | 0 | 1 |
| Selling | 16 | 14 | 2 | 0 | 0 |
| Manufacturing | 10 | 10 | 0 | 0 | 0 |
| API | 8 | 8 | 0 | 0 | 0 |
| Reorder / scheduler | 7 | 5 | 1 | 0 | 1 |
| HR | 6 | 6 | 0 | 0 | 0 |
| Finance | 9 | 9 | 0 | 0 | 0 |
| Permissions | 4 | 1 | 0 | 2 | 1 |
| Infrastructure | 1 | 0 | 1 | 0 | 0 |
| Regression | 1 | 1 | 0 | 0 | 0 |
| **Total** | 84 | 72 | 6 | 2 | 4 |

Reading the table: *Fail* rows are scenarios where the expected business outcome did not happen on the live site (each maps to a defect below); *Partial* means part of the scenario was verified; *Not run* was not exercised live in this cycle (unit coverage exists for QI-3 and SJ-6). The detailed per-scenario evidence is in `docs/05_test_plan_and_evidence.md` (Evidence column and the "Live QA additions" table).

## 3. Sample data left on the site (demo inventory)

All documents below were created on 16-Oct-2026 and are intentionally kept.

**Purchase Orders (8)**

| PO | Supplier | Grand total | Level | State | Notes |
| --- | --- | --- | --- | --- | --- |
| PUR-ORD-2026-00001 | Mumbai Steel Traders | ₹50,000 | Level 1 | Approved (submitted) | A1; received on PR-26-00001 |
| PUR-ORD-2026-00002 | Mumbai Steel Traders | ₹3,00,000 | Level 2 | Approved | A2 |
| PUR-ORD-2026-00003 | Bharat Castings Ltd | ₹7,00,000 | Level 3 | Approved | A3 (three approvals) |
| PUR-ORD-2026-00004 | Pune Electricals | ₹1,80,000 | Level 2 | **Pending Procurement Manager** (draft) | A5/A7: rejected → revised → re-submitted → auto-escalated by the reminder job |
| PUR-ORD-2026-00005 | ABC Supplies (blacklisted) | ₹12,000 | Level 3 (override) | Approved | A6; Supplier Exception Log SEL-00001 Approved by rajesh; received on PR-26-00003 |
| PUR-ORD-2026-00006 | Delhi Fastener House | ₹26,000 | Level 1 | Approved | notification e-mail evidence |
| PUR-ORD-2026-00007 | Pune Electricals | ₹36,000 | Level 1 | Approved | serialised motors; received on PR-26-00004 |
| PUR-ORD-2026-00008 | ABC Corp | ₹5,000 | Level 1 | Approved | received PR-26-00005, invoiced PINV-26-00001 |

Note: server-created POs carry the GST template name but no tax rows (UI populates them), so grand totals are ex-GST (DEF-16).

**Purchase Receipts / Invoices**: PR-26-00001 (Mumbai Steel, 90 accepted + 10 rejected, QC release MAT-STE-00002), PR-26-00002 (draft Purchase Return −10 Kg from HQ Rejected), PR-26-00003 (ABC Supplies, 100 Kg batch WR-0002), PR-26-00004 (Pune Electricals, serials MOT-0011/0012, release MAT-STE-00003), PR-26-00005 (ABC Corp, 20 bearings); PINV-26-00001 (ABC Corp ₹5,250, settled by common-party JE ACC-JV-2026-00026).

**Quality Inspections (5)**: MAT-QA-2026-00001 Incoming RM-STEEL-PLATE Accepted; 00002 Incoming CMP-MOTOR-5HP Accepted; 00003 In Process HZ-PUMP-100 on Job Card PO-JOB00004 Accepted; 00004 Outgoing HZ-PUMP-100 on DN-26-00001 Accepted; 00005 In Process SP-IMPELLER on PO-JOB00009 qc_result **Rework** → rework WO MFG-WO-2026-00003.

**CRM / Selling**: Lead CRM-LEAD-2026-00001 (Rohan Deshmukh, status Opportunity) → Opportunity CRM-OPP-2026-00001 (Converted) → Quotation SAL-QTN-2026-00001 (Tata, ₹7,05,411, Ordered) and SAL-QTN-2026-00002 (Tata, 20 % extra discount approved, ₹49,504, Ordered).

| Sales Order | Customer | Grand total | Delivery | Status |
| --- | --- | --- | --- | --- |
| SAL-ORD-2026-00002 | Tata Precision Works (Premium, West) | ₹7,05,411 (HZ-PUMP-100 ×2 @175,750; SP-IMPELLER ×60 @5,005) | 06-11-2026 | To Deliver and Bill, 51.6 % delivered |
| SAL-ORD-2026-00003 | Tata Precision Works | ₹49,504 (SP-IMPELLER ×10, 20 % doc discount, approved) | 18-10-2026 | To Deliver and Bill, 50 % delivered (Shipment Decision SD-2026-00001 Ship Partial 5) |
| SAL-ORD-2026-00004 | Delhi Metro Fabricators (Standard, North, IGST) | ₹69,873.55 (impellers 5, seal sets 8, belt kits 3 at North Selling −10 % Q4) | 19-10-2026 | Completed |

**Delivery Notes (3)**: DN-26-00001 Tata ₹5,37,243 (pumps PMP-0001/0002 + 30 impellers, short-ship with deviation notes, outgoing QI; submitted by Administrator – see DEF-04); DN-26-00002 Tata ₹24,752 (5 impellers from DEL FG, linked to SD-2026-00001); DN-26-00003 Delhi Metro ₹69,873.55 (DEL Finished Goods, branch Delhi DC).

**Sales Invoices (2)**: SINV-26-00002 Delhi Metro ₹69,873.55 IGST, Partly Paid (outstanding 27,874); SINV-26-00003 ABC Corp ₹4,838.40 (FD bypass without DN, audited comment). **No invoice exists for the Tata deliveries** because the auto-invoice failed (DEF-05/06) and even Administrator with `ignore_pricing_rule` cannot invoice the partially shipped volume-discount line.

**Manufacturing**: MFG-WO-2026-00001 HZ-PUMP-100 ×2 Completed (Job Cards PO-JOB00001…08, transfer MAT-STE-00005, manufacture MAT-STE-00006, serials PMP-0001/0002 now Delivered); MFG-WO-2026-00002 SP-IMPELLER ×5 Completed (PO-JOB00009, MAT-STE-00007/00008); MFG-WO-2026-00003 SP-IMPELLER ×2 **draft rework** (`rework_of` 00002). Production Audits PA-2026-00001 (85, Submitted) and PA-2026-00002 (65, escalated, Action Closed, Quality Action QA-ACT-00014 Open). Shipment Decision SD-2026-00001 (Ship Partial 5, Decided).

**Stock / reorder**: Material Issue MAT-STE-00004 (RM-WELD-ROD 160 Kg); Material Requests MAT-MR-2026-00001 (Purchase, RM-WELD-ROD 100 Kg) and MAT-MR-2026-00002 (Manufacture, SP-IMPELLER 60); Batch WR-0002; Item Reorder rows recomputed by the daily job (see DEF-08/09 – levels are now much lower than the demo masters).

**Finance**: Journal Entry ACC-JV-2026-00025 (Marketing ₹50,000, Sales - HML); Payment Entries ACC-PAY-2026-00001 (₹42,000 vs SINV-26-00002) and ACC-PAY-2026-00002 (₹2,50,000 advance Bharat Mining Co, FD-approved); Bank Transactions ACC-BTN-2026-00009 and 00003 Reconciled; Bank Reconciliation Sign-off BRS-00001 (Sep 2026).

**HR**: Leave Application HR-LAP-2026-00001 (Neha, CL 26–27 Oct, Approved); Employee Checkins EMP-CKIN-10-2026-000061/000062 (Ravi Kumar 06:09 / 14:10 today).

**Queues / logs**: 37 Email Queue rows (Not Sent – muted), 12 Notification Log rows, Error Log entries 'Auto Sales Invoice failed for DN-26-0000x' (evidence for DEF-05/06).

**Added by the fix round (16-Oct-2026, re-running the failed scenarios as the intended users)**: PUR-ORD-2026-00009 (dept.head, Mumbai Steel Traders, RM-PAINT-GREY 20 L @350 = ₹7,000, Level 1, Approved) received by **procure** on PR-26-00006 with auto-created Batch **PG-0002** (bundle 462801aed1e3bb5ab3a2; HQ RM paint 79 → 99 L). MAT-STE-00009 (Administrator, 4 × SP-SEAL-SET HQ FG → DEL FG to restock Delhi). SAL-ORD-2026-00005 Delhi Metro Fabricators (amit, North Selling −10 % Q4, IGST, ₹4,983.55) delivered by **wh.delhi** on DN-26-00004 from DEL Finished Goods → auto draft **SINV-26-00004** (owner wh.delhi). SAL-ORD-2026-00006 Tata Precision Works (amit, Premium 5 % + Q4 10 % = 15 %, ₹4,569.60) delivered by **amit** on DN-26-00005 → auto draft **SINV-26-00005** (owner amit). **SINV-26-00006** Tata Precision Works ₹5,37,243 (HZ-PUMP-100 ×2 @175,750; SP-IMPELLER ×30 @5,005 - the Sales Order rates) for DN-26-00001, submitted, Unpaid, due 15-11-2026; DN-26-00001 is now Completed / 100 % billed. DN-26-00002 (Tata, ₹24,752) is still *To Bill* - invoice it from the Delivery Note ("Create > Sales Invoice"), the price lock now applies. The 14 false-positive "Stock accuracy flag" Item comments of 16-Oct were deleted after the corrected check reported zero mismatches; Item Reorder rows were restored to the demo masters (RM-STEEL-PLATE 400/1000, bolts 500/2000, spares Manufacture rows only, no row on HZ-PUMP-100); Employee User Permissions of rajesh/priya/amit/neha/qc re-scoped; Leave Block List *Plant Shutdown Dec 2026* replaced by *Diwali Peak Production Block*; Asset Maintenance Log ACC-AML-2026-00001 Completed on 10-10-2026.

## 4. Defects

Severity: Critical / High / Medium / Low. Risk = risk of leaving it unfixed before go-live.

### Fix status (16-Oct-2026)

| Defect | Fix status | Where | Evidence (live re-run as the intended user) |
| --- | --- | --- | --- |
| DEF-01 | **Fixed** | `demo_data.setup_email_account`, `tasks.safe_sendmail` (used by `notify_users`, daily summary, blacklist override, audit escalation) | Email Account *Horizon Notifications* default outgoing; `frappe.sendmail` with `mute_emails` queues without error; `test_email_account_is_default_outgoing_and_sendmail_never_raises` |
| DEF-02 | **Fixed** | `roles.setup_role_permissions` (Custom DocPerm: Batch / Serial No / Serial and Batch Bundle / Address / Contact / Supplier / Customer), fixture in `hooks.py`, applied on `after_migrate` | procure: PR-26-00006 from PUR-ORD-2026-00009 submitted, Batch PG-0002 auto-created; priya / wh.delhi read *Tata Precision Works-Billing* and *Mumbai Steel Traders-Billing* |
| DEF-03 | **Fixed** | `demo_hr_finance.scope_employee_user_permissions` (ADR-13) | priya and qc read PA-2026-00002 (inspector HR-EMP-00010) and see both audits in the list; neha created an Employee Checkin for Ravi Kumar (rolled back); `test_employee_user_permission_scoped_to_self_service_doctypes` |
| DEF-04 | **Fixed** | same Custom DocPerm set + Delivery Note for Warehouse Manager | wh.delhi: DN-26-00004 from DEL Finished Goods submitted (owner wh.delhi), `has_permission("Serial and Batch Bundle","create")` True for wh.delhi and amit |
| DEF-05 | **Fixed** | `selling.lock_rates_to_sales_order` (`before_validate` on DN and SI), Selling Settings *Maintain Same Rate* = Stop (ADR-14) | SINV-26-00006 for DN-26-00001 posted at the SO rates (5,005 for 30 of 60 impellers), ₹5,37,243, no over-billing error; `test_partial_delivery_keeps_sales_order_rate_and_invoices_cleanly` |
| DEF-06 | **Fixed** | `selling.on_submit_delivery_note` maps into a target with `ignore_permissions`, inserts with `ignore_permissions`; Sales User read on Sales Invoice | amit (no SI create): DN-26-00005 → draft SINV-26-00005; wh.delhi: DN-26-00004 → draft SINV-26-00004; no Error Log; `test_auto_invoice_is_created_when_a_sales_user_submits_the_delivery` |
| DEF-07 | **Fixed** | `hourly._flag_bin_mismatches` compares Bin with the latest SLE `qty_after_transaction` | re-run reports 0 mismatches on the live site; the 14 Info comments of 16-Oct deleted; `test_bin_mismatch_compares_with_latest_sle_qty_after_transaction` |
| DEF-08 | **Fixed** | `daily.recompute_reorder_levels` upserts per warehouse, keeps `material_request_type`, inserts only for purchase items; `demo_data._sync_item_children` removes duplicates / make-to-order rows | live run after fix: no duplicate rows, SP-* keep their Manufacture row, HZ-PUMP-100 row removed; `test_recompute_reorder_levels_keeps_manufacture_row_and_safety_stock_floor` |
| DEF-09 | **Fixed** | history gate: first outgoing SLE >= 60 days old and >= 3 movements, floor at `Item.safety_stock` | live run: every demo item `skipped_insufficient_history`, manual levels untouched (RM-STEEL-PLATE 400/1000, bolts 500/2000); `test_recompute_reorder_levels_needs_sixty_days_and_three_movements` |
| DEF-10 | **Fixed** | `selling.get_rule_rate` additive (compounds only `apply_discount_on_rate`); docs/01 PR-4, ADR-14 | `test_rule_rate_adds_stacked_discount_percentages` (5 + 8 + 10 = 23 % → 5,005) |
| DEF-11 | **Fixed** (valid_till) / **Not fixed** (price list) | `selling.set_quotation_valid_till` | `test_quotation_valid_till_defaults_from_crm_settings`; the customer default price list on server-created orders is standard ERPNext behaviour (the form sets it) - left as is |
| DEF-12 | **Fixed** | `selling.get_mfg_lead_days` recursive (depth 5, cap 365) | `test_mfg_lead_days_explodes_multi_level_bom` (3-level BOM → 23 days vs 1 before); HZ-PUMP-100 now 30 days |
| DEF-13 | Not fixed (design) | - | documented: discounts beyond the rules are granted through `additional_discount_percentage`, which triggers the approval |
| DEF-14 | **Fixed** | Quality Inspector: read/write/create/submit/cancel on Quality Inspection; Stock User read | `test_role_permissions_close_receiving_and_dispatch_gaps` |
| DEF-15 | **Fixed** | Approval Audit Report lists Info comments starting "Auto-escalated" as transitions | PUR-ORD-2026-00004 row "Auto-escalated → Pending Procurement Manager"; `test_auto_escalation_comments_are_transition_rows` |
| DEF-16 | Not fixed (documented) | - | Server-created POs carry the GST template name only; POs created in the UI get the template's tax rows through India Compliance (`set_taxes` on the form), so approval limits apply to the grand total incl. GST for UI-created POs. API/script-created POs must append the template rows themselves (`get_taxes_and_charges`) - see the QA scripts |
| DEF-17 (bank statement) | Not fixed (demo data) | - | out of scope of this round |
| DEF-18 (leave block list) | **Fixed** | `demo_hr_finance.ensure_leave_block_list` - *Diwali Peak Production Block* 19 / 22 / 23 Oct 2026 | rajesh approving neha's Leave Application for 22-10-2026 → `LeaveDayBlockedError` "You are not authorized to approve leaves on Block Dates" (HRMS only warns at application time, by design); control date 29-10-2026 approves; `test_leave_block_list_on_working_days` |
| DEF-19 (budget PDF) | **Fixed** | `monthly.send_budget_report` attaches the PDF with the daily-summary fallback | `test_send_budget_report` asserts no `pdf_error` |
| DEF-20 (asset last maintenance) | **Fixed** | `demo_hr_finance.complete_first_maintenance_log` | ACC-AML-2026-00001 Completed 10-10-2026, Asset Register shows the date; `test_completed_maintenance_log_feeds_asset_register` |
| DEF-21 (salary branch) | **Fixed** | Salary Cost Analysis group by *Branch* (`Salary Slip.branch`) | `test_group_by_variants` |

Regression after the fixes: `bench --site horizon.local run-tests --app horizon_erp --skip-test-records` → **Ran 134 tests in 87.649s — OK**; leftover check for all test prefixes = 0 (the remaining `Error Log` / `Comment` rows of earlier test rounds that mentioned a test prefix were removed as part of this clean-up).

### DEF-01 – No default outgoing Email Account: every notification and workflow e-mail fails
*Severity* High · *Priority* P1 · *Risk* High · *Type* Environment / configuration
*Impact*: PO approval requests, blacklist-override alerts, audit escalations, delivery-dispatched mails, reminders, daily/budget reports – none can be queued. 33 "Failed to send Notification", 17 "Failed to send workflow action email", 13 "Blacklist override email failed", 10 "Production Audit escalation email failed" Error Logs accumulated during this run before the workaround. With `mute_emails` the dummy account even raises `AttributeError: 'NoneType' object has no attribute 'encode'`.
*Steps*: on the site as shipped, `frappe.sendmail(recipients=['rajesh@horizon.local'], subject='x', message='x')`.
*Expected*: Email Queue row. *Actual*: `OutgoingEmailError: Please setup default outgoing Email Account from Tools > Email Account`.
*Fix*: add the outgoing Email Account to `setup/demo_data.py` (or document it as a mandatory step in `06_deployment_and_migration_guide.md`) and assert it in `setup_dashboards`-style consistency checks. QA left "Horizon Notifications (QA outgoing)" on the site – replace with the real SMTP account.

### DEF-02 – Demo roles cannot receive batch- or serial-tracked items
*Severity* High · *Priority* P1 · *Risk* High · *Type* Configuration (role matrix)
*Impact*: RM-WELD-ROD / RM-PAINT-GREY (create_new_batch) and CMP-MOTOR-5HP (serial) cannot be received by procure@, dept.head@, priya@ or wh.delhi@.
*Steps*: as procure@ make PR from PUR-ORD-2026-00005 and submit.
*Expected*: Batch WR-xxxx auto-created, PR submitted. *Actual*: `frappe.PermissionError` from `Batch.insert()` – Batch DocType permissions are **Item Manager only**; Serial No create is Stock Manager only (procure lacks it); priya/wh.delhi (Stock Manager) cannot even map the PR: "does not have access to this document: Address - Mumbai Steel Traders-Billing" (Address read requires Supplier read).
*Fix*: grant Batch/Serial No create to Stock User (or add Item Manager to the receiving users) and give Stock roles Supplier/Customer read (or a custom Address permission) in `setup/roles.py`; add a receiving test as procure@.

### DEF-03 – Employee User Permissions leak into every DocType with an Employee link
*Severity* High · *Priority* P1 · *Risk* High · *Type* Configuration
*Impact*: priya@ (Operations Head) gets `PermissionError` on **read** of Production Audits whose `inspector` is not her own Employee record → cannot Review / Close Action (the designated role for the escalation workflow); neha@ (HR Manager) cannot create an Employee Checkin for another employee. The same applies to qc@, amit@, rajesh@.
*Steps*: `frappe.has_permission('Production Audit','read', doc=PA-2026-00002, user='priya@horizon.local')` → False; set inspector to HR-EMP-00014 → True.
*Fix*: on the Employee User Permission rows set `applicable_for` to the HRMS self-service DocTypes (or untick "Apply to all document types") in `setup/demo_data.py:setup_users`; Close Action on PA-2026-00002 was performed by Administrator as a stand-in.

### DEF-04 – Nobody but Administrator can dispatch serialised finished goods from HQ
*Severity* High · *Priority* P1 · *Risk* High · *Type* Configuration (role matrix)
*Impact*: amit@ (Sales User/Manager) can create DN-26-00001 but submit fails creating the Serial and Batch Bundle (no create permission: Purchase/Stock/Delivery/Manufacturing roles only); priya@ and wh.delhi@ (Stock roles) cannot create a DN: "does not have access to this document: Address - Tata Precision Works-Billing".
*Fix*: give a dispatch role Stock User + Customer read (Delivery User is a good fit) or add Serial and Batch Bundle permissions to Sales User; re-test E5/E7 as wh.delhi@.

### DEF-05 – Partial delivery of a volume-discounted line cannot be invoiced (auto Sales Invoice fails with over-billing)
*Severity* High · *Priority* P1 · *Risk* High · *Type* Design / code (`selling.on_submit_delivery_note`, pricing rules)
*Steps*: SAL-ORD-2026-00002 has SP-IMPELLER ×60 priced with PR-VOLUME-8 (qty ≥ 51) → 5,005. Deliver 30 (DN-26-00001). The mapped SI is re-priced by the pricing engine at qty 30 (no volume rule) → 5,525 → "Cannot overbill … SP-IMPELLER billed more than ₹1,50,150.00".
*Expected*: draft SI at SO/DN rates. *Actual*: Error Log 'Auto Sales Invoice failed for DN-26-00001'; no invoice; the same error for rajesh and even Administrator with `ignore_pricing_rule` (rate reset to price list). Tata cannot be invoiced for ₹5,37,243 of shipped goods.
*Fix*: set `ignore_pricing_rule = 1` on the SI mapped from the DN and keep DN rates (or set `apply_discount_on_rate`/"Validate Applied Rule"), or set an over-billing allowance; add a test with a partial delivery of a volume-priced row.

### DEF-06 – Auto Sales Invoice never runs for the users who actually submit Delivery Notes
*Severity* High · *Priority* P1 · *Risk* High · *Type* Code (`selling.on_submit_delivery_note`)
*Steps*: amit@ submits DN-26-00002 / DN-26-00003.
*Expected*: draft SI + comment. *Actual*: Error Log = `PermissionError` raised in `erpnext…delivery_note.make_sales_invoice` → `get_mapped_doc` because the submitter has no Sales Invoice *create* permission; the hook sets `si.flags.ignore_permissions` only after mapping.
*Fix*: call `make_sales_invoice(doc.name, ignore_permissions=True)` (the ERPNext function accepts it) and cover with a test running as a Sales User.

### DEF-07 – Stock-accuracy check reports every opening-stock bin as a mismatch and comments on Items daily
*Severity* High · *Priority* P2 · *Risk* Medium · *Type* Code (`tasks.hourly._flag_bin_mismatches`)
*Steps*: run `reorder_and_accuracy_check` → `bin_mismatches` 17 (e.g. CMP-BEARING-6205 bin 200 vs "SLE 0").
*Cause*: the query sums `Stock Ledger Entry.actual_qty`; Stock Reconciliation rows carry `actual_qty` 0 and only set `qty_after_transaction`. 14 Info comments were written on Item masters in one run (one per item per day).
*Fix*: compare the Bin to the latest `qty_after_transaction` per item/warehouse (or exclude bins whose last SLE is a Stock Reconciliation); clean the Info comments created today.

### DEF-08 – `recompute_reorder_levels` creates duplicate Item Reorder rows (Purchase next to Manufacture) incl. make-to-order equipment
*Severity* Medium · *Priority* P2 · *Risk* Medium · *Type* Code (`tasks.daily`)
*Steps*: run the job after consumption of SP items. Result: SP-IMPELLER / SP-SEAL-SET / SP-BELT-KIT now have **two** rows on HQ Finished Goods - HML (Manufacture 20/50 and Purchase 7/10 …) and HZ-PUMP-100 (make-to-order, no supplier) got a Purchase row level 1 / qty 1.
*Impact*: ERPNext's own Item validation forbids two rows for one warehouse; `reorder_item` will raise both a Purchase and a Manufacture MR for the same shortage; purchase requests for items Horizon manufactures.
*Fix*: skip items whose existing reorder row is Manufacture (or whose default BOM exists), key `existing` on (item, warehouse) regardless of request type, skip Equipment item group.

### DEF-09 – Reorder recompute collapses manual levels from a single day of history
*Severity* Medium · *Priority* P2 · *Risk* Medium · *Type* Design
*Evidence*: RM-STEEL-PLATE 400 → 42, RM-BOLT-M10/M8 500 → 3, RM-WELD-ROD 50 → 4, CMP-CONTACTOR 10 → 1 after one day's consumption averaged over a 90-day window. The hourly reorder will now stop raising MRs for most raw materials.
*Fix*: require a minimum history (e.g. 30 days with movements) before overriding, floor at the manual level, or write a separate "suggested level" field.

### DEF-10 – Pricing-rule precedence: docs/`rule_rate` compound, ERPNext adds
*Severity* Medium · *Priority* P2 · *Risk* Medium · *Type* Documentation / code (`selling.get_rule_rate`)
*Evidence*: SP-IMPELLER ×60 for Tata: engine discount 5 + 8 + 10 = 23 % → rate 5,005; `rule_rate` (compounded 0.95 × 0.92 × 0.90) = 5,112.90; `discount_over_rule_pct` shows a spurious 2.11 % and the 15 % approval threshold is measured against the wrong base. `docs/01` PR-4 states "discounts compound in that order".
*Fix*: either tick `apply_discount_on_rate` on the rules (then ERPNext compounds) or make `get_rule_rate` additive; align `docs/01`.

### DEF-11 – `valid_till` is empty on server-created quotations; customer default price list not applied server-side
*Severity* Medium · *Priority* P3 · *Risk* Medium · *Type* Code
*Evidence*: SAL-QTN-2026-00001 `valid_till` NULL (CRM Settings default_valid_till = 30 is applied only by the client script) – the "Horizon Quotation Expiring" notification can never fire for API/mapped quotations. Likewise a server-side SO for Delhi Metro took Standard Selling instead of the customer's North Selling (ERPNext behaviour; UI sets it).
*Fix*: set `valid_till` in `validate_discounts` when blank; optionally set `selling_price_list` from the customer in the same hook.

### DEF-12 – Manufacturing lead time explodes one BOM level only
*Severity* Medium · *Priority* P3 · *Risk* Medium · *Type* Code (`selling.get_mfg_lead_days`)
*Evidence*: HZ-PUMP-100 mfg_lead_days 3 (operations 180 min → 1 d + max lead of direct BOM items, which are sub-assemblies) although the item lead time is 21 d and its components have 14–28 d lead. Quotation expected_delivery_date 19-10-2026 for a pump ordered 16-10.
*Fix*: use the exploded BOM (`get_bom_items_as_dict`/`exploded_items`) or fall back to `Item.lead_time_days` when larger.

### DEF-13 – Row-level extra discount on a rule-priced row is silently reverted
*Severity* Low · *Priority* P3 · *Risk* Low · *Type* Design
*Evidence*: rate 4,000 entered on SP-IMPELLER (rule rate 5,525) saved as 5,525, `needs_discount_approval` 0 – the pricing engine re-applies rules on save. Only `additional_discount_percentage` triggers the approval. The SL-1 test-plan step is therefore not achievable as written; document the supported path or set "Validate Applied Rule" on the pricing rules.

### DEF-14 – Quality Inspector role has no permission on Quality Inspection
*Severity* Low · *Priority* P3 · *Risk* Low · *Type* Configuration
*Evidence*: DocPerms on Quality Inspection = Quality Manager only; qc@ works because it also holds Quality Manager. A pure inspector could not record incoming inspections. *Fix*: add Quality Inspector (create/write/submit) in `setup/roles.py`.

### DEF-15 – Approval Audit Report omits auto-escalations
*Severity* Low · *Priority* P4 · *Risk* Low · *Type* Report
*Evidence*: PUR-ORD-2026-00004 escalated by the job to Pending Procurement Manager (Info comment) – the report shows the state but no 'escalated' transition row, so hours-in-state for the skipped approver are lost. *Fix*: write the escalation as a Workflow comment or include Info comments starting with "Auto-escalated".

### DEF-16 – Server-created purchase documents carry the GST template but no tax rows
*Severity* Low · *Priority* P4 · *Type* Observation (ERPNext behaviour)
All eight POs have `taxes_and_charges` = Input GST template but `grand_total` = net (no tax rows); approval routing therefore ignores GST unless the PO is created in the UI. Document that approval limits are on the UI grand total (incl. GST) or append template taxes in a `before_insert` hook.
*Resolution*: documented, standard behaviour kept. In the UI India Compliance / ERPNext populate the template's rows (`set_taxes`), so approval limits apply to the grand total **including GST**; scripts and API clients that create Purchase Orders must append the template rows themselves (`erpnext.controllers.accounts_controller.get_taxes_and_charges`), as the QA scripts do for Sales Orders.

### DEF-17 – Sample bank statement has no GL counterpart
*Severity* Low · *Priority* P4 · *Type* Demo data
Bank Transactions reference invoices/payments (HML-SINV-0001, PINV-0007…) that do not exist; bank GL balance at 30-Sep is 0, so BRS-00001 shows a 12.5 L difference and `auto_reconcile_vouchers` matches nothing. Add the September vouchers to `demo_hr_finance.step_bank` or shrink the statement.

### DEF-18 – Leave Block List dates coincide with holidays
*Severity* Low · *Priority* P4 · *Type* Demo data / documentation
28–31 Dec 2026 are holidays in 'Horizon Holidays 2026-27', so HRMS rejects the application as "holidays" before the block list is consulted; HRMS only enforces block dates at approval (warning on application). Pick non-holiday block dates for the demo and adjust HR-2 in the test plan.

### DEF-19 – Budget e-mail has no PDF (daily summary has one); DEF-20 – Asset Register `last_maintenance_date` blank although maintenance cost 35,000 is shown; DEF-21 – Salary Cost Analysis has no Branch grouping (Department / Grade / Employment Type only)
*Severity* Low · *Priority* P4 – confirm against requirements, otherwise documentation updates.

## 5. Observations (not defects)

- Workflow Action e-mails (Frappe standard) also fail without an outgoing account and go to `admin@horizon.local`; Notification Log creation is asynchronous (worker) – evidence appears a few seconds after the transaction.
- GST on Horizon items is driven by the HSN master (pump 5 %, spares 12 %), not by the 18 % rows of the Sales Taxes templates; India Compliance correctly rejects CGST/SGST for the Delhi customer.
- Common Party Accounting is enabled: the ABC Corp PI is immediately netted against the receivable (ACC-JV-2026-00026), which is why Net Party Position shows only the net −412.
- `use_multi_level_bom` on the pump WO produced 8 Job Cards (sub-assembly operations) – correct ERPNext v15 behaviour but worth stating in the manufacturing SOP.
- Shipping DN-26-00003 from DEL Finished Goods with company GSTIN 27 (Mumbai) is what the brief asked for; for a real Delhi dispatch the Delhi GSTIN/branch address should be used.

## 6. Not covered

UI/list-view visibility for wh.delhi (PERM-1 UI part), Production Plan from SO (D1 optional), PO-11 (last-level never escalates), QI-3 (Fail → Non Conformance), SJ-6 (job failure wrapper), OB-1 (Mark for Scrap), Production/Inventory/Warehouse workspace cards, print of the thermal packing slip, the QI-driven DN gate with a Rejected inspection (only the audit path was exercised), `auto_reconcile_vouchers` with matching references, PF for an employee with B+DA 12,000 (no such employee), today's auto attendance materialisation (shift allowance window not yet reached).

## 7. Recommendation

Do not sign off for go-live until DEF-01 … DEF-06 are fixed: three of them are role-matrix gaps that make the receiving and dispatch flows impossible for the people who own them, and two make the "invoice follows every delivery" promise fail silently (Error Log only). DEF-07/08/09 should be fixed before the scheduler is enabled in production (they write to masters every hour/day). The remaining items are documentation or demo-data corrections. After fixes, re-run scripts B4, E5, E7, D4 as the intended users (procure@, wh.delhi@, amit@, priya@) and the regression suite.

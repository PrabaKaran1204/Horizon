# Horizon ERP - Test Plan and Evidence

Types: **unit** (automated, `bench --site horizon.local run-tests --app horizon_erp`),
**functional** (manual through the UI or `bench execute`), **permission**, **boundary**.
Automated coverage exists in `horizon_operations/test_buying.py`, `test_selling.py`,
`test_manufacturing.py`, `test_projects.py`, `horizon_quality/test_quality.py`,
`doctype/shipment_decision/test_shipment_decision.py`, `api/test_inventory_api.py`,
`tasks/test_tasks.py` and one `test_<report>.py` per report. The Evidence column is filled by the
lead from the test run (screenshot reference, test name, or log excerpt).

Demo users: dept.head@, procure@, rajesh@ (Finance Director), priya@ (Operations Head), amit@
(Sales Manager), wh.delhi@, qc@, neha@ (all `@horizon.local`, password `Horizon@123`).

## Purchasing

| ID | Scenario | Steps | Expected | Type | Evidence |
| --- | --- | --- | --- | --- | --- |
| PO-1 | INR 50,000 PO routing | As dept.head create PO for Mumbai Steel Traders, grand total 50,000; Submit for Approval; as dept.head Approve | `approval_level_required = Level 1`; state Pending Dept Head -> Approved (docstatus 1) in one step | functional | (to be filled from test run) |
| PO-2 | INR 3,00,000 PO routing | Same with grand total 3,00,000; Dept Head Approve; procure Approve | Level 2; Pending Dept Head -> Pending Procurement Manager -> Approved; email *Horizon PO Approval Request* to each role | functional | (to be filled from test run) |
| PO-3 | INR 7,00,000 PO routing | Same with 7,00,000; three approvals | Level 3; passes Pending Finance Director; rajesh approves | functional | (to be filled from test run) |
| PO-4 | Boundary at exactly 1,00,000 and 5,00,000 | `get_approval_level(100000)`, `get_approval_level(500000)`, `get_approval_level(500000.01)` | Level 2, Level 2, Level 3 (`test_approval_levels`) | boundary / unit | (to be filled from test run) |
| PO-5 | Rejected PO returns to creator | Procurement Manager clicks Reject on PO-2; creator clicks Revise | State Rejected -> Draft, PO editable, `pending_since` cleared | functional | (to be filled from test run) |
| PO-6 | Blacklisted supplier blocked | As dept.head create PO for ABC Supplies without override | Save blocked with "Blacklisted Supplier" message naming the reason (`test_blacklisted_without_override_blocked`) | unit / functional | (to be filled from test run) |
| PO-7 | Plain Purchase User cannot override | As dept.head tick Blacklist Override with a 30-char reason | PermissionError "Only a Procurement Manager or Finance Director may override" (`test_override_by_plain_purchase_user_blocked`) | permission | (to be filled from test run) |
| PO-8 | Override reason too short | As procure tick override with reason "urgent" | Blocked: reason must be >= 20 characters (`test_override_short_reason_rejected`) | boundary | (to be filled from test run) |
| PO-9 | Override by Procurement Manager routes to FD and logs | As procure tick override, reason >= 20 chars, save, submit for approval, approve through | `approval_level_required = Level 3`; Supplier Exception Log SEL-* created Pending with requester, amount, both reasons; rajesh receives bell + email; after final submit log status Approved with approver (`test_override_by_procurement_manager`, `test_exception_log_approved_on_submit`) | functional | (to be filled from test run) |
| PO-10 | Reminder after 24 h, escalation after 48 h | Set `pending_since` of a Pending Dept Head PO to now - 30 h; run `horizon_erp.tasks.hourly.po_approval_reminders`; set to now - 50 h; run again | First run: reminder to Department Head users, cache key set (no second reminder within 6 h); second run: state Pending Procurement Manager, comment "Auto-escalated after 48h", email to both roles (`test_po_approval_reminders_escalates_after_48h`) | unit / functional | (to be filled from test run) |
| PO-11 | Last level never escalates | PO in Pending Finance Director older than 48 h; run job | Reminder only; state unchanged | boundary | (to be filled from test run) |

## Receipt and quality

| ID | Scenario | Steps | Expected | Type | Evidence |
| --- | --- | --- | --- | --- | --- |
| PR-0 | Inspection items forced into QC Hold | PR for RM-STEEL-PLATE (inspection required) targeted at HQ Raw Materials - HML, plus a row for a non-inspection item; Save | Inspection row `warehouse` = HQ QC Hold - HML and `rejected_warehouse` = HQ Rejected - HML with a "Rows ... routed to HQ QC Hold" message; the other row keeps its warehouse; returns untouched (`test_inspection_item_rerouted_to_qc_hold`, `test_non_inspection_item_keeps_warehouse`, `test_return_receipt_not_rerouted`) | unit | (to be filled from test run) |
| PR-1 | Purchase Receipt without Quality Inspection | PR for RM-STEEL-PLATE into HQ QC Hold - HML, no QI, Submit | Blocked by Stock Settings (QI not submitted = Stop) | functional | (to be filled from test run) |
| PR-2 | 100 received, 10 rejected | PR 100 Kg into HQ QC Hold, `rejected_qty 10`, `rejected_warehouse HQ Rejected - HML`; QI template RM Steel Incoming, status Accepted; Submit | Stock Entry Material Transfer 90 Kg QC Hold -> HQ Raw Materials; Bin HQ Rejected +10; draft Purchase Return created; comment lists both links; if a submitted Purchase Invoice referenced the PR, a draft Debit Note for 10 | functional | (to be filled from test run) |
| PR-3 | Rejected QI blocks receipt | QI status Rejected on the PR row; Submit | Blocked (QI rejected = Stop) | functional | (to be filled from test run) |
| QI-1 | Evidence required | QI with `evidence_required = 1`, no attachment; Submit | Blocked "Evidence Missing" (`test_evidence_required_blocks_submit_without_attachment`) | unit | (to be filled from test run) |
| QI-2 | Rework result creates rework WO | QI on a Job Card of WO-A, `qc_result = Rework`, `sample_size 3`; Submit | Draft Work Order with `rework_of = WO-A`, qty 3, linked in `rework_work_order`; comment on QI (`test_rework_quality_inspection_creates_rework_wo`) | unit / functional | (to be filled from test run) |
| QI-3 | Fail result creates Non Conformance | Same with `qc_result = Fail` | Non Conformance under *Horizon Manufacturing QC*, status Open (`test_fail_quality_inspection_creates_non_conformance`) | unit | (to be filled from test run) |
| QI-4 | Quality Metrics report | Three completed WOs (one with a rework WO, one with a Production Audit scoring 65, one clean), a rework WO, and a PR + QI pair 1 h apart; run *Quality Metrics* filtered on the item group | First-pass yield 33.3 % (3 completed, 2 with issues); rework cost 25 % of production cost; defect reason counted once with a one-month trend series; inspection SLA 1.0 h, 100 % within 4 h; four KPIs in the summary (`test_quality_metrics`) | unit / functional | (to be filled from test run) |

## Selling

| ID | Scenario | Steps | Expected | Type | Evidence |
| --- | --- | --- | --- | --- | --- |
| SL-1 | 20 % discount needs approval | As amit's Sales User colleague: Quotation for Tata Precision Works, SP-IMPELLER rate 20 % under `rule_rate`, no reason; Save | Blocked "Discount Reason Required"; with reason >= 15 chars `needs_discount_approval = 1`, banner shown, only *Submit for Discount Approval* available; Sales Manager approves (`test_large_discount_needs_reason_and_manager`) | functional / unit | (to be filled from test run) |
| SL-2 | 10 % discount auto-approved | Same with 10 % | `needs_discount_approval = 0`, direct Submit (`test_small_discount_needs_no_approval`) | boundary | (to be filled from test run) |
| SL-3 | Sales User edits price list rate | Change `price_list_rate` manually as Sales User | PermissionError "Ad-hoc Pricing Not Allowed" (`test_manual_price_list_rate_blocked_for_sales_user`) | permission | (to be filled from test run) |
| SL-4 | Availability on Quotation | Add HZ-PUMP-100 qty 1 | `available_qty`, `mfg_lead_days` and `expected_delivery_date` populated; cell coloured (`test_quotation_availability_fields`) | functional | (to be filled from test run) |
| SL-5 | Sales Invoice without Delivery Note blocked | As Accounts User create SI for a stock item with no DN | PermissionError "Delivery Note Required" (`test_invoice_without_dn_blocked_for_accounts_user`) | permission | (to be filled from test run) |
| SL-6 | FD bypass logged | Same as rajesh | SI saves; Comment "Invoice without Delivery Note authorised by rajesh@horizon.local" (`test_invoice_without_dn_allowed_for_finance_director`) | permission | (to be filled from test run) |
| SL-7 | Short delivery needs deviation note; draft invoice auto-created | DN for 8 of 10 ordered without `deviation_notes`; then with | First save blocked "Deviation Notes Required"; after submit a draft Sales Invoice exists and comment links it; customer email *Horizon Delivery Dispatched* queued (`test_short_delivery_requires_deviation_notes_and_creates_invoice`) | functional | (to be filled from test run) |
| SL-8 | Signature requires Received By | DN with `customer_signature` set and blank `received_by` | Blocked (`test_signature_requires_received_by`) | boundary | (to be filled from test run) |
| SL-9 | DN blocked by open low audit until Shipment Decision | WO for the SO has a submitted Production Audit score 65 not Action Closed; create DN | Blocked "Shipment Decision Required" with link; create and submit Shipment Decision *Delay Delivery* with new date; DN now saves with `shipment_decision` linked and SO delivery dates moved (`test_delivery_gate_and_delay_decision`) | functional / unit | (to be filled from test run) |
| SL-10 | Shipment Decision validations | Ship Partial with qty 0 / qty > pending; Delay with date <= current; Invoice Now without finance approver; Concession without quality approver | Each blocked with the specific message (`test_decision_validations`) | boundary / unit | (to be filled from test run) |

## Manufacturing and audits

| ID | Scenario | Steps | Expected | Type | Evidence |
| --- | --- | --- | --- | --- | --- |
| MF-1 | Capacity overload blocked | WO HZ-CONV-200 (Line A, 8 h/unit) qty 30, planned window 1 day | Blocked "Line Capacity Exceeded" listing capacity 14.4 h, booked, available, options (other line / split / later date) (`test_over_capacity_blocked`) | unit / functional | (to be filled from test run) |
| MF-2 | Override requires Operations Head | Same WO, Capacity Override ticked by a Manufacturing User | PermissionError (`test_override_requires_operations_head`) | permission | (to be filled from test run) |
| MF-3 | Override by Operations Head | As priya tick override, reason >= 10 chars | WO saves; audit Comment "Capacity override by priya ... required X h, available Y h" (`test_override_by_operations_head`) | functional | (to be filled from test run) |
| MF-4 | Small order fits | WO qty 1 | Saves without message; `required_machine_hours = 8.75` (`test_small_order_fits`) | boundary | (to be filled from test run) |
| PA-1 | Audit 65 requires photo | Production Audit score 65, no photo row; Save | Blocked "Photo Evidence Required" (`test_low_score_requires_photo`) | boundary | (to be filled from test run) |
| PA-2 | Audit 65 escalates and blocks completion | Add photo, Submit; then try Manufacture Stock Entry for the WO | Quality Action created and linked; `escalated = 1`; priya gets bell + email; Stock Entry blocked "Production Audit Open"; after Review -> Close Action (requires corrective action) the Stock Entry submits (`test_low_score_escalates_and_gates_manufacture`) | functional / unit | (to be filled from test run) |
| PA-3 | Audit 85 not escalated | Score 85, Submit | No Quality Action, no escalation (`test_high_score_not_escalated`) | boundary | (to be filled from test run) |
| PA-4 | Score outside 0-100 | Score 101 | Blocked "Invalid Score" | boundary | (to be filled from test run) |

## API

| ID | Scenario | Steps | Expected | Type | Evidence |
| --- | --- | --- | --- | --- | --- |
| API-1 | Success | `POST /api/method/horizon_erp.api.inventory.get_inventory_snapshot` `{"warehouse":"Delhi DC","filter_by_criticality":true}` with token | 200, `warehouse = Delhi DC - HML`, `warehouses_included` = DEL leaves, items with A/B criticality only, `summary`, `X-RateLimit-*` headers; Inventory API Log row Success (`test_group_warehouse_aggregates_children`, `test_filter_by_criticality`) | functional / unit | (to be filled from test run) |
| API-2 | Invalid warehouse | `{"warehouse":"Nowhere DC"}` | 404 `invalid_warehouse` with hint; log row Invalid Input (`test_invalid_warehouse_returns_404`) | unit | (to be filled from test run) |
| API-3 | Missing warehouse | `{}` | 400 `missing_warehouse` (`test_missing_warehouse_returns_400`) | unit | (to be filled from test run) |
| API-4 | Rate limit | 101 calls within the hour for one key | Calls 1-100 return 200; call 101 returns 429 with `retry_after_seconds`, `Retry-After` header, log row Rate Limited (`test_rate_limit_returns_429_and_logs`, `test_rate_limit_default_is_100_per_hour`) | boundary / unit | (to be filled from test run) |
| API-5 | Database failure | `_simulate_failure=1` with `developer_mode` on | 503 `temporary_failure`, `retry_after_seconds 30`, Error Log entry, log row Error (`test_simulated_failure_returns_503_and_logs_error`) | unit | (to be filled from test run) |
| API-6 | Permission denied is still logged | Call as a user without `Bin` read | 403; Inventory API Log row persists despite rollback (`test_permission_denied_log_survives_rollback`) | permission / unit | (to be filled from test run) |
| API-7 | Client retry schedule | `fetch_snapshot` against a fake session returning 429, 503, connection error, 200 | Sleeps 1 s, 5 s, 25 s then succeeds; 404 raises immediately (`test_retries_on_429_then_5xx_then_connection_error_with_fixed_backoff`, `test_does_not_retry_other_4xx`) | unit | (to be filled from test run) |
| API-8 | Usage report | Open *API Usage Report* for last 7 days | Rows per client/endpoint with calls, success, failed, rate limited, avg and P95 ms; chart of calls per day | functional | (to be filled from test run) |

## Scheduled jobs

| ID | Scenario | Steps | Expected | Type | Evidence |
| --- | --- | --- | --- | --- | --- |
| SJ-1 | Reorder level recompute inserts Item Reorder | Item with 90-day consumption and no reorder row; run `tasks.daily.recompute_reorder_levels` | Item Reorder row inserted with `level = ceil(usage x lead x (1 + factor))`, `safety_stock_factor` written from criticality (`test_recompute_reorder_levels_inserts_row`) | unit | (to be filled from test run) |
| SJ-2 | Hourly reorder creates Material Request | Bin below reorder level; run `tasks.hourly.reorder_and_accuracy_check` | Material Request (Purchase) created by ERPNext reorder; summary dict returned (`test_reorder_and_accuracy_check_returns_keys`) | functional | (to be filled from test run) |
| SJ-3 | Quality-deadline conflict detection | SO due in 2 days with open WO, no Shipment Decision; run `detect_quality_deadline_conflicts` | SO in `flagged`; one alert to Sales Manager / Operations Head / Quality Manager; second run same day sends nothing (`test_detect_quality_deadline_conflicts`) | unit | (to be filled from test run) |
| SJ-4 | Daily summary | `bench execute horizon_erp.tasks.daily.send_daily_summary` | Email to rajesh and priya with HTML + PDF (PDF skipped with warning if wkhtmltopdf missing) (`test_send_daily_summary`) | functional | (to be filled from test run) |
| SJ-5 | Monthly budget report | `bench execute horizon_erp.tasks.monthly.send_budget_report` | Email to Department Heads and FD; rows > 10 % flagged red; top 3 drivers per cost centre; year-end run-rate forecast columns (`run_rate_forecast`, `forecast_variance`, `forecast_variance_pct`) with rows forecast > budget + 10 % flagged (`test_send_budget_report`, `test_budget_forecast_formula`) | functional / unit | (to be filled from test run) |
| SJ-6 | Job failure handling | Force an exception inside a job | Error Log, alert to System Managers, retry marker set and consumed on next run (`test_horizon_job_wrapper_logs_and_sets_retry_marker`) | unit | (to be filled from test run) |

## Permissions, HR, finance

| ID | Scenario | Steps | Expected | Type | Evidence |
| --- | --- | --- | --- | --- | --- |
| PERM-1 | Delhi warehouse user sees only Delhi stock | Log in as wh.delhi; open Stock Entry list, Bin list, Stock Balance report, Delivery Note new form warehouse picker | Only `DEL Finished Goods - HML` / `DEL Goods In Transit - HML` offered; HQ documents hidden; rajesh sees all | permission | (to be filled from test run) |
| PERM-2 | Delhi user and the API | wh.delhi API key, request `HQ Raw Materials`; then request `All Warehouses - HML` | **Fixed**: 403 `warehouse_not_permitted` logged as Error (`test_warehouse_user_permission_denies_other_leaf`); the group request returns only the Delhi leaves with the HQ leaves in `warehouses_excluded` (`test_warehouse_user_permission_trims_group`) | permission | (to be filled from test run) |
| HR-1 | Leave over balance blocked | Leave Application Casual Leave 13 days for an employee with 12 allocated | Standard validation blocks (insufficient balance) | functional | (to be filled from test run) |
| HR-2 | Leave on blocked date blocked | Leave Application including 29 Dec 2026 | Blocked by Leave Block List *Plant Shutdown Dec 2026* | functional | (to be filled from test run) |
| HR-3 | Late entry flag | Employee Checkin 06:08 on Morning Shift; process auto attendance | Attendance `late_entry = 1` (8 min > 5 min grace); 06:04 check-in not flagged | boundary | (to be filled from test run) |
| PY-1 | PF ceiling | Salary slip for Grade S3 (base 75,000: Basic 30,000 + DA 3,000) and Grade W1 (base 18,000 -> Basic + DA 19,800) | PF deduction 1,800 for both (ceiling), employer PF 1,800; for an employee with Basic + DA 12,000, PF = 1,440 | boundary | (to be filled from test run) |
| PY-2 | ESI threshold | Gross 21,000 vs 21,001 | 0.75 % ESI vs 0 | boundary | (to be filled from test run) |
| PY-3 | Payroll per branch posts with Branch dimension | Run payroll for last month | Two Payroll Entries (Mumbai HQ, Delhi DC), accrual journals carry branch; slips for all three structures | functional | (to be filled from test run) |
| AS-1 | Depreciation JE auto | Asset *CNC Lathe 2m* submitted; run `post_depreciation_entries` (or wait for the daily job) | Depreciation Entry journals for due months, Dr Depreciation / Cr Accumulated Depreciation - Production Equipment, branch Mumbai HQ; NBV in Asset Register with Maintenance | functional | (to be filled from test run) |
| BG-1 | Budget Stop on annual overrun | Journal Entry debiting Marketing Expenses on Sales - HML for more than the remaining annual budget | Blocked by Budget (action Stop); a Material Request over budget only warns | functional / boundary | (to be filled from test run) |
| BG-2 | 90 % alert | Actuals at 91 % of an account budget; run `budget_threshold_alerts` | One alert per (budget, account) per day to Department Heads and FD (`test_budget_threshold_alerts`) | unit | (to be filled from test run) |
| FIN-1 | Net Party Position | Sales Invoice 10 L on Customer ABC Corp, Purchase Invoice 5 L on Supplier ABC Corp | Report row: receivable 10 L, payable 5 L, net 5 L, direction Net Receivable, settlement 5 L (`test_execute_default_filters`) | functional | (to be filled from test run) |
| FIN-2 | Data Validation Report | Customer with GSTIN `27AABCU9602H1Z0` | Row "GSTIN fails format / checksum validation", severity High (`test_gstin_validation`) | unit | (to be filled from test run) |
| FIN-3 | Bank Unmatched Aging | Two submitted Bank Transactions on a test bank account, 40 and 3 days old, unreconciled; run the report as on today, then as on 10 days ago | Rows aged 40 d (bucket 31-60, red) and 3 d (0-7); summary unmatched 2 / value 1,500 / older than 30 d = 1 with the bank GL balance; as-on 10 days ago hides the newer one and ages the older to 30 d (`test_rows_aging_and_summary`, `test_as_on_before_transaction_excludes_it`) | unit | (to be filled from test run) |
| WS-1 | Horizon Production workspace | Open *Horizon Production*; create an open WO with a past `planned_end_date` | Cards Work Orders In Progress, Work Orders Overdue (+1), Line Utilisation Today %, Open Low-Score Audits and the Work Orders by Status donut render; `setup_dashboards` reports all workspaces consistent (`test_dashboards`) | functional / unit | (to be filled from test run) |
| OB-1 | Mark for Scrap | Select two rows in Inventory Obsolescence Analysis, reason Obsolete, 100 % | One draft Stock Entry Material Transfer to HQ Scrap - HML (`test_mark_for_scrap_creates_draft_stock_entry`) | functional / unit | (to be filled from test run) |

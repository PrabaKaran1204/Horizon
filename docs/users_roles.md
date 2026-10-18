All test users: Horizon@Test123

# Horizon ERP - users, roles and permissions (site `horizon.local`, read from the database 2026-10-17)

Source: `tabUser` (enabled = 1, user_type = System User, Guest excluded), `tabHas Role`, `tabUser Permission`,
`tabWorkflow` / `tabWorkflow Transition`. Passwords were set with `frappe.utils.password.update_password`;
`POST /api/method/login` returned HTTP 200 for all 10 users below (no failures).

## Users

| User | Full name | Persona (assignment) | Business roles (Horizon + key ERPNext) | User Permissions | Workflow steps they act on |
| --- | --- | --- | --- | --- | --- |
| `Administrator` | Administrator | System administrator | All roles (System Manager) | none | Every transition (Administrator holds all roles) |
| `admin@horizon.local` | Administrator | none (second admin account) | 46 standard roles incl. System Manager, Accounts / Stock / Sales / Purchase / HR / Manufacturing / Quality Manager; **no Horizon role** | none | Discount Approval: Approve / Reject (Sales Manager); PO: Submit for Approval / Revise (Purchase User); Payment: Submit (Accounts User); Production Audit: Review (Quality Manager) |
| `rajesh@horizon.local` | Rajesh Menon | **Finance Director Rajesh** | Finance Director, Accounts Manager, Accounts User, Purchase Manager, Leave Approver, Employee | Company = Horizon Manufacturing Ltd (all doctypes); Employee = HR-EMP-00013 (Employee, Salary Slip, Expense Claim, Tax Exemption Declaration) | PO Approval: *Pending Finance Director* -> Approve / Reject; Payment Approval: *Pending Finance Director* -> Approve / Reject (>= INR 1 L); Payment: Submit / Submit for Approval (Accounts User) |
| `priya@horizon.local` | Priya Nair | **Operations Head Priya** | Operations Head, Manufacturing Manager / User, Stock Manager / User, Leave Approver, Employee | Company = HML; Employee = HR-EMP-00014 (self-service doctypes) | Production Audit: *Submitted* -> Review; *Reviewed* -> Close Action (score >= 70 or corrective action) |
| `amit@horizon.local` | Amit Shah | **Sales Director Amit** (role in system: Sales Manager) | Sales Manager, Sales User, Employee | Company = HML; Employee = HR-EMP-00015 (self-service doctypes) | Discount Approval (Quotation and Sales Order): *Pending Discount Approval* -> Approve / Reject; Draft -> Submit / Submit for Discount Approval |
| `neha@horizon.local` | Neha Verma | **HR Manager Neha** | HR Manager, HR User, Employee | Company = HML; Employee = HR-EMP-00016 (self-service doctypes) | none (no HR workflow configured; leave approval is the standard Leave Approver field) |
| `wh.delhi@horizon.local` | Delhi Warehouse | **Warehouse manager - Delhi DC** | Warehouse Manager, Stock Manager, Stock User | **Warehouse = Delhi DC - HML** (all doctypes, default) | none |
| `dept.head@horizon.local` | Dept Head | **Department head** | Department Head, Purchase User, Stock User | none | PO Approval: *Pending Dept Head* -> Approve (< INR 1 L -> Approved, else -> Pending Procurement Manager) / Reject; Draft -> Submit for Approval; Rejected -> Revise |
| `procure@horizon.local` | Procurement | **Procurement manager** | Procurement Manager, Purchase Manager, Purchase User, Stock User | none | PO Approval: *Pending Procurement Manager* -> Approve (<= INR 5 L -> Approved, else / blacklist override -> Pending Finance Director) / Reject; Draft -> Submit for Approval; Rejected -> Revise |
| `qc@horizon.local` | Kavita Joshi | Quality inspector (extra, not a named persona) | Quality Inspector, Quality Manager, Manufacturing User, Stock User, Employee | Company = HML; Employee = HR-EMP-00010 (self-service doctypes) | Production Audit: Draft -> Submit (Quality Inspector); *Submitted* -> Review (Quality Manager) |

Disabled System Users not included: `qa.accounts@`, `qa.api@`, `qa.sales@horizon.local`.

## Persona coverage

| Persona | Matching user | Note |
| --- | --- | --- |
| Finance Director Rajesh | rajesh@horizon.local | Match |
| Operations Head Priya | priya@horizon.local | Match |
| Sales Director Amit | amit@horizon.local | Match; the system role is *Sales Manager* (no "Sales Director" role exists) |
| HR Manager Neha | neha@horizon.local | Match |
| Warehouse manager - Delhi | wh.delhi@horizon.local | Match |
| Warehouse manager - Mumbai HQ | **none** | No Mumbai warehouse user exists; not created (per instruction). HQ visibility is only shown through unrestricted users |
| Department head | dept.head@horizon.local | Match |
| Procurement manager | procure@horizon.local | Match |

## Workflows (active)

| Workflow | DocType | Transitions (state -> action -> next, role) |
| --- | --- | --- |
| Horizon PO Approval | Purchase Order | Draft -> Submit for Approval -> Pending Dept Head (Purchase User); Pending Dept Head -> Approve -> Approved if < 1 L and no override, else Pending Procurement Manager (Department Head); Pending Procurement Manager -> Approve -> Approved if <= 5 L and no override, else Pending Finance Director (Procurement Manager); Pending Finance Director -> Approve -> Approved (Finance Director); every Pending state -> Reject -> Rejected; Rejected -> Revise -> Draft (Purchase User) |
| Horizon Discount Approval | Quotation | Draft -> Submit -> Approved if no discount approval needed / Submit for Discount Approval -> Pending Discount Approval (Sales User); Pending -> Approve -> Approved, Reject -> Draft (Sales Manager) |
| Horizon Discount Approval - Sales Order | Sales Order | Same as the Quotation workflow |
| Horizon Payment Approval | Payment Entry | Draft -> Submit -> Approved if < 1 L / Submit for Approval -> Pending Finance Director (Accounts User); Pending FD -> Approve / Reject (Finance Director) |
| Horizon Production Audit | Production Audit | Draft -> Submit -> Submitted (Quality Inspector); Submitted -> Review -> Reviewed (Quality Manager, Operations Head); Reviewed -> Close Action -> Action Closed (Operations Head, needs score >= 70 or a corrective action) |

## Purchase Orders by workflow state (for approver screenshots)

Only `PUR-ORD-2026-00004` (Pune Electricals, INR 1,80,000) is awaiting action, in *Pending Procurement Manager*.
No PO is currently in *Pending Dept Head* or *Pending Finance Director*; all other 11 POs are *Approved*.

## Permission findings from the screenshot run (2026-10-18)

| # | Finding | Evidence | Status |
| --- | --- | --- | --- |
| 1 | Every non-admin persona got "Not permitted" on the Horizon workspaces (Horizon ERP home, Selling, Inventory, Manufacturing, HR & Payroll ...): Frappe only opens a workspace whose module owns a DocType the user can read, and most Horizon modules own none | `get_desktop_page` HTTP 403 for priya / amit / neha / wh.delhi | **Fixed** (commit c3f76e8): workspace roles + `horizon_erp/overrides/desktop.py` (desk page, sidebar, boot), test `horizon_erp/tests/test_workspace_access.py` |
| 2 | Finance Director cannot run Stock Balance: prepared report fails with "No permission to read UOM" | `screenshots/admin_fd_stock_balance_error.png` (before), `role_finance_director_2.png` (after) | **Fixed**: UOM read for Accounts Manager / Finance Director (Custom DocPerm), commit 2bedfb7 |
| 3 | Delhi warehouse manager sees HQ note DN-26-00001 in the Delivery Note list (warehouse only on item rows, `set_warehouse` empty); opening it is refused | `role_warehouse_delhi_9.png` (before), `role_warehouse_delhi_3.png` (after: 4 Delhi notes) | **Fixed** (commit 2bedfb7, test `horizon_erp/horizon_stock/tests/test_warehouse_permissions.py`): row-level `permission_query_conditions` on Delivery Note, Purchase Receipt, Stock Entry |
| 4 | Inventory Obsolescence Analysis as wh.delhi: rows filtered to Delhi, but the summary shows company totals (₹7,37,756 / ₹2,65,950 / 17 items) | `role_warehouse_delhi_8.png` (after: ₹5,500 / 1 item) | **Fixed** (commit 2bedfb7, test `horizon_erp/horizon_stock/tests/test_warehouse_permissions.py`) |
| 5 | Number cards *Aging Stock Value (90d+)* and *Stock Turnover (90d)* return company-wide values to wh.delhi (raw queries, no warehouse permission) | `role_warehouse_delhi_6.png` (after: ₹0.00 / 2) | **Fixed** (commit 2bedfb7, test `horizon_erp/horizon_stock/tests/test_warehouse_permissions.py`) |
| 6 | Forecast vs Actual Demand returns 12 item rows to wh.delhi with no warehouse scoping (likely company-wide demand) | API run as wh.delhi (after: 3 Delhi rows) | **Fixed** (commit 2bedfb7, test `horizon_erp/horizon_stock/tests/test_warehouse_permissions.py`) |

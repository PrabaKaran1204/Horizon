# Pending notes for the lead (receipt / QC change, 17-Oct-2026)

docs/01, docs/02 (ADR-2) and README were updated directly after the workspace developer finished.
Remaining items are in files owned by the workspace work and were left untouched:

1. `docs/08_screenshot_guide.md`
   - Row 6 (warehouse tree): replace "Receiving goes to *HQ QC Hold*" with "Receiving goes to
     *HQ Raw Materials* (Purchase Receipt submit = GRN); *HQ QC Hold* is used only by the optional
     QC Hold mode".
   - Row 20 (Purchase Receipt with QC Hold / Rejected): point at `/app/purchase-receipt/PR-26-00009`
     (user procure@horizon.local): 20 Kg received, Accepted Warehouse HQ Raw Materials - HML 18,
     Rejected Warehouse HQ Rejected - HML 2, QI MAT-QA-2026-00007, draft return PR-26-00010. Retitle
     "Purchase Receipt (GRN) with Rejected qty".
   - Optional new row: `/app/supplier-scorecard` (Administrator) - one standard Supplier Scorecard
     per demo supplier.
2. Workspaces (`horizon_buying/workspace/horizon_buying`, `horizon_quality_management/workspace/horizon_quality`):
   add a link to the standard DocType *Supplier Scorecard* next to the *Supplier Quality Scorecard*
   report (then export fixtures as you normally do).

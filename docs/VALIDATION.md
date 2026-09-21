# Validation report — 21 September 2026

## Result

**39 automated tests passed.** Final recorded run completed in 2.635 seconds on the bundled Windows Python runtime. Raw output: `test-results.txt`. Run again with `python -m unittest discover -s tests -v` from the project root. No external package or API credential is required.

Tests include engine arithmetic and constraints, contract validation, time/expiry/receipt handling, shared budget, common supplier horizon, transactional approval, rejected/stale/superseded decisions, concurrent approval, repeated export, identical-snapshot duplicate protection, database reopening, and the full HTTP planning/approval/export workflow.

## Browser verification

Verified the actual local application in the Codex browser:

1. Load synthetic demo and view PENDING recommendations.
2. See one purchase line (200 boxes, IDR 3,000,000), IDR 2,000,000 remaining budget, no purchase for the adequately stocked SKU, and a blocked cold-chain SKU.
3. Confirm standard and fast suppliers are both sized to 200 boxes over the same 14-day horizon; their illustrative purchase costs are IDR 3,000,000 and IDR 3,300,000.
4. Confirm Export requisition is disabled before approval.
5. Enter `Demo QA reviewer` and an explicitly synthetic test reason; approve the draft.
6. Confirm APPROVED status, disabled decision buttons and enabled export.
7. Export; observe “Draft requisition exported. Nothing has been sent externally.”

The browser screenshot was inspected for the initial responsive layout. Recommendation and approval results were verified through the rendered accessibility/DOM state. This is not a complete accessibility, mobile-device or cross-browser certification.

## Issues found and fixed during implementation

- SQLite connections initially remained open after transaction context exit, causing Windows file-handle cleanup failures. Connections now close explicitly.
- Supplier-specific sizing horizons initially biased the comparison against shorter-lead options. All options now use a common sizing and comparison horizon, covered by a regression test.
- Added active-run checks and a unique exported-snapshot constraint to prevent stale approvals and duplicate draft exports from identical reimports.
- Two early test expectations were corrected: MOQ 251 in packs of 12 rounds to 252, and removing an inbound receipt can change the chosen supplier, so the invariant is worse baseline availability rather than monotonic selected order quantity.

## Limits of this evidence

This validates the bounded synthetic vertical slice, not real pharmaceutical operating performance, regulatory compliance, production security, model calibration or ERP interoperability. No actual distributor data or patient information was used. No upstream repository was merged. Upstream CI findings and a locally reproduced RAG grounding defect are documented separately in `AUDIT.md`; upstream suites were not rerun locally.

The SQLite ledger is a local demo, not a tamper-proof enterprise audit store. Authenticated roles, budget reservations across changed snapshots, real-data reconciliation, forecast backtesting, cold-chain qualification and ERP sandbox acceptance remain roadmap gates.

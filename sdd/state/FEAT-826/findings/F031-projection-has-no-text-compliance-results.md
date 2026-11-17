---
id: F031
query_id: Q024
type: grep
intent: "Follow-up (cross-lane note of F018/F020): which legacy per-shelf fields the projection fills for a zone shelf."
executed_at: 2026-11-06T16:20:00Z
duration_ms: 300
parent_id: F020
depth: 2
lanes: [codebase]
merged_from: []
---

# F031 — The legacy projection never sets `text_compliance_results`; a zone shelf carries only expected/found/missing/unexpected product lists

## Summary

A grep of `comparison/projection.py` for `text_compliance_results|missing_products|found_products|expected_products` returns the docstring (lines 75-77) and the four keyword arguments at lines 169-172 only: `expected_products`, `found_products`, `missing_products`, `unexpected_products`. `text_compliance_results` is never assigned, so the "Text Requirements" block of the FlowTask report (F018) cannot print for any shelf produced by this projection, and for a zone shelf the remaining lists are empty except for illumination failures (F020).

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py`
  lines: 169-172
  symbol: `(ComplianceResult keyword arguments)`
  excerpt: |
    expected_products=expected,
    found_products=found,
    missing_products=missing,
    unexpected_products=unexpected,

## Notes

- This closes the item F020 left unverified ("no `text_compliance_results` in the lines read").
- Consequence for the ticket: in March the UI showed "Text Requirements: ✅ 'GOODBYE CARTRIDGES'"; with the current projection that block is absent for these rows.

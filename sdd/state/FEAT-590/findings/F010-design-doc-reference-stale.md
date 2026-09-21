---
id: F010
query_id: Q010
type: read
intent: Verify the proposal's reference to claude/handle-only-execution-design.md
executed_at: 2026-09-21T22:14:00Z
depth: 0
parent_id: null
---

# F010 — Design doc reference is stale

## Summary

The proposal references `claude/handle-only-execution-design.md` as context — this file DOES NOT EXIST on disk. The actual specification is at `sdd/specs/execution-plan-tool.spec.md` (FEAT-419). The hardening spec is at `sdd/specs/plan-then-execute-hardening.spec.md` (FEAT-585). The proposal's §9 "Pending per the plan-then-execute doc" items should reference these specs instead.

## Citations

- path: `claude/handle-only-execution-design.md`
  excerpt: |
    NOT FOUND — file does not exist on disk

- path: `sdd/specs/execution-plan-tool.spec.md`
  excerpt: |
    Feature Specification: ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent (FEAT-419)

- path: `sdd/specs/plan-then-execute-hardening.spec.md`
  excerpt: |
    Feature Specification: Plan-then-Execute Hardening (FEAT-585)

## Notes

The design doc was likely the working document that became the FEAT-419 spec. The enriched proposal should update all references to point at the current specs.

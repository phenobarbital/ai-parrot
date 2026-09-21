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

The proposal referenced `claude/handle-only-execution-design.md` — the actual file is at `artifacts/proposals/handle-only-execution-design.md`. The canonical specifications are `sdd/specs/execution-plan-tool.spec.md` (FEAT-419) and `sdd/specs/plan-then-execute-hardening.spec.md` (FEAT-585). The proposal's §9 "Pending per the plan-then-execute doc" items should reference these specs instead.

## Citations

- path: `artifacts/proposals/handle-only-execution-design.md`
  excerpt: |
    Original design doc (was referenced as claude/handle-only-execution-design.md)

- path: `sdd/specs/execution-plan-tool.spec.md`
  excerpt: |
    Feature Specification: ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent (FEAT-419)

- path: `sdd/specs/plan-then-execute-hardening.spec.md`
  excerpt: |
    Feature Specification: Plan-then-Execute Hardening (FEAT-585)

## Notes

The design doc at `artifacts/proposals/` was the working document that became the FEAT-419 spec. The enriched proposal now references the correct path and the current specs.

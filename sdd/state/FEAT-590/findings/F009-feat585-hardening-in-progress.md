---
id: F009
query_id: Q009
type: read
intent: Check FEAT-585 scope for conflicts with delegate node additions
executed_at: 2026-09-21T22:13:00Z
depth: 0
parent_id: null
---

# F009 — FEAT-585 hardening actively in progress

## Summary

FEAT-585 (plan-then-execute hardening) has 16 tasks (TASK-3589..3604) covering PlanFlow checkpointing, plan_resume, plan_repair, and versioned artifacts. Its Non-Goals section explicitly excludes "changes to `packages/ai-parrot/src/parrot/bots/flows/plan/`, including its models, validator, guards, compiler and argument-resolution semantics." This means the delegate can safely extend those files without conflicting with FEAT-585, and could later benefit from FEAT-585's checkpointed execution recovery.

## Citations

- path: `sdd/specs/plan-then-execute-hardening.spec.md`
  excerpt: |
    ### Non-Goals (explicitly out of scope)
    - Changes to `packages/ai-parrot/src/parrot/bots/flows/plan/`, including its models,
      validator, guards, compiler and argument-resolution semantics.

- path: `sdd/tasks/index/plan-then-execute-hardening.json`
  excerpt: |
    FEAT-585, 16 tasks (TASK-3589..3604), status: in-progress

## Notes

FEAT-585 focuses on the ExecutionPlanToolkit layer (recovery, repair, checkpointing) above the plan module. The delegate operates at the plan module level (new node type, new model, validator extensions). No overlap. However, once FEAT-585 lands, a delegate node inside a checkpointed PlanFlow would get free resume/recovery — a sequencing benefit worth noting.

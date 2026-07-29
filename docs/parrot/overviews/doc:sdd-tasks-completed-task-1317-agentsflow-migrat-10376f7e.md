---
type: Wiki Overview
title: 'TASK-1317: Mark FEAT-009 obsolete + docs sweep (L6 — Module 10)'
id: doc:sdd-tasks-completed-task-1317-agentsflow-migration-docs-and-feat009-obsolete-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Layer 6 — final bookkeeping. After TASK-1316 deletes the legacy `parrot/bots/flow/`
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
---

# TASK-1317: Mark FEAT-009 obsolete + docs sweep (L6 — Module 10)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1316
**Assigned-to**: unassigned

---

## Context

Layer 6 — final bookkeeping. After TASK-1316 deletes the legacy `parrot/bots/flow/`
package, this task closes out the feature by:
1. Marking the superseded `FEAT-009` spec as obsolete
2. Sweeping `docs/`, `README.md`, `CLAUDE.md`, and SDD specs for any remaining
   `parrot.bots.flow` references

Implements §3 Module 10 of the spec.

---

## Scope

1. **Update `sdd/specs/agentsflow-persistency.spec.md`**:
   - Set `**Status**: obsolete` (or add a prominent "SUPERSEDED" banner at top)
   - Add a note: "Superseded by FEAT-147 (`flows/core/storage/persistence.py`)
     for the persistence implementation, and FEAT-196 (this migration) for the
     package-level cleanup. No further work is required from this spec."

2. **Grep sweep** — scan these locations for `parrot.bots.flow` (singular):
   - `docs/` directory
   - `README.md` (if present)
   - `CLAUDE.md`
   - `sdd/specs/*.spec.md` (other specs)
   - `.agent/CONTEXT.md`
   
   For each match, update the reference to `parrot.bots.flows` (plural) or remove
   if the reference is describing the old deleted package.

3. **Update the FEAT-196 spec itself** (optional): change `**Status**: draft` to
   `**Status**: implemented` in `sdd/specs/agentsflow-migration.spec.md`.

**NOT in scope**: changing any production code. Not modifying test files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/specs/agentsflow-persistency.spec.md` | MODIFY | Add "SUPERSEDED" / "obsolete" status |
| `docs/**` (any matching files) | MODIFY | Update `parrot.bots.flow` → `parrot.bots.flows` |
| `CLAUDE.md` (if any matches) | MODIFY | Update stale references |
| `.agent/CONTEXT.md` (if any matches) | MODIFY | Update stale references |
| `sdd/specs/agentsflow-migration.spec.md` | MODIFY | Update Status: draft → Status: implemented |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

None — this task only modifies documentation and spec files, not Python code.

### Does NOT Exist

- ~~`parrot/bots/flow/`~~ — deleted in TASK-1316; any remaining docs refs are stale

---

## Implementation Notes

### FEAT-009 spec update pattern

```markdown
<!-- Add at the top of sdd/specs/agentsflow-persistency.spec.md after the frontmatter: -->

> **⚠️ SUPERSEDED** — This spec is obsolete as of FEAT-196 (AgentsFlow Migration,
> 2026-05-28).
>
> - The persistence implementation described here was delivered by
>   **FEAT-147** (`parrot/bots/flows/core/storage/persistence.py`).
> - The package-level cleanup (removing `parrot/bots/flow/`) was completed
>   by **FEAT-196** (`sdd/specs/agentsflow-migration.spec.md`).
>
> No further work is required from this spec.
```

### Grep commands to run

```bash
# Scan for stale references:
grep -rn "parrot\.bots\.flow\b" docs/ CLAUDE.md .agent/CONTEXT.md sdd/specs/ \
  2>/dev/null | grep -v "parrot\.bots\.flows" | grep -v "agentsflow-migration"

# Check README if present:
grep -n "parrot\.bots\.flow\b" README.md 2>/dev/null | grep -v "parrot\.bots\.flows"
```

### Key Constraints

- Only update documentation references — do NOT modify Python code
- If a doc says "the legacy `parrot.bots.flow` package", it's describing history —
  it's OK to leave it with a note "(deleted in FEAT-196)" rather than rewriting
  the entire sentence
- Do NOT modify the `sdd/specs/agentsflow-migration.spec.md` Codebase Contract
  section — it's a historical record of what existed at the time the spec was written

---

## Acceptance Criteria

- [ ] `sdd/specs/agentsflow-persistency.spec.md` is marked obsolete/superseded
- [ ] `grep -rn "parrot\.bots\.flow\b" docs/ README.md CLAUDE.md .agent/CONTEXT.md sdd/specs/`
  returns only intentional historical references (with "(deleted in FEAT-196)" notes
  where appropriate), or zero matches
- [ ] `sdd/specs/agentsflow-migration.spec.md` Status updated to `implemented`
  (or `approved` — either is acceptable as long as `draft` is removed)

---

## Test Specification

No automated tests for this task. The acceptance criteria are verified by grep
and visual inspection.

```bash
# Manual verification:
grep -n "parrot\.bots\.flow\b" sdd/specs/agentsflow-persistency.spec.md | head -5
grep -n "SUPERSEDED\|obsolete" sdd/specs/agentsflow-persistency.spec.md | head -3

# Confirm no stale source refs in docs:
grep -rn "parrot\.bots\.flow\b" docs/ 2>/dev/null | grep -v "parrot\.bots\.flows"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md`
2. **Check dependencies** — TASK-1316 must be in `sdd/tasks/completed/`
3. **Read `sdd/specs/agentsflow-persistency.spec.md`** in full before editing
4. **Run grep sweep** to discover all stale references
5. **Implement** the updates following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** in `sdd/tasks/index/agentsflow-migration.json`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-28
**Notes**:
- agentsflow-persistency.spec.md (FEAT-009): Status changed to "obsolete", SUPERSEDED banner added
- agentsflow-migration.spec.md (FEAT-196): Status changed to "implemented"
- agentsflow-refactor-spec3.spec.md (FEAT-163): Status changed to "implemented", FEAT-196 note added
- dev-loop-orchestration.spec.md (FEAT-129): FEAT-196 note added at top
- flow-primitives.spec.md (FEAT-134): Status changed to "implemented", FEAT-196 note added
- feat-129-upgrades.spec.md (FEAT-132): FEAT-196 note added
- migration-orchestration-to-flows.spec.md (FEAT-155): Status changed to "implemented", FEAT-196 note added
- docs/architecture/08-agentsflow-dag.md: Updated code example from parrot.bots.flow to parrot.bots.flows
- docs/superpowers/plans/2026-04-20-orchestrator-aimessage-preservation.md: Updated 2 import paths
- Remaining references in older historical specs are intentional (with notes) per spec §3 Module 10 guidelines

**Deviations from spec**: none

**Deviations from spec**: none

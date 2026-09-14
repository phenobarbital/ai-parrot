# TASK-3240: Deferred findings in Claude, Codex, and Antigravity review twins

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3235, TASK-3236
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12. Unfixed major/critical review findings become durable ledger issues rather than prose, with equivalent workflow instructions on all platform twins.

## Scope

- Add mandatory Deferred findings table and `ledger open` procedure to each codereview twin.
- Define severity/title/body/discovered-from/about mapping and explicit no-findings row.
- Add semantic parity tests.

**NOT in scope**: review code changes, human acknowledgement, or start/next/done behavior.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-codereview.md` | MODIFY | Claude workflow. |
| `.agent/workflows/sdd-codereview.md` | MODIFY | Antigravity workflow. |
| `.agents/skills/sdd-codereview/SKILL.md` | MODIFY | Codex workflow. |
| `tests/sdd/test_ledger_workflow_twins.py` | CREATE | Twin parity assertions. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
These files are the Claude, Antigravity, and Codex SDD review twins; no runtime Python API is introduced.

### Existing Signatures to Use
Use `wikitoolkit ledger open` from TASK-3236 and MCP `ledger_open` semantics from TASK-3235.

### Does NOT Exist
- ~~a Deferred findings ledger table~~ — this task adds it.
- ~~permission to auto-acknowledge a critical~~ — human decision only.

## Acceptance Criteria

- [ ] Every twin mandates durable filing of out-of-scope major/critical findings.
- [ ] Parity tests verify equivalent fields and no-findings outcome.
- [ ] `pytest tests/sdd/test_ledger_workflow_twins.py -q` passes.

## Test Specification

Assert semantic tokens and ordering, not byte-identical complete files.


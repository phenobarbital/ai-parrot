# TASK-3240: Deferred findings in Claude, Codex, and Antigravity review twins

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
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

- [x] Every twin mandates durable filing of out-of-scope major/critical findings.
- [x] Parity tests verify equivalent fields and no-findings outcome.
- [x] `pytest tests/sdd/test_ledger_workflow_twins.py -q` passes.

## Test Specification

Assert semantic tokens and ordering, not byte-identical complete files.

### Completion Note

Merged clean (qwen, files exactly as declared). Post-merge integration
found that TASK-3242 — dispatched in parallel, declaring the SAME shared
test file as its own MODIFY target — landed afterward and silently
clobbered this task's entire test file with its own from-scratch
rewrite (git reported no conflict since both branches rewrote the file
wholesale from a common "doesn't exist yet" base). Reconciled into one
file with a `TestCodereviewTwins` class owning this task's tests
alongside TASK-3242's `TestDoneTwins`, and fixed a CWD-fragility bug
shared by both original versions (bare relative paths silently read the
MAIN checkout's stale files under pytest, due to an unrelated navconfig
chdir side-effect — see the fix commit for detail). Strengthened the
"parity" checks from bare `len() > 1000` into real content assertions
("Deferred findings", "ledger open").

`pytest tests/sdd/test_ledger_workflow_twins.py -q` → 8 passed (4 for
this task's own `TestCodereviewTwins`). `ruff check` / `black --check`
clean.

Seat: qwen (nova) · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct
· Attempts: 1 · Duration: 282.4s · Tokens: 2,205,152 in / 11,050 out.
Post-merge reconciliation applied by sdd-worker (sonnet), shared with
TASK-3242's fix commit.


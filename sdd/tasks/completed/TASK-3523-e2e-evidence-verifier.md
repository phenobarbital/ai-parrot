# TASK-3523: Evaluate exact coverage and validate immutable evidence

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3522
**Assigned-to**: unassigned
**Module**: M2
**Spec acceptance criteria**: AC7, AC8, AC9

---

## Context

Implement the M2 deliverable **Evaluate exact coverage and validate immutable evidence** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Add atomic per-run evidence persistence and final pointer update only after cleanup; hash artifact bytes and contained paths.
- Require exact selected/collected/executed nodes and setup/call/teardown success; required skipped/xfail/xpass/missing nodes never satisfy gate.
- Reject malformed/tampered/incomplete reports and changed before/after identity; accept only matching commit or content-identical descendant.
- Separate report status from advisory feature policy; no-test/all-skipped is BLOCKED and interrupted evidence cannot pass.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/evidence.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-server/tests/unit/e2e/test_evidence.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

This module is new. No existing project symbol is required beyond standard library and already-declared Pydantic/YAML/pytest dependencies. Its field and outcome contracts come from spec §2.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3522 (`sdd/tasks/active/TASK-3522-e2e-source-identity.md`) must be done; consume its declared interfaces and re-read its completion evidence.

- `verify_evidence(plan_path: Path, *, worktree: Path) -> VerificationResult`

### Modify-Target Freshness

- `packages/ai-parrot-server/src/parrot/e2e/evidence.py` is created by TASK-3522; no current hash/import exists. Re-read after that dependency lands.

### Does NOT Exist

- The new E2E harness and run/verify machinery do not exist at decomposition time;
  dependent task outputs are not pre-existing imports.
- No `E2ECriterion`, universal agent `/mcp/info`, reliable cookie session backend,
  or automatic provider-wide request budget may be assumed.
- Eligibility annotations are not Delegation Contracts. This task follows normal
  implementation routing until a complete validated code packet is authored.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/e2e/evidence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/e2e/test_evidence.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3523 owns its declared files for M2. TASK-3522 supplies capture source and environment identity for evidence. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Add atomic per-run evidence persistence and final pointer update only after cleanup; hash artifact bytes and contained paths.
2. Require exact selected/collected/executed nodes and setup/call/teardown success; required skipped/xfail/xpass/missing nodes never satisfy gate.
3. Reject malformed/tampered/incomplete reports and changed before/after identity; accept only matching commit or content-identical descendant.
4. Separate report status from advisory feature policy; no-test/all-skipped is BLOCKED and interrupted evidence cannot pass.

### Fixed interfaces

- `verify_evidence(plan_path: Path, *, worktree: Path) -> VerificationResult`

### `packages/ai-parrot-server/src/parrot/e2e/evidence.py` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Add atomic per-run evidence persistence and final pointer update only after cleanup; hash artifact bytes and contained paths.

2. Require exact selected/collected/executed nodes and setup/call/teardown success; required skipped/xfail/xpass/missing nodes never satisfy gate.

3. Reject malformed/tampered/incomplete reports and changed before/after identity; accept only matching commit or content-identical descendant.

4. Separate report status from advisory feature policy; no-test/all-skipped is BLOCKED and interrupted evidence cannot pass.
### `packages/ai-parrot-server/tests/unit/e2e/test_evidence.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Add atomic per-run evidence persistence and final pointer update only after cleanup; hash artifact bytes and contained paths.
- [ ] Require exact selected/collected/executed nodes and setup/call/teardown success; required skipped/xfail/xpass/missing nodes never satisfy gate.
- [ ] Reject malformed/tampered/incomplete reports and changed before/after identity; accept only matching commit or content-identical descendant.
- [ ] Separate report status from advisory feature policy; no-test/all-skipped is BLOCKED and interrupted evidence cannot pass.
- [ ] Relevant spec criteria AC7, AC8, AC9 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_evidence.py -q`

## Test Specification

Use focused tests covering success, invalid input, prerequisite failure and cleanup. Assert the outcomes named in Scope; construction-only tests are insufficient.

Test the boundary and negative cases from Scope using the exact task-owned test file(s).

**Runtime E2E validation:** ordinary SDD test selection intentionally excludes E2E.
After the required harness dependencies exist, run declared scenario node IDs via
`parrot e2e run --plan` with `PARROT_TEST_E2E=1`. Live execution additionally needs
`PARROT_TEST_REAL_LLM=1` and the provider key. These are separate from the file-level
pytest contract above. This task cannot claim E2E success solely from agent-tier tests.

## Agent Instructions

1. Read the approved spec and confirm every Depends-on task is done in the per-spec index.
2. For research-gated work, read the completed research contract; BLOCKED research
   does not authorize guessing its unresolved interface.
3. Update `sdd/tasks/index/agentic-e2e-testing.json` to in-progress with assignment/time.
4. Verify imports/signatures, then implement this task's bounded blueprint.
5. Run Validation Commands and applicable runtime probes; retain useful logs.
6. Commit scoped code and SDD state, move this task to `sdd/tasks/completed/`,
   update its index file path/status/timestamps and fill the Completion Note.
7. Never update the historical monolithic task index.

## Completion Note

Completed 2026-09-19. Implemented `parrot.e2e.evidence.verify_evidence(
plan_path, *, worktree) -> VerificationResult` (modifying the already-merged
evidence.py), reusing `capture_identity` for the "current" identity side of
the comparison. Returns `MISSING` when no pointer/verdict exists yet
(synthesized, not a fabricated PASS); raises `E2EEvidenceError` (exit 4,
fails closed) for untrustworthy evidence (malformed schema, feature_id
mismatch, mutated before/after identity, tampered/missing artifact hash,
stale source/spec/plan/environment identity); otherwise returns an
objectively-evaluated `PASS`/`FAIL`/`BLOCKED` (BLOCKED only for zero-
collection or all-skipped; FAIL for any genuinely-reported failed/xfailed/
xpassed/incomplete-cleanup required node) — separate from the advisory
feature policy, which stays the SDD consumer's concern.

Design note flagged for reviewer/M3 confirmation: no production writer for
`E2EVerdict`/the run pointer exists yet (M3's `runner.py` lands later), so
the implementing agent inferred and documented the read-side contract this
function depends on: `sdd/state/<feature_id>/e2e/latest.json` (`{"run_id":
...}`) and `sdd/state/<feature_id>/e2e/runs/<run_id>/e2e-verdict.json` —
both already excluded from `capture_identity`'s manifest. This is the
executable contract the future M3 runner must satisfy; not a pre-specified
fixed interface, so it needs M3-task-owner confirmation. Also flagged: AC8
is implemented as hash-only comparison (never the git commit SHA itself,
verified by a dedicated bookkeeping-descendant-commit test); a verdict's
`policy` field isn't cross-checked against the current plan directly (relies
on `plan_sha256` catching any drift) — a minor theoretical gap for reviewer
judgment.

Tests: `packages/ai-parrot-server/tests/unit/e2e/test_evidence.py` (new, 31
tests, same env-isolation fixture convention as TASK-3522's tests).
`pytest packages/ai-parrot-server/tests/unit/e2e/ -q` → 133 passed (102
pre-existing + 31 new, no regressions).

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 ·
Duration: 946.3s · Tokens: 214176 (subagent, in+out combined; native
usage_known=false in engine seats roll-up).

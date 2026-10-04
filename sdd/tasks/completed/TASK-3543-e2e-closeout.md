# TASK-3543: Require validated E2E evidence before both closeout flows

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3542
**Assigned-to**: unassigned
**Module**: M7
**Spec acceptance criteria**: AC8, AC9

---

## Context

Implement the M7 deliverable **Require validated E2E evidence before both closeout flows** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Both hosts invoke verify before index stamps, push, PR, merge or cleanup; consume same required/optional/none policy.
- Missing/stale/tampered/blocked/failed required evidence aborts; generic force does not bypass it.
- Preserve ordinary task-test reuse; never run full suite or trust exploration passed fields.
- Exercise validator/consumer decision table with realistic artifacts and bookkeeping-only descendant identity, not a prose-only substring test.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Task-owned deliverable |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Task-owned deliverable |
| `tests/sdd_scripts/test_e2e_closeout_contract.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `.claude/commands/sdd-done.md:116` — Existing closeout reuses ordinary test evidence; add E2E verify without rerunning full suite. Source SHA-256: `1dcda980137f85db82727dbfdd214b1dec82c5386ab83376812d6ec22551f6f3`.
- `.agents/skills/sdd-done/SKILL.md:50` — Evidence gathering precedes stamp at 70, push and PR. Required E2E cannot be bypassed by generic force. Source SHA-256: `328670c7ca02a01c17c392cf84b9749b989891564ecc919a7cbaefaa81d3c4bd`.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3542 (`sdd/tasks/active/TASK-3542-e2e-devloop-stage.md`) must be done; consume its declared interfaces and re-read its completion evidence.

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### Modify-Target Freshness

- `.claude/commands/sdd-done.md` current SHA-256: `1dcda980137f85db82727dbfdd214b1dec82c5386ab83376812d6ec22551f6f3`; re-read at execution because other features may change it.
- `.agents/skills/sdd-done/SKILL.md` current SHA-256: `328670c7ca02a01c17c392cf84b9749b989891564ecc919a7cbaefaa81d3c4bd`; re-read at execution because other features may change it.

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
      "path": ".claude/commands/sdd-done.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-done/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_e2e_closeout_contract.py",
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
- **Parallelism:** TASK-3543 owns its declared files for M7. TASK-3542 supplies run separate e2e stage after final dev-loop qa edits. Exclusive prerequisite/shared-orchestration edit; do not co-schedule.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Both hosts invoke verify before index stamps, push, PR, merge or cleanup; consume same required/optional/none policy.
2. Missing/stale/tampered/blocked/failed required evidence aborts; generic force does not bypass it.
3. Preserve ordinary task-test reuse; never run full suite or trust exploration passed fields.
4. Exercise validator/consumer decision table with realistic artifacts and bookkeeping-only descendant identity, not a prose-only substring test.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `.claude/commands/sdd-done.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Both hosts invoke verify before index stamps, push, PR, merge or cleanup; consume same required/optional/none policy.

2. Missing/stale/tampered/blocked/failed required evidence aborts; generic force does not bypass it.

3. Preserve ordinary task-test reuse; never run full suite or trust exploration passed fields.

4. Exercise validator/consumer decision table with realistic artifacts and bookkeeping-only descendant identity, not a prose-only substring test.
### `.agents/skills/sdd-done/SKILL.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Both hosts invoke verify before index stamps, push, PR, merge or cleanup; consume same required/optional/none policy.

2. Missing/stale/tampered/blocked/failed required evidence aborts; generic force does not bypass it.

3. Preserve ordinary task-test reuse; never run full suite or trust exploration passed fields.

4. Exercise validator/consumer decision table with realistic artifacts and bookkeeping-only descendant identity, not a prose-only substring test.
### `tests/sdd_scripts/test_e2e_closeout_contract.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Both hosts invoke verify before index stamps, push, PR, merge or cleanup; consume same required/optional/none policy.
- [ ] Missing/stale/tampered/blocked/failed required evidence aborts; generic force does not bypass it.
- [ ] Preserve ordinary task-test reuse; never run full suite or trust exploration passed fields.
- [ ] Exercise validator/consumer decision table with realistic artifacts and bookkeeping-only descendant identity, not a prose-only substring test.
- [ ] Relevant spec criteria AC8, AC9 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q`

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

Completed 2026-09-24. Attempt 1 (seat gpt-5.6-terra/codex) failed immediately
with `SubWorktreeMergeError` before producing any code; the engine
auto-escalated to a native sonnet retry (attempt 2, attempt_uid
`1061790d086c4fa3990b1a288138c27b`), which delivered the task cleanly.

Modified `.claude/commands/sdd-done.md`: added Step 4.6 "Verify E2E Evidence
(FEAT-581)", invoked before Step 5's report, Step 7's index stamp, Step 8's
push, Step 9's merge-blocker check, Step 9.2's PR/merge and Step 11's
cleanup. Reads the spec's `e2e.policy` frontmatter (default `optional`;
malformed value treated as `required`+missing), runs the read-only
`parrot e2e verify --plan sdd/state/<FEAT-ID>/e2e-plan.md`, and applies:
`none` → exempt; `optional` → advisory only, never blocks; `required`/
`invalid` → any status other than `PASS`+`gate_satisfied:true` aborts the
whole command — explicitly NOT bypassable by `--force` (AC9). Mirrored the
same contract in `.agents/skills/sdd-done/SKILL.md`.

Created `tests/sdd_scripts/test_e2e_closeout_contract.py` (519 lines): a
task-local `evaluate_closeout_gate()` encodes the decision table both docs
describe, exercised against the real `parrot.e2e.evidence.verify_evidence`
validator fed realistic on-disk evidence (never a mocked validator).
Covers: missing plan, missing evidence (force=True/False both blocking,
proving AC9), zero collection (BLOCKED), failed required node (FAIL),
incomplete cleanup (FAIL), tampered/stale artifact (blocked), a fully-passing
run (allowed), and AC8's bookkeeping-only descendant commit still passing.
`optional` proven advisory across missing/failed/tampered evidence; `none`
proven to never touch a plan/evidence path.

Tests:
- `pytest tests/sdd_scripts/test_e2e_closeout_contract.py -q` → 26 passed.
- Regression: `pytest tests/sdd_scripts/test_e2e_spec_contract.py
  tests/sdd_scripts/test_command_twin_parity.py
  tests/sdd_scripts/test_command_contracts.py -q` → 35 passed, no
  regressions (confirms `.claude/commands/sdd-done.md` has no tracked
  twin-parity test in that suite).
- `ruff check` clean; `black --check` clean.

Only the 3 declared files touched (648 insertions); nothing under `sdd/`
touched. `.agent/workflows/sdd-done.md` — a separate, already-stale
pre-FEAT-145 legacy twin not covered by `test_command_twin_parity.py` and
not in this task's declared scope — was deliberately left untouched
(flagged by the implementing agent for a future task, not fixed here).

No unresolved limitations. AC8/AC9 demonstrated by the new test suite.

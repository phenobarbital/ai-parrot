# TASK-3542: Run separate E2E stage after final dev-loop QA edits

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3534, TASK-3541
**Assigned-to**: unassigned
**Module**: M7
**Spec acceptance criteria**: AC9, AC10

---

## Context

Implement the M7 deliverable **Run separate E2E stage after final dev-loop QA edits** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Invoke the server CLI lazily via bounded argv subprocess after code-review/triage edits and deterministic rechecks, before final passed aggregation.
- Capture rich E2E result in state/notes; AND required gate satisfaction into existing QA passed, retain optional failures as advisory.
- Keep core usable without server installation for none/optional-no-plan; required missing capability blocks.
- Preserve FEAT-563 marker selector and criterion union; align packaged/repo QA prompts and existing verdict format without granting agent-spawn tools.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/e2e.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | Task-owned deliverable |
| `.claude/agents/qa-runner.md` | MODIFY | Task-owned deliverable |
| `.claude/agents/sdd-qa.md` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-qa.md` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_e2e_stage.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:350` — Final passed conjunction at 350 follows QA reruns at 325/337. Add separate E2E stage after code-changing work, before report aggregation. Signature: `class QANode(DevLoopNode)`. Source SHA-256: `3293bf629504119cdd9fc1bdbf75e3b21335bfd77d92c3f33f16397f23a342e7`.
- `.claude/agents/qa-runner.md:61` — Feature selector excludes E2E; retain verdict: PASS|FAIL at line 85 and read-only verifier behavior. Source SHA-256: `ba948986bc520c1cdedeb05f041f56a65516f9fe4de8eeedff1e968011425678`.
- `.claude/agents/sdd-qa.md:27` — Read/Bash-only verifier, exit-code report. Deterministic E2E runs in outer orchestration, not an LLM judgement. Source SHA-256: `2e48ecefd69b8341994eeddf651ccdf3350803317005b7b4736d6bf0650cb9f2`.
- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-qa.md:27` — Packaged prompt mirrors the repository sdd-qa prompt; keep the two aligned. Source SHA-256: `2e48ecefd69b8341994eeddf651ccdf3350803317005b7b4736d6bf0650cb9f2`.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3534 (`sdd/tasks/active/TASK-3534-e2e-cli.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3541 (`sdd/tasks/active/TASK-3541-e2e-spec-surfaces.md`) must be done; consume its declared interfaces and re-read its completion evidence.

- `run_e2e_stage(*, worktree: Path, spec_path: Path, feature_id: str) -> dict[str, Any] (async)`

### Modify-Target Freshness

- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` current SHA-256: `3293bf629504119cdd9fc1bdbf75e3b21335bfd77d92c3f33f16397f23a342e7`; re-read at execution because other features may change it.
- `.claude/agents/qa-runner.md` current SHA-256: `ba948986bc520c1cdedeb05f041f56a65516f9fe4de8eeedff1e968011425678`; re-read at execution because other features may change it.
- `.claude/agents/sdd-qa.md` current SHA-256: `2e48ecefd69b8341994eeddf651ccdf3350803317005b7b4736d6bf0650cb9f2`; re-read at execution because other features may change it.
- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-qa.md` current SHA-256: `2e48ecefd69b8341994eeddf651ccdf3350803317005b7b4736d6bf0650cb9f2`; re-read at execution because other features may change it.

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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/e2e.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/qa-runner.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-qa.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-qa.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_qa_e2e_stage.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3542 owns its declared files for M7. TASK-3534 supplies expose lazy e2e run verify and lifecycle commands; TASK-3541 supplies generate e2e plans consistently in claude and codex specs. Exclusive prerequisite/shared-orchestration edit; do not co-schedule.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Invoke the server CLI lazily via bounded argv subprocess after code-review/triage edits and deterministic rechecks, before final passed aggregation.
2. Capture rich E2E result in state/notes; AND required gate satisfaction into existing QA passed, retain optional failures as advisory.
3. Keep core usable without server installation for none/optional-no-plan; required missing capability blocks.
4. Preserve FEAT-563 marker selector and criterion union; align packaged/repo QA prompts and existing verdict format without granting agent-spawn tools.

### Fixed interfaces

- `run_e2e_stage(*, worktree: Path, spec_path: Path, feature_id: str) -> dict[str, Any] (async)`

### `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/e2e.py` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Invoke the server CLI lazily via bounded argv subprocess after code-review/triage edits and deterministic rechecks, before final passed aggregation.

2. Capture rich E2E result in state/notes; AND required gate satisfaction into existing QA passed, retain optional failures as advisory.

3. Keep core usable without server installation for none/optional-no-plan; required missing capability blocks.

4. Preserve FEAT-563 marker selector and criterion union; align packaged/repo QA prompts and existing verdict format without granting agent-spawn tools.
### `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Invoke the server CLI lazily via bounded argv subprocess after code-review/triage edits and deterministic rechecks, before final passed aggregation.

2. Capture rich E2E result in state/notes; AND required gate satisfaction into existing QA passed, retain optional failures as advisory.

3. Keep core usable without server installation for none/optional-no-plan; required missing capability blocks.

4. Preserve FEAT-563 marker selector and criterion union; align packaged/repo QA prompts and existing verdict format without granting agent-spawn tools.
### `.claude/agents/qa-runner.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Invoke the server CLI lazily via bounded argv subprocess after code-review/triage edits and deterministic rechecks, before final passed aggregation.

2. Capture rich E2E result in state/notes; AND required gate satisfaction into existing QA passed, retain optional failures as advisory.

3. Keep core usable without server installation for none/optional-no-plan; required missing capability blocks.

4. Preserve FEAT-563 marker selector and criterion union; align packaged/repo QA prompts and existing verdict format without granting agent-spawn tools.
### `.claude/agents/sdd-qa.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Invoke the server CLI lazily via bounded argv subprocess after code-review/triage edits and deterministic rechecks, before final passed aggregation.

2. Capture rich E2E result in state/notes; AND required gate satisfaction into existing QA passed, retain optional failures as advisory.

3. Keep core usable without server installation for none/optional-no-plan; required missing capability blocks.

4. Preserve FEAT-563 marker selector and criterion union; align packaged/repo QA prompts and existing verdict format without granting agent-spawn tools.
### `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-qa.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Invoke the server CLI lazily via bounded argv subprocess after code-review/triage edits and deterministic rechecks, before final passed aggregation.

2. Capture rich E2E result in state/notes; AND required gate satisfaction into existing QA passed, retain optional failures as advisory.

3. Keep core usable without server installation for none/optional-no-plan; required missing capability blocks.

4. Preserve FEAT-563 marker selector and criterion union; align packaged/repo QA prompts and existing verdict format without granting agent-spawn tools.
### `packages/ai-parrot/tests/flows/dev_loop/test_qa_e2e_stage.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Invoke the server CLI lazily via bounded argv subprocess after code-review/triage edits and deterministic rechecks, before final passed aggregation.
- [ ] Capture rich E2E result in state/notes; AND required gate satisfaction into existing QA passed, retain optional failures as advisory.
- [ ] Keep core usable without server installation for none/optional-no-plan; required missing capability blocks.
- [ ] Preserve FEAT-563 marker selector and criterion union; align packaged/repo QA prompts and existing verdict format without granting agent-spawn tools.
- [ ] Relevant spec criteria AC9, AC10 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_e2e_stage.py -q`

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

Completed 2026-09-24 by seat gpt-5.6-terra (backend codex), attempt 1,
attempt_uid `076427f4a3b94bddb372d73db5278757` (276.6s). Delivery merged
cleanly first attempt (0 lint errors).

Created `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/e2e.py`
(`run_e2e_stage(*, worktree, spec_path, feature_id) -> dict[str, Any]`),
invoking the server E2E CLI lazily via bounded argv subprocess after
code-review/triage edits, before final `passed` aggregation. Modified
`nodes/qa.py` to call it and AND its required-gate result into the existing
`passed` conjunction while keeping optional failures advisory-only. Kept
`.claude/agents/qa-runner.md`, `.claude/agents/sdd-qa.md`, and their packaged
twin `_subagent_data/sdd-qa.md` aligned (each +4 lines documenting the
separate E2E stage) without granting agent-spawn tools.

Tests:
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_e2e_stage.py -q`
  → 5 passed.
- Regression: `pytest packages/ai-parrot/tests/flows/dev_loop/ -k qa -q`
  → 118 passed, 1 pre-existing skip.
- Prompt-twin parity: `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_defs.py -q`
  → 14 passed (sdd-qa.md ↔ packaged `_subagent_data/sdd-qa.md` still aligned).

Only the 6 declared files touched (334 insertions/1 deletion); no `sdd/`
files touched. Core stays usable without server installation for
none/optional-no-plan; required-but-missing capability blocks per spec.

Environment note (not a task defect): this bare worktree lacked the
compiled `.so` for two Cython modules (`parrot.utils.types`,
`parrot.utils.parsers.toml`) needed to even collect `dev_loop`'s heavy
conftest import chain; copied the matching `cpython-312` `.so` files from
the main checkout (gitignored, not committed) to verify locally — same
pre-existing worktree/build gap documented on TASK-3533/3534/3539's notes,
now additionally confirmed to affect collection, not just subprocess
re-imports.

No unresolved limitations. AC9/AC10 demonstrated by the new test suite.

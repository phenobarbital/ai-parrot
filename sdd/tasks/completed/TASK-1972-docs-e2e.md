# TASK-1972: Docs update + intake-to-dispatch integration test

**Feature**: FEAT-388 — `parrot devloop` CLI Homologation
**Spec**: `sdd/specs/devloop-cli-homologation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1970, TASK-1971
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests + §5 final criterion. Closes FEAT-388: an
end-to-end test proving free text → document → `FeatureBrief` → dispatch,
and user-facing documentation for the new CLI surface.

---

## Scope

- Integration test `test_intake_to_dispatch_e2e`: mock intake LLM → real
  `FeatureIntake` document write (tmp dir) → `FeatureBrief` → fake-runner
  dispatch through `DevLoopConsole` (extends the TASK-1898 fake-flow E2E
  pattern).
- Update `documentation/parrot-devloop-cli.md`: kind picker, feature intake
  walkthrough, `/feature`, `--dev-agent backend[:model[:count]]`, `--text`,
  `DEV_LOOP_INTAKE_LLM`, `DEV_LOOP_DEVELOPMENT_AGENT` on the CLI,
  backend-aware preflight table.
- Run the full affected suites and record evidence.

**NOT in scope**: new features; example-server docs (`examples/dev_loop/`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/cli/devloop/test_intake_e2e.py` | CREATE | Intake → dispatch E2E (all external calls mocked) |
| `documentation/parrot-devloop-cli.md` | MODIFY | New CLI surface documented |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-28 on `dev` @ `623f0a6`. This task lands after
> TASK-1968..1971 — re-verify their delivered interfaces first.

### Verified Imports

```python
from parrot.cli.devloop.console import DevLoopConsole   # console.py:30
from parrot.cli.devloop.intake import FeatureIntake     # delivered by TASK-1969
from parrot.flows.dev_loop.models import FeatureBrief   # models.py:1068
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/cli/devloop/console.py
class DevLoopConsole:                                   # :30
    def __init__(self, *, console: Optional[Console] = None,
                 session: Optional[PromptSession] = None) -> None:  # :33
    async def _dispatch_run(self, brief: Any) -> str:   # :239 (asyncio task via runner.run)
```

### Does NOT Exist

- No live LLM, Redis, or `claude` binary in tests — everything external is
  faked (existing bootstrap/console test fixtures show how).
- ~~`tests/cli/devloop/test_intake_e2e.py`~~ — created here.

---

## Implementation Notes

### References in Codebase
- TASK-1898 console E2E (fake flow) — the fake-runner/session pattern.
- `packages/ai-parrot/tests/cli/test_devloop_feature_brief.py` — brief
  loading assertions to mirror.
- `documentation/parrot-devloop-cli.md` — existing doc structure to extend.

### Key Constraints
- The E2E asserts the *full* chain: draft fields → document content
  (frontmatter) → `FeatureBrief.document_path` → runner received the brief.
- Evidence: save test output to `artifacts/logs/` per project workflow.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/cli/ -v` passes end to end.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes unchanged.
- [ ] Docs cover every new flag/command/config key added by FEAT-388.
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_intake_e2e.py
async def test_intake_to_dispatch_e2e(tmp_path):
    """free text -> FeatureDraft (mock LLM) -> document written with
    frontmatter -> FeatureBrief -> fake runner.run received it."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1970 and TASK-1971 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** against the delivered interfaces
4. **Update status** in `sdd/tasks/index/devloop-cli-homologation.json`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index**, **fill the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-28
**Notes**: `test_intake_e2e.py` exercises the full chain with NO mocking
of the document-rendering logic itself: a fake `AbstractClient`
(`FakeIntakeClient`, patched at `parrot.clients.factory.LLMFactory.
create`) supplies the canned `FeatureDraft`, but `FeatureIntake.
write_document()` runs for real against a `monkeypatch.chdir(tmp_path)`
-scoped `sdd/proposals/` (its default is a bare relative `Path("sdd/
proposals")`, so chdir is the correct/least-invasive way to sandbox it
without touching `intake.py`'s public signature). The test drives the
interactive path start-to-finish — kind picker ("3") → multiline free
text → accept → skip pool/judge steps → `dc._dispatch_run(brief)` — and
asserts on every link: the LLM prompt actually contains the user's free
text, the document exists on disk with FEAT-145 frontmatter and the
drafted content, `FeatureBrief.document_path` points at that exact file,
and a fake `StubRunner.run()` received that exact `FeatureBrief`
instance.

Docs (`documentation/parrot-devloop-cli.md`) gained: a "The kind picker"
section, a full "Feature-mode intake" walkthrough (draft/accept/edit/
redo/cancel), a "Dev-agent pool & judge panel" section (interactive +
`--dev-agent` non-interactive), a `FeatureBrief (YAML)` example
alongside the existing `WorkBrief`/`RevisionBrief` ones, a
"Configuration reference" table for `DEV_LOOP_DEVELOPMENT_AGENT` /
`DEV_LOOP_INTAKE_LLM` / concurrency+TTL keys / per-backend model env
vars, an expanded backend-aware preflight table (with a correction
mid-write: CLI-transport backends other than claude-code still
genuinely gate preflight on their own binary — only API-transport
backends are unconditionally soft — my first draft wording implied
otherwise), `/feature` in the slash-command table, and updated
Quick-start/Troubleshooting entries. `examples/dev_loop/` docs
deliberately untouched (out of scope).

`pytest packages/ai-parrot/tests/cli/ -v` → 130 passed (1 new E2E + 129
pre-existing, zero regressions). `pytest packages/ai-parrot/tests/flows/
dev_loop/ -q` → 862 passed, 2 failed, 6 skipped — the 2 failures
(`test_e2e_run_with_blocking_gates`, `test_models_module_is_pure`) are
the exact same pre-existing/order-dependent baseline observed at the
start of this feature (TASK-1968's completion note), unchanged by
FEAT-388. Evidence saved to `artifacts/logs/feat-388-task-1972-
evidence.txt` (local only — `artifacts/` is gitignored per project
convention, not committed).

This closes FEAT-388 — all 5 tasks (TASK-1968..1972) done.

**Deviations from spec**: none.

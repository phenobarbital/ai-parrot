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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

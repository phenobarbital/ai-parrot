# TASK-4886: Move Claude-dispatcher tests onto linked-worktree fixtures

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 policy 2: native launches require a linked worktree with valid Git metadata and reject a
primary-checkout or non-repository cwd. Once TASK-4888 lands, every test that resolves or
dispatches an `sdd-worker`/`sdd-coder` profile (the default `ClaudeCodeDispatchProfile()` is
`sdd-worker`) with a bare `tmp_path` cwd will fail. This task moves those tests onto a fake linked
worktree **first**, while behavior is unchanged, so TASK-4888's diff only adds native assertions.
It is a behavior-neutral test refactor: every migrated test must pass before AND after TASK-4888.

Found at task time (spec §6 did not list these files): the default profile is used with bare
`tmp_path`/`WORKTREE_BASE_PATH` cwd in the files below. `test_nova_integration.py` and
`test_adversarial_review.py` use non-Claude dispatchers and are out of scope.

---

## Scope

- Add a `linked_worktree` fixture to the dev-loop `conftest.py` that builds a fake primary
  checkout + linked worktree under `tmp_path` (file-based Git metadata, no `git` binary needed)
  and pins every dispatcher's `WORKTREE_BASE_PATH` so the linked worktree passes the cwd check.
- Switch the sandboxed-profile tests in the listed dev-loop files to use it as their cwd.
- In `dev_flow/test_ideation_graph_search.py` (no conftest in `dev_flow/`), add a local
  module-level helper with the same layout for its two `sdd-worker` `_resolve_run_options` calls.
- Do not change any assertion's meaning.

**NOT in scope**: new native assertions (TASK-4887/4888), any production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/conftest.py` | MODIFY | Add `linked_worktree` fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` | MODIFY | Sandboxed-profile tests use the linked worktree |
| `packages/ai-parrot/tests/flows/dev_loop/test_cli_dispatcher_usage_events.py` | MODIFY | Same |
| `packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py` | MODIFY | Same |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_concurrency.py` | MODIFY | Same |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | `test_programmatic_claude_protection_does_not_depend_on_project_settings` cwd only |
| `packages/ai-parrot/tests/flows/dev_flow/test_ideation_graph_search.py` | MODIFY | Local helper for the two `sdd-worker` calls |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher   # test_worktree_environment.py:20
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile          # models/__init__.py:64
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/flows/dev_loop/conftest.py
@pytest.fixture
def temp_worktree_base(tmp_path, monkeypatch) -> Iterator[str]:   # :119-136 — pins WORKTREE_BASE_PATH on
    ...                                                           # claude/codex/gemini/google_coding/llm + research
# packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py
def _patch_worktree_base(monkeypatch, tmp_path):                  # :98 fixture, returns tmp_path
def dispatcher(monkeypatch):                                      # :108 fixture
class TestProfileResolution:                                      # :131 (default profile = sdd-worker)
class TestSandboxedSettingSources:                                # :795
# packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
def checkout(tmp_path: Path) -> tuple[Path, Path]:                # :39 — reference layout (pool worktree)
def test_programmatic_claude_protection_does_not_depend_on_project_settings(tmp_path, subagent)  # :293
# Call sites with a sandboxed (default) profile and bare cwd:
#   test_cli_dispatcher_usage_events.py:158-164, :184-190   (cwd=str(_patch_worktree_base))
#   test_dual_publish.py:381-387, :489-495                    (cwd=str(tmp_path))
#   integration/test_concurrency.py:102-108                   (cwd=str(tmp_path))
#   dev_flow/test_ideation_graph_search.py:92-93, :106-107    (cwd=str(tmp_path))
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py
def repository_paths(cwd: Path) -> tuple[Path, Path | None]:      # :54 — what "linked" means
```

Linked-worktree layout `repository_paths` recognises: `<main>/.git/` directory;
`<main>/.git/worktrees/<name>/commondir` containing `../..`; the checkout's `.git` *file*
containing `gitdir: <main>/.git/worktrees/<name>`.

### Does NOT Exist
- ~~`linked_worktree` fixture~~ — does not exist yet in any conftest.
- ~~`packages/ai-parrot/tests/flows/dev_flow/conftest.py`~~ — no such file; use a local helper there.
- ~~a `git worktree add` requirement~~ — fake file-based metadata is enough and keeps tests fast.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/flows/dev_loop/conftest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_cli_dispatcher_usage_events.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/integration/test_concurrency.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_flow/test_ideation_graph_search.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#repository_paths"
  ]
}
```

---

## Implementation Notes

- `conftest.py` changes affect every dev-loop test, so this task is exclusive (`parallel: false`).
- Keep `_patch_worktree_base` in `test_dispatcher.py`; make the sandboxed tests request
  `linked_worktree` instead. Tests using non-sandboxed profiles keep their cwd.
- The linked worktree must sit under the pinned `WORKTREE_BASE_PATH`
  (`_enforce_cwd_under_worktree_base`, dispatchers/claude.py:523).

---

## Implementation Blueprint

### Steps (in order)
1. Add the fixture to `conftest.py` — *why*: one layout for all dev-loop tests.
2. Run the listed files BEFORE editing them to record the baseline pass set — *why*: the refactor must be behavior-neutral.
3. Switch each listed call site to the fixture — *why*: these break once TASK-4888 enforces policy 2.
4. Re-run the same files; the pass set must be identical.

### `packages/ai-parrot/tests/flows/dev_loop/conftest.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cxF 'def temp_worktree_base(tmp_path, monkeypatch) -> Iterator[str]:' conftest.py)
# occurrences: 1 (verified: grep -cxF '    yield base' conftest.py)
# AFTER — insert below `    yield base` (verified: conftest.py:136), the last line of temp_worktree_base


@pytest.fixture
def linked_worktree(tmp_path, monkeypatch) -> Path:
    """Return a fake linked SDD worktree (``<main>/.claude/worktrees/feat``) under a pinned WORKTREE_BASE_PATH.

    FEAT-768 native launches refuse primary checkouts and non-repositories, so sandboxed
    ``sdd-worker``/``sdd-coder`` dispatch tests need a linked worktree as their cwd.
    """
    main = tmp_path / "main"
    admin = main / ".git" / "worktrees" / "feat"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    worktree = main / ".claude" / "worktrees" / "feat"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    # FILL IN: pin WORKTREE_BASE_PATH exactly like temp_worktree_base (same target list) to str(tmp_path)
    return worktree
```
**Why**: mirrors `test_worktree_environment.checkout`, but under `.claude/worktrees` like real SDD
worktrees so TASK-4887/4888 tests can also exercise the admin-dir grant. `conftest.py` has no `Path`
import (verified: imports at :9-16): add `from pathlib import Path`.

### Call-site edits (MODIFY, each listed file)
```python
# FILL IN: per call site listed in "Existing Signatures": request `linked_worktree` and pass
# cwd=str(linked_worktree); keep every assertion unchanged — bounded by "behavior-neutral"
```

### `packages/ai-parrot/tests/flows/dev_flow/test_ideation_graph_search.py` (MODIFY)
```python
# FILL IN: add a module-level `_linked_worktree(tmp_path: Path) -> Path` helper with the same
# layout as the conftest fixture and use it in the two sdd-worker tests (:92, :106); their
# WORKTREE_BASE_PATH monkeypatch to str(tmp_path) already covers it
```

### FILL IN checklist
- [ ] conftest fixture pins the same WORKTREE_BASE_PATH targets as `temp_worktree_base`
- [ ] every listed sandboxed call site uses the linked worktree
- [ ] identical pass set before/after

---

## Acceptance Criteria

- [ ] All listed test files pass with the same test count before and after the change.
- [ ] No production file changed.
- [ ] `ruff check` clean on the modified files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_cli_dispatcher_usage_events.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_dual_publish.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/integration/test_concurrency.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_flow/test_ideation_graph_search.py -q`

---

## Test Specification

No new tests: the existing tests are the specification. Record the before/after pass counts in
the Completion Note.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-claude-native-sandbox --feature-id FEAT-768`).
2. Mark the task in progress in `sdd/tasks/index/sdd-claude-native-sandbox.json`.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` before and after.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4886 sdd-claude-native-sandbox verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any

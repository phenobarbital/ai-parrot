# TASK-4534: Engine binds the validation capability; native hook rewrites lone runner commands to the verdict

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4532, TASK-4533
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (engine + native half). The engine builds one capability per MCP attempt (bound to that
task and attempt worktree, delegating to the supervisor task tier) and extends the attempt profile's
`allowed_commands` with the registry's binaries. Native seats keep their tool list; their Bash goes through
`wikitoolkit claude-hook` → `worktree_environment._scope_guard`, which now rewrites a LONE runner command to
`cd <root> && python scripts/sdd/select_tests.py --tier task --run --verdict --worktree <root>` (brainstorm Q6).

---

## Scope

- `engine._validation_capability(ctx, task, *, path, attempt_uid, execution_id)` ⇒ object with `task_id` and `async run(targets=())` calling `run_validation(tier="task")` + `wait_verdict` and returning `verdict_to_json`.
- In `_run_attempt` (MCP path): `dispatcher.set_validation_runner(capability)` before `dispatch`, cleared in `finally`; profile `allowed_commands` extended with `load_registry(path).binaries`.
- `worktree_environment.py`: `_is_lone_pytest` ⇒ `_is_lone_runner_command(command, registry)`; `_scope_guard` handles `verdict` from `guard_bash` (rewrite to the verdict command), keeps `block`/`allow`.
- Sandbox PATH: ensure the directories of resolvable runner binaries (`shutil.which`) are visible inside bubblewrap (read-only bind) when the TOML declares them.

**NOT in scope**: Docs (TASK-4536).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | capability + profile extension |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | native verdict rewrite |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_capability.py` | CREATE | capability tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | native rewrite tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.runners.registry import load_registry  # TASK-4521
from parrot.flows.dev_loop.test_scope.verdict import verdict_to_json  # TASK-4529
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py
def _load_guard_bash() -> Any                         # line 294 — package or path import of test_scope.guard
def _is_lone_pytest(command: str) -> bool             # line 313 — basename in {pytest, python, python3}, no compounds
def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]   # line 325 — returns allow|rewrite|block
#   hook caller line 445: `action, value = _scope_guard(command, cwd)`; `if action == "rewrite" and value: command = value`
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
#   _run_attempt ~3229-3245: _write_attempt_scope(...); dispatcher, profile = self._dispatcher_builder(...);
#   profile = profile.model_copy(update={"subagent": "sdd-coder"}); … output = await dispatcher.dispatch(brief=TaskScopedBrief(...), profile=profile, …)
```

### Does NOT Exist
- ~~`_is_lone_runner_command`, `_validation_capability`~~ — added here
- ~~a shebang on select_tests.py~~ — invoke with `python`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_capability.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#_scope_guard",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#_is_lone_pytest",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt"
  ]
}
```

---

## Implementation Notes

- The hook runs under system Python with the kernel path-imported: `_scope_guard` must not import `parrot.*`; it receives the rendered command from `guard_bash`.
- Keep the hook's `action == "rewrite"` handling working for `verdict` too (rename the branch: `if action in ("rewrite", "verdict") and value`).
- FEAT-633 (spec rev 0.3) also plans edits to worktree_environment.py — rebase-check before merging (spec Worktree Strategy).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Capability + profile extension in engine — *why*: S7, S4.
2. Native rewrite — *why*: brainstorm Q6.
3. Sandbox PATH binds — *why*: pnpm/cargo resolvable.
4. Tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _is_lone_pytest(' …/worktree_environment.py)
# REPLACE _is_lone_pytest (worktree_environment.py:313) with:
def _is_lone_runner_command(command: str) -> bool:
    """True for a single runner invocation (pytest/python -m pytest/vitest/pnpm exec vitest/npx vitest/cargo test) with no compounding."""
    # FILL IN: same compound-marker check as before; then shlex.split and a head in
    #          {"pytest","python","python3","vitest","pnpm","npx","cargo","uv"} — bounded by brainstorm Q6 (lone only)

# _scope_guard (line 325): accept outcome.action == "verdict" exactly like the old "rewrite" branch,
# return ("verdict", rendered) — FILL IN; hook caller (line 445): treat "verdict" like "rewrite".
```
**Why**: Lone-only scope is a decided answer (brainstorm Q6); do not widen to compounds.

### FILL IN checklist
- [ ] capability object + lifecycle
- [ ] allowed_commands extension
- [ ] `_is_lone_runner_command`
- [ ] `_scope_guard` verdict branch + caller
- [ ] PATH binds
- [ ] tests

---

## Acceptance Criteria

- [ ] MCP attempt dispatch has a bound capability; it is cleared after dispatch.
- [ ] Attempt profile allows the registry's runner binaries.
- [ ] Native lone `pytest x.py` / `pnpm exec vitest run` in an attempt ⇒ rewritten to `cd <root> && python scripts/sdd/select_tests.py --tier task --run --verdict --worktree <root>`.
- [ ] Compound commands unchanged.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_capability.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4534 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

# TASK-5296: Live-process guard and post-move check in the legacy migration recipe

**Feature**: FEAT-837 — Brief Worktrees Survive the Worktree-Root Migration
**Spec**: `sdd/specs/dev-loop-feature-launcher-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:1b8289182630`

---

## Context

`issue:1b8289182630`: the FEAT-802 worktree-root migration lost the brief
worktree `hotfix-NAV-7762-…` that had a live `sdd-worker` inside it.
`legacy_migration_recipe()` emits `mv` + `git worktree repair` for every
registered legacy worktree without checking for a live process and without
confirming afterwards that each destination is still a git checkout. This task
implements spec §3 Module 1 (goals G1, G2; AC1, AC2).

---

## Scope

- In `legacy_migration_recipe()`, refuse (raise `ValueError`) when any topmost
  legacy path has a live process inside, naming the path and the PIDs.
- Append, after the `git worktree repair` line, one
  `git -C <dest> rev-parse --git-dir >/dev/null || { echo <msg> >&2; exit 1; }`
  line per destination in `mappings`.
- Update the function docstring (`Raises:`).
- Add tests in `test_config.py`.

**NOT in scope**: `doctor.py` / `installer.py` (they already render the
`ValueError`), the launcher (TASK-5297), unregistered legacy directories.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/config.py` | MODIFY | live-process guard + destination checks |
| `packages/ai-parrot/tests/sdd/test_config.py` | MODIFY | two new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.sdd.config import legacy_migration_recipe  # verified: packages/ai-parrot/src/parrot/sdd/config.py:195
from parrot.sdd.scripts import remove_worktree  # LAZY import only, inside the function:
# remove_worktree.py:49 does `from parrot.sdd.config import worktree_root` → module-level import is circular
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/config.py:195
def legacy_migration_recipe(repo_root: Path, paths: Sequence[Path]) -> list[str]:
    # locals used: root (Path), mappings: list[tuple[Path, Path]], topmost: list[tuple[Path, Path]],
    # quote = shlex.quote (line 243), lines: list[str]
    # line 239-241: for _, destination in topmost: if os.path.lexists(destination): raise ValueError(...)
    # line 256: lines.append(f"git -C {quote(str(root))} worktree repair {repaired_paths}")
    # line 257: lines.append(")")

# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:183
def live_processes_in(path: Path, exclude_pids: Collection[int] = ()) -> list[tuple[int, str]]:
    # (pid, cmdline[:160]) per process whose /proc/<pid>/cwd is path or below; skips own pid

# packages/ai-parrot/tests/sdd/test_config.py — helpers _git_repo(tmp_path), _add_worktree(repo, rel, branch)
# test_legacy_migration_recipe_shape (line 335), test_legacy_migration_recipe_executes (line 382)
```

### Does NOT Exist

- ~~`parrot.sdd.config.live_processes`~~ / any live-process helper in config.py — use `remove_worktree.live_processes_in`.
- ~~`legacy_migration_recipe(..., force=...)`~~ — no override parameter; do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_config.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#legacy_migration_recipe",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#live_processes_in"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- Monkeypatch `remove_worktree.live_processes_in` in tests (the module
  attribute), so the lazy `from parrot.sdd.scripts import remove_worktree` +
  `remove_worktree.live_processes_in(...)` call picks up the fake. Do NOT use
  `from ... import live_processes_in` inside the function — it would bypass the
  monkeypatch.
- Guard only `topmost` paths: `live_processes_in` already matches descendants.
- The guard runs before any line is built, so a refused recipe returns nothing.

---

## Implementation Blueprint

### Steps (in order)

1. Insert the guard after the `lexists` loop — *why*: every refusal (occupied
   destination, live process) happens before the recipe is built.
2. Append the per-destination checks after the `worktree repair` line —
   *why*: `set -e` does not catch a repair that silently leaves a tree unregistered.
3. Add the two tests; run the whole `test_config.py` — *why*: the existing
   execute test runs the recipe in real git and must still pass.

### `packages/ai-parrot/src/parrot/sdd/config.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'raise ValueError(f"migration destination already exists: {destination}")' config.py)
# AFTER — insert below `            raise ValueError(f"migration destination already exists: {destination}")` (verified: config.py:241)
    from parrot.sdd.scripts import remove_worktree  # lazy: remove_worktree imports this module

    for old_path, _ in topmost:
        live = remove_worktree.live_processes_in(old_path)
        if live:
            pids = ", ".join(str(pid) for pid, _ in live)
            raise ValueError(
                f"legacy worktree has {len(live)} live process(es) inside, wait for them to exit: "
                f"{old_path} (pids: {pids})"
            )
```

```python
# occurrences: 1 (verified: grep -c 'worktree repair {repaired_paths}' config.py)
# AFTER — insert below `    lines.append(f"git -C {quote(str(root))} worktree repair {repaired_paths}")` (verified: config.py:256)
    for _, destination in mappings:
        message = quote(f"error: migrated worktree is not a git checkout: {destination}")
        lines.append(f"git -C {quote(str(destination))} rev-parse --git-dir >/dev/null || {{ echo {message} >&2; exit 1; }}")
```

**Why**: G1 / G2. Every path is shell-quoted. Also add to the docstring's
`Raises:` — "or when a legacy worktree has a live process inside it".
Wrap the long line to 120 columns (black).

### `packages/ai-parrot/tests/sdd/test_config.py` (MODIFY)

```python
# AFTER — append after test_legacy_migration_recipe_shape (verified: test_config.py:335-351)
def test_legacy_migration_refuses_live_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A live process inside a legacy worktree blocks the recipe and is named."""
    from parrot.sdd.scripts import remove_worktree

    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    repo = _git_repo(tmp_path)
    wt = _add_worktree(repo, ".claude/worktrees/hotfix-NAV-1-x", "hotfix-NAV-1-x")
    # FILL IN: monkeypatch remove_worktree.live_processes_in to return [(4242, "claude --agent sdd-worker")]
    #          for wt, assert ValueError match includes str(wt) and "4242"


def test_legacy_migration_recipe_verifies_destinations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every destination is checked with rev-parse after the repair line."""
    # FILL IN: two legacy worktrees; assert two `rev-parse --git-dir` lines, each after the repair line,
    #          each containing its quoted .parrot/worktrees destination
```

### FILL IN checklist

- [ ] `test_legacy_migration_refuses_live_process` body — bounded by AC1
- [ ] `test_legacy_migration_recipe_verifies_destinations` body — bounded by AC2

---

## Acceptance Criteria

- [ ] AC1: live process in a topmost legacy worktree → `ValueError` naming path and PIDs.
- [ ] AC2: one `rev-parse --git-dir` check per destination after `worktree repair`; `test_legacy_migration_recipe_executes` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/sdd/config.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_config.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor_sdd.py -q`

---

## Test Specification

See the blueprint test stubs above.

---

## Agent Instructions

Implement exactly the scope above inside the FEAT-837 worktree; run tests with
`PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note

*(Agent fills this in when done)*

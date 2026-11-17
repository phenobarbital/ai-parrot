# TASK-5734: `parrot sdd experience export` writes into the checkout it runs in

**Feature**: FEAT-905 — `parrot sdd experience export` writes into the checkout it runs in, without home paths
**Spec**: `sdd/specs/experience-sync-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:ebd9db5806f2`

---

## Context

Spec §2 item 1 / §3 Module 1. `experience_cli._dispatch` passes `service.root` (the shared root, i.e. the
primary checkout) as the `checkout` argument of `export_shared` (`experience_cli.py:198`). Run from a linked
worktree, as `/sdd-done` step 7 does, the export lands in `<primary>/sdd/experience/lessons/` and the
`/sdd-done` path check exits 2. The FEAT-887 spec and both `/sdd-done` twins say the export goes into the
checkout it runs in.

---

## Scope

- Add the private helper `_export_checkout(shared_root: Path) -> Path` to `experience_cli.py`.
- Pass `_export_checkout(service.root)` to `export_shared` in the `export` branch of `_dispatch`.
- Change the `export` subparser help to `Export shared lesson definitions into the current checkout.`
- Tests: `test_cli_export_from_linked_worktree_writes_into_worktree` and
  `test_cli_export_ignores_nested_foreign_repository` (spec §4).

**NOT in scope**: `sync.py`, `models.py`, the plane location, graduation and the ledger root (all stay on the
shared root), `/sdd-done` and its twins, a `--checkout` flag, feature scoping of the export.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py` | MODIFY | `find_shared_root` import, `_export_checkout`, export call, help text |
| `packages/ai-parrot/tests/sdd/test_experience_cli.py` | MODIFY | two new tests and their helpers |

---

## Codebase Contract (Anti-Hallucination)

Verified against `70567be025`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py — already imported
from pathlib import Path  # line 11
from parrot.knowledge.wiki.experience.sync import export_shared, register_namespace, sync_global  # line 16
from parrot.knowledge.wiki.ledger.service import LedgerService  # line 17
# to add — defined at packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1568
from parrot.knowledge.wiki.project import find_shared_root

# packages/ai-parrot/tests/sdd/test_experience_cli.py — already imported
import json  # line 5
import logging  # line 6
from pathlib import Path  # line 7
from types import SimpleNamespace  # line 8
import pytest  # line 10
from parrot.sdd.scripts import experience_cli  # line 12
from parrot.sdd.scripts.experience_cli import main  # line 13
# to add
import subprocess
from parrot.knowledge.wiki.experience.fastpath import append_event  # fastpath.py:584
from parrot.knowledge.wiki.experience.models import validate_event  # models.py:225
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py
def _parser() -> argparse.ArgumentParser  # line 31; line 64: verbs.add_parser("export", help="Export shared lesson definitions.")
def _available(service: ExperienceService) -> bool  # line 113
async def _dispatch(args: argparse.Namespace) -> int  # line 139
    # line 198: exported = export_shared(service.plane_dir, service.root)

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def find_shared_root(start: Path | None = None) -> Path | None  # line 1568
    # nearest .git (dir or file) above start, resolved to the primary checkout; None when none is found;
    # never inspects the system temp directory itself

# packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py
def export_shared(repo_plane: Path, checkout: Path) -> Path | None  # line 121; writes checkout/sdd/experience/lessons/<digest>.jsonl

# packages/ai-parrot/tests/sdd/test_experience_cli.py
def _checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, name: str = "primary") -> Path  # line 16
def test_cli_export_writes_under_checkout_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None  # line 98
```

### Does NOT Exist
- ~~`experience_cli._export_checkout`~~ — created by this task.
- ~~a `--checkout` flag~~ — the cwd decides.
- ~~`parrot.knowledge.wiki.project.find_checkout_root` / `find_worktree_root`~~ — no such helper.
  `find_project_root` is not usable: for a worktree under `.parrot/worktrees/` it walks up to the primary
  checkout's `.parrot/wiki.json`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_experience_cli.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py#main",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/sync.py#export_shared"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- From the primary checkout (or a subdirectory), return the `shared_root` object itself, so callers and the
  existing tests see an unchanged value.
- A nearest `.git` entry whose shared root differs (nested repository, submodule), or no `.git` entry at all,
  falls back to `shared_root`. Stop at the first `.git` entry; never keep walking past it.
- `Path.cwd()` / `resolve()` may raise `OSError`; fall back to `shared_root`.
- `main` stays `asyncio.run`-based; the new tests are synchronous.

---

## Implementation Blueprint

### `experience_cli.py`

```python
from parrot.knowledge.wiki.project import find_shared_root  # after the LedgerService import

verbs.add_parser("export", help="Export shared lesson definitions into the current checkout.")


def _export_checkout(shared_root: Path) -> Path:
    """Return the checkout ``export`` writes into.

    The nearest directory above the working directory with a ``.git`` entry is
    the invoking checkout: the primary checkout (a ``.git`` directory) or a
    linked worktree (a ``.git`` file). It is used only when its shared root is
    ``shared_root``; anything else falls back to ``shared_root``.

    Args:
        shared_root: Primary checkout resolved by the experience service.

    Returns:
        The checkout whose ``sdd/experience/lessons/`` receives the export.
    """
    try:
        expected = shared_root.resolve()
        current = Path.cwd().resolve()
    except OSError:
        return shared_root
    for candidate in (current, *current.parents):
        if not (candidate / ".git").exists():
            continue
        found = find_shared_root(candidate)
        if candidate == expected or found is None or found.resolve() != expected:
            return shared_root
        return candidate
    return shared_root

# _dispatch, export branch
exported = export_shared(service.plane_dir, _export_checkout(service.root))
```

### `test_experience_cli.py`

- `_git(cwd: Path, *args: str) -> None` runs `git` with `check=True, capture_output=True`.
- `_recorded_lesson(lesson_id: str) -> dict[str, object]` returns
  `validate_event({...a "lesson.recorded" event...}).model_dump(mode="json")` (same payload shape as
  `test_sync.py::_record`).
- `test_cli_export_from_linked_worktree_writes_into_worktree(tmp_path, monkeypatch, capsys)`: set `PARROT_HOME`;
  `git init -q` a `primary`, an empty commit with `-c user.name=t -c user.email=t@example.com`,
  `git worktree add -q -b linked <tmp>/linked`; create `<primary>/.parrot/experience` and `append_event` one
  recorded lesson; `chdir` into `<linked>/nested`; `main(["export"]) == 0`; the printed path's parent is
  `(<linked>/sdd/experience/lessons).resolve()` and the file exists; `<primary>/sdd/experience` does not exist;
  a second `main(["export"])` returns 0 and prints nothing.
- `test_cli_export_ignores_nested_foreign_repository(tmp_path, monkeypatch)`: `_checkout(...)`, a plane, a
  `vendor/foreign/.git` directory under the checkout, `chdir` there; a `Service` double (as in
  `test_cli_export_writes_under_checkout_root`) and an `export_shared` double that asserts `checkout == root`;
  `main(["export"]) == 0`.

---

## Acceptance Criteria

- [ ] From a linked worktree, `export` writes and prints a path under `<worktree>/sdd/experience/lessons/`, and
      the primary checkout gains no `sdd/experience/`.
- [ ] A second export from the same worktree prints nothing.
- [ ] From the primary checkout or a subdirectory, `export_shared` receives `service.root` (existing tests).
- [ ] Inside a nested foreign repository, `export_shared` receives `service.root`.
- [ ] The worktree test fails on `origin/dev` without the fix. The fallback test passes there too; it guards
      the fallback rule.
- [ ] Every pre-existing test in `test_experience_cli.py` still passes; `ruff check` is clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_experience_cli.py -q`

---

## Test Specification

Spec §4, M1 rows.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug experience-sync-fixes --feature-id FEAT-905`).
2. Verify the Codebase Contract, mark the task `in-progress` in `sdd/tasks/index/experience-sync-fixes.json`.
3. Implement from the blueprint, run the Validation Commands from the worktree root with
   `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the two files listed, close with `scripts/sdd/close_task.sh`, fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (`/sdd-fix` session, actor `agent:sdd-fix:d1ad40b1`)
**Date**: 2026-11-17
**Notes**: code commit `4d8e615b63`. `_export_checkout(shared_root)` walks up from the resolved cwd to the first
directory with a `.git` entry. It returns that directory only when it is not the shared root itself and
`find_shared_root(candidate)` resolves to the shared root; every other case (primary checkout, nested foreign
repository, submodule, no `.git`, `OSError`) returns the `shared_root` object unchanged. The `export` branch
passes it to `export_shared`; plane, graduation and ledger stay on the shared root. Help text updated.
Validation: `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_experience_cli.py -q`
→ 10 passed; `ruff check` and `black --check -l 120` clean on both files. Mutation check: with
`origin/dev`'s `experience_cli.py` restored, `test_cli_export_from_linked_worktree_writes_into_worktree` fails
with the export landing in `primary/sdd/experience/lessons` (the reported bug); restored → passes.
**Deviations from spec**: none. As the task's Acceptance Criteria state, `test_cli_export_ignores_nested_foreign_repository`
also passes on `origin/dev`; it guards the fallback rule, so spec §5's "the new tests fail on `origin/dev`"
applies to the worktree test only.

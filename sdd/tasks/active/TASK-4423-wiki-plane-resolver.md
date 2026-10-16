# TASK-4423: Wiki plane resolver for linked worktrees

**Feature**: FEAT-697 — sdd-coder blast collector must read the wiki plane from the main checkout
**Spec**: `sdd/specs/sdd-coder-complexity-collectors-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:9448f28680e0`

---

## Context

Implements spec §3 Module 1. The wiki plane (`.parrot/wiki`) is git-ignored and
lives only in the main checkout, so every `symbols blast` call made with
`--path <worktree>` exits 1. This task adds the resolver that answers *where the
plane actually is*; TASK-4424 wires it into the collector.

---

## Scope

- Add `_resolve_wiki_plane_root(worktree: Path, policy: ComplexityPolicy) -> Optional[Path]`
  to `complexity_collectors.py`, private to the module.
- Resolution order, first hit wins:
  1. `<worktree>/.parrot/wiki` is a directory → return `worktree`.
  2. Run `git rev-parse --path-format=absolute --git-common-dir` through the
     module's `_run_subprocess` with `cwd=worktree`; on exit 0 take
     `Path(stdout.strip()).resolve().parent` as the main checkout and return it
     if `<main>/.parrot/wiki` is a directory.
  3. Otherwise return `None`.
- The function must never raise: any git failure, timeout, non-zero exit or
  unparseable output degrades to `None`.
- Write unit tests T1, T2 and T6 from spec §4.

**NOT in scope**: changing `_collect_wiki_blast` (that is TASK-4424); touching
`_collect_ruff_cyclomatic` / `_collect_ruff_syntax`; importing anything from
`telemetry.py`; the unrelated open `issue:455ae7a3d8ea` in the same file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py` | MODIFY | Add `_resolve_wiki_plane_root` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py` | MODIFY | Tests T1, T2, T6 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

- `from pathlib import Path` — already imported in `complexity_collectors.py`.
- `_run_subprocess` — defined in the same module at line 1076.
- `ComplexityPolicy` — already imported; exposes `.timeout_seconds` and
  `.max_output_bytes` (used at lines 414, 570, 662).

### Existing Signatures to Use

- `async def _run_subprocess(cmd: List[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> SubprocessResult`
  — `complexity_collectors.py:1076`. `SubprocessResult` carries `.returncode`
  and `.stdout`.

### Does NOT Exist

- No `_resolve_wiki_plane_root` exists yet.
- `ComplexityPolicy` has **no** `plane_root` field — do not reference one.
- `complexity_collectors.py` imports nothing from `telemetry.py`; do not add it.
  `resolve_durable_root` is a *reference pattern only* (`telemetry.py:107-157`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py#_run_subprocess"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

`telemetry.resolve_durable_root` (`telemetry.py:140-150`) already derives the
main checkout the same way:

```python
main_checkout = Path(res.stdout.strip()).resolve().parent
```

Copy the *technique*, not the code: that function resolves a telemetry
directory and raises on failure; this one resolves a wiki plane and returns
`None`.

### Key Constraints

- `async def` — the collector module is async throughout. Never call
  `subprocess.run` directly here; it would block the event loop and trip ruff's
  ASYNC rules.
- Bound the git call with `policy.timeout_seconds` / `policy.max_output_bytes`,
  exactly like the other call sites.
- Google-style docstring, strict type hints, 120-column lines.

---

## Acceptance Criteria

- AC1. Worktree containing `.parrot/wiki` → returns the worktree path.
- AC2. Worktree without a plane whose main checkout has one → returns the main
  checkout path.
- AC3. Neither location has a plane → returns `None`.
- AC4. `git rev-parse` failing, timing out or returning a non-zero exit →
  returns `None`, no exception escapes.
- AC5. `ruff check` clean on both changed files.

---

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src timeout -s KILL 600 pytest \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py -q
ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity_collectors.py \
  packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py
```

---

## Test Specification

- T1 — plane in the worktree: create `tmp_path/.parrot/wiki`, assert the
  resolver returns `tmp_path` and that **no** git subprocess was spawned.
- T2 — plane only in the main checkout: stub `_run_subprocess` to return a
  `SubprocessResult` with `returncode=0` and `stdout=f"{main}/.git\n"`, create
  `main/.parrot/wiki`, assert the resolver returns `main`.
- T6 — git failure: stub `_run_subprocess` to raise / return `returncode=128`,
  assert the resolver returns `None` and nothing propagates.

---

## Agent Instructions

Implement exactly the scope above. Verify every Codebase Contract entry in the
source before using it. Touch only the two listed files. Run the validation
commands before committing. Commit as
`feat(sdd-coder-complexity-collectors-fixes): TASK-4423 — wiki plane resolver for linked worktrees`.

---

## Completion Note

*(fill in on close)*

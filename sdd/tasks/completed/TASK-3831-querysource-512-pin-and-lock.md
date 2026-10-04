# TASK-3831: querysource 5.1.2 pin + lock

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 and Goal G5. The `.venv` already runs querysource 5.1.2, but the
workspace still declares `querysource>=4.1.11` (`ai-parrot[db]`, `ai-parrot[integrations]`)
and `querysource>=5.1.1` (`ai-parrot-tools[db]`), and `uv.lock` pins 5.1.1. CI and the
venv therefore disagree. Every other FEAT-611 staging scenario (S1/S2/S3/S5) is defined
"on querysource 5.1.2", and TASK-3832 (the staging seed) must run on this lock.

**Coordination (spec §3 M1, §8 Q3)**: FEAT-610 (`a2ui-linked-e2e-test`) makes the same pin
change. Whichever feature merges second drops its duplicate hunk and regenerates the lock
on top of the other. Before starting, check whether `dev` already carries `>=5.1.2`
(`grep -n 'querysource>=' packages/ai-parrot/pyproject.toml packages/ai-parrot-tools/pyproject.toml`);
if it does, only the test and the docstring work remain.

---

## Scope

- Raise both `"querysource>=4.1.11",` lines in `packages/ai-parrot/pyproject.toml` (the `db`
  and `integrations` extras) to `"querysource>=5.1.2",`.
- Raise `db = ["querysource>=5.1.1", "psycopg-binary>=3.2"]` in
  `packages/ai-parrot-tools/pyproject.toml` to `>=5.1.2`.
- Regenerate `uv.lock` with `uv lock --upgrade-package querysource` so it locks querysource 5.1.2
  (and navigator-auth ≥0.28.2 if the resolver wants it).
- Update the stale floor test `test_querysource_floor.py`, which asserts the literal
  `"querysource>=5.1.1"` and would otherwise go red.
- Refresh the stale `"4.5.11" at spec time` docstring on `installed_version()` in `_qs.py`.
- Add `test_querysource_version_gate.py`: assert the installed querysource is ≥ 5.1.2.

**NOT in scope**:
- `DIALECT_VERIFIED_AGAINST = "4.5.11"` in `parrot_tools/querysource/dialect.py:20`. That value
  records which querysource the conditions dialect was *verified* against, and
  `test_dialect.py:84-85` pins its behaviour. Changing it is a claim of re-verification, which is
  not this task. `QuerysourceToolkit.__init__` will keep logging a version-mismatch warning
  (toolkit.py:107-111); that is expected.
- `packages/ai-parrot-server/pyproject.toml` (it declares no querysource pin; verified by grep).
- Any `uv sync`, `pip install`, or venv change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Two `querysource>=4.1.11` → `>=5.1.2` (db, integrations extras) |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `db` extra `querysource>=5.1.1` → `>=5.1.2` |
| `uv.lock` | MODIFY | Regenerated with `uv lock --upgrade-package querysource` |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py` | MODIFY | Fix stale `"4.5.11"` docstring on `installed_version()` |
| `packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py` | MODIFY | Floor assertion `>=5.1.1` → `>=5.1.2` |
| `packages/ai-parrot-tools/tests/querysource/test_querysource_version_gate.py` | CREATE | `installed_version() >= 5.1.2` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot_tools.querysource._qs import installed_version  # verified: packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py:67
from packaging.version import Version                        # verified: packaging 26.3 in .venv; ai-parrot declares packaging>=26.2 (uv.lock:92)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py:67-69
def installed_version() -> str:
    """Return ``querysource.version.__version__`` ("4.5.11" at spec time)."""   # line 68 — the stale docstring
    return _load("querysource.version").__version__
# Returns a plain str (e.g. "5.1.2"). _load() raises ImportError with a
# `pip install querysource` hint when querysource is absent (_qs.py:20-22 via parrot._imports.lazy_import).

# packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py:11-15
def test_querysource_floor_is_5_1_1() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    db = data["project"]["optional-dependencies"]["db"]
    assert "querysource>=5.1.1" in db          # line 15 — breaks after the bump

# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py:20,196-205 (read-only context, do NOT edit)
DIALECT_VERIFIED_AGAINST: str = "4.5.11"
def check_version_compatibility(installed: str) -> str | None: ...  # warns on major.minor mismatch
```

Verified manifest lines (current tree, commit `b7399dcef`):
- `packages/ai-parrot/pyproject.toml:225` and `:688` — `    "querysource>=4.1.11",` (2 occurrences)
- `packages/ai-parrot-tools/pyproject.toml:77` — `db = ["querysource>=5.1.1", "psycopg-binary>=3.2"]` (1)
- `uv.lock:13046-13047` — `name = "querysource"` / `version = "5.1.1"`; specifier rows at
  `uv.lock:1006-1007` (`>=4.1.11`) and `uv.lock:2130` (`>=5.1.1`) are rewritten by `uv lock`.
- Installed: `.venv` querysource `5.1.2` (verified `querysource.version.__version__`).

### Does NOT Exist
- ~~A querysource pin in `packages/ai-parrot-server/pyproject.toml`~~ — none; do not add one.
- ~~A runtime version gate in `QuerysourceToolkit`~~ — it only *warns* via `check_version_compatibility`; the
  new test is the gate (spec §4 `test_querysource_version_gate`).
- ~~`installed_version()` returning a `Version` / tuple~~ — it returns `str`; parse it with `packaging.version.Version`.
- ~~`package-lock.json` / pip-tools lockfiles~~ — the workspace lock is `uv.lock` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/pyproject.toml", "action": "MODIFY"},
    {"path": "uv.lock", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/querysource/test_querysource_version_gate.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py#installed_version",
    "sym:packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py#test_querysource_floor_is_5_1_1"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Lock regeneration runs from the main checkout's toolchain, never `uv sync`.** Inside a worktree,
  `uv sync` repoints the shared `.venv` `.pth` files and breaks `import parrot` for every session
  (`.claude/rules/worktree-management.md:49`). `uv lock --upgrade-package querysource` only rewrites
  `uv.lock`; run it from the worktree root that holds the edited `pyproject.toml` files (the lock must
  reflect *this* branch's manifests) and never follow it with `uv sync`.
- Change only the querysource package in the lock. If `uv lock --upgrade-package querysource` also moves
  unrelated packages beyond querysource's own transitive needs (e.g. navigator-auth), record the diff
  summary in the Completion Note — do not hand-edit `uv.lock`.
- The test must not need network or a DB: `installed_version()` only imports `querysource.version`.

### References in Codebase
- `packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py` — tomllib pattern for the floor test.
- `packages/ai-parrot-client-google/tests/unit/reel/test_reel_sdk_contract.py:35` — an existing
  "installed version meets declared floor" test in the repo.

---

## Implementation Blueprint

### Steps (in order)
1. Check `dev` for FEAT-610's pin change first (see Context) — *why*: if it already landed, re-bumping
   creates a conflicting lock hunk.
2. Edit the two `packages/ai-parrot/pyproject.toml` lines and the one `packages/ai-parrot-tools/pyproject.toml`
   line — *why*: G5, all three extras must agree on the floor.
3. Run `uv lock --upgrade-package querysource` at the repo root (no `uv sync`), then
   `grep -n -A1 'name = "querysource"' uv.lock` and confirm `version = "5.1.2"` — *why*: AC1 requires the lock
   to lock 5.1.2, and `--upgrade-package` re-resolves only querysource (and what it pulls), so the rest of the
   lock does not churn.
4. Update `test_querysource_floor.py` to the new floor — *why*: it asserts the literal old string and would fail.
5. Fix the `_qs.py:68` docstring — *why*: it states a version that is no longer true.
6. Create `test_querysource_version_gate.py` — *why*: spec §4 names it as the runtime proof that the env is on 5.1.2.
7. Run the Validation Commands and `ruff check` on the two Python files.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 2 (verified: grep -c '    "querysource>=4.1.11",' packages/ai-parrot/pyproject.toml)
# FILL IN: disambiguate — quote enough surrounding context to make each anchor unique:
#   (a) db extra (verified :224-225):
#         db = [
#             "querysource>=4.1.11",          →  "querysource>=5.1.2",
#   (b) integrations extra (verified :687-688):
#         integrations = [
#             "querysource>=4.1.11",          →  "querysource>=5.1.2",
# Both lines change identically, so `replace_all` on the exact line is acceptable.
```
**Why**: the `db` and `integrations` extras are the two places `ai-parrot` pulls querysource (spec §3 M1).

### `packages/ai-parrot-tools/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c 'db = \["querysource>=5.1.1", "psycopg-binary>=3.2"\]' packages/ai-parrot-tools/pyproject.toml)
# REPLACE line (verified: packages/ai-parrot-tools/pyproject.toml:77)
db = ["querysource>=5.1.2", "psycopg-binary>=3.2"]
```
**Why**: `ai-parrot-tools[db]` is the extra `QuerysourceToolkit` users install.

### `uv.lock` (MODIFY — regenerate, never hand-edit)
```bash
# occurrences: 1 (verified: grep -c '^name = "querysource"$' uv.lock → uv.lock:13046, version "5.1.1" at :13047)
uv lock --upgrade-package querysource
grep -n -A1 '^name = "querysource"$' uv.lock          # expect: version = "5.1.2"
grep -n 'name = "querysource", marker' uv.lock        # expect every specifier ">=5.1.2"
```
**Why**: the lock is the CI source of truth; the explicit `--upgrade-package` moves querysource to the newest
release without re-resolving the rest of the workspace.

### `packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '("4.5.11" at spec time)' packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py)
# REPLACE the docstring line (verified: packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py:68)
    """Return ``querysource.version.__version__`` (the workspace floor is 5.1.2, FEAT-611)."""
```
**Why**: the old text claims 4.5.11; the behaviour is unchanged.

### `packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert "querysource>=5.1.1" in db' packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py)
# Update the module docstring (:1), rename the test (:11) and the assertion (:15):
"""FEAT-598 AC12 / FEAT-611 M1: ai-parrot-tools declares querysource>=5.1.2 (no runtime gate)."""
...
def test_querysource_floor_is_5_1_2() -> None:
    """Pin the querysource floor declared by the db extra."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    db = data["project"]["optional-dependencies"]["db"]
    assert "querysource>=5.1.2" in db
```
**Why**: keeps the manifest floor pinned by a test, now at the new value.

### `packages/ai-parrot-tools/tests/querysource/test_querysource_version_gate.py` (CREATE)
```python
"""FEAT-611 M1: the environment runs querysource >= 5.1.2 (spec §4 test_querysource_version_gate)."""

from __future__ import annotations

import pytest
from packaging.version import Version

from parrot_tools.querysource._qs import installed_version

MIN_QUERYSOURCE = Version("5.1.2")


def test_querysource_version_gate() -> None:
    """installed_version() parses and is at least the workspace floor."""
    try:
        raw = installed_version()
    except ImportError:
        # FILL IN: skip vs fail when querysource is absent — bounded by AC1 (the gate must FAIL in an env
        # that has the [db] extra; a bare install without querysource may skip). Default: pytest.skip(...).
        pytest.skip("querysource not installed ([db] extra absent)")
    assert Version(raw) >= MIN_QUERYSOURCE, f"querysource {raw} < {MIN_QUERYSOURCE}"
```
**Why**: `installed_version()` returns a `str`, so parse it with `packaging` instead of comparing strings
("5.10" < "5.9" lexically).

### FILL IN checklist
- [ ] `pyproject.toml` (ai-parrot) — both anchors disambiguated by their extra name; bounded by occurrence count 2.
- [ ] `test_querysource_version_gate.py` — skip vs fail on ImportError; bounded by AC1.
- [ ] `uv.lock` — confirm `version = "5.1.2"` and all querysource specifiers `>=5.1.2`; bounded by AC1.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot` (db, integrations) and `ai-parrot-tools` (db) pin `querysource>=5.1.2`.
- [ ] `uv.lock` locks querysource `5.1.2`; the lock was produced by `uv lock`, not by hand; no `uv sync` was run.
- [ ] `test_querysource_version_gate` and `test_querysource_floor_is_5_1_2` pass.
- [ ] The existing querysource toolkit suite still passes on 5.1.2 (spec AC2, the toolkit half).
- [ ] `_qs.py` no longer mentions 4.5.11; `dialect.py` is untouched.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py packages/ai-parrot-tools/tests/querysource/test_querysource_version_gate.py packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-tools/tests/querysource/test_querysource_version_gate.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_qs_imports_and_errors.py packages/ai-parrot-tools/tests/querysource/test_dialect.py packages/ai-parrot-tools/tests/querysource/test_multiquery_tools.py -q`

---

## Test Specification

See the `test_querysource_version_gate.py` CREATE block above; it is the whole test. The floor test is the
existing one with the new literal.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none. This task is **exclusive** (`parallel: false`): it rewrites
   `uv.lock` and two `pyproject.toml` manifests, so no other task may run beside it.
4. **Verify the Codebase Contract** — re-run the `grep -c` counts in each blueprint block before editing
5. **Update status** in `sdd/tasks/index/a2ui-linked-e2e-parallel.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker.
   **Never run `uv sync` in a worktree**; `uv lock --upgrade-package querysource` only.
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3831 a2ui-linked-e2e-parallel verified`
10. **Fill in the Completion Note** below (include the `uv.lock` package-change summary), then commit the staged SDD state

---

## Completion Note

**Completed by**: Claude (session_01CFWijXsJLATx5g6k94o1EP), feature worktree
**Date**: 2026-09-28
**Notes**: Raised `querysource>=5.1.2` in `ai-parrot[db,integrations]` and `ai-parrot-tools[db]`, and regenerated `uv.lock` with `uv lock --upgrade-package querysource` (querysource 5.1.1 → 5.1.2, every specifier `>=5.1.2`). Updated the `_qs.installed_version` docstring and `test_querysource_floor.py`, and added `test_querysource_version_gate.py`. The shared venv was already upgraded to querysource 5.1.2 before this task (a targeted `uv pip install`; the freeze from before is kept in the session scratchpad). `tests/querysource`: 98 passed; ruff clean.

**Deviations from spec**:
- The lock was regenerated with uv 0.12.19 (`uvx --from uv`) instead of the installed uv 0.9.13. uv 0.9.13 rewrote marker formatting across 6.5k lines; 0.12.19 matches the committed lock's format (40-line diff).
- The lock diff also picks up the `hooba` extra that is already declared in `packages/ai-parrot-tools/pyproject.toml` on dev but was never locked. That is pre-existing drift, not something this task introduced.
- `DIALECT_VERIFIED_AGAINST="4.5.11"` is intentionally unchanged, as the task specifies.

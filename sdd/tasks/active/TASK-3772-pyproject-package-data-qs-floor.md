# TASK-3772: Ship linked/contract as package data + querysource>=5.1.1 floor

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3769
**Assigned-to**: unassigned

---

## Context

Two manifest edits the feature needs, grouped into ONE exclusive task because both mutate shared
dependency manifests / the workspace lockfile:

1. **S7 / M12**: the linked contract (`linked/contract/schema.json` and `contract/fixtures/**/*.json`)
   is *installable package data* — `pip install ai-parrot` must ship it to third-party renderer teams.
   The core `[tool.setuptools.package-data]` table does not include it today.
2. **AC12 / M7**: `ai-parrot-tools` must declare `querysource>=5.1.1` (FEAT-151 tenant MultiQuery
   dispatch + FEAT-150 `principal=`). No runtime version gate exists (AC5).

This task is `parallel: false`: it edits `pyproject.toml` files and `uv.lock`.

---

## Scope

- Add a `"parrot.outputs.a2ui.linked"` entry to `packages/ai-parrot/pyproject.toml`
  `[tool.setuptools.package-data]`.
- Change `packages/ai-parrot-tools/pyproject.toml` `db` extra to `querysource>=5.1.1`.
- Re-lock: `uv lock --upgrade-package querysource` so `uv.lock` records the new specifier and
  resolves `querysource` to `>=5.1.1` (it currently locks **5.0.0**).
- Add two small tests that pin both declarations.

**NOT in scope**: creating any contract file (TASK-3770/TASK-3771/TASK-3773/TASK-3774/TASK-3778/TASK-3790 do); the core
`ai-parrot` extras `db`/`integrations` that still say `querysource>=4.1.11`
(`packages/ai-parrot/pyproject.toml:225,677`) — the spec's AC12 names only `ai-parrot-tools`; leave them and note
it in the Completion Note. `DIALECT_VERIFIED_AGAINST` in `dialect.py` (owned by TASK-3782's file).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | package-data entry for `parrot.outputs.a2ui.linked` |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `querysource>=5.1.1` in the `db` extra |
| `uv.lock` | MODIFY | re-locked (`uv lock --upgrade-package querysource`) |
| `packages/ai-parrot/tests/outputs/a2ui/test_linked_package_data.py` | CREATE | pins the package-data globs |
| `packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py` | CREATE | pins the floor |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tomllib            # stdlib; requires-python >=3.11 (packages/ai-parrot/pyproject.toml:18, ai-parrot-tools/pyproject.toml:8)
from pathlib import Path
```

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml
[tool.setuptools.package-data]                       # L939
parrot = ["py.typed", "templates/*.tpl", "**/*.pyx", "**/*.pxd"]   # L940 — does NOT cover *.json
"parrot.observability.cost.pricing" = ["*.json"]      # L970 — existing precedent for a json glob entry
[tool.setuptools.packages.find]  where=["src"] include=["parrot*"] namespaces=true   # L934-937

# packages/ai-parrot-tools/pyproject.toml
db = ["querysource>=4.5.11", "psycopg-binary>=3.2"]   # L77

# uv.lock
# L1865 `name = "ai-parrot-tools"` … L2114: { name = "querysource", marker = "extra == 'db'", specifier = ">=4.5.11" }
# L13030-13031: name = "querysource" / version = "5.0.0"   ← locked below the new floor
```
Installed in the shared venv: `querysource 5.1.1`.

### Does NOT Exist
- ~~any `"parrot.outputs.a2ui.linked"` package-data entry~~ — added here.
- ~~`supports_tenant_multiquery`, `TenantMultiQueryUnsupportedError`, a runtime `>=5.1.0` gate~~ — never built (AC5).
- ~~`contract/__init__.py`~~ — `contract/` is a data directory, NOT a package; setuptools reaches it through the `parrot.outputs.a2ui.linked` package entry with sub-path globs.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/pyproject.toml", "action": "MODIFY"},
    {"path": "uv.lock", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/test_linked_package_data.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Package-data globs are relative to the package directory `parrot/outputs/a2ui/linked/`:
  `["contract/*.json", "contract/fixtures/*/*.json"]` (schema at depth 1, fixtures at
  `fixtures/{conditions,dsl,envelopes}/*.json`). setuptools does not need the files to exist yet.
- **Locking**: run `uv lock --upgrade-package querysource` in the task's own environment. NEVER run
  `uv sync` inside a worktree (it repoints the shared venv's `.pth` — `.claude/rules/worktree-management.md` §4).
  If `uv lock` cannot run in your sandbox (no network), do the two pyproject edits + tests, and set the task to
  `done-with-issues` stating "uv.lock not re-locked — operator must run `uv lock --upgrade-package querysource`";
  never hand-edit `uv.lock`.
- Keep the diff to exactly these lines; no reformatting of the TOML files.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `packages/ai-parrot/pyproject.toml` — *why*: S7, the contract must be in the wheel.
2. Edit `packages/ai-parrot-tools/pyproject.toml` — *why*: AC12 floor.
3. `uv lock --upgrade-package querysource` — *why*: lock currently pins 5.0.0, below the new floor.
4. Write the two tests; run them.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"parrot.observability.cost.pricing" = \["\*.json"\]' packages/ai-parrot/pyproject.toml)
# AFTER — insert below `"parrot.observability.cost.pricing" = ["*.json"]` (verified: packages/ai-parrot/pyproject.toml:970)
# FEAT-598: installable linked-surface contract (JSON Schema + golden fixtures) for renderer teams.
"parrot.outputs.a2ui.linked" = ["contract/*.json", "contract/fixtures/*/*.json"]
```

### `packages/ai-parrot-tools/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c 'db = \["querysource>=4.5.11", "psycopg-binary>=3.2"\]' packages/ai-parrot-tools/pyproject.toml)
# REPLACE line 77 `db = ["querysource>=4.5.11", "psycopg-binary>=3.2"]` with:
db = ["querysource>=5.1.1", "psycopg-binary>=3.2"]
```

### `uv.lock` (MODIFY)
Generated by `uv lock --upgrade-package querysource` — expected diff: L2114 specifier `>=5.1.1`, the
`querysource` package block version `>=5.1.1` (and its transitive pins if any). Do not hand-edit.

### `packages/ai-parrot/tests/outputs/a2ui/test_linked_package_data.py` (CREATE)
```python
"""FEAT-598 S7: the linked contract ships as package data."""
from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"   # packages/ai-parrot/pyproject.toml


def test_linked_contract_is_package_data() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    globs = data["tool"]["setuptools"]["package-data"]["parrot.outputs.a2ui.linked"]
    assert "contract/*.json" in globs
    assert "contract/fixtures/*/*.json" in globs
```

### `packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py` (CREATE)
```python
"""FEAT-598 AC12: ai-parrot-tools declares querysource>=5.1.1 (no runtime gate)."""
from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"   # packages/ai-parrot-tools/pyproject.toml


def test_querysource_floor_is_5_1_1() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    db = data["project"]["optional-dependencies"]["db"]
    assert "querysource>=5.1.1" in db
```
(`tests/querysource/conftest.py` imports `asyncdb` and `parrot_tools.querysource._qs` at module import — both
available in the shared venv; the test itself needs neither.)

### FILL IN checklist
- [ ] Run `uv lock --upgrade-package querysource`, or record why it could not run (see Implementation Notes)

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-tools/pyproject.toml` declares `querysource>=5.1.1` (AC12).
- [ ] Core package-data includes the linked contract globs (S7, AC7 "shipped as package data").
- [ ] `uv.lock` re-locked by `uv` (never hand-edited) or the gap explicitly reported.
- [ ] No other line in either pyproject changes; no new runtime dependency (AC12).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/test_linked_package_data.py -q`
- `pytest packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py -q`

---

## Test Specification

```python
def test_linked_contract_is_package_data(): ...   # tomllib pin on the two globs
def test_querysource_floor_is_5_1_1(): ...        # tomllib pin on the db extra
```

---

## Agent Instructions

1. Read spec AC7, AC12, §9 S7.
2. No dependencies. This task is **exclusive** (`parallel: false`) — nothing else runs alongside it.
3. Index → `in-progress`; edit; lock; test.
4. Move to `sdd/tasks/completed/`, index → `done`, Completion Note (mention the untouched core `>=4.1.11` extras).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

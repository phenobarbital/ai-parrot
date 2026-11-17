# TASK-5252: `ontology-store` extra in packages/ai-parrot/pyproject.toml

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 11 adds the extra
`ontology-store = ["asyncpg>=0.29", "pgvector>=0.2", "rdflib>=7.0", "pyshacl>=0.26", "numpy>=1.26"]`.
It is pulled forward into its own first-wave task because `rdflib` and `pyshacl` are **not
installed** in the shared venv today (verified 2026-11-06 with `uv pip list`), and the Turtle and
validation tasks (TASK-5258, TASK-5259) cannot run their tests without them. Worktree agents may
not install into the shared environment (`.claude/rules/worktree-management.md` §4), so the
installation is a host-operator step this task triggers. The CLI registration half of Module 11
stays in TASK-5267.

---

## Scope

- Add the `ontology-store` extra right after the `graphindex-postgres` extra, with a two-line
  comment naming FEAT-824.
- Lockfile: run `uv lock --check` **before** editing. If it passes and the environment has network
  access, run `uv lock` after the edit and confirm the lock diff only adds the new extra and the
  `rdflib`/`pyshacl` (and their transitive) packages. If `--check` already failed before the edit,
  or there is no network, do **not** relock — leave `uv.lock` untouched and say so in the
  Completion Note for the host operator (a stale-lock relock widens the diff far beyond this task).
- Create a test asserting the extra exists with exactly those five requirements.
- In the Completion Note, tell the host operator to run, in the **main checkout**:
  `source .venv/bin/activate && uv pip install 'rdflib>=7.0' 'pyshacl>=0.26'`
  before TASK-5258 and TASK-5259 are dispatched.

**NOT in scope**: `parrot/cli/__init__.py` (TASK-5267); `uv sync` anywhere; adding the extra to the
`all` meta-extra.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | new `ontology-store` extra |
| `uv.lock` | MODIFY | only under the conditions in Scope |
| `packages/ai-parrot/tests/knowledge/ontology/test_ontology_store_extra.py` | CREATE | extra contents test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tomllib   # stdlib (Python >= 3.11)
```

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml:294-299  (occurrences of the anchor: 1)
# GraphIndex Postgres backend (FEAT-520) — bitemporal graph + wiki plane over
# asyncpg. Zero SQLAlchemy (U4/D8); PgVectorStore is explicitly excluded.
graphindex-postgres = [
    "asyncpg>=0.29",
    "pgvector>=0.2",
]
```

### Does NOT Exist
- ~~an `ontology-store` extra~~ — created here.
- ~~`rdflib`, `pyshacl` in any `pyproject.toml`~~ — this task adds the first declaration.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "uv.lock", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/test_ontology_store_extra.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `uv lock --check` — *why*: decides whether relocking is safe (Scope).
2. Insert the extra below `graphindex-postgres` — *why*: groups the PostgreSQL-backed extras.
3. Relock only if Scope allows; inspect `git diff --stat uv.lock`.
4. Write and run the test.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c 'graphindex-postgres = \[' packages/ai-parrot/pyproject.toml)
# AFTER — insert below the closing `]` of `graphindex-postgres = [` (verified: pyproject.toml:296-299)

# Ontology vocabulary store (FEAT-824) — PostgreSQL OntologyStore, Turtle publication,
# SHACL validation and SQLite snapshots.
ontology-store = [
    "asyncpg>=0.29",
    "pgvector>=0.2",
    "rdflib>=7.0",
    "pyshacl>=0.26",
    "numpy>=1.26",
]
```

### `packages/ai-parrot/tests/knowledge/ontology/test_ontology_store_extra.py` (CREATE)
```python
"""The ontology-store extra declares the vocabulary store's drivers (FEAT-824)."""
from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


def test_ontology_store_extra() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    extra = data["project"]["optional-dependencies"]["ontology-store"]
    assert sorted(extra) == sorted(
        ["asyncpg>=0.29", "pgvector>=0.2", "rdflib>=7.0", "pyshacl>=0.26", "numpy>=1.26"]
    )
```

### FILL IN checklist
- [ ] lockfile decision recorded in the Completion Note (relocked / left for host, and why).
- [ ] host-operator install instruction in the Completion Note.

---

## Acceptance Criteria

- [ ] The extra exists with the five requirements of spec Module 11.
- [ ] `uv.lock` either untouched or changed only by the new extra's packages.
- [ ] No `uv sync` was run in the worktree.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/test_ontology_store_extra.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug ontology-backend --feature-id FEAT-824`).
2. Mark `in-progress`, implement, run the Validation Commands, commit only the files listed above.
3. Close with `parrot sdd task close TASK-5252 ontology-backend verified`; fill in the Completion Note,
   including the host-operator install line.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 164s.
Merge-tier validation green (only baseline red: test_taxonomy_loads). Lockfile: `uv.lock` left untouched (host operator relocks if desired).
Host operator: `source .venv/bin/activate && uv pip install 'rdflib>=7.0' 'pyshacl>=0.26'` — rdflib/pyshacl already importable in the shared venv as of this run.

**Completed by**: sdd-worker (coder: gpt-5.6-terra)
**Date**: 2026-11-07
**Notes**:

**Deviations from spec**: the extra moved from Module 11's task to this first-wave task so the
Turtle/validation tasks can run their tests (rdflib/pyshacl not installed).

# TASK-4463: ai-parrot-semantic distribution skeleton (M1)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

First task of FEAT-704 (spec §3 Module 1). It makes `parrot.semantic` an installable PEP 420 satellite distribution that confines the AGPL-3.0 `sidemantic` dependency (spec §2 item 8, §8 Q1 — sign-off recorded 2026-10-19, Jesus Lara). Every other satellite task imports from this package, and the shared test fixtures for subjects and PBAC guard doubles live in the `conftest.py` created here.

---

## Scope

- Create `packages/ai-parrot-semantic/pyproject.toml` mirroring `packages/ai-parrot-embeddings/pyproject.toml` (setuptools, `dynamic = ["version"]`, `license = "MIT"`, `requires-python = ">=3.11,<3.14"`, `namespaces = true`).
- Pin `sidemantic==0.12.0`, `sqlglot>=30.1,<31`, `jsonschema>=4.20`, `pyyaml>=6`, `ai-parrot`; extras `bigquery` (`google-cloud-bigquery>=3.30`) and `duckdb` (`duckdb>=1.0`).
- Create `packages/ai-parrot-semantic/README.md` with a section "License notice: sidemantic is AGPL-3.0" spelling out the network clause and the sign-off line (Jesus Lara, 2026-10-19).
- Create `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` and `packages/ai-parrot-semantic/src/parrot/semantic/version.py` (`__version__ = "1.3.0"`). NO `src/parrot/__init__.py` (PEP 420).
- Create `packages/ai-parrot-semantic/tests/__init__.py`, `packages/ai-parrot-semantic/tests/conftest.py` (subject + guard fixtures) and `packages/ai-parrot-semantic/tests/test_packaging.py`.
- Register the workspace source in root `pyproject.toml`, the `Package` entry in `scripts/release.py`, the TID251 `sidemantic` ban + per-file ignore in `ruff.toml`, and a `test-semantic` CI job.
- Run `uv lock` (lock only — never `uv sync` in a worktree) and commit `uv.lock`.

**NOT in scope**: any `parrot.semantic` module beyond `__init__`/`version` (TASK-4464+); model/DuckDB fixtures (TASK-4467 owns `tests/_models.py`); installing packages into the shared venv (operator action, see Notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/pyproject.toml` | CREATE | distribution metadata, pins, extras |
| `packages/ai-parrot-semantic/README.md` | CREATE | package README with AGPL notice |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | CREATE | package root (finalized by TASK-4477) |
| `packages/ai-parrot-semantic/src/parrot/semantic/version.py` | CREATE | `__version__` for setuptools dynamic + release.py |
| `packages/ai-parrot-semantic/tests/__init__.py` | CREATE | test package marker |
| `packages/ai-parrot-semantic/tests/conftest.py` | CREATE | pctx_factory + guard double fixtures |
| `packages/ai-parrot-semantic/tests/test_packaging.py` | CREATE | namespace + import-ban tests |
| `pyproject.toml` | MODIFY | workspace source entry |
| `uv.lock` | MODIFY | lock the new member (uv lock) |
| `scripts/release.py` | MODIFY | PACKAGES entry |
| `ruff.toml` | MODIFY | TID251 sidemantic ban + per-file ignore |
| `.github/workflows/ci.yml` | MODIFY | test-semantic job |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.auth import PermissionContext, UserSession, DataPlanePolicyGuard  # verified: packages/ai-parrot/src/parrot/auth/__init__.py (lazy map, lines 33,34,45)
from parrot.auth.exceptions import AuthorizationRequired                     # verified: packages/ai-parrot/src/parrot/auth/exceptions.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/permission.py
class UserSession:            # line 21 — frozen dataclass: user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict[str, Any] (lines 46-49)
class PermissionContext:      # line 81 — session: UserSession; request_id; channel; trace_context; extra (lines 122-126)
# packages/ai-parrot/src/parrot/auth/dataplane_guard.py
class DataPlanePolicyGuard:   # line 45
    async def authorize_source(self, ctx, resources) -> None        # line 193 — raises AuthorizationRequired on deny
    async def rls_predicates(self, ctx, resources) -> list           # line 316
# scripts/release.py:116  — `PACKAGES: list[Package] = [` ; entries look like
#   Package("ai-parrot-embeddings", [("packages/ai-parrot-embeddings/src/parrot/embeddings/version.py", "python")],
#           "packages/ai-parrot-embeddings", aliases=["embeddings"]),
# packages/ai-parrot-embeddings/pyproject.toml:106-112 — [tool.setuptools.dynamic] version = {attr = "..."};
#   [tool.setuptools.packages.find] where=["src"] include=["parrot*"] namespaces=true
# packages/ai-parrot-embeddings/src/parrot/embeddings/version.py — __title__/__description__/__version__/__author__/__license__ style
```

### Does NOT Exist
- ~~`packages/ai-parrot-semantic/`~~, ~~`parrot.semantic`~~ — created by this task.
- ~~`packages/ai-parrot-semantic/src/parrot/__init__.py`~~ — must NOT be created (PEP 420 namespace).
- ~~`parrot_tools.semantic`~~ — must never exist (AGPL boundary).
- ~~A `sidemantic` entry in `ruff.toml`~~ — the banned-api table (ruff.toml:125-135) lists only requests/httpx/starlette/fastapi/uvicorn/langchain*/langgraph/langsmith.
- ~~A CI job running the satellite tests~~ — `test-tool-optimizations` syncs only `ai-parrot-tools` (`uv sync --package ai-parrot-tools`), so the satellite needs its OWN job (the spec's 'step after ci.yml:506' would run without sidemantic installed).
- ~~`sidemantic` in the shared venv~~ — not installed (2026-10-19); tests that import it are skipped until the operator installs it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/pyproject.toml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/README.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/version.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/conftest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_packaging.py",
      "action": "CREATE"
    },
    {
      "path": "pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "uv.lock",
      "action": "MODIFY"
    },
    {
      "path": "scripts/release.py",
      "action": "MODIFY"
    },
    {
      "path": "ruff.toml",
      "action": "MODIFY"
    },
    {
      "path": ".github/workflows/ci.yml",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext",
    "sym:packages/ai-parrot/src/parrot/auth/dataplane_guard.py#DataPlanePolicyGuard"
  ]
}
```

---

## Implementation Notes

- **Operator action after merge of this task (write it in the Completion Note):** from the main checkout, `source .venv/bin/activate && uv pip install -e packages/ai-parrot-semantic[duckdb]` — worktree agents must not install into the shared venv (worktree rule §4).
- `test_packaging.py` uses `pytest.importorskip("sidemantic")` only where it imports sidemantic; the namespace test must pass without it.
- The `ruff` import-ban test runs `ruff check --select TID251` on temp files via `subprocess` with `--config ruff.toml` from the repo root.

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Create the package files (pyproject, README, version, `__init__`) — *why*: everything else imports `parrot.semantic`.
2. Append `ai-parrot-semantic = { workspace = true }` after `ai-parrot-openlit-bridge = { workspace = true }` in root `pyproject.toml` — *why*: workspace source resolution.
3. Add the `Package(...)` entry to `scripts/release.py` `PACKAGES` — *why*: AC17, the release tool must bump it.
4. Add the TID251 ban and the satellite per-file ignore to `ruff.toml` — *why*: AC1 enforces the AGPL boundary mechanically.
5. Insert a `test-semantic` job above `  test-loaders:` in `ci.yml` — *why*: AC16 requires the suite in CI.
6. Run `uv lock` (no sync) and stage `uv.lock` — *why*: CI uses the lock.
7. Write conftest fixtures and `test_packaging.py`; run them — *why*: later tasks reuse the fixtures.

### `packages/ai-parrot-semantic/pyproject.toml` (CREATE)
```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-parrot-semantic"
dynamic = ["version"]
description = "Governed semantic layer for AI-Parrot agents (sidemantic core + sqlglot governance)"
readme = "README.md"
requires-python = ">=3.11,<3.14"
license = "MIT"
authors = [{name = "Jesus Lara", email = "jesuslara@phenobarbital.info"}]
keywords = ["ai", "semantic-layer", "metrics", "sql", "governance"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Programming Language :: Python :: 3 :: Only",
    "Framework :: AsyncIO",
    "Typing :: Typed",
]
dependencies = [
    "ai-parrot",
    "sidemantic==0.12.0",   # AGPL-3.0 — see README "License notice"; exact pin (spec §7)
    "sqlglot>=30.1,<31",
    "jsonschema>=4.20",
    "pyyaml>=6",
]

[project.optional-dependencies]
bigquery = ["google-cloud-bigquery>=3.30"]
duckdb = ["duckdb>=1.0"]

[tool.setuptools.dynamic]
version = {attr = "parrot.semantic.version.__version__"}

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true

[tool.setuptools.package-data]
"parrot.semantic" = ["schemas/*.json", "sql/*.sql"]
```
**Why this shape**: mirrors the embeddings satellite exactly (spec §6 Integration Points); `package-data` ships the vendored Ossie schema (TASK-4466) and the audit DDL (TASK-4474).

### `packages/ai-parrot-semantic/src/parrot/semantic/version.py` (CREATE)
```python
"""AI-Parrot Semantic Layer meta information."""

__title__ = "ai-parrot-semantic"
__description__ = "Governed semantic layer for AI-Parrot agents."
__version__ = "1.3.0"
__author__ = "Jesus Lara"
__author_email__ = "jesuslara@phenobarbital.info"
__license__ = "MIT"
```

### `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` (CREATE)
```python
"""ai-parrot-semantic — governed semantic layer (sidemantic core + sqlglot governance)."""
from .version import __version__

__all__ = ["__version__"]
```
**Why**: TASK-4477 finalizes the exports; keep the anchor line `__all__ = ["__version__"]` verbatim so its MODIFY block attaches.

### `packages/ai-parrot-semantic/README.md` (CREATE)
```markdown
# ai-parrot-semantic

Governed semantic layer for AI-Parrot agents: metric queries compiled by sidemantic,
authorized/filtered/masked by ai-parrot's sqlglot governance pipeline (PBAC, RLS push-down,
column lineage, positive SQL guard, signed audit).

## Install
    pip install ai-parrot-semantic[duckdb]      # or [bigquery]

## License notice: sidemantic is AGPL-3.0
This package is MIT-licensed, but it depends on `sidemantic==0.12.0`, which is **AGPL-3.0**.
<!-- FILL IN: 4–6 sentences on the AGPL §13 network clause: offering the semantic layer over a
network (HTTP handler, MCP) to users obliges offering the corresponding source of sidemantic
and any modifications to it; this distribution is opt-in and confines every sidemantic import. -->
Legal sign-off: Jesus Lara, 2026-10-19 (FEAT-704 spec §8 Q1).
```
**Why**: AC16 requires the AGPL notice; the sign-off line is fixed by spec §8 Q1.

### `pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c -F 'ai-parrot-openlit-bridge = { workspace = true }' pyproject.toml)
# AFTER — insert below `ai-parrot-openlit-bridge = { workspace = true }` (verified: pyproject.toml:239)
ai-parrot-semantic = { workspace = true }
```

### `scripts/release.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'PACKAGES: list[Package] = [' scripts/release.py)
# Append as the LAST entry inside the PACKAGES list that starts at scripts/release.py:116
    Package("ai-parrot-semantic",
            [("packages/ai-parrot-semantic/src/parrot/semantic/version.py", "python")],
            "packages/ai-parrot-semantic", aliases=["semantic"]),
```
**Why**: a new satellite must be bumped with the others (AC17); the Makefile comment above PACKAGES says to keep both in sync — FILL IN: add the matching `*_VERSION_FILE` variable to the Makefile ONLY if the Makefile lists the other satellites (check, do not guess).

### `ruff.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c -F '[lint.flake8-tidy-imports.banned-api]' ruff.toml)
# AFTER — append below the `"langsmith".msg` line of the table that starts at ruff.toml:125
"sidemantic".msg          = "AGPL-3.0 dependency confined to ai-parrot-semantic; import it only under packages/ai-parrot-semantic/."

# occurrences: 1 (verified: grep -c -F '[lint.per-file-ignores]' ruff.toml)
# AFTER — add inside the table that starts at ruff.toml:137 (e.g. after the conftest line)
"packages/ai-parrot-semantic/**" = ["TID251"]
```
**Why**: AC1 — `ruff check` must flag `import sidemantic` anywhere else. FILL IN: if a later `per-file-ignores` key also matches satellite test files (e.g. `"**/tests/**/*.py"`), confirm ruff merges the two lists (it does for distinct globs) by running the ban test.

### `.github/workflows/ci.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c -F '  test-loaders:' .github/workflows/ci.yml)
# BEFORE — insert above `  test-loaders:` (verified: ci.yml:508); copy the checkout / python / uv
# setup steps verbatim from the job that contains ci.yml:506 (test-tool-optimizations)
  test-semantic:
    name: "Test ai-parrot-semantic (Python ${{ matrix.python-version }})"
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12"]
    steps:
      # FILL IN: checkout, setup-python, setup-uv steps copied from test-tool-optimizations
      - name: Sync semantic package
        run: uv sync --package ai-parrot-semantic --extra duckdb
      - name: Scaffold NavConfig environment
        run: mkdir -p env/dev && touch env/dev/.env
      - name: Run semantic-layer tests
        run: uv run pytest packages/ai-parrot-semantic/tests -q --tb=short
```
**Why**: the tool-optimizations job syncs only `ai-parrot-tools`, so sidemantic would be missing there (drift from the spec's Edit Sites row — recorded in Does NOT Exist).

### `packages/ai-parrot-semantic/tests/conftest.py` (CREATE)
```python
"""Shared fixtures for ai-parrot-semantic tests: subjects and PBAC guard doubles."""
from __future__ import annotations

from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth import DataPlanePolicyGuard, PermissionContext, UserSession
from parrot.auth.exceptions import AuthorizationRequired


@pytest.fixture
def pctx_factory() -> Callable[..., PermissionContext]:
    """Build PermissionContext(UserSession(...)) for subjects A/B."""
    def _make(user_id: str = "user-a", tenant_id: str = "t1", roles: tuple[str, ...] = ("analyst",),
              **metadata: Any) -> PermissionContext:
        # FILL IN: construct UserSession(user_id=, tenant_id=, roles=frozenset(roles), metadata=metadata)
        # and PermissionContext(session=...) — check the dataclass field names at permission.py:46-49/122-126
        raise NotImplementedError
    return _make


def _guard(authorize_side_effect: Any = None) -> MagicMock:
    guard = MagicMock(spec=DataPlanePolicyGuard)
    guard.authorize_source = AsyncMock(side_effect=authorize_side_effect)
    guard.rls_predicates = AsyncMock(return_value=[])
    return guard


@pytest.fixture
def allow_all_guard() -> MagicMock:
    """Guard double that authorizes every resource."""
    return _guard()


@pytest.fixture
def deny_table_guard() -> Callable[[str], MagicMock]:
    """Factory: guard double denying `table:read` for one `schema.table`."""
    def _make(table: str) -> MagicMock:
        async def _authorize(ctx: Any, resources: Any) -> None:
            # FILL IN: raise AuthorizationRequired(tool_name="dataplane_authz", message=...) when any
            # entry of resources.tables ends with f":{table}"; signature at auth/exceptions.py:12
            return None
        return _guard(_authorize)
    return _make
```
**Why**: spec §4 Test Data lists `pctx_factory` and `allow_all_guard / deny_table_guard`; model/DuckDB fixtures belong to TASK-4467 (`tests/_models.py`) so this conftest is never touched again.

### FILL IN checklist
- [ ] README AGPL paragraph — network clause explained; bounded by AC16 and spec §8 Q1.
- [ ] ci.yml job setup steps copied from `test-tool-optimizations` — bounded by AC16.
- [ ] Makefile version variable — only if the Makefile enumerates satellites.
- [ ] conftest `pctx_factory` / `deny_table_guard` bodies — bounded by the verified dataclass fields.
- [ ] `test_packaging.py` bodies (see Test Specification).

---

## Acceptance Criteria

- [ ] `import parrot.semantic; parrot.semantic.__version__ == "1.3.0"` with the satellite on PYTHONPATH (AC1).
- [ ] `packages/ai-parrot-semantic/src/parrot/__init__.py` does not exist.
- [ ] `ruff check` reports TID251 for `import sidemantic` in a file under `packages/ai-parrot/src`, not under the satellite (AC1).
- [ ] `scripts/release.py status` (or equivalent listing) shows `ai-parrot-semantic` (AC17).
- [ ] README contains the AGPL-3.0 network-clause notice and the sign-off line (AC16).
- [ ] `uv.lock` contains `ai-parrot-semantic`; nothing was `uv sync`-ed in the worktree.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_packaging.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_packaging.py
import subprocess
from pathlib import Path

import parrot.semantic

REPO = Path(__file__).resolve().parents[3]


def test_packaging_namespace():
    """parrot.semantic imports alongside core; src/parrot has no __init__.py; version matches."""
    assert parrot.semantic.__version__ == "1.3.0"
    assert not (REPO / "packages/ai-parrot-semantic/src/parrot/__init__.py").exists()


def test_sidemantic_import_ban(tmp_path):
    """TID251 flags `import sidemantic` outside the satellite only."""
    # FILL IN: write `import sidemantic\n` into a temp file placed under packages/ai-parrot/src/parrot/
    # (and remove it in a finally) and under packages/ai-parrot-semantic/src/parrot/semantic/;
    # run ["ruff", "check", "--select", "TID251", <file>] with cwd=REPO; assert rc!=0 / rc==0
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4463 — ai-parrot-semantic distribution skeleton (M1)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4463 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 5.5), attempt 3 (orchestrator) after both codex seats (gpt-5.6-terra, gpt-5.6-sol) returned empty_delivery with 0 turns
**Date**: 2026-10-19
**Commit**: dcec17c959f6ea901a8bc3fe341803cfbb2de3c4
**Notes**: Satellite skeleton, workspace source, release.py entry, TID251 sidemantic ban + satellite per-file ignore, test-semantic CI job, uv.lock (adds sidemantic 0.12.0 + antlr4 runtime; `uv lock` also refreshed navrules 1.2.2→1.2.3 lock drift). test_packaging.py: 2 passed; ruff clean; `scripts/release.py status` lists ai-parrot-semantic 1.3.0.
**OPERATOR ACTION REQUIRED**: from the main checkout run `source .venv/bin/activate && uv pip install -e packages/ai-parrot-semantic[duckdb]` — sidemantic is not in the shared venv and worktree agents must not install it.
**Deviations from spec**: the Makefile DOES enumerate satellite `*_VERSION_FILE` variables, but Makefile is not in this task's file list, so no `SEMANTIC_VERSION_FILE` was added (file fidelity). Follow-up needed if the Makefile release targets must cover the semantic package.

# TASK-4463: MIT satellite packaging, workspace and CI (M1)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M1; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Create the PEP 420 satellite with MIT metadata, sqlglot>=30.1,<31, jsonschema>=4.20, pyyaml>=6 and ai-parrot; extras duckdb>=1.0 and google-cloud-bigquery>=3.30. No sidemantic dependency, code reference or import exemption.
- Register workspace source, release package and CI; regenerate uv.lock with uv lock, never copy a salvage lockfile. Include schema/SQL package data. No dependency install into a shared worktree environment.
- Ban sidemantic imports everywhere through TID251 with no per-file exemption. CI explicitly installs the duckdb extra and runs the satellite tests; source repair tests are owned separately.
- Create lightweight tests/conftest.py with path setup only, no imports of future feature modules. Empty package test marker and namespace/version tests must work before downstream tasks land.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/pyproject.toml` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/README.md` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/version.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/__init__.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/conftest.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_packaging.py` | CREATE | Focused regression evidence |
| `pyproject.toml` | MODIFY | Scoped deliverable per blueprint |
| `uv.lock` | MODIFY | Scoped deliverable per blueprint |
| `scripts/release.py` | MODIFY | Scoped deliverable per blueprint |
| `ruff.toml` | MODIFY | Scoped deliverable per blueprint |
| `.github/workflows/ci.yml` | MODIFY | Scoped deliverable per blueprint |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .version import __version__
from pathlib import Path
import pytest
import sys
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

```python
# scripts/release.py:62
class Package():
```

### Dependency Contracts and Parallelism Evidence

- exclusive: workspace dependency manifest/uv.lock resolution and shared conftest.py setup

### Does NOT Exist

- `parrot.semantic` on dev — the package and symbols are created by this graph, never imported from the salvage branch environment.
- A semantic engine selector, sidemantic adapter or sidemantic parity oracle — native SQL generation is the only path.
- `PermissionContext.session_id` or `.agent_id` — the satellite identity contract carries trusted scope; request_id is not a session id.
- Automatic semantic authorization in `DatasetManager.add_dataframe()` — retained snapshots require the guarded host-sink contract.

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
    "sym:scripts/release.py#Package"
  ]
}
```

## Implementation Notes

- Keep the scope and signatures fixed by spec rev 0.4. Complete the bounded blueprint gaps, not a broad refactor. Preserve the clean-room rule: do not open sidemantic source/API glue.
- Use async I/O, Pydantic v2, strict types and Google-style docstrings. CPU SQL passes run off the event loop. Use logging, not print; black/ruff are the format/lint gates.
- Run in the feature worktree with the existing venv activated; never repair the shared environment. Write test logs to `artifacts/logs/`.
- The full-file snippets below are starting points. Recheck dependency-created MODIFY anchors after their tasks land; they cannot be falsely reported verified on dev today.

## Implementation Blueprint

### Steps (in order)

1. Verify existing anchors and dependency contracts — because stale signatures invalidate a mechanical implementation.
2. Implement the listed targets in their blueprint order — because each target has one explicit owner and the graph orders shared writers.
3. Complete all scope-specific validation branches and regression scenarios — because success-path-only tests cannot establish the required fail-closed behavior.
4. Run this task's validation commands and focused lint — because only evidence from its declared files closes this task.

### `packages/ai-parrot-semantic/pyproject.toml` (CREATE)

```toml
[build-system]
requires = ["setuptools>=77.0.0", "wheel>=0.44.0"]
build-backend = "setuptools.build_meta"
[project]
name = "ai-parrot-semantic"
dynamic = ["version"]
description = "Governed semantic metric queries for AI-Parrot"
readme = "README.md"
requires-python = ">=3.11,<3.14"
license = "MIT"
dependencies = ["ai-parrot", "sqlglot>=30.1,<31", "jsonschema>=4.20", "pyyaml>=6"]
[project.optional-dependencies]
duckdb = ["duckdb>=1.0"]
bigquery = ["google-cloud-bigquery>=3.30"]
[tool.setuptools.dynamic]
version = {attr = "parrot.semantic.version.__version__"}
[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
[tool.setuptools.package-data]
"parrot.semantic" = ["schemas/*.json", "sql/*.sql"]
[tool.uv.sources]
ai-parrot = {workspace = true}
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/README.md` (CREATE)

```markdown
# ai-parrot-semantic

MIT satellite: native sqlglot compilation and ai-parrot governance.
Install: `uv pip install 'ai-parrot-semantic[duckdb]'`.

## Layering
Generic semantic queries and the future accounting extension share this namespace.
The accounting extension must remain independently importable.

## Governance
<!-- FILL IN: document governed defaults, host PBAC factory, opt-in guarded sink,
     current compiler subset, extras and docs link; bounded by AC1/AC16. -->
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` (CREATE)

```python
"""Governed semantic queries using the native sqlglot compiler."""
from .version import __version__
__all__ = ["__version__"]
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/version.py` (CREATE)

```python
"""Semantic layer distribution version."""
__version__ = "1.3.0"
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/__init__.py` (CREATE)

```python
"""Semantic-layer tests."""
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/conftest.py` (CREATE)

```python
"""Lightweight namespace setup; feature fixtures are imported by their consumers."""
from pathlib import Path
import sys
# FILL IN: add satellite/core source roots if needed using Path(__file__).parents;
# do not import future parrot.semantic modules or install dependencies (M1 isolation).
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_packaging.py` (CREATE)

```python
"""Regression contract: MIT satellite packaging, workspace and CI (M1)."""
from pathlib import Path
import pytest


def test_namespace_version_and_package_data(tmp_path: Path) -> None:
    """Verify namespace version and package data."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_no_removed_dependency_or_import_exemption(tmp_path: Path) -> None:
    """Verify no removed dependency or import exemption."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_workspace_ci_duckdb_extra(tmp_path: Path) -> None:
    """Verify workspace ci duckdb extra."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `pyproject.toml` (MODIFY)

Anchor `ai-parrot-openlit-bridge = { workspace = true }` — occurrences: **1**, freshly verified at `pyproject.toml:244`.

```toml
# occurrences: 1 (verified: grep -c -F 'ai-parrot-openlit-bridge = { workspace = true }' pyproject.toml)
# AFTER — insert below `ai-parrot-openlit-bridge = { workspace = true }` (verified: pyproject.toml:239)
ai-parrot-semantic = { workspace = true }
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `uv.lock` (MODIFY)

Generated-file anchor `version = 1` — occurrences: **1**, verified at `uv.lock:1`; regenerate using uv lock, never patch records manually.

```text
# GENERATED: refresh with `uv lock` after the workspace manifest edits.
# Do not hand-edit resolution records or copy the salvage lockfile.
# FILL IN: verify only expected new satellite/resolution records and no sidemantic.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `scripts/release.py` (MODIFY)

Anchor `PACKAGES: list[Package] = [` — occurrences: **1**, freshly verified at `scripts/release.py:116`.

```python
# occurrences: 1 (verified: grep -c -F 'PACKAGES: list[Package] = [' scripts/release.py)
# Append as the LAST entry inside the PACKAGES list that starts at scripts/release.py:116
    Package("ai-parrot-semantic",
            [("packages/ai-parrot-semantic/src/parrot/semantic/version.py", "python")],
            "packages/ai-parrot-semantic", aliases=["semantic"]),
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `ruff.toml` (MODIFY)

Anchor `[lint.flake8-tidy-imports.banned-api]` — occurrences: **1**, freshly verified at `ruff.toml:125`.

```toml
# AFTER verified banned-api table anchor (count below).
"sidemantic".msg = "Removed dependency: do not import sidemantic anywhere."
# FILL IN: verify no per-file ignore can exempt this import; AC1/AC22.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `.github/workflows/ci.yml` (MODIFY)

Anchor `        run: uv run pytest packages/ai-parrot-tools/tests/tool_optimizations -q --tb=short` — occurrences: **1**, freshly verified at `.github/workflows/ci.yml:531`.

```yaml
# AFTER verified tool_optimizations test step; keep existing job indentation.
      - name: Semantic-layer tests
        run: |
          uv sync --all-packages --extra duckdb --package ai-parrot-semantic
          uv run pytest packages/ai-parrot-semantic/tests -q --tb=short
# FILL IN: confirm uv workspace extra syntax against existing CI conventions;
# the committed CI must install DuckDB explicitly and run the real source oracle.
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/pyproject.toml` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/README.md` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/version.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/__init__.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/conftest.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_packaging.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `pyproject.toml` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `uv.lock` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `scripts/release.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `ruff.toml` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `.github/workflows/ci.yml` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Create the PEP 420 satellite with MIT metadata, sqlglot>=30.1,<31, jsonschema>=4.20, pyyaml>=6 and ai-parrot; extras duckdb>=1.0 and google-cloud-bigquery>=3.30. No sidemantic dependency, code reference or import exemption.
- [ ] Register workspace source, release package and CI; regenerate uv.lock with uv lock, never copy a salvage lockfile. Include schema/SQL package data. No dependency install into a shared worktree environment.
- [ ] Ban sidemantic imports everywhere through TID251 with no per-file exemption. CI explicitly installs the duckdb extra and runs the satellite tests; source repair tests are owned separately.
- [ ] Create lightweight tests/conftest.py with path setup only, no imports of future feature modules. Empty package test marker and namespace/version tests must work before downstream tasks land.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_packaging.py -q`

## Test Specification

- `test_namespace_version_and_package_data`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_no_removed_dependency_or_import_exemption`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_workspace_ci_duckdb_extra`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4463` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.

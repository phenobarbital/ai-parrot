# TASK-4466: Vendored Ossie 0.1.1 validation (M4 import boundary)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4464
**Assigned-to**: unassigned
**Spec revision**: 0.4

## Context

Spec rev 0.4, §3 M4; replaces the prior task text for this same reserved identity. The unmerged branch is a salvage reference only; no completion state is inherited.

## Scope

- Vendor the official Ossie 0.1.1 JSON Schema with provenance; consult original format documentation only, never sidemantic source or its importer.
- Implement is_ossie_document and validate_ossie_document; fail with first error path on invalid/version-mismatched documents. Valid fixture demonstrates physical columns and measure input needed by the loader.
- Keep validation separate from lowering; typed graph construction belongs to the loader. Package data inclusion is provided by the skeleton task.

**NOT in scope**: changes outside the target table; provider SDK calls; a third-party semantic engine; symmetric aggregates; reviving the removed M12 core RLS work. Blueprint gaps are planning instructions only and must not survive in implementation files.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/fixtures/ossie/orders.ossie.json` | CREATE | Scoped deliverable per blueprint |
| `packages/ai-parrot-semantic/tests/test_ossie.py` | CREATE | Focused regression evidence |

## Codebase Contract (Anti-Hallucination)

Verified against main-checkout `dev` at `c431642e2` on 2026-10-25. Existing source definitions below were re-read. Satellite imports are **planned contracts**, not claims that those files already exist on dev; their producer tasks must land first.

### Verified Imports

```python
from .errors import SemanticPolicyError
from __future__ import annotations
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any
import json
import jsonschema
import pytest
```

Standard-library imports are built in; pydantic v2, sqlglot, PyYAML/jsonschema and pytest are governed by existing metadata and M1's explicit dependency/extra declarations. Reverify optional backend imports in the implementation environment. Relative satellite imports below resolve within the target package and are bounded by the listed dependency contracts.

### Existing Signatures to Use

No existing project symbol is extended; consume only dependency-created satellite contracts and the installed libraries below.

### Dependency Contracts and Parallelism Evidence

- TASK-4464: consumes packages/ai-parrot-semantic/src/parrot/semantic/errors.py, packages/ai-parrot-semantic/src/parrot/semantic/models.py (Query/result contracts and trusted identity model (M2))

- Consumer-specific evidence: SemanticPolicyError from errors.py

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
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/ossie.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/fixtures/ossie/orders.ossie.json",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_ossie.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
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

### `packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json` (CREATE)

```json
{"$comment": "FILL IN: vendor the complete official Ossie 0.1.1 JSON Schema; preserve its declared draft, version and provenance. No generated substitute schema."}
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py` (CREATE)

```python
"""Apache Ossie 0.1.1 detection and validation against the vendored JSON Schema."""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

import jsonschema

from .errors import SemanticPolicyError

OSSIE_SPEC_VERSION = "0.1.1"


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    return json.loads(files("parrot.semantic").joinpath("schemas/ossie-0.1.1.schema.json").read_text())


def is_ossie_document(doc: dict) -> bool:
    """True when `doc` declares itself an Apache Ossie document (any version)."""
    # FILL IN: check the version/kind marker field the schema requires — bounded by the vendored schema
    raise NotImplementedError


def validate_ossie_document(doc: dict) -> None:
    """Validate against the vendored 0.1.1 schema.

    Raises:
        SemanticPolicyError: code "ossie_version" for a version other than 0.1.1 (never coerced);
            code "ossie_invalid" with details["path"] = the first error's JSON path otherwise.
    """
    # FILL IN: version check first; then jsonschema.Draft202012Validator (or the draft the schema's
    #          "$schema" names) -> sorted(iter_errors) by path; raise on the first
    raise NotImplementedError
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/fixtures/ossie/orders.ossie.json` (CREATE)

```json
{"$comment": "FILL IN: a valid official Ossie 0.1.1 orders fixture with physical columns and measure inputs; verify using the vendored schema, never a sidemantic importer."}
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### `packages/ai-parrot-semantic/tests/test_ossie.py` (CREATE)

```python
"""Regression contract: Vendored Ossie 0.1.1 validation (M4 import boundary)."""
from pathlib import Path
import pytest


def test_official_fixture_and_version(tmp_path: Path) -> None:
    """Verify official fixture and version."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...


def test_invalid_document_reports_path(tmp_path: Path) -> None:
    """Verify invalid document reports path."""
    # FILL IN: arrange isolated inputs, exercise public behavior, assert the exact
    # result/denial and side effects required by this task scope and spec ACs.
    # For async paths use pytest.mark.asyncio and async def; never nest asyncio.run.
    ...
```

**Why**: this file implements the scoped responsibility above; preserve its public contract and complete its marked decisions under the task acceptance criteria.

### FILL IN checklist

- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/schemas/ossie-0.1.1.schema.json` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/fixtures/ossie/orders.ossie.json` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.
- [ ] `packages/ai-parrot-semantic/tests/test_ossie.py` — complete the bounded behavior, validation and error paths in its blueprint; no unfinished placeholders in the implementation.

## Acceptance Criteria

- [ ] Vendor the official Ossie 0.1.1 JSON Schema with provenance; consult original format documentation only, never sidemantic source or its importer.
- [ ] Implement is_ossie_document and validate_ossie_document; fail with first error path on invalid/version-mismatched documents. Valid fixture demonstrates physical columns and measure input needed by the loader.
- [ ] Keep validation separate from lowering; typed graph construction belongs to the loader. Package data inclusion is provided by the skeleton task.
- [ ] The task-specific regression cases below pass; focused black/ruff checks pass on changed code. No unrelated target is modified.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_ossie.py -q`

## Test Specification

- `test_official_fixture_and_version`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.
- `test_invalid_document_reports_path`: assert the observable behavior and denial/cleanup effects described in Scope; use deterministic isolated fixtures.

## Agent Instructions

Use `$sdd-start TASK-4466` in the feature worktree; it provisions isolation. Read spec/dependencies, reverify contracts, implement only declared targets, run validation and commit code. Use `scripts.sdd.finalize_task` with real TaskCompletionEvidence and the exact implementation HEAD; do not use close_task.sh or manually move/stamp completion artifacts.

## Completion Note

Populated only by the authorized completion workflow with implementation/validation evidence. Task planning is not completion.

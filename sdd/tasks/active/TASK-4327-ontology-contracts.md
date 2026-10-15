# TASK-4327: ontology/contracts.py, query-dialect validators, new exceptions

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 ontology contracts + §3 M8 + §8 Q2. Define `GraphDocumentStore`, `OntologyTraversalStore`, `DynamicQuery`, the ontology backend registry, dialect-dispatching `validate_query`, and register the existing AQL validator as the reference.

---

## Scope

- Create `ontology/contracts.py` per spec §2 (ABCs, `DynamicQuery`, `register_ontology_backend`, `create_ontology_graph_store` with lazy built-in `arangodb`).
- `exceptions.py`: `QueryValidationError(OntologyError)`, `AQLValidationError` now subclasses it, `QueryDialectMismatch`, `TraversalPatternUnavailable`.
- `validators.py`: `register_query_validator`, `validate_query(dialect, text, max_depth=None)`; register `validate_aql` for `"aql"`.
- Tests.

**NOT in scope**: Arango implementation (TASK-4328).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py` | CREATE | contracts + registry |
| `packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py` | MODIFY | exceptions |
| `packages/ai-parrot/src/parrot/knowledge/ontology/validators.py` | MODIFY | dispatch |
| `packages/ai-parrot/tests/knowledge/ontology/test_contracts.py` | CREATE | contract tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.ontology.schema import TenantContext, TraversalPattern  # schema.py:529, :261
from .exceptions import AQLValidationError  # validators.py:10
```

### Existing Signatures to Use
```python
# exceptions.py: OntologyError :4; AQLValidationError(OntologyError) :27
# validators.py: async def validate_aql(aql, max_depth=None) -> str :36
# graph_store.py signatures (for GraphDocumentStore): initialize_tenant :91, ensure_collection :570, upsert_nodes :311, create_edges :411, get_all_nodes :488,
#   soft_delete_nodes :517, get_document :598, upsert_document :622, insert_document :650, remove_document :669, query_documents :697, get_all_edges :738,
#   edges_incident :764, remove_edge_by_triple :791
```

### Does NOT Exist
- ~~`parrot.knowledge.ontology.contracts` (created here)~~
- ~~`validate_query` / `register_query_validator` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/validators.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/ontology/test_contracts.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/validators.py#validate_aql",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py#AQLValidationError"
  ]
}
```

---

## Implementation Notes

Contracts are ABCs (intra-package, spec §7). Keep `validate_aql` behaviour and its tests unchanged.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Exceptions.
2. Validators dispatch + AQL registration — *why*: Q2 reference validator.
3. Contracts module.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py` (CREATE)
```python
"""Backend-neutral ontology graph-store contracts (FEAT-540 M8)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Callable, ClassVar

from pydantic import BaseModel, Field

from parrot.knowledge.ontology.schema import TenantContext, TraversalPattern


class DynamicQuery(BaseModel):
    """A dialect-bound query text with its bind parameters."""

    dialect: str
    text: str
    bind_vars: dict[str, Any] = Field(default_factory=dict)
    collection_binds: dict[str, str] = Field(default_factory=dict)


# FILL IN: GraphDocumentStore(ABC) — abstract methods with the exact graph_store.py signatures;
#          OntologyTraversalStore(ABC) — dialect ClassVar + is_reachable/get_document_by_id/find_by_field/search_by_name/execute_pattern/execute_query (spec §2);
#          register_ontology_backend / create_ontology_graph_store (built-in 'arangodb' -> parrot.knowledge.ontology.graph_store:ArangoOntologyGraphStore, lazy)
```
**Why**: Spec §2 verbatim.

### `packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class AQLValidationError(OntologyError):' parrot/knowledge/ontology/exceptions.py)
# AFTER/AT — anchor `class AQLValidationError(OntologyError):` (verified: exceptions.py:27)
# INSERT ABOVE:
class QueryValidationError(OntologyError):
    """Dynamic query rejected (no validator for its dialect, or unsafe)."""


# CHANGE the base of AQLValidationError to QueryValidationError; APPEND QueryDialectMismatch(OntologyError), TraversalPatternUnavailable(OntologyError)
```
**Why**: AQL errors stay catchable as before.

### `packages/ai-parrot/src/parrot/knowledge/ontology/validators.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def validate_aql(' parrot/knowledge/ontology/validators.py)
# AFTER/AT — anchor `async def validate_aql(` (verified: validators.py:36)
# APPEND after validate_aql:
# _VALIDATORS: dict[str, Callable] = {}
# def register_query_validator(dialect, validator) -> None
# async def validate_query(dialect, text, max_depth=None) -> str  — QueryValidationError when unregistered
# register_query_validator("aql", validate_aql)
```
**Why**: Q2: AQL is the reference validator.

### `packages/ai-parrot/tests/knowledge/ontology/test_contracts.py` (CREATE)
```python
"""Ontology contracts + validator dispatch (FEAT-540 M8)."""
import pytest

from parrot.knowledge.ontology.exceptions import QueryValidationError
from parrot.knowledge.ontology.validators import validate_query


@pytest.mark.asyncio
async def test_unregistered_dialect_fails_closed() -> None:
    with pytest.raises(QueryValidationError):
        await validate_query("cypher", "MATCH (n) RETURN n")


@pytest.mark.asyncio
async def test_aql_dispatch() -> None:
    assert await validate_query("aql", "FOR d IN c RETURN d") == "FOR d IN c RETURN d"

# FILL IN: AQL mutation via validate_query raises AQLValidationError (still a QueryValidationError); registry unknown name
```
**Why**: Spec §4.

### FILL IN checklist
- [ ] ABCs
- [ ] registry
- [ ] validator dispatch
- [ ] tests

---

## Acceptance Criteria

- [ ] contracts importable; AQL validator registered
- [ ] existing `test_ontology_validators.py` passes unchanged

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/test_contracts.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_validators.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4327 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: ontology/contracts.py, new exceptions and query-dialect validators + test_contracts.py; no review corrections. Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings show no failure absent from the clean origin/dev baseline.

**Deviations from spec**: none

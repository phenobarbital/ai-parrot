# TASK-5443: Extract shared crew definition codec

**Feature**: FEAT-860 — Postgres CrewDefinition Storage
**Spec**: `sdd/specs/postgres-crew-storage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement the approved revision 0.2 contracts for extract shared crew definition codec.
Spec §§2–5 are authoritative; §6 records baseline source, not old error-policy requirements.
This task is part of the four review resolutions recorded in spec §9.

## Scope

- Move read-side transformation into the codec without changing logic — legacy payload acceptance is a compatibility boundary.
- Delegate Redis helpers and add codec tests — both stores must share exactly one transformation.

**NOT in scope**: files outside the table; changing CrewDefinition model fields, execution-result storage,
creation.sql, _load_database_bots, dependency manifests or introducing new services.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/definition_codec.py` | CREATE | Both backends must deserialize historical documents identically. |
| `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` | MODIFY | Thin delegates preserve callers and legacy payload tests. |
| `packages/ai-parrot-server/tests/unit/test_crew_definition_codec.py` | CREATE | Exercise unknown root/nested keys, invalid relations, timestamp parsing and exact round trips. |

## Codebase Contract (Anti-Hallucination)

Verified at `0cfa595cb2` on `dev`; re-check after dependencies land.

### Verified Imports

```python
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
import logging
from datetime import datetime
from typing import Any
import pytest
```

Standard-library imports resolve under the project Python runtime; pytest/Pydantic/asyncdb are already declared in workspace pyproject.toml files. Crew model re-exports are verified in handlers/crew/models.py:17–23. Relative imports of new modules in blueprints are dependency contracts below, not claims of pre-existing code.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition` — `class CrewDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:178).
- `sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition` — `class AgentDefinition(BaseModel):` (packages/ai-parrot/src/parrot/models/crew_definition.py:31).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis._strip_unknown_keys` — `def _strip_unknown_keys(self, crew_dict: dict, crew_id: str) -> dict:` (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:125).
- `sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis._deserialize_crew` — `def _deserialize_crew(self, data: str) -> CrewDefinition:` (packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:180).

### Dependency Imports and New Symbols

Independent codec extraction; owns redis_persistence.py before TASK-5445 extends it.

Exact blueprint imports (stdlib/existing references above; new symbols require the named prerequisite):

```python
from .definition_codec import strip_unknown_keys, crew_definition_from_dict
from .models import AgentDefinition, CrewDefinition, FlowRelation, ToolNodeDefinition
from __future__ import annotations
from datetime import datetime
from parrot.handlers.crew.definition_codec import crew_definition_from_dict, crew_definition_to_document, strip_unknown_keys
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition
from typing import Any
import logging
import pytest
```
Blueprint imports from `definition_codec`, `postgres_persistence`, `definition_storage`, and new Redis types are permitted only after their producer task completes; inspect those exact declarations before implementation. New symbols defined by this task are declared in its blueprint.

### Does NOT Exist

- definition_codec.py does not exist before this task.
- There is no AbstractCrewStorage to inherit.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/definition_codec.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/unit/test_crew_definition_codec.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis._strip_unknown_keys",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py#CrewRedis._deserialize_crew"
  ]
}
```

## Implementation Notes

Use async I/O, Pydantic v2 models, strict type hints and Google-style docstrings. Format with black (120 columns); lint with ruff. No new dependencies. Logs belong under artifacts/logs/.

## Implementation Blueprint

### Steps (in order)

1. Move read-side transformation into the codec without changing logic — legacy payload acceptance is a compatibility boundary.
2. Delegate Redis helpers and add codec tests — both stores must share exactly one transformation.

### `packages/ai-parrot-server/src/parrot/handlers/crew/definition_codec.py` (CREATE)

```python
"""Shared compatibility codec for stored crew definitions."""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Any
from .models import AgentDefinition, CrewDefinition, FlowRelation, ToolNodeDefinition

def strip_unknown_keys(crew_dict: dict[str, Any], crew_id: str, logger: logging.Logger) -> dict[str, Any]:
    """Copy declared root/nested fields and preserve existing drift warnings."""
    # FILL IN: transplant existing recursive pruning exactly; AC1.
    raise NotImplementedError

def crew_definition_from_dict(crew_dict: dict[str, Any], logger: logging.Logger) -> CrewDefinition:
    """Parse ISO timestamps, strip unknown keys, and validate the stored document."""
    # FILL IN: preserve the Redis read compatibility contract; AC1/AC2.
    raise NotImplementedError

def crew_definition_to_document(crew: CrewDefinition) -> dict[str, Any]:
    """Return the JSON-compatible definition without double encoding."""
    return crew.model_dump(mode="json")
```

**Why**: Both backends must deserialize historical documents identically.

### `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` (MODIFY)

```python
# Anchor:     def _strip_unknown_keys(self, crew_dict: dict, crew_id: str) -> dict:
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:125 at 0cfa595cb2
# Anchor:     def _deserialize_crew(self, data: str) -> CrewDefinition:
# occurrences: 1; verified packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py:180 at 0cfa595cb2
# Add codec imports beside .models; keep json.loads and existing exception logging.
from .definition_codec import strip_unknown_keys, crew_definition_from_dict
# Replace only helper bodies; preserve signatures and unrelated Redis methods.
# FILL IN: _strip_unknown_keys delegates with self.logger; _deserialize_crew
# calls crew_definition_from_dict(json.loads(data), self.logger) within existing error handling.
```

**Why**: Thin delegates preserve callers and legacy payload tests.

### `packages/ai-parrot-server/tests/unit/test_crew_definition_codec.py` (CREATE)

```python
"""FEAT-860 regression tests; use isolated fakes unless explicitly live."""
from __future__ import annotations
import pytest
from parrot.handlers.crew.definition_codec import crew_definition_from_dict, crew_definition_to_document, strip_unknown_keys
from parrot.handlers.crew.models import CrewDefinition, AgentDefinition, FlowRelation, ToolNodeDefinition

def test_nested_unknown_fields_and_warning() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError

def test_iso_timestamps_and_round_trip() -> None:
    """Assert the state transition specified in this task, including failures."""
    # FILL IN: arrange fixtures and assert outcomes per AC and Test Specification.
    raise NotImplementedError
```

**Why**: Exercise unknown root/nested keys, invalid relations, timestamp parsing and exact round trips.

### FILL IN checklist

- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/definition_codec.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] `packages/ai-parrot-server/tests/unit/test_crew_definition_codec.py` — complete the bounded logic described above; satisfy all task acceptance criteria and retain unrelated content.
- [ ] Replace all blueprint gaps with complete working code/tests; no placeholders in implementation files.

## Acceptance Criteria

- [ ] AC1: Redis compatibility helpers retain existing signatures, dropped-field warning text and error behavior.
- [ ] AC2: Codec handles ISO strings and complete model round trips; invalid model data still raises.
- [ ] AC3: Existing legacy-payload tests pass unchanged; no Redis network access in unit tests.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_crew_definition_codec.py -q`

## Test Specification

Each test block above is an executor starting point, not an implementation. Build fixtures locally in the declared test files; do not modify shared conftest.py. Assert observable state and error behavior from every acceptance criterion. Avoid network/LLM calls except the explicitly gated live tests in TASK-5451.

## Agent Instructions

Implement in the feature worktree provisioned by sdd-start, never on dev. Check the dependency states
in `sdd/tasks/index/postgres-crew-storage.json` first. Verify source anchors and dependency-created APIs before editing.
Complete only declared files, run narrow validation commands, and commit scoped code. Finalize with
`parrot sdd task finalize` and real TaskCompletionEvidence for the implementation HEAD; do not manually
move the task, stamp completion, or run legacy task-close helpers.

## Completion Note

Pending; populated by the task finalizer after implementation and validation.

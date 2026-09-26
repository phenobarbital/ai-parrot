# TASK-3771: JSON Schema export + committed contract/schema.json

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3769
**Assigned-to**: unassigned

---

## Context

G1: ai-parrot publishes the descriptor/DSL **JSON Schema** plus golden fixtures; every renderer
implements its own executor against them. This task adds `export_json_schema()` and commits the
generated `linked/contract/schema.json` as installable package data (S7). The bundled UI (TASK-3792)
copies it into `ui/schemas/` for `pnpm generate`. Spec §3 Module 1 (schema part), AC7.

---

## Scope

- Create `linked/schema.py` with `export_json_schema() -> dict` and `write_json_schema(path=None) -> Path`,
  plus a `python -m parrot.outputs.a2ui.linked.schema` entry point that (re)writes the file.
- Generate and commit `linked/contract/schema.json`.
- Tests: determinism, committed file is byte-equal to a fresh export, a valid descriptor validates
  and an invalid one does not (via `jsonschema`).

**NOT in scope**: the UI copy / TS generation (TASK-3792); package-data configuration (TASK-3772).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/schema.py` | CREATE | schema export + writer |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/schema.json` | CREATE | generated, committed |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_schema.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.linked.models import LinkedSources   # created by TASK-3769 (RootModel[dict[str, LinkedDataSource]])
import jsonschema                                              # installed 4.26.0 (existing dependency, spec §7 External Dependencies)
```

### Existing Signatures to Use
```python
# pydantic v2: BaseModel/RootModel.model_json_schema(by_alias=True, mode="validation") -> dict
# TASK-3769: Join.with_ has alias "with" → by_alias=True is mandatory so the wire name appears in the schema.
```

### Does NOT Exist
- ~~`docs/outputs/schemas/linked*.json`~~ — spec §4's `test_json_schema_export_deterministic` row mentions a docs path; the binding location is `linked/contract/schema.json` (M1 skeleton, S7). Do NOT create a docs copy.
- ~~`parrot.outputs.a2ui.linked.schema`~~ — this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/schema.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/schema.json", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_schema.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Draft: `"$schema": "https://json-schema.org/draft/2020-12/schema"` (pydantic v2 emits 2020-12-compatible `$defs`).
- Add `"$id": "https://ai-parrot.dev/schemas/a2ui/linked-sources.v1.json"` and `"title": "LinkedSources"` — a stable identifier renderers can reference; it is an identifier, not a fetch URL.
- Determinism: serialise with `json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False) + "\n"`. The dict returned by `export_json_schema()` is the same object before serialisation.
- `mode="validation"` (renderers validate incoming wire); `by_alias=True`.
- Location of the file: `Path(__file__).parent / "contract" / "schema.json"`.

---

## Implementation Blueprint

### Steps (in order)
1. Write `schema.py` — *why*: one generator for the committed file and the test.
2. Run `python -m parrot.outputs.a2ui.linked.schema` to write `contract/schema.json`; commit it — *why*: AC7 "contract/schema.json is committed and deterministic".
3. Write and run the tests.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/schema.py` (CREATE)
```python
"""JSON Schema of ``parrot_data_sources`` (FEAT-598 M1, S7) — the published renderer contract."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from parrot.outputs.a2ui.linked.models import LinkedSources

logger = logging.getLogger(__name__)

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://ai-parrot.dev/schemas/a2ui/linked-sources.v1.json"
SCHEMA_PATH = Path(__file__).parent / "contract" / "schema.json"


def export_json_schema() -> dict[str, Any]:
    """Return the JSON Schema (draft 2020-12) of ``LinkedSources``."""
    schema = LinkedSources.model_json_schema(by_alias=True, mode="validation")
    schema = {"$schema": SCHEMA_DRAFT, "$id": SCHEMA_ID, **schema, "title": "LinkedSources"}
    return schema


def dumps_schema(schema: dict[str, Any] | None = None) -> str:
    """Serialise the schema deterministically (sorted keys, 2-space indent, trailing newline)."""
    return json.dumps(schema or export_json_schema(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_json_schema(path: Path | None = None) -> Path:
    """Write the schema to ``path`` (default ``contract/schema.json``) and return the path."""
    target = path or SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps_schema(), encoding="utf-8")
    logger.info("linked-sources JSON Schema written to %s", target)
    return target


if __name__ == "__main__":
    write_json_schema()
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/schema.json` (CREATE)
Generated by step 2 — never hand-edited.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_schema.py` (CREATE)
```python
"""Tests for the published linked-sources JSON Schema (FEAT-598 M1)."""
from __future__ import annotations

import jsonschema
import pytest

from parrot.outputs.a2ui.linked.schema import SCHEMA_PATH, dumps_schema, export_json_schema


def test_json_schema_export_deterministic() -> None:
    assert dumps_schema(export_json_schema()) == dumps_schema(export_json_schema())


def test_committed_schema_matches_export() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == dumps_schema()


def test_schema_accepts_valid_descriptor(linked_source) -> None:
    # FILL IN: {"activity": linked_source.model_dump(mode="json", by_alias=True, exclude_none=True)} validates
    ...


def test_schema_rejects_invalid_descriptor(linked_source) -> None:
    # FILL IN: an unknown top-level key and a wrong `kind` each raise jsonschema.ValidationError
    ...
```

### FILL IN checklist
- [ ] valid/invalid descriptor tests; bounded by AC7 (schema is the renderer contract)

---

## Acceptance Criteria

- [ ] `contract/schema.json` committed, byte-equal to a fresh export (AC7).
- [ ] The schema carries `"with"` (not `"with_"`) for the join op and forbids additional properties.
- [ ] A descriptor produced by the models validates under `jsonschema.Draft202012Validator`.
- [ ] `ruff check` + `black --check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_linked_schema.py -q`

---

## Test Specification

```python
def test_json_schema_export_deterministic(): ...
def test_committed_schema_matches_export(): ...
def test_schema_accepts_valid_descriptor(linked_source): ...
def test_schema_rejects_invalid_descriptor(linked_source): ...
def test_schema_uses_with_alias(): ...     # '"with"' appears under the Join def; '"with_"' does not
```

---

## Agent Instructions

1. Read spec §3 Module 1 (`export_json_schema`), §9 S7.
2. Confirm TASK-3769 done. Index → `in-progress`.
3. Implement, regenerate the file, run Validation Commands (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
4. Move to `sdd/tasks/completed/`, index → `done`, Completion Note.

---

## Completion Note


- Task: TASK-3771
- Feature: a2ui-linked-surfaces
- Implementation SHA: 9546bced726f7cf8512a46a69fcf8425317119fd
- Closed at (UTC): 2026-09-26T00:27:54+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | completed: 25 passed (packages/ai-parrot/tests/outputs/a2ui/linked) |
| seat_summary | Seat: gpt-5.6-terra - Backend: codex - Model: gpt-5.6-terra - Attempts: 1 - Duration: 125.2s - Tokens: n/a |

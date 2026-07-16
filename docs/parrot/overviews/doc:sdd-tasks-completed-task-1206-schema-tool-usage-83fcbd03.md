---
type: Wiki Overview
title: 'TASK-1206: SCHEMA_TOOL_USAGE_LAYER prompt layer'
id: doc:sdd-tasks-completed-task-1206-schema-tool-usage-prompt-layer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After TASK-1204 ships, the LLM sees three tools (`db_search_schema`,
relates_to:
- concept: mod:parrot.bots.database.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
---

# TASK-1206: SCHEMA_TOOL_USAGE_LAYER prompt layer

**Feature**: FEAT-178 — Database Toolkit Cache Contract & Tool Semantics
**Spec**: `sdd/specs/database-toolkit-cache-contract.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1204
**Assigned-to**: unassigned

---

## Context

After TASK-1204 ships, the LLM sees three tools (`db_search_schema`,
`db_describe_table`, `db_generate_query`). Without explicit prompt
guidance, the model keeps misusing `db_search_schema` to search
*data values* ("alaska") instead of identifiers. The new prompt
layer documents the correct workflow.

Implements **Module 6** of the spec.

---

## Scope

- Add `SCHEMA_TOOL_USAGE_LAYER` in
  `packages/ai-parrot/src/parrot/bots/database/prompts.py`.
- The layer is **unconditional** (no `condition=`) — it always
  renders.
- Content must communicate:
  - Workflow: `db_search_schema` → `db_describe_table` →
    `db_generate_query` (or author SQL directly).
  - `db_search_schema` searches **identifiers** (table / column /
    comment names), **not data values**. For data filtering, use
    `db_describe_table` then SELECT with a WHERE clause.
  - Never reference a table whose columns have not been loaded
    via `db_describe_table`.
- Wire into `_build_database_prompt_builder()` (prompts.py:76).

Unit test: `test_schema_tool_usage_layer_renders` —
asserts the system prompt produced by `_build_database_prompt_builder()`
contains the workflow text unconditionally.

**NOT in scope**: agent-side configuration changes (already
covered by TASK-1202's `cache_ttl_by_completeness` wiring).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/prompts.py` | MODIFY | Add new layer + register it in the builder |
| `packages/ai-parrot/tests/bots/database/test_prompts.py` | CREATE or MODIFY | Test the layer renders |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.builder import PromptBuilder
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/prompts.py:15-86
DATABASE_CONTEXT_LAYER       # line 15
DATABASE_SAFETY_LAYER        # line 26
SCHEMA_GROUNDING_LAYER       # line 45 — conditional on schema_summary
DATABASE_INSTRUCTIONS_LAYER  # line 58
def _build_database_prompt_builder() -> PromptBuilder: ...   # line 76
```

### Does NOT Exist
- ~~`SCHEMA_TOOL_USAGE_LAYER`~~ — introduced here.

---

## Implementation Notes

### Layer shape
Follow the pattern of `DATABASE_INSTRUCTIONS_LAYER`. Approximate
structure (final wording up to the implementing agent; must cover
the three bullets above):

```python
SCHEMA_TOOL_USAGE_LAYER = PromptLayer(
    name="schema_tool_usage",
    priority=LayerPriority.HIGH,
    phase=RenderPhase.SYSTEM,
    content=(
        "## Schema discovery workflow\n"
        "1. `db_search_schema(term)` finds tables whose NAME, COLUMN NAME, "
        "or COMMENT matches `term`. It searches *identifiers, not data values*.\n"
        "   - `db_search_schema('alaska')` will not find rows where "
        "`state_code = 'AK'`. To filter by a value, find the table first, "
        "then describe it, then write SQL with a WHERE clause.\n"
        "2. `db_describe_table(schema, table)` returns the full column list, "
        "primary key, indexes, and foreign keys for a single table. Call this "
        "before generating SQL that references a table.\n"
        "3. `db_generate_query(natural_language, target_tables=...)` produces "
        "a SELECT skeleton grounded in the real columns of `target_tables`. "
        "Refine the WHERE / JOIN before executing.\n"
        "4. Never reference a column you have not seen in a `db_describe_table` "
        "result.\n"
    ),
)
```

### Builder wiring
In `_build_database_prompt_builder()` (prompts.py:76-85), add the
layer in the appropriate place. Match the existing `builder.add(...)`
call style — read the surrounding code to confirm the exact API.

---

## Acceptance Criteria

- [ ] `SCHEMA_TOOL_USAGE_LAYER` defined in `prompts.py`
- [ ] Layer is unconditional
- [ ] Layer mentions all three tools explicitly
- [ ] Layer states `db_search_schema` searches identifiers, not
      data values
- [ ] Layer warns against referencing tables / columns not
      surfaced by `db_describe_table`
- [ ] `_build_database_prompt_builder()` registers the layer
- [ ] `test_schema_tool_usage_layer_renders` passes

---

## Test Specification

```python
from parrot.bots.database.prompts import (
    SCHEMA_TOOL_USAGE_LAYER,
    _build_database_prompt_builder,
)


def test_layer_is_unconditional():
    assert SCHEMA_TOOL_USAGE_LAYER.condition is None or \
           SCHEMA_TOOL_USAGE_LAYER.condition(context={}) is True


def test_layer_mentions_all_three_tools():
    text = SCHEMA_TOOL_USAGE_LAYER.content
    assert "db_search_schema" in text
    assert "db_describe_table" in text
    assert "db_generate_query" in text


def test_layer_states_identifier_only():
    text = SCHEMA_TOOL_USAGE_LAYER.content.lower()
    assert "identifier" in text
    assert "data value" in text or "row" in text


def test_builder_registers_layer():
    builder = _build_database_prompt_builder()
    rendered = builder.render(context={})
    assert "Schema discovery workflow" in rendered
```

---

## Agent Instructions

1. Confirm TASK-1204 is in `sdd/tasks/completed/`.
2. Read `prompts.py` end-to-end to match the existing layer style.
3. Implement.
4. Run `pytest packages/ai-parrot/tests/bots/database/test_prompts.py -v`.
5. Move task file to `completed/` and update the per-spec index.
6. Fill in the Completion Note.

---

## Completion Note

Implemented on branch `feat-178-database-toolkit-cache-contract`.

- Added `SCHEMA_TOOL_USAGE_LAYER` in `prompts.py`: `phase=CONFIGURE`, `condition=None` (unconditional), `priority=LayerPriority.PRE_INSTRUCTIONS + 2`. Template documents the 3-step workflow (`db_search_schema` → `db_describe_table` → `db_generate_query`), explicitly states that `db_search_schema` searches identifiers not data values, and warns never to reference a column not seen in a `db_describe_table` result.
- Registered the new layer in `_build_database_prompt_builder()` between `DATABASE_INSTRUCTIONS_LAYER` and `SQL_DIALECT_LAYER`.
- Added 6 new tests to `test_database_prompts.py`; 9/9 total pass; ruff clean.

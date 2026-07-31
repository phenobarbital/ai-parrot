---
type: Wiki Overview
title: 'TASK-1126: Database PromptLayer Constants & Builder Factory'
id: doc:sdd-tasks-completed-task-1126-database-prompt-layers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of FEAT-164 (spec §3 "Module 2"). The current
relates_to:
- concept: mod:parrot.bots.database.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.domain_layers
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
---

# TASK-1126: Database PromptLayer Constants & Builder Factory

**Feature**: FEAT-164 — DatabaseAgent Homologation
**Spec**: `sdd/specs/database-agent-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-164 (spec §3 "Module 2"). The current
`bots/database/prompts.py` exports five legacy `string.Template`-style
constants (`DB_AGENT_PROMPT`, `BASIC_HUMAN_PROMPT`, `DATA_ANALYSIS_PROMPT`,
`DATABASE_EDUCATION_PROMPT`, `DATABASE_TROUBLESHOOTING_PROMPT`). They are
incompatible with the new `PromptBuilder` / `PromptLayer` machinery used
by `PandasAgent` (`bots/data.py:305–311`).

This task **rewrites** `prompts.py` to expose four `PromptLayer` constants
plus a `_build_database_prompt_builder()` factory function, mirroring the
PandasAgent pattern.

Open Question #1 resolution: DB-specific layers live in
`bots/database/prompts.py`, NOT in `prompts/domain_layers.py` and NOT in
a new module.

---

## Scope

- Replace the contents of `bots/database/prompts.py`. Delete the five
  legacy `$placeholder` constants entirely (no aliasing).
- Define four `PromptLayer` instances:
  - `DATABASE_CONTEXT_LAYER` — priority `KNOWLEDGE+5`, phase `REQUEST`.
  - `DATABASE_SAFETY_LAYER` — priority `SECURITY+5`, phase `CONFIGURE`.
  - `SCHEMA_GROUNDING_LAYER` — priority `KNOWLEDGE+10`, phase `REQUEST`.
  - `DATABASE_INSTRUCTIONS_LAYER` — priority `PRE_INSTRUCTIONS+1`,
    phase `CONFIGURE`.
- Define `_build_database_prompt_builder() -> PromptBuilder` that returns
  `PromptBuilder.default()` enriched with the four new layers plus
  `SQL_DIALECT_LAYER` and `STRICT_GROUNDING_LAYER`.
- Write unit tests for the factory and layer rendering.

**NOT in scope**:
- Wiring the builder onto `DatabaseAgent` (Module 5 / TASK-1128).
- Adding LLM-instruction text — the four layers' template bodies should
  carry the prompt content; this is part of this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/prompts.py` | REWRITE | Drop legacy constants; add four `PromptLayer`s + factory. |
| `packages/ai-parrot/tests/bots/database/test_database_prompts.py` | CREATE | Tests for factory composition and layer rendering. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Available — re-verify line numbers before using:
from parrot.bots.prompts.builder import PromptBuilder          # bots/prompts/builder.py:20
from parrot.bots.prompts.layers import (
    PromptLayer,          # bots/prompts/layers.py:51
    LayerPriority,        # bots/prompts/layers.py:22
    RenderPhase,          # bots/prompts/layers.py:35
)
from parrot.bots.prompts.domain_layers import (
    SQL_DIALECT_LAYER,        # bots/prompts/domain_layers.py:29
    STRICT_GROUNDING_LAYER,   # bots/prompts/domain_layers.py:67
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py:51
@dataclass(frozen=True)
class PromptLayer:
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase
    condition: Optional[Callable] = None
    required_vars: Optional[List[str]] = None

# LayerPriority(IntEnum)            # layers.py:22
#   IDENTITY=10  PRE_INSTRUCTIONS=15  SECURITY=20
#   KNOWLEDGE=30 USER_SESSION=40     TOOLS=50
#   OUTPUT=60    BEHAVIOR=70         CUSTOM=80

# RenderPhase(str, Enum)            # layers.py:35
#   CONFIGURE = "configure"         # line 46
#   REQUEST   = "request"           # line 47

# packages/ai-parrot/src/parrot/bots/prompts/builder.py:20
class PromptBuilder:
    @classmethod
    def default(cls) -> PromptBuilder: ...          # line 45 (re-verify)
    def add(self, layer: PromptLayer) -> PromptBuilder: ...
    def remove(self, name: str) -> PromptBuilder: ...
    def configure(self, context: Dict[str, Any]) -> None: ...
    def build(self, context: Dict[str, Any]) -> str: ...
```

### Reference Implementation

```python
# packages/ai-parrot/src/parrot/bots/data.py:305
def _build_pandas_prompt_builder() -> PromptBuilder:
    builder = PromptBuilder.default()
    builder.add(DATAFRAME_CONTEXT_LAYER)
    builder.add(STRICT_GROUNDING_LAYER)
    builder.add(PANDAS_INSTRUCTIONS_LAYER)
    return builder
```

### Does NOT Exist

- ~~`DATABASE_CONTEXT_LAYER`~~ — not defined anywhere; this task creates it.
- ~~`DATABASE_SAFETY_LAYER`~~ — not defined anywhere; this task creates it.
- ~~`SCHEMA_GROUNDING_LAYER`~~ — not defined anywhere; this task creates it.
- ~~`DATABASE_INSTRUCTIONS_LAYER`~~ — not defined anywhere; this task creates it.
- ~~`_build_database_prompt_builder`~~ — not defined anywhere; this task creates it.
- ~~`PromptLayer.required_vars` as a Pydantic field~~ — `PromptLayer` is a
  `@dataclass(frozen=True)`, not Pydantic.

---

## Implementation Notes

### Pattern to Follow

Read `packages/ai-parrot/src/parrot/bots/data.py:305–325` for the
PandasAgent equivalents (`DATAFRAME_CONTEXT_LAYER`,
`PANDAS_INSTRUCTIONS_LAYER`, `_build_pandas_prompt_builder`). Copy the
shape; adapt the template bodies for the database domain.

### Layer Template Bodies — content to author

Use the legacy `DB_AGENT_PROMPT` (current `prompts.py`) as raw material
but split its content across the four layer templates:

- `DATABASE_CONTEXT_LAYER` (REQUEST, priority `KNOWLEDGE+5`):
  Describes the user's request context, intent, and target database
  identifier. Has dynamic placeholders for `database`, `intent`,
  `output_components`.
- `DATABASE_SAFETY_LAYER` (CONFIGURE, priority `SECURITY+5`):
  Hard constraints (no DDL, read-only verbs only unless explicitly
  permitted, no destructive ops, parameter binding for any user-supplied
  value).
- `SCHEMA_GROUNDING_LAYER` (REQUEST, priority `KNOWLEDGE+10`):
  Schema reference block. Placeholder for dynamic
  `schema_summary` (table+column list rendered by the agent before build).
  Strongly directs the LLM to use ONLY the tables/columns listed.
- `DATABASE_INSTRUCTIONS_LAYER` (CONFIGURE, priority
  `PRE_INSTRUCTIONS+1`):
  Output-format expectations — LLM must return a `QueryResponse`
  (explanation + optional query + optional dataset), call tools only when
  required, prefer the schema-grounded query path.

### Priority Encoding

`LayerPriority` is an `IntEnum`; arithmetic is legal:
```python
priority=LayerPriority.KNOWLEDGE + 5     # → int 35
priority=LayerPriority.SECURITY + 5      # → int 25
priority=LayerPriority.PRE_INSTRUCTIONS + 1  # → int 16
```

### Key Constraints

- Layer `name` is the lookup key — use lowercase snake_case
  (`database_context`, `database_safety`, `schema_grounding`,
  `database_instructions`). Tests assert these exact names.
- `condition` is optional; default to `None` for unconditional layers.
- `required_vars` should list ONLY the placeholders the layer's template
  actually references — otherwise `builder.build()` will raise.
- Do not re-add `SQL_DIALECT_LAYER` / `STRICT_GROUNDING_LAYER` into the
  module — import them and add them to the builder inside the factory.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/data.py:305` — PandasAgent factory.
- `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py:29` —
  `SQL_DIALECT_LAYER` definition for shape reference.

---

## Acceptance Criteria

- [ ] `bots/database/prompts.py` no longer defines `DB_AGENT_PROMPT`,
      `BASIC_HUMAN_PROMPT`, `DATA_ANALYSIS_PROMPT`,
      `DATABASE_EDUCATION_PROMPT`, `DATABASE_TROUBLESHOOTING_PROMPT`.
- [ ] The four new `*_LAYER: PromptLayer` constants are defined and
      exported.
- [ ] `_build_database_prompt_builder() -> PromptBuilder` returns a
      builder whose `layer_names` (or equivalent inspection method)
      contains `database_context`, `database_safety`, `schema_grounding`,
      `database_instructions` PLUS the `default()` baseline.
- [ ] `builder.configure({...}); builder.build({...})` does not raise
      when given the minimal set of required vars.
- [ ] Unit tests pass:
      `pytest packages/ai-parrot/tests/bots/database/test_database_prompts.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/database/prompts.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_database_prompts.py
import pytest
from parrot.bots.database.prompts import (
    DATABASE_CONTEXT_LAYER,
    DATABASE_SAFETY_LAYER,
    SCHEMA_GROUNDING_LAYER,
    DATABASE_INSTRUCTIONS_LAYER,
    _build_database_prompt_builder,
)


def test_database_prompt_builder_factory_assembles_layers():
    """The factory returns a PromptBuilder containing all four DB layers."""
    builder = _build_database_prompt_builder()
    # Use whatever the builder exposes (e.g. _layers / layers / iterate)
    names = {layer.name for layer in builder.layers}
    expected = {
        "database_context",
        "database_safety",
        "schema_grounding",
        "database_instructions",
    }
    assert expected.issubset(names)


def test_database_prompt_layers_render_with_minimal_context():
    """builder.configure(...) + builder.build(...) does not raise."""
    builder = _build_database_prompt_builder()
    static_ctx = {
        "agent_name": "DatabaseAgent",
        "agent_role": "Database analyst",
    }
    dynamic_ctx = {
        "query": "SELECT 1",
        "database": "postgres",
        "intent": "explore_schema",
        "output_components": "QUERY",
        "schema_summary": "public.users(id, name)",
    }
    builder.configure(static_ctx)
    rendered = builder.build(dynamic_ctx)
    assert "DatabaseAgent" in rendered or rendered  # smoke


def test_no_legacy_placeholder_constants_remain():
    """The five legacy constants are deleted."""
    import parrot.bots.database.prompts as prompts_mod
    for legacy in (
        "DB_AGENT_PROMPT",
        "BASIC_HUMAN_PROMPT",
        "DATA_ANALYSIS_PROMPT",
        "DATABASE_EDUCATION_PROMPT",
        "DATABASE_TROUBLESHOOTING_PROMPT",
    ):
        assert not hasattr(prompts_mod, legacy), f"{legacy} should be deleted"
```

---

## Agent Instructions

1. Read the spec §2 (Architectural Design — Overview, New Public
   Interfaces) and §3 (Module 2) before editing.
2. Read `packages/ai-parrot/src/parrot/bots/data.py:305` for the
   PandasAgent factory pattern.
3. Re-verify the line numbers in this contract — `prompts/layers.py`
   and `prompts/builder.py` may have shifted.
4. Author the four layer templates carefully — they are the LLM's
   contract for what the agent does. Keep them tight and specific.
5. Run `pytest packages/ai-parrot/tests/bots/database/test_database_prompts.py`.
6. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-13
**Notes**: Rewrote `prompts.py` with 4 PromptLayer constants + `_build_database_prompt_builder()`. All 3 tests pass, ruff clean. Adapted test to use `builder.layer_names` (list of str) instead of `builder.layers` (property doesn't exist). Also removed `DB_AGENT_PROMPT` import from `agent.py` (1-line stub placeholder) to unblock the import chain without aliasing.
**Deviations from spec**: `agent.py` touched minimally — `system_prompt_template = ""` placeholder added (TASK-1128 will replace with PromptBuilder). Test uses `set(builder.layer_names)` instead of `{layer.name for layer in builder.layers}` since `PromptBuilder` exposes `layer_names` not `layers`.

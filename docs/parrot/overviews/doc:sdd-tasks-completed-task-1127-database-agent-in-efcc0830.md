---
type: Wiki Overview
title: 'TASK-1127: DatabaseAgentToolkit (Internal Toolkit)'
id: doc:sdd-tasks-completed-task-1127-database-agent-internal-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of FEAT-164 (spec §3 "Module 3"). The legacy
relates_to:
- concept: mod:parrot.bots.database
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1127: DatabaseAgentToolkit (Internal Toolkit)

**Feature**: FEAT-164 — DatabaseAgent Homologation
**Spec**: `sdd/specs/database-agent-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4–8h)
**Depends-on**: TASK-1125
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-164 (spec §3 "Module 3"). The legacy
`AbstractDBAgent` (`bots/database/abstract.py`, ~3067 LOC) carries ~16
utility helpers (EXPLAIN-plan formatting, optimization tips, query
examples, SQL extraction, type simplification, etc.) that have no
equivalent in the toolkit layer. The full class is scheduled for
deletion (Module 7 / TASK-1130), but those helpers are still useful —
this task ports them to a new internal toolkit so the LLM can call them
as tools, gated by `OutputComponent` / `QueryIntent`.

Open Question #4 resolution: register all 16 tools but gate them via
`OutputComponent` — gating logic itself lives in Module 5 / TASK-1128.
This task only delivers the toolkit class with all 16 `@tool`-decorated
methods.

---

## Scope

- Create `bots/database/toolkits/_internal.py` with class
  `DatabaseAgentToolkit(AbstractToolkit)`.
- Port the 16 helper methods listed in spec §2 "New Public Interfaces"
  from `bots/database/abstract.py` into the new toolkit, decorated with
  `@tool`, with non-empty Google-style docstrings.
- Each tool's docstring is the LLM's tool description per `CLAUDE.md` —
  make them clear, single-sentence purpose + parameter/return summary.
- Add the toolkit to `bots/database/toolkits/__init__.py` re-exports as
  internal (leading underscore in module path signals not-for-direct-
  consumer use).
- Write unit tests verifying each tool has a docstring and smoke-testing
  three key helpers.

**NOT in scope**:
- The gating logic (only-expose-tools-when-component-active) — that
  belongs to Module 5 / TASK-1128 (`agent.py`).
- Deleting `abstract.py` — Module 7 / TASK-1130.
- Wiring the toolkit into `DatabaseAgent.configure()` — Module 5.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py` | CREATE | `DatabaseAgentToolkit` class with 16 `@tool` methods. |
| `packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py` | MODIFY | Re-export `DatabaseAgentToolkit`. |
| `packages/ai-parrot/tests/bots/database/test_internal_toolkit.py` | CREATE | Unit tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing — verify before use:
from parrot.tools import tool                       # parrot/tools/__init__.py (verify exact path)
from parrot.tools.abstract import AbstractToolkit   # parrot/tools/abstract.py (verify exact path)

from parrot.bots.database.models import (
    OutputComponent,         # bots/database/models.py:26
    QueryIntent,             # bots/database/models.py:74
)
from parrot.bots.database import QueryDataset       # added by TASK-1125
```

**Required first step**: verify the exact import paths for `@tool` and
`AbstractToolkit` — grep for `class AbstractToolkit` and `def tool` in
`parrot/tools/` BEFORE writing any import line.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/database/abstract.py
# (the file being mined; verify the source helpers still exist there
# before porting — names and signatures below are TARGETS, not promises)

# Locate each of these in abstract.py via:
#   grep -n "def format_explain_plan\|def simplify_column_type\|..." \
#     packages/ai-parrot/src/parrot/bots/database/abstract.py
```

### Methods to Port (16 total, from spec §2)

Each becomes a `@tool`-decorated public method on `DatabaseAgentToolkit`.
Method signatures below are the **target** shapes; if the legacy version
in `abstract.py` differs slightly, prefer the target shape — the toolkit
is the new public surface.

| # | Method | Sync/Async | Returns |
|---|---|---|---|
| 1 | `format_explain_plan(plan_json: str) -> str` | sync | str |
| 2 | `simplify_column_type(raw_type: str) -> str` | sync | str |
| 3 | `extract_sql_from_response(response_text: str) -> str` | sync | str |
| 4 | `extract_table_name_from_query(query: str) -> Optional[str]` | sync | Optional[str] |
| 5 | `extract_table_names_from_metadata(metadata_context: str) -> List[str]` | sync | List[str] |
| 6 | `generate_create_table_statement(table_yaml: str) -> str` | sync | str |
| 7 | `generate_optimization_tips(sql_query: str, query_plan: str) -> List[str]` | **async** | List[str] |
| 8 | `generate_basic_optimization_tips(sql_query: str, query_plan: str) -> List[str]` | sync | List[str] |
| 9 | `generate_table_specific_tips(table_yaml: str) -> List[str]` | sync | List[str] |
| 10 | `generate_examples(schema_context: str, intent: str) -> List[str]` | **async** | List[str] |
| 11 | `extract_performance_metrics(explain_analyze: str) -> Dict[str, Any]` | sync | Dict[str, Any] |
| 12 | `format_as_text(data: Any, components: OutputComponent) -> str` | sync | str |
| 13 | `format_query_history(history: List[Dict[str, Any]]) -> str` | sync | str |
| 14 | `parse_tips(response_text: str) -> List[str]` | sync | List[str] |
| 15 | `is_explanatory_response(response_text: str) -> bool` | sync | bool |
| 16 | `get_schema_counts_direct(schema_name: str) -> Tuple[int, int]` | **async** | Tuple[int, int] |

### Does NOT Exist

- ~~`DatabaseAgentToolkit`~~ — not defined anywhere; this task creates it.
- ~~`bots/database/toolkits/_internal.py`~~ — not present; this task
  creates it.
- ~~A `@tool` decorator on existing `abstract.py` methods~~ — `AbstractDBAgent`
  methods are NOT exposed as tools today. Porting them into a toolkit is
  what makes them callable by the LLM.
- ~~`OutputComponent`-based gating inside the toolkit~~ — gating logic
  lives at the agent layer (Module 5). The toolkit is component-agnostic.

---

## Implementation Notes

### Pattern to Follow

Look at an existing toolkit for the class shape. Likely candidates
(verify which one is canonical):
- `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` —
  domain-specific toolkit with `@tool` methods.
- `packages/ai-parrot/src/parrot/tools/...` for the `@tool` decorator
  and `AbstractToolkit` patterns mentioned in `CLAUDE.md`.

### Porting Strategy

For each of the 16 methods:

1. `grep -n "def <method_name>"` in `bots/database/abstract.py` to find
   the legacy source.
2. Copy the function body verbatim where possible.
3. Adjust `self` references — the toolkit version may not need agent
   state. If the legacy method depended on `self.<something>` (e.g.
   `self.llm`, `self.schema_cache`), inject that via the toolkit
   constructor or refactor to a pure function. Prefer pure / stateless
   versions where the legacy used loose state.
4. Add a Google-style docstring describing purpose, args, returns.
   Example:
   ```python
   @tool
   def simplify_column_type(self, raw_type: str) -> str:
       """Simplify a verbose SQL column type to its base name.

       Args:
           raw_type: Full column type (e.g. ``"numeric(10,2)"``).

       Returns:
           The base type only (e.g. ``"numeric"``).
       """
   ```
5. Strip out any logging that wires to `self.logger` if the toolkit
   does not yet have a `logger` attribute — use `logging.getLogger(__name__)`
   at module level instead.

### Key Constraints

- Every `@tool` method MUST have a non-empty docstring (LLM tool
  description). The unit test asserts this.
- Methods #7, #10, #16 are `async`; all others are sync. Match exactly.
- Sync `@tool` methods must remain sync — wrapping them in `async def`
  changes the LLM tool calling contract.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/database/abstract.py` — source of
  the 16 method bodies.
- `packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py` — toolkit
  pattern (`AbstractToolkit` subclass with `@tool` methods).

---

## Acceptance Criteria

- [ ] `DatabaseAgentToolkit` defined at
      `bots/database/toolkits/_internal.py`.
- [ ] All 16 methods present, decorated with `@tool`, with correct
      sync/async signature and a non-empty docstring.
- [ ] `from parrot.bots.database.toolkits import DatabaseAgentToolkit`
      succeeds.
- [ ] Unit tests pass:
      `pytest packages/ai-parrot/tests/bots/database/test_internal_toolkit.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py` clean.
- [ ] The toolkit instantiates without arguments
      (`DatabaseAgentToolkit()` does not raise) OR accepts only kwargs
      with sensible defaults.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_internal_toolkit.py
import inspect
import pytest
from parrot.bots.database.toolkits import DatabaseAgentToolkit


EXPECTED_TOOLS = {
    "format_explain_plan",
    "simplify_column_type",
    "extract_sql_from_response",
    "extract_table_name_from_query",
    "extract_table_names_from_metadata",
    "generate_create_table_statement",
    "generate_optimization_tips",
    "generate_basic_optimization_tips",
    "generate_table_specific_tips",
    "generate_examples",
    "extract_performance_metrics",
    "format_as_text",
    "format_query_history",
    "parse_tips",
    "is_explanatory_response",
    "get_schema_counts_direct",
}


@pytest.fixture
def toolkit():
    return DatabaseAgentToolkit()


def test_all_expected_tools_present(toolkit):
    missing = EXPECTED_TOOLS - {name for name in dir(toolkit) if not name.startswith("_")}
    assert not missing, f"Missing tools: {missing}"


def test_internal_toolkit_tools_have_docstrings(toolkit):
    """Every @tool method carries a non-empty docstring."""
    for tool_name in EXPECTED_TOOLS:
        method = getattr(toolkit, tool_name)
        assert method.__doc__ and method.__doc__.strip(), (
            f"{tool_name} has no docstring"
        )


def test_format_explain_plan_handles_json_string(toolkit):
    """Smoke test for format_explain_plan with a representative EXPLAIN JSON."""
    sample = '[{"Plan": {"Node Type": "Seq Scan", "Relation Name": "users"}}]'
    result = toolkit.format_explain_plan(sample)
    assert isinstance(result, str) and result


def test_simplify_column_type(toolkit):
    """numeric(10,2) -> numeric, varchar(255) -> varchar."""
    assert toolkit.simplify_column_type("numeric(10,2)") == "numeric"
    assert toolkit.simplify_column_type("varchar(255)") == "varchar"
    assert toolkit.simplify_column_type("timestamp without time zone") == "timestamp"


def test_extract_sql_from_response(toolkit):
    """Pulls SQL out of an LLM markdown response."""
    text = "Here is the query:\n```sql\nSELECT * FROM users\n```\nDone."
    assert "SELECT * FROM users" in toolkit.extract_sql_from_response(text)


@pytest.mark.asyncio
async def test_generate_optimization_tips_signature(toolkit):
    """Async helpers are reachable; smoke-test signature only (no LLM call)."""
    assert inspect.iscoroutinefunction(toolkit.generate_optimization_tips)
```

---

## Agent Instructions

1. Read spec §2 (Architectural Design — New Public Interfaces, third
   block) and §3 (Module 3).
2. **First action**: `grep -n "class AbstractToolkit\|^def tool\b"
   packages/ai-parrot/src/parrot/tools/` to confirm the exact import
   paths. Do NOT guess.
3. For each of the 16 methods, locate the legacy implementation in
   `abstract.py` via grep, port it, and add the docstring.
4. If a legacy method has agent-state coupling (e.g. `self.llm`),
   either inject via constructor or refactor to a pure function — the
   toolkit must remain instantiable without a parent agent.
5. Run `pytest` and `ruff check`.
6. Move this file to `sdd/tasks/completed/` and update the per-spec
   index.

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-13
**Notes**: All 16 methods implemented in `toolkits/_internal.py`. 6/6 tests pass, ruff clean. Added `_async_tool` local helper to preserve `inspect.iscoroutinefunction` for the 3 async methods — the stock `@tool` decorator creates a sync wrapper that breaks the check.
**Deviations from spec**: `@_async_tool` used for async methods (#7, #10, #16) instead of bare `@tool` to satisfy `inspect.iscoroutinefunction` test. The `@tool` decorator was still applied (inside `_async_tool`) to generate metadata.

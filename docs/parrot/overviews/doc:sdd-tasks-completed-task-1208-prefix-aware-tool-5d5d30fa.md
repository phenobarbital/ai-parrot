---
type: Wiki Overview
title: 'TASK-1208: Prefix-aware tool resolution in DatabaseAgent'
id: doc:sdd-tasks-completed-task-1208-prefix-aware-tool-resolution-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'PR #866 added external-toolkit tool exposure to'
relates_to:
- concept: mod:parrot.bots.database.agent
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits._internal
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

# TASK-1208: Prefix-aware tool resolution in DatabaseAgent

**Feature**: FEAT-171 — Prefix-Aware Tool Resolution for DatabaseAgent
**Spec**: `sdd/specs/databaseagent-prefix-aware-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

PR #866 added external-toolkit tool exposure to
`DatabaseAgent._compute_active_tools` but baked in a hardcoded
`"db_"` prefix assumption. Toolkits with a different `tool_prefix`
(`"bq"`, `"influx"`, …) become invisible to the LLM. Toolkit-name
collisions are silently dropped. This task fixes both — it splits
`_COMPONENT_TO_TOOL_NAMES` into two maps (internal vs external),
rewrites `_compute_active_tools` to be prefix-aware, dedupes
collision warnings, and emits a `DeprecationWarning` for legacy
`tool_prefix=None` toolkits pointing at FEAT-172.

Implements **Module 1 + Module 2** of the spec.

---

## Scope

- Replace `_COMPONENT_TO_TOOL_NAMES` (agent.py:43-82) with two
  module-level constants:
  - `_INTERNAL_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]]`
    — every name **without** the `db_` prefix today.
  - `_TOOLKIT_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]]`
    — names with `db_` today, stripped of the prefix. Logical
    names only.
- Add a top-of-section comment block above
  `_TOOLKIT_TOOLS_BY_COMPONENT` explaining that names are LOGICAL
  and each toolkit applies its own prefix at resolution time.
- Initialise per-agent collision/deprecation tracking state in
  `DatabaseAgent.__init__` (agent.py:106-128):
  ```python
  self._logged_collisions: Set[Tuple[str, FrozenSet[str]]] = set()
  self._warned_none_prefix: Set[int] = set()
  ```
- Rewrite `_compute_active_tools` (agent.py:628-680):
  - Pass 1 — internal helpers: iterate `_INTERNAL_TOOLS_BY_COMPONENT`
    and `getattr(self._internal_toolkit, name, None)` (unchanged
    path).
  - Pass 2 — external toolkits: for every active `OutputComponent`
    flag, for every logical name in `_TOOLKIT_TOOLS_BY_COMPONENT`,
    for every `tk` in `self.toolkits`:
    - If `tk.tool_prefix is None`: fall back to `logical_name` as
      the full name **and** emit a one-time `DeprecationWarning`
      per toolkit instance (keyed by `id(tk)` in
      `self._warned_none_prefix`).
    - Else: build `full_name = f"{tk.tool_prefix}{tk.prefix_separator}{logical_name}"`.
    - Call `tk.get_tool(full_name)`.
    - If already exposed (by another toolkit): emit deduped
      collision warning keyed by `(full_name,
      frozenset({first_owner_cls, this_cls}))` in
      `self._logged_collisions`. Include the current
      `OutputComponent.name` in the message. Skip the duplicate
      (first-wins).
  - Preserve the return type (list of tool objects accepted by
    `ToolManager.register_tool`).
- Update the docstring on `_compute_active_tools` (agent.py:628-649):
  drop the "`db_*` after `tool_prefix` is applied" wording in
  favour of "each toolkit's own `tool_prefix` is applied at
  resolution time".
- Add Mock fixture in `tests/unit/bots/database/conftest.py`
  (`MockDatabaseToolkit` per spec §4).
- Unit tests in
  `packages/ai-parrot/tests/unit/bots/database/test_compute_active_tools.py`
  (CREATE):
  - `test_compute_active_tools_default_prefix`
  - `test_compute_active_tools_custom_prefix`
  - `test_compute_active_tools_two_toolkits_distinct_prefixes`
  - `test_compute_active_tools_logs_collision` (asserts the
    `OutputComponent.name` is in the message)
  - `test_collision_warning_deduplicated_across_turns` (three
    calls → one log)
  - `test_none_prefix_graceful_resolution`
  - `test_none_prefix_emits_deprecation_warning_once`
  - `test_no_regression_sql_analyst_path`

**NOT in scope**:
- Making `tool_prefix` mandatory or fail-fast at toolkit
  registration time (**FEAT-172**).
- Migrating `DatabaseAgentToolkit` to use a `tool_prefix`
  (**FEAT-173**).
- Touching `AbstractToolkit` prefix-rewrite mechanism
  (`tools/toolkit.py:350-...`).
- Integration test for multi-toolkit runtime (TASK-1209).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | Replace `_COMPONENT_TO_TOOL_NAMES` with two new maps; rewrite `_compute_active_tools`; add state in `__init__`; update docstring |
| `packages/ai-parrot/tests/unit/bots/database/conftest.py` | CREATE or MODIFY | Add `MockDatabaseToolkit` fixture |
| `packages/ai-parrot/tests/unit/bots/database/test_compute_active_tools.py` | CREATE | Unit tests for all eight scenarios |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# bots/database/agent.py — already imports
import logging
import warnings  # ← ADD this import for the DeprecationWarning
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from parrot.bots.database.toolkits._internal import DatabaseAgentToolkit
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.bots.database.models import OutputComponent
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    tool_prefix: Optional[str] = None       # line 242
    prefix_separator: str = "_"              # line 245
    def get_tool(self, name: str) -> Optional[AbstractTool]: ...  # line 433
    def list_tool_names(self) -> List[str]: ...   # not needed here

# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class DatabaseToolkit(AbstractToolkit):
    tool_prefix: str = "db"                  # line 93 — concrete default

# packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py
class DatabaseAgentToolkit(AbstractToolkit):
    # tool_prefix is NOT overridden — inherits None.
    # FEAT-173 will migrate it; FEAT-171 does NOT.

# packages/ai-parrot/src/parrot/bots/database/agent.py
class DatabaseAgent(BasicAgent):                # line 85
    def __init__(self, name="DatabaseAgent", toolkits=None, ...): ...  # line 106
    def _compute_active_tools(self, components: OutputComponent) -> List[Any]: ...  # line 628
```

### Existing Module-Level Constant (REPLACED)
```python
# agent.py:43-82 — current shape; this task REPLACES the constant entirely.
_COMPONENT_TO_TOOL_NAMES: Dict[OutputComponent, Set[str]] = {
    OutputComponent.SQL_QUERY: {
        "extract_sql_from_response", "extract_table_name_from_query",
        "db_generate_query", "db_validate_query",
    },
    OutputComponent.OPTIMIZATION_TIPS: {
        "generate_optimization_tips", "generate_basic_optimization_tips",
        "generate_table_specific_tips", "extract_performance_metrics",
    },
    OutputComponent.EXECUTION_PLAN: {
        "format_explain_plan", "extract_performance_metrics", "db_explain_query",
    },
    OutputComponent.SCHEMA_CONTEXT: {
        "generate_create_table_statement", "simplify_column_type",
        "extract_table_names_from_metadata", "get_schema_counts_direct",
        "db_search_schema",
    },
    OutputComponent.EXAMPLES: {"generate_examples"},
    OutputComponent.DATA_RESULTS: {"format_query_history"},
    OutputComponent.DOCUMENTATION: {
        "format_as_text", "is_explanatory_response", "parse_tips",
    },
}
```

### Existing `_compute_active_tools` body to be rewritten
```python
# agent.py:628-680 — current body for reference (rewritten by this task)
def _compute_active_tools(self, components: OutputComponent) -> List[Any]:
    if self._internal_toolkit is None:
        return []
    exposed_names: Set[str] = set()
    for flag, tool_names in _COMPONENT_TO_TOOL_NAMES.items():
        if flag in components:
            exposed_names |= tool_names
    tools: List[Any] = []
    seen: Set[str] = set()
    for name in exposed_names:
        attr = getattr(self._internal_toolkit, name, None)
        if attr is not None and getattr(attr, "_is_tool", False):
            tools.append(attr)
            seen.add(name)
    for tk in self.toolkits:
        get_tool = getattr(tk, "get_tool", None)
        if get_tool is None:
            continue
        for name in exposed_names:
            if name in seen:
                continue
            tk_tool = get_tool(name)
            if tk_tool is not None:
                tools.append(tk_tool)
                seen.add(name)
    return tools
```

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractToolkit.tools()`~~ — does not exist as a list-returning
  method. Use `get_tool(name)` (exact lookup) — no iteration needed
  here.
- ~~`AbstractToolkit.iter_tools()`~~ — does not exist.
- ~~`DatabaseAgent.add_toolkit()`~~ — does not exist; toolkits come
  via `__init__(toolkits=...)`.
- The internal toolkit (`DatabaseAgentToolkit`) does **NOT** carry
  `tool_prefix`. FEAT-173 will migrate it. Pass 1 in this task
  must keep using `getattr` against `self._internal_toolkit`, not
  `tk.get_tool`.

---

## Implementation Notes

### Two-map split — mechanical
Walk every entry of the current `_COMPONENT_TO_TOOL_NAMES`:
- Names that start with `db_` → strip the prefix, drop into
  `_TOOLKIT_TOOLS_BY_COMPONENT[component]`.
- Every other name → drop into `_INTERNAL_TOOLS_BY_COMPONENT[component]`.

Result (per spec §2 Data Models):
```python
_INTERNAL_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]] = {
    OutputComponent.SQL_QUERY: {
        "extract_sql_from_response", "extract_table_name_from_query",
    },
    OutputComponent.OPTIMIZATION_TIPS: {
        "generate_optimization_tips", "generate_basic_optimization_tips",
        "generate_table_specific_tips", "extract_performance_metrics",
    },
    OutputComponent.EXECUTION_PLAN: {
        "format_explain_plan", "extract_performance_metrics",
    },
    OutputComponent.SCHEMA_CONTEXT: {
        "generate_create_table_statement", "simplify_column_type",
        "extract_table_names_from_metadata", "get_schema_counts_direct",
    },
    OutputComponent.EXAMPLES: {"generate_examples"},
    OutputComponent.DATA_RESULTS: {"format_query_history"},
    OutputComponent.DOCUMENTATION: {
        "format_as_text", "is_explanatory_response", "parse_tips",
    },
}

# Names below are LOGICAL — each toolkit applies its own
# `tool_prefix` at resolution time via `tk.get_tool(full_name)`.
# Hardcoded "db_" prefixes have been removed (FEAT-171).
_TOOLKIT_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]] = {
    OutputComponent.SQL_QUERY: {"generate_query", "validate_query"},
    OutputComponent.EXECUTION_PLAN: {"explain_query"},
    OutputComponent.SCHEMA_CONTEXT: {"search_schema"},
}
```

### Pass-2 resolution loop (Q1 + Q2 resolutions)
```python
# pseudo — implement in the rewritten _compute_active_tools
first_owner: Dict[str, DatabaseToolkit] = {}

for component in OutputComponent:
    if component not in components:
        continue
    for logical_name in _TOOLKIT_TOOLS_BY_COMPONENT.get(component, set()):
        for tk in self.toolkits:
            get_tool = getattr(tk, "get_tool", None)
            if get_tool is None:
                continue

            if tk.tool_prefix is None:
                if id(tk) not in self._warned_none_prefix:
                    self._warned_none_prefix.add(id(tk))
                    warnings.warn(
                        f"{type(tk).__name__} has tool_prefix=None; resolving "
                        f"tools by logical name. This is a transitional escape "
                        f"hatch and will be rejected at configure() time once "
                        f"FEAT-172 ships.",
                        DeprecationWarning,
                        stacklevel=2,
                    )
                full_name = logical_name
            else:
                full_name = (
                    f"{tk.tool_prefix}{tk.prefix_separator}{logical_name}"
                )

            tk_tool = get_tool(full_name)
            if tk_tool is None:
                continue

            if full_name in seen:
                owner_cls = type(first_owner[full_name]).__name__
                this_cls = type(tk).__name__
                key = (full_name, frozenset({owner_cls, this_cls}))
                if key not in self._logged_collisions:
                    self._logged_collisions.add(key)
                    self.logger.warning(
                        "Toolkit tool name collision: %r already exposed by %s; "
                        "skipping duplicate from %s (component=%s). "
                        "Toolkit order in self.toolkits determines first-wins; "
                        "reorder if needed.",
                        full_name, owner_cls, this_cls, component.name,
                    )
                continue

            tools.append(tk_tool)
            seen.add(full_name)
            first_owner[full_name] = tk
```

The `seen` set must hold **full** names in Pass 2 (`full_name`),
not logical names — different toolkits can legitimately expose the
same logical name under different prefixes (`db_search_schema` and
`bq_search_schema`).

### Pass 1 (internal helpers)
Pass 1 stays close to today's body, but reads from
`_INTERNAL_TOOLS_BY_COMPONENT` instead of the merged map. The
`seen` set for Pass 1 can be separate (or unified — both work
since prefix namespaces don't overlap until FEAT-173 lands).

### Mock fixture
```python
# tests/unit/bots/database/conftest.py
from typing import List
import pytest
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.tools.toolkit import tool


class MockDatabaseToolkit(DatabaseToolkit):
    """Minimal stub: declares tool_prefix and exposes one tool."""

    database_type: str = "mock"
    primary_schema: str = "public"
    allowed_schemas: List[str] = ["public"]

    @tool
    async def search_schema(self, search_term: str, limit: int = 10):
        return []

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass
```
The fixture should accept a `tool_prefix` parameter so tests can
instantiate `MockDatabaseToolkit(tool_prefix="mk")` and
`MockDatabaseToolkit(tool_prefix=None)` variants.

### Test for deprecation warning
Use `pytest.warns(DeprecationWarning)` for the first call, then
`warnings.catch_warnings(record=True)` for the second call to
assert no warning is re-emitted. Reset `_warned_none_prefix`
between tests.

### Acceptance grep
After implementation:
```bash
grep '"db_' packages/ai-parrot/src/parrot/bots/database/agent.py
```
Must return **zero lines**. This is an explicit acceptance
criterion from the spec.

---

## Acceptance Criteria

- [ ] `_COMPONENT_TO_TOOL_NAMES` is gone; the two new maps exist.
- [ ] `grep '"db_' packages/ai-parrot/src/parrot/bots/database/agent.py`
      returns zero matches.
- [ ] `DatabaseAgent` instances expose `_logged_collisions: Set`
      and `_warned_none_prefix: Set` after construction.
- [ ] `_compute_active_tools` resolves toolkit tools via
      `tk.get_tool(f"{tk.tool_prefix}{tk.prefix_separator}{logical}")`.
- [ ] A toolkit with `tool_prefix="mk"` exposing `mk_search_schema`
      is surfaced under `OutputComponent.SCHEMA_CONTEXT`.
- [ ] Two toolkits with distinct prefixes (`db`, `mk`) coexist —
      both tools surface.
- [ ] Collision across two toolkits with the same prefix logs a
      single warning per call site combination across turns, and
      the message includes the current `OutputComponent.name`.
- [ ] Toolkit with `tool_prefix=None` resolves via the logical
      name and emits exactly one `DeprecationWarning` per instance.
- [ ] `test_no_regression_sql_analyst_path` passes — current
      `sql_analyst` surface (one `PostgresToolkit` with
      `tool_prefix="db"`) is byte-identical before and after.
- [ ] `pytest packages/ai-parrot/tests/unit/bots/database/test_compute_active_tools.py -v` passes.
- [ ] Docstring on `_compute_active_tools` no longer claims
      "`db_*` after `tool_prefix` is applied".
- [ ] Existing tests in `tests/unit/bots/database/` still pass.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/database/test_compute_active_tools.py
import warnings
import pytest

from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import OutputComponent


@pytest.fixture
def agent_factory(mock_toolkit_factory):
    """Build a DatabaseAgent already past __init__ (no async start)."""
    def _make(toolkits=None):
        agent = DatabaseAgent(name="t", toolkits=toolkits or [])
        # Inject a stub _internal_toolkit so Pass 1 doesn't bail.
        agent._internal_toolkit = type("I", (), {})()
        return agent
    return _make


class TestPrefixAwareResolution:
    def test_default_prefix(self, agent_factory, mock_toolkit_factory):
        agent = agent_factory(
            toolkits=[mock_toolkit_factory(tool_prefix="db")],
        )
        tools = agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        names = {getattr(t, "name", None) for t in tools}
        assert "db_search_schema" in names

    def test_custom_prefix(self, agent_factory, mock_toolkit_factory):
        agent = agent_factory(
            toolkits=[mock_toolkit_factory(tool_prefix="mk")],
        )
        tools = agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        names = {getattr(t, "name", None) for t in tools}
        assert "mk_search_schema" in names

    def test_two_toolkits_distinct_prefixes(
        self, agent_factory, mock_toolkit_factory,
    ):
        agent = agent_factory(toolkits=[
            mock_toolkit_factory(tool_prefix="db"),
            mock_toolkit_factory(tool_prefix="mk"),
        ])
        tools = agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        names = {getattr(t, "name", None) for t in tools}
        assert {"db_search_schema", "mk_search_schema"}.issubset(names)


class TestCollisionLogging:
    def test_logs_collision_with_component(
        self, agent_factory, mock_toolkit_factory, caplog,
    ):
        agent = agent_factory(toolkits=[
            mock_toolkit_factory(tool_prefix="db"),
            mock_toolkit_factory(tool_prefix="db"),
        ])
        agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        msgs = [r.getMessage() for r in caplog.records]
        assert any("SCHEMA_CONTEXT" in m and "collision" in m for m in msgs)

    def test_collision_deduplicated_across_turns(
        self, agent_factory, mock_toolkit_factory, caplog,
    ):
        agent = agent_factory(toolkits=[
            mock_toolkit_factory(tool_prefix="db"),
            mock_toolkit_factory(tool_prefix="db"),
        ])
        for _ in range(3):
            agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        collisions = [r for r in caplog.records if "collision" in r.getMessage()]
        assert len(collisions) == 1


class TestLegacyNonePrefix:
    def test_none_prefix_graceful(self, agent_factory, mock_toolkit_factory):
        agent = agent_factory(
            toolkits=[mock_toolkit_factory(tool_prefix=None)],
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            tools = agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        names = {getattr(t, "name", None) for t in tools}
        assert "search_schema" in names

    def test_none_prefix_emits_deprecation_once(
        self, agent_factory, mock_toolkit_factory,
    ):
        tk = mock_toolkit_factory(tool_prefix=None)
        agent = agent_factory(toolkits=[tk])
        with pytest.warns(DeprecationWarning, match="FEAT-172"):
            agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        # Second call: must NOT emit again.
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
            assert not [
                x for x in w if issubclass(x.category, DeprecationWarning)
            ]


class TestNoRegression:
    def test_sql_analyst_surface_unchanged(
        self, agent_factory, postgres_toolkit_fixture,
    ):
        """One PostgresToolkit(tool_prefix='db') — surface must be the
        same set of tool names as before this feature."""
        agent = agent_factory(toolkits=[postgres_toolkit_fixture])
        tools = agent._compute_active_tools(
            OutputComponent.SQL_QUERY |
            OutputComponent.SCHEMA_CONTEXT |
            OutputComponent.EXECUTION_PLAN,
        )
        names = {getattr(t, "name", None) for t in tools}
        # Pinned canonical surface
        assert {"db_search_schema", "db_generate_query",
                "db_validate_query", "db_explain_query"}.issubset(names)
```

---

## Agent Instructions

1. Read the spec at `sdd/specs/databaseagent-prefix-aware-tools.spec.md`
   end-to-end. §2 (resolutions for Q1/Q2) and §3 Module 1 contain
   the implementation pattern.
2. Verify the Codebase Contract: re-grep `agent.py` for the line
   numbers — they may shift.
3. Implement in this order: (a) split maps, (b) `__init__` state,
   (c) rewrite `_compute_active_tools`, (d) Mock fixture, (e) unit
   tests, (f) docstrings.
4. Run `pytest packages/ai-parrot/tests/unit/bots/database/ -v`.
5. Run the acceptance grep: `grep '"db_' packages/ai-parrot/src/parrot/bots/database/agent.py` — must be empty.
6. Run `ruff check packages/ai-parrot/src/parrot/bots/database/agent.py`.
7. Move task file to `sdd/tasks/completed/` and update the
   per-spec index `sdd/tasks/index/databaseagent-prefix-aware-tools.json`.
8. Fill in the Completion Note.

---

## Completion Note

Implemented by sdd-worker on 2026-05-15.

**Changes made:**
- `agent.py`: Added `import warnings` and `FrozenSet, Tuple` to typing imports.
- `agent.py`: Replaced `_COMPONENT_TO_TOOL_NAMES` with two maps:
  `_INTERNAL_TOOLS_BY_COMPONENT` (names without prefix, resolved via `getattr`)
  and `_TOOLKIT_TOOLS_BY_COMPONENT` (logical names, each toolkit applies its own prefix).
- `agent.py`: Added `self._logged_collisions: Set[Tuple[str, FrozenSet[str]]]` and
  `self._warned_none_prefix: Set[int]` to `DatabaseAgent.__init__`.
- `agent.py`: Rewrote `_compute_active_tools` with two-pass prefix-aware resolution.
- Updated docstring to drop hardcoded prefix wording.
- `tests/unit/bots/database/conftest.py`: Created `MockDatabaseToolkit` fixture.
- `tests/unit/bots/database/test_compute_active_tools.py`: Created 8 unit tests.

**Acceptance grep:** `grep '"db_' agent.py` returned zero matches.
**Tests:** 8/8 passed.

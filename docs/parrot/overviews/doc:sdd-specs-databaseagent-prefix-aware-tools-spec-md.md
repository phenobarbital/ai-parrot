---
type: Wiki Overview
title: 'Feature Specification: Prefix-Aware Tool Resolution for DatabaseAgent'
id: doc:sdd-specs-databaseagent-prefix-aware-tools-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'PR #866 (`fix/database-agent-improvements`, merged into `dev`) added'
relates_to:
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits._internal
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Prefix-Aware Tool Resolution for DatabaseAgent

**Feature ID**: FEAT-171
**Date**: 2026-05-14
**Author**: Juan Francisco Ruffato
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

PR #866 (`fix/database-agent-improvements`, merged into `dev`) added
external-toolkit tool exposure to
`DatabaseAgent._compute_active_tools` so that `sql_analyst` (and any
plugin-injected toolkit) could finally reach the LLM. The fix shipped
correctly but bakes in a hardcoded prefix assumption that the parrot
maintainer (Jesús Lara) flagged during review:

> "Los toolkits tienen prefijos. Dos tools no se deberían llamar
> igual. Imaginá `get_schema` en `DatabaseToolkit` y `get_schema` en
> `QueryToolkit` — hay colisión de nombres. Los toolkits deberían
> tener un prefijo en el nombre de función."

The current map `_COMPONENT_TO_TOOL_NAMES` literally hardcodes the
strings `"db_search_schema"`, `"db_describe_table"`,
`"db_generate_query"`, `"db_validate_query"`, `"db_explain_query"`.
A toolkit declared with a different prefix
(`BigQueryToolkit(tool_prefix="bq")`,
`InfluxToolkit(tool_prefix="influx")`, a hypothetical
`QueryToolkit(tool_prefix="qry")`) exposes
`bq_search_schema` / `influx_search_schema` / `qry_search_schema`,
none of which match any entry in the map — so those tools become
invisible to the LLM even though the toolkit is correctly attached.

A secondary problem: when two attached toolkits register the same
fully-qualified tool name, the current `seen: Set[str]` guard drops
the second one without logging anything. The LLM sees only the first;
the second toolkit's work is silently shadowed.

The `AbstractToolkit` base already documents
(`tools/toolkit.py:240-241`) that `tool_prefix=None` is
*"a transitional escape hatch and will become mandatory in a future
release."* The codebase has decided the direction; `DatabaseAgent`
simply did not adopt it.

### Goals

- Make external-toolkit tool resolution **prefix-aware**: a toolkit
  with any `tool_prefix` value (or `None`) gets its tools exposed
  correctly to the LLM, gated by the same component flags.
- Detect runtime tool-name collisions **loudly**: log a warning when
  two toolkits would expose the same fully-qualified name and skip
  the duplicate with deterministic first-wins semantics.
- Decouple `_COMPONENT_TO_TOOL_NAMES` from the literal `"db_"`
  string. The map should describe **logical** capabilities, not
  hardcoded names.

### Non-Goals (explicitly out of scope)

- Making `tool_prefix` mandatory or fail-fast at toolkit
  registration time. Tracked separately in **FEAT-172**.
- Migrating the internal helper toolkit (`DatabaseAgentToolkit`) to
  use a prefix. Tracked separately in **FEAT-173**.
- Touching `AbstractToolkit` itself or its prefix-rewrite mechanism
  (`tools/toolkit.py:350-...`) — already correct and idempotent.
- Touching `EpisodicMemoryMixin._configure_episodic_memory`. The
  idempotency check added in PR #866 (mixin.py:114-121) addresses a
  different bug (same toolkit re-configuring on a second
  `configure()` call) and is unrelated to cross-toolkit collisions.
- Modifying `clients/base.py::_execute_tool` or
  `clients/google/client.py::_execute_tool`. The context-filtering
  fix already shipped in PR #866.

---

## 2. Architectural Design

### Overview

Replace the single `_COMPONENT_TO_TOOL_NAMES` map with two maps that
separate the two naming regimes:

1. `_INTERNAL_TOOLS_BY_COMPONENT` — keyed by the **exact** method
   names on `DatabaseAgentToolkit`. Lookup path is unchanged
   (`getattr(self._internal_toolkit, name, None)`).
2. `_TOOLKIT_TOOLS_BY_COMPONENT` — keyed by **logical** tool names
   *without any prefix*. Each external toolkit applies its own
   `tool_prefix` at resolution time via `tk.get_tool(...)`.

`_compute_active_tools` becomes prefix-aware: it composes
`f"{tk.tool_prefix}{tk.prefix_separator}{logical_name}"` per
attached toolkit and asks each one whether it owns that tool.
Collisions across toolkits log a warning and keep first-wins
behaviour.

**Collision-log deduplication (Q1 resolution).** Repeated calls to
`_compute_active_tools` (one per LLM turn) must not re-emit the
same collision warning. A per-agent `self._logged_collisions:
Set[Tuple[str, FrozenSet[str]]]` tracks already-reported
collisions keyed by `(full_name, frozenset(toolkit-class-names))`.
The warning message includes the current `OutputComponent` flag
to aid multi-component debugging.

**Legacy `tool_prefix=None` (Q2 resolution).** When a toolkit's
`tool_prefix` is `None`, Pass 2 falls back to looking up the
logical name directly (`tk.get_tool(logical_name)`) — graceful
degradation. The first time this fallback fires for a given
toolkit, a `DeprecationWarning` is emitted via
`warnings.warn(..., DeprecationWarning, stacklevel=2)` with a
message pointing at FEAT-172. A per-agent
`self._warned_none_prefix: Set[int]` (keyed by `id(tk)`) ensures
the deprecation fires once per toolkit instance.

### Component Diagram

```
DatabaseAgent._compute_active_tools(components)
       │
       ├── Pass 1 ─► DatabaseAgentToolkit (internal helpers)
       │              │
       │              └──► getattr(_internal_toolkit, name)
       │                   for name in _INTERNAL_TOOLS_BY_COMPONENT[…]
       │
       └── Pass 2 ─► every tk in self.toolkits
                       │
                       ├── for logical in _TOOLKIT_TOOLS_BY_COMPONENT[…]
                       │
                       └── tk.get_tool(f"{tk.tool_prefix}_{logical}")
                              │
                              └──► if already seen → log warning, skip
                                   else → append to active_tools
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit.tool_prefix` | uses (read) | Read each toolkit's declared prefix to build the fully-qualified tool name. |
| `AbstractToolkit.prefix_separator` | uses (read) | Honor the separator each toolkit declares (default `_`). |
| `AbstractToolkit.get_tool(name)` | uses (call) | Exact-name lookup. No new toolkit API required. |
| `DatabaseAgent._compute_active_tools()` | rewrites | Logic redesigned around the two new maps + prefix-aware resolution. |
| `_COMPONENT_TO_TOOL_NAMES` | replaces | Becomes two module-level constants. |

### Data Models

No new Pydantic models. Two module-level constants in
`bots/database/agent.py` replace the single existing one:

```python
# Internal helper tools (live in DatabaseAgentToolkit). Resolved via
# getattr against self._internal_toolkit, the same path as today.
_INTERNAL_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]] = {
    OutputComponent.SQL_QUERY: {
        "extract_sql_from_response",
        "extract_table_name_from_query",
    },
    OutputComponent.OPTIMIZATION_TIPS: {
        "generate_optimization_tips",
        "generate_basic_optimization_tips",
        "generate_table_specific_tips",
        "extract_performance_metrics",
    },
    OutputComponent.EXECUTION_PLAN: {
        "format_explain_plan",
        "extract_performance_metrics",
    },
    OutputComponent.SCHEMA_CONTEXT: {
        "generate_create_table_statement",
        "simplify_column_type",
        "extract_table_names_from_metadata",
        "get_schema_counts_direct",
    },
    OutputComponent.EXAMPLES: {"generate_examples"},
    OutputComponent.DATA_RESULTS: {"format_query_history"},
    # ... DOCUMENTATION etc., preserving every internal name from
    # the current _COMPONENT_TO_TOOL_NAMES (i.e. everything WITHOUT
    # the "db_" prefix today).
}

# External database-toolkit tools. Names are LOGICAL — each toolkit
# applies its own tool_prefix at resolution time. This is the map
# that drops the "db_" hardcoding.
_TOOLKIT_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]] = {
    OutputComponent.SQL_QUERY: {"generate_query", "validate_query"},
    OutputComponent.EXECUTION_PLAN: {"explain_query"},
    OutputComponent.SCHEMA_CONTEXT: {"search_schema"},
}
```

### New Public Interfaces

None. This feature is a refactor behind the existing surface.

---

## 3. Module Breakdown

### Module 1: Two-map split + prefix-aware lookup

- **Path**: `packages/ai-parrot/src/parrot/bots/database/agent.py`
- **Responsibility**:
  - Replace `_COMPONENT_TO_TOOL_NAMES` with the two new constants
    (`_INTERNAL_TOOLS_BY_COMPONENT`, `_TOOLKIT_TOOLS_BY_COMPONENT`).
    Mechanical split — every entry that lives in
    `DatabaseAgentToolkit` (no `db_` prefix today) goes into the
    internal map; entries with `db_` go into the toolkit map after
    dropping the prefix.
  - Rewrite `_compute_active_tools` so Pass 2 builds the
    fully-qualified name per toolkit and calls
    `tk.get_tool(full_name)`.
  - When `full_name` is already in `seen`, log a deduped warning
    (see "Collision logging" below) and continue (first-wins).
  - When a toolkit's `tool_prefix` is `None`, fall back to
    `tk.get_tool(logical_name)` and emit a one-time
    `DeprecationWarning` per toolkit instance.
  - Preserve the current return shape: a `list` of tool objects
    accepted by `ToolManager.register_tool`.
  - Initialise two per-agent sets in `DatabaseAgent.__init__`
    (or first-use lazy init):
    `self._logged_collisions: Set[Tuple[str, FrozenSet[str]]]`
    and `self._warned_none_prefix: Set[int]`.

  **Collision logging (Q1 resolution).** Inside Pass 2:
  ```python
  key = (full_name, frozenset({type(first_owner).__name__,
                               type(tk).__name__}))
  if key not in self._logged_collisions:
      self._logged_collisions.add(key)
      logger.warning(
          "Toolkit tool name collision: %r already exposed by %s; "
          "skipping duplicate from %s (component=%s). "
          "Toolkit order in self.toolkits determines first-wins; "
          "reorder if needed.",
          full_name, type(first_owner).__name__,
          type(tk).__name__, component.name,
      )
  ```
  Track `first_owner` per `full_name` in a local
  `Dict[str, DatabaseToolkit]` populated during Pass 2.

  **Legacy `tool_prefix=None` (Q2 resolution).** When the toolkit
  declares no prefix:
  ```python
  if tk.tool_prefix is None:
      if id(tk) not in self._warned_none_prefix:
          self._warned_none_prefix.add(id(tk))
          warnings.warn(
              f"{type(tk).__name__} has tool_prefix=None; resolving "
              f"tools by logical name. This is a transitional escape "
              f"hatch and will be rejected at configure() time once "
              f"FEAT-172 ships.",
              DeprecationWarning, stacklevel=2,
          )
      full_name = logical_name
  else:
      full_name = f"{tk.tool_prefix}{tk.prefix_separator}{logical_name}"
  tool = tk.get_tool(full_name)
  ```

### Module 2: Update docstrings and inline comments

- **Path**: `packages/ai-parrot/src/parrot/bots/database/agent.py`
- **Responsibility**:
  - The docstring on `_compute_active_tools` (currently at
    `agent.py:628-649`) references "`db_*` after `tool_prefix` is
    applied". Reword to "each toolkit's own `tool_prefix` is applied
    at resolution time".
  - Add a top-of-section comment block above
    `_TOOLKIT_TOOLS_BY_COMPONENT` explaining that names are LOGICAL
    and each toolkit applies its own prefix.
- **Depends on**: Module 1 (cosmetic only — must reflect new code).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_compute_active_tools_default_prefix` | Module 1 | `DatabaseAgent` with a single `PostgresToolkit(tool_prefix="db")` exposes `db_search_schema`, `db_explain_query`, etc. for the relevant components. Regression test pinning current behaviour. |
| `test_compute_active_tools_custom_prefix` | Module 1 | `DatabaseAgent` with a `MockToolkit(tool_prefix="mk")` exposing `mk_search_schema` is correctly surfaced when `OutputComponent.SCHEMA_CONTEXT` is active. Today this returns no tools — would catch the bug. |
| `test_compute_active_tools_two_toolkits_distinct_prefixes` | Module 1 | A `DatabaseAgent` with both `PostgresToolkit(tool_prefix="db")` and `MockToolkit(tool_prefix="mk")` exposes both `db_search_schema` AND `mk_search_schema` simultaneously. |
| `test_compute_active_tools_logs_collision` | Module 1 | Two toolkits with the same `tool_prefix` that both expose `search_schema` — `_compute_active_tools` logs a warning containing both class names AND the current `OutputComponent` flag; first toolkit's tool is kept. |
| `test_collision_warning_deduplicated_across_turns` | Module 1 | Call `_compute_active_tools` three times with the same colliding setup — the warning is logged exactly once. The set `_logged_collisions` grows by one entry, not three. |
| `test_none_prefix_graceful_resolution` | Module 1 | A toolkit with `tool_prefix=None` exposing `search_schema` is resolved via `tk.get_tool("search_schema")` and surfaces correctly when `OutputComponent.SCHEMA_CONTEXT` is active. |
| `test_none_prefix_emits_deprecation_warning_once` | Module 1 | First call to `_compute_active_tools` with a `tool_prefix=None` toolkit emits `DeprecationWarning` mentioning FEAT-172; the second call for the same toolkit emits nothing. |
| `test_no_regression_sql_analyst_path` | Module 1 | End-to-end: `sql_analyst` plugin's exact runtime config (one `PostgresToolkit` with `tool_prefix="db"`) yields the same tool surface before and after this feature. Pin the surface in the test. |

### Integration Tests

| Test | Description |
|---|---|
| `test_databaseagent_multi_toolkit_runtime` | Spin up a `DatabaseAgent` with two toolkits (Postgres + a Mock implementing the `DatabaseToolkit` interface), drive `_compute_active_tools` with every `OutputComponent` flag combination, assert both toolkits' tools appear in the merged set. |

### Test Data / Fixtures

```python
# tests/unit/bots/database/conftest.py (new or extended)
import pytest
from typing import List
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.tools.toolkit import tool

class MockDatabaseToolkit(DatabaseToolkit):
    """Minimal stub: declares tool_prefix and exposes one tool."""
    tool_prefix: str = "mk"
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

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] All new unit tests pass
      (`pytest packages/ai-parrot/tests/unit/bots/database/test_compute_active_tools.py -v`).
- [ ] `test_no_regression_sql_analyst_path` passes — the
      `sql_analyst` tool surface is byte-identical before and after.
- [ ] Manual smoke: in a working sql_analyst session
      (QuerySource Query Executor), the LLM still emits SQL for
      "join categories with products" with no regression.
- [ ] No breaking changes to any toolkit's public API.
- [ ] No silent collision branches remain — every collision logs a
      warning. (Fail-fast at configure-time is **FEAT-172**, not
      this feature.)
- [ ] Collision warnings are deduplicated across `_compute_active_tools`
      calls via `self._logged_collisions`; the same `(full_name,
      toolkits)` pair logs once per agent lifetime.
- [ ] Collision warning message includes the current
      `OutputComponent` flag.
- [ ] Toolkits with `tool_prefix=None` resolve via
      `tk.get_tool(logical_name)` (graceful) and emit a one-time
      `DeprecationWarning` mentioning FEAT-172.
- [ ] `_compute_active_tools` no longer references the literal
      string `"db_"` anywhere. `grep '"db_' packages/ai-parrot/src/parrot/bots/database/agent.py`
      after the change matches **zero lines**.
- [ ] Documentation: a short comment block above
      `_TOOLKIT_TOOLS_BY_COMPONENT` explains that names are
      LOGICAL and each toolkit applies its own prefix at
      resolution time.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified by reading the repository at HEAD of `dev` on 2026-05-14.

### Verified Imports

```python
# bots/database/agent.py (existing, top of file)
from typing import Any, Dict, List, Optional, Set
from parrot.bots.database.toolkits._internal import DatabaseAgentToolkit  # verified
from parrot.bots.database.toolkits.base import DatabaseToolkit   # verified
from parrot.bots.database.models import OutputComponent                  # verified
```

### Existing Class Signatures

```python
# tools/toolkit.py:242-245
class AbstractToolkit:
    tool_prefix: Optional[str] = None       # line 242
    prefix_separator: str = "_"              # line 245

    def get_tool(self, name: str) -> Optional[AbstractTool]:  # line 433
        ...

    def list_tool_names(self) -> List[str]:  # line 448
        ...

# bots/database/toolkits/base.py:93
class DatabaseToolkit(AbstractToolkit):
    tool_prefix: str = "db"                  # line 93 (overrides Optional[str] with the concrete default)

# bots/database/toolkits/_internal.py:45
class DatabaseAgentToolkit(AbstractToolkit):
    # tool_prefix is NOT overridden — inherits None.
    # This feature does NOT change that. See FEAT-173 for the prefix migration.

# bots/database/agent.py:628
class DatabaseAgent(...):
    def _compute_active_tools(self, components: OutputComponent) -> List[Any]:
        # Existing surface; body rewritten by Module 1.
```

### Existing Module-Level Constant (REPLACED)

```python
# bots/database/agent.py:43-77 (current — REPLACED by this feature)
_COMPONENT_TO_TOOL_NAMES: Dict[OutputComponent, Set[str]] = {
    OutputComponent.SQL_QUERY: {
        "extract_sql_from_response",
        "extract_table_name_from_query",
        "db_generate_query",
        "db_validate_query",
    },
    OutputComponent.OPTIMIZATION_TIPS: {
        "generate_optimization_tips",
        "generate_basic_optimization_tips",
        "generate_table_specific_tips",
        "extract_performance_metrics",
    },
    OutputComponent.EXECUTION_PLAN: {
        "format_explain_plan",
        "extract_performance_metrics",
        "db_explain_query",
    },
    OutputComponent.SCHEMA_CONTEXT: {
        "generate_create_table_statement",
        "simplify_column_type",
        "extract_table_names_from_metadata",
        "get_schema_counts_direct",
        "db_search_schema",
    },
    OutputComponent.EXAMPLES: {"generate_examples"},
    OutputComponent.DATA_RESULTS: {"format_query_history"},
    OutputComponent.DOCUMENTATION: {...},
}
```

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| `_compute_active_tools` Pass 2 | `AbstractToolkit.get_tool` | method call | `tools/toolkit.py:433` |
| `_compute_active_tools` Pass 2 | `AbstractToolkit.tool_prefix` | attribute read | `tools/toolkit.py:242`, `bots/database/toolkits/base.py:93` |
| `_compute_active_tools` Pass 2 | `AbstractToolkit.prefix_separator` | attribute read | `tools/toolkit.py:245` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractToolkit.tools()`~~ — does not exist as a list-returning
  method. Use `list_tool_names()` (returns `List[str]`) or
  `get_tools_sync()` (returns `List[AbstractTool]`) if iteration is
  ever needed; this feature does not need either — `get_tool(name)`
  is sufficient.
- ~~`AbstractToolkit.iter_tools()`~~ — does not exist.
- ~~`DatabaseAgent.add_toolkit()`~~ — does not exist. Toolkits are
  passed via `__init__(toolkits=...)` and finalized in `configure()`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `logger.warning` (not `error`, not `print`) for runtime
  collision logging. Runtime collisions must NOT crash the agent —
  they should surface in logs only. Fail-fast at configure-time is
  the scope of FEAT-172.
- Preserve the existing comment on `_COMPONENT_TO_TOOL_NAMES` that
  explains the relationship to `OutputComponent` — adapt it to the
  two new maps.
- Keep `_compute_active_tools` synchronous (no `async`) — the
  existing signature is `def`, not `async def`.

### Known Risks / Gotchas

- **Toolkit instantiation order matters for first-wins**.
  `self.toolkits` is a list, so `_compute_active_tools` walks them in
  insertion order. The collision warning's "first-wins" semantics
  depend on that order. Document this explicitly in the warning
  message so operators can reorder if needed.
- **`prefix_separator` edge cases**. Default is `"_"`, but a
  toolkit could set it to `""` or `"."`. The full-name builder must
  honor whatever the toolkit declares. Use `f"{prefix}{separator}{name}"`
  rather than hardcoding `"_"`.
- **`tool_prefix` with embedded prefix**. `AbstractToolkit`
  documents (lines 234-237) that if a method name already starts
  with `{prefix}{separator}`, the prefix is NOT re-applied
  (idempotent rewrite). The new resolution code must trust
  `tk.get_tool(...)` to do the right lookup — do not reconstruct
  names from `list_tool_names()` results.

### External Dependencies

None.

---

## 8. Open Questions

> Both open questions are resolved. Kept here with the resolutions
> as the audit trail.

- [x] **Q1 — Collision warning content** — *Resolved 2026-05-15*:
      **Include the current `OutputComponent` flag in the warning**
      and dedupe via `self._logged_collisions:
      Set[Tuple[str, FrozenSet[str]]]` keyed by `(full_name,
      frozenset(toolkit-class-names))`. The same `(full_name,
      toolkits)` pair logs at most once per agent lifetime. The
      colliding toolkit's class name (`type(tk).__name__`) and the
      first-owner class name are both included so operators can
      reorder `self.toolkits` if needed.
- [x] **Q2 — `tool_prefix=None` handling** — *Resolved 2026-05-15*:
      **Graceful degradation + one-time `DeprecationWarning` per
      toolkit instance**. When `tk.tool_prefix is None`, fall back
      to `tk.get_tool(logical_name)`. The first time the fallback
      fires for a given toolkit (tracked via
      `self._warned_none_prefix: Set[int]` keyed by `id(tk)`),
      emit a `DeprecationWarning` pointing at FEAT-172. This
      keeps existing legacy setups working through the FEAT-171
      → FEAT-172 bridge without silent breakage.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-14 | Juan Francisco Ruffato | Initial draft after PR #866 review feedback from Jesús Lara. |
| 0.2 | 2026-05-14 | Juan Francisco Ruffato | Slimmed scope to Module 1 only. Modules 2 & 3 extracted to FEAT-172 and FEAT-173. |
| 0.3 | 2026-05-15 | Juan Francisco Ruffato | Resolved Q1 (collision warning dedupe + component flag) and Q2 (graceful `tool_prefix=None` + one-time DeprecationWarning). Status: draft → approved. |

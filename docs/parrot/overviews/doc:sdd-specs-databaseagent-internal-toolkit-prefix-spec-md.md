---
type: Wiki Overview
title: 'Feature Specification: Internal Toolkit Prefix Migration (`int_`)'
id: doc:sdd-specs-databaseagent-internal-toolkit-prefix-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-172 (`databaseagent-mandatory-prefix-collision`). Both must be
relates_to:
- concept: mod:parrot.bots.database.toolkits._internal
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Internal Toolkit Prefix Migration (`int_`)

**Feature ID**: FEAT-173
**Date**: 2026-05-14
**Author**: Juan Francisco Ruffato
**Status**: draft
**Target version**: next

**Depends on**: FEAT-171 (`databaseagent-prefix-aware-tools`) AND
FEAT-172 (`databaseagent-mandatory-prefix-collision`). Both must be
merged first. This feature is the cleanup pass that brings the
internal helper toolkit under the same naming model as external
toolkits.

---

## 1. Motivation & Business Requirements

### Problem Statement

After FEAT-171 and FEAT-172, `DatabaseAgent._compute_active_tools`
still has an asymmetry: it resolves internal helpers
(`DatabaseAgentToolkit`'s 16 string-manipulation / formatting tools)
via `getattr(self._internal_toolkit, name, None) + _is_tool` check,
while every external toolkit goes through `tk.get_tool(name)`. Two
different resolution paths for what is conceptually the same thing
(*"give me the tool object for this name"*).

This asymmetry has three concrete costs:

1. **Maintenance**. Anyone reading `_compute_active_tools` has to
   keep two mental models. Bug reports about "this tool isn't being
   exposed" require checking which path applies.
2. **The internal toolkit is the only `AbstractToolkit` subclass in
   `bots/database/` that does not declare a `tool_prefix`**. After
   FEAT-172 makes prefixes mandatory for `DatabaseToolkit`,
   the internal toolkit becomes the lone hold-out — it inherits
   directly from `AbstractToolkit`, so FEAT-172's check does not
   force it. But the inconsistency is bad signal.
3. **Two name spaces, one set of components**. Today, the same map
   `_COMPONENT_TO_TOOL_NAMES` (replaced by two maps in FEAT-171)
   carries names from both regimes. A future reader cannot tell, by
   looking at the map alone, which entry resolves through which
   path. With this feature, the maps become a clean split:
   *"every entry resolves via `tk.get_tool` with its toolkit's
   own prefix."*

This is purely a cleanup feature. No new behaviour for the LLM.
But it pays off in the next time anyone touches this code.

### Goals

- Declare `tool_prefix = "int"` (with `prefix_separator = "_"`) on
  `DatabaseAgentToolkit`. Its 16 tools will register as
  `int_extract_sql_from_response`, `int_generate_examples`, etc.
- Update `_INTERNAL_TOOLS_BY_COMPONENT` (introduced in FEAT-171) so
  it keeps the **logical** names (no `int_` prefix). The prefix is
  applied at resolution time, same as for any other toolkit.
- Collapse `_compute_active_tools` into a single resolution loop:
  iterate `[self._internal_toolkit, *self.toolkits]`, call
  `tk.get_tool(f"{tk.tool_prefix}_{logical}")` for every logical
  name in the active component set.
- Remove the legacy `getattr + _is_tool` lookup path.

### Non-Goals (explicitly out of scope)

- Renaming any of the 16 internal helper methods. They keep their
  current Python names (`extract_sql_from_response`, etc.). Only
  the **registered tool name** changes (gets prefixed).
- Changing the surface of `DatabaseAgentToolkit` beyond adding the
  two class attributes. No new methods, no removals.
- Promoting `int_` as a convention for other internal toolkits in
  the parrot codebase. This feature only touches `bots/database/`.
  If other internal toolkits exist (e.g. inside `forms/`,
  `memory/`), they keep their current behaviour.

---

## 2. Architectural Design

### Overview

Two coordinated edits:

1. **`_internal.py`**: add `tool_prefix` and `prefix_separator`
   class attributes to `DatabaseAgentToolkit`. The 16 existing
   `@tool`-decorated methods are unchanged; `AbstractToolkit`'s
   idempotent prefix-rewrite mechanism will turn them into
   `int_<method>` automatically.
2. **`agent.py`**: rewrite `_compute_active_tools` as a single loop
   over all toolkits (internal + externals), using uniform
   `tk.get_tool(...)` resolution. Drop the
   `_INTERNAL_TOOLS_BY_COMPONENT` vs `_TOOLKIT_TOOLS_BY_COMPONENT`
   distinction at the call-site — the maps can merge into one
   `_TOOLS_BY_COMPONENT` since both regimes now share the same
   semantics.

### Component Diagram

```
DatabaseAgent._compute_active_tools(components)
       │
       ▼
for tk in [self._internal_toolkit, *self.toolkits]:
       │
       ├── for logical in _TOOLS_BY_COMPONENT[active components]:
       │
       └── tk.get_tool(f"{tk.tool_prefix}{tk.prefix_separator}{logical}")
              │
              └──► first non-None wins; subsequent matches log warning
                   (defensive fallback from FEAT-171)
```

Before this feature there were two passes (internal via `getattr`,
external via `get_tool`); after, there is one.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatabaseAgentToolkit` | extends | Adds two class attributes. |
| `AbstractToolkit._generate_tools()` | uses | Already applies `tool_prefix` to method names. We rely on that mechanism — no change to the toolkit core. |
| `DatabaseAgent._compute_active_tools()` | rewrites | Pass 1 (getattr) removed; resolution unified through `get_tool`. |
| `DatabaseAgent.configure()` | uses (read) | Still creates `self._internal_toolkit = DatabaseAgentToolkit()`; no behaviour change at configure time. |
| Two maps from FEAT-171 | merges | `_INTERNAL_TOOLS_BY_COMPONENT` + `_TOOLKIT_TOOLS_BY_COMPONENT` → single `_TOOLS_BY_COMPONENT`. |

### Data Models

None. Modifying class attributes and a module-level constant only.

### New Public Interfaces

None.

### Behaviour-Visible Change to External Observers

The **registered tool names** for the 16 internal helpers change
from bare names (`extract_sql_from_response`) to prefixed names
(`int_extract_sql_from_response`). Anything that addresses these
tools by their registered name must update.

The exhaustive list (from `_internal.py`, verified at HEAD of
`dev` on 2026-05-14):

| Before | After |
|---|---|
| `extract_sql_from_response` | `int_extract_sql_from_response` |
| `extract_table_name_from_query` | `int_extract_table_name_from_query` |
| `extract_table_names_from_metadata` | `int_extract_table_names_from_metadata` |
| `extract_performance_metrics` | `int_extract_performance_metrics` |
| `generate_optimization_tips` | `int_generate_optimization_tips` |
| `generate_basic_optimization_tips` | `int_generate_basic_optimization_tips` |
| `generate_table_specific_tips` | `int_generate_table_specific_tips` |
| `generate_examples` | `int_generate_examples` |
| `generate_create_table_statement` | `int_generate_create_table_statement` |
| `simplify_column_type` | `int_simplify_column_type` |
| `format_explain_plan` | `int_format_explain_plan` |
| `format_query_history` | `int_format_query_history` |
| `format_as_text` | `int_format_as_text` |
| `get_schema_counts_direct` | `int_get_schema_counts_direct` |
| (+ any others present in `_internal.py`) | … |

LLM-visible prompts that mention these tool names will need
updating; see Module 3 below.

---

## 3. Module Breakdown

### Module 1: Internal toolkit declares `tool_prefix`

- **Path**: `packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py`
- **Responsibility**:
  - Add `tool_prefix: str = "int"` and
    `prefix_separator: str = "_"` as class attributes on
    `DatabaseAgentToolkit` (line 45).
  - No other changes. The `@tool`-decorated methods keep their
    Python names. `AbstractToolkit._generate_tools` applies the
    prefix on first generation.
- **Depends on**: FEAT-171 + FEAT-172 already on `dev`.

### Module 2: Unify `_compute_active_tools` resolution

- **Path**: `packages/ai-parrot/src/parrot/bots/database/agent.py`
- **Responsibility**:
  - Merge `_INTERNAL_TOOLS_BY_COMPONENT` and
    `_TOOLKIT_TOOLS_BY_COMPONENT` into a single
    `_TOOLS_BY_COMPONENT` constant containing logical names only.
    Internal helpers and external tools live together; the
    `tool_prefix` distinguishes them at resolution.
  - Rewrite `_compute_active_tools` body:
    ```python
    if self._internal_toolkit is None:
        return []
    logical_names = set()
    for flag, names in _TOOLS_BY_COMPONENT.items():
        if flag in components:
            logical_names |= names
    tools, seen = [], set()
    for tk in [self._internal_toolkit, *self.toolkits]:
        prefix, sep = tk.tool_prefix, tk.prefix_separator
        for logical in logical_names:
            full = f"{prefix}{sep}{logical}"
            if full in seen:
                self.logger.warning(...)   # defensive
                continue
            t = tk.get_tool(full)
            if t is not None:
                tools.append(t)
                seen.add(full)
    return tools
    ```
  - Remove the legacy `getattr(self._internal_toolkit, name, None)` +
    `_is_tool` path entirely.
- **Depends on**: Module 1.

### Module 3: Update LLM-facing references to the renamed tools

- **Path**: search across `packages/ai-parrot/src/parrot/bots/database/`
  for prompts, backstories, or system-prompt fragments that name
  any of the 16 internal helpers by their bare (unprefixed) name.
- **Responsibility**:
  - Grep for each old name listed in Section 2 (table). Update
    every reference to the new `int_*` form.
  - The PromptBuilder / system-prompt construction
    (`agent.py:_build_database_prompt_builder`, line 104) is the
    most likely place. Inspect every `{tool_name}` interpolation.
  - Update any docstrings or developer-facing docs that name the
    tools — these are read by humans, not the LLM, but staleness
    is bad signal.
- **Depends on**: Module 1 (the rename must already be in effect
  before the docs catch up).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_internal_toolkit_registers_int_prefix` | Module 1 | Instantiate `DatabaseAgentToolkit()`, call `list_tool_names()`, assert every name starts with `int_`. |
| `test_compute_active_tools_resolves_internal_via_prefix` | Module 2 | `DatabaseAgent` with `OutputComponent.SQL_QUERY` flag returns the bound method for `int_extract_sql_from_response`. The returned object is the same one that today's `getattr + _is_tool` path would return. |
| `test_compute_active_tools_unified_single_pass` | Module 2 | Mock both `self._internal_toolkit.get_tool` and a `MockDatabaseToolkit.get_tool`; assert the lookup sequence is `[int_<name>, mk_<name>]` (single iteration over `[internal, *toolkits]`). |
| `test_no_regression_sql_analyst_surface_after_feat_173` | All | Pin the full tool surface for the `sql_analyst` config. The surface IS different from pre-FEAT-173 (names are now `int_*`), but it must equal the new pinned surface byte-for-byte. |
| `test_legacy_getattr_path_removed` | Module 2 | Static analysis check: `grep "getattr(self._internal_toolkit" packages/ai-parrot/src/parrot/bots/database/agent.py` returns zero hits. |

### Integration Tests

| Test | Description |
|---|---|
| `test_sql_analyst_e2e_after_feat_173` | Run the canonical "join categories with products" prompt against a sql_analyst session. The LLM may now call `int_*` tools by their new names; assert the response is functionally equivalent (SQL produced, no tool-not-found errors in logs). |
| `test_prompt_construction_uses_new_names` | Module 3 | After `agent.configure()`, the system prompt produced by `PromptBuilder` contains `int_*` references (or no references at all, if the prompt was changed to not name tools explicitly). Zero references to the old bare names. |

### Test Data / Fixtures

Extend the FEAT-171 fixtures with the renamed expected names.

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] All new unit tests pass.
- [ ] `test_sql_analyst_e2e_after_feat_173` passes — sql_analyst
      produces a functionally equivalent SQL response after the
      rename.
- [ ] `grep "getattr(self._internal_toolkit" packages/ai-parrot/src/parrot/bots/database/agent.py`
      matches **zero lines**.
- [ ] `grep -E "\"(extract_sql_from_response|generate_examples|format_explain_plan|...)\""`
      across `packages/ai-parrot/src/parrot/bots/database/` matches
      **zero lines** outside `_internal.py` itself (where the method
      names live). All references go through the prefixed form.
- [ ] The two-map split from FEAT-171 is collapsed back to a single
      `_TOOLS_BY_COMPONENT` map containing logical names.
- [ ] `DatabaseAgentToolkit.tool_prefix == "int"` and
      `DatabaseAgentToolkit.prefix_separator == "_"`.
- [ ] No unit test asserts the bare (pre-prefix) form of any
      internal tool name. Search test files for the same set of
      strings.
- [ ] Documentation: a comment block above
      `DatabaseAgentToolkit` (in `_internal.py`) explains the
      prefix choice (`int` = internal helpers, not exposed to
      direct user query — separated from `db_*` toolkit tools).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified by reading the repository at HEAD of `dev` on 2026-05-14.

### Verified Imports

```python
# bots/database/toolkits/_internal.py (existing)
from parrot.tools.toolkit import AbstractToolkit  # verified: tools/toolkit.py
# `@tool` decorator imported from the same module — verified

# bots/database/agent.py (existing)
from parrot.bots.database.toolkits._internal import DatabaseAgentToolkit  # verified
```

### Existing Class Signatures

```python
# tools/toolkit.py:242-245
class AbstractToolkit:
    tool_prefix: Optional[str] = None       # line 242 — overridden by this feature on DatabaseAgentToolkit
    prefix_separator: str = "_"              # line 245 — default; this feature accepts the default

    def get_tool(self, name: str) -> Optional[AbstractTool]:  # line 433
        ...

    def list_tool_names(self) -> List[str]:  # line 448
        ...

# bots/database/toolkits/_internal.py:45
class DatabaseAgentToolkit(AbstractToolkit):
    # Currently NO tool_prefix override (inherits None).
    # This feature adds:
    #     tool_prefix: str = "int"
    #     prefix_separator: str = "_"
    # No other attribute changes.
```

### Existing Module-Level Constants (REPLACED after this feature)

After FEAT-171, `bots/database/agent.py` contains:

```python
_INTERNAL_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]] = {...}
_TOOLKIT_TOOLS_BY_COMPONENT:  Dict[OutputComponent, Set[str]] = {...}
```

This feature merges them into a single `_TOOLS_BY_COMPONENT` with
logical (unprefixed) names. The internal-only entries that today
live in `_INTERNAL_TOOLS_BY_COMPONENT` move into the merged map
without their `int_` prefix.

### Integration Points

| New Code | Connects To | Via | Verified At |
|---|---|---|---|
| Single resolution loop | `AbstractToolkit.get_tool` | method call | `tools/toolkit.py:433` |
| `_TOOLS_BY_COMPONENT` lookup | `DatabaseAgentToolkit` | indirectly via `get_tool` | `bots/database/toolkits/_internal.py:45` |
| Prompt builder | `OutputComponent` flags + new tool names | string interpolation | `bots/database/agent.py:104` |

### Does NOT Exist (Anti-Hallucination)

- ~~`DatabaseAgentToolkit.set_prefix()`~~ — does not exist. Set
  `tool_prefix` as a class attribute (declarative), not via a
  setter.
- ~~`AbstractToolkit.rename_tool()`~~ — does not exist. The rename
  is implicit through `_generate_tools` applying the prefix.
- ~~`OutputComponent.INTERNAL`~~ — does not exist. There is no
  separate component flag for internal-only tools; internal
  helpers are gated by the same `OutputComponent.*` flags as
  external toolkit tools.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Trust `AbstractToolkit._generate_tools` to apply the prefix
  idempotently. Do NOT manually concatenate `int_` anywhere in
  `_internal.py` — the framework handles it.
- The order of toolkits in the unified loop is
  `[self._internal_toolkit, *self.toolkits]`. Internal helpers
  resolve first. This preserves first-wins semantics consistent
  with FEAT-171.
- Use a single set `seen: set[str]` for the full-name
  deduplication. After FEAT-172, this set should never grow past
  unique names — the defensive warning from FEAT-171 is the only
  reason it exists at all.

### Known Risks / Gotchas

- **Prompt staleness**. The system prompt may name internal tools
  literally (`"Use extract_sql_from_response to..."`). Module 3
  must catch every such reference. Missing one means the LLM gets
  told to call a tool whose registered name is now `int_*`, and
  the tool call fails. Recommend exhaustive grep before merging.
- **Test fragility**. Many existing unit tests likely assert the
  bare tool names. Plan for collateral test churn proportional to
  the number of internal-tool references in tests.
- **Documentation drift**. The README / docs in
  `packages/ai-parrot/docs/` may name these tools. Audit docs as
  part of Module 3 even though they don't affect runtime.
- **Re-running migrations**. If a deployment has cached the old
  tool names somewhere (e.g. Redis registry, vector store
  metadata), redeployment may need a cache flush. Unlikely
  scenario but worth mentioning in the PR notes.

### External Dependencies

None.

---

## 8. Open Questions

- [ ] Is `"int"` the right prefix? Alternatives: `"helper"`,
      `"hlp"`, `"agent"`. `"int"` is short and matches the existing
      file name (`_internal.py`). — *Owner: Jesús Lara*
- [ ] After this feature lands, should we remove the
      `DatabaseAgentToolkit` from the `OutputComponent.SCHEMA_CONTEXT`
      set (since `get_schema_counts_direct` is the only internal
      helper that touches the DB)? Tangential question, not
      blocking. — *Owner: implementer*
- [ ] Should the prompt builder be refactored to enumerate tools
      from `_compute_active_tools` rather than naming them
      literally? That would make this kind of rename trivial in
      the future. Out of scope here but worth a follow-up. —
      *Owner: Jesús Lara*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-14 | Juan Francisco Ruffato | Initial draft. Extracted from the original FEAT-171 spec (Module 3). |

---
type: Wiki Overview
title: 'Feature Specification: Skills Tools → Toolkit Unification'
id: doc:sdd-specs-skills-tools-toolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The skills subsystem (`parrot/skills/`) exposes its agent-facing tools as
  a
relates_to:
- concept: mod:parrot.memory.skills.tools
  rel: mentions
- concept: mod:parrot.skills.models
  rel: mentions
- concept: mod:parrot.skills.store
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Skills Tools → Toolkit Unification

**Feature ID**: FEAT-207
**Date**: 2026-05-29
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The skills subsystem (`parrot/skills/`) exposes its agent-facing tools as a
loose collection of one-class-per-tool `AbstractTool` subclasses, each wired
individually inside `create_skill_tools()` and (for the file-based ones) again
inside `SkillRegistryMixin`. This produced two concrete pains:

1. **Duplicated, drift-prone wiring.** `LoadSkillTool` was instantiated in two
   places (the mixin's FEAT-188 path *and* `create_skill_tools`), while
   `read_skill_asset` / `save_learned_skill` were never registered through the
   mixin path at all — an inconsistency that shipped silently.
2. **Repeated dependency injection.** Every tool re-receives the same
   `SkillFileRegistry` (or DB-backed `SkillRegistry`) in its own `__init__`.
   There is no single place that owns the shared dependency.

AI-Parrot's own guidance (`CLAUDE.md` → "Toolkit Pattern: Use
`AbstractToolkit` for complex tool collections") already prescribes the fix:
group related tools that share a dependency into a toolkit initialized once.

### Goals

- Replace the file-based skill tools with a single **`SkillFileToolkit`**
  initialized once with the shared `SkillFileRegistry`. *(Already implemented
  on this branch — see Module 1.)*
- Introduce **`SkillRegistryToolkit`** that groups the DB-backed skill tools
  (`search_skills`, `read_skill`, `list_skills`, `document_skill`,
  `update_skill`) behind one toolkit initialized with the shared
  `SkillRegistry` store + `agent_id`.
- Reduce **`create_skill_tools()`** to simply instantiating the two toolkits
  and concatenating their `get_tools()`.
- Preserve every existing tool **name** and argument **schema** (rich
  `Field(description=...)`), so the `<available_skills>` prompt layer, the
  trigger middleware, and existing agents keep working unchanged.

### Non-Goals (explicitly out of scope)

- No change to the on-disk skill formats, the two-tier prompt design, or the
  `SkillRegistry` store / `SkillFileRegistry` internals.
- No change to `parrot.memory.skills.tools` (a separate module with its own
  `SaveLearnedSkillTool`).
- No new agent-facing capabilities beyond what the existing tools already do.

---

## 2. Architectural Design

### Overview

Two cohesive toolkits, each owning one registry dependency, replace seven
standalone tool classes. `create_skill_tools()` becomes a thin factory.

### Component Diagram

```
create_skill_tools(registry, agent_id, include_write_tools, file_registry, learned_dir)
        │
        ├──→ SkillRegistryToolkit(registry, agent_id, include_write_tools)
        │         └─ get_tools() → [search_skills, read_skill, list_skills,
        │                           document_skill*, update_skill*]   (* write-only)
        │
        └──→ SkillFileToolkit(file_registry, learned_dir)            [Module 1 — done]
                  └─ get_tools() → [load_skill, read_skill_asset,
                                    save_learned_skill†]              († needs learned_dir)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | Both toolkits subclass it; public async methods → tools |
| `@tool_schema` decorator | uses | Attaches the existing `*Args` schemas to methods (rich descriptions) |
| `SkillRegistry` (store) | injected | Shared by all `SkillRegistryToolkit` methods |
| `SkillFileRegistry` | injected | Shared by all `SkillFileToolkit` methods |
| `SkillRegistryMixin._add_skill_tools` | calls | Uses `create_skill_tools()` (DB toolkit) |
| `SkillRegistryMixin._configure_skill_file_registry` | calls | Registers `SkillFileToolkit.get_tools()` (FEAT-188 path) |

### New Public Interfaces

```python
class SkillRegistryToolkit(AbstractToolkit):
    def __init__(self, registry: SkillRegistry, agent_id: str,
                 include_write_tools: bool = True, **kwargs) -> None: ...

    @tool_schema(SkillSearchArgs)
    async def search_skills(self, query: str, category: Optional[str] = None,
                            max_results: int = 5) -> ToolResult: ...

    @tool_schema(ReadSkillToolArgs)
    async def read_skill(self, skill_id: str,
                         version: Optional[int] = None) -> ToolResult: ...

    async def list_skills(self) -> ToolResult: ...            # no args

    @tool_schema(DocumentSkillArgs)                            # write-only
    async def document_skill(self, name: str, description: str, content: str,
                             category: str = "general", tags=None,
                             triggers=None, related_tools=None) -> ToolResult: ...

    @tool_schema(UpdateSkillArgs)                              # write-only
    async def update_skill(self, skill_id: str, content: str,
                           commit_message: str = "", name=None,
                           description=None) -> ToolResult: ...
```

`include_write_tools=False` excludes `document_skill` + `update_skill` via the
toolkit's `exclude_tools` mechanism (set in `__init__`).

---

## 3. Module Breakdown

### Module 1: `SkillFileToolkit` (file-based) — ✅ DONE on this branch
- **Path**: `packages/ai-parrot/src/parrot/skills/tools.py`
- **Responsibility**: Unify `load_skill`, `read_skill_asset`,
  `save_learned_skill` behind one toolkit sharing `SkillFileRegistry`.
- **Status**: Implemented and committed (`recover: SkillFileToolkit …`),
  61 skills tests green. Listed here for completeness; no further work.

### Module 2: `SkillRegistryToolkit` (DB-backed) — ✅ DONE on this branch
- **Path**: `packages/ai-parrot/src/parrot/skills/tools.py`
- **Responsibility**: Replace `SearchSkillsTool`, `ReadSkillTool`,
  `ListSkillsTool`, `DocumentSkillTool`, `UpdateSkillTool` with one toolkit
  whose public methods carry the existing `_execute` bodies verbatim.
- **Depends on**: existing `SkillRegistry` store API, `@tool_schema`.

### Module 3: `create_skill_tools()` simplification + exports — ✅ DONE on this branch
- **Path**: `packages/ai-parrot/src/parrot/skills/tools.py`,
  `packages/ai-parrot/src/parrot/skills/__init__.py`
- **Responsibility**: Reduce `create_skill_tools()` to instantiating the two
  toolkits; update `__init__.py` to export `SkillRegistryToolkit` and drop the
  removed standalone classes. Keep the `*Args` models exported.
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_search_skills_*` | 2 | search returns formatted summary + metadata; empty-result path |
| `test_read_skill_*` | 2 | reads by id; KeyError → error result |
| `test_list_skills_*` | 2 | groups by category; empty path; no-arg schema |
| `test_document_skill` | 2 | uploads via registry; returns version metadata |
| `test_update_skill` | 2 | new version preserving history; not-found → error |
| `test_write_tools_excluded` | 2 | `include_write_tools=False` hides document/update |
| `test_registry_toolkit_tool_names` | 2 | `get_tools()` exposes the expected 5 (or 3) names |
| `test_create_skill_tools_*` | 3 | factory returns union of both toolkits' tools with correct names |

### Integration Tests
| Test | Description |
|---|---|
| `test_skill_registry_mixin` (existing) | mixin still registers file tools (already green) |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_registry():
    """Async-mock SkillRegistry exposing search_skills/read_skill/list_skills/upload_skill."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `SkillRegistryToolkit` exposes `search_skills`, `read_skill`,
      `list_skills`, `document_skill`, `update_skill` with the original tool
      names and rich arg schemas.
- [ ] `include_write_tools=False` excludes `document_skill` + `update_skill`.
- [ ] `create_skill_tools()` returns the same set of tool **names** as before
      for equivalent arguments (no behavioural regression for agents).
- [ ] Standalone DB-tool classes removed; `__init__.py` exports
      `SkillRegistryToolkit` (and keeps `*Args` models). No dangling imports.
- [ ] All skills unit + integration tests pass against the worktree source.
- [ ] No breaking change to tool names, schemas, or `ToolResult` shapes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit          # verified: tools/toolkit.py:191
from parrot.tools.decorators import tool_schema            # verified: tools/decorators.py:37
from parrot.tools.abstract import AbstractTool, ToolResult # verified: tools/abstract.py:46
from parrot.skills.store import SkillRegistry              # verified: skills/store.py
from parrot.skills.models import (                          # verified: skills/models.py
    SkillCategory, SearchSkillArgs, ReadSkillArgs,
)
```

### Existing Class Signatures (to be folded into SkillRegistryToolkit)
```python
# packages/ai-parrot/src/parrot/skills/tools.py  (current standalone classes)
class SearchSkillsTool(AbstractTool):   # name="search_skills", args=SkillSearchArgs (local)
    async def _execute(self, query, category=None, max_results=5) -> ToolResult  # :221
class ReadSkillTool(AbstractTool):      # name="read_skill", args=ReadSkillToolArgs (local)
    async def _execute(self, skill_id, version=None) -> ToolResult               # :304
class ListSkillsTool(AbstractTool):     # name="list_skills", NO args_schema
    async def _execute(self) -> ToolResult                                       # :352
class DocumentSkillTool(AbstractTool):  # name="document_skill", args=DocumentSkillArgs, needs agent_id
    async def _execute(self, name, description, content, category="general",
                       tags=None, triggers=None, related_tools=None) -> ToolResult  # :70
class UpdateSkillTool(AbstractTool):    # name="update_skill", args=UpdateSkillArgs, needs agent_id
    async def _execute(self, skill_id, content, commit_message="",
                       name=None, description=None) -> ToolResult                # :144

# SkillRegistry store methods these call (verified by grep in store.py):
#   await registry.search_skills(query=, category=, max_results=) -> [SkillSearchResult]
#   await registry.read_skill(skill_id, version) -> str
#   await registry.list_skills() -> list[dict]   (dicts keyed skill_id/name/category/current_version)
#   await registry.upload_skill(name=, content=, agent_id=, description=, category=,
#                               tags=, triggers=, related_tools=, commit_message=, skill_id=)
```

### AbstractToolkit contract (verified: tools/toolkit.py)
- `get_tools()` converts every **public async** method to a `ToolkitTool`. :337
- Method name = tool name when `tool_prefix is None` (default → KEEP names). :383
- `exclude_tools: tuple[str,...]` hides methods; settable per-instance in `__init__`. :228
- `@tool_schema(Model)` sets `bound_method._args_schema`, honored at :498.
- Methods with no params (e.g. `list_skills`) → empty `AbstractToolArgsSchema`. :143

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractToolkit.list_skills`~~ — not a base method; safe to define.
- ~~`tool_prefix` default value other than None~~ — default is None (names preserved).
- ~~a shared base between `SkillRegistry` (store) and `SkillFileRegistry`~~ — they are
  distinct; do NOT merge the two toolkits into one.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `SkillFileToolkit` (Module 1) exactly: `_`-prefixed deps, `@tool_schema`
  per method, docstring becomes the tool description.
- Move each standalone `_execute` body verbatim into the matching toolkit
  method (drop the trailing `**kwargs` since the schema is explicit).
- `SkillSearchArgs` is currently a **local** class in `tools.py`; reuse it (or
  the `SearchSkillArgs` in `models.py` — confirm which the LLM-facing schema
  should be; they differ in `max_results` bounds). Document the choice.

### Known Risks / Gotchas
- `SkillRegistryToolkit` must NOT expose helper methods like `_format_summary`
  as tools — keep them `_`-prefixed (already are).
- `list_skills` has no args: verify the generated schema is the empty
  `AbstractToolArgsSchema`, not a spurious model.
- Keep `create_skill_tools()`'s signature stable (`registry, agent_id,
  include_write_tools, file_registry, learned_dir`) — callers depend on it.

### External Dependencies
None new.

---

## 8. Open Questions

- [x] `search_skills` schema → **RESOLVED**: use `models.SearchSkillArgs`
      (adds `tags`, `include_deprecated`, `max_results ≤ 20`). The store's
      `search_skills` already accepts `tags`/`include_deprecated`, so they are
      wired through.
- [x] Standalone classes → **RESOLVED**: deleted outright, no backward-compat
      shims (consumers are few and internal).

### Implementation note — latent bug fixed
The original DB-tool error paths returned `ToolResult(status="error",
error=...)` **without** the required `result` field, which raises a Pydantic
`ValidationError` whenever hit (those error paths had no test coverage). The
ported `SkillRegistryToolkit` methods add `result=None` to every error return,
so those paths now work. Not a behavioural regression — the prior behaviour was
a latent crash.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-29 | Jesus Lara | Initial draft; Module 1 already implemented on branch |
| 0.2 | 2026-05-30 | Jesus Lara | Modules 2 & 3 implemented; open questions resolved; latent error-path bug fixed; 77 skills tests green |

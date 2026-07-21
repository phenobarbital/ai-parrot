---
type: Wiki Overview
title: 'Feature Specification: Skills Directory Loader + PromptBuilder Integration'
id: doc:sdd-specs-skill-registry-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot's `parrot.memory.skills` module has a mature filesystem-backed
  skill subsystem
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.memory.skills
  rel: mentions
- concept: mod:parrot.memory.skills.models
  rel: mentions
- concept: mod:parrot.memory.skills.parsers
  rel: mentions
- concept: mod:parrot.memory.unified
  rel: mentions
- concept: mod:parrot.skills
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Skills Directory Loader + PromptBuilder Integration

**Feature ID**: FEAT-188
**Date**: 2026-05-25
**Author**: jesus (assisted by Claude)
**Status**: approved
**Target version**: 0.next

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's `parrot.memory.skills` module has a mature filesystem-backed skill subsystem
(`SkillFileRegistry`, `parse_skill_file`, `SaveLearnedSkillTool`, trigger middleware,
SearchSkillsTool/ReadSkillTool for DB-backed SkillRegistry). What's missing is the
**skills directory auto-discovery + system prompt surfacing** pattern:

1. **Tier 1** — A description index (`<available_skills>` XML block) injected into the
   system prompt at `configure()` time, so the LLM knows which skills exist without
   any tool call.
2. **Tier 2** — A `LoadSkillTool` that returns the full body of a skill on demand,
   triggered by the LLM after it spots a relevant skill in the Tier 1 index.

This two-tier approach complements the existing `/trigger` middleware (user-invoked,
zero LLM calls) and `SearchSkillsTool` (LLM-invoked, embedding search + load).

| Mechanism                                  | Decider | Latency           | Use case                   |
| ------------------------------------------ | ------- | ----------------- | -------------------------- |
| `/trigger` middleware                      | User    | 0 LLM calls       | Power-user slash commands  |
| **Description index + `LoadSkillTool`** (NEW) | LLM     | +1 tool call      | Contextual, discovery-time |
| `SearchSkillsTool` (existing)              | LLM     | +1 search +1 load | Skills beyond prompt budget|

### Goals
- Auto-discover skill files from configured filesystem paths at boot time.
- Inject a static `<available_skills>` XML block into the system prompt via a
  `PromptLayer` resolved at `configure()` time (zero per-turn cost).
- Provide a `LoadSkillTool` for on-demand full-body retrieval (+1 tool call).
- Support both single-file (`.md`) and composite (`dir/SKILL.md` + assets) layouts.
- Promote all skills code to a top-level `parrot.skills` namespace with deprecation
  re-exports in `parrot.memory.skills`.
- Surface trigger-equipped skills in both the `/trigger` middleware AND the prompt
  index (with a trigger hint).

### Non-Goals (explicitly out of scope)
- Embedding-based top-K filtering of the description index (deferred to FEAT-069 IntentRouter).
- Bidirectional sync between `SkillFileRegistry` (filesystem) and `SkillRegistry` (versioned DB).
- Skill package distribution / install-from-URL.
- `watchdog`-based filesystem hot-reload (a manual `reload_skills()` API is acceptable for v1).
- `LoadSkillAssetTool` for granular per-asset retrieval in composite skills.
- Provider abstraction layer (rejected in brainstorm — see `proposals/skill-registry.brainstorm.md` Option B).
- Configuration-driven SkillsManager pattern (rejected — see Option C).

---

## 2. Architectural Design

### Overview

**Approach: Direct Integration (Option A from brainstorm).**

Extend the existing `SkillFileRegistry` and `SkillRegistryMixin` minimally. Add a
`SkillsDirectoryLoader` for filesystem discovery, a `LoadSkillTool` for Tier 2 retrieval,
and a helper function `render_skills_prompt_layer()` that builds a static `PromptLayer`
from registry contents at `configure()` time.

All skills code is promoted to `parrot/skills/` as a top-level module. The existing
`parrot/memory/skills/` becomes a deprecation re-export shim (1–2 minor versions).

Skill paths default to empty (opt-in). The recommended convention is `.agent/skills/`.

### Component Diagram
```
Boot-time flow:

  bot.configure()
       │
       ▼
  SkillRegistryMixin._configure_skill_file_registry()
       │
       ├── SkillFileRegistry.load()                    ← existing: authored + learned .md
       │
       ├── SkillsDirectoryLoader.load_into(registry)   ← NEW: discover from skill_paths
       │       │
       │       ├── parse_skill_file(path)              ← existing: single-file .md
       │       └── parse_skill_directory(dir)           ← NEW: composite dir/SKILL.md
       │
       ├── render_skills_prompt_layer(registry)         ← NEW: build static PromptLayer
       │       │
       │       └── self._prompt_builder.add(layer)      ← existing API
       │
       └── register LoadSkillTool                       ← NEW: Tier 2 tool
               │
               └── tool_manager.register_tool(tool)     ← existing dual-mode pattern

Per-turn flow (Tier 1): <available_skills> is already in system prompt — zero cost.

On-demand flow (Tier 2):
  LLM calls load_skill(name="...")
       │
       └── LoadSkillTool._execute()
               │
               └── registry.get_by_name(name)           ← NEW method on SkillFileRegistry
                       │
                       └── returns ToolResult(template_body + asset manifest)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SkillFileRegistry` | extends | Add `get_by_name()` public method (wraps existing `_by_name` dict) |
| `SkillDefinition` (model) | extends | Add `assets_dir: Path \| None` field for composite skills |
| `parse_skill_file()` | reuses | Called by `SkillsDirectoryLoader` for single-file skills |
| `SkillRegistryMixin` | extends | New config flags (`skill_paths`, `inject_skills_into_prompt`), extended `_configure_skill_file_registry()` |
| `PromptBuilder.add()` | uses | Inject static `PromptLayer` at configure-time |
| `PromptLayer` dataclass | uses | Create instance with `phase=RenderPhase.CONFIGURE` |
| `AbstractTool` / `ToolResult` | inherits | `LoadSkillTool` follows existing tool pattern |
| `tool_manager.register_tool()` | uses | Dual-mode registration (manager or `_tools` list fallback) |
| Trigger middleware | unchanged | Skills with `triggers:` continue to work; also appear in prompt index |

### Data Models

```python
# Extension to SkillDefinition (parrot/skills/models.py)
class SkillDefinition(BaseModel):
    # ... existing fields ...
    assets_dir: Optional[Path] = Field(
        default=None,
        description="Filesystem dir for composite skills; None for single-file."
    )

# LoadSkillTool args
class LoadSkillArgs(BaseModel):
    name: str = Field(..., description="Skill name as listed in <available_skills>.")
```

### New Public Interfaces

```python
# parrot/skills/loader.py
class SkillsDirectoryLoader:
    def __init__(self, paths: list[Path], logger: Logger | None = None): ...
    async def discover(self) -> list[SkillDefinition]: ...
    async def load_into(self, registry: SkillFileRegistry) -> int: ...

# parrot/skills/parsers.py (extension)
def parse_skill_directory(skill_dir: Path) -> SkillDefinition: ...

# parrot/skills/prompt.py
def render_skills_prompt_layer(
    registry: SkillFileRegistry,
    max_skills: int | None = None,
    priority: int = 45,
) -> PromptLayer: ...

# parrot/skills/tools.py (addition)
class LoadSkillTool(AbstractTool):
    name: str = "load_skill"
    async def _execute(self, name: str, **kwargs) -> ToolResult: ...

# parrot/skills/file_registry.py (extension)
class SkillFileRegistry:
    def get_by_name(self, name: str) -> Optional[SkillDefinition]: ...
```

---

## 3. Module Breakdown

### Module 1: Namespace Promotion
- **Path**: `parrot/skills/` (new top-level package)
- **Responsibility**: Move all code from `parrot/memory/skills/` to `parrot/skills/`.
  Create `parrot/memory/skills/__init__.py` as a deprecation re-export shim that
  imports everything from `parrot.skills` and issues `DeprecationWarning` on access.
- **Depends on**: none (prerequisite for all other modules)
- **Files**:
  - `parrot/skills/__init__.py` — new package init with full `__all__` exports
  - `parrot/skills/models.py` — moved from `parrot/memory/skills/models.py`
  - `parrot/skills/parsers.py` — moved from `parrot/memory/skills/parsers.py`
  - `parrot/skills/file_registry.py` — moved from `parrot/memory/skills/file_registry.py`
  - `parrot/skills/store.py` — moved from `parrot/memory/skills/store.py`
  - `parrot/skills/tools.py` — moved from `parrot/memory/skills/tools.py`
  - `parrot/skills/mixin.py` — moved from `parrot/memory/skills/mixin.py`
  - `parrot/skills/middleware.py` — moved from `parrot/memory/skills/middleware.py`
  - `parrot/memory/skills/__init__.py` — rewritten as deprecation re-export shim
  - All internal imports within moved files updated to new `parrot.skills` paths
  - All external importers across the codebase updated

### Module 2: SkillDefinition Model Extension
- **Path**: `parrot/skills/models.py`
- **Responsibility**: Add `assets_dir: Optional[Path] = None` field to `SkillDefinition`.
- **Depends on**: Module 1

### Module 3: Composite Skill Parser
- **Path**: `parrot/skills/parsers.py`
- **Responsibility**: Add `parse_skill_directory(skill_dir: Path) -> SkillDefinition`
  that parses `{dir}/SKILL.md` via `parse_skill_file()` and sets `assets_dir`.
- **Depends on**: Module 2

### Module 4: SkillFileRegistry Extension
- **Path**: `parrot/skills/file_registry.py`
- **Responsibility**: Add `get_by_name(name: str) -> Optional[SkillDefinition]` public
  method that wraps the existing `_by_name` private dict.
- **Depends on**: Module 1

### Module 5: SkillsDirectoryLoader
- **Path**: `parrot/skills/loader.py` (new file)
- **Responsibility**: Discover skills from one or more filesystem paths. Supports both
  `{dir}/{name}.md` (single-file) and `{dir}/{name}/SKILL.md` (composite) layouts.
  `load_into(registry)` hot-adds discovered skills to a `SkillFileRegistry`.
  Logs warnings on parse failure; never crashes boot.
- **Depends on**: Module 3, Module 4

### Module 6: Skills Prompt Layer Factory
- **Path**: `parrot/skills/prompt.py` (new file)
- **Responsibility**: `render_skills_prompt_layer()` function that reads all skills
  from a `SkillFileRegistry`, builds an `<available_skills>` XML block, and returns
  a `PromptLayer` instance with `phase=RenderPhase.CONFIGURE`. Skills with triggers
  get an "Also triggerable via: /cmd" hint line.
- **Depends on**: Module 4

### Module 7: LoadSkillTool
- **Path**: `parrot/skills/tools.py` (addition to moved file)
- **Responsibility**: `LoadSkillTool` — Tier 2 on-demand skill retrieval. Takes a
  `SkillFileRegistry` reference. `_execute(name)` calls `get_by_name()`, returns
  `template_body` plus an asset manifest (filenames relative to `assets_dir`) for
  composite skills.
- **Depends on**: Module 4

### Module 8: Mixin Wiring
- **Path**: `parrot/skills/mixin.py` (extension of moved file)
- **Responsibility**: Add config flags (`skill_paths: list[Path]`, `inject_skills_into_prompt: bool`,
  `skill_prompt_max_entries: int | None`). Extend `_configure_skill_file_registry()` to:
  1. Run `SkillsDirectoryLoader.load_into()` after existing `load()`.
  2. Call `render_skills_prompt_layer()` and add to `self._prompt_builder`.
  3. Register `LoadSkillTool` via dual-mode tool registration.
- **Depends on**: Module 5, Module 6, Module 7

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_parse_skill_directory_valid` | Module 3 | Composite skill dir with SKILL.md parses correctly; `assets_dir` is set |
| `test_parse_skill_directory_missing_skill_md` | Module 3 | Raises `FileNotFoundError` when SKILL.md absent |
| `test_parse_skill_directory_inherits_fields` | Module 3 | Frontmatter fields (name, description, triggers) parsed same as single-file |
| `test_get_by_name_found` | Module 4 | Returns `SkillDefinition` for a registered skill name |
| `test_get_by_name_not_found` | Module 4 | Returns `None` for unknown name |
| `test_loader_discover_single_file` | Module 5 | Discovers `*.md` files from a directory |
| `test_loader_discover_composite` | Module 5 | Discovers `dir/SKILL.md` composite skills |
| `test_loader_discover_mixed` | Module 5 | Discovers both single and composite in same directory |
| `test_loader_skip_missing_dir` | Module 5 | Non-existent path logged and skipped, no crash |
| `test_loader_skip_malformed` | Module 5 | Malformed frontmatter logged as warning, other skills loaded |
| `test_loader_load_into` | Module 5 | Hot-adds discovered skills to registry; returns count |
| `test_render_skills_prompt_layer_empty` | Module 6 | Returns empty-template PromptLayer when no skills |
| `test_render_skills_prompt_layer_basic` | Module 6 | XML block contains skill names and descriptions |
| `test_render_skills_prompt_layer_trigger_hint` | Module 6 | Skills with triggers include "Also triggerable via" line |
| `test_render_skills_prompt_layer_max_entries` | Module 6 | Truncates when `max_skills` is set |
| `test_render_skills_prompt_layer_phase` | Module 6 | PromptLayer has `phase=RenderPhase.CONFIGURE` |
| `test_load_skill_tool_found` | Module 7 | Returns `template_body` in `ToolResult.result` |
| `test_load_skill_tool_not_found` | Module 7 | Returns `ToolResult(status="error")` for unknown name |
| `test_load_skill_tool_composite_manifest` | Module 7 | Returns asset filenames in `metadata.assets` for composite skill |
| `test_load_skill_tool_single_file_no_assets` | Module 7 | `metadata.assets` is empty list for single-file skill |
| `test_deprecation_reexport` | Module 1 | `from parrot.memory.skills import X` issues `DeprecationWarning` and resolves correctly |

### Integration Tests
| Test | Description |
|---|---|
| `test_mixin_configure_injects_prompt_layer` | After `configure()`, `self._prompt_builder` contains an `available_skills` layer |
| `test_mixin_configure_registers_load_skill_tool` | After `configure()`, `LoadSkillTool` is in the tool list |
| `test_mixin_configure_no_skill_paths` | When `skill_paths=[]`, no loader runs, no prompt layer, no LoadSkillTool |
| `test_full_discovery_to_load` | Skills in directory → appear in prompt layer → `load_skill()` returns body |

### Test Data / Fixtures
```python
@pytest.fixture
def skill_dir(tmp_path):
    """Directory with mixed single-file and composite skills."""
    # Single-file skill
    (tmp_path / "summarize.md").write_text(
        "---\nname: summarize\ndescription: Summarize text\n"
        "triggers:\n  - /resumen\n---\nSummarize the input text."
    )
    # Composite skill
    composite = tmp_path / "extract-pdf"
    composite.mkdir()
    (composite / "SKILL.md").write_text(
        "---\nname: extract-pdf\ndescription: Extract tables from PDF\n"
        "triggers: []\n---\nUse camelot to extract tables."
    )
    (composite / "script.py").write_text("# extraction script")
    return tmp_path

@pytest.fixture
def populated_registry(skill_dir):
    """SkillFileRegistry pre-loaded with test skills."""
    registry = SkillFileRegistry(skills_dir=skill_dir)
    # Synchronous load for tests — or use event_loop fixture
    return registry
```

---

## 5. Acceptance Criteria

- [ ] `SkillsDirectoryLoader` discovers both `*.md` and `*/SKILL.md` from each configured path.
- [ ] Failed parses log warnings; boot continues without crashing.
- [ ] `<available_skills>` XML block appears in the system prompt after `configure()` when `inject_skills_into_prompt=True` and `skill_paths` is non-empty.
- [ ] The prompt layer has `phase=RenderPhase.CONFIGURE` (resolved once, cached — zero per-turn cost).
- [ ] `LoadSkillTool` returns `template_body` + asset manifest for composite skills; returns `template_body` only for single-file skills.
- [ ] `LoadSkillTool` returns `ToolResult(status="error")` for unknown skill names.
- [ ] Skills declaring `triggers:` remain functional via `/trigger` middleware AND surface in `<available_skills>` with a "Also triggerable via" hint.
- [ ] All code lives in `parrot/skills/` (top-level namespace).
- [ ] `parrot.memory.skills` re-exports with `DeprecationWarning` — all existing imports continue to work.
- [ ] Existing `SkillFileRegistry`, trigger middleware, and DB-backed `SkillRegistry` unaffected.
- [ ] `SkillFileRegistry.get_by_name()` returns `Optional[SkillDefinition]` by name lookup.
- [ ] `SkillDefinition.assets_dir` is `Path | None` — set for composite skills, `None` for single-file.
- [ ] `skill_paths` defaults to empty list (opt-in).
- [ ] All unit and integration tests pass.
- [ ] No breaking changes to existing public API beyond the deprecation warnings on old import paths.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.memory.skills import SkillFileRegistry      # __init__.py
from parrot.memory.skills import SkillDefinition        # __init__.py
from parrot.memory.skills import parse_skill_file       # __init__.py
from parrot.memory.skills import SkillRegistryMixin     # __init__.py
from parrot.memory.skills import SkillRegistryHooks     # __init__.py
from parrot.memory.skills import create_skill_tools     # __init__.py
from parrot.memory.skills import SaveLearnedSkillTool   # __init__.py
from parrot.memory.skills.models import SkillSource     # models.py:47
from parrot.memory.skills.parsers import parse_skill_file  # parsers.py:33
from parrot.bots.prompts import PromptLayer, LayerPriority, RenderPhase  # __init__.py
from parrot.bots.prompts import PromptBuilder           # __init__.py
from parrot.tools.abstract import AbstractTool, ToolResult  # tools/abstract.py
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/memory/skills/file_registry.py:16
class SkillFileRegistry:
    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None) -> None:  # line 28
        self.skills_dir: Path                              # line 33
        self.learned_dir: Path                             # line 34
        self._skills: Dict[str, SkillDefinition] = {}      # trigger -> skill, line 35
        self._by_name: Dict[str, SkillDefinition] = {}     # name -> skill, line 36
        self._lock: asyncio.Lock                           # line 37
        self.logger: logging.Logger                        # line 38
    async def load(self) -> None:                          # line 40
    def _scan_dir(self, directory: Path, exclude_subdir: Optional[str] = None) -> List[SkillDefinition]:  # line 64
    def _register(self, skill: SkillDefinition) -> None:   # line 88
    def get(self, trigger: str) -> Optional[SkillDefinition]:  # line 110
    def add(self, skill: SkillDefinition) -> None:         # line 121
    def list_skills(self) -> List[SkillDefinition]:        # line 129
    def has_trigger(self, trigger: str) -> bool:           # line 133

# packages/ai-parrot/src/parrot/memory/skills/models.py:53
class SkillDefinition(BaseModel):  # Pydantic BaseModel
    name: str                                              # required
    description: str                                       # required
    triggers: List[str]                                    # required
    source: SkillSource = SkillSource.AUTHORED
    priority: int = 90
    version: str = "1.0"
    category: Optional[str] = None
    template_body: str                                     # THIS IS THE CONTENT FIELD
    token_count: int
    file_path: Path
    MAX_TOKENS: ClassVar[int] = 1000

# packages/ai-parrot/src/parrot/memory/skills/models.py:84
@dataclass
class SkillMetadata:
    name: str
    description: str
    category: SkillCategory = SkillCategory.GENERAL
    tags: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    related_tools: List[str] = field(default_factory=list)

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:50
@dataclass(frozen=True)
class PromptLayer:
    name: str                                              # line 66
    priority: LayerPriority | int                          # line 67
    template: str                                          # line 68
    phase: RenderPhase = RenderPhase.REQUEST               # line 69
    condition: Optional[Callable] = None                   # line 70
    required_vars: frozenset[str] = frozenset()            # line 71
    cacheable: Optional[bool] = None                       # line 72 (auto-derives from phase)

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:22
class LayerPriority(IntEnum):
    IDENTITY = 10
    PRE_INSTRUCTIONS = 15
    SECURITY = 20
    KNOWLEDGE = 30
    USER_SESSION = 40
    TOOLS = 50
    OUTPUT = 60
    BEHAVIOR = 70
    CUSTOM = 80

# packages/ai-parrot/src/parrot/bots/prompts/layers.py:35
class RenderPhase(str, Enum):
    CONFIGURE = "configure"   # Static, resolved once, cached
    REQUEST = "request"       # Dynamic, resolved per request

# packages/ai-parrot/src/parrot/bots/prompts/builder.py:21
class PromptBuilder:
    def add(self, layer: PromptLayer) -> PromptBuilder:    # line 152, adds/replaces by name
    def remove(self, name: str) -> PromptBuilder:          # line 164
    def replace(self, name: str, layer: PromptLayer) -> PromptBuilder:  # line 176
    def get(self, name: str) -> Optional[PromptLayer]:     # line 197
    def configure(self, **kwargs) -> PromptBuilder:        # line 223, Phase 1
    def build(self, **kwargs) -> str:                      # line 243, Phase 2

# packages/ai-parrot/src/parrot/memory/skills/parsers.py:33
def parse_skill_file(file_path: Path) -> SkillDefinition:
    # Uses python-frontmatter library
    # Counts tokens via tiktoken cl100k_base
    # Raises ValueError (missing fields), ValidationError (token limit), FileNotFoundError
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SkillsDirectoryLoader` | `SkillFileRegistry.add()` | method call (hot-add) | `file_registry.py:121` |
| `SkillsDirectoryLoader` | `parse_skill_file()` | function call | `parsers.py:33` |
| `SkillsDirectoryLoader` | `parse_skill_directory()` | function call (new) | N/A — to be created |
| `render_skills_prompt_layer()` | `SkillFileRegistry.list_skills()` | method call | `file_registry.py:129` |
| `render_skills_prompt_layer()` | `PromptLayer(...)` | constructor | `layers.py:50` |
| Mixin wiring | `self._prompt_builder.add(layer)` | method call | `builder.py:152` (pattern at `agent.py:1163`) |
| Mixin wiring | `tool_manager.register_tool(tool)` | method call | `mixin.py:253` |
| `LoadSkillTool` | `SkillFileRegistry.get_by_name()` | method call (new) | N/A — to be created |

### Tool Registration Pattern
```python
# From mixin.py:250-257 — dual registration (verified)
tool_manager = getattr(self, 'tool_manager', None)
if tool_manager and hasattr(tool_manager, 'register_tool'):
    result = tool_manager.register_tool(tool)
    if inspect.isawaitable(result):
        await result
elif hasattr(self, '_tools'):
    self._tools = getattr(self, '_tools', []) + tools
```

### Prompt Builder Access Pattern
```python
# From agent.py:1161-1163 — how bots add layers (verified)
if self._prompt_builder is not None:
    self._prompt_builder.add(DATAFRAME_CONTEXT_LAYER)
```

### Does NOT Exist (Anti-Hallucination)
- ~~`SkillFileRegistry.get_by_name()`~~ — does NOT exist yet; only private `_by_name` dict at line 36. **Must be created in Module 4.**
- ~~`parrot/skills/`~~ — top-level module does NOT exist. **Must be created in Module 1.**
- ~~`parse_skill_directory()`~~ — does NOT exist. **Must be created in Module 3.**
- ~~`LoadSkillTool`~~ — does NOT exist. **Must be created in Module 7.**
- ~~`SkillDefinition.assets_dir`~~ — field does NOT exist. **Must be added in Module 2.**
- ~~`SkillDefinition.content`~~ — field is called `template_body`, NOT `content`.
- ~~`SkillDefinition.body`~~ — field is called `template_body`, NOT `body`.
- ~~`PromptBuilder.register_layer()`~~ — method is called `add()`, NOT `register_layer()`.

…(truncated)…

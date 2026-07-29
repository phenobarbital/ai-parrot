---
type: Wiki Overview
title: 'Brainstorm: Skills Directory Loader + PromptBuilder Integration'
id: doc:sdd-proposals-skill-registry-brainstorm-md
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

# Brainstorm: Skills Directory Loader + PromptBuilder Integration

**Date**: 2026-05-25
**Author**: jesus (assisted by Claude)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

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

**Who is affected:** Developers building agents with AI-Parrot who author skill files.
Agents gain contextual skill discovery without consuming embedding-search tokens.

**Why now:** The skill subsystem is stable, the PromptBuilder layer system (FEAT-181)
is in place, and the target is under 20 skills — making static prompt injection viable
without needing IntentRouter (FEAT-069) filtering.

## Constraints & Requirements

- Zero per-turn latency: the description index is resolved once at `configure()` time
  via a static `PromptLayer` (phase=CONFIGURE). No dynamic rendering per request.
- Under 20 skills initially (~70 tokens/skill = ~1,400 tokens persistent). No
  embedding-based filtering needed for v1.
- Backward compatibility: existing `SkillFileRegistry`, trigger middleware, and
  DB-backed `SkillRegistry` must remain fully functional.
- Full namespace promotion: all skills code moves to `parrot.skills` as a top-level
  module; `parrot.memory.skills` becomes deprecation re-exports.
- Both single-file (`.md`) and composite (`dir/SKILL.md` + assets) skill layouts
  must be supported from v1.
- Skills with `triggers:` declared must appear in both the trigger middleware AND
  the `<available_skills>` prompt index (with a trigger hint).

---

## Options Explored

### Option A: Direct Integration (Pragmatic)

Move everything to `parrot/skills/`, extend existing classes minimally, and wire
the new components (SkillsDirectoryLoader, LoadSkillTool, prompt layer) directly
into the existing SkillRegistryMixin using the established patterns.

The key additions:
- `SkillsDirectoryLoader` class for filesystem discovery (single-file + composite).
- `get_by_name()` added to `SkillFileRegistry`.
- `parse_skill_directory()` companion to `parse_skill_file()`.
- `LoadSkillTool` that references `SkillFileRegistry` directly.
- `render_skills_prompt_layer()` helper that builds a static `PromptLayer` from the
  registry contents at `configure()` time.
- Wiring in `SkillRegistryMixin._configure_skill_file_registry()`.

The mixin's existing `_configure_skill_file_registry()` gains a new phase after
`load()`: run the directory loader, then build and inject the prompt layer.

✅ **Pros:**
- Lowest effort — extends existing patterns rather than introducing new abstractions.
- Familiar to anyone who knows the current mixin/registry code.
- No new abstractions to maintain; `LoadSkillTool` follows the same pattern as
  `SearchSkillsTool` and `ReadSkillTool`.
- Easy to test — each component is independently testable.

❌ **Cons:**
- `SkillFileRegistry` grows more responsibilities (name lookup, directory loading).
- Tighter coupling between LoadSkillTool and SkillFileRegistry — harder to swap
  backends later (though YAGNI for v1).
- Mixin grows more configuration flags.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | YAML frontmatter parsing | Already a dependency (used by parsers.py) |
| `tiktoken` | Token counting for prompt budget | Already a dependency (used by parsers.py) |

🔗 **Existing Code to Reuse:**
- `parrot/memory/skills/file_registry.py` — SkillFileRegistry (extend with `get_by_name()`)
- `parrot/memory/skills/parsers.py` — `parse_skill_file()` (add `parse_skill_directory()`)
- `parrot/memory/skills/mixin.py` — SkillRegistryMixin (extend `_configure_skill_file_registry()`)
- `parrot/bots/prompts/layers.py` — PromptLayer dataclass (create static instance)
- `parrot/memory/skills/tools.py` — AbstractTool/ToolResult pattern (follow for LoadSkillTool)

---

### Option B: Provider Abstraction (Extensible)

Same namespace promotion, but introduce a `SkillProvider` protocol that abstracts
how skills are discovered and loaded. `SkillFileRegistry` becomes one provider;
`SkillsDirectoryLoader` becomes another. `LoadSkillTool` accepts any provider.

```
SkillProvider (Protocol)
├── FileRegistryProvider  — wraps existing SkillFileRegistry
├── DirectoryProvider     — wraps SkillsDirectoryLoader
└── (future) RemoteProvider — URL-based skill install
```

The prompt layer factory and tool take a `SkillProvider` instead of concrete classes.

✅ **Pros:**
- Clean abstraction boundary — LoadSkillTool doesn't know about SkillFileRegistry.
- Easy to add new providers (remote, package-based) without touching existing code.
- Natural integration point for IntentRouter (FEAT-069) — router queries providers.
- Testable via mock providers.

❌ **Cons:**
- Adds an abstraction layer for a use case with exactly one concrete implementation
  today (under 20 skills, single directory).
- More boilerplate: protocol definition, adapter classes, provider registration.
- Indirection cost — debugging requires understanding the provider chain.
- YAGNI risk: the "extensibility" may never be exercised.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | YAML frontmatter parsing | Already a dependency |
| `tiktoken` | Token counting | Already a dependency |

🔗 **Existing Code to Reuse:**
- Same as Option A, plus abstracting behind protocol adapters.

---

### Option C: Configuration-Driven Manager (Declarative)

Replace the mixin-extension approach with a standalone `SkillsManager` that
encapsulates all skill lifecycle: discovery, registration, prompt injection, and
tool creation. Configured via a `SkillsConfig` dataclass. The bot uses composition
instead of mixin inheritance:

```python
config = SkillsConfig(
    skill_paths=[Path(".agent/skills/")],
    inject_into_prompt=True,
    expose_load_tool=True,
)
manager = SkillsManager(config, prompt_builder=bot._prompt_builder)
await manager.setup()
```

The mixin becomes a thin wrapper that delegates to `SkillsManager`.

✅ **Pros:**
- Clean separation of concerns — manager owns the full lifecycle.
- Composable: can be used without the mixin (e.g., in standalone scripts).
- Configuration is explicit and type-safe (SkillsConfig dataclass).
- Easier to test in isolation — no bot instance required.

❌ **Cons:**
- Larger refactor: existing mixin code must be reorganized.
- Two ways to configure skills (mixin flags vs. SkillsConfig) during the transition.
- Over-engineering for the current use case (under 20 skills, single agent type).
- Breaking change risk if mixin consumers depend on internal state.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | YAML frontmatter parsing | Already a dependency |
| `tiktoken` | Token counting | Already a dependency |

🔗 **Existing Code to Reuse:**
- Same components, but reorganized under SkillsManager orchestration.

---

## Recommendation

**Option A** is recommended because:

1. **Right-sized for the problem.** Under 20 skills, single directory, static prompt
   injection — the simplest approach that works is the best approach. Adding an
   abstraction layer (Option B) or a manager (Option C) trades implementation
   simplicity for extensibility we don't need yet.

2. **Follows established patterns.** The codebase already uses the mixin + direct
   reference pattern (e.g., `SearchSkillsTool` takes `SkillRegistry` directly,
   `SaveLearnedSkillTool` takes `SkillFileRegistry` directly). Option A is consistent.

3. **Clear upgrade path.** If IntentRouter (FEAT-069) later needs a provider
   abstraction, Option A's direct references can be wrapped in adapters without
   changing the public API. The namespace promotion to `parrot.skills` gives us
   the clean module boundary we need.

4. **Lowest risk.** The namespace promotion is the biggest change; adding the loader,
   tool, and prompt layer on top of that are all incremental. Option C's mixin
   refactor would risk regressions in all existing skill-using bots.

**Tradeoff accepted:** tighter coupling between LoadSkillTool and SkillFileRegistry.
Acceptable because (a) there's only one implementation, (b) the namespace promotion
makes future extraction easy, (c) YAGNI.

---

## Feature Description

### User-Facing Behavior

A developer places `.md` skill files (with YAML frontmatter) in configured skill
directories (default: `.agent/skills/`). When the agent boots:

1. All skills are auto-discovered and parsed (single-file `.md` or composite
   directory with `SKILL.md`).
2. The system prompt includes an `<available_skills>` block listing each skill's
   name and description, with trigger hints where applicable.
3. During conversation, the LLM can call `load_skill(name="...")` to retrieve the
   full skill body when it determines a skill is relevant.

Skills with `triggers:` continue to work via the `/trigger` middleware AND appear
in the prompt index for contextual discovery.

### Internal Behavior

**Boot-time flow:**
1. `SkillRegistryMixin._configure_skill_file_registry()` runs during `bot.configure()`.
2. `SkillFileRegistry.load()` eagerly loads authored and learned `.md` files (existing).
3. **NEW:** `SkillsDirectoryLoader.load_into(registry)` discovers additional skills
   from configured `skill_paths` and hot-adds them to the `SkillFileRegistry`.
4. **NEW:** `render_skills_prompt_layer(registry)` builds a static `PromptLayer`
   with the `<available_skills>` XML block. Added to `self._prompt_builder` via `.add()`.
5. **NEW:** `LoadSkillTool` is instantiated with the `SkillFileRegistry` reference and
   registered via `tool_manager.register_tool()` (or `_tools` fallback).

**Per-turn flow (Tier 1 — zero cost):**
- The `<available_skills>` block is already in the system prompt. The LLM reads it
  as static context.

**On-demand flow (Tier 2 — +1 tool call):**
- LLM calls `load_skill(name="extract-pdf-tables")`.
- `LoadSkillTool._execute()` calls `registry.get_by_name(name)`.
- Returns `ToolResult` with `template_body` and, for composite skills, an asset
  manifest (list of filenames relative to the skill directory).

### Edge Cases & Error Handling

- **Missing skill directory:** Loader logs debug message and continues. No crash.
- **Malformed frontmatter:** Loader logs warning per file and skips. Boot continues.
- **Name collision:** `SkillFileRegistry._register()` already handles this — logs
  error, skips duplicate. Directory-loaded skills follow the same path.
- **LoadSkillTool with unknown name:** Returns `ToolResult(status="error")`.
- **Composite skill with no assets:** Returns body only, empty asset manifest.
- **Token budget exceeded:** With under 20 skills at ~70 tokens each, this is
  not a v1 concern. The `skill_prompt_max_entries` config flag provides a safety
  valve. Future IntentRouter integration replaces truncation with smart filtering.
- **Skills in both old and new directories:** `SkillFileRegistry` deduplicates
  by name — the first-registered wins. Loader processes `skill_paths` in order,
  after the existing `skills_dir` load.

---

## Capabilities

### New Capabilities
- `skills-directory-loader`: Auto-discover skills from configured filesystem paths
- `skills-prompt-injection`: Static `<available_skills>` block in system prompt
- `load-skill-tool`: On-demand full-body skill retrieval via tool call
- `composite-skill-support`: Directory-based skills with SKILL.md + adjacent assets
- `skills-namespace-promotion`: Top-level `parrot.skills` module with deprecation re-exports

### Modified Capabilities
- `skill-file-registry`: Add `get_by_name()` method
- `skill-parsers`: Add `parse_skill_directory()` function
- `skill-registry-mixin`: Extend `_configure_skill_file_registry()` for discovery + prompt injection

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/memory/skills/*` | moves to `parrot/skills/` | Full module promotion; re-exports with DeprecationWarning |
| `parrot/memory/skills/__init__.py` | modifies | Becomes deprecation re-export shim |
| `parrot/skills/file_registry.py` | extends | Add `get_by_name()` method |
| `parrot/skills/parsers.py` | extends | Add `parse_skill_directory()` |
| `parrot/skills/loader.py` | new | `SkillsDirectoryLoader` class |
| `parrot/skills/tools.py` | extends | Add `LoadSkillTool` class |
| `parrot/skills/mixin.py` | extends | New config flags, prompt layer injection, tool registration |
| `parrot/skills/models.py` | extends | Add `SkillDefinition.assets_dir: Path | None` field |
| `parrot/bots/prompts/builder.py` | depends on | Uses existing `add()` API — no changes needed |
| `parrot/bots/prompts/layers.py` | depends on | Uses existing `PromptLayer` dataclass — no changes needed |
| All importers of `parrot.memory.skills` | depends on | Must be updated or use re-exports |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/memory/skills/file_registry.py:16
class SkillFileRegistry:
    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None) -> None:  # line 28
        self.skills_dir: Path
        self.learned_dir: Path
        self._skills: Dict[str, SkillDefinition] = {}   # trigger -> skill (line 35)
        self._by_name: Dict[str, SkillDefinition] = {}   # name -> skill (line 36)
    async def load(self) -> None:                         # line 40
    def get(self, trigger: str) -> Optional[SkillDefinition]:  # line 110
    def add(self, skill: SkillDefinition) -> None:        # line 121
    def list_skills(self) -> List[SkillDefinition]:       # line 129
    def has_trigger(self, trigger: str) -> bool:          # line 133
    def _register(self, skill: SkillDefinition) -> None:  # line 88
    def _scan_dir(self, directory: Path, exclude_subdir: Optional[str] = None) -> List[SkillDefinition]:  # line 64

# From packages/ai-parrot/src/parrot/memory/skills/models.py:53
class SkillDefinition(BaseModel):
    name: str                                   # line ~55
    description: str                            # line ~56
    triggers: List[str]                         # line ~57
    source: SkillSource = SkillSource.AUTHORED  # line ~58
    priority: int = 90                          # line ~59
    version: str = "1.0"                        # line ~60
    category: Optional[str] = None              # line ~61
    template_body: str                          # line ~62 — THIS IS THE CONTENT FIELD
    token_count: int                            # line ~63
    file_path: Path                             # line ~64
    MAX_TOKENS: ClassVar[int] = 1000            # line ~65

# From packages/ai-parrot/src/parrot/memory/skills/models.py:84
@dataclass
class SkillMetadata:
    name: str
    description: str
    category: SkillCategory = SkillCategory.GENERAL
    tags: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    related_tools: List[str] = field(default_factory=list)

# From packages/ai-parrot/src/parrot/bots/prompts/layers.py:50
@dataclass(frozen=True)
class PromptLayer:
    name: str                                              # line 66
    priority: LayerPriority | int                          # line 67
    template: str                                          # line 68
    phase: RenderPhase = RenderPhase.REQUEST               # line 69
    condition: Optional[Callable] = None                   # line 70
    required_vars: frozenset[str] = frozenset()            # line 71
    cacheable: Optional[bool] = None                       # line 72

# From packages/ai-parrot/src/parrot/bots/prompts/builder.py:21
class PromptBuilder:
    def add(self, layer: PromptLayer) -> PromptBuilder:    # line 152 — adds/replaces by name
    def configure(self, **kwargs) -> PromptBuilder:        # line 223 — Phase 1
    def build(self, **kwargs) -> str:                      # line 243 — Phase 2

# From packages/ai-parrot/src/parrot/bots/prompts/layers.py:22
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
```

#### Verified Imports
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

#### Key Attributes & Constants
- `SkillDefinition.template_body` → `str` (models.py:~62) — the skill content/body field
- `SkillDefinition.name` → `str` — used as the lookup key in `_by_name`
- `SkillDefinition.triggers` → `List[str]` — used by trigger middleware
- `SkillDefinition.file_path` → `Path` — source file on disk
- `SkillFileRegistry._by_name` → `Dict[str, SkillDefinition]` (file_registry.py:36) — private name index
- `LayerPriority.CUSTOM` → `80` — highest built-in priority
- `RenderPhase.CONFIGURE` → resolved once at configure(), cached

#### Tool Registration Pattern
```python
# From mixin.py:250-257 — dual registration
tool_manager = getattr(self, 'tool_manager', None)
if tool_manager and hasattr(tool_manager, 'register_tool'):
    result = tool_manager.register_tool(tool)
    if inspect.isawaitable(result):
        await result
elif hasattr(self, '_tools'):
    self._tools = getattr(self, '_tools', []) + tools
```

#### Prompt Builder Access Pattern
```python
# From agent.py:1161-1163 — how bots add layers
if self._prompt_builder is not None:
    self._prompt_builder.add(DATAFRAME_CONTEXT_LAYER)
```

### Does NOT Exist (Anti-Hallucination)
- ~~`SkillFileRegistry.get_by_name()`~~ — does NOT exist; must be added (only `_by_name` private dict exists)
- ~~`parrot/skills/`~~ — top-level module does NOT exist; must be created
- ~~`parse_skill_directory()`~~ — does NOT exist; must be added to parsers.py
- ~~`LoadSkillTool`~~ — does NOT exist; must be created
- ~~`SkillDefinition.assets_dir`~~ — does NOT exist; must be added
- ~~`SkillDefinition.content`~~ — field is called `template_body`, NOT `content`
- ~~`SkillDefinition.body`~~ — field is called `template_body`, NOT `body`
- ~~`PromptBuilder.register_layer()`~~ — method is called `add()`, NOT `register_layer()`
- ~~`AbstractPromptLayer`~~ — does NOT exist; `PromptLayer` is a frozen dataclass, not abstract
- ~~`SkillRegistryMixin._prompt_builder`~~ — mixin does NOT expose prompt builder; must access via `self._prompt_builder` (inherited from bot base class)
- ~~`SkillRegistryMixin.skill_paths`~~ — config flag does NOT exist; must be added

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The namespace promotion (move + re-exports) must
  complete first, then the new components (loader, tool, prompt layer, parsers) can be
  developed in parallel since they touch different files. Mixin wiring depends on all
  of them.
- **Cross-feature independence**: No conflicts with in-flight specs. The PromptBuilder
  (`bots/prompts/`) is used read-only (`.add()` API). IntentRouter (FEAT-069) is a
  future consumer, not an in-flight dependency.
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: The namespace promotion affects every file in the module. Splitting
  tasks across worktrees would create merge conflicts on every file. Sequential execution
  in one worktree, with the promotion task first, avoids this entirely. The total effort
  is Low–Medium, so parallel workers wouldn't save meaningful time.

---

## Open Questions
- [x] Does PromptBuilder expose a layer/section registration API? — *Owner: jesus*: Yes, `PromptBuilder.add(layer: PromptLayer)` at `builder.py:152`. Returns self for chaining.
- [x] What is the Skill content field name? — *Owner: jesus*: `SkillDefinition.template_body` (NOT `content` or `body`).
- [x] Does `SkillFileRegistry.get_by_name()` exist? — *Owner: jesus*: No. Private `_by_name` dict exists at line 36. Must add a public `get_by_name()` method.
- [x] How are tools registered in the mixin? — *Owner: jesus*: Dual mode — `tool_manager.register_tool(tool)` primary, `_tools` list append fallback. See mixin.py:250-257.
- [x] Module location: `parrot.memory.skills` vs `parrot.skills`? — *Owner: jesus*: Promote to `parrot.skills` with deprecation re-exports in `parrot.memory.skills`.
- [x] Default `skill_paths`? — *Owner: jesus*: Empty by default (opt-in). Document `.agent/skills/` as the recommended convention.
- [x] What PromptLayer priority should the `<available_skills>` block use? — *Owner: jesus*: Candidates: `LayerPriority.KNOWLEDGE` (30) positions it with context; a custom int like 45 (between USER_SESSION and TOOLS) keeps it close to tool descriptions. Needs decision during spec: Skills are knowledge, put after 30.
- [x] Should `SkillDefinition.MAX_TOKENS` (1000) increase for composite skills? — *Owner: jesus*: Composite skills may have longer bodies. The current 1000-token limit might be too restrictive. Needs measurement with real composite skills: need measurement first, I think 4096 will be a great start.
- [x] What's the deprecation timeline for `parrot.memory.skills` re-exports? — *Owner: jesus*: Proposal says 1-2 minor versions. Need to decide the exact version where re-exports are removed: memory.skills is only used in tests and in unified model, changing the path is only affecting parrot.memory.unified/mixin.py.
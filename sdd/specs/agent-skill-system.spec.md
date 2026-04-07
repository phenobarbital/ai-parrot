# Feature Specification: Agent Skill System

**Feature ID**: FEAT-088
**Date**: 2026-04-07
**Author**: Jesus Lara + Claude
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents have no lightweight mechanism for developers (or the agents themselves) to define reusable behavioral instructions that activate on demand via deterministic triggers. The existing `SkillRegistryMixin` provides learned-skill storage with vector search, FAISS indexing, and versioning — heavy infrastructure designed for runtime discovery, not for simple "when the user says `/resumen`, follow these instructions" patterns.

As agents become more configurable via `AGENTS_DIR/{agent_id}/` (KB, queries, config.yaml), skills are the natural next step: behavioral templates described in markdown that live alongside knowledge bases and activate deterministically.

### Goals

- Developers can define skills as `.md` files with YAML frontmatter in `AGENTS_DIR/{agent_id}/skills/`
- Skills activate via deterministic `/trigger` at the start of user messages
- Activated skills inject as a transient `PromptLayer` in the system prompt for that request only
- Agents with `SkillsMixin` can autonomously create learned skills persisted to `skills/learned/`
- Learned skills are immediately available in the current session (hot-add)
- Reserved `/skills` and `/help` triggers list available skills from the registry
- Skill template body enforces a 1000-token maximum

### Non-Goals (explicitly out of scope)

- Global skill registry (skills shared across bots)
- Non-deterministic trigger detection (regex, keyword matching, embeddings)
- Skills declaring tool dependencies
- Skills composing/invoking other skills
- Multi-skill activation per request (only first trigger matches)
- Vector search for skill discovery (files-only approach)

---

## 2. Architectural Design

### Overview

The skill system is implemented as two cooperating components layered on existing infrastructure:

1. **`SkillFileRegistry`** — scans `AGENTS_DIR/{agent_id}/skills/` (and `skills/learned/`) at configure time, parses YAML frontmatter + markdown body, validates, and indexes by trigger name in a dict. Eager loading.

2. **`SkillTriggerMiddleware`** — a `PromptMiddleware` registered in the bot's `PromptPipeline`. Intercepts user messages, detects `/trigger` patterns, strips the prefix, stores the activated `SkillDefinition` on the bot instance, and returns the cleaned query.

3. **Transient layer injection** — `create_system_prompt()` checks for an active skill on the bot instance, temporarily adds a `PromptLayer` to the builder, calls `build()`, then removes it.

### Component Diagram

```
AGENTS_DIR/{agent_id}/skills/
├── resumen.md (authored)
├── traductor.md (authored)
└── learned/
    └── extraer_datos.md (LLM-generated)
          │
          ▼
  ┌─ SkillFileRegistry ──────────────┐
  │  Eager load at configure()        │
  │  Dict[trigger_name → SkillDef]    │
  │  Validates frontmatter + tokens   │
  └───────────┬───────────────────────┘
              │
              ▼
  ┌─ SkillTriggerMiddleware ─────────┐
  │  Registered in PromptPipeline     │
  │  Detects /trigger at msg start    │
  │  Strips prefix, sets bot._active_skill │
  └───────────┬───────────────────────┘
              │
              ▼
  ┌─ create_system_prompt() ─────────┐
  │  Checks self._active_skill        │
  │  Adds transient PromptLayer       │
  │  Calls _build_prompt()            │
  │  Removes transient layer          │
  │  Clears self._active_skill        │
  └───────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PromptMiddleware` / `PromptPipeline` | uses | SkillTriggerMiddleware is a standard PromptMiddleware |
| `PromptLayer` / `PromptBuilder` | uses | Transient skill layer uses `add()` / `remove()` public API |
| `SkillRegistryMixin` | extends | Add file-based loading, middleware registration, hot-add |
| `AbstractBot.create_system_prompt()` | modifies | ~15 lines to check active skill + inject/remove transient layer |
| `AbstractBot._prompt_pipeline` | uses | Middleware registered during configure |
| `AGENTS_DIR/{agent_id}/` | extends | New `skills/` and `skills/learned/` subdirectories |
| `DocumentSkillTool` (existing) | adapts | Adapt to write `.md` files to `skills/learned/` instead of JSON |

### Data Models

```python
class SkillSource(str, Enum):
    """Origin of the skill."""
    AUTHORED = "authored"    # Developer-created
    LEARNED = "learned"      # LLM-generated

class SkillDefinition(BaseModel):
    """Parsed skill from a .md file."""
    name: str
    description: str
    triggers: List[str]               # e.g., ["/resumen"]
    source: SkillSource = SkillSource.AUTHORED
    priority: int = 90                # Fixed: sits after CUSTOM(80)
    version: str = "1.0"
    category: Optional[str] = None
    # Runtime
    template_body: str                # The markdown body (skill instructions)
    token_count: int                  # Pre-computed at load time
    file_path: Path                   # Source .md file for debugging

    MAX_TOKENS: ClassVar[int] = 1000
```

### New Public Interfaces

```python
class SkillFileRegistry:
    """Filesystem-based skill registry with eager loading."""

    def __init__(self, skills_dir: Path, learned_dir: Optional[Path] = None) -> None: ...
    async def load(self) -> None: ...
    def get(self, trigger: str) -> Optional[SkillDefinition]: ...
    def add(self, skill: SkillDefinition) -> None: ...   # Hot-add for learned skills
    def list_skills(self) -> List[SkillDefinition]: ...
    def has_trigger(self, trigger: str) -> bool: ...


# SkillTriggerMiddleware is a PromptMiddleware instance, not a class:
def create_skill_trigger_middleware(
    registry: SkillFileRegistry,
    bot: AbstractBot,
) -> PromptMiddleware: ...


# Extension to SkillRegistryMixin:
class SkillRegistryMixin:
    # New attributes
    _skill_file_registry: Optional[SkillFileRegistry] = None
    _active_skill: Optional[SkillDefinition] = None

    async def _configure_skill_file_registry(self) -> None: ...
    async def save_learned_skill(
        self, name: str, content: str, description: str,
        triggers: List[str], category: str = "general",
    ) -> Optional[SkillDefinition]: ...
```

---

## 3. Module Breakdown

### Module 1: Skill Definition Model
- **Path**: `parrot/memory/skills/models.py` (extend existing)
- **Responsibility**: `SkillDefinition` pydantic model, `SkillSource` enum, YAML frontmatter parsing, token counting validation
- **Depends on**: `pydantic`, `tiktoken`

### Module 2: Skill File Registry
- **Path**: `parrot/memory/skills/file_registry.py` (new file)
- **Responsibility**: Scan skills directories, parse `.md` files, validate, build trigger index, support hot-add for learned skills, list available skills
- **Depends on**: Module 1 (SkillDefinition)

### Module 3: Skill Trigger Middleware
- **Path**: `parrot/memory/skills/middleware.py` (new file)
- **Responsibility**: Factory function that creates a `PromptMiddleware` instance detecting `/trigger` patterns, stripping prefix, setting `bot._active_skill`. Also handles reserved `/skills` and `/help` triggers.
- **Depends on**: Module 2 (SkillFileRegistry), `parrot/bots/middleware.py` (PromptMiddleware)

### Module 4: Mixin & Prompt Integration
- **Path**: `parrot/memory/skills/mixin.py` (extend existing)
- **Responsibility**: Wire SkillFileRegistry + middleware into bot lifecycle. Modify `create_system_prompt()` integration to inject/remove transient PromptLayer. Add `save_learned_skill()` method. Hot-add support.
- **Depends on**: Module 2, Module 3, `parrot/bots/abstract.py`, `parrot/bots/prompts/builder.py`

### Module 5: Learned Skill Persistence Tool
- **Path**: `parrot/memory/skills/tools.py` (extend existing)
- **Responsibility**: Adapt or add a tool (`SaveLearnedSkillTool`) that writes `.md` files to `skills/learned/` with proper frontmatter, validates, and hot-adds to registry. Available only when SkillsMixin is enabled.
- **Depends on**: Module 1, Module 2, Module 4

### Module 6: Tests
- **Path**: `tests/unit/test_skill_file_registry.py`, `tests/unit/test_skill_trigger_middleware.py`, `tests/integration/test_skill_system.py`
- **Responsibility**: Unit tests for registry loading, trigger detection, edge cases. Integration test for full flow.
- **Depends on**: All modules

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_skill_definition_valid` | Module 1 | Parse valid YAML frontmatter + body into SkillDefinition |
| `test_skill_definition_missing_fields` | Module 1 | Missing required fields raises ValidationError |
| `test_skill_definition_token_limit` | Module 1 | Body exceeding 1000 tokens is rejected |
| `test_skill_source_enum` | Module 1 | SkillSource.AUTHORED and .LEARNED values |
| `test_registry_load_authored` | Module 2 | Loads .md files from skills directory |
| `test_registry_load_learned` | Module 2 | Loads .md files from skills/learned/ |
| `test_registry_skip_malformed` | Module 2 | Malformed files logged as warning, skipped |
| `test_registry_name_collision_error` | Module 2 | Same name in authored + learned = error, both skipped |
| `test_registry_trigger_lookup` | Module 2 | `get("/resumen")` returns correct SkillDefinition |
| `test_registry_unknown_trigger` | Module 2 | `get("/unknown")` returns None |
| `test_registry_hot_add` | Module 2 | `add()` makes skill immediately available via `get()` |
| `test_registry_list_skills` | Module 2 | Returns all loaded skills |
| `test_registry_empty_dir` | Module 2 | Empty directory = empty registry, no errors |
| `test_middleware_detects_trigger` | Module 3 | `/resumen doc Q4` → strips prefix, sets active skill |
| `test_middleware_no_trigger` | Module 3 | Normal message passes through unchanged |
| `test_middleware_unknown_trigger` | Module 3 | `/unknown text` passes through unchanged (including `/`) |
| `test_middleware_trigger_only` | Module 3 | `/resumen` with no text → empty query, skill activated |
| `test_middleware_reserved_skills` | Module 3 | `/skills` returns skill listing, `/help` returns help |
| `test_middleware_compound_name` | Module 3 | `/analisis_financiero data` correctly splits trigger from text |
| `test_save_learned_skill_writes_md` | Module 5 | Tool creates .md file with valid frontmatter in learned/ |
| `test_save_learned_skill_collision` | Module 5 | Save rejected if name collides with existing skill |

### Integration Tests

| Test | Description |
|---|---|
| `test_skill_activate_in_prompt` | Full flow: user sends `/resumen text`, system prompt contains skill instructions, next request has no skill |
| `test_learned_skill_hot_add` | LLM saves skill via tool, immediately available for `/trigger` in same session |
| `test_skill_system_disabled` | Bot without SkillsMixin works normally, no middleware registered |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_skill_md():
    return """---
name: resumen
description: Resume textos largos en bullet points
triggers:
  - /resumen
source: authored
---

<skill-instructions>
Cuando el usuario solicite un resumen:
1. Identifica las ideas principales
2. Genera bullet points (max 7)
3. Manten el tono original
</skill-instructions>
"""

@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "learned").mkdir()
    return d
```

---

## 5. Acceptance Criteria

- [x] All unit tests pass (`pytest tests/unit/test_skill_*.py -v`)
- [ ] All integration tests pass (`pytest tests/integration/test_skill_system.py -v`)
- [ ] Authored skills load from `AGENTS_DIR/{agent_id}/skills/*.md` at configure time
- [ ] Learned skills load from `AGENTS_DIR/{agent_id}/skills/learned/*.md` at configure time
- [ ] Malformed skill files emit warning and are skipped (not errors)
- [ ] Name collisions between authored and learned skills are reported as errors (both skipped)
- [ ] `/trigger` at message start activates the corresponding skill for that request only
- [ ] Skill instructions appear in system prompt as a PromptLayer with fixed priority 90
- [ ] Skill template body is validated against 1000-token maximum at load time
- [ ] `/skills` and `/help` are reserved triggers that list available skills
- [ ] Learned skills saved via tool are immediately available in current session (hot-add)
- [ ] No breaking changes to existing PromptBuilder, PromptLayer, or PromptMiddleware APIs
- [ ] Bots without SkillsMixin are unaffected

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# These imports have been confirmed to work:
from parrot.bots.middleware import PromptMiddleware, PromptPipeline  # parrot/bots/middleware.py:1-50
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase  # parrot/bots/prompts/layers.py:22-46
from parrot.bots.prompts.builder import PromptBuilder  # parrot/bots/prompts/builder.py
from parrot.memory.skills.mixin import SkillRegistryMixin  # parrot/memory/skills/mixin.py:19
from parrot.memory.skills.models import SkillStatus, SkillCategory, SkillMetadata  # parrot/memory/skills/models.py
from parrot.memory.skills.store import SkillRegistry, create_skill_registry  # parrot/memory/skills/store.py
from parrot.memory.skills.tools import create_skill_tools  # parrot/memory/skills/tools.py
```

### Existing Class Signatures

```python
# parrot/bots/middleware.py:8
@dataclass
class PromptMiddleware:
    name: str
    priority: int = 0                                      # line 11 — lower runs first
    transform: Callable[[str, Dict[str, Any]], Awaitable[str]] = None  # line 12
    enabled: bool = True                                   # line 15
    async def apply(self, query: str, context: Dict[str, Any]) -> str:  # line 17

# parrot/bots/middleware.py:23
class PromptPipeline:
    def add(self, middleware: PromptMiddleware) -> None:    # line 30
    def remove(self, name: str) -> None:                   # line 34
    async def apply(self, query: str, context: Dict[str, Any] = None) -> str:  # line 37
    @property
    def has_middlewares(self) -> bool:                      # line 48

# parrot/bots/prompts/layers.py:22
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

# parrot/bots/prompts/layers.py:35
class RenderPhase(str, Enum):
    CONFIGURE = "configure"
    REQUEST = "request"

# parrot/bots/prompts/layers.py:50
@dataclass(frozen=True)
class PromptLayer:
    name: str
    priority: LayerPriority | int                          # line 63
    template: str                                          # line 64
    phase: RenderPhase = RenderPhase.REQUEST                # line 65
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None  # line 66
    required_vars: frozenset[str] = field(default_factory=frozenset)  # line 67
    def render(self, context: Dict[str, Any]) -> Optional[str]:  # line 69
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer:  # line 83

# parrot/bots/prompts/builder.py:196
class PromptBuilder:
    def add(self, layer: PromptLayer) -> PromptBuilder:    # ~line 130 — add/replace by name
    def remove(self, name: str) -> PromptBuilder:          # ~line 140 — remove by name
    def get(self, name: str) -> Optional[PromptLayer]:     # line 153
    def clone(self) -> PromptBuilder:                      # line 164
    def configure(self, context: Dict[str, Any]) -> None:  # line 176
    def build(self, context: Dict[str, Any]) -> str:       # line 196
    @property
    def layer_names(self) -> List[str]:                    # line 231

# parrot/memory/skills/mixin.py:19
class SkillRegistryMixin:
    enable_skill_registry: bool = True                     # line 35
    skill_registry_expose_tools: bool = True               # line 36
    skill_registry_inject_context: bool = True             # line 37
    skill_registry_auto_extract: bool = False              # line 38
    skill_registry_max_context_skills: int = 3             # line 39
    skill_registry_max_context_tokens: int = 1500          # line 40
    _skill_registry: Optional[SkillRegistry] = None        # line 43
    async def _configure_skill_registry(self) -> None:     # line 45
    async def _add_skill_tools(self) -> None:              # line 78
    async def get_skill_context(self, query, ...) -> str:  # line 97
    async def document_skill(self, name, content, ...) -> Optional[Skill]:  # line 117

# parrot/memory/skills/models.py:20-37
class SkillStatus(str, Enum):     # ACTIVE, DEPRECATED, REVOKED, DRAFT
class SkillCategory(str, Enum):   # TOOL_USAGE, WORKFLOW, DOMAIN_KNOWLEDGE, ...
class ContentType(str, Enum):     # FULL, DELTA

# parrot/memory/skills/models.py:47
@dataclass
class SkillMetadata:
    name: str                                              # line 49
    description: str                                       # line 50

# parrot/bots/abstract.py:790
def _build_prompt(
    self,
    user_context: str = "",
    vector_context: str = "",
    conversation_context: str = "",
    kb_context: str = "",
    pageindex_context: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> str:                                                  # returns assembled prompt via self._prompt_builder.build()

# parrot/bots/abstract.py:1690
async def create_system_prompt(
    self,
    user_context: str = "",
    vector_context: str = "",
    conversation_context: str = "",
    kb_context: str = "",
    pageindex_context: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    memory_context: Optional[str] = None,
    **kwargs
) -> str:                                                  # Uses self._prompt_builder if available, else legacy
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SkillTriggerMiddleware` | `PromptPipeline.add()` | Registered during configure | `middleware.py:30` |
| `SkillTriggerMiddleware` | `bot._active_skill` | Sets attribute on bot instance | `base.py:584-594` |
| Transient `PromptLayer` | `PromptBuilder.add()` / `remove()` | Injected in `create_system_prompt()` | `builder.py:130,140` |
| `SkillFileRegistry` | `AGENTS_DIR/{agent_id}/skills/` | Filesystem scan at configure | `mixin.py:59-61` |
| `SaveLearnedSkillTool` | `SkillFileRegistry.add()` | Hot-add after writing .md file | N/A (new) |
| `SkillRegistryMixin._configure_skill_file_registry()` | `_configure_skill_registry()` | Called alongside existing setup | `mixin.py:45` |

### Key Design Constraint: Middleware-to-Prompt Communication

The `PromptPipeline.apply()` (base.py:586) receives a **fresh dict literal** as context, and returns only the transformed query string. This context dict is NOT shared with `create_system_prompt()` (base.py:694).

**Solution:** The middleware stores the activated skill on the bot instance (`bot._active_skill`). The middleware receives the bot reference via closure (factory function pattern). `create_system_prompt()` checks `self._active_skill`, uses it, then clears it.

This is **not thread-safe** for concurrent requests on the same bot instance. If thread safety is needed later, use `contextvars.ContextVar` instead. For now, the instance attribute approach matches existing patterns (e.g., `self.status` on line 597).

### Does NOT Exist (Anti-Hallucination)

- ~~`PromptLayer.active`~~ — PromptLayer is frozen, has no mutable state
- ~~`PromptBuilder.skill_layers`~~ — no skill-specific slot exists
- ~~`LayerPriority.SKILL`~~ — no SKILL priority level in IntEnum (use int `90` directly)
- ~~`SkillDefinition`~~ — does not exist yet; must be created in Module 1
- ~~`SkillFileRegistry`~~ — does not exist yet; must be created in Module 2
- ~~`SkillTriggerMiddleware`~~ — does not exist yet; must be created in Module 3
- ~~`save_skill` tool~~ — existing tool is `DocumentSkillTool` (name="document_skill")
- ~~`SkillRegistryMixin.load_from_files()`~~ — no such method
- ~~`SkillRegistryMixin._active_skill`~~ — does not exist yet; must be added in Module 4
- ~~`SkillRegistryMixin._skill_file_registry`~~ — does not exist yet; must be added in Module 4
- ~~`PromptBuilder.add_transient()`~~ — no transient layer API; use `add()` then `remove()`
- ~~`PromptPipeline.context`~~ — pipeline does not store/share context between middleware and builder
- ~~`AbstractBot._active_skill`~~ — does not exist on AbstractBot; will be added via mixin

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use `python-frontmatter` or manual YAML parsing for `.md` file frontmatter
- Follow async-first design — `SkillFileRegistry.load()` is async for consistency even if I/O is sync
- Pydantic `BaseModel` for `SkillDefinition` with field validators
- `self.logger` for all warnings (malformed files, collisions)
- Factory function pattern for middleware creation (closure captures registry + bot reference)
- Fixed priority `90` for all skill layers (between CUSTOM=80 and any future higher layers)

### Known Risks / Gotchas

- **Thread safety**: `_active_skill` on bot instance is not thread-safe. Acceptable for now (matches existing `self.status` pattern). If concurrent request handling is added later, migrate to `contextvars.ContextVar`.
- **Token counting**: Using `tiktoken` assumes a specific tokenizer. The 1000-token limit is approximate — different LLM providers tokenize differently. Use `cl100k_base` (GPT-4 tokenizer) as a reasonable approximation.
- **`/` prefix collision**: If a user naturally types `/something` that isn't a skill, the message passes through unchanged. The `/` prefix is only consumed if it matches a registered trigger.
- **Hot-add race condition**: If `save_learned_skill()` and a concurrent request both access the registry dict simultaneously, there's a potential read-during-write. Mitigate with a simple `asyncio.Lock` on the registry.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `python-frontmatter` | `>=1.0` | Parse YAML frontmatter from .md files |
| `tiktoken` | `>=0.5` | Token counting for 1000-token limit validation |

Both are likely already in the dependency tree. Verify before adding.

---

## 8. Open Questions

All open questions from brainstorm have been resolved:

- [x] **Skill priority range**: Fixed at 90 (decision: Jesus Lara)
- [x] **Hot-reload for learned skills**: Available in current session via hot-add (decision: Jesus Lara)
- [x] **SkillRegistry unification**: Files only, no vector search needed (decision: Jesus Lara)
- [x] **`/help` and `/skills` built-in**: Reserved triggers, both supported (decision: Jesus Lara)

No remaining open questions.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Module 4 (mixin integration) depends on Modules 1-3. Module 5 (tool) depends on Modules 1-2. Sequential execution in a single worktree avoids merge coordination overhead for a Medium-effort feature (~5-6 tasks).
- **Cross-feature dependencies**: None. The modified files (`mixin.py`, `models.py`, `abstract.py`) are not touched by other in-flight specs.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-07 | Jesus Lara + Claude | Initial draft from brainstorm |

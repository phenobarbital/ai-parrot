# Brainstorm: Agent Skill System

**Date**: 2026-04-07
**Author**: Jesus Lara + Claude
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AI-Parrot agents currently have no lightweight mechanism for developers (or the agents themselves) to define reusable behavioral instructions that activate on demand. The existing `SkillRegistryMixin` provides learned-skill storage with vector search, versioning, and FAISS indexing — but it's heavy infrastructure designed for runtime discovery, not for simple "when the user says `/resumen`, follow these instructions" scenarios.

**Who is affected:**
- **Developers** who want to give their agents specialized behaviors without writing Python code.
- **End users** who want predictable, trigger-based agent responses for common tasks.
- **Agents themselves** who could learn and persist useful patterns as reusable skills.

**Why now:** As agents become more configurable via `AGENTS_DIR/{agent_id}/` (KB, queries, config.yaml), skills are the natural next step — behavioral templates that live alongside knowledge bases.

## Constraints & Requirements

- Skills are **per-bot** — no global skill registry.
- Skills live in `AGENTS_DIR/{agent_id}/skills/` (authored) and `AGENTS_DIR/{agent_id}/skills/learned/` (LLM-generated).
- Triggers are **deterministic only**: `/skill_name` at the start of the user message. No regex, no embeddings, no keyword matching.
- Skill names: single word/phrase with `_` or `-`, no spaces (e.g., `resumen`, `analisis_financiero`).
- Skills are **per-request, atomic** — injected as a transient `PromptLayer`, discarded after the request.
- Skill template body must not exceed **1000 tokens**.
- Registry is **eager** — all skills loaded into memory at bot configure time.
- Malformed skills emit a **warning** and are skipped (not errors).
- If an authored skill and a learned skill share the same name, it's a **load-time error** (reported, both skipped).
- Skills do **not** declare tool dependencies — if a skill references a tool the bot doesn't have, it fails at runtime.
- Learned skills are created autonomously by the LLM via a `save_skill` tool, only available to agents with `SkillsMixin` enabled.
- A unified `Skill` model covers both authored and learned; `source: authored | learned` differentiates them.

---

## Options Explored

### Option A: Middleware + Transient Layer Injection

The skill system is implemented as two cooperating components:

1. **`SkillTriggerMiddleware`** (a `PromptMiddleware`) — intercepts user messages, detects `/trigger` patterns, strips the trigger prefix, and marks the activated skill in the request context.
2. **Transient `PromptLayer` injection** — during `build()`, a skill layer is dynamically added to the prompt builder for that request only, using the skill's markdown body as the template.

The `SkillFileRegistry` scans `AGENTS_DIR/{agent_id}/skills/` at configure time, parses YAML frontmatter + markdown body from each `.md` file, validates, and indexes by trigger name in a dict.

**Flow:**
```
User: "/resumen documento Q4"
  → SkillTriggerMiddleware.transform()
    → detects "/resumen", looks up registry
    → strips prefix → query becomes "documento Q4"
    → sets context["_active_skill"] = SkillDefinition
  → PromptBuilder.build() (in _build_prompt or create_system_prompt)
    → checks context["_active_skill"]
    → temporarily adds skill as PromptLayer(priority=SKILL, phase=REQUEST)
    → renders all layers including skill
    → removes transient layer after render
  → LLM receives system prompt with skill instructions
```

**Pros:**
- Leverages existing `PromptMiddleware` and `PromptLayer` — zero changes to core classes.
- Clean separation: middleware handles detection, builder handles injection.
- Transient layer means no state leaks between requests.
- Eager registry is just a dict lookup — O(1) at request time.
- Follows the same `AGENTS_DIR/{agent_id}/` pattern as KB and queries.

**Cons:**
- Requires a small integration point in `_build_prompt()` or `create_system_prompt()` to check for active skills.
- Middleware modifies the query (strips prefix) — needs care to preserve original for logging.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pyyaml` or `python-frontmatter` | Parse YAML frontmatter from .md files | Already in project deps |
| `tiktoken` | Token counting for 1000-token limit | Already used in project |

**Existing Code to Reuse:**
- `parrot/bots/middleware.py` — `PromptMiddleware` dataclass and `PromptPipeline` class (entire file, 50 lines)
- `parrot/bots/prompts/layers.py` — `PromptLayer`, `LayerPriority`, `RenderPhase` (lines 1-60)
- `parrot/bots/prompts/builder.py` — `PromptBuilder.add()` / `PromptBuilder.remove()` for transient layer management
- `parrot/memory/skills/mixin.py` — `SkillRegistryMixin._configure_skill_registry()` pattern (lines 45-60) for directory resolution
- `parrot/memory/skills/models.py` — `SkillMetadata`, `SkillCategory`, `SkillStatus` enums for the unified model
- `parrot/bots/stores/local.py` — `LocalKBMixin._get_agent_kb_directory()` pattern for per-agent directory resolution

---

### Option B: Pure Middleware Approach (No Layer Injection)

The middleware detects the trigger AND injects the skill instructions directly into the query or context, bypassing the layer system entirely. The skill content is prepended to the user message or appended to an existing context variable.

**Flow:**
```
User: "/resumen documento Q4"
  → SkillTriggerMiddleware.transform()
    → detects "/resumen", looks up registry
    → returns: "[SKILL: resumen]\n{skill_body}\n[/SKILL]\ndocumento Q4"
  → Normal prompt building (no changes)
  → LLM sees skill instructions as part of user message
```

**Pros:**
- Zero changes to PromptBuilder or layer system.
- Simplest implementation — everything lives in one middleware.
- No integration points needed in base bot classes.

**Cons:**
- Skill instructions mixed into user message space, not system prompt — less authoritative for the LLM.
- No priority control — can't position skill instructions relative to other system prompt sections.
- Breaks the architectural principle of system instructions in system prompt vs user content in user message.
- Token counting is harder (skill tokens compete with user message tokens, not system prompt budget).

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | Parse YAML frontmatter | Same as Option A |

**Existing Code to Reuse:**
- `parrot/bots/middleware.py` — `PromptMiddleware` and `PromptPipeline`

---

### Option C: Skill as a Dedicated Layer Type (New Layer Subclass)

Introduce a `SkillLayer` subclass of `PromptLayer` with built-in trigger matching, token validation, and source tracking. The PromptBuilder is extended with a `skill_layers` slot that holds registered skills, and the `build()` method is modified to activate/deactivate skill layers based on request context.

**Flow:**
```
configure():
  → SkillFileRegistry loads skills
  → Each skill becomes a SkillLayer(active=False)
  → All SkillLayers registered in PromptBuilder.skill_layers

build(context):
  → Checks context["_trigger"]
  → Sets matching SkillLayer.active = True
  → Renders all layers (skills included if active)
  → Resets SkillLayer.active = False
```

**Pros:**
- Type-safe: `SkillLayer` carries source, token_count, trigger as first-class attributes.
- PromptBuilder is skill-aware — could enable future features like skill introspection, multi-skill activation.
- Clean abstraction boundary.

**Cons:**
- Modifies `PromptLayer` (currently frozen dataclass) — requires unfreezing or a parallel type.
- Modifies `PromptBuilder.build()` — core system change for a feature that can be done without it.
- Over-engineering for the current scope (per-request, atomic, simple trigger matching).
- `PromptLayer` is frozen by design; mutable `active` flag contradicts immutability principle.

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | Parse YAML frontmatter | Same as Option A |
| `tiktoken` | Token counting | Same as Option A |

**Existing Code to Reuse:**
- `parrot/bots/prompts/layers.py` — Would need modification (PromptLayer subclass)
- `parrot/bots/prompts/builder.py` — Would need modification (skill_layers slot, build() changes)
- `parrot/memory/skills/models.py` — Enums and base models

---

## Recommendation

**Option A** is recommended because:

- It achieves the goal with **zero modifications to core classes** (`PromptLayer`, `PromptBuilder`). The middleware and transient layer injection use the existing public API exactly as designed.
- The separation between detection (middleware) and injection (transient layer) follows the existing architectural pattern where middleware transforms queries and the builder assembles prompts.
- Option B is simpler but violates the principle of system-level instructions belonging in the system prompt. Skill instructions are behavioral guidance for the LLM — they belong in the system prompt, not the user message.
- Option C is architecturally elegant but over-engineered: modifying a frozen dataclass and core builder for what is fundamentally a "add a layer, render, remove it" operation is unnecessary complexity.
- The tradeoff is a small integration point in `_build_prompt()` — acceptable given that this method already handles knowledge context, user context, and other dynamic content assembly.

---

## Feature Description

### User-Facing Behavior

**For developers (skill authors):**

Create a `.md` file in `AGENTS_DIR/{agent_id}/skills/`:

```markdown
---
name: resumen
description: Resume textos largos en bullet points concisos
triggers:
  - /resumen
source: authored
---

<skill-instructions>
Cuando el usuario solicite un resumen:
1. Identifica las ideas principales del texto proporcionado
2. Genera un resumen en bullet points (maximo 7 puntos)
3. Manten el tono y registro del texto original
4. Si el texto supera 2000 palabras, agrupa por secciones tematicas
</skill-instructions>
```

The agent automatically loads it at startup. Users can then type `/resumen documento Q4` and the agent follows those instructions for that single request.

**For end users (chatting with the agent):**

- Type `/resumen <text>` — agent activates the "resumen" skill for this message only.
- Type a normal message — no skill activated, agent behaves normally.
- Ask "what skills do you have?" — agent can query the registry and list available skills (not via prompt injection, but via a tool or direct registry query).

**For agents (learned skills):**

When the LLM recognizes that a user has taught it a useful, reusable procedure, it autonomously calls `save_skill(name, content, description, triggers)` which persists a `.md` file in `AGENTS_DIR/{agent_id}/skills/learned/`. This skill is available from the next session (or immediately if the registry supports hot-reload).

### Internal Behavior

**At configure time:**
1. `SkillFileRegistry` scans `AGENTS_DIR/{agent_id}/skills/` and `skills/learned/`.
2. For each `.md` file: parse YAML frontmatter, validate required fields, check token limit (<=1000), check for name collisions.
3. Build an in-memory dict: `trigger_name → SkillDefinition`.
4. Warnings for malformed files (skipped). Errors for name collisions (both skipped).
5. `SkillTriggerMiddleware` is registered in the bot's `PromptPipeline`.

**At request time:**
1. `SkillTriggerMiddleware.transform(query, context)`:
   - Check if query starts with `/`.
   - Extract trigger name (first token after `/`, split on space).
   - Look up in registry dict.
   - If found: strip trigger from query, set `context["_active_skill"]`.
   - If not found: pass query through unchanged.
2. In `_build_prompt()` or `create_system_prompt()`:
   - Check `context.get("_active_skill")`.
   - If present: create transient `PromptLayer` from skill template, add to builder.
   - Call `build()` — skill layer renders into system prompt.
   - Remove transient layer after render (or use a fresh builder clone).

**Learned skill creation:**
1. The LLM decides a user interaction is worth persisting.
2. Calls `save_skill` tool (only available via `SkillsMixin`).
3. Tool writes `.md` file to `skills/learned/` with proper frontmatter.
4. Registry is updated in-memory (hot-add without full rescan).

### Edge Cases & Error Handling

| Case | Behavior |
|---|---|
| Malformed YAML frontmatter | Warning logged, skill file skipped |
| Missing required field (name, description, triggers) | Warning logged, skill file skipped |
| Skill body exceeds 1000 tokens | Warning logged, skill file skipped |
| Name collision (authored vs learned) | Error logged, both skills skipped |
| `/unknown_trigger` in user message | No skill activated, message passed through unchanged (including the `/`) |
| Skill references a tool the bot doesn't have | LLM sees the instruction but tool call fails — runtime error, not load error |
| Empty skills directory | No skills loaded, no middleware registered (or middleware is no-op) |
| User sends just `/resumen` with no text | Skill activates, query is empty string — LLM handles it (may ask for input) |
| Multiple triggers in one message (`/resumen /traducir`) | Only first trigger matches (single skill per request) |
| Learned skill saved with trigger that collides with authored | Error at save time, save rejected |

---

## Capabilities

### New Capabilities
- `skill-file-registry`: Filesystem-based skill discovery and loading from markdown files with YAML frontmatter
- `skill-trigger-middleware`: Deterministic `/trigger` detection and query transformation middleware
- `skill-prompt-injection`: Transient PromptLayer injection for activated skills
- `skill-learned-persistence`: LLM-autonomous skill creation and persistence to `skills/learned/`
- `skill-listing`: Registry-based skill catalog query (available skills and descriptions)

### Modified Capabilities
- `skill-registry-mixin`: Extend existing `SkillRegistryMixin` to integrate with `SkillFileRegistry` — authored skills loaded from files, learned skills created via existing `document_skill` / `save_skill` tools but now persisted as `.md` files
- `prompt-builder-integration`: Small hook in `_build_prompt()` to check for active skill and inject transient layer

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/memory/skills/mixin.py` | extends | Add SkillFileRegistry initialization, middleware registration |
| `parrot/memory/skills/models.py` | extends | Add `SkillDefinition` pydantic model for parsed .md files, add `source` field to unified model |
| `parrot/bots/base.py` (`_build_prompt`) | modifies | Add ~10 lines to check `context["_active_skill"]` and inject transient layer |
| `parrot/bots/middleware.py` | depends on | Uses existing `PromptMiddleware` / `PromptPipeline` — no changes needed |
| `parrot/bots/prompts/layers.py` | depends on | Uses existing `PromptLayer`, `LayerPriority` — no changes needed |
| `parrot/bots/prompts/builder.py` | depends on | Uses existing `add()` / `remove()` — no changes needed |
| `AGENTS_DIR/{agent_id}/skills/` | new directory | Authored skill .md files |
| `AGENTS_DIR/{agent_id}/skills/learned/` | new directory | LLM-generated skill .md files |

---

## Code Context

### User-Provided Code

No code snippets provided during brainstorming. Skill markdown format was discussed:

```markdown
# Source: user-provided (discussion)
---
name: resumen
description: Resume textos largos en bullet points concisos
triggers:
  - /resumen
source: authored
priority: 45
---

<skill-instructions>
Cuando el usuario solicite un resumen...
</skill-instructions>
```

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/bots/middleware.py:8
@dataclass
class PromptMiddleware:
    name: str
    priority: int = 0
    transform: Callable[[str, Dict[str, Any]], Awaitable[str]] = None
    enabled: bool = True
    async def apply(self, query: str, context: Dict[str, Any]) -> str:  # line 17

# From parrot/bots/middleware.py:23
class PromptPipeline:
    def add(self, middleware: PromptMiddleware) -> None:  # line 30
    def remove(self, name: str) -> None:  # line 34
    async def apply(self, query: str, context: Dict[str, Any] = None) -> str:  # line 37
    @property
    def has_middlewares(self) -> bool:  # line 48

# From parrot/bots/prompts/layers.py:50
@dataclass(frozen=True)
class PromptLayer:
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    def render(self, context: Dict[str, Any]) -> Optional[str]:  # line 69
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer:  # line 83

# From parrot/bots/prompts/layers.py:22
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

# From parrot/bots/prompts/layers.py:35
class RenderPhase(str, Enum):
    CONFIGURE = "configure"
    REQUEST = "request"

# From parrot/memory/skills/mixin.py:19
class SkillRegistryMixin:
    enable_skill_registry: bool = True  # line 35
    skill_registry_expose_tools: bool = True  # line 36
    skill_registry_inject_context: bool = True  # line 37
    skill_registry_auto_extract: bool = False  # line 38
    skill_registry_max_context_skills: int = 3  # line 39
    skill_registry_max_context_tokens: int = 1500  # line 40
    _skill_registry: Optional[SkillRegistry] = None  # line 43
    async def _configure_skill_registry(self) -> None:  # line 45

# From parrot/memory/skills/models.py:20
class SkillStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"
    DRAFT = "draft"

# From parrot/memory/skills/models.py:28
class SkillCategory(str, Enum):
    TOOL_USAGE = "tool_usage"
    WORKFLOW = "workflow"
    DOMAIN_KNOWLEDGE = "domain"
    ERROR_HANDLING = "error_handling"
    USER_PREFERENCE = "user_preference"
    INTEGRATION = "integration"
    OPTIMIZATION = "optimization"
    GENERAL = "general"

# From parrot/memory/skills/models.py:47
@dataclass
class SkillMetadata:
    name: str
    description: str  # line 50
```

#### Verified Imports

```python
# These imports have been confirmed to work:
from parrot.bots.middleware import PromptMiddleware, PromptPipeline  # parrot/bots/middleware.py:1-50
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase  # parrot/bots/prompts/layers.py:1-60
from parrot.bots.prompts.builder import PromptBuilder  # parrot/bots/prompts/builder.py
from parrot.memory.skills.mixin import SkillRegistryMixin  # parrot/memory/skills/mixin.py
from parrot.memory.skills.models import SkillStatus, SkillCategory, SkillMetadata  # parrot/memory/skills/models.py
from parrot.memory.skills.store import SkillRegistry, create_skill_registry  # parrot/memory/skills/store.py
from parrot.memory.skills.tools import create_skill_tools  # parrot/memory/skills/tools.py
```

#### Key Attributes & Constants

- `LayerPriority.CUSTOM` → `80` (parrot/bots/prompts/layers.py:32) — skills could use priority range 90-99 to sit after CUSTOM
- `RenderPhase.REQUEST` → `"request"` (parrot/bots/prompts/layers.py:45) — skills always render at request time
- `SkillRegistryMixin._skill_registry` → `Optional[SkillRegistry]` (parrot/memory/skills/mixin.py:43)
- `PromptMiddleware.priority` → `int` (parrot/bots/middleware.py:11) — lower runs first

### Does NOT Exist (Anti-Hallucination)

- ~~`PromptLayer.active`~~ — PromptLayer is frozen, has no mutable state
- ~~`PromptBuilder.skill_layers`~~ — no skill-specific slot exists on PromptBuilder
- ~~`LayerPriority.SKILL`~~ — no SKILL priority level exists in the IntEnum
- ~~`SkillDefinition`~~ — does not exist yet; needs to be created as pydantic model
- ~~`SkillFileRegistry`~~ — does not exist yet; needs to be created
- ~~`SkillTriggerMiddleware`~~ — does not exist yet; needs to be created
- ~~`save_skill` tool~~ — the existing tool is named `document_skill` (DocumentSkillTool in tools.py)
- ~~`SkillRegistryMixin.load_from_files()`~~ — no file-loading method exists on the mixin
- ~~`PromptBuilder.add_transient()`~~ — no transient layer API exists; must use add()/remove() manually

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The feature decomposes into at least 3 independent components:
  1. `SkillDefinition` model + `SkillFileRegistry` (pure data, no bot dependencies)
  2. `SkillTriggerMiddleware` (depends only on `PromptMiddleware`)
  3. Integration into `SkillRegistryMixin` + `_build_prompt()` (depends on 1 and 2)
  
  Components 1 and 2 can be developed in parallel; 3 is sequential after both.

- **Cross-feature independence**: No conflicts with in-flight specs. The files modified (`mixin.py`, `models.py`, `base.py`) are not currently being changed by other features.

- **Recommended isolation**: `per-spec` — the feature is cohesive enough that all tasks run sequentially in one worktree, with components 1+2 possibly as parallel tasks within the same worktree.

- **Rationale**: The integration task (3) needs both the model and the middleware, so a single worktree avoids merge coordination. The total scope is Medium effort (~4-5 tasks), manageable sequentially.

---

## Open Questions

- [ ] **Skill priority range**: Should skills use a fixed priority (e.g., 90) or should the frontmatter `priority` field allow arbitrary placement? Risk: a skill at priority 15 could override PRE_INSTRUCTIONS. — *Owner: Jesus Lara*
- [ ] **Hot-reload for learned skills**: When the LLM saves a new skill at runtime, should it be immediately available in the current session or only after restart? Option A describes hot-add but this adds complexity. — *Owner: Jesus Lara*
- [ ] **Existing SkillRegistry unification**: The current `SkillRegistry` (store.py) uses FAISS + Redis + JSON persistence. The new `SkillFileRegistry` uses plain .md files. Should learned skills write to both (file for human readability, store for vector search), or migrate entirely to files? — *Owner: Jesus Lara*
- [ ] **`/help` or `/skills` built-in**: Should there be a reserved trigger (e.g., `/skills`) that lists available skills, or is this purely via the registry query method? — *Owner: Jesus Lara*

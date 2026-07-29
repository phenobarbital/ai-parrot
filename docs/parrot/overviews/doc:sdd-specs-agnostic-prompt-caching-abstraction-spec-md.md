---
type: Wiki Overview
title: 'Feature Specification: Provider-Agnostic Prompt Caching'
id: doc:sdd-specs-agnostic-prompt-caching-abstraction-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot agents rebuild their full system prompt on every LLM call — identity,
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.bots.prompts.agent_context
  rel: mentions
- concept: mod:parrot.bots.prompts.layers
  rel: mentions
- concept: mod:parrot.bots.prompts.segments
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.clients.base
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events.client
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Provider-Agnostic Prompt Caching

**Feature ID**: FEAT-181
**Date**: 2026-05-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents rebuild their full system prompt on every LLM call — identity,
security rules, knowledge context, agent-context documents — even when 80%+ of
that content is static across calls. LLM providers (Anthropic, OpenAI, Gemini)
each offer server-side prompt caching that can dramatically cut latency and cost
for repeated static prefixes, but each uses a different API primitive. There is
currently **zero prompt-caching code in `parrot/`** and no mechanism to load a
per-agent context document from the filesystem.

This came up while designing the `GitHubReviewer` agent, which sends the same
large system prompt + repo-level context on every PR review.

### Goals

- **G1**: Expose a single `prompt_caching: bool = False` flag at the
  `AbstractBot` / `PromptBuilder` level that activates provider-side prompt
  caching for any supported provider.
- **G2**: Each `AbstractClient` subclass translates cacheable segments to its
  native primitive — Anthropic `cache_control` blocks, OpenAI automatic prefix
  caching, Gemini `CachedContent` — and degrades to a debug-level no-op for
  unsupported providers.
- **G3**: Ship an `AgentContextLoader` that reads per-agent context files from
  `AGENT_CONTEXT_DIR/<agent_id>.md` with mtime-based invalidation.
- **G4**: Auto-inject an `AGENT_CONTEXT_LAYER` into the `PromptBuilder` when
  `prompt_caching=True`, so consumers like `GitHubReviewer` opt in with a
  single flag.
- **G5**: Emit lifecycle events (`PromptCacheAppliedEvent`,
  `PromptCacheSkippedEvent`) so cache cost/benefit is observable per call.

### Non-Goals (explicitly out of scope)

- Client-side caching of LLM response bodies.
- Multi-tenant per-user cache-key segmentation (single global key per
  `(agent_id, model)` is sufficient for v1).
- Caching tool definitions — Anthropic supports `cache_control` on tools but
  v1 caches only the system block.
- Migrating `GitHubReviewer` to a full `PromptBuilder` — the context layer
  composes on top of the existing `system_prompt=` path.
- Adding cache support to providers that do not document it (Groq, Grok,
  HuggingFace, NVIDIA, LocalLLM, vLLM, OpenRouter) — these degrade to no-op.
- Changing the `PromptBuilder.build()` return type or contract.
- Runtime fallback-on-failure (rejected in proposal — see
  `sdd/proposals/agnostic-prompt-caching-abstraction.proposal.md`).

---

## 2. Architectural Design

### Overview

The existing `PromptBuilder` two-phase render (CONFIGURE once, REQUEST per call)
maps naturally onto cacheable vs. non-cacheable boundaries. This feature adds:

1. A `CacheableSegment` dataclass representing one chunk of system prompt with a
   cache-eligibility flag.
2. A `build_segments()` method on `PromptBuilder` that derives cache boundaries
   from `layer.phase` (CONFIGURE → cacheable, REQUEST → not cacheable), with
   per-layer override via a new `cacheable` attribute on `PromptLayer`.
3. A per-client `_apply_cache_hints()` hook that translates segments to the
   provider's native caching primitive.
4. An `AgentContextLoader` + `AGENT_CONTEXT_LAYER` that auto-injects a
   CONFIGURE-phase cacheable layer containing the per-agent context document.

The flag is boolean (`prompt_caching: bool = False`). Silent provider-side
degradation is the default. Consumers wanting richer control can be added later.

When `prompt_caching=True` and a `PromptBuilder` is in use, the
`AGENT_CONTEXT_LAYER` is auto-injected during `AbstractBot.__init__`. If no
per-agent file exists, the layer renders empty and logs at INFO once on
`configure()`.

### Component Diagram

```
AbstractBot (prompt_caching=True)
    │
    ├── PromptBuilder
    │     ├── IDENTITY_LAYER         (CONFIGURE, cacheable=True)
    │     ├── AGENT_CONTEXT_LAYER    (CONFIGURE, cacheable=True)  ← NEW
    │     ├── SECURITY_LAYER         (CONFIGURE, cacheable=True)
    │     ├── KNOWLEDGE_LAYER        (REQUEST,   cacheable=False)
    │     └── ...
    │     │
    │     └── build_segments(ctx)  → List[CacheableSegment]  ← NEW
    │
    └── AbstractClient.ask(system_prompt=segments)
          │
          ├── ClaudeClient._apply_cache_hints()     → cache_control blocks
          ├── OpenAIClient._apply_cache_hints()      → automatic (prefix ≥1024)
          ├── GoogleClient._apply_cache_hints()      → CachedContent resource
          └── GroqClient._apply_cache_hints()        → no-op
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PromptBuilder` (`builder.py:20`) | extends | New `prompt_caching` ctor kwarg + `build_segments()` method. `build()` unchanged. |
| `PromptLayer` (`layers.py:50`) | extends | New `cacheable: bool` attribute, default derived from `phase`. |
| `AbstractBot.__init__` (`abstract.py:247`) | extends | New `prompt_caching` kwarg; auto-injects `AGENT_CONTEXT_LAYER` when True. |
| `AbstractClient` (`base.py:242`) | extends | New `_apply_cache_hints()` default no-op; `system_prompt` Union-widened. |
| `ClaudeClient` (`claude.py`) | overrides | `_apply_cache_hints()` → `cache_control` blocks on system content. |
| `OpenAIClient` (`gpt.py`) | overrides | `_apply_cache_hints()` → no shape change (prefix caching is automatic). |
| `GoogleClient` (`google/client.py`) | overrides | `_apply_cache_hints()` → `CachedContent` resource when ≥ threshold. |
| `conf.py` | adds constant | New `AGENT_CONTEXT_DIR`. |
| Lifecycle events (`events/client.py`) | extends | Two new event dataclasses alongside existing client events. |

### Data Models

```python
from dataclasses import dataclass, field
from typing import Optional, Literal, List

@dataclass(frozen=True)
class CacheableSegment:
    """One chunk of the system prompt with a cache-eligibility flag."""
    text: str
    cacheable: bool
    ttl_hint: Optional[Literal['short', 'long']] = None  # reserved, no translation in v1
```

### New Public Interfaces

```python
# ── PromptBuilder additions ──
class PromptBuilder:
    def __init__(self, layers=None, *, prompt_caching: bool = False): ...
    def build_segments(self, context: Dict[str, Any]) -> List[CacheableSegment]: ...

# ── PromptLayer addition ──
@dataclass(frozen=True)
class PromptLayer:
    cacheable: bool  # default: True if phase==CONFIGURE, False if REQUEST

# ── AbstractClient addition ──
class AbstractClient:
    _min_cache_tokens: int = 0  # subclasses override
    def _apply_cache_hints(
        self, payload: Dict[str, Any], segments: List[CacheableSegment]
    ) -> Dict[str, Any]: ...  # default no-op, returns payload unchanged

# ── AbstractBot.__init__ addition ──
class AbstractBot:
    def __init__(self, ..., prompt_caching: bool = False, ...): ...

# ── AgentContextLoader ──
def load_agent_context(agent_id: str) -> str: ...  # sync, lru_cache by (path, mtime)
```

---

## 3. Module Breakdown

### Module 1: CacheableSegment + PromptLayer.cacheable

- **Path**: `parrot/bots/prompts/segments.py` (new) + `parrot/bots/prompts/layers.py`
- **Responsibility**: Define `CacheableSegment` dataclass. Add `cacheable: bool`
  attribute to `PromptLayer` with default derived from `phase`.
- **Depends on**: none

### Module 2: PromptBuilder.build_segments()

- **Path**: `parrot/bots/prompts/builder.py`
- **Responsibility**: Add `prompt_caching: bool = False` ctor kwarg and
  `build_segments(context) -> List[CacheableSegment]` method that sorts layers
  by priority, renders each, and tags with `layer.cacheable`.
- **Depends on**: Module 1

### Module 3: AgentContextLoader + AGENT_CONTEXT_LAYER

- **Path**: `parrot/bots/prompts/agent_context.py` (new) + `parrot/conf.py`
- **Responsibility**: `load_agent_context(agent_id) -> str` with sync
  `@functools.lru_cache` keyed on `(path, st_mtime)`. `AGENT_CONTEXT_LAYER` is
  a CONFIGURE-phase, `cacheable=True` `PromptLayer`. `AGENT_CONTEXT_DIR`
  constant in `conf.py`.
- **Depends on**: Module 1

### Module 4: AbstractBot prompt_caching integration

- **Path**: `parrot/bots/abstract.py`
- **Responsibility**: Accept `prompt_caching: bool = False` kwarg. When True and
  a `PromptBuilder` is in use, auto-inject `AGENT_CONTEXT_LAYER`. Thread
  segments through to the client at call time (call `build_segments()` instead
  of `build()` when the flag is on).
- **Depends on**: Module 2, Module 3

### Module 5: AbstractClient._apply_cache_hints (base)

- **Path**: `parrot/clients/base.py`
- **Responsibility**: Declare `_min_cache_tokens: int = 0` class attribute and
  `_apply_cache_hints(payload, segments) -> payload` (default no-op). Widen
  `system_prompt` type to `Optional[Union[str, List[CacheableSegment]]]` on
  `ask()`, `ask_stream()`, and `complete()`. When segments are received,
  dispatch through `_apply_cache_hints()` before SDK invocation.
- **Depends on**: Module 1

### Module 6: ClaudeClient cache translator

- **Path**: `parrot/clients/claude.py`
- **Responsibility**: Override `_apply_cache_hints()`. Convert cacheable
  segments into `system: [{type: 'text', text: ..., cache_control: {type:
  'ephemeral'}}]` list-of-blocks form. Aggregate into ≤4 blocks (Anthropic
  hard limit). Keep string form when segments are absent. `_min_cache_tokens =
  1024`.
- **Depends on**: Module 5

### Module 7: OpenAI cache translator

- **Path**: `parrot/clients/gpt.py`
- **Responsibility**: Override `_apply_cache_hints()`. OpenAI caches prefixes
  ≥1024 tokens automatically. The translator is a pass-through that emits
  `PromptCacheAppliedEvent` when segments are present. `_min_cache_tokens =
  1024`.
- **Depends on**: Module 5

### Module 8: Google/Gemini cache translator

- **Path**: `parrot/clients/google/client.py` (+ shared helper for
  `analysis.py`, `generation.py`)
- **Responsibility**: Override `_apply_cache_hints()`. Estimate token count; if
  ≥ `_min_cache_tokens`, call `client.caches.create(...)` and pass
  `cached_content=<name>` to `generate_content`; otherwise skip with debug log +
  `PromptCacheSkippedEvent(reason="below_threshold")`. `_min_cache_tokens =
  4096` (subclass/model-specific overrides for Flash variants at 32768).
- **Depends on**: Module 5

### Module 9: Lifecycle events

- **Path**: `parrot/core/events/lifecycle/events/client.py`
- **Responsibility**: Add `PromptCacheAppliedEvent` and
  `PromptCacheSkippedEvent` as frozen dataclasses alongside existing client
  events. Mirror the `_system_prompt_hash` pattern for segment hashes.
- **Depends on**: none (parallel with Module 1)

### Module 10: GitHubReviewer opt-in

- **Path**: `parrot/bots/github_reviewer.py`
- **Responsibility**: Opt in via `kwargs.setdefault("prompt_caching", True)` in
  `__init__`. Document the Gemini-threshold caveat in the class docstring.
- **Depends on**: Module 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_cacheable_segment_creation` | 1 | Validates `CacheableSegment` fields and defaults |
| `test_prompt_layer_cacheable_default` | 1 | CONFIGURE layers default `cacheable=True`, REQUEST default `False` |
| `test_prompt_layer_cacheable_override` | 1 | Explicit `cacheable=False` on a CONFIGURE layer |
| `test_build_segments_basic` | 2 | Correct segmentation with mixed CONFIGURE/REQUEST layers |
| `test_build_segments_flag_off` | 2 | When `prompt_caching=False`, `build_segments()` returns empty or raises |
| `test_build_unchanged` | 2 | `build()` output is identical pre- and post-change for each preset |
| `test_agent_context_loader_read` | 3 | Reads file, returns content |
| `test_agent_context_loader_missing_file` | 3 | Missing file returns empty string |
| `test_agent_context_loader_mtime_invalidation` | 3 | Content updates when mtime changes |
| `test_apply_cache_hints_noop_base` | 5 | Base class no-op returns payload unchanged |
| `test_claude_cache_hints` | 6 | Produces list-of-blocks with `cache_control` |
| `test_claude_cache_hints_max_4_blocks` | 6 | Aggregates into ≤4 blocks |
| `test_claude_no_segments_string_form` | 6 | String system_prompt produces today's payload exactly |
| `test_openai_cache_hints_passthrough` | 7 | No payload shape change, event emitted |
| `test_gemini_above_threshold` | 8 | Creates `CachedContent` when ≥ threshold |
| `test_gemini_below_threshold` | 8 | Skips with debug log + `PromptCacheSkippedEvent` |
| `test_cache_applied_event` | 9 | Event fields and serialization |
| `test_cache_skipped_event_reasons` | 9 | All reason variants |
| `test_github_reviewer_opts_in` | 10 | `prompt_caching=True` set by default |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_anthropic_caching` | Full pipeline: PromptBuilder → build_segments → ClaudeClient payload |
| `test_feature_off_regression` | Feature-off path produces identical payload to today (regression guard) |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_builder():
    """PromptBuilder with prompt_caching=True and a mix of layers."""
    from parrot.bots.prompts import PromptBuilder
    return PromptBuilder.default()  # with prompt_caching=True override

@pytest.fixture
def sample_segments():
    """Pre-built CacheableSegment list for client tests."""
    from parrot.bots.prompts.segments import CacheableSegment
    return [
        CacheableSegment(text="You are a helpful agent.", cacheable=True),
        CacheableSegment(text="User context: ...", cacheable=False),
    ]
```

---

## 5. Acceptance Criteria

- [ ] `PromptBuilder.build()` output is byte-identical pre- and post-change for all existing presets (`default`, `minimal`, `voice`, `agent`, `rag`).
- [ ] `build_segments()` returns correct cacheable/non-cacheable partitioning based on layer phase.
- [ ] `AgentContextLoader` reads per-agent files, caches by mtime, returns empty string for missing files.
- [ ] `AGENT_CONTEXT_DIR` constant follows the `config.get(..., fallback=...)` convention in `conf.py`.
- [ ] Anthropic client produces `cache_control` blocks when segments present, string form otherwise.
- [ ] Anthropic client aggregates cacheable segments into ≤4 blocks.
- [ ] OpenAI client passes segments through without shape change.
- [ ] Gemini client creates `CachedContent` when ≥ threshold, skips otherwise.
- [ ] Unsupported providers (Groq, Grok, etc.) produce identical payloads with or without the flag.
- [ ] `PromptCacheAppliedEvent` and `PromptCacheSkippedEvent` are emitted correctly.
- [ ] Segment hashes in events use SHA-256, never raw content.
- [ ] Feature-off regression test: calling `ask()` with `system_prompt="..."` (string) produces identical behavior to today.
- [ ] `GitHubReviewer` opts in by default; Gemini threshold caveat documented.
- [ ] All unit tests pass (`pytest tests/ -v -k prompt_cach`)
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase  # layers.py:22-47
from parrot.bots.prompts.builder import PromptBuilder  # builder.py:20
from parrot.bots.prompts import PromptBuilder, PromptLayer, RenderPhase  # __init__.py:15-29

from parrot.clients.base import AbstractClient  # base.py:242 (inherits EventEmitterMixin)
from parrot.core.events.lifecycle.base import LifecycleEvent  # base.py:21
from parrot.core.events.lifecycle.trace import TraceContext  # trace.py (used by all events)
from parrot.core.events.lifecycle.mixin import EventEmitterMixin  # mixin.py (base.py:64)
from parrot.core.events.lifecycle.events.client import (
    BeforeClientCallEvent,  # client.py:18
    AfterClientCallEvent,   # client.py:38
    ClientCallFailedEvent,  # client.py:62
)

from parrot.conf import BASE_DIR, PLUGINS_DIR, AGENTS_DIR  # conf.py:31-141
from navconfig import config, BASE_DIR  # conf.py:5
```

### Existing Class Signatures

```python
# parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):           # line 22
    IDENTITY = 10
    PRE_INSTRUCTIONS = 15
    SECURITY = 20
    KNOWLEDGE = 30
    USER_SESSION = 40
    TOOLS = 50
    OUTPUT = 60
    BEHAVIOR = 70
    CUSTOM = 80

class RenderPhase(str, Enum):           # line 35
    CONFIGURE = "configure"
    REQUEST = "request"

@dataclass(frozen=True)
class PromptLayer:                       # line 50
    name: str
    priority: LayerPriority | int
    template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = field(default_factory=frozenset)
    def render(self, context: Dict[str, Any]) -> Optional[str]: ...   # line 69
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer: ...  # line 83

# parrot/bots/prompts/builder.py
class PromptBuilder:                     # line 20
    def __init__(self, layers: Optional[List[PromptLayer]] = None): ...  # line 35
    def configure(self, context: Dict[str, Any]) -> None: ...  # line 184
    def build(self, context: Dict[str, Any]) -> str: ...       # line 204
    def add(self, layer: PromptLayer) -> PromptBuilder: ...    # line 116
    def remove(self, name: str) -> PromptBuilder: ...          # line 128
    def clone(self) -> PromptBuilder: ...                      # line 172
    @property
    def is_configured(self) -> bool: ...                       # line 233
    @property
    def layer_names(self) -> List[str]: ...                    # line 238

# parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):  # line 242
    _min_cache_tokens: int  # DOES NOT EXIST YET — to be added
    def _system_prompt_hash(self, system_prompt: Optional[str]) -> str: ...  # line 340
    def _emit_before_call(self, *, client_name, model, temperature, system_prompt, has_tools, parent_trace) -> TraceContext: ...  # line 355
    async def _emit_after_call(self, tc, *, client_name, model, duration_ms, input_tokens, output_tokens, finish_reason) -> None: ...  # line 402
    @abstractmethod
    async def ask(self, prompt, model, ..., system_prompt: Optional[str] = None, ...) -> MessageResponse: ...  # line 1431
    @abstractmethod
    async def ask_stream(self, prompt, model, ..., system_prompt: Optional[str] = None, ...) -> AsyncIterator: ...  # line 1469
    async def complete(self, prompt, *, model, system_prompt: Optional[str] = None, ...) -> str: ...  # line 775

# parrot/bots/abstract.py
class AbstractBot:
    def __init__(self, ..., prompt_builder: PromptBuilder = None, prompt_preset: str = None, ..., **kwargs): ...  # line 247

# parrot/core/events/lifecycle/base.py
@dataclass(frozen=True)
class LifecycleEvent(ABC):               # line 21
    trace_context: TraceContext
    event_id: str                        # auto UUID4
    timestamp: datetime                  # auto UTC
    source_type: str = ""
    source_name: str = ""

# parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class BeforeClientCallEvent(LifecycleEvent):  # line 18
    client_name: str = ""
    model: str = ""
    temperature: Optional[float] = None
    system_prompt_hash: str = ""
    has_tools: bool = False

# parrot/stores/kb/local.py — mtime pattern (line 180)
# current_loaded_files = {f.name: f.stat().st_mtime for f in local_files}

# parrot/registry/routing/cache.py — async-safe LRU pattern (line 55)
# class DecisionCache with OrderedDict + asyncio.Lock
```

### Configuration References

```python
# parrot/conf.py — established convention (line 33, 40, 141, 158):
PLUGINS_DIR = config.get('PLUGINS_DIR', fallback=BASE_DIR.joinpath('plugins'))
AGENTS_DIR = config.get('AGENTS_DIR', fallback=BASE_DIR.joinpath('agents'))
MCP_SERVER_DIR = config.get('MCP_SERVER_DIR', fallback=BASE_DIR.joinpath('mcp_servers'))
# New (to be added):
# AGENT_CONTEXT_DIR = config.get('AGENT_CONTEXT_DIR', fallback=BASE_DIR.joinpath('agent_context'))
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CacheableSegment` | `PromptBuilder.build_segments()` | return type | new code |
| `PromptLayer.cacheable` | `PromptBuilder.build_segments()` | read during segmentation | `builder.py:221` (loop) |
| `PromptBuilder.build_segments()` | `AbstractBot` call path | replaces `build()` when flag on | `abstract.py:247+` |
| `AbstractClient._apply_cache_hints()` | `ClaudeClient`, `OpenAIClient`, `GoogleClient` | override | `base.py:242` |
| `AGENT_CONTEXT_LAYER` | `PromptBuilder` | `builder.add()` | `builder.py:116` |
| `AgentContextLoader` | `AGENT_CONTEXT_DIR` from `conf.py` | file read | `conf.py` |
| `PromptCacheAppliedEvent` | `EventEmitterMixin.events.emit_nowait()` | lifecycle emit | `base.py:390` |

### Claude Client — System Prompt Assignment Sites

The following lines assign `payload["system"]` and must be handled by `_apply_cache_hints()`:
- `claude.py:193` — `ask()` main path
- `claude.py:581` — `ask_stream()` main path
- `claude.py:982-986` — structured output paths

### Does NOT Exist (Anti-Hallucination)

- ~~`CacheableSegment`~~ — does not exist yet; to be created in Module 1
- ~~`PromptBuilder.build_segments()`~~ — does not exist yet; to be created in Module 2
- ~~`PromptBuilder.__init__(prompt_caching=...)`~~ — no such kwarg yet
- ~~`PromptLayer.cacheable`~~ — no such attribute on the frozen dataclass
- ~~`AbstractClient._apply_cache_hints()`~~ — does not exist yet
- ~~`AbstractClient._min_cache_tokens`~~ — does not exist yet
- ~~`parrot.bots.prompts.segments`~~ — module does not exist yet
- ~~`parrot.bots.prompts.agent_context`~~ — module does not exist yet
- ~~`AGENT_CONTEXT_DIR`~~ — not in `conf.py` yet
- ~~`PromptCacheAppliedEvent`~~ — does not exist yet
- ~~`PromptCacheSkippedEvent`~~ — does not exist yet
- ~~`parrot.clients._cache_constants`~~ — NOT being created; thresholds live as per-client class attributes instead

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **PromptBuilder two-phase render**: CONFIGURE once / REQUEST per call maps to
  cacheable / non-cacheable. Extend, don't replace. (`builder.py:184-231`)
- **`AbstractClient._system_prompt_hash`**: SHA-256 privacy pattern for
  emitting events without leaking content. Apply to segment hashes.
  (`base.py:340`)
- **`navconfig` + `BASE_DIR` + `fallback=`**: For `AGENT_CONTEXT_DIR`.
  (`conf.py:33-158`)
- **`stores/kb/local.py` mtime invalidation**: Read once, cache by
  `(path, st_mtime)`, re-read when mtime changes. (`local.py:180-248`)
- **`functools.lru_cache` for sync only**: Never decorate async functions with
  `lru_cache`. The loader is sync; if called from async code, wrap with
  `asyncio.to_thread()`. (`registry/routing/cache.py` module docstring)
- **Lifecycle events (FEAT-176)**: Frozen `@dataclass(frozen=True)` inheriting
  `LifecycleEvent`. Emitted via `self.events.emit_nowait()`.
  (`core/events/lifecycle/events/client.py`)
- **`PromptLayer` is `frozen=True`**: Adding `cacheable` requires adding it to
  the dataclass fields; `partial_render()` must propagate it when creating the
  new layer instance. (`layers.py:103-110`)

### Known Risks / Gotchas

- **Anthropic 4-block `cache_control` limit.** v1 marks at most 1–2 blocks
  (AGENT_CONTEXT + identity). If more cacheable segments exist than slots, log
  at debug level and drop the excess.
- **Gemini threshold may underwhelm.** `GitHubReviewer` defaults to
  `GoogleModel.GEMINI_3_FLASH_PREVIEW` (line 269), which may have a 32k minimum.
  If the system prompt + context doesn't reach the threshold, the feature
  silently skips with `PromptCacheSkippedEvent(reason="below_threshold")`.
  Document this in the `GitHubReviewer` docstring.

…(truncated)…

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: PromptBuilder Identity Capability (file-based identity + capabilities layer)

**Feature ID**: FEAT-321
**Date**: 2026-07-21
**Author**: jlara (brainstorm: `sdd/proposals/promptbuilder-identity-capability.brainstorm.md`; supersedes draft proposal `sdd/proposals/identitycapability.spec.md` by amartinez)
**Status**: draft
**Target version**: 0.26.0 (current: 0.25.22)

---

## 1. Motivation & Business Requirements

### Problem Statement

Agent personas are authored as huge inline Python strings — Porygon's `BACKSTORY`
constant spans `agents/porygon.py:11-133` (~122 lines of prose) and is passed as a
kwarg to `super().__init__`. This is painful to edit/review/reuse and conflates the
framework's five identity concerns (`role`, `goal`, `capabilities`, `backstory`,
`rationale`) into one blob.

`AbstractBot` already resolves all five fields (`kwarg → class attribute → package
default`, abstract.py:432-452), but the composable `PromptBuilder` path has two gaps:

1. **`capabilities` is silently dropped.** `IDENTITY_LAYER` deliberately omits
   `$capabilities` (layers.py:137-152), and the only layer that renders it —
   `KNOWLEDGE_SCOPE_LAYER` (domain_layers.py:154-167) — is RAG-only and not in
   `PromptBuilder.default()` (builder.py:52-64). An agent can set `capabilities`
   and it never reaches the LLM.
2. **No file-based, reusable loader.** The whole-blob convention exists
   (`load_agent_context` → `<AGENT_CONTEXT_DIR>/<agent_id>.md`, agent_context.py:57),
   but nothing loads the five identity fields from separate, human-editable
   Markdown files, and nothing packages this so a new agent gets it for free.

**Who is affected**: agent authors (persona authoring/review), prompt engineers
(live persona iteration), and any agent whose `capabilities` currently vanish.

### Goals
- Let any agent load its five identity fields from per-field Markdown files in an
  agent-local `identity/` directory (`role.md`, `goal.md`, `capabilities.md`,
  `backstory.md`, `rationale.md`), with overridable `identity_dir`.
- Render **all five** fields in the composable prompt, including `capabilities`,
  via a reusable `CAPABILITIES_LAYER` (no edits to `IDENTITY_LAYER`).
- **Hot reload**: edits to `identity/*.md` apply on the next system-prompt build
  without restarting the agent (mtime-based, near-zero steady-state cost).
- Expose the capability two ways: an opt-in `IdentityMixin` (file loading + hot
  reload) and a registered `"identity"` PromptBuilder preset (capabilities
  rendering only, for builder-savvy agents).
- Preserve resolution precedence: explicit kwarg > file value > class attribute >
  package default. Missing files fall through **silently**.
- Migrate Porygon to the new mechanism as the reference implementation.

### Non-Goals (explicitly out of scope)
- Changing `AbstractBot`'s `kwarg → class attribute → DEFAULT` resolution order.
- Editing `IDENTITY_LAYER` to add `$capabilities` (kept stable by design).
- Storing identity fields in a database or the Navigator `ai_bots` row.
- Registry auto-discovery of `identity/` folders (opt-in mixin preferred).
- The DevLoop session-state sample (`sdd/artifacts/devloop_session_state.py`) —
  explicitly out of scope per brainstorm discovery.
- Construct-time-only loading, capabilities-only hot reload, and sectioned
  single-file identity were rejected in brainstorm — see
  `proposals/promptbuilder-identity-capability.brainstorm.md` Options A/C/D.

---

## 2. Architectural Design

### Overview

Recommended Option B from the brainstorm: a generic, opt-in identity capability
with four cooperating pieces.

1. **Loader** — `load_identity(directory) → IdentityFields` reads the five `.md`
   files (UTF-8, stripped) through a public mtime-keyed cached reader
   (`read_text_cached`, promoted from `agent_context._read_cached`). Missing or
   empty file → field `None` (silent, debug log only). File content is injected
   **verbatim — no `$`-escaping** so dynamic-variable pre-resolution
   (`$current_date` etc., abstract.py:1200-1214) keeps working exactly as it does
   for inline identity.
2. **Layer + preset** — `CAPABILITIES_LAYER` (frozen `PromptLayer`,
   `priority=LayerPriority.IDENTITY + 1` = 11, `phase=CONFIGURE`, template
   `<capabilities>\n$capabilities\n</capabilities>`, condition = non-empty),
   registered as `"capabilities"` in `_DOMAIN_LAYERS` and composed into a new
   `"identity"` preset (`register_preset("identity", …)` = default stack +
   `CAPABILITIES_LAYER`). Agents can adopt the preset via the existing
   `prompt_preset` kwarg without the mixin.
3. **Mixin** — `IdentityMixin` (opt-in flag `enable_identity: bool = False`,
   `identity_dir` defaulting to `<dir of the concrete agent's module>/identity`).
   Before `super().__init__` it loads identity and sets non-empty fields as
   instance attributes (so kwargs still win via `kwargs.get(...) or getattr(...)`),
   setting `self.capabilities` explicitly (the `PandasAgent` path swallows the
   `capabilities` kwarg into `self._capabilities`, data.py:550,586). Its
   `_configure_identity()` coroutine clones the agent's **effective** builder
   (instance attribute when set via `prompt_builder`/`prompt_preset`,
   abstract.py:533-536; else the class attribute), adds `CAPABILITIES_LAYER`, and
   stashes that clone **pristine** (never configured).
4. **Hot reload** — the mixin overrides `_build_prompt` (abstract.py:1242) and
   delegates to `super()`. Per call it re-runs `load_identity` (near-free: lru
   cache keyed on `(path, mtime)`); when fields differ from last applied it
   updates the instance attributes, re-clones the pristine builder, re-runs
   configure, **carries over transient layers** present on the old builder but
   not the clone (e.g. `skill_active`, added by `create_system_prompt` at
   abstract.py:2772 before `_build_prompt` runs), then atomically swaps
   `self._prompt_builder`. The pristine clone is mandatory because
   `PromptBuilder.configure()` destroys original templates — it replaces layers
   with partially-rendered copies (builder.py:234-241).

Mixin wiring mirrors the **real** pattern used by `SkillRegistryMixin` /
`EpisodicMemoryMixin`: opt-in class flag + an `async _configure_*()` coroutine
the adopting agent calls explicitly after `await super().configure()`
(agents/porygon.py:322-326). The mixins do NOT override `configure()`.

**User-facing behavior**: create `identity/` next to the agent module with any
subset of the five files; add `IdentityMixin` + `enable_identity = True`; all
five blocks (including `<capabilities>`) appear in the system prompt; edit a
file and the next message reflects it. Non-adopters are byte-for-byte unchanged.

### Component Diagram
```
IdentityMixin (enable_identity=True)
   │  __init__ (pre-super): load_identity(identity_dir) ─→ IdentityFields
   │      └─→ sets self.role/goal/capabilities/backstory/rationale (non-empty only)
   │
   ├─ _configure_identity(): clone(effective builder) + add(CAPABILITIES_LAYER)
   │      └─→ pristine clone stashed (never configured)
   │
   └─ _build_prompt() override (per request, delegates to super()):
          load_identity (mtime-cached) ─→ changed?
              ├─ no  → super()._build_prompt(...)          [5 cached lookups]
              └─ yes → re-clone pristine → re-configure →
                       carry over transient layers (skill_active) →
                       swap self._prompt_builder → super()._build_prompt(...)

PromptBuilder stack: IDENTITY(10) · CAPABILITIES(11) · agent_context(12) · … · BEHAVIOR(70)
Preset path (no mixin): prompt_preset="identity" → get_preset → default() + CAPABILITIES_LAYER
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/bots/prompts/domain_layers.py` | extends | `CAPABILITIES_LAYER` + `"capabilities"` entry in `_DOMAIN_LAYERS` (line 576) |
| `parrot/bots/prompts/presets.py` | extends | `register_preset("identity", …)` in `_PRESETS` (line 15) |
| `parrot/bots/prompts/agent_context.py` | extends | promote `_read_cached` → public `read_text_cached` (single shared lru cache) |
| `parrot/bots/abstract.py` | uses (no edits) | relies on identity resolution (432-452), `_configure_prompt_builder` context (1213), `_build_prompt` (1242) override seam, skill-layer flow (2758-2787) |
| `parrot/bots/mixins/__init__.py` | extends | export `IdentityMixin` alongside `IntentRouterMixin` |
| `SkillRegistryMixin` / `EpisodicMemoryMixin` | mirrors | flag + explicit `_configure_*()` call pattern |
| `agents/porygon.py` + `agents/porygon/identity/` | modifies / new | reference migration; `BACKSTORY` (11-133) removed |
| FEAT-181 prompt caching | interacts | re-configure invalidates cacheable segments only on actual persona change; `CAPABILITIES_LAYER` is CONFIGURE-phase → cacheable |

### Data Models
```python
# parrot/bots/prompts/identity.py (new)
from pydantic import BaseModel, Field

class IdentityFields(BaseModel):
    """The five composable identity fields, loaded from Markdown."""
    role: Optional[str] = Field(default=None)
    goal: Optional[str] = Field(default=None)
    capabilities: Optional[str] = Field(default=None)
    backstory: Optional[str] = Field(default=None)
    rationale: Optional[str] = Field(default=None)

    def as_kwargs(self) -> dict[str, str]:
        """Non-empty fields only, for injection as instance attributes."""
        return {k: v for k, v in self.model_dump().items() if v}
```

### New Public Interfaces
```python
# parrot/bots/prompts/identity.py (new)
IDENTITY_FILES: tuple[str, ...]  # ("role", "goal", "capabilities", "backstory", "rationale")

def load_identity(directory: Union[str, Path]) -> IdentityFields:
    """Read {role,goal,capabilities,backstory,rationale}.md from `directory`.
    Missing/empty/unreadable file → field None (silent fallthrough; debug log).
    Content injected verbatim — NO $-escaping (dynamic_values parity).
    Optional: escape_placeholders: bool = False keyword for locked-down personas."""

# parrot/bots/prompts/agent_context.py (promotion)
def read_text_cached(path: Union[str, Path]) -> str:
    """Public mtime-keyed cached text read; stats the file and delegates to the
    existing lru-cached private. Returns "" when the file does not exist."""

# parrot/bots/prompts/domain_layers.py
CAPABILITIES_LAYER: PromptLayer  # priority IDENTITY+1 (11), CONFIGURE, renders $capabilities
# registered: _DOMAIN_LAYERS["capabilities"] = CAPABILITIES_LAYER

# parrot/bots/prompts/presets.py (registration at import time of the layer module)
# register_preset("identity", lambda: PromptBuilder.default().add(CAPABILITIES_LAYER))

# parrot/bots/mixins/identity.py (new)
class IdentityMixin:
    enable_identity: bool = False                 # opt-in flag
    identity_dir: Union[str, Path, None] = None   # default: <agent module dir>/identity
    async def _configure_identity(self) -> None: ...   # called by agent after super().configure()
    def _build_prompt(self, *args, **kwargs): ...      # hot-reload seam, delegates to super()
```

---

## 3. Module Breakdown

### Module 1: Capabilities layer + "identity" preset
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`,
  `packages/ai-parrot/src/parrot/bots/prompts/presets.py`
- **Responsibility**: Define `CAPABILITIES_LAYER` (priority `IDENTITY + 1` = 11 —
  slots between `IDENTITY_LAYER` (10) and `AGENT_CONTEXT_LAYER` (12) —
  `RenderPhase.CONFIGURE`, template `<capabilities>\n$capabilities\n</capabilities>`,
  condition = non-empty `capabilities`); register as `"capabilities"` in
  `_DOMAIN_LAYERS`; register the `"identity"` preset (default stack + the layer).
- **Depends on**: `prompts/layers.py` (`PromptLayer`, `LayerPriority`,
  `RenderPhase`), `prompts/presets.py` (`register_preset`).

### Module 2: File-based identity loader + reader promotion
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/identity.py` (new),
  `packages/ai-parrot/src/parrot/bots/prompts/agent_context.py` (promotion)
- **Responsibility**: `IdentityFields` model + `load_identity(directory)`
  (five `.md` files, UTF-8, stripped, verbatim — no `$`-escaping; missing/empty →
  `None`, silent). Promote `_read_cached` to public `read_text_cached(path)`
  keeping one shared lru cache; loader consumes it.
- **Depends on**: `bots/prompts/agent_context.py`.

### Module 3: IdentityMixin (injection + hot reload)
- **Path**: `packages/ai-parrot/src/parrot/bots/mixins/identity.py` (new),
  `packages/ai-parrot/src/parrot/bots/mixins/__init__.py` (export)
- **Responsibility**: Opt-in mixin per §2. Pre-`super().__init__` field
  injection (instance attributes, non-empty only, `self.capabilities` set
  explicitly); `_configure_identity()` builds the pristine clone from the
  agent's effective builder + `CAPABILITIES_LAYER`; `_build_prompt` override
  implements mtime-based hot reload with transient-layer carry-over and atomic
  builder swap.
- **Depends on**: Module 1, Module 2; `AbstractBot` seams listed in §6.

### Module 4: Porygon reference migration
- **Path**: `agents/porygon/identity/{role,goal,capabilities,backstory,rationale}.md`
  (new), `agents/porygon.py`
- **Responsibility**: Split `BACKSTORY` (porygon.py:11-133) into the five files;
  add `IdentityMixin` first in bases, `enable_identity = True`; remove the
  constant and its `backstory=BACKSTORY` kwarg; call
  `await self._configure_identity()` in `configure()` alongside the existing
  `_configure_episodic_memory()` / `_configure_skill_registry()` calls.
- **Depends on**: Modules 1–3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_capabilities_layer_renders` | Module 1 | `render({"capabilities": "x"})` yields `<capabilities>x</capabilities>`; empty → `None`. |
| `test_capabilities_layer_registered` | Module 1 | `get_domain_layer("capabilities")` returns the layer; priority 11, CONFIGURE phase, cacheable. |
| `test_identity_preset_registered` | Module 1 | `get_preset("identity")` returns a fresh builder = default stack + capabilities layer. |
| `test_load_identity_reads_all_fields` | Module 2 | All five `.md` files load, stripped, into `IdentityFields`. |
| `test_load_identity_missing_file` | Module 2 | Missing field file → field `None`, no warning raised (silent fallthrough). |
| `test_load_identity_empty_file` | Module 2 | Whitespace-only file → field `None`. |
| `test_load_identity_no_dollar_escaping` | Module 2 | File containing `$current_date` loads verbatim (no `$$`). |
| `test_read_text_cached_mtime_invalidation` | Module 2 | Same mtime → cached; touched file with new content → fresh read. |
| `test_mixin_injects_fields` | Module 3 | `enable_identity=True` agent gets all five `self.*` fields from files, incl. `self.capabilities`. |
| `test_mixin_precedence_kwarg_wins` | Module 3 | Explicit constructor kwarg beats file value; file beats class attribute. |
| `test_mixin_hot_reload` | Module 3 | Edit `backstory.md` (bump mtime) → next `_build_prompt` output reflects new text. |
| `test_mixin_swap_carries_transient_layers` | Module 3 | Builder swap during hot reload preserves a transient `skill_active` layer added pre-call. |
| `test_mixin_dynamic_values_resolve` | Module 3 | `$current_date` inside a loaded identity file is resolved at (re-)configure. |
| `test_non_adopter_unaffected` | Module 3 | Agent without the mixin renders **byte-for-byte** the same prompt as before; no `<capabilities>` block. |
| `test_mixin_disabled_flag_inert` | Module 3 | Mixin present but `enable_identity=False` → no loading, no layer, no override effects. |

### Integration Tests
| Test | Description |
|---|---|
| `test_example_agent_renders_all_five` | An `IdentityMixin` agent: `await agent.create_system_prompt()` contains `<agent_identity>`, `<capabilities>`, `<response_style>`. |
| `test_porygon_renders_capabilities` | Porygon's assembled prompt contains `<capabilities>` sourced from `identity/capabilities.md`. |
| `test_porygon_prompt_parity` | Migrated Porygon prompt contains the same substantive content previously carried by `BACKSTORY`. |

### Test Data / Fixtures
```python
@pytest.fixture
def identity_dir(tmp_path):
    for f, text in {
        "role": "a test analyst",
        "goal": "answer questions",
        "capabilities": "- do X\n- do Y",
        "backstory": "context here",
        "rationale": "be concise",
    }.items():
        (tmp_path / f"{f}.md").write_text(text, encoding="utf-8")
    return tmp_path
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] An agent with `enable_identity=True` renders all five identity blocks,
      including `<capabilities>`, in its system prompt.
- [ ] `capabilities` renders without editing `IDENTITY_LAYER`.
- [ ] Editing any `identity/*.md` file is reflected in the next system-prompt
      build without restarting the agent (hot reload).
- [ ] Explicit constructor kwargs override file values; missing/empty files fall
      through silently to class attribute / package default.
- [ ] Agents that do not enable the mixin are byte-for-byte unchanged in their
      assembled prompt (no `<capabilities>` block appears).
- [ ] A hot-reload builder swap does not drop a transient `skill_active` layer
      for that turn.
- [ ] Identity file content is injected verbatim (no `$`-escaping);
      `$current_date`-style dynamic variables resolve inside file personas.
- [ ] `get_preset("identity")` returns default stack + `CAPABILITIES_LAYER`.
- [ ] Porygon is migrated: inline `BACKSTORY` removed, five `identity/*.md`
      files present, prompt renders identically-or-better.
- [ ] Documentation updated in `docs/` (identity capability + `identity/`
      directory convention + `$`-placeholder semantics).
- [ ] No breaking changes to existing public API; no new third-party
      dependencies.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references verified 2026-07-21 on `dev`. Paths relative to
> `packages/ai-parrot/src/` unless noted.

### Verified Imports
```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.domain_layers import get_domain_layer, _DOMAIN_LAYERS
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.presets import register_preset, get_preset
from parrot.bots.prompts.agent_context import load_agent_context, AGENT_CONTEXT_LAYER
from parrot.bots.mixins import IntentRouterMixin        # bots/mixins/__init__.py (only export today)
from parrot.skills import SkillRegistryMixin
from parrot.memory import EpisodicMemoryMixin
```

### Existing Class Signatures
```python
# parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):  # line 22 — IDENTITY=10, PRE_INSTRUCTIONS=15, SECURITY=20,
    ...                        # KNOWLEDGE=30, USER_SESSION=40, TOOLS=50, OUTPUT=60,
                               # BEHAVIOR=70, CUSTOM=80
class RenderPhase(str, Enum):  # line 35 — CONFIGURE="configure" (46), REQUEST="request" (47)
@dataclass(frozen=True)
class PromptLayer:             # line 50
    name: str; priority: LayerPriority | int; template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str]; cacheable: Optional[bool]   # cacheable derived from phase (75-80)
    def render(self, context: Dict[str, Any]) -> Optional[str]: ...      # line 82 — safe_substitute
    def partial_render(self, context: Dict[str, Any]) -> PromptLayer: ...  # line 96 — REQUEST-phase copy
IDENTITY_LAYER   # line 142 — CONFIGURE, priority IDENTITY; template OMITS $capabilities (comment 137-141)
BEHAVIOR_LAYER   # line 232 — CONFIGURE, priority BEHAVIOR; renders $rationale, condition non-empty

# parrot/bots/prompts/domain_layers.py
KNOWLEDGE_SCOPE_LAYER          # line 154 — CONFIGURE, priority KNOWLEDGE-5; renders $capabilities (RAG-only)
_DOMAIN_LAYERS: Dict[str, PromptLayer]  # line 576 — 10 keys, NO "capabilities"
def get_domain_layer(name: str) -> PromptLayer: ...  # line 590 — raises KeyError

# parrot/bots/prompts/builder.py
class PromptBuilder:                                    # line 21
    def __init__(self, layers=None, *, prompt_caching=False)   # line 36
    @classmethod default()/minimal()/voice()/agent()/rag()/from_system_prompt()
    #   lines 52/66/72/98/106/122 — default() = IDENTITY..BEHAVIOR, NO capabilities/knowledge_scope
    def add(self, layer) -> PromptBuilder     # line 152 — add-or-replace by name, MUTATES, returns self
    def remove(self, name) -> PromptBuilder   # line 164 — NO-OP on missing name (pop(name, None), 164-174)
    def replace(self, name, layer)            # line 176 — KeyError if not found
    def clone(self) -> PromptBuilder          # line 208 — deep copy, preserves _configured
    def configure(self, context) -> None      # line 223 — REPLACES layers with partial_render copies
    #   (234-241) → original templates are LOST after configure; sets _configured=True
    def build(self, context) -> str           # line 243 — per-request render
    def build_segments(self, context)         # line 272 — FEAT-181 cacheable segments
    is_configured                             # property, gates one-shot configure

# parrot/bots/prompts/presets.py
_PRESETS  # line 15 — {"default","minimal","voice","agent","rag"} — NO "identity"
def register_preset(name, factory)  # line 24
def get_preset(name)                # line 34 — fresh builder per call

# parrot/bots/abstract.py
class AbstractBot:
    system_prompt_template = BASIC_SYSTEM_PROMPT      # line 214 (legacy path only)
    _prompt_builder: Optional[PromptBuilder] = None   # line 223 — CLASS attribute
    # __init__: instance builder from prompt_builder kwarg (533) or get_preset(prompt_preset) (535-536)
    # identity resolution, __init__ 432-452:
    #   self.<field> = kwargs.get(f) or getattr(self, f, None) or DEFAULT_<F>
    #   (backstory default constant is spelled DEFAULT_BACKHISTORY, 443-446)
    async def _configure_prompt_builder(self)          # line 1179 — called ONCE from configure()
    #   (1423-1425, guarded by `not is_configured`)
    #   _resolve() pre-resolves dynamic vars INSIDE identity fields (1200-1214, intentional per
    #   comment 1200-1203); configure_context["capabilities"] = _resolve(getattr(self,
    #   'capabilities', '')) at 1213; ends with self._prompt_builder.configure(...) at 1240
    def _build_prompt(self, user_context="", vector_context="", conversation_context="",
                      kb_context="", pageindex_context="", metadata=None, ...)  # line 1242
    #   per-request; builder.build() at 1311 (or build_segments at 1310 when caching)
    async def create_system_prompt(...)                # line 2733 — per-message entry
    #   skill-layer flow (2758-2787): adds transient "skill_active" REQUEST layer via
    #   _prompt_builder.add() at 2772 BEFORE _build_prompt (2774); remove("skill_active") at 2786

# parrot/bots/prompts/agent_context.py
@functools.lru_cache(maxsize=256)
def _read_cached(path: str, mtime: float) -> str   # line 38 — (path, mtime) cache key — PRIVATE today
def load_agent_context(agent_id: str) -> str       # line 57 — missing file → "" SILENTLY (88-89)
AGENT_CONTEXT_LAYER                                 # line 96 — CONFIGURE, priority 12, cacheable

# parrot/bots/data.py
def _build_pandas_prompt_builder() -> PromptBuilder  # line 431 — default() + dataframe/grounding/pandas
class PandasAgent(IntentRouterMixin, BasicAgent):    # line 514
    _prompt_builder = _build_pandas_prompt_builder() # line 535 — SHARED class attribute
    def __init__(..., capabilities: str = None, ...) # line 550 — swallowed → self._capabilities (586)

# Mixin pattern to mirror (opt-in flag + explicit _configure_* call):
# parrot/skills/mixin.py:27  SkillRegistryMixin: enable_skill_registry=True (57);
#                            async _configure_skill_registry() guarded by flag (105-108)
# parrot/memory/episodic/mixin.py:77  EpisodicMemoryMixin: enable_episodic_memory=False (100);
#                            async _configure_episodic_memory() (181, guard 195)
# agents/porygon.py (repo-root agents/, NOT inside the package):
#   :11-133 BACKSTORY constant; :136 @register_agent("porygon", at_startup=True);
#   :137 class Porygon(SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent);
#   :160-179 super().__init__(..., backstory=BACKSTORY, ...);
#   :322-326 configure(): await super().configure(...) then explicit _configure_* calls
# agents/porygon/ contains only skills/ — no identity/ directory yet.
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CAPABILITIES_LAYER` | `_DOMAIN_LAYERS` | dict entry + `get_domain_layer` | `domain_layers.py:576,590` |
| `"identity"` preset | `presets._PRESETS` | `register_preset` | `presets.py:15,24` |
| `IdentityMixin` | agent's effective builder | `clone()` + `add(CAPABILITIES_LAYER)` | `builder.py:208,152`; `abstract.py:533-536` |
| `IdentityMixin` | `AbstractBot` identity fields | pre-super instance attrs + `self.capabilities` | `abstract.py:432-452`; `data.py:550,586` |
| `IdentityMixin._build_prompt` | `AbstractBot._build_prompt` | override + `super()` delegation | `abstract.py:1242,2774` |
| hot-reload swap | skill-layer transient add/remove | carry-over; `remove()` no-op tolerance | `abstract.py:2772,2786`; `builder.py:164-174` |
| `load_identity` | `read_text_cached` (promoted `_read_cached`) | cached file read | `agent_context.py:38` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/bots/prompts/identity.py`~~ / ~~`IdentityFields`~~ / ~~`load_identity`~~ — new (M2).
- ~~`read_text_cached`~~ — new public name (M2); today only private `_read_cached` exists.
- ~~`parrot/bots/mixins/identity.py`~~ / ~~`IdentityMixin`~~ — new (M3).
- ~~`CAPABILITIES_LAYER`~~ / ~~a `"capabilities"` key in `_DOMAIN_LAYERS`~~ — new (M1).
- ~~an `"identity"` entry in `_PRESETS`~~ — new (M1).
- ~~`agents/porygon/identity/`~~ — new (M4).
- ~~`IDENTITY_LAYER` rendering `$capabilities`~~ — it does NOT and will NOT (by design).
- ~~mixins cooperating via `super().configure()` overrides~~ — neither `SkillRegistryMixin`
  nor `EpisodicMemoryMixin` overrides `configure()`; agents call `_configure_*()` explicitly.
- ~~`PromptBuilder.add()` returning a new builder~~ — mutates in place; copy primitive is `clone()`.
- ~~re-configuring an already-configured builder with new values~~ — impossible
  (templates destroyed at configure, builder.py:234-241); hot reload MUST re-clone pristine.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror the real mixin pattern: class-attribute opt-in flag + `async
  _configure_identity()` that the adopting agent calls explicitly after
  `await super().configure()` (see Porygon, agents/porygon.py:322-326).
  Do NOT override `configure()` in the mixin.
- `PromptLayer` is a frozen dataclass — compose, never mutate.
- Pydantic model (`IdentityFields`) for loaded data; strict type hints;
  Google-style docstrings; `self.logger` (debug for silent fallthroughs).
- Default `identity_dir` resolves relative to the concrete agent's module file
  (`Path(inspect.getfile(type(self))).parent / "identity"`), never the CWD.
- Inject only *non-empty* file values, as instance attributes set **before**
  `super().__init__`, so `kwargs.get(f) or getattr(self, f, None) or DEFAULT`
  keeps kwargs winning and files beating class attributes.

### Known Risks / Gotchas
- **Shared class-level builder** (`data.py:535`): never `add()` to the class
  builder — clone the agent's *effective* builder (instance attr when set via
  `prompt_builder`/`prompt_preset`, else class attr) and assign per instance.
- **`configure()` destroys templates** (builder.py:234-241): hot reload must
  re-clone the stashed pristine builder; a configured builder cannot be
  re-configured with new values.
- **Transient skill layer**: `create_system_prompt` adds `skill_active` before
  `_build_prompt` and removes it after (abstract.py:2772,2786). On builder swap,
  carry over layers present on the old builder but absent from the pristine
  clone. `remove()` is a no-op on missing names, so cleanup never crashes.
- **Atomic swap**: fully build + configure the new builder, then assign
  `self._prompt_builder` in one step so concurrent requests see a consistent
  snapshot.
- **`capabilities` kwarg swallowed** by `PandasAgent.__init__` into
  `self._capabilities` (data.py:550,586): the mixin sets `self.capabilities`
  directly so `_configure_prompt_builder`'s `getattr(self, 'capabilities')`
  (abstract.py:1213) picks it up.
- **`$` semantics**: file content injected verbatim. Dynamic variables
  (`$current_date`, …) resolve at (re-)configure via `_resolve`
  (abstract.py:1200-1214) — this is intentional parity with inline identity.
  Leftover `$tokens` colliding with REQUEST-context keys (`$user_context`,
  `$knowledge_content`, …) substitute at request time — pre-existing property of
  inline identity, not a regression; document it. Optional
  `escape_placeholders=False` loader flag for locked-down personas.
- **Hot-reload thrash**: mtime granularity → at most one re-configure per file
  change; a touched-but-identical file re-configures harmlessly. Re-configure
  invalidates FEAT-181 cacheable segments for that turn only.
- **Empty vs missing**: whitespace-only files must normalize to `None` so they
  don't short-circuit the fallthrough chain with an empty string.
- **Unreadable file** (permissions/decode error): log warning, treat as missing.
- **Field staleness**: `$current_date` inside identity refreshes only on
  re-configure — i.e., whenever any identity file changes (improvement over
  inline identity, which never refreshes). Pre-existing behavior otherwise.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | existing | `IdentityFields` model |

_No new third-party dependencies._

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: four small, chained modules (M1/M2 independent of each other
  but both tiny; M3 depends on M1+M2; M4 depends on M3) with a shared touchpoint
  in `parrot/bots/prompts/` — one worktree in dependency order avoids
  cross-worktree merge noise for near-zero parallel speedup.
- **Cross-feature dependencies**: none. No overlap with in-flight work
  (adaptive-cards builder lives under `packages/ai-parrot-integrations/`; the
  dev-loop session-state proposal has no code yet).
- **Worktree**: `git worktree add -b feat-321-promptbuilder-identity-capability
  .claude/worktrees/feat-321-promptbuilder-identity-capability HEAD` (from `dev`,
  after `/sdd-task`).

---

## 8. Open Questions

> All questions were resolved during brainstorm discovery
> (`sdd/proposals/promptbuilder-identity-capability.brainstorm.md`). Echoed here
> for the audit trail; none remain open.

- [x] Feature ID — *Resolved in brainstorm*: FEAT-321 (highest was FEAT-320;
      re-verified at spec time: FEAT-322 claimed by a concurrent session's
      `sdd/state/`, FEAT-321 free; FEAT-373 is an external FieldSync reference).
- [x] Hot-reload hook — *Resolved in brainstorm*: override `_build_prompt`
      (abstract.py:1242) with transient-layer carry-over for `skill_active`
      (added/removed by `create_system_prompt` at 2772/2786; `remove()` no-op on
      missing names).
- [x] `_read_cached` promotion — *Resolved in brainstorm*: promote to public
      `read_text_cached(path)` in `agent_context.py`, keeping one shared lru cache.
- [x] `$`-escaping policy — *Resolved in brainstorm*: do NOT escape by default;
      escaping breaks intentional dynamic-variable pre-resolution inside identity
      fields (abstract.py:1200-1214). Verbatim injection preserves parity with
      inline identity; optional `escape_placeholders` flag.
- [x] Builder source for the mixin clone — *Resolved in brainstorm*: clone the
      agent's own *effective* builder + `add(CAPABILITIES_LAYER)` (instance attr
      when set, else class attr); the `"identity"` preset is an independent
      adoption path. `add()` is add-or-replace, so mixin + preset cannot
      double-add.
- [x] Flow type/base — *Resolved in brainstorm*: feature → dev.
- [x] `devloop_session_state.py` role — *Resolved in brainstorm*: out of scope.
- [x] Mixin module path — *Resolved in brainstorm*: `parrot/bots/mixins/identity.py`.
- [x] Missing-file behavior — *Resolved in brainstorm*: silent fallthrough
      (like `load_agent_context`).
- [x] Preset in addition to mixin — *Resolved in brainstorm*: yes, ship both.
- [x] Builder-copy strategy — *Resolved in brainstorm*: per-instance pristine
      `clone()` (required for hot reload).
- [x] Hot reload — *Resolved in brainstorm*: yes, per build (mtime-based).
- [x] Porygon migration — *Resolved in brainstorm*: in scope, reference
      implementation.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-21 | jlara | Initial spec from brainstorm (Option B); supersedes draft proposal by amartinez |

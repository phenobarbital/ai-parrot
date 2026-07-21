---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Agent Identity Capability (file-based identity + capabilities layer)

**Feature ID**: FEAT-<NNN>
**Date**: 2026-07-21
**Author**: amartinez
**Status**: draft

**Target version**: x.y.z

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Agent personas are authored today as large inline Python strings (e.g. Porygon's
~150-line `BACKSTORY` constant passed to `super().__init__`). This is hard to
edit, review, and reuse, and it conflates five distinct identity concerns into
one blob.

The framework already defines a five-field identity contract —
`role`, `goal`, `capabilities`, `backstory`, `rationale` — resolved in
`AbstractBot` (`kwarg → class attribute → package default`). But on the
composable `PromptBuilder` path there are two gaps:

1. **`capabilities` is silently dropped.** `IDENTITY_LAYER` deliberately omits
   `$capabilities`, and the only layer that renders it
   (`KNOWLEDGE_SCOPE_LAYER`) is RAG-only and not part of `PromptBuilder.default()`.
   An agent can set `capabilities` and it never reaches the LLM.
2. **No file-based, reusable loader.** There is a whole-blob per-agent context
   file convention (`load_agent_context` → `<AGENT_CONTEXT_DIR>/<agent_id>.md`),
   but nothing loads the five identity fields from separate, human-editable
   Markdown files, and nothing packages this so a *new* agent gets it for free.

### Goals
- Let any agent load its five identity fields from per-field Markdown files in
  an agent-local `identity/` directory (`role.md`, `goal.md`, `capabilities.md`,
  `backstory.md`, `rationale.md`).
- Render **all five** fields in the composable prompt, including `capabilities`,
  via a reusable `CAPABILITIES_LAYER`.
- Expose the capability generically as an opt-in `IdentityMixin` that mirrors
  the existing `SkillRegistryMixin` / `EpisodicMemoryMixin` wiring.
- Migrate Porygon to the new mechanism as the reference implementation.

### Non-Goals (explicitly out of scope)
- Changing the `kwarg → class attribute → DEFAULT` resolution order in
  `AbstractBot`.
- Editing `IDENTITY_LAYER` to add `$capabilities` (kept stable; capabilities is
  a separate layer by design).
- Storing identity fields in a database or the Navigator `ai_bots` row (the DB
  path continues to work unchanged via kwargs).
- Auto-discovering `identity/` folders from the registry with zero code
  (an opt-in mixin is preferred over registry magic in this iteration).

---

## 2. Architectural Design

### Overview

Add a generic, opt-in identity capability with three cooperating pieces: a
file-based loader that reads the five Markdown files into a typed model, a
reusable `CAPABILITIES_LAYER` registered alongside the other domain layers, and
an `IdentityMixin` that ties them together and injects the fields at
construction — exactly following the pattern of the mixins Porygon already uses.

### Component Diagram
```
IdentityMixin ──→ load_identity(dir) ──→ IdentityFields (role/goal/capabilities/backstory/rationale)
      │
      ├──→ sets self.role/goal/backstory/rationale (+ self.capabilities)
      │
      └──→ PromptBuilder.add(CAPABILITIES_LAYER)
                   │
                   └──→ IDENTITY_LAYER · CAPABILITIES_LAYER · BEHAVIOR_LAYER  (rendered prompt)
```

### Integration Points

> How does this feature integrate with existing AI-Parrot components?

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot` (identity resolution) | uses | Injects loaded fields as constructor kwargs; relies on `kwarg → class attr → DEFAULT`. |
| `PromptBuilder` | uses/extends | `IdentityMixin` calls `.add(CAPABILITIES_LAYER)` on the instance builder. |
| `domain_layers._DOMAIN_LAYERS` | extends | Registers the new `"capabilities"` layer. |
| `SkillRegistryMixin` / `EpisodicMemoryMixin` | mirrors | Same class-flag + `_configure_*()` + `super().configure()` MRO pattern. |
| `agent_context._read_cached` | reuses | mtime-keyed cached file read for the loader. |

### Data Models
```python
# parrot/bots/prompts/identity.py
from pydantic import BaseModel, Field

class IdentityFields(BaseModel):
    """The five composable identity fields, loaded from Markdown."""
    role: Optional[str] = Field(default=None)
    goal: Optional[str] = Field(default=None)
    capabilities: Optional[str] = Field(default=None)
    backstory: Optional[str] = Field(default=None)
    rationale: Optional[str] = Field(default=None)

    def as_kwargs(self) -> dict[str, str]:
        """Non-empty fields only, for splatting into a constructor."""
        return {k: v for k, v in self.model_dump().items() if v}
```

### New Public Interfaces
```python
# parrot/bots/prompts/identity.py
def load_identity(directory: Union[str, Path]) -> IdentityFields:
    """Read {role,goal,capabilities,backstory,rationale}.md from `directory`.
    Missing files leave that field None (falls through to class attr/DEFAULT)."""

# parrot/bots/prompts/domain_layers.py
CAPABILITIES_LAYER: PromptLayer   # priority IDENTITY+1, CONFIGURE, renders $capabilities

# parrot/bots/mixins/identity.py
class IdentityMixin:
    enable_identity: bool = False          # opt-in flag
    identity_dir: Union[str, Path, None] = None   # defaults to <agent module dir>/identity
    async def _configure_identity(self) -> None: ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

### Module 1: Capabilities prompt layer
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`
- **Responsibility**: Define `CAPABILITIES_LAYER` (priority `LayerPriority.IDENTITY + 1`,
  `RenderPhase.CONFIGURE`, template `<capabilities>\n$capabilities\n</capabilities>`,
  `condition` = capabilities non-empty) and register it as `"capabilities"` in
  `_DOMAIN_LAYERS` so `get_domain_layer("capabilities")` resolves.
- **Depends on**: `prompts/layers.py` (`PromptLayer`, `LayerPriority`, `RenderPhase`).

### Module 2: File-based identity loader
- **Path**: `packages/ai-parrot/src/parrot/bots/prompts/identity.py` (new)
- **Responsibility**: `IdentityFields` model + `load_identity(directory)` that
  reads the five `.md` files (UTF-8, stripped), reusing the mtime-cached reader
  from `agent_context`. Missing file → field stays `None`.
- **Depends on**: `bots/prompts/agent_context.py` (`_read_cached`).

### Module 3: IdentityMixin
- **Path**: `packages/ai-parrot/src/parrot/bots/mixins/identity.py` (new)
- **Responsibility**: Opt-in mixin. When `enable_identity` is set, resolve
  `identity_dir` (default: `<dir of the concrete agent's module>/identity`),
  `load_identity(...)`, inject non-empty fields as `__init__` kwargs, set
  `self.capabilities` explicitly (subclasses like `PandasAgent` consume the
  `capabilities` kwarg as a legacy-only param), and add `CAPABILITIES_LAYER` to
  the instance's `_prompt_builder`. Provide `_configure_identity()` invoked via
  `super().configure()` cooperation.
- **Depends on**: Module 1, Module 2, `AbstractBot` identity resolution.

### Module 4: Porygon reference migration
- **Path**: `agents/porygon/identity/{role,goal,capabilities,backstory,rationale}.md`,
  `agents/porygon/identity/__init__.py`, `agents/porygon/porygon.py`
- **Responsibility**: Add `IdentityMixin` to `Porygon`, set `enable_identity = True`,
  remove the inline `BACKSTORY` constant, and ship the five Markdown files.
- **Depends on**: Modules 1–3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_load_identity_reads_all_fields` | Module 2 | All five `.md` files load, stripped, into `IdentityFields`. |
| `test_load_identity_missing_file` | Module 2 | A missing field file leaves that field `None` (no crash). |
| `test_capabilities_layer_renders` | Module 1 | `CAPABILITIES_LAYER.render({"capabilities": "x"})` yields `<capabilities>x</capabilities>`; empty capabilities → `None`. |
| `test_capabilities_layer_registered` | Module 1 | `get_domain_layer("capabilities")` returns the layer. |
| `test_mixin_injects_fields` | Module 3 | An agent with `enable_identity=True` gets `self.role/goal/backstory/rationale` and `self.capabilities` from files. |
| `test_mixin_precedence` | Module 3 | Explicit kwarg still wins over a file value (resolution order preserved). |
| `test_non_adopter_unaffected` | Module 3 | An agent without the mixin renders no `<capabilities>` block and behaves exactly as before. |

### Integration Tests
| Test | Description |
|---|---|
| `test_example_agent_renders_all_five` | An example `IdentityMixin` agent: `await agent.create_system_prompt()` contains `<agent_identity>`, `<capabilities>`, and `<response_style>`. |
| `test_porygon_renders_capabilities` | Porygon's assembled system prompt contains the `<capabilities>` block sourced from `identity/capabilities.md`. |

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
- [ ] Agents that do not enable the mixin are byte-for-byte unchanged in their
      assembled prompt (no `<capabilities>` block appears).
- [ ] Porygon is migrated: inline `BACKSTORY` removed, five `identity/*.md`
      files present, prompt renders identically-or-better.
- [ ] Documentation updated in `docs/` (identity capability + directory convention).
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase  # prompts/layers.py:22,35,50
from parrot.bots.prompts.domain_layers import get_domain_layer, _DOMAIN_LAYERS  # domain_layers.py:576,590
from parrot.bots.prompts.builder import PromptBuilder                           # prompts/builder.py
from parrot.bots.prompts.agent_context import load_agent_context, AGENT_CONTEXT_LAYER  # agent_context.py
from parrot.bots.data import PandasAgent, _build_pandas_prompt_builder          # bots/data.py:514,431
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):        # line 22
    IDENTITY = 10; PRE_INSTRUCTIONS = 15; SECURITY = 20; KNOWLEDGE = 30
    USER_SESSION = 40; TOOLS = 50; OUTPUT = 60; BEHAVIOR = 70; CUSTOM = 80
class RenderPhase(str, Enum):        # line 35  (CONFIGURE="configure", REQUEST="request")
@dataclass(frozen=True)
class PromptLayer:                    # line 50
    name: str; priority: LayerPriority | int; template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str] = frozenset(); cacheable: Optional[bool] = None
    def render(self, context: Dict[str, Any]) -> Optional[str]: ...   # line 82
IDENTITY_LAYER  = PromptLayer(name="identity", priority=IDENTITY, phase=CONFIGURE, ...)  # line 142 (OMITS $capabilities)
BEHAVIOR_LAYER  = PromptLayer(name="behavior", priority=BEHAVIOR, phase=CONFIGURE, template=".. $rationale ..")  # line 232

# packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py
KNOWLEDGE_SCOPE_LAYER = PromptLayer(name="knowledge_scope", priority=KNOWLEDGE-5, ... "$capabilities" ...)  # line 154
_DOMAIN_LAYERS: Dict[str, PromptLayer] = { ... }     # line 576
def get_domain_layer(name: str) -> PromptLayer: ...  # line 590

# packages/ai-parrot/src/parrot/bots/prompts/builder.py
class PromptBuilder:
    def __init__(self, layers=None, *, prompt_caching=False): ...  # line 36
    @classmethod
    def default(cls) -> PromptBuilder: ...   # line 52 (IDENTITY..BEHAVIOR, NO capabilities/knowledge_scope)
    def add(self, layer: PromptLayer) -> PromptBuilder: ...     # line 152
    def remove(self, name: str) -> PromptBuilder: ...           # line 164
    def configure(self, context: Dict[str, Any]) -> None: ...   # line 223
    def build(self, context: Dict[str, Any]) -> str: ...        # line 243

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):
    system_prompt_template = BASIC_SYSTEM_PROMPT        # line 214
    _prompt_builder: Optional[PromptBuilder] = None     # line 222-223 (None ⇒ legacy template)
    # identity resolution (kwarg → class attr → DEFAULT):
    self.role/goal/capabilities/backstory/rationale     # lines 432-452
    async def _configure_prompt_builder(self) -> None: ...  # ~line 1179; builds configure_context
    #   configure_context["capabilities"] = _resolve(getattr(self, 'capabilities', ...))  # ~line 1211-1213

# packages/ai-parrot/src/parrot/bots/data.py
def _build_pandas_prompt_builder() -> PromptBuilder:    # line 431 (default() + dataframe/grounding/pandas)
class PandasAgent(IntentRouterMixin, BasicAgent):        # line 514
    _prompt_builder = _build_pandas_prompt_builder()     # line 535 (class attribute)
    def __init__(self, ..., capabilities: str = None, ...):  # line 550  → self._capabilities  # line 586
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CAPABILITIES_LAYER` | `_DOMAIN_LAYERS` | dict entry + `get_domain_layer` | `domain_layers.py:576,590` |
| `IdentityMixin` | `PromptBuilder.add()` | instance `.add(CAPABILITIES_LAYER)` | `builder.py:152` |
| `IdentityMixin` | `AbstractBot` identity fields | constructor kwargs + `self.capabilities` | `abstract.py:432-452`, `data.py:550,586` |
| `load_identity` | `agent_context._read_cached` | cached file read | `bots/prompts/agent_context.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.bots.prompts.domain_layers.CAPABILITIES_LAYER`~~ — to be created (M1).
- ~~`parrot.bots.prompts.identity`~~ / ~~`load_identity`~~ / ~~`IdentityFields`~~ — new (M2).
- ~~`parrot.bots.mixins.identity.IdentityMixin`~~ — new (M3).
- ~~a per-field `identity/` directory convention~~ — introduced by this feature.
- ~~`IDENTITY_LAYER` rendering `$capabilities`~~ — it does NOT and will NOT (by design).
- ~~a `"capabilities"` key in `_DOMAIN_LAYERS`~~ — not present today.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `SkillRegistryMixin` / `EpisodicMemoryMixin`: class-attribute flags,
  a `_configure_identity()` coroutine, and cooperation through
  `super().configure()` (respect MRO — Porygon is
  `SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent`).
- `PromptLayer` is a frozen dataclass; compose, don't mutate.
- Pydantic model (`IdentityFields`) for the loaded data.
- Comprehensive logging with `self.logger`.

### Known Risks / Gotchas
- **Shared class-level builder.** `_prompt_builder` is a *class* attribute
  (`data.py:535`). Adding the layer must not mutate a builder shared across
  agent classes — add it to a per-instance/per-class copy, or via a
  `build_prompt_builder()` helper the agent assigns to its own class.
- **`capabilities` kwarg is swallowed** by `PandasAgent.__init__` into
  `self._capabilities` (legacy-only). The mixin MUST set `self.capabilities`
  directly so `_configure_prompt_builder`'s `getattr(self, 'capabilities')`
  picks it up.
- **Field precedence.** Only inject *non-empty* file values so an explicit kwarg
  or class attribute still wins.
- **Directory resolution.** Default `identity/` is relative to the concrete
  agent's module file (`Path(inspect.getfile(type(self))).parent / "identity"`),
  not the CWD.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | (existing) | `IdentityFields` model |

_No new third-party dependencies._

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] Assign the real `FEAT-<NNN>` id — *Owner: amartinez*
- [ ] Final module paths: `bots/mixins/identity.py` vs `bots/prompts/identity.py` for the mixin — *Owner: amartinez*
- [ ] Should we also register an `"identity"` `PromptBuilder` preset (default stack + capabilities), or is the mixin injection sufficient? — *Owner: amartinez*
- [ ] Should missing identity files warn (log) or stay silent like `load_agent_context`? — *Owner: amartinez*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-21 | amartinez | Initial draft |

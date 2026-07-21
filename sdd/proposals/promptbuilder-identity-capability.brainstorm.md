---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: PromptBuilder Identity Capability (file-based identity + capabilities layer)

**Date**: 2026-07-21
**Author**: jlara (input: draft spec `sdd/proposals/identitycapability.spec.md` by amartinez)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

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

## Constraints & Requirements

Decisions locked during discovery (Rounds 0–2 with the user):

- Flow: `type: feature`, `base_branch: dev`.
- The DevLoop session-state sample (`sdd/artifacts/devloop_session_state.py`) is
  **out of scope** — ignore it for this feature.
- `IdentityMixin` lives at `parrot/bots/mixins/identity.py` (the `bots/mixins/`
  package already exists with `IntentRouterMixin`).
- Missing identity file → **silent fallthrough** to class attr / package default
  (same behavior as `load_agent_context` on a missing file).
- Ship **both** the mixin **and** a registered `"identity"` PromptBuilder preset.
- **Hot-reload per build**: edits to `identity/*.md` apply to the next system
  prompt without restarting the agent.
- Porygon migration is **in scope** as the reference implementation.
- Hard constraints carried from the draft spec: don't change `AbstractBot`'s
  resolution order; don't edit `IDENTITY_LAYER`; no DB storage; no registry
  auto-discovery magic; non-adopters must be byte-for-byte unchanged.
- House rules: async-first, Pydantic models, `self.logger`, no new third-party deps.

---

## Options Explored

### Option A: Spec baseline — construct-time load, CONFIGURE-phase capabilities layer

The draft spec as written. `IdentityMixin.__init__` loads the five `.md` files
once, injects non-empty values as instance attributes before `super().__init__`
(so `AbstractBot`'s `getattr(self, field)` resolution picks them up, and explicit
kwargs still win), and adds a CONFIGURE-phase `CAPABILITIES_LAYER`
(priority `IDENTITY + 1` = 11) to a per-instance `clone()` of the builder.
Identity is fixed for the agent's lifetime.

✅ **Pros:**
- Smallest delta; matches the existing two-phase render design exactly (CONFIGURE
  layers bake once, stay cacheable for FEAT-181 prompt caching).
- No new hook points in `AbstractBot`; zero per-request overhead.
- Precedence semantics fall out of the existing resolution order for free.

❌ **Cons:**
- **No hot reload** — rejected by the user in Round 2: persona edits must apply
  without restart.
- Editing a persona requires bouncing the agent, which is exactly the friction
  this feature exists to remove.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | `IdentityFields` model | existing dependency |

🔗 **Existing Code to Reuse:**
- `parrot/bots/prompts/agent_context.py:38` — `_read_cached(path, mtime)` lru-cached reader
- `parrot/bots/prompts/builder.py:208` — `PromptBuilder.clone()` for the per-instance copy

---

### Option B: Mixin + registered "identity" preset, full hot reload via pristine-clone re-configure  ⭐

Everything in Option A, plus:

1. **Hot reload of all five fields.** The mixin keeps a *pristine* (never-configured)
   clone of the builder with `CAPABILITIES_LAYER` added. On each system-prompt
   assembly it calls `load_identity()` — near-free thanks to the
   `(path, mtime)`-keyed `lru_cache` — and compares against the last-applied
   `IdentityFields`. On change: update the instance identity attributes, re-clone
   the pristine builder, re-run configure. This is mandatory because
   `PromptBuilder.configure()` **destroys the original templates** — it replaces
   layers with partially-rendered copies (builder.py:234-241), so `$backstory` et
   al. cannot be re-substituted on an already-configured builder.
2. **`"identity"` preset** registered via `register_preset("identity", factory)`
   (presets.py:24): default stack + `CAPABILITIES_LAYER`. Builder-savvy agents can
   adopt via the existing `prompt_preset` kwarg (`get_preset` is called in
   `AbstractBot.__init__`, abstract.py:535-536) without inheriting the mixin —
   they get the capabilities rendering, but file loading/hot reload stays
   mixin-only.
3. **Mixin wiring mirrors the real pattern** (not the spec's assumed
   `super().configure()` cooperation, which does not exist): an opt-in class flag
   (`enable_identity: bool = False`) plus an `async _configure_identity()`
   coroutine that adopting agents call explicitly after `await super().configure()`
   — exactly how Porygon already calls `_configure_episodic_memory()` /
   `_configure_skill_registry()` (agents/porygon.py:322-326).

✅ **Pros:**
- Delivers every discovery decision: mixin + preset, full five-field hot reload,
  silent fallthrough, Porygon migration path.
- Persona iteration becomes edit-file → next message reflects it; huge DX win for
  prompt engineers.
- Hot-reload cost is bounded: five `stat()` calls per prompt build on the happy
  path; the expensive re-clone + re-configure runs only when an mtime changed.
- `IDENTITY_LAYER` and `AbstractBot` resolution order untouched; non-adopters
  render byte-for-byte identically.

❌ **Cons:**
- Needs an interception point for prompt assembly — the mixin overrides
  `create_system_prompt` (abstract.py:2733) or `_build_prompt` (abstract.py:1242)
  and delegates to `super()`; the exact hook is a spec-level decision.
- Re-configure on change re-bakes *all* CONFIGURE layers (agent_context, security,
  etc.), and invalidates provider prompt-cache segments for that turn — acceptable:
  it only happens when someone actually edited a persona file.
- Slightly more state in the mixin (pristine clone + last-applied fields).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | `IdentityFields` model | existing dependency |

🔗 **Existing Code to Reuse:**
- `parrot/bots/prompts/agent_context.py:38` — `_read_cached(path, mtime)` mtime-keyed reader (promote or wrap)
- `parrot/bots/prompts/builder.py:208` — `clone()`; `builder.py:223` — `configure()`
- `parrot/bots/prompts/presets.py:24,34` — `register_preset` / `get_preset`
- `parrot/skills/mixin.py:57` + `parrot/memory/episodic/mixin.py:100,181` — the flag + `_configure_*()` pattern to mirror
- `parrot/bots/mixins/__init__.py` — export site (currently only `IntentRouterMixin`)

---

### Option C: Capabilities-only hot reload — REQUEST-phase CAPABILITIES_LAYER

Make `CAPABILITIES_LAYER` a REQUEST-phase layer; the mixin injects fresh
`capabilities` file content into the per-request build context. `role`, `goal`,
`backstory`, `rationale` load once at construction (Option A behavior).

✅ **Pros:**
- No pristine-clone machinery; hot reload falls out of the existing per-request
  `build()` path (builder.py:243).
- Simple, low-risk change.

❌ **Cons:**
- **Partial hot reload** — the user asked for persona edits (all five fields) to
  apply live; here backstory/role edits still need a restart. Confusing split.
- REQUEST-phase layers default to `cacheable=False` (layers.py:75-80), so the
  capabilities block is excluded from FEAT-181 prompt-cache segments on every turn.
- Still needs a request-context injection point in the mixin, so it saves less
  complexity than it appears.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | `IdentityFields` model | existing dependency |

🔗 **Existing Code to Reuse:**
- Same loader/reader reuse as Option A; `parrot/bots/abstract.py:1242` `_build_prompt` request-context assembly.

---

### Option D (unconventional): Sectioned single-file identity via the agent-context convention

No new directory convention: extend the existing whole-blob channel. One
`<AGENT_CONTEXT_DIR>/<agent_id>.identity.md` with `## Role` / `## Goal` /
`## Capabilities` / `## Backstory` / `## Rationale` headings, parsed into the five
fields by a small Markdown-section splitter; delivery reuses `load_agent_context`'s
directory + caching machinery.

✅ **Pros:**
- One file per agent — trivially diffable persona, single artifact to deploy.
- Reuses an existing, deployed convention (`AGENT_CONTEXT_DIR`) instead of adding
  a second file-layout concept.

❌ **Cons:**
- Conflates two channels: `agent_context` is a free-form appendix layer
  (priority 12, agent_context.py:96-107) with different semantics than structured
  identity fields; overloading its directory invites confusion.
- Heading-based parsing is fragile (personas legitimately contain `##` headings
  inside backstory prose) and needs escaping rules.
- Per-field files are the better unit of reuse — e.g. several agents sharing one
  `rationale.md` via `identity_dir` pointing at a shared directory.
- Contradicts the agreed agent-local `identity/` directory design.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | `IdentityFields` model | existing dependency |

🔗 **Existing Code to Reuse:**
- `parrot/bots/prompts/agent_context.py:57-89` — directory resolution + silent-missing behavior.

---

## Recommendation

**Option B** is recommended because:

- It is the only option that satisfies all Round-2 decisions simultaneously:
  mixin **and** preset, **full** five-field hot reload, Porygon in scope. Option A
  fails hot reload outright; Option C delivers a confusing half of it while losing
  prompt-cache eligibility for the capabilities block every turn; Option D
  contradicts the agreed per-field layout and overloads an unrelated convention.
- Its main cost — pristine-clone + re-configure machinery — is precisely scoped:
  it exists because `configure()` irreversibly bakes templates (verified at
  builder.py:234-241), and it runs only when a persona file actually changed.
  Steady-state per-request overhead is five cached `stat()`-keyed lookups.
- What we trade off: a small amount of mixin state and one interception point in
  the prompt-assembly path. Acceptable — the interception is a `super()` delegation
  in the mixin, no `AbstractBot` edits, and non-adopters are provably untouched
  (flag defaults to `False`).

---

## Feature Description

### User-Facing Behavior

- An agent author creates an `identity/` directory next to the agent's module
  (default `Path(inspect.getfile(type(self))).parent / "identity"`, overridable via
  `identity_dir`), containing any subset of `role.md`, `goal.md`, `capabilities.md`,
  `backstory.md`, `rationale.md`.
- Adding `IdentityMixin` + `enable_identity = True` to the agent class makes those
  files the agent's identity. All five blocks — including a new
  `<capabilities>…</capabilities>` block — appear in the assembled system prompt.
- Editing any identity file takes effect on the **next** system-prompt assembly —
  no restart (hot reload).
- Explicit constructor kwargs still override file values; missing files silently
  fall through to class attributes / package defaults.
- Agents that only want the capabilities rendering (managing content themselves)
  can use `prompt_preset="identity"` without the mixin.
- Porygon ships as the reference: inline `BACKSTORY` removed, five
  `agents/porygon/identity/*.md` files added.

### Internal Behavior

1. **Loader** (`parrot/bots/prompts/identity.py`): `load_identity(directory) →
   IdentityFields` (Pydantic, five `Optional[str]` fields, `as_kwargs()` filters
   empties). Reads UTF-8, strips; each read goes through the mtime-keyed cached
   reader so repeated loads are dict lookups until a file changes. Missing file or
   missing directory → field(s) `None`, debug-level log only.
2. **Layer** (`parrot/bots/prompts/domain_layers.py`): `CAPABILITIES_LAYER` —
   frozen `PromptLayer`, `priority=LayerPriority.IDENTITY + 1` (11, just after
   identity at 10 and before agent_context at 12), `phase=CONFIGURE`,
   template `<capabilities>\n$capabilities\n</capabilities>`, condition = non-empty
   `capabilities`. Registered as `"capabilities"` in `_DOMAIN_LAYERS`.
3. **Preset** (`parrot/bots/prompts/presets.py`): `register_preset("identity", …)`
   → fresh `PromptBuilder.default()` + `CAPABILITIES_LAYER`.
4. **Mixin** (`parrot/bots/mixins/identity.py`): before `super().__init__`, loads
   identity and sets non-empty fields as instance attributes (so `AbstractBot`'s
   `kwarg → getattr(self, …) → DEFAULT` resolution keeps kwargs winning and files
   beating class attributes); sets `self.capabilities` explicitly (the `PandasAgent`
   path swallows the `capabilities` kwarg into `self._capabilities`, data.py:550,586).
   During `_configure_identity()`: clone the agent's *effective* builder (instance
   attribute when set via `prompt_builder`/`prompt_preset`, else the class
   attribute), add `CAPABILITIES_LAYER`, stash the pristine clone. At
   prompt-assembly time (override of `_build_prompt` — resolved open question —
   delegating to `super()`): re-run `load_identity`; if fields differ from last
   applied, update attributes, re-clone pristine, re-configure, carry over any
   transient layers present on the old builder but not the clone (e.g.
   `skill_active`, added by `create_system_prompt` before `_build_prompt` runs),
   then swap `self._prompt_builder`.
5. **Porygon**: add `IdentityMixin` first in bases, `enable_identity = True`,
   delete the `BACKSTORY` constant and its kwarg, call
   `await self._configure_identity()` in `configure()` alongside the existing
   mixin `_configure_*` calls.

### Edge Cases & Error Handling

- **Missing dir / missing files**: silent fallthrough (debug log), never an error.
- **Empty or whitespace-only file**: treated as missing (field `None`) so the
  fallthrough chain is not short-circuited by an empty string.
- **`$tokens` in identity markdown**: injected verbatim, NO escaping (resolved
  open question). Dynamic variables (`$current_date`, …) are intentionally
  pre-resolved inside identity fields by `_configure_prompt_builder`'s
  `_resolve()` (abstract.py:1200-1214) — file personas keep parity with inline
  ones. Leftover `$tokens` that collide with REQUEST-context keys substitute at
  request time (`safe_substitute`, layers.py:93-119) — pre-existing property of
  inline identity; document it, optionally offer `escape_placeholders=False`
  loader flag.
- **Concurrent requests during a reload**: builder swap must be atomic (build the
  new configured builder fully, then assign) so in-flight `build()` calls use a
  consistent snapshot.
- **Unreadable file (permissions, decode error)**: log warning, treat as missing.
- **Non-adopters**: flag `False` → mixin is inert; no layer added, no per-request
  stats, prompt byte-for-byte unchanged (regression-tested).
- **Hot-reload thrash**: mtime granularity means at most one re-configure per
  change; identical content with touched mtime re-configures harmlessly.

---

## Capabilities

### New Capabilities
- `promptbuilder-identity-capability`: file-based per-field agent identity
  (loader + `CAPABILITIES_LAYER` + `IdentityMixin` + `"identity"` preset) with
  hot reload; Porygon migrated as reference.

### Modified Capabilities
- (none — existing specs untouched)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/prompts/domain_layers.py` | extends | `CAPABILITIES_LAYER` + `"capabilities"` entry in `_DOMAIN_LAYERS` (line 576) |
| `parrot/bots/prompts/presets.py` | extends | `register_preset("identity", …)` in `_PRESETS` |
| `parrot/bots/prompts/identity.py` | new | `IdentityFields` + `load_identity` |
| `parrot/bots/mixins/identity.py` | new | `IdentityMixin`; export from `bots/mixins/__init__.py` |
| `parrot/bots/prompts/agent_context.py` | depends on | reuse/promote `_read_cached` (private today) |
| `parrot/bots/abstract.py` | depends on | no edits planned — mixin overrides + delegates; relies on resolution order (432-452) and `_configure_prompt_builder` context (1213) |
| `agents/porygon.py` + `agents/porygon/identity/` | modifies / new | reference migration; BACKSTORY (11-133) removed |
| FEAT-181 prompt caching | interacts | re-configure invalidates cacheable segments only on actual persona change |

No breaking changes; no new dependencies; no deployment/config changes (identity
dir is agent-local by default).

---

## Code Context

### User-Provided Code

The user provided `sdd/artifacts/devloop_session_state.py` alongside the draft
spec; per Round 1 it is **out of scope** for this feature (recorded here only so
downstream agents don't go looking for a connection). The draft spec
`sdd/proposals/identitycapability.spec.md` is the substantive input; its proposed
`IdentityFields` / `load_identity` / `IdentityMixin` sketches are carried into
this brainstorm with the corrections noted below.

### Verified Codebase References

All paths relative to `packages/ai-parrot/src/` unless noted. Verified 2026-07-21
against `dev`.

#### Classes & Signatures
```python
# From parrot/bots/prompts/layers.py
class LayerPriority(IntEnum):  # line 22: IDENTITY=10, PRE_INSTRUCTIONS=15, SECURITY=20,
    ...                        # KNOWLEDGE=30, USER_SESSION=40, TOOLS=50, OUTPUT=60,
                               # BEHAVIOR=70, CUSTOM=80
class RenderPhase(str, Enum):  # line 35 — CONFIGURE="configure" (46), REQUEST="request" (47)
@dataclass(frozen=True)
class PromptLayer:             # line 50
    name: str; priority: LayerPriority | int; template: str
    phase: RenderPhase = RenderPhase.REQUEST
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    required_vars: frozenset[str]; cacheable: Optional[bool]  # cacheable defaults from phase (75-80)
    def render(self, context) -> Optional[str]: ...           # line 82 — Template.safe_substitute
    def partial_render(self, context) -> PromptLayer: ...     # line 96 — returns REQUEST-phase copy
IDENTITY_LAYER   # line 142 — CONFIGURE, priority IDENTITY; template OMITS $capabilities (comment 137-141)
BEHAVIOR_LAYER   # line 232 — CONFIGURE, priority BEHAVIOR; renders $rationale, condition non-empty

# From parrot/bots/prompts/domain_layers.py
KNOWLEDGE_SCOPE_LAYER          # line 154 — CONFIGURE, priority KNOWLEDGE-5; renders $capabilities (RAG-only)
_DOMAIN_LAYERS: Dict[str, PromptLayer]  # line 576 — 10 keys, NO "capabilities"
def get_domain_layer(name: str) -> PromptLayer: ...  # line 590 — raises KeyError

# From parrot/bots/prompts/builder.py
class PromptBuilder:                                   # line 21
    def __init__(self, layers=None, *, prompt_caching=False)  # line 36
    @classmethod default() / minimal() / voice() / agent() / rag() / from_system_prompt()
    #   lines 52/66/72/98/106/122 — default() = IDENTITY..BEHAVIOR, NO capabilities/knowledge_scope
    def add(self, layer) -> PromptBuilder    # line 152 — MUTATES in place, returns self
    def remove(self, name) -> PromptBuilder  # line 164 — mutates in place
    def replace(self, name, layer)           # line 176
    def clone(self) -> PromptBuilder         # line 208 — deep copy, preserves _configured
    def configure(self, context) -> None     # line 223 — REPLACES layers with partial_render
    #   copies (234-241) → original templates are LOST after configure; sets _configured=True
    def build(self, context) -> str          # line 243 — per-request; renders remaining layers
    def build_segments(self, context)        # line 272 — FEAT-181 cacheable segments

# From parrot/bots/prompts/presets.py
_PRESETS  # line 15 — {"default","minimal","voice","agent","rag"}
def register_preset(name, factory)  # line 24
def get_preset(name)                # line 34 — fresh builder per call; used by AbstractBot.__init__ (abstract.py:535-536)

# From parrot/bots/abstract.py
class AbstractBot:
    system_prompt_template = BASIC_SYSTEM_PROMPT   # line 214 (legacy path only)
    _prompt_builder: Optional[PromptBuilder] = None  # line 223 — CLASS attribute
    # identity resolution, __init__ lines 432-452:
    #   self.<field> = kwargs.get(f) or getattr(self, f, None) or DEFAULT_<F>
    #   (backstory default constant is spelled DEFAULT_BACKHISTORY)
    async def _configure_prompt_builder(self)      # line 1179 — called ONCE from configure()
    #   (1423-1425, guarded by `not is_configured`); sets
    #   configure_context["capabilities"] = _resolve(getattr(self, 'capabilities', ''))  # line 1213
    def _build_prompt(...)                          # line 1242 — per-request; builder.build() at 1311
    async def create_system_prompt(...)             # line 2733 — per-message entry; _build_prompt at 2774

# From parrot/bots/prompts/agent_context.py
@functools.lru_cache(maxsize=256)
def _read_cached(path: str, mtime: float) -> str   # line 38 — (path, mtime) cache key
def load_agent_context(agent_id: str) -> str       # line 57 — missing file → "" SILENTLY (88-89)
AGENT_CONTEXT_LAYER                                 # line 96 — CONFIGURE, priority 12, cacheable

# From parrot/bots/data.py
def _build_pandas_prompt_builder() -> PromptBuilder  # line 431 — default() + dataframe/grounding/pandas
class PandasAgent(IntentRouterMixin, BasicAgent):    # line 514
    _prompt_builder = _build_pandas_prompt_builder() # line 535 — SHARED class attribute
    def __init__(..., capabilities: str = None, ...) # line 550 — swallowed → self._capabilities (586)

# Mixin pattern to mirror (opt-in flag + explicit _configure_* call — NOT super().configure() cooperation):
# parrot/skills/mixin.py:27  class SkillRegistryMixin: enable_skill_registry=True (57);
#                            async _configure_skill_registry() guarded by the flag (105-108)
# parrot/memory/episodic/mixin.py:77  EpisodicMemoryMixin: enable_episodic_memory=False (100);
#                            async _configure_episodic_memory() (181, guard at 195)
# agents/porygon.py:322-326 — Porygon.configure(): await super().configure(...) then
#                            await self._configure_episodic_memory(); await self._configure_skill_registry()

# Porygon (repo-root agents/, NOT inside the package):
# agents/porygon.py:11-133 BACKSTORY constant; :136 @register_agent("porygon", at_startup=True);
# :137 class Porygon(SkillRegistryMixin, EpisodicMemoryMixin, PandasAgent);
# :160-179 super().__init__(..., backstory=BACKSTORY, ...)
# agents/porygon/ contains only skills/ — no identity/ directory yet.
```

#### Verified Imports
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

#### Key Attributes & Constants
- `AbstractBot._prompt_builder` → `Optional[PromptBuilder]`, class attr (abstract.py:223)
- `PromptBuilder.is_configured` → property gating one-shot configure (used abstract.py:1423-1425)
- `PromptLayer.cacheable` → derived `phase == CONFIGURE` when unset (layers.py:75-80)
- `AGENT_CONTEXT_LAYER.priority == 12` → new capabilities layer at 11 slots between identity (10) and it
- `DEFAULT_BACKHISTORY` — note the spelling; it is the backstory package default (abstract.py:443-446)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/bots/prompts/identity.py`~~ / ~~`IdentityFields`~~ / ~~`load_identity`~~ — new (M2).
- ~~`parrot/bots/mixins/identity.py`~~ / ~~`IdentityMixin`~~ — new (M3).
- ~~`CAPABILITIES_LAYER`~~ / ~~a `"capabilities"` key in `_DOMAIN_LAYERS`~~ — new (M1).
- ~~an `"identity"` entry in `_PRESETS`~~ — new (M1/M3).
- ~~`agents/porygon/identity/`~~ — new (M4); today `agents/porygon/` holds only `skills/`.
- ~~`IDENTITY_LAYER` rendering `$capabilities`~~ — it does NOT and will NOT (by design).
- ~~mixins cooperating via `super().configure()` overrides~~ — the draft spec assumed
  this; in reality neither `SkillRegistryMixin` nor `EpisodicMemoryMixin` overrides
  `configure()`; agents call `_configure_*()` explicitly. Follow the real pattern.
- ~~`PromptBuilder.add()` returning a new builder~~ — it mutates in place and returns
  `self`; the copy primitive is `clone()` (builder.py:208).
- ~~re-configuring an already-configured builder with new values~~ — impossible;
  `configure()` discards original templates (builder.py:234-241). Hot reload MUST
  go through a pristine clone.

---

## Parallelism Assessment

- **Internal parallelism**: limited. M1 (layer + preset) and M2 (loader) are
  independent of each other, but both are small; M3 (mixin) depends on M1+M2, and
  M4 (Porygon) depends on M3. A single sequential worktree is the natural shape.
- **Cross-feature independence**: touches `parrot/bots/prompts/` (domain_layers,
  presets, new identity module), `parrot/bots/mixins/`, and `agents/porygon.py`.
  No overlap with in-flight work (adaptive-cards builder lives under
  `packages/ai-parrot-integrations/`; the dev-loop session-state proposal has no
  code yet).
- **Recommended isolation**: `per-spec`.
- **Rationale**: four small, chained modules with a shared touchpoint
  (`prompts/` package) — one worktree, tasks in dependency order, avoids
  cross-worktree merge noise for ~zero parallel speedup.

---

## Open Questions

- [x] Assign the real `FEAT-<NNN>` id — *Owner: jlara*: highest assigned id today
      is FEAT-320 → tentative **FEAT-321**. `/sdd-spec` MUST re-scan
      `sdd/tasks/index/` + `sdd/specs/` at spec-commit time (concurrent sessions
      have collided on ids before, cf. FEAT-306/307).
- [x] Hot-reload hook: override `create_system_prompt` (abstract.py:2733) or
      `_build_prompt` (abstract.py:1242)? — *Owner: jlara*: override
      **`_build_prompt`**, with skill-layer compatibility. Verified mechanics:
      `create_system_prompt` `add()`s the transient `skill_active` layer
      (abstract.py:2772) BEFORE calling `_build_prompt` (2774) and `remove()`s it
      after (2786). Therefore when the override swaps `self._prompt_builder`
      (identity changed → re-clone + re-configure), it MUST carry over any layers
      present on the old builder but absent from the pristine clone (e.g.
      `skill_active`) before delegating to `super()._build_prompt(...)`.
      `PromptBuilder.remove()` is a no-op on missing names (builder.py:164-174),
      so the post-call cleanup is safe either way — carry-over only prevents a
      one-turn silent drop of the active skill.
- [x] Promote `agent_context._read_cached` to a public helper (e.g.
      `read_text_cached`) vs. the identity loader importing the private name or
      shipping its own copy — *Owner: jlara*: promote to a public helper —
      `read_text_cached(path)` in `agent_context.py` that stats mtime and calls
      the existing lru-cached private, keeping one shared cache.
- [x] `$`-escaping policy for identity file content — *Owner: jlara → verified*:
      **do NOT escape by default.** Escaping would break `dynamic_values`:
      `_configure_prompt_builder` deliberately pre-resolves dynamic variables
      (`$current_date`, `$local_time`, …) INSIDE identity fields via
      `_resolve()` → `Template.safe_substitute(dynamic_context)`
      (abstract.py:1200-1214, comment at 1200-1203 states this is intentional).
      Escaping `$`→`$$` at load time would strip that supported capability from
      file-based personas, breaking parity with inline/kwarg identity. Policy:
      inject file content verbatim (same behavior as inline BACKSTORY today);
      document that unresolved `$tokens` colliding with REQUEST-context keys
      (`$user_context`, `$knowledge_content`, …) will substitute at request time
      — a pre-existing property of inline identity, not a regression. Optionally
      expose `escape_placeholders: bool = False` on the loader for locked-down
      personas.
- [x] Should the `"identity"` preset ALSO be what the mixin clones from (single
      source of the capabilities-augmented stack), or does the mixin always clone
      the agent's own class builder and just `add(CAPABILITIES_LAYER)`? (Porygon
      needs the latter — its builder carries pandas layers.) — *Owner: jlara*:
      mixin clones the agent's own builder + `add(CAPABILITIES_LAYER)`. Caveat:
      clone the agent's *effective* builder — the instance attribute when set
      (`prompt_builder` kwarg / `prompt_preset` via `get_preset`,
      abstract.py:533-536), else the class attribute. `add()` is
      add-or-replace-by-name, so combining the mixin with
      `prompt_preset="identity"` cannot double-add the layer.
- [x] Flow type/base — *Owner: jlara*: feature → dev.
- [x] Role of `devloop_session_state.py` — *Owner: jlara*: out of scope; ignore.
- [x] Mixin module path — *Owner: jlara*: `parrot/bots/mixins/identity.py`.
- [x] Missing-file behavior — *Owner: jlara*: silent fallthrough (like `load_agent_context`).
- [x] Preset in addition to mixin? — *Owner: jlara*: yes, ship both.
- [x] Builder-copy strategy — *Owner: jlara*: brainstorm compares; recommendation is
      per-instance pristine `clone()` (required anyway for hot reload).
- [x] Hot reload — *Owner: jlara*: yes, per build (mtime-based).
- [x] Porygon migration in scope — *Owner: jlara*: yes, reference implementation.

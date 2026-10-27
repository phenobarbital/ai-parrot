---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-server, ai-parrot-integrations, admin-ui, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [suggestions, followup-chips, chat-response, skills, output-mode, admin-ui]
# e2e: optional deterministic-E2E-gate policy metadata (FEAT-581). Absent
#   entirely (the default for every spec written before this feature) means
#   the generated e2e-plan.md's policy defaults to `optional` when loaded.
#   `policy` MUST be exactly `required`, `optional` or `none` — an
#   unrecognized value fails plan loading closed, it is never coerced to a
#   default. `scenario_ids` are the plan's stable `ScenarioSpec.id` values,
#   kept in sync with the "### E2E Scenarios" subsection below (§4). Omit
#   this whole key for a feature with no E2E surface.
# e2e:
#   policy: optional
#   scenario_ids: []
---

# Feature Specification: Follow-up Suggestion Chips (server-produced, agent-grounded)

**Feature ID**: FEAT-752
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD (next minor — ai-parrot / ai-parrot-server)
**Source**: Jira NAV-10382 ("metrics copilot" follow-up chips) — ticket review of 2026-10-27 moved suggestion
production from the frontend to the agent; this spec carries that decision. No brainstorm/proposal document exists.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

NAV-10382 asked for a row of follow-up chips under every inline chat answer of the "metrics copilot"
("vs last month", "by dimension", "as line / bar / table / KPI", "Explain this"). The first design put a
hard-coded chip catalog and an intent parser in the frontend. That approach has three defects the ticket review
recorded on 2026-10-27:

1. **The frontend cannot know what the agent can do.** Only the agent knows which output modes it can render
   (`parrot.outputs.formats.RENDERERS` is populated lazily per installed package — `outputs/formats/__init__.py:48-73`),
   which skill is active for the request (`SkillRegistryMixin._active_skill`, `skills/mixin.py:101-108`), and whether
   the answer carries tabular data worth re-presenting.
2. **Every client re-implements the catalog.** The admin UI (`packages/ai-parrot-server/ui`), navigator-frontend-next,
   Telegram and Teams would each carry their own copy, drifting independently.
3. **Suggestions should be grounded in the answer.** "What would the user ask next?" is a cheap, bounded LLM task
   that the agent can run on the lightweight model *after* the answer, with the question and answer as context.

Today nothing in the response carries suggestions: `AIMessage` (`parrot/models/responses.py:93-382`) has no
`suggestions`/`followup`/`chips` field (grep over `parrot/models/` returned zero hits), the `AgentTalk` envelopes
(`handlers/agent.py:2685-2729` stream finaliser, `:2927-2977` JSON path) forward only the fields listed in
`parrot.server.ui.chat_models.AgentChatResponse` (`chat_models.py:67-90`), and `ChatBubble.svelte` renders no
chips — its only "Reply" / "Explain" affordances are hover-revealed side buttons (`ChatBubble.svelte:632-667`).

### Goals

- **G1 — Additive wire field.** `AIMessage.suggestions: list[Suggestion]` (empty by default) and the same key on the
  JSON response and on the final stream envelope. An agent that does not opt in produces byte-identical bodies.
- **G2 — Agent-side production.** A cooperative `SuggestionProvider` protocol and a per-bot registry: deterministic
  providers first (skill-declared chips, presentation chips, the "Explain this" action), then an **opt-in** LLM lane
  that uses the lightweight `AbstractClient.invoke()` path, never a second `ask()`, never blocking or failing the
  answer, with capped latency/tokens and cost recorded in `AIMessage.metadata["suggestions"]`.
- **G3 — Only offer what the agent can emit.** Presentation chips ("View as table / chart / KPI") are offered only
  for output modes with a registered renderer and only when the answer has tabular data.
- **G4 — Skills as a deterministic producer.** A skill's frontmatter may declare `suggestions:`; they are emitted
  when that skill is the request's active skill (tenant views and `global_only` semantics untouched — FEAT-707).
- **G5 — Extension point for FEAT-756.** `register_suggestion_provider()` lets the metric-definition registry plug
  "vs last month / by <dimension>" chips later; this spec defines the protocol and does **not** implement metrics.
- **G6 — Reference renderer.** The ai-parrot-server admin UI renders chips under the assistant bubble; a click
  sends `prompt` (+ optional `output_mode`) through the existing `handleSend` path, and the "Explain this" chip maps to
  the existing `handleExplain` path (`AgentChat.svelte:1687-1725` → `bot.followup()`, `handlers/agent.py:1869-1882`).
- **G7 — Documented channel coverage.** Teams and A2A ignore the field in v1 (justification in §2); Telegram renders
  chips as inline-keyboard quick replies when the bot opts in (rev 0.3, Module 9); the wire contract is documented
  so navigator-frontend-next can consume it without reading Python.
- **G8 — Non-blocking stream tail (rev 0.3, Q1).** A stream client that sends `suggestions_trailer: true` receives
  the final envelope immediately and the chips in a separate trailing frame (Module 8); clients that do not ask
  keep the v1 wire byte-for-byte.
- **G9 — Agent Studio settings (rev 0.3, Q5).** The five chip settings are editable in the admin agent form
  (Capabilities tab) and reach database-stored bots (Module 10).

### Non-Goals (explicitly out of scope)

- Client-side intent parsing or chip catalogs (the design NAV-10382 abandoned).
- Metric catalogs, period comparison or dimension discovery — **FEAT-756** `metric-definition-registry`
  (it will register a provider against the protocol defined here).
- New A2UI components or inline component routing — **FEAT-755**.
- navigator-frontend-next changes (consumer of the wire contract only).
- Rendering chips as Teams `suggestedActions` / A2A parts (deferred — §2 "Channel degradation"). Telegram buttons
  are IN scope since rev 0.3 (Module 9); Telegram group/channel chats are not (private-chat path only).
- Persisting suggestions in `ChatStorage` / conversation history reloads (chips are shown for the live turn only).
- Changing `parrot/clients/base.py` (`AbstractClient.invoke()` is consumed as-is).

---

## 2. Architectural Design

### Overview

Suggestions are computed **once, after the answer is final** and attached to the `AIMessage` before it leaves the bot.
Both bot entry points already converge on a single "response is final" point — the FEAT-396 output guardrail
pipeline — so the attachment hook sits right after it:

- `BaseBot.ask()`: `response = await self._run_output_pipeline(response, method="ask")` (`bots/base.py:1735`) → **new**
  `response = await self._attach_suggestions(question, response, output_mode=output_mode)` → existing hooks / `return`.
- `BaseBot.ask_stream()`: after `_run_output_pipeline(..., "ask_stream")` and the FEAT-611 linked-surface lift
  (`bots/base.py:2273-2284`) → **new** attach → `yield ai_message` (`:2303`). Suggestions therefore travel **only in the
  final envelope** of a stream (the `\n\x00`-separated JSON dict `_handle_stream_response` writes at
  `handlers/agent.py:2685-2732`), never in text chunks.

`_attach_suggestions` delegates to a `SuggestionEngine` that runs registered providers in **three lanes**:

| Lane | Providers | Gate | I/O |
|---|---|---|---|
| `skill` | `SkillSuggestionProvider` | always (a skill declaring `suggestions:` is the author's opt-in) | none (ContextVar read) |
| `deterministic` | `PresentationSuggestionProvider`, `ExplainSuggestionProvider`, externally registered (FEAT-756) | `enable_suggestions=True` | none |
| `llm` | `LLMSuggestionProvider` | `suggest_followups=True` (implies `enable_suggestions`) | one `AbstractClient.invoke()` call on the lightweight model, `asyncio.wait_for(timeout=suggestion_timeout_s)` |

The engine never raises: each provider runs under `try/except` + timeout, failures are logged and recorded in
`metadata["suggestions"]["providers"][name]["status"]`, deterministic chips always survive an LLM failure, the list
is de-duplicated by case-folded label, truncated to `max_suggestions` (default 6, LLM contributes ≤ 4), and every
chip carrying an `output_mode` is dropped unless `parrot.outputs.formats.get_renderer(mode)` succeeds (fail-closed:
a chip can never request a mode the server cannot render — the same crash class the handler guards against at
`handlers/agent.py:1664-1678`).

The server is **envelope-agnostic**: the handler forwards `suggestions` the way it forwards `a2ui_envelope` — an
additive key, present only when non-empty, at the four passthrough sites. The schema source of truth is the Pydantic
mirror `parrot.server.ui.chat_models.AgentChatResponse`; `scripts/generate_ts_types.py` exports
`ui/schemas/AgentChatResponse.json` and `pnpm generate` (`json2ts`, `ui/package.json:15`) produces the `.d.ts` —
generated files are never hand-edited (`test_ts_codegen.py::test_schemas_in_sync_with_committed` guards drift).

The admin UI renders `message.suggestions` as a chip row below the bubble (after the sources panel). A click calls
`onSuggestion(message, suggestion)`: `action == "explain"` → the existing `handleExplain(message.id, message.data)`;
otherwise `handleSend(suggestion.prompt, undefined, suggestion.output_mode)` — the normal chat path, so the server
sees an ordinary turn with conversation history (and `output_mode` keeps its top precedence:
`AbstractBot._apply_default_output_mode`, `bots/abstract.py:4191-4210`, is only consulted for `DEFAULT`).

**Channel degradation (decision).** Telegram, MS Teams and A2A **ignore** `suggestions` in v1 — no code change in
`ai-parrot-integrations` or `parrot/a2a`. Evidence: all three map an `AIMessage` through structures with no
"action" concept — Telegram/Teams via `parse_response(response) -> ParsedResponse`
(`integrations/parser.py:416`, dataclass `:86-110`: text, images, documents, media, urls, charts, code, table — no
buttons), Teams replies with `MessageFactory.text` (`msteams/handler.py:40`) and uses `CardAction` only for sign-in
(`msteams/auth.py:444`), A2A emits `Part.from_text` artifacts (`a2a/server.py:1529`) plus A2UI parts (`:588`).
Rendering chips as Telegram quick replies is **not** a mapping change: Telegram `callback_data` is a short opaque
token, so the chip prompt cannot ride in the button — it needs a turn-scoped server store plus a `callbacks.py`
prefix handler (`build_inline_keyboard`, `telegram/callbacks.py:318`), i.e. a feature of its own (§8 Q3). Because the
field is additive and defaults to `[]`, these channels are unaffected and a custom wrapper can still read
`AIMessage.suggestions`. **Rev 0.3 (Q3):** that Telegram feature is now part of this spec as Module 9 (opt-in
`suggestion_buttons`); Teams and A2A keep ignoring the field.

### Component Diagram
```
                       BaseBot.ask() / ask_stream()            (bots/base.py:1735 / :2273-2303)
                                   │ response final (after _run_output_pipeline)
                                   ▼
                 AbstractBot._attach_suggestions(question, response, output_mode)      [M2]
                                   │
                                   ▼
                          SuggestionEngine.collect(ctx)                                 [M2]
            ┌──────────────────────┼───────────────────────────┐
            ▼                      ▼                           ▼
   lane "skill" (always)   lane "deterministic"          lane "llm" (suggest_followups=True)
   SkillSuggestionProvider (enable_suggestions=True)     LLMSuggestionProvider            [M4]
   current_active_skill()  PresentationSuggestionProvider  get_client() → client.invoke(
   SkillDefinition         ExplainSuggestionProvider         output_type=SuggestionBatch,
     .suggestions [M3]     <FEAT-756 provider later>         max_tokens=256) + wait_for()
            └──────────────────────┼───────────────────────────┘
                                   ▼  dedupe · cap 6 · renderer check (get_renderer)
                    AIMessage.suggestions: list[Suggestion]                              [M1]
                    AIMessage.metadata["suggestions"] = {...cost/status...}
                                   │
                                   ▼
   AgentTalk envelopes (stream final dict · JSON · A2UI JSON · infographic JSON)         [M5]
   AgentChatResponse.suggestions → schemas/AgentChatResponse.json → generated .d.ts
                                   │
                                   ▼
   AgentChat.svelte (finalMessage.suggestions) → ChatBubble → SuggestionChips.svelte     [M6]
       click: action=="explain" → handleExplain(turn)   else → handleSend(prompt, _, output_mode)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AIMessage` (`models/responses.py:93`) | extends (new field) | `suggestions: List[Suggestion] = []`, placed after `a2ui_envelope` (`:212-219`); `render_as()` (`:369-382`) dumps/reloads it unchanged |
| `AbstractBot.__init__` (`bots/abstract.py:556`) | extends (kwargs) | `enable_suggestions`, `suggest_followups`, `suggestion_timeout_s`, `max_suggestions` read like `operation_mode` (`:553`) |
| `AbstractBot` (`bots/abstract.py:4191`) | extends (methods) | `register_suggestion_provider()`, `_default_suggestion_providers()`, `_attach_suggestions()` next to `_apply_default_output_mode` |
| `BaseBot.ask()` / `ask_stream()` (`bots/base.py:1735`, `:2303`) | uses (call site) | one `await self._attach_suggestions(...)` per entry point, after the output pipeline |
| `AbstractBot.get_client()` (`bots/abstract.py:1218`) | uses | LLM lane enters the client it returns (cooperative with `ModelSwitchingMixin`) |
| `AbstractClient.invoke()` (`clients/base.py:1952`) | uses | lightweight stateless call; `_resolve_invoke_model` (`:2054-2088`) picks `_lightweight_model` when no explicit model |
| `SkillDefinition` / `parse_skill_file` (`skills/models.py:60`, `skills/parsers.py:69`) | extends | new optional `suggestions:` frontmatter key → `SkillDefinition.suggestions` |
| `current_active_skill()` (`skills/tenancy.py:97`) | uses | request-local active skill (FEAT-707 S5) |
| `parrot.outputs.formats.get_renderer` (`outputs/formats/__init__.py:94`) | uses | capability check for presentation chips and for every chip's `output_mode` |
| `AgentTalk` envelopes (`handlers/agent.py:2727`, `:2874`, `:2975`, `:3282`) | extends (passthrough) | additive `suggestions` key, mirrors `a2ui_envelope` passthrough |
| `AgentChatResponse` (`server/ui/chat_models.py:67`) | extends | `suggestions: list[AgentChatSuggestion] = []` → schema + TS regeneration |
| `ChatBubble.svelte` (`:154`, `:1757`) / `AgentChat.svelte` (`:1033`, `:1374`, `:1559`, `:1677`, `:2442`) | extends | prop + chip row; handler + three final-message mappings |
| `BasicAgent.followup()` (`bots/agent.py:1510`) | reused unchanged | target of the "Explain this" chip via the existing `turn_id`+`data` request path |

### Data Models
```python
# packages/ai-parrot/src/parrot/models/suggestions.py  (new)
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .outputs import OutputMode  # verified: parrot/models/outputs.py:23


class SuggestionKind(str, Enum):
    """What the chip does when clicked."""
    FOLLOWUP = "followup"          # a new question grounded on this answer
    PRESENTATION = "presentation"  # same answer, different output_mode
    ACTION = "action"              # client-side action (v1: "explain")


class SuggestionSource(str, Enum):
    """Who produced the chip."""
    LLM = "llm"
    SKILL = "skill"
    PROVIDER = "provider"


class Suggestion(BaseModel):
    """One follow-up chip. Wire shape is identical for every channel (FEAT-752)."""
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    label: str = Field(min_length=1, max_length=40, description="Chip text (≤ 40 chars)")
    prompt: str = Field(min_length=1, max_length=500, description="Text sent through the normal chat path on click")
    output_mode: Optional[OutputMode] = Field(default=None, description="Explicit mode for the click turn, if any")
    kind: SuggestionKind = SuggestionKind.FOLLOWUP
    source: SuggestionSource = SuggestionSource.PROVIDER
    action: Optional[str] = Field(default=None, description='Client action id; v1 allows only "explain" (kind=action)')

    @field_validator("label", "prompt")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        """Collapse whitespace; reject blank values."""


class SuggestionBatch(BaseModel):
    """Structured output requested from the lightweight model (LLM lane)."""
    suggestions: List[Suggestion] = Field(default_factory=list, max_length=4)
```

```python
# AIMessage extension — packages/ai-parrot/src/parrot/models/responses.py (after a2ui_envelope, :212-219)
suggestions: List[Suggestion] = Field(
    default_factory=list,
    description="Follow-up chips produced by the agent after the answer (FEAT-752). Empty unless the agent opts in.",
)
# metadata["suggestions"] (set by the engine, always a plain dict):
# {"enabled_lanes": ["skill","deterministic","llm"], "count": 3,
#  "providers": {"<name>": {"status": "ok|timeout|error|skipped", "count": n, "elapsed_ms": f}},
#  "llm": {"model": str, "usage": {prompt_tokens, completion_tokens, total_tokens}, "elapsed_ms": f} | None}
```

```python
# Skill frontmatter (SkillDefinition extension) — packages/ai-parrot/src/parrot/skills/models.py
class SkillSuggestion(BaseModel):
    """A chip declared in a skill's YAML frontmatter under `suggestions:`."""
    label: str = Field(min_length=1, max_length=40)
    prompt: str = Field(min_length=1, max_length=500)
    output_mode: Optional[str] = None   # validated against OutputMode by the provider, not at parse time

# SkillDefinition gains: suggestions: list[SkillSuggestion] = Field(default_factory=list)
```

```yaml
# Example skill frontmatter
---
name: sales-analyst
description: Monthly sales analysis helpers
triggers: [/sales]
suggestions:
  - label: "vs last month"
    prompt: "Compare the same figures against the previous month"
  - label: "As KPI"
    prompt: "Show the headline number as a KPI card"
    output_mode: card
---
```

```python
# Server mirror — packages/ai-parrot-server/src/parrot/server/ui/chat_models.py (pydantic-only file, no parrot imports)
class AgentChatSuggestion(BaseModel):
    """Mirror of parrot.models.suggestions.Suggestion for the generated TS types."""
    label: str
    prompt: str
    output_mode: str | None = None
    kind: str = "followup"
    source: str = "provider"
    action: str | None = None

# AgentChatResponse gains: suggestions: list[AgentChatSuggestion] = []
```

Wire contract (JSON response and final stream envelope — key **omitted** when the list is empty):
```json
{
  "input": "...", "output": "...", "metadata": {"turn_id": "...", "suggestions": {"count": 3, "...": "..."}},
  "suggestions": [
    {"label": "vs last month", "prompt": "Compare the same figures against the previous month",
     "output_mode": null, "kind": "followup", "source": "skill", "action": null},
    {"label": "View as table", "prompt": "Show the previous answer as a table",
     "output_mode": "structured_table", "kind": "presentation", "source": "provider", "action": null},
    {"label": "Explain this", "prompt": "Explain this answer", "output_mode": null,
     "kind": "action", "source": "provider", "action": "explain"}
  ]
}
```
Client contract: for `kind != action`, send `prompt` as a new chat turn with `output_mode` when present; for
`action == "explain"`, send the existing explain request (`query`, `turn_id`, `data`) — `handlers/agent.py:1688-1689`
pops `turn_id`/`data` and routes to `bot.followup()` (`:1869-1882`).

### New Public Interfaces
```python
# packages/ai-parrot/src/parrot/bots/suggestions/protocol.py  (new)
@dataclass(frozen=True)
class SuggestionContext:
    """Everything a provider may look at. `bot` is the producing bot (read-only use)."""
    question: str
    response: AIMessage
    output_mode: OutputMode
    bot: Any
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tenant: Optional[str] = None


class SuggestionProvider(Protocol):
    """Cooperative chip producer. Pure/async, must not raise (the engine guards anyway)."""
    name: str
    lane: Literal["skill", "deterministic", "llm"]
    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]: ...


# AbstractBot (bots/abstract.py) — public surface added by M2
def register_suggestion_provider(self, provider: SuggestionProvider, *, prepend: bool = False) -> None: ...
# constructor kwargs: enable_suggestions: bool = False, suggest_followups: bool = False,
#                     suggestion_timeout_s: float = 4.0, max_suggestions: int = 6
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

Mark which modules can be implemented by the targeted writer from an
already-decided TASK packet. Architecture decisions always stay with the
thinking model; eligibility only means "the design is complete enough that
writing the code is mechanical".

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `Suggestion` models + `AIMessage.suggestions` | yes | field list in §2; `extra="forbid"`, `use_enum_values=True`; label ≤ 40, prompt ≤ 500; `action` only with `kind=action`; export from `parrot.models` | — |
| M2: Protocol + `SuggestionEngine` + bot wiring | yes | lanes/gates table in §2; dedupe by `label.casefold()`; cap `max_suggestions`; renderer check via `get_renderer`; `asyncio.wait_for` per provider; metadata shape fixed in §2; two call sites in `base.py` | — |
| M3: Deterministic providers + skill frontmatter | yes | rules in §7 ("Presentation rules", "Explain rule", "Skill rule"); `SkillSuggestion` model; parser reads `suggestions:` like `global_only` | — |
| M4: `LLMSuggestionProvider` | yes | `get_client()` → `async with client as entered` → `entered.invoke(prompt, output_type=SuggestionBatch, max_tokens=256, temperature=0.3)`; prompt template fixed in §7; answer text truncated to 2 000 chars; ≤ 4 chips; `source="llm"` forced; cost → `metadata["suggestions"]["llm"]` | — |
| M5: Server wire + schema regeneration | yes | `AgentChatSuggestion` mirror; four passthrough sites listed in §6 with the exact `a2ui_envelope` pattern; regenerate with `python scripts/generate_ts_types.py` then `pnpm generate` | — |
| M6: Admin-UI reference renderer | yes | `SuggestionChips.svelte` props/events fixed in §3; `onSuggestion(message, s)` contract; three mapping sites; DaisyUI `btn btn-xs btn-outline` chips, hidden while streaming | — |
| M7: Docs | yes | `docs/agents/followup-suggestion-chips.md` sections listed in §7 | — |

### Module 1: `Suggestion` models + `AIMessage.suggestions`
- **Path**: `packages/ai-parrot/src/parrot/models/suggestions.py` (new); modifies `packages/ai-parrot/src/parrot/models/responses.py:9,212`, `packages/ai-parrot/src/parrot/models/__init__.py:8`
- **Responsibility**: the wire model of a chip, the structured-output batch for the LLM lane, the additive
  `AIMessage` field and its package export.
- **Depends on**: `parrot.models.outputs.OutputMode` (existing)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/models/suggestions.py  (new)
  class SuggestionKind(str, Enum):
      """followup | presentation | action."""

  class SuggestionSource(str, Enum):
      """llm | skill | provider."""

  class Suggestion(BaseModel):
      """One chip (fields in §2). `action` is allowed only when kind == action and must be "explain" in v1."""
      @field_validator("label", "prompt")
      @classmethod
      def _strip_nonempty(cls, v: str) -> str:
          """Collapse internal whitespace, strip, reject empty."""
      @model_validator(mode="after")
      def _action_consistency(self) -> "Suggestion":
          """Raise ValueError when action is set without kind=action, or kind=action without action."""

  class SuggestionBatch(BaseModel):
      """LLM structured output: `suggestions`, at most 4."""

  # parrot/models/responses.py  (modifies parrot/models/responses.py:9 import block, :212 field block)
  from .suggestions import Suggestion                      # verified anchor: parrot/models/responses.py:9
  class AIMessage(BaseModel):                              # verified: parrot/models/responses.py:93
      suggestions: List[Suggestion] = Field(default_factory=list, description="...")  # after a2ui_envelope, :212-219

  # parrot/models/__init__.py  (modifies parrot/models/__init__.py:8)
  from .suggestions import Suggestion, SuggestionBatch, SuggestionKind, SuggestionSource  # + __all__ entries
  ```

### Module 2: `SuggestionProvider` protocol, `SuggestionEngine`, bot wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/suggestions/__init__.py`, `protocol.py`, `engine.py` (new);
  modifies `packages/ai-parrot/src/parrot/bots/abstract.py:556,4191` and `packages/ai-parrot/src/parrot/bots/base.py:1735,2303`
- **Responsibility**: the extension point (protocol + registry), lane gating, timeout/dedupe/cap/renderer checks,
  metadata accounting, and the two call sites that attach suggestions after the answer is final.
- **Depends on**: Module 1; `parrot.outputs.formats.get_renderer` (existing); `AbstractBot.get_client()` (existing)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/bots/suggestions/protocol.py  (new)
  @dataclass(frozen=True)
  class SuggestionContext:
      """question, response (AIMessage), output_mode, bot, user_id, session_id, tenant — see §2."""

  class SuggestionProvider(Protocol):
      """name: str; lane: Literal["skill","deterministic","llm"]; async suggest(ctx) -> Sequence[Suggestion]."""

  # parrot/bots/suggestions/engine.py  (new)
  class SuggestionEngine:
      """Runs providers lane by lane; never raises; returns (suggestions, metadata)."""
      def __init__(self, *, max_suggestions: int = 6, max_llm_suggestions: int = 4,
                   timeout_s: float = 4.0, logger: Optional[logging.Logger] = None) -> None:
          """Caps and per-provider timeout. `timeout_s` applies to every provider, not only the LLM lane."""
      def register(self, provider: SuggestionProvider, *, prepend: bool = False) -> None:
          """Append (or prepend) a provider; duplicate `name` replaces the previous registration."""
      @property
      def providers(self) -> tuple[SuggestionProvider, ...]:
          """Registration order, skill lane first, llm lane last (stable within a lane)."""
      async def collect(self, ctx: SuggestionContext, *, lanes: frozenset[str]) -> tuple[list[Suggestion], dict[str, Any]]:
          """Run providers whose lane ∈ lanes. Each under try/except + asyncio.wait_for(timeout_s).
          Post-process: drop chips whose output_mode has no renderer (get_renderer raises ValueError),
          dedupe by label.casefold() (first wins), llm lane ≤ max_llm_suggestions, total ≤ max_suggestions.
          Returns the list and the metadata dict (§2 shape). Never raises."""

  def renderer_available(mode: "OutputMode | str | None") -> bool:
      """True when mode is None or parrot.outputs.formats.get_renderer(OutputMode(mode)) succeeds."""  # get_renderer verified: parrot/outputs/formats/__init__.py:94

  # parrot/bots/suggestions/__init__.py  (new)
  # re-exports: SuggestionContext, SuggestionProvider, SuggestionEngine, renderer_available,
  #             SkillSuggestionProvider, PresentationSuggestionProvider, ExplainSuggestionProvider, LLMSuggestionProvider

  # parrot/bots/abstract.py  (modifies parrot/bots/abstract.py:556 ctor; :4191 methods)
  class AbstractBot(...):                                                   # verified: parrot/bots/abstract.py:201
      # __init__, next to `self.default_output_mode = output_mode`          # verified: parrot/bots/abstract.py:556
      #   self.enable_suggestions: bool = kwargs.get("enable_suggestions", False) or kwargs.get("suggest_followups", False)
      #   self.suggest_followups: bool = kwargs.get("suggest_followups", False)
      #   self.suggestion_timeout_s: float = float(kwargs.get("suggestion_timeout_s", 4.0))
      #   self.max_suggestions: int = int(kwargs.get("max_suggestions", 6))
      #   self._suggestion_engine: Optional[SuggestionEngine] = None   (built lazily by _get_suggestion_engine)
      def register_suggestion_provider(self, provider: SuggestionProvider, *, prepend: bool = False) -> None:
          """Public registry hook (FEAT-756 plugs here). Builds the engine on first use."""
      def _default_suggestion_providers(self) -> list[SuggestionProvider]:
          """Skill, Presentation, Explain, LLM providers bound to self. Mixins may extend via super()."""
      def _get_suggestion_engine(self) -> SuggestionEngine:
          """Lazily create the engine with self.max_suggestions / self.suggestion_timeout_s and the defaults."""
      def _suggestion_lanes(self) -> frozenset[str]:
          """{"skill"} ∪ ({"deterministic"} if enable_suggestions) ∪ ({"llm"} if suggest_followups)."""
      async def _attach_suggestions(self, question: str, response: AIMessage, *, output_mode: OutputMode,
                                    user_id: Optional[str] = None, session_id: Optional[str] = None) -> AIMessage:
          """Collect chips and set response.suggestions + response.metadata["suggestions"]. Skips the engine
          entirely (no metadata written) when lanes == {"skill"} and current_active_skill() declares none.
          Never raises; returns the same AIMessage instance."""

  # parrot/bots/base.py  (modifies parrot/bots/base.py:1735 and :2303 — call sites only)
  #   ask():        response = await self._run_output_pipeline(response, method="ask")           # verified :1735
  #                 response = await self._attach_suggestions(question, response, output_mode=output_mode,
  #                                                           user_id=user_id, session_id=session_id)
  #   ask_stream(): ... linked-surface lift (verified :2276-2284) ...
  #                 ai_message = await self._attach_suggestions(question, ai_message, output_mode=output_mode, ...)
  #                 yield ai_message                                                               # verified :2303
  ```

### Module 3: Deterministic providers + skill frontmatter `suggestions:`
- **Path**: `packages/ai-parrot/src/parrot/bots/suggestions/providers.py` (new); modifies
  `packages/ai-parrot/src/parrot/skills/models.py:81`, `packages/ai-parrot/src/parrot/skills/parsers.py:123,136`
- **Responsibility**: the three built-in deterministic producers and the skill-side declaration they read.
- **Depends on**: Module 1, Module 2; `current_active_skill` (`skills/tenancy.py:97`); `get_renderer`
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/skills/models.py  (modifies parrot/skills/models.py:81 — after global_only)
  class SkillSuggestion(BaseModel):
      """Chip declared under `suggestions:` in skill frontmatter (label ≤ 40, prompt ≤ 500, output_mode str|None)."""
  class SkillDefinition(BaseModel):                                          # verified: parrot/skills/models.py:60
      suggestions: list[SkillSuggestion] = Field(default_factory=list, description="FEAT-752 chips emitted when active")

  # parrot/skills/parsers.py  (modifies parrot/skills/parsers.py:123 and :136)
  def parse_skill_file(file_path: Path) -> SkillDefinition:                # verified: parrot/skills/parsers.py:69
      """Unchanged contract; additionally reads optional `suggestions` (list of mappings) — a non-list value
      raises ValueError naming the file, mirroring the `triggers` handling at :90-100."""

  # parrot/bots/suggestions/providers.py  (new)
  class SkillSuggestionProvider:
      """lane="skill". Emits current_active_skill().suggestions as Suggestion(kind=followup|presentation,
      source=skill); kind=presentation when output_mode is set. No skill or no suggestions → []."""
      name = "skill"; lane = "skill"
      def __init__(self, bot: Any) -> None: ...
      async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]: ...

  class PresentationSuggestionProvider:
      """lane="deterministic". Offers 'View as table/chart/KPI' per §7 "Presentation rules"; only for modes with a
      registered renderer and never the response's current output_mode."""
      name = "presentation"; lane = "deterministic"
      DEFAULT_MODES: ClassVar[tuple[tuple[OutputMode, str, str], ...]]  # (mode, label, prompt) — §7
      def __init__(self, bot: Any, *, modes: Optional[Sequence[OutputMode]] = None) -> None: ...
      async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]: ...

  class ExplainSuggestionProvider:
      """lane="deterministic". One chip: label "Explain this", kind=action, action="explain", source=provider —
      only when the answer has data (§7 "Explain rule") and the bot exposes a callable `followup`."""
      name = "explain"; lane = "deterministic"
      def __init__(self, bot: Any) -> None: ...
      async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]: ...

  def has_tabular_data(response: AIMessage) -> bool:
      """True for a non-empty list of dicts in response.data, or an object with .to_dict/.to_string (DataFrame)."""
  ```

### Module 4: `LLMSuggestionProvider` (opt-in lane)
- **Path**: `packages/ai-parrot/src/parrot/bots/suggestions/llm.py` (new)
- **Responsibility**: grounded follow-up questions from the lightweight model, bounded in time and tokens, with cost
  accounting; never a second `ask()`.
- **Depends on**: Module 1, Module 2; `AbstractBot.get_client()` (`bots/abstract.py:1218`); `AbstractClient.invoke()`
  (`clients/base.py:1952`); `InvokeResult` (`models/responses.py:1329`)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/bots/suggestions/llm.py  (new)
  SUGGESTION_PROMPT: Final[str]  # template in §7 "LLM prompt"

  class LLMSuggestionProvider:
      """lane="llm". client = bot.get_client(); async with client as entered:
      result = await entered.invoke(prompt, output_type=SuggestionBatch, max_tokens=max_tokens, temperature=0.3)
      Returns ≤ max_items chips with source forced to "llm" and kind=followup; output_mode never set by this lane.
      Records {"model": result.model, "usage": result.usage.model_dump(), "elapsed_ms": ...} on self.last_cost
      for the engine to copy into metadata["suggestions"]["llm"]. Any exception → [] (engine logs)."""
      name = "llm"; lane = "llm"
      def __init__(self, bot: Any, *, max_items: int = 4, max_tokens: int = 256,
                   answer_chars: int = 2000, temperature: float = 0.3) -> None: ...
      async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]: ...
      @property
      def last_cost(self) -> Optional[dict[str, Any]]:
          """Cost record of the most recent call, or None."""

  def _answer_text(response: AIMessage, limit: int) -> str:
      """response.to_text truncated to `limit` chars (verified: AIMessage.to_text, parrot/models/responses.py:246)."""
  ```

### Module 5: Server wire — `AgentChatResponse.suggestions`, handler passthrough, schema regeneration
- **Path**: modifies `packages/ai-parrot-server/src/parrot/server/ui/chat_models.py:88`,
  `packages/ai-parrot-server/src/parrot/handlers/agent.py:2727,2874,2975,3282`; regenerates
  `packages/ai-parrot-server/ui/schemas/AgentChatResponse.json` and
  `packages/ai-parrot-server/ui/src/lib/types/generated/AgentChatResponse.d.ts`
- **Responsibility**: additive, omitted-when-empty `suggestions` key on every `AgentTalk` body; the Pydantic mirror
  that drives the committed JSON schema and the generated TS type.
- **Depends on**: Module 1 (field name/shape only — `chat_models.py` stays import-free of `parrot.models`)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/server/ui/chat_models.py  (modifies parrot/server/ui/chat_models.py:88)
  class AgentChatSuggestion(BaseModel):
      """Mirror of parrot.models.suggestions.Suggestion (fields in §2). Pydantic-only, like the rest of this file."""
  class AgentChatResponse(BaseModel):                     # verified: parrot/server/ui/chat_models.py:67
      suggestions: list[AgentChatSuggestion] = []        # after a2ui_envelope (:88)

  # parrot/handlers/agent.py  (modifies four passthrough sites; pattern == a2ui_envelope passthrough)
  #   stream finaliser  (:2727-2729)  → _suggestions = getattr(ai_message, "suggestions", None)
  #                                      if _suggestions: envelope["suggestions"] = [s.model_dump(mode="json") for s in _suggestions]
  #   A2UI JSON branch  (:2874)        → add "suggestions" entry to the dict only when non-empty (build dict, then conditional key)
  #   JSON path         (:2975-2977)   → same as stream finaliser on `response` → obj_response
  #   infographic JSON  (:3282-3284)   → same on `response` → obj_response
  # scripts/generate_ts_types.py needs NO change: AgentChatSuggestion lands in $defs via AgentChatResponse
  # (registry entry verified: scripts/generate_ts_types.py:97). Regenerate:
  #   PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src python scripts/generate_ts_types.py
  #   cd packages/ai-parrot-server/ui && pnpm generate
  ```

### Module 6: Admin-UI reference renderer
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/SuggestionChips.svelte`,
  `SuggestionChips.test.ts` (new); modifies `packages/ai-parrot-server/ui/src/lib/types/agent.ts:51`,
  `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte:154,1757`,
  `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte:1033,1374,1559,1677,2442`
- **Responsibility**: render chips under the assistant bubble and route clicks through the existing send / explain
  paths. Svelte 5 runes only; `vitest` + `@testing-library/svelte` next to the component.
- **Depends on**: Module 5 (generated `AgentChatSuggestion` type)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```ts
  // src/lib/types/agent.ts  (modifies :51 — after a2ui_envelope?)
  export interface AgentMessage {                                          // verified: ui/src/lib/types/agent.ts:25
    suggestions?: import("$lib/types/generated/AgentChatResponse").AgentChatSuggestion[];  // FEAT-752, live turn only
  }

  // src/lib/components/agents/SuggestionChips.svelte  (new)
  // Props ($props): { suggestions: AgentChatSuggestion[]; disabled?: boolean; onSelect: (s: AgentChatSuggestion) => void }
  // Renders one <button class="btn btn-xs btn-outline rounded-full" data-kind={s.kind} data-testid="suggestion-chip">
  // per item (title = s.prompt); renders nothing for an empty list.

  // src/lib/components/agents/ChatBubble.svelte  (modifies :154 props, :1757 render)
  //   onSuggestion?: (message: AgentMessage, suggestion: AgentChatSuggestion) => void;   // next to onExplain (:154)
  //   {#if !isUser && !isStreaming && onSuggestion && message.suggestions?.length}
  //     <SuggestionChips suggestions={message.suggestions} onSelect={(s) => onSuggestion(message, s)} />
  //   {/if}                                                                   // right after <SourcesPanel …/> block (:1756-1758)

  // src/lib/components/agents/AgentChat.svelte
  //   function handleSuggestion(message: AgentMessage, s: AgentChatSuggestion): void   // after handleFollowup (:1677)
  //     action === "explain" → handleExplain(message.id, message.data)
  //     else → handleSend(s.prompt, undefined, s.output_mode ?? undefined)
  //   <ChatBubble … onSuggestion={handleSuggestion} />                         // next to onExplain={handleExplain} (:2442)
  //   finalMessage mappings: suggestions: agentResult.suggestions (:1033) / result.suggestions (:1374, :1559)
  ```

### Module 7: Docs
- **Path**: `docs/agents/followup-suggestion-chips.md` (new)
- **Responsibility**: operator/agent-author/frontend documentation: opt-in kwargs, skill frontmatter, provider
  protocol (with a FEAT-756-style example), wire contract (JSON + stream), client click contract, channel degradation,
  cost/latency knobs.
- **Depends on**: all modules
- **Interface Skeleton**: n/a (Markdown; section list in §7 "Docs").

### Module 8: Stream suggestions trailer (rev 0.3 — Q1)
- **Paths**: `parrot/models/responses.py` (`AIMessage._suggestions_task` private attr), `parrot/bots/base.py`
  (`ask_stream`), `parrot/handlers/agent.py` (`post` flag pop + `_handle_stream_response`), admin UI
  `src/lib/api/stream.ts` + `AgentChat.svelte`.
- **Responsibility**: when the agent stream request body carries `suggestions_trailer: true`, the final envelope goes
  out without waiting for the chips, and the chips follow in a second NUL-separated frame before EOF:
  `<text>\n\x00{envelope}\n\x00{"suggestions": [...], "turn_id": "<turn>"}`. Without the flag the v1 wire is
  byte-identical (chips inside the envelope). The trailer frame is written only when the list is non-empty.
- **Bot side**: `ask_stream(..., defer_suggestions=True)` (popped from `kwargs`, never forwarded) starts
  `_attach_suggestions(...)` as an `asyncio.Task` right before `yield ai_message` instead of awaiting it, and stores
  it on `ai_message._suggestions_task` (pydantic `PrivateAttr`, never serialised). `asyncio.create_task` copies the
  current context, so `current_turn_skill()` and the tenant ContextVars still hold when the task runs after the
  generator's `finally` has reset them. **No extra item is yielded** — about 15 other `ask_stream` consumers
  (`handlers/stream.py`, `openai_compat.py`, `a2a/server.py`, Slack, agentd, voice, CLI) would mis-handle one.
- **Handler**: pops `suggestions_trailer` next to `avatar_bifurcate` (`handlers/agent.py:1694`) so it never leaks into
  `**data` → `bot.ask_stream(**kwargs)`; passes `defer_suggestions=True`; sets `X-Parrot-Stream:
  chunked-aimessage+suggestions`; never puts `suggestions` in the envelope on this path (deterministic regardless of
  task timing); after the envelope `write`+`drain` awaits the task with
  `asyncio.wait_for(..., timeout=bot.suggestion_timeout_s + 1.0)` and writes the trailer; cancels the task on client
  cancel / error. A timeout or task failure only means no trailer.
- **UI**: `consumeStream` splits every frame on NUL (JSON text never contains a raw NUL): it yields `done` as soon as
  the second NUL arrives (or at EOF, as today), then `{type: "suggestions", suggestions, turn_id}` for a trailer frame
  that carries `suggestions`; any other trailing frame (e.g. a late `{"error": ...}`) is ignored. `AgentChat.svelte`
  sends `suggestions_trailer: true` in the agent stream payload, swaps the pending bubble for the final message inside
  the `done` branch (the bubble completes immediately) and patches `suggestions` onto that message when the trailer
  arrives. `streamChatWithBot` and the non-stream paths are unchanged. Chips stay live-turn only (no ChatStorage).
- **Depends on**: M2 (`_attach_suggestions`), M5 (handler passthrough site 1), M6 (`AgentChat.svelte` mappings).

### Module 9: Telegram quick-reply buttons (rev 0.3 — Q3)
- **Paths** (`packages/ai-parrot-integrations/src/parrot/integrations/telegram/`): `suggestion_buttons.py` (new),
  `models.py` (`TelegramAgentConfig`), `wrapper.py`.
- **Responsibility**: opt-in `suggestion_buttons: bool = False` and `suggestion_button_ttl_s: int = 86400` on
  `TelegramAgentConfig` (+ `from_dict`). After `handle_message` sends the reply, the non-`action` chips (≤ 6, two per
  row, label ≤ 40 chars) go out as a short "💡 Follow-ups:" message with an inline keyboard. Each button's
  `callback_data` is `sg:<token>` (`secrets.token_urlsafe(9)`, well under Telegram's 64-byte limit — `CallbackData.MAX_BYTES`);
  the token maps, in a TTL store backed by `InMemoryStateStore` (`integrations/core/state.py:14`), to
  `{prompt, output_mode, chat_id, user_id}`. The wrapper registers the `sg` prefix with `CallbackRegistry.register`
  (`callbacks.py:271`) **before** `_register_handlers()` (`wrapper.py:230`), because the `callback_query` route is only
  installed when the registry is non-empty (`wrapper.py:364`). A press: unknown/expired token → toast "expired";
  clicker or chat ≠ the stored ones → toast, no turn; otherwise the prompt is replayed as a new turn through
  `_invoke_agent` (stored `output_mode` mapped to `OutputMode`, fallback `OutputMode.TELEGRAM`) and the reply is sent
  with its own chips. `kind == "action"` chips (explain) are never rendered on Telegram (no explain path there).
  Group/channel chats (`_process_group_query`) are unchanged.
- **Depends on**: M1 (`Suggestion`).

### Module 10: Agent Studio settings (rev 0.3 — Q5)
- **Paths**: `parrot/models/bots.py` (`BotModel`), `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` (new),
  `parrot/manager/manager.py` (`_build_database_bot`), `parrot/server/ui/models.py` (`BotWritePayload`) + the
  regenerated `ui/schemas/BotWritePayload.json` / `generated/BotWritePayload.d.ts`, `ui/src/lib/agents/fields.ts`,
  `ui/src/pages/agents/form/TabsCapabilities.svelte`.
- **Responsibility**: make `enable_suggestions`, `suggest_followups`, `suggestion_timeout_s`, `max_suggestions` and
  `suggestion_model` editable for database-stored agents. Bot construction from the DB goes through two hard-coded
  key lists — `BotModel.to_bot_config()` (create/update path) and `BotManager._build_database_bot()` (startup/reload
  path) — so both forward the five fields. Defaults equal the constructor defaults (`False`, `False`, `4.0`, `6`,
  `None`). The columns land on `navigator.ai_bots` through an idempotent migration that must be applied before deploy
  (a missing column fails every `BotModel` read — FEAT-593 precedent). The Capabilities tab gets a "Follow-up
  suggestions" group (two switches, two number inputs, one optional text input). `presentation_modes` stays
  code/YAML-only.
- **Depends on**: M2 (kwarg semantics/defaults), M5 (both regenerate `ui/schemas` — serialized).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_suggestion_label_max_40` | M1 | 41-char label → `ValidationError`; 40 passes |
| `test_suggestion_action_requires_kind_action` | M1 | `action="explain"` with `kind=followup` rejected; `kind=action` without action rejected |
| `test_aimessage_suggestions_default_empty_and_roundtrip` | M1 | default `[]`; `model_dump`/`render_as` preserve chips |
| `test_engine_never_raises_and_records_status` | M2 | provider raising / timing out → `[]` for it, status `error`/`timeout`, others kept |
| `test_engine_lane_gating` | M2 | lanes `{skill}` skips deterministic+llm providers; `{skill,deterministic}` skips llm |
| `test_engine_dedupe_cap_and_renderer_check` | M2 | duplicate labels collapse; total ≤ 6, llm ≤ 4; chip with unregistered mode dropped |
| `test_bot_attach_noop_without_optin` | M2 | `enable_suggestions=False`, no active skill → `suggestions == []`, no `metadata["suggestions"]` |
| `test_bot_register_provider_prepend` | M2 | externally registered provider runs before built-ins when `prepend=True` |
| `test_ask_and_ask_stream_attach_once` | M2 | both entry points call `_attach_suggestions` exactly once, after the output pipeline |
| `test_skill_frontmatter_suggestions_parsed` | M3 | `suggestions:` list → `SkillDefinition.suggestions`; absent → `[]`; non-list → `ValueError` |
| `test_skill_provider_emits_only_active_skill` | M3 | chips emitted iff `current_active_skill()` is that skill |
| `test_presentation_provider_rules` | M3 | no data → `[]`; current mode excluded; unregistered renderer excluded |
| `test_explain_provider_requires_data_and_followup` | M3 | emitted only with data and a callable `followup` |
| `test_llm_provider_uses_invoke_not_ask` | M4 | fake client: `invoke` called once with `output_type=SuggestionBatch`, `ask` never |
| `test_llm_provider_cost_recorded_and_capped` | M4 | `last_cost` has model/usage/elapsed; > 4 items truncated; `source` forced to `llm` |
| `test_llm_provider_failure_is_silent` | M4 | `invoke` raising → `[]`; deterministic chips still attached by the engine |
| `test_chat_models_suggestions_schema` | M5 | `AgentChatResponse` schema has `suggestions` with `AgentChatSuggestion` in `$defs` |
| `test_stream_and_json_passthrough_suggestions` | M5 | key present iff non-empty on the stream finaliser, JSON, A2UI JSON and infographic bodies |
| `SuggestionChips.test.ts` | M6 | renders N chips, click fires `onSelect` with the chip, empty list renders nothing |
| `ChatBubble.test.ts` (extended) | M6 | chips visible for assistant message with suggestions; hidden while streaming / for user role |
| `AgentChat.test.ts` (extended) | M6 | explain chip → explain payload (`turn_id`,`data`); presentation chip → `output_mode` in payload |

### Integration Tests
| Test | Description |
|---|---|
| `test_suggestions_end_to_end_fake_client` | `BaseBot.ask()` with a fake client, `suggest_followups=True`, an active skill declaring chips and tabular data: skill → presentation → explain → llm order, metadata populated, JSON body carries the key |

### Validation Contract

> FEAT-699. Explicit pytest operands (repo-relative file or `file::node`) that gate this feature in ALL
> tiers — task, merge, feature (`/sdd-done`) and QA. When present it REPLACES the heuristic breadth
> (import impact, suite escalation); the nightly workflow covers everything else. Write
> `none — fallback` to opt out explicitly (bounded fallback: tasks' own tests + direct importers).
> Never list `real_llm` tests. `integration`/`e2e`-marked operands listed here DO run.
> `/sdd-task` caches this list into the per-spec index header (`test_contract`).

runners:
- kind: pytest
  tests:
  - packages/ai-parrot/tests/unit/models/test_aimessage_artifact_id.py
  - packages/ai-parrot/tests/models/test_aimessage_url_fields.py
  - packages/ai-parrot/tests/bots/test_linked_surface_lifting.py
  - packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py
  - packages/ai-parrot/tests/unit/test_skill_definition.py
  - packages/ai-parrot/tests/unit/test_skill_global_only.py
  - packages/ai-parrot-server/tests/test_chat_models.py
  - packages/ai-parrot-server/tests/test_ts_codegen.py
  - packages/ai-parrot-server/tests/handlers/test_structured_envelope_passthrough.py
  - packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py
  - packages/ai-parrot-server/tests/test_agenttalk_dual_emit.py
  - packages/ai-parrot/tests/unit/models/test_suggestion_models.py
  - packages/ai-parrot/tests/unit/test_skill_turn_scope.py
  - packages/ai-parrot/tests/unit/test_skill_tenant_hardening.py
  - packages/ai-parrot/tests/unit/test_skill_tenancy.py
  - packages/ai-parrot/tests/unit/test_skill_suggestions_frontmatter.py
  - packages/ai-parrot/tests/bots/test_suggestion_engine.py
  - packages/ai-parrot/tests/bots/test_suggestion_providers.py
  - packages/ai-parrot/tests/bots/test_suggestion_llm_provider.py
  - packages/ai-parrot/tests/bots/test_suggestion_bot_wiring.py
  - packages/ai-parrot-server/tests/handlers/test_suggestions_passthrough.py
  - packages/ai-parrot-server/tests/ui/test_vitest_suggestion_chips.py
  - packages/ai-parrot-server/tests/ui/test_vitest_suggestion_chat_wiring.py
  - packages/ai-parrot/tests/bots/test_suggestion_stream_deferred.py
  - packages/ai-parrot-server/tests/handlers/test_suggestions_trailer.py
  - packages/ai-parrot-server/tests/ui/test_vitest_suggestion_stream_trailer.py
  - packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons.py
  - packages/ai-parrot-integrations/tests/telegram/test_suggestion_buttons_wrapper.py
  - packages/ai-parrot-integrations/tests/telegram/test_tenant_binding.py
  - packages/ai-parrot/tests/test_callbacks.py
  - packages/ai-parrot-server/tests/test_botmodel_suggestion_fields.py
  - packages/ai-parrot-server/tests/manager/test_build_database_bot_tools.py
  - packages/ai-parrot/tests/handlers/test_bot_model_fields.py
  - packages/ai-parrot-server/tests/ui/test_vitest_studio_suggestion_fields.py
  markers: none
- kind: vitest
  cwd: packages/ai-parrot-server/ui
  tests:
  - src/lib/components/agents/ChatBubble.test.ts
  - src/lib/components/agents/AgentChat.test.ts
  - src/lib/api/stream.test.ts
  - src/lib/components/agents/SuggestionChips.test.ts
  - src/lib/agents/fields.test.ts
  - src/pages/agents/form/TabsCapabilities.test.ts

> Multi-runner form (FEAT-709) — use it INSTEAD of the flat form above when the feature has non-pytest tests
> (replace the flat lines; never write both). Kinds, tiers and settings come from `.parrot/test_runners.toml`;
> the flat form stays valid and is lifted on read to one pytest runner.

> New test files created by this feature are listed above as operands (rev 0.2, `/sdd-task`); each is created by
> the task whose Validation Commands name it.

### Test Data / Fixtures
```python
# Key fixtures needed
@pytest.fixture
def ai_message_with_table() -> AIMessage:
    """AIMessage(input='q', output='text', data=[{"month": "Sep", "sales": 10}, {"month": "Oct", "sales": 12}],
    model='fake', provider='fake', usage=CompletionUsage(...), output_mode=OutputMode.DEFAULT)."""

@pytest.fixture
def fake_invoke_client():
    """Async-context-manager client whose invoke() returns InvokeResult(output=SuggestionBatch(...), model='fake-lite',
    usage=CompletionUsage(...)); records calls; ask() raises AssertionError('ask must not be called')."""

@pytest.fixture
def skill_with_suggestions(tmp_path) -> SkillDefinition:
    """parse_skill_file() over a tmp .md whose frontmatter declares two `suggestions:` entries (one with output_mode: card)."""

@pytest.fixture
def provider_that_raises():
    """SuggestionProvider(name='boom', lane='deterministic') whose suggest() raises RuntimeError."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Every operand in the §4 Validation Contract passes (pytest + vitest runners).
- [ ] `AIMessage().suggestions == []` by default; an agent constructed without `enable_suggestions` / `suggest_followups`
      and with no active skill declaring chips produces a byte-identical JSON body and stream envelope (no `suggestions`
      key, no `metadata["suggestions"]`) — asserted by a golden comparison in the passthrough test.
- [ ] With `suggest_followups=True`, the LLM lane calls `AbstractClient.invoke()` exactly once per answer and never
      `ask()`; an `invoke()` exception or timeout leaves the answer intact with deterministic chips only; cost lands in
      `metadata["suggestions"]["llm"]`.
- [ ] No chip ever carries an `output_mode` without a registered renderer (engine drops it; test covers an
      unregistered mode).
- [ ] A skill declaring `suggestions:` emits them only when it is the request's active skill; `parse_skill_file`
      of every existing skill under `packages/*/tests` fixtures still succeeds (field optional).
- [ ] `register_suggestion_provider()` works from outside the package (a test registers a provider class defined in the
      test module) — the FEAT-756 extension path.
- [ ] Streaming: without `suggestions_trailer`, suggestions appear only in the final envelope; text chunks are unchanged.
- [ ] Streaming with `suggestions_trailer: true`: the envelope carries no `suggestions` and is written before the chips
      are computed; a non-empty chip list arrives as a second `\n\x00` frame `{"suggestions", "turn_id"}`; the admin
      UI completes the bubble on the envelope and adds the chips when the trailer arrives (Module 8).
- [ ] `ui/schemas/AgentChatResponse.json` and the generated `.d.ts` are regenerated by the scripts (never hand-edited);
      `test_ts_codegen.py::test_schemas_in_sync_with_committed` passes.
- [ ] Admin UI: chips render under assistant bubbles; presentation chip click sends `output_mode`; explain chip click
      sends `turn_id` + `data` to the existing explain path; nothing renders while streaming.
- [ ] Teams / A2A untouched. Telegram with `suggestion_buttons: true` sends non-action chips as `sg:<token>` inline
      buttons; a press by the original user replays the prompt as a turn; expired token or another user → toast,
      no turn; with the flag off nothing changes (Module 9).
- [ ] Agent Studio: the five settings round-trip through the form, `BotModel.to_bot_config()` and
      `_build_database_bot()`; `ui/schemas/BotWritePayload.json` regenerated; migration file present (Module 10).
- [ ] `docs/agents/followup-suggestion-chips.md` written with the sections listed in §7.
- [ ] No breaking changes to existing public API; `ruff check` clean on touched files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
<!-- Exact import statements confirmed to work. Agents MUST use these verbatim. -->
```python
from parrot.models.responses import AIMessage, InvokeResult        # verified: packages/ai-parrot/src/parrot/models/responses.py:93, :1329
from parrot.models import AIMessage                                 # verified: packages/ai-parrot/src/parrot/models/__init__.py:8-9,124
from parrot.models.outputs import OutputMode, StructuredOutputConfig  # verified: packages/ai-parrot/src/parrot/models/outputs.py:23; __init__.py:15-16
from parrot.models.basic import CompletionUsage                     # verified: packages/ai-parrot/src/parrot/models/responses.py:8 (relative import there)
from parrot.outputs.formats import get_renderer, RENDERERS          # verified: packages/ai-parrot/src/parrot/outputs/formats/__init__.py:94, :48
from parrot.skills.models import SkillDefinition                    # verified: packages/ai-parrot/src/parrot/skills/models.py:60
from parrot.skills.parsers import parse_skill_file                  # verified: packages/ai-parrot/src/parrot/skills/parsers.py:69
from parrot.skills.tenancy import current_active_skill, set_active_skill  # verified: packages/ai-parrot/src/parrot/skills/tenancy.py:97, :102
from parrot.bots.abstract import AbstractBot                        # verified: packages/ai-parrot/src/parrot/bots/abstract.py:201
from parrot.bots.base import BaseBot                                # verified: packages/ai-parrot/src/parrot/bots/base.py:91
from parrot.clients.base import AbstractClient                      # verified: packages/ai-parrot/src/parrot/clients/base.py:1952 (invoke), :2054 (_resolve_invoke_model)
from parrot.utils.helpers import RequestContext                     # verified: packages/ai-parrot/src/parrot/bots/abstract.py:67 (import site)
from parrot.server.ui.chat_models import AgentChatResponse, AgentChatMetadata, AgentToolCall  # verified: packages/ai-parrot-server/src/parrot/server/ui/chat_models.py:67, :42, :26
from scripts.generate_ts_types import SCHEMAS_DIR, export_schemas   # verified: scripts/generate_ts_types.py:43, :117 (used by tests/test_ts_codegen.py:20)
```
```ts
import type { AgentMessage, AgentChatRequest } from "$lib/types/agent";                       // verified: ui/src/lib/types/agent.ts:25, :12
import type { AgentChatResponse } from "$lib/types/generated/AgentChatResponse";               // verified: ui/src/lib/types/agent.ts:19-23 (re-export)
import { render, screen, fireEvent } from "@testing-library/svelte";                           // verified: ui/src/lib/components/agents/ChatBubble.test.ts:7
```

### Existing Class Signatures
<!-- Exact signatures of classes/methods that tasks will extend or call.
     Include attribute types and method signatures with line numbers. -->
```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                                   # line 93
    output_mode: OutputMode = Field(default=OutputMode.DEFAULT, ...)          # line 201
    artifact_id: Optional[str] = Field(default=None, ...)                     # line 204
    a2ui_envelope: Optional[Dict[str, Any]] = Field(default=None, ...)        # line 212-219  ← new field goes after this block
    model_config = ConfigDict(arbitrary_types_allowed=True)                   # line 222
    metadata: Dict[str, Any] = Field(default_factory=dict, ...)               # line 193
    data: Optional[Any] = Field(default=None, ...)                            # line 100
    @property
    def to_text(self) -> str: ...                                             # line 246
    def render_as(self, mode: OutputMode, formatter: Any, **kwargs) -> "AIMessage": ...  # line 369 (model_dump exclude output/output_mode)
class InvokeResult(BaseModel):                                                # line 1329
    output: Any; output_type: Optional[type]; model: str; usage: CompletionUsage; raw_response: Optional[Any]; budget_report: Optional[Dict]

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    _lightweight_model: Optional[str] = None                                  # line 309
    async def invoke(self, prompt: str, *, output_type: Optional[type] = None,
                     structured_output: Optional[StructuredOutputConfig] = None, model: Optional[str] = None,
                     system_prompt: Optional[str] = None, max_tokens: Optional[int] = None, temperature: float = 0.0,
                     use_tools: bool = False, tools: Optional[list] = None) -> InvokeResult: ...   # line 1952-1964
    def _resolve_invoke_model(self, model: Optional[str] = None) -> str: ...  # line 2054 (explicit > self.model > _lightweight_model > _default_model)

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):  # line 201
    # __init__: self.operation_mode = kwargs.get("operation_mode", "adaptive")  # line 553
    #           self.formatter = OutputFormatter(); self.default_output_mode = output_mode  # lines 555-556
    def get_client(self) -> AbstractClient: ...                               # line 1218 (returns self._llm; mixin terminal)
    async def execute_llm_call(self, client: AbstractClient, method: str = "ask", **llm_kwargs: Any) -> Any: ...  # line 1231
    async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn, *, compaction=None) -> None: ...  # line 2579
    async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage: ...  # line 2758
    async def _resolve_output_mode(self, question: str, ctx: Optional[RequestContext]) -> Optional[OutputMode]: ...  # line 4168 (returns None; mixin hook)
    def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode: ...  # line 4191  ← new methods go before this
    async def invoke(self, question: str, session_id=None, user_id=None, use_conversation_history=True, memory=None,
                     ctx=None, response_model: Optional[Type[BaseModel]] = None, **kwargs) -> AIMessage: ...  # line 4476 (abstract decl)
    async def ask(self, question: str, ..., output_mode: OutputMode = OutputMode.DEFAULT, format_kwargs: dict = None,
                  use_tools: bool = True, trace_context: Optional[TraceContext] = None, **kwargs) -> AIMessage: ...  # line 4738
    async def ask_stream(self, ...) -> AsyncIterator[Union[str, AIMessage]]: ...  # line 4793

# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot(AbstractBot):                                                   # line 91
    async def invoke(self, question: str, ..., response_model=None, **kwargs) -> AIMessage: ...  # line 667 — enters get_client() and calls execute_llm_call(client, "ask", ...) (:748-771); NOT AbstractClient.invoke
    async def _on_post_ask(self, question: str, response: "AIMessage", user_id=None, session_id=None, **kwargs) -> None: ...  # line 892 (fire-and-forget hook; NOT used here — suggestions must be attached before return)
    async def ask(self, ...) -> AIMessage: ...                                # line 1063
    #   response = await self._run_output_pipeline(response, method="ask")   # line 1735  ← attach after this
    #   ... post-response hooks (:1741-1776) ... AfterInvokeEvent (:1787) ... return response  # line 1801
    async def ask_stream(self, ...) -> AsyncIterator[Union[str, AIMessage]]: ...  # line 1867
    #   ai_message = await self._run_output_pipeline(ai_message, method="ask_stream")  # line 2273
    #   linked-surface lift (:2276-2284) ... AfterInvokeEvent (:2291) ... yield ai_message  # line 2303  ← attach before this

# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):                                  # line 40
    async def followup(self, question: str, turn_id: str, data: Any, session_id=None, user_id=None,
                       use_conversation_history: bool = True, memory=None, ctx=None, structured_output=None,
                       output_mode: Any = None, format_kwargs: dict = None, return_structured: bool = True, **kwargs) -> AIMessage: ...  # line 1510

# packages/ai-parrot/src/parrot/skills/models.py
class SkillDefinition(BaseModel):                                             # line 60
    name: str; description: str; triggers: list[str]; source: SkillSource; priority: int = 90; version: str = "1.0"
    category: str | None; template_body: str; token_count: int; file_path: Path
    assets_dir: Path | None = Field(default=None, ...)                        # line 77
    global_only: bool = Field(default=False, ...)                             # line 81-84  ← new field goes after this
    MAX_TOKENS: ClassVar[int] = 1000                                          # line 86

# packages/ai-parrot/src/parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition: ...                 # line 69
#   global_only = _parse_bool(metadata.get("global_only", False))            # line 123  ← read `suggestions` after this
#   return SkillDefinition(..., global_only=global_only, ...)                 # line 136  ← pass suggestions=

# packages/ai-parrot/src/parrot/skills/tenancy.py
def current_active_skill() -> Optional[SkillDefinition]: ...                  # line 97
def set_active_skill(skill: Optional[SkillDefinition]) -> None: ...           # line 102
class SkillView:  def list_skills(self) -> List[SkillDefinition]: ...         # line 134, :254
# packages/ai-parrot/src/parrot/skills/mixin.py
class SkillRegistryMixin:  _active_skill (property, request-local) line 101-108; current_skill_view(tenant=None) line 165

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
RENDERERS: dict[OutputMode, type[Renderer]] = {}                              # line 48
_MODULE_MAP: dict = {...}                                                     # line 52 (lazy module map per mode)
def register_renderer(mode: OutputMode, system_prompt: str | None = None): ...  # line 76
def get_renderer(mode: OutputMode) -> type[Renderer]: ...                     # line 94 (raises ValueError "No renderer registered for mode")
# registered modes today (core + ai-parrot-visualizations): APPLICATION CARD ECHARTS HTML INFOGRAPHIC JINJA JSON MAP MARKDOWN
# SLACK STRUCTURED_CHART STRUCTURED_MAP STRUCTURED_TABLE TABLE TEMPLATE_REPORT TEXT WHATSAPP YAML

# packages/ai-parrot-server/src/parrot/server/ui/chat_models.py
class AgentToolCall(BaseModel): ...                                           # line 26
class AgentChatMetadata(BaseModel): ...                                       # line 42
class AgentChatResponse(BaseModel):                                           # line 67
    a2ui_envelope: dict[str, Any] | list[dict[str, Any]] | None = None       # line 88  ← new field after this
    audio_base64: str | None = None; audio_format: str | None = None          # lines 89-90

# packages/ai-parrot-server/src/parrot/handlers/agent.py  (class AgentTalk)
def _format_to_output_mode(self, format_str: str) -> OutputMode: ...          # line 506
async def post(self): ...                                                     # line 1539
#   output_mode = data.pop("output_mode", OutputMode.DEFAULT) + coercion      # lines 1669-1678
#   followup_turn_id = data.pop("turn_id", None); followup_data = data.pop("data", None)  # lines 1688-1689
#   if followup_turn_id and followup_data is not None: response = await bot.followup(...)  # lines 1869-1882
async def _handle_stream_response(self, bot: AbstractBot, query: str, session_id, user_id, search_type, return_sources,
    use_vector_context, use_conversation_history, output_mode: OutputMode, format_kwargs, memory, llm, agent_name="",
    client_message_id=None, avatar_bifurcate=False, tenant=None, **kwargs): ...  # line 2607
#   envelope = {...}; a2ui_envelope = getattr(ai_message, "a2ui_envelope", None) ...  # lines 2685-2729; separator b"\n\x00" :2730
#   A2UI JSON branch: self.json_response({... "a2ui_envelope": getattr(response, "a2ui_envelope", None), ...})  # lines 2866-2876
#   JSON path: obj_response = {...}; _a2ui_envelope passthrough                # lines 2927-2977
#   infographic JSON: obj_response ...; _a2ui_envelope passthrough             # lines 3262-3289
```
```ts
// packages/ai-parrot-server/ui/src/lib/types/agent.ts
export interface AgentChatRequest { ws_channel_id?: string; query: string; session_id?: string; [key: string]: any }  // line 12
export interface AgentMessage { id; role; content; timestamp; metadata?; data?; code?; output?; tool_calls?; output_mode?; …; a2ui_envelope?: A2UIEnvelope }  // line 25, a2ui_envelope line 51
// packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte
//   props: message: AgentMessage (line 151); onFollowup?: (turnId, data) => void (153); onExplain?: (turnId, data) => void (154); onFeedback? (155)
//   side actions block `{#if !isUser}` line 633; <SourcesPanel sources={message.sources} /> line 1757 (inside `{#if !isStreaming && message.sources …}` 1756-1758)
// packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte
//   async function handleSend(query: string, methodName?: string, outputMode?: string, llm?: string, kwargs?: Record<string,string>, existingUserMsgId?: string)  // line 756
//   payload: AgentChatRequest & { stream: true } = { query, session_id, message_id, turn_id?, data?, output_mode?, format_kwargs?, … }  // lines 915-928
//   finalMessage = { …, a2ui_envelope: agentResult.a2ui_envelope }  // line 1033 (stream); result.a2ui_envelope lines 1374, 1559 (non-stream / voice)
//   function handleFollowup(turnId: string, data: any) line 1677; async function handleExplain(turnId: string, data: any) line 1687 → chatWithAgent(agentId, {query, session_id, turn_id, data, …})
//   <ChatBubble … onFollowup={handleFollowup} onExplain={handleExplain} …/>  // lines 2432-2450
```

### Integration Points
<!-- How new code connects to existing code. Specify exact method calls. -->
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AIMessage.suggestions` | `AIMessage` field block | new `Field(default_factory=list)` after `a2ui_envelope` | `packages/ai-parrot/src/parrot/models/responses.py:212-219` |
| `AbstractBot._attach_suggestions` | `BaseBot.ask()` | awaited right after `_run_output_pipeline(..., "ask")` | `packages/ai-parrot/src/parrot/bots/base.py:1735` |
| `AbstractBot._attach_suggestions` | `BaseBot.ask_stream()` | awaited before `yield ai_message` | `packages/ai-parrot/src/parrot/bots/base.py:2303` |
| `LLMSuggestionProvider` | `AbstractBot.get_client()` → `AbstractClient.invoke()` | `async with client as entered: await entered.invoke(...)` (same enter pattern as NarrativeMixin) | `bots/abstract.py:1218`; `clients/base.py:1952`; `bots/mixins/narrative.py:199-201` |
| `SkillSuggestionProvider` | `current_active_skill()` | ContextVar read, request-local | `packages/ai-parrot/src/parrot/skills/tenancy.py:97` |
| `SkillDefinition.suggestions` | `parse_skill_file()` | optional frontmatter key, same style as `global_only` | `packages/ai-parrot/src/parrot/skills/parsers.py:123,136` |
| `SuggestionEngine.renderer_available` / `PresentationSuggestionProvider` | `get_renderer(mode)` | `ValueError` ⇒ not available | `packages/ai-parrot/src/parrot/outputs/formats/__init__.py:94-105` |
| `AgentTalk` passthrough | stream envelope / JSON / A2UI JSON / infographic bodies | conditional additive key, mirrors `a2ui_envelope` | `packages/ai-parrot-server/src/parrot/handlers/agent.py:2727-2729, 2874, 2975-2977, 3282-3284` |
| `AgentChatSuggestion` | `export_schemas()` registry | nested model → `$defs` of `AgentChatResponse.json` | `scripts/generate_ts_types.py:97,117` |
| `SuggestionChips.svelte` | `ChatBubble.svelte` | rendered after `<SourcesPanel>` | `ui/src/lib/components/agents/ChatBubble.svelte:1756-1758` |
| `handleSuggestion` | `handleSend(query, methodName, outputMode)` / `handleExplain(turnId, data)` | function calls | `ui/src/lib/components/agents/AgentChat.svelte:756, 1687` |
| "Explain this" chip | `BasicAgent.followup()` | existing request path (`turn_id` + `data` → `bot.followup`) | `handlers/agent.py:1688-1689, 1869-1882`; `bots/agent.py:1510` |

### Does NOT Exist (Anti-Hallucination)
<!-- Things that look plausible but DO NOT exist in the codebase.
     Prevents agents from inventing imports or attributes. -->
- ~~`AIMessage.suggestions` / `AIMessage.followups` / `AIMessage.chips`~~ — `grep -rni "suggest|followup|follow_up|chips" packages/ai-parrot/src/parrot/models/` returns nothing (2026-10-27, `b7e78ccec`).
- ~~`parrot.models.suggestions`~~, ~~`parrot.bots.suggestions`~~, ~~`SuggestionProvider`~~, ~~`SuggestionEngine`~~ — created by this feature.
- ~~`AgentChatResponse.suggestions`~~ — `chat_models.py:67-90` has no such field; the committed schema's property list is
  `a2ui_envelope, audio_base64, audio_format, code, data, input, metadata, output, output_mode, response, sources, tool_calls`.
- ~~`SkillDefinition.suggestions`~~ / ~~a `suggestions` frontmatter key~~ — `grep -rn suggestion packages/ai-parrot/src/parrot/skills/` is empty.
- ~~`BaseBot.invoke()` calling `AbstractClient.invoke()`~~ — `bots/base.py:748-771` enters `get_client()` and calls
  `execute_llm_call(client, "ask", ...)`; the lightweight model path is **only** `AbstractClient.invoke()`
  (`clients/base.py:1952`, `_resolve_invoke_model` `:2054`). Do not use `self.invoke(...)` for the LLM lane.
- ~~`OutputFormatter.supported_modes()` / `available_modes()` / `list_modes()`~~ — none under `parrot/outputs/`; capability
  checks go through `get_renderer()` / `RENDERERS` (`outputs/formats/__init__.py:48,94`).
- ~~`AbstractBot.followup()`~~ — `followup` exists only on `BasicAgent` (`bots/agent.py:1510`); providers must `getattr(bot, "followup", None)`.
- ~~`AbstractBot._lightweight_model`~~ — the attribute lives on `AbstractClient` (`clients/base.py:309`), not on bots.
- ~~Chip rendering in `ChatBubble.svelte`~~ — the only "suggest" hit is a comment about the Query Executor panel (`:197`);
  no `onSuggestion` prop, no `SuggestionChips` component; `AgentMessage` (`types/agent.ts:25-52`) has no `suggestions`.
- ~~`ParsedResponse.actions` / `buttons`~~ (Telegram/Teams) — `integrations/parser.py:86-110` has text/files/urls/charts/code/table only.
- ~~An A2A suggestion `Part`~~ — `a2a/server.py` emits `Part.from_text` (`:1529`) and A2UI data parts (`:588`, `:623`) only.
- ~~`_on_post_ask` as the attachment point~~ — it is fire-and-forget (`bots/base.py:1766-1776`); suggestions must be on the
  `AIMessage` before `return`/`yield`, hence the explicit `_attach_suggestions` call sites.

### Edit Sites (Blueprint Anchors)
<!-- One row per file the §3 modules will touch. `/sdd-task` turns each row into an
     Implementation Blueprint block, so the anchor is verified ONCE per feature here
     instead of once per task. Keep it to files the modules actually change — this
     table is re-read on every downstream turn, so rows must earn their place.

     Verified against: b7e78ccec (dev, 2026-10-27)

     Anchors go stale between spec time and task time. `/sdd-task` MUST re-run the
     `grep -c` for every row it uses; this table saves the search, not the check. -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/models/suggestions.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | `from .outputs import OutputMode` | `responses.py:9` | 1 |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | `    a2ui_envelope: Optional[Dict[str, Any]] = Field(` | `responses.py:212` | 1 |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | `from .responses import (` | `__init__.py:8` | 1 |
| `packages/ai-parrot/src/parrot/bots/suggestions/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/suggestions/protocol.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/suggestions/engine.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/suggestions/providers.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/suggestions/llm.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        self.default_output_mode = output_mode` | `abstract.py:556` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `    def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode:` | `abstract.py:4191` | 1 |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `                response = await self._run_output_pipeline(response, method="ask")` | `base.py:1735` | 1 |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `                    yield ai_message` | `base.py:2303` | 1 |
| `packages/ai-parrot/src/parrot/skills/models.py` | MODIFY | `    global_only: bool = Field(` | `models.py:81` | 1 |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | MODIFY | `    global_only = _parse_bool(metadata.get("global_only", False))` | `parsers.py:123` | 1 |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | MODIFY | `        global_only=global_only,` | `parsers.py:136` | 1 |
| `packages/ai-parrot-server/src/parrot/server/ui/chat_models.py` | MODIFY | `    a2ui_envelope: dict[str, Any] \| list[dict[str, Any]] \| None = None` | `chat_models.py:88` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `                a2ui_envelope = getattr(ai_message, "a2ui_envelope", None)` | `agent.py:2727` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `                    "a2ui_envelope": getattr(response, "a2ui_envelope", None),` | `agent.py:2874` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `            _a2ui_envelope = getattr(response, "a2ui_envelope", None)` (12-space indent; preceded by `# TASK-2563), mirroring the stream path (already ungated).`) | `agent.py:2975` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `        _a2ui_envelope = getattr(response, "a2ui_envelope", None)` (8-space indent; context: `# FEAT-527: dual-emit — additive key only, byte-identical body when no` / `# envelope was produced (G6).` / anchor / `if _a2ui_envelope is not None:` / `obj_response["a2ui_envelope"] = _a2ui_envelope`) | `agent.py:3282` | 2 (substring of the :2975 line — unique with the context above) |
| `packages/ai-parrot-server/ui/schemas/AgentChatResponse.json` | MODIFY (regenerated by `python scripts/generate_ts_types.py` — never hand-edited) | — | `test_ts_codegen.py:34` guards drift | — |
| `packages/ai-parrot-server/ui/src/lib/types/generated/AgentChatResponse.d.ts` | MODIFY (regenerated by `pnpm generate` — never hand-edited) | `// GENERATED by scripts/generate_ts_types.py — DO NOT EDIT` | `AgentChatResponse.d.ts:1` | 1 |
| `packages/ai-parrot-server/ui/src/lib/types/agent.ts` | MODIFY | `  a2ui_envelope?: A2UIEnvelope;` | `agent.ts:51` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/SuggestionChips.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/SuggestionChips.test.ts` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte` | MODIFY | `    onExplain?: (turnId: string, data: any) => void;` | `ChatBubble.svelte:154` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/ChatBubble.svelte` | MODIFY | `          <SourcesPanel sources={message.sources} />` | `ChatBubble.svelte:1757` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | `                  a2ui_envelope: agentResult.a2ui_envelope,` | `AgentChat.svelte:1033` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | `            a2ui_envelope: result.a2ui_envelope,` (12-space indent; preceded by `            sources: resolveAgentSources(result.sources),` and followed by `          };`) | `AgentChat.svelte:1374` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | `        a2ui_envelope: result.a2ui_envelope,` (8-space indent; context: `        htmlResponse: isInteractive ? null : isHtml ? responseText : null,` / `        sources: resolveAgentSources(result.sources),` / anchor / `        // Spoken answer (present only when TTS succeeded) — kept in-memory only.`) | `AgentChat.svelte:1559` | 2 (substring of the :1374 line — unique with the context above) |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | `  function handleFollowup(turnId: string, data: any) {` | `AgentChat.svelte:1677` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte` | MODIFY | `                      onExplain={handleExplain}` | `AgentChat.svelte:2442` | 1 |
| `packages/ai-parrot/tests/unit/models/test_suggestion_models.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/bots/test_suggestion_engine.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/bots/test_suggestion_providers.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/unit/test_skill_suggestions_frontmatter.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/handlers/test_suggestions_passthrough.py` | CREATE | — | — | — |
| `docs/agents/followup-suggestion-chips.md` | CREATE | — | — | — |

- A **CREATE** row declares only the path the module adds; it needs no anchor.
- **Occurrences > 1** means the one-line anchor is ambiguous. Quote 2–3 lines of
  surrounding context in the anchor cell so the blueprint block can attach uniquely.
- An anchor that cannot be verified is written `(unverified — check before use)`,
  never guessed.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- Cooperative hooks, not inheritance surgery: the bot surface is three small methods next to
  `_apply_default_output_mode` (same style as the `_resolve_output_mode` hook, `abstract.py:4168-4210`), and
  `_default_suggestion_providers()` is `super()`-extensible so mixins can add providers without touching the engine.
- LLM lane = `client = bot.get_client(); async with client as entered: await entered.invoke(...)` — the enter pattern
  of `NarrativeMixin` (`mixins/narrative.py:199-201`) combined with the lightweight `invoke()`; this keeps
  `ModelSwitchingMixin.get_client()` overrides effective. Guard with `asyncio.wait_for` exactly like
  `IntentRouterMixin` (`mixins/intent_router.py:289-296`).
- Envelope passthrough = the `a2ui_envelope` pattern (additive key, only when present): keeps the FEAT-527 G6
  "byte-identical body" guarantee for non-opted-in agents.
- Pydantic v2 models everywhere; `self.logger`; Google docstrings; type hints; ≤ 120 columns; Svelte 5 runes only.
- Never hand-edit `ui/schemas/*.json` or `src/lib/types/generated/*` — regenerate (M5 task is `parallel: false`).

### Presentation rules (M3; binding)
- Emit only when `has_tabular_data(response)` (non-empty `list[dict]` in `response.data`, or a DataFrame-like).
- Candidates in this order: `STRUCTURED_TABLE` → label `View as table`, prompt `Show the previous answer as a table`;
  `STRUCTURED_CHART` → `View as chart`, `Show the previous answer as a chart`; `CARD` → `View as KPI`,
  `Show the headline figure of the previous answer as a KPI card`. `kind=presentation`, `source=provider`.
- Skip the response's own `output_mode`; skip any mode where `get_renderer(mode)` raises (so without
  `ai-parrot-visualizations` installed no structured chip is offered); honour the per-agent override
  `presentation_modes` (constructor kwarg / class attribute, `Sequence[OutputMode]`) when present.

### Explain rule (M3; binding)
- One chip `Suggestion(label="Explain this", prompt="Explain this answer", kind=action, action="explain", source=provider)`
  when `has_tabular_data(response)` **and** `callable(getattr(bot, "followup", None))`. Clients that cannot run the
  explain flow must hide `kind=action` chips (documented in M7).

### Skill rule (M3; binding)
- **Rev 0.2 — turn skill, not active skill.** `current_active_skill()` is cleared by `create_system_prompt()`
  (`set_active_skill(None)`, `bots/abstract.py:3726`) *before* the LLM call, so it is always `None` when suggestions
  attach after the answer. A second request-local ContextVar records the turn's skill: `set_active_skill(skill)` with a
  non-`None` skill also sets it, `enter_active_skill_scope()` / `exit_active_skill_scope()` snapshot/reset it with the
  active skill, and `current_turn_skill()` (new, `skills/tenancy.py`) reads it. The provider reads
  `current_turn_skill()`; `current_active_skill()` semantics are unchanged.
- `SkillSuggestionProvider` emits `current_turn_skill().suggestions` mapped 1:1 (`source=skill`;
  `kind=presentation` iff `output_mode` set, else `followup`); an `output_mode` string that is not an `OutputMode`
  value is dropped with a warning (never raises); the engine's renderer check applies afterwards.
- Tenant shadowing, `global_only` and request-local activation are untouched — the provider only reads the already
  resolved active skill.

### LLM prompt (M4; binding template)
```
You suggest at most {max_items} short follow-up questions a user might ask next, grounded ONLY on the exchange below.
Rules: each label ≤ 40 characters, each prompt is a complete question the assistant can answer with the same data
or context, no duplicates of the original question, no presentation changes (those are offered separately), no
actions. Respond with the structured schema only.

Question: {question}
Answer (may be truncated): {answer_text}
```
`invoke(prompt, output_type=SuggestionBatch, max_tokens=256, temperature=0.3)`; `system_prompt=None` (client default).
The provider forces `source="llm"`, `kind="followup"`, `output_mode=None`, `action=None` on every returned chip
regardless of what the model produced.

### Engine metadata (M2; binding)
`response.metadata["suggestions"]` is written **only when the engine ran** (lanes beyond `skill`, or an active skill
with chips): `{"enabled_lanes": [...], "count": n, "providers": {name: {"status", "count", "elapsed_ms"}},
"llm": {...} | None}` — plain JSON types only (it is persisted by `ChatStorage` and rendered by clients).

### Docs (M7; sections)
1. What you get (screenshot-free description + JSON sample) · 2. Opt-in per agent (`enable_suggestions`,
`suggest_followups`, `suggestion_timeout_s`, `max_suggestions`, `presentation_modes`) · 3. Skill-declared chips
(frontmatter) · 4. Writing a provider (`SuggestionProvider`, `register_suggestion_provider`, FEAT-756 example sketch)
· 5. Wire contract (JSON + stream final envelope; omitted-when-empty) and the client click contract (explain action)
· 6. Channel behaviour (admin UI renders; Telegram buttons via `suggestion_buttons`; Teams/A2A ignore in v1) ·
7. Cost, latency and metadata · 8. Stream trailer (`suggestions_trailer`, frame format, UI handling) · 9. Agent
Studio settings + the `FEAT-752-ai-bots-suggestion-columns.sql` migration (apply before deploy).

### Known Risks / Gotchas
- **Stream tail latency**: the LLM lane runs before the final envelope, so an opted-in agent's stream ends up to
  `suggestion_timeout_s` later (text is already on screen). Mitigation: 4 s default, `max_tokens=256`, lightweight
  model; §8 Q1 covers emitting a separate trailing event later.
- **Shared `.venv` / worktrees**: tests must run with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
  (worktree rule); `test_ts_codegen.py` imports `scripts.generate_ts_types` from the worktree root.
- **Schema drift**: adding `AgentChatSuggestion` changes `AgentChatResponse.json`; forgetting regeneration fails
  `test_schemas_in_sync_with_committed`. Regenerate schema (Python) **then** `pnpm generate` in one task.
- **`extra="forbid"` on `Suggestion`**: an LLM that returns extra keys fails validation of `SuggestionBatch` — the
  provider treats that as a failed call (returns `[]`), which is the intended fail-closed behaviour.
- **ChatStorage persistence**: `AIMessage.metadata["suggestions"]` is persisted with the turn; `suggestions` itself is
  not (reload shows no chips). Accepted for v1 (Non-Goals).
- **`render_as()` round-trip**: it rebuilds `AIMessage(**model_dump(...))`; `Suggestion` dicts re-validate — covered by
  `test_aimessage_suggestions_default_empty_and_roundtrip`.
- **Memory**: no change to conversation memory; chips are not fed back into history.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none new (`pydantic` v2, `python-frontmatter`, `aiohttp`, `json-schema-to-typescript` already present) |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] **Q1 — Trailing stream event?** *Resolved (rev 0.3): yes, opt-in per request (`suggestions_trailer: true`) —
      Module 8; the v1 envelope stays the default.* v1 puts suggestions in the final envelope (blocks the stream tail by the LLM lane's
      latency). Should a later revision emit the final envelope first and a separate `suggestions` trailer so the UI
      can finish the bubble immediately? Needs a stream-format change on both server and `stream.ts`. — *Owner: Jesus Lara*
- [x] **Q2 — Lightweight model override.** *Resolved (rev 0.2): yes — `suggestion_model: Optional[str] = None` bot
      kwarg, forwarded as `invoke(model=...)` by `LLMSuggestionProvider(model=...)`; `None` keeps `_resolve_invoke_model`.* `AbstractClient.invoke()` uses `self.model` when the agent was built with an
      explicit model (`_resolve_invoke_model`, `clients/base.py:2054-2088`), so an agent on `gemini-2.5-pro` runs the
      suggestion call on that model. Should `LLMSuggestionProvider` accept a `model=` override kwarg
      (`suggestion_model`) to force the cheap tier? Proposed: yes, additive, default `None`. — *Owner: Jesus Lara*
- [x] **Q3 — Telegram quick replies.** *Resolved (rev 0.3): in scope as Module 9 (opt-in `suggestion_buttons`,
      `sg:<token>` + TTL store, private chats only).* Map chips to `build_inline_keyboard` (`telegram/callbacks.py:318`) with a
      turn-scoped store so the callback can recover the prompt? Separate feature (needs a `callbacks.py` prefix handler
      and TTL store). — *Owner: Jesus Lara*
- [x] **Q4 — Agent YAML config.** *Resolved (rev 0.2): no whitelist — `BotMetadata.get_instance()` merges
      `startup_config` with runtime kwargs and passes them to the factory verbatim (`registry/registry.py:108,155`).* Do `AGENTS_DIR` agent definitions forward arbitrary constructor kwargs so
      `suggest_followups: true` can be set declaratively, or does the loader whitelist keys? Verify at task time;
      if whitelisted, add the four kwargs to the whitelist in the M2 task. — *Owner: implementer of M2*
- [x] **Q5 — Opt-in default for the admin "Agent Studio".** *Resolved (rev 0.3): yes — Module 10 (form fields,
      both DB kwarg whitelists, `navigator.ai_bots` migration).* Should the studio expose the toggles in the agent form
      (`TabsCapabilities.svelte`)? Out of this spec unless answered yes before `/sdd-task`. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

Status: skipped (no accepted exploration document — spec authored from the NAV-10382 ticket review)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## Worktree Strategy

- **Isolation**: ONE feature worktree `feat-FEAT-752-followup-suggestion-chips` (from `origin/dev`); the `sdd-coder`
  engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edges = imports/uses, evidence in §3):
  - M2 → M1 (`Suggestion`, `AIMessage.suggestions`); M3 → M1, M2 (`SuggestionContext`, protocol); M4 → M1, M2;
    M5 → M1 (field name/shape only; `chat_models.py` stays import-free); M6 → M5 (generated `AgentChatSuggestion`
    type); M7 → all.
  - No edge between: M3 ‖ M4 (both only need M2); M5 ‖ M2/M3/M4 (server mirror + handler passthrough can start as
    soon as M1's field name is fixed — which it is, here). These run concurrently.
- **Shared files** (tasks serialized): `bots/abstract.py` and `bots/base.py` (M2 only); `skills/models.py` +
  `skills/parsers.py` (M3 only); `handlers/agent.py` (M5 only — all four passthrough sites in ONE task);
  `AgentChat.svelte` + `ChatBubble.svelte` + `types/agent.ts` (M6 — one task for the three files). Rev 0.3: M8 touches
  `base.py` (after M2), `handlers/agent.py` (after M5) and `AgentChat.svelte` (after M6); M9 owns the Telegram files;
  M10's schema regeneration runs after M5's (both rewrite `ui/schemas`).
- **Exclusive resources** (`parallel: false`): schema + TS regeneration (`ui/schemas/AgentChatResponse.json`,
  `src/lib/types/generated/`) — M5 owns it; M6 depends on it being merged first.
- **Cross-feature dependencies**: none to merge first. FEAT-756 (`metric-definition-registry`) consumes
  `register_suggestion_provider()` **after** this feature lands; FEAT-755 is independent.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.3 | 2026-10-27 | Jesus Lara | Q1/Q3/Q5 resolved and brought into scope: Module 8 (opt-in stream suggestions trailer), Module 9 (Telegram quick-reply buttons), Module 10 (Agent Studio settings + DB columns); G7 reworded, G8/G9 added, ACs and validation contract extended |
| 0.2 | 2026-10-27 | Jesus Lara | Approved for `/sdd-task`. Skill lane reads a new `current_turn_skill()` (active skill is consumed before the answer); Q2 resolved (`suggestion_model` kwarg); Q4 resolved (YAML kwargs forwarded) |
| 0.1 | 2026-10-27 | Jesus Lara | Initial draft from the NAV-10382 ticket review (server-side suggestions decision); anchors verified against `b7e78ccec` |

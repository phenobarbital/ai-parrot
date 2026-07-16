---
type: Wiki Overview
title: 'Brainstorm: UX for Custom Engine Copilot Agents (Semantic UI Model → Adaptive
  Cards)'
id: doc:sdd-proposals-ux-custom-engine-copilot-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot agents are already exposed to Microsoft 365 Copilot and Teams as
relates_to:
- concept: mod:parrot.forms.renderers
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.outputs.a2ui
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: UX for Custom Engine Copilot Agents (Semantic UI Model → Adaptive Cards)

**Date**: 2026-07-14
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AI-Parrot agents are already exposed to Microsoft 365 Copilot and Teams as
**custom engine agents** via the Microsoft 365 Agents SDK integration
(`parrot/integrations/msagentsdk/`, package `ai-parrot-integrations`). Today
that bridge is text-only: `ParrotM365Agent._handle_message()` calls
`parrot_agent.ask()` and sends `str(response.content)` back as a plain-text
activity. The only Adaptive Cards ever emitted are auth plumbing (OAuthCard
sign-in and the static-key capture card).

Domain agents (finance, workday, etc.) produce rich, structured results —
tables of records, KPI sets, entity details, statuses — that read poorly as
flat text in Copilot/Teams. Microsoft's UX guidance for custom engine agents
(https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/ux-custom-engine-agent)
is explicit: rich results should be rendered as **Adaptive Cards**, with
actions the user can click to continue the conversation.

We need a **Semantic UI Model**: a channel-neutral, structured description of
an agent's result (result type, fields, metrics, available actions) that the
Copilot Studio / M365 adapter renders as an Adaptive Card. Per the target
architecture, the same idea also feeds custom web/mobile clients — but that
branch is already served by the A2UI stack (FEAT-273); this feature covers the
Copilot/Teams branch only.

**Who is affected**: end users interacting with AI-Parrot agents inside M365
Copilot and Teams (better UX), and agent developers who want deterministic,
card-rendered outputs without hand-writing Bot Framework attachments.

## Constraints & Requirements

Decisions locked during discovery (Rounds 0–3 with the user):

- **Flow**: `type: feature`, `base_branch: dev`.
- **Placement**: the Semantic UI Model lives in **`ai-parrot-integrations`
  only** (inside/alongside `parrot/integrations/msagentsdk/`). It is NOT a
  core-parrot contract and does NOT reuse the A2UI envelope — a new,
  lightweight, card-oriented Pydantic contract.
- **Producer**: agents opt in via **explicit structured output** — the domain
  agent/tool returns the Semantic UI Model deterministically (via
  `ask(structured_output=...)` or by placing it in
  `AIMessage.structured_output`). No LLM inference of the model by the
  adapter in v1.
- **Renderer**: **template-per-result-type** — deterministic Python/JSON
  templates keyed by result type. No LLM-composed card JSON.
- **Actions**: **full round-trip** — card actions re-enter the domain agent.
  Each action carries a **natural-language prompt** (template, e.g. "Show
  details for order {id}") that flows back through the normal `ask()` path.
  No new dispatch API on the bot.
- **v1 result types**: table/list of records, metrics/KPI set, entity detail,
  status/error card.
- **Surfaces**: M365 Copilot **and** Teams — common-denominator Adaptive Card
  features only (schema ≤ 1.5; existing cards in the codebase use 1.4).
- **Failure mode**: **plain-text fallback** — on unknown result type,
  template error, or oversized card, degrade to a markdown/text rendering of
  the model's content. The user always gets the data; a turn never breaks.
- Async-first, aiohttp-based, Pydantic models, Google-style docstrings,
  `self.logger` — per project standards.
- Must keep the lazy-import discipline of `msagentsdk` (importable without
  `microsoft-agents-*` installed).

---

## Options Explored

### Option A: Lightweight Semantic UI Model + deterministic card templates (in `msagentsdk`)

Define a small Pydantic contract in a new module (e.g.
`parrot/integrations/msagentsdk/semantic.py`):
`SemanticUIResult(result_type, title, summary, fields, rows/columns, metrics,
actions)` with `result_type ∈ {table, metrics, detail, status}` and
`UIAction(title, prompt_template, params)`. A companion renderer module
(e.g. `cards.py`) holds one template function per result type that emits
common-denominator Adaptive Card 1.4/1.5 JSON (dicts), plus a text fallback
serializer.

`ParrotM365Agent._handle_message()` gains a seam: after `ask()`, if
`response.structured_output` is a `SemanticUIResult` (or `response.data`
carries one), render the card and send it as an attachment (reusing the
existing `application/vnd.microsoft.card.adaptive` attachment pattern from
`_emit_adaptive_card`); otherwise keep today's `_send_text()` path.

Actions render as `Action.Submit` with a Teams `messageBack` payload whose
`text` is the filled prompt template — the click arrives as a normal
`message` activity and flows through the existing `_handle_message()` with
zero new invoke handling. An `adaptiveCard/action` (Action.Execute) invoke
handler is added to `on_turn()` as a compatibility shim for surfaces that
send invokes instead, translating the invoke payload into the same
prompt-based `ask()` call.

✅ **Pros:**
- Deterministic, testable rendering — pure functions from model → card JSON.
- Zero new runtime dependencies (cards are plain dicts; SDK already present).
- Prompt-based actions reuse the entire existing message pipeline (identity,
  broker, suspend/resume) untouched.
- Lazy-import discipline preserved; model importable without the MS SDK.
- Small blast radius: one package, additive changes to `ParrotM365Agent`.

❌ **Cons:**
- Web/mobile clients can't consume this contract without depending on
  `ai-parrot-integrations` (accepted: that branch uses A2UI instead).
- Some duplication of intent with core's `StructuredTableConfig` /
  A2UI catalog components (accepted for decoupling).
- Template-per-type means new result types require code changes.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `microsoft-agents-hosting-aiohttp` | Activity/TurnContext, card attachments | already pinned `~=0.9.0` in `ai-parrot-integrations` |
| `microsoft-agents-authentication-msal` | auth (unchanged) | already pinned `~=0.9.0` |
| `pydantic` | Semantic UI Model | already a core dependency |
| — (no new deps) | card JSON as plain dicts | avoid stale `adaptivecards` PyPI packages |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` —
  `_emit_adaptive_card()` (attachment shape, `contentType`), `_send_text()`
  (plain-text fallback), `_handle_message()` (injection seam), `on_turn()`
  (invoke routing pattern).
- `packages/ai-parrot/src/parrot/models/responses.py` — `AIMessage.structured_output`
  / `.content` as the carrier from agent to adapter.
- `packages/ai-parrot/src/parrot/bots/abstract.py` — `ask(structured_output=...)`
  already supported; no bot API changes needed.
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py` —
  `TeamsCardRenderer` as a card-building style reference.

---

### Option B: Transcode the existing A2UI envelope (FEAT-273) to Adaptive Cards

Agents emit `OutputMode.A2UI` (already supported end-to-end in core:
`parrot/outputs/a2ui/` with a component catalog — datatable, kpicard, card,
chart, form — and `finalize_a2ui_response()`). The Copilot adapter walks the
A2UI envelope (`CreateSurface` / `UpdateComponents` / `UpdateDataModel`
messages) and maps each catalog component to Adaptive Card elements.

✅ **Pros:**
- One semantic contract for every surface — literally the diagram's promise.
- Agents already able to produce A2UI today get Copilot cards "for free".
- No new model to design or document.

❌ **Cons:**
- A2UI is a *wire protocol* (surfaces, component trees, JSON-pointer data
  bindings, incremental updates) — far richer than Adaptive Cards can
  express; the mapping is lossy and full of special cases.
- High effort: a faithful transcoder for even 4 component types (with
  bindings resolution) dwarfs the lightweight-model approach.
- Couples the integrations package to A2UI internals; changes in the
  catalog ripple into card rendering.
- Contradicts the discovery decision (user explicitly chose a new
  lightweight model over A2UI reuse).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (core parrot) `parrot.outputs.a2ui` | envelope + catalog | exists (FEAT-273) |
| `microsoft-agents-hosting-aiohttp` | delivery | existing |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` — `Component`,
  envelope messages.
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/` —
  datatable/kpicard/card definitions.

---

### Option C: LLM-generated Adaptive Card JSON (producer pattern)

Mirror the A2UI producer (`parrot/outputs/a2ui/producer.py::generate_envelope`,
which prompts an LLM and repairs invalid JSON): after `ask()`, a second LLM
pass composes an Adaptive Card from the agent's answer, validated against the
Adaptive Card JSON schema with a repair loop.

✅ **Pros:**
- Works with *any* agent output, zero opt-in — no structured output needed.
- Flexible layouts; new result shapes need no code.
- Proven in-repo pattern (A2UI producer + repair prompt).

❌ **Cons:**
- Non-deterministic: same data can render differently turn to turn.
- Extra LLM latency + token cost on every rich answer.
- Invalid/oversized cards still possible after repair; harder to test.
- Contradicts the discovery decision (user chose deterministic templates and
  explicit structured output).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jsonschema` | validate generated cards against AC schema | new dev/runtime dep |
| (core parrot) LLM clients | card composition pass | existing |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/outputs/a2ui/producer.py` — repair-loop
  pattern (`_extract_envelope`, `_repair_prompt`, `generate_envelope`).

---

### Option D (unconventional): Data-binding card templates (Adaptive Card Template Language)

Instead of Python template functions, ship **declarative card templates** as
JSON files using the official Adaptive Cards template language (`${...}`
binding expressions, `$data`, `$when`). The Semantic UI Model is serialized
to a plain dict and bound into the template at render time by a small
expression evaluator (subset: property paths, `$data` iteration, `$when`
conditionals — no full AEL). Designers can edit card layouts without touching
Python; templates are versioned assets next to the code.

✅ **Pros:**
- Layouts editable/reviewable as JSON artifacts; can be previewed in the
  Adaptive Cards Designer as-is.
- Clean separation of data (model) and presentation (template) — the same
  philosophy Microsoft recommends.
- New layout variants (e.g. compact vs. wide table) without code changes.

❌ **Cons:**
- No maintained Python implementation of the AC template language — we'd
  write and own a subset evaluator (correctness risk, edge cases: `$when`,
  `$index`, escaping).
- More moving parts than Option A for the same 4 result types.
- Debugging binding failures at runtime is harder than debugging Python.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — (custom subset evaluator) | `${}` binding resolution | `adaptivecards-templating` is JS/.NET only; no viable PyPI equivalent (verified: not a current dependency; stale unofficial ports exist) |

🔗 **Existing Code to Reuse:**
- Same seams as Option A (`_handle_message`, attachment pattern).

---

## Recommendation

**Option A** — lightweight Semantic UI Model + deterministic
template-per-result-type renderer inside `msagentsdk`, with prompt-based
action round-trip.

Reasoning:
- It matches every discovery decision: integrations-only placement, explicit
  structured output, deterministic templates, full round-trip via
  natural-language prompts, plain-text fallback.
- It has the smallest dependency and blast-radius footprint: no new packages,
  additive changes to one class (`ParrotM365Agent`) plus two new modules.
- The `messageBack`-style action design means the round-trip reuses the
  existing message pipeline (identity mapping, credential broker,
  suspend/resume) with no new state machinery — the cheapest possible path to
  "truly interactive" cards.
- What we trade off: contract reuse across surfaces (Option B) and
  designer-editable layouts (Option D). Both are acceptable — the web branch
  already has A2UI, and with only four v1 result types, Python templates are
  cheaper to own than a template-language evaluator. If layout variety grows,
  Option D can be layered on later without changing the semantic model.

---

## Feature Description

### User-Facing Behavior

- A user asks an AI-Parrot custom engine agent a question in M365 Copilot or
  Teams. When the agent's answer is structured (a `SemanticUIResult`), the
  reply renders as an Adaptive Card instead of flat text:
  - **table**: a column-header row + data rows (capped, with a "showing N of
    M" note when truncated);
  - **metrics**: a set of labeled KPI values with optional delta/trend text;
  - **detail**: a single entity as a FactSet of labeled fields;
  - **status**: a success/warning/error banner with message and optional
    details.
- Cards carry a title/summary and up to a handful of **action buttons**.
  Clicking one (e.g. "Show details for order 123") sends its prompt back to
  the agent as if the user had typed it; the agent answers normally — possibly
  with another card. `Action.OpenUrl` links are also supported.
- Plain-text agents and unstructured answers behave exactly as today
  (plain-text activity). If a card cannot be rendered, the user still receives
  the result as readable text — never a broken or empty turn.

### Internal Behavior

1. **Model** (`semantic.py`, new): Pydantic models — `SemanticUIResult`
   (discriminated by `result_type`), payload shapes for the four types, and
   `UIAction` (title, prompt template, optional params, optional URL).
   Importable with no `microsoft_agents.*` dependency.
2. **Producer**: a domain agent opts in by returning the model as structured
   output (e.g. `ask(structured_output=SemanticUIResult)` from the caller, or
   the agent/tool sets it on the response). The adapter detects it on
   `AIMessage.structured_output` (fallback: `AIMessage.data`).
3. **Renderer** (`cards.py`, new): pure functions `render(result) -> dict`
   keyed by `result_type`, emitting Adaptive Card 1.4/1.5 JSON limited to
   common-denominator elements (TextBlock, ColumnSet, FactSet, Container,
   Action.Submit, Action.OpenUrl). A sibling `render_text(result) -> str`
   produces the markdown/plain fallback. Enforces card-size and row caps.
4. **Bridge** (`agent.py`, modified): `_handle_message()` checks the response
   for a `SemanticUIResult`; renders and sends the card attachment (same
   attachment shape as `_emit_adaptive_card`, including the plain-`text`
   fallback field on the Activity); on any rendering exception, logs and
   falls back to `_send_text(render_text(result))`, else to
   `str(response.content)`.
5. **Action round-trip**: actions are emitted as `Action.Submit` with a
   `msteams: {type: "messageBack", text: <filled prompt>}` payload — Teams
   and Copilot deliver the click as a `message` activity that re-enters
   `_handle_message()` unchanged. Additionally, `on_turn()` learns to route
   the `adaptiveCard/action` invoke name: it acknowledges the invoke and
   feeds the payload's prompt through the same message path (shim for
   surfaces that send Action.Execute-style invokes).
6. **Config**: an opt-out/knobs surface on `MSAgentSDKConfig` (e.g.
   `enable_semantic_cards: bool = True`, `max_table_rows`), so operators can
   disable cards per bot without code changes.

### Edge Cases & Error Handling

- **Unknown `result_type`** → Pydantic validation fails at the producer, or
  (if a forward-compat type arrives) the renderer raises → text fallback.
- **Oversized card** (Teams ~28 KB attachment limit) → row cap + serialized
  size check before send; truncate rows with a "showing N of M" note; if
  still oversized → text fallback.
- **Template error / SDK send failure** → log with `exc_info`, fall back to
  text; never re-raise into the turn.
- **Action click with stale/garbled payload** → treated as a plain message;
  the agent answers as best it can (no server-side action state to corrupt).
- **Empty tables / zero metrics** → render a status-style "no results" card
  rather than an empty ColumnSet.
- **Non-Teams channels** via the same bridge (e.g. Bot Framework Emulator)
  → the Activity's `text` fallback field carries the plain rendering.
- **Credential flows unchanged**: `CredentialRequired` handling (OAuthCard /
  static-key card, suspend/resume) takes precedence and is untouched.

---

## Capabilities

### New Capabilities
- `copilot-semantic-ui-model`: card-oriented Pydantic contract
  (`SemanticUIResult`, `UIAction`, four result types) in
  `parrot/integrations/msagentsdk/`.
- `adaptive-card-renderer`: deterministic template-per-result-type rendering
  to common-denominator Adaptive Card JSON + text fallback.
- `card-action-roundtrip`: messageBack-based action prompts +
  `adaptiveCard/action` invoke shim in `ParrotM365Agent.on_turn()`.

### Modified Capabilities
- `msagentsdk` integration (`ParrotM365Agent`, `MSAgentSDKConfig`) — additive
  changes only; existing text/auth behavior preserved.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/integrations/msagentsdk/agent.py` (`ParrotM365Agent`) | modifies (additive) | card seam in `_handle_message`; `adaptiveCard/action` route in `on_turn` |
| `parrot/integrations/msagentsdk/models.py` (`MSAgentSDKConfig`) | extends | `enable_semantic_cards`, row/size knobs |
| `parrot/integrations/msagentsdk/semantic.py` | new | Semantic UI Model (Pydantic) |
| `parrot/integrations/msagentsdk/cards.py` | new | card templates + text fallback |
| `parrot/integrations/msagentsdk/__init__.py` | extends | add lazy exports for new public names |
| `packages/ai-parrot-integrations/tests/` | extends | unit tests: model validation, per-type rendering, fallback, action round-trip |
| core `parrot` package | none | no core changes; `AIMessage.structured_output` and `ask(structured_output=...)` already exist |
| Dependencies / deployment | none | no new packages; SDK pins unchanged |

No breaking changes: agents that never return a `SemanticUIResult` see
identical behavior.

---

## Code Context

### User-Provided Code

```text
# Source: user-provided (architecture diagram from /sdd-brainstorm invocation)
AI-Parrot domain agent → returns Semantic UI Model (result type, fields,
metrics, available actions) → JSON schema →
  (a) Copilot Studio adapter → JSON → Adaptive Card → M365 Copilot / Teams
  (b) Custom web/mobile client → JSON/A2UI → UI renderer
Reference: https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/ux-custom-engine-agent
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py:21
class ParrotM365Agent:
    def __init__(self, parrot_agent: AbstractBot, welcome_message: Optional[str] = None,
                 resolver=None, audit_ledger=None, broker=None, identity_mapper=None,
                 suspended_store=None, conv_ref_store=None, adapter=None,
                 agent_app_id: Optional[str] = None) -> None: ...   # line 46
    async def on_turn(self, context) -> None: ...                   # line 117
        # routes: message → _handle_message (137); invoke by name:
        # "signin/verifyState" (142) / "signin/tokenExchange" (144); else DEBUG-ignored
    async def _handle_message(self, context) -> None: ...           # line 214
        # calls: response = await self.parrot_agent.ask(question=..., session_id=...,
        #        user_id=..., ctx=..., permission_context=...)      # lines 291-297
        # then:  await self._send_text(context, str(response.content))  # line 298
    async def _emit_adaptive_card(self, context, capture_url: str, provider: str) -> None:  # line 680
        # builds {"type": "AdaptiveCard", "version": "1.4", ...}        # lines 708-728
        # attachment contentType "application/vnd.microsoft.card.adaptive"  # lines 729-732
        # Activity(type=message, text=<fallback>, attachments=[...])       # lines 733-737
    @staticmethod
    async def _send_text(context, text: str) -> None: ...           # line 771
        # sends Activity(text_format=TextFormatTypes.plain)

# From packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py:63
class MSAgentSDKWrapper:
    def __init__(self, agent: AbstractBot, config: MSAgentSDKConfig,
                 app: web.Application, broker=None, identity_mapper=None,
                 agent_class: Optional[type] = None) -> None: ...   # line 88
        # agent_class lets callers substitute a ParrotM365Agent subclass (line 109-113)

# From packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py:11
class MSAgentSDKConfig:  # dataclass; fields include anonymous_auth, api_key,
    ...                  # api_key_header, endpoint (verified via wrapper usage)

# From packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
    output: Any                                   # line 79
    response: Optional[str]                       # line 82
    data: Optional[Any]                           # line 86
    structured_output: Optional[Any]              # line 194
    @property
    def content(self) -> Any: ...                 # line 235 (alias for text rendering)

# From packages/ai-parrot/src/parrot/bots/abstract.py:3764
@abstractmethod
async def ask(self, question: str, session_id: Optional[str] = None,
              user_id: Optional[str] = None, ...,
              ctx: Optional[RequestContext] = None,
              structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,  # line 3778
              output_mode: OutputMode = OutputMode.DEFAULT,          # line 3779
              **kwargs) -> AIMessage: ...

# From packages/ai-parrot/src/parrot/models/outputs.py:36
class OutputMode(str, Enum):
    MSTEAMS = "msteams"    # exists (unused by msagentsdk bridge today)
    A2UI = "a2ui"          # line 70 (FEAT-273)

# From packages/ai-parrot/src/parrot/models/outputs.py:73
class StructuredOutputConfig:  # dataclass used by ask(structured_output=...)

# From packages/ai-parrot/src/parrot/forms/renderers/adaptive_card.py:69
class AdaptiveCardRenderer(AbstractFormRenderer):
    # FORM-dialog renderer (render/render_section/render_summary/render_error)
    # — style reference only; NOT a generic result-card renderer.

# From packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py:51
class TeamsCardRenderer:  # HITL card building — style reference

# A2UI stack (FEAT-273) — the web-client branch of the diagram (NOT reused here):
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py:123  class Component
# packages/ai-parrot/src/parrot/outputs/a2ui/emission.py:18 def finalize_a2ui_response
# packages/ai-parrot/src/parrot/outputs/a2ui/producer.py:110 async def generate_envelope
# catalog components: card, chart, datatable, form, infographic, kpicard
```

#### Verified Imports
```python
# Confirmed working (lazy re-export via PEP 562 __getattr__,
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py:18-23):
from parrot.integrations.msagentsdk import MSAgentSDKConfig, ParrotM365Agent, MSAgentSDKWrapper
# New public names (SemanticUIResult, renderers) must be added to _LAZY_EXPORTS there.

…(truncated)…

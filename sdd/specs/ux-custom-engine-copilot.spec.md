---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: UX for Custom Engine Copilot Agents (Semantic UI Model → Adaptive Cards)

**Feature ID**: FEAT-303
**Date**: 2026-07-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-integrations 0.26.0 (next minor)
**Brainstorm**: `sdd/proposals/ux-custom-engine-copilot.brainstorm.md` (Option A)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot agents are exposed to Microsoft 365 Copilot and Teams as **custom
engine agents** via the Microsoft 365 Agents SDK integration
(`parrot/integrations/msagentsdk/`, package `ai-parrot-integrations`). Today
that bridge is text-only: `ParrotM365Agent._handle_message()` calls
`parrot_agent.ask()` and sends `str(response.content)` back as a plain-text
activity. The only Adaptive Cards ever emitted are auth plumbing (OAuthCard
sign-in, static-key capture card).

Domain agents produce rich, structured results — tables of records, KPI sets,
entity details, statuses — that read poorly as flat text. Microsoft's UX
guidance for custom engine agents
(https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/ux-custom-engine-agent)
is explicit: rich results should render as **Adaptive Cards**, with actions
the user can click to continue the conversation.

This feature introduces a **Semantic UI Model** — a structured, card-oriented
description of an agent's result (result type, fields, metrics, available
actions) — and a deterministic renderer that turns it into Adaptive Cards for
the Copilot/Teams surface. The web/mobile branch of the target architecture is
already served by the A2UI stack (FEAT-273) and is out of scope here.

### Goals

- Agents can return structured results that render as Adaptive Cards in M365
  Copilot and Teams, covering four result types: **table**, **metrics/KPI**,
  **entity detail**, **status/error**.
- Rendering is **deterministic**: template-per-result-type, pure functions
  from model → card JSON. No LLM pass in the render path.
- Cards are **interactive**: actions carry natural-language prompt templates
  that re-enter the agent through the normal `ask()` pipeline (full
  round-trip), plus `Action.OpenUrl` links.
- Cards target the **common denominator** of M365 Copilot and Teams
  (Adaptive Card schema 1.4; only TextBlock, ColumnSet, FactSet, Container,
  Action.Submit, Action.OpenUrl).
- **Never break a turn**: any rendering failure degrades to a readable
  plain-text rendering of the same data.
- Zero new runtime dependencies; `msagentsdk`'s lazy-import discipline
  preserved (importable without `microsoft-agents-*` installed).
- Existing behavior unchanged for agents that never return the model
  (plain text, auth cards, suspend/resume untouched).

### Non-Goals (explicitly out of scope)

- Charts as a v1 result type — *resolved in brainstorm*: excluded; charts
  remain available via existing image/ECharts paths and may join in v2.
- Reusing the A2UI envelope as the semantic contract — *rejected in
  brainstorm (Option B)*: A2UI stays the web-client protocol; see
  `sdd/proposals/ux-custom-engine-copilot.brainstorm.md`.
- LLM-generated card JSON (*rejected, Option C*) and a declarative
  card-template-language evaluator (*rejected, Option D*).
- Core `parrot` package changes — `AIMessage.structured_output` and
  `ask(structured_output=...)` already exist and suffice.
- Changes to the legacy `msteams` integration (Bot Framework) — this feature
  targets the `msagentsdk` bridge only.
- Named tool/action dispatch bypassing the LLM — *resolved in brainstorm*:
  actions are natural-language prompts through `ask()`.

---

## 2. Architectural Design

### Overview

A new module pair inside `parrot/integrations/msagentsdk/`:

1. **`semantic.py`** — the Semantic UI Model: a Pydantic contract
   (`SemanticUIResult`, discriminated by `result_type`, with payload shapes
   for the four result types, and `UIAction` for actions). Importable with no
   `microsoft_agents.*` dependency, so any agent or tool can construct it.
2. **`cards.py`** — the deterministic renderer: one template function per
   result type producing Adaptive Card **1.4** JSON as plain dicts, a
   `render_text()` plain/markdown fallback serializer, size enforcement
   (row cap + serialized-size guard), and the `messageBack` action payload
   builder.

The bridge (`ParrotM365Agent`) gains a seam: after `ask()`, if the response
carries a `SemanticUIResult` (checked on `AIMessage.structured_output` first,
then `AIMessage.data`), it renders and sends the card as an
`application/vnd.microsoft.card.adaptive` attachment with the plain-text
rendering in the Activity's `text` field as channel fallback. Otherwise the
existing `_send_text()` path runs unchanged. Any exception in the card path
logs and falls back to text — the turn always completes.

**Producer contract**: agents opt in via explicit structured output — either
the caller passes `structured_output=SemanticUIResult` to `ask()`, or the
agent/tool sets a `SemanticUIResult` instance on the response. The adapter
never infers the model from free text (per brainstorm decision).

**Action round-trip**: each card action renders as `Action.Submit` with an
`msteams: {"type": "messageBack", "text": <filled prompt>}` payload. Teams
and Copilot deliver the click as a normal `message` activity, which re-enters
`_handle_message()` — reusing identity mapping, credential broker, and
suspend/resume with no new state machinery. As a compatibility shim for
surfaces that send Universal-Action invokes instead, `on_turn()` learns to
route the `adaptiveCard/action` invoke name: acknowledge the invoke (200) and
feed the payload's prompt through the same message-handling path.

**Configuration**: `MSAgentSDKConfig` gains
`enable_semantic_cards: bool = True`, `max_table_rows: int = 15`, and
`max_card_bytes: int = 25_000` so operators can tune or disable cards per bot
without code changes (defaults resolved at spec time; 25 KB sits under Teams'
~28 KB attachment limit).

### Component Diagram

```
Domain agent / tool
      │  returns SemanticUIResult (explicit structured output)
      ▼
AIMessage.structured_output  (fallback: AIMessage.data)
      │
      ▼
ParrotM365Agent._handle_message()          parrot/integrations/msagentsdk/agent.py
      │
      ├─ no SemanticUIResult ──────────────► _send_text(str(response.content))   [unchanged]
      │
      └─ SemanticUIResult
              │
              ▼
        cards.render_card(result, config)   parrot/integrations/msagentsdk/cards.py
              │        │
              │        └─ error / oversized ──► cards.render_text(result) ─► _send_text()
              ▼
        Activity(text=render_text(result),
                 attachments=[adaptive card 1.4])
              │
              ▼
        M365 Copilot / Teams renders card
              │  user clicks action
              ├─ Action.Submit (messageBack) ──► message activity ──► _handle_message()  [normal path]
              └─ adaptiveCard/action invoke ──► on_turn() shim ──► same prompt path
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ParrotM365Agent` (`msagentsdk/agent.py`) | modifies (additive) | card seam in `_handle_message()`; `adaptiveCard/action` route in `on_turn()` |
| `MSAgentSDKConfig` (`msagentsdk/models.py`) | extends | `enable_semantic_cards`, `max_table_rows`, `max_card_bytes` |
| `msagentsdk/__init__.py` lazy exports | extends | add `SemanticUIResult`, `UIAction`, renderer entry points to `_LAZY_EXPORTS` |
| `AIMessage` (core `parrot/models/responses.py`) | uses (read-only) | `structured_output` / `data` as the carrier; no core changes |
| `AbstractBot.ask()` (core `parrot/bots/abstract.py`) | uses (read-only) | `structured_output=` param already exists |
| `MSAgentSDKWrapper` (`msagentsdk/wrapper.py`) | none | untouched; `agent_class` override still works |
| Auth flows (OAuthCard, static-key card, suspend/resume) | none | `CredentialRequired` handling takes precedence, untouched |
| `packages/ai-parrot-integrations/tests/` | extends | new unit + integration tests |

### Data Models

```python
# parrot/integrations/msagentsdk/semantic.py — design sketch (names/shapes normative,
# exact field metadata to be finalized in implementation)

class UIAction(BaseModel):
    """A card action; prompt_template re-enters ask() as natural language."""
    title: str
    prompt_template: str | None = None      # e.g. "Show details for order {id}"
    params: dict[str, Any] = {}             # filled into prompt_template
    url: str | None = None                  # renders Action.OpenUrl instead
    # exactly one of prompt_template / url must be set (model validator)

class UIField(BaseModel):
    label: str
    value: str

class UIMetric(BaseModel):
    label: str
    value: str
    delta: str | None = None                # optional trend/delta text

class TablePayload(BaseModel):
    result_type: Literal["table"]
    columns: list[str]
    rows: list[list[str]]
    total_rows: int | None = None           # for "showing N of M" note

class MetricsPayload(BaseModel):
    result_type: Literal["metrics"]
    metrics: list[UIMetric]

class DetailPayload(BaseModel):
    result_type: Literal["detail"]
    fields: list[UIField]

class StatusPayload(BaseModel):
    result_type: Literal["status"]
    level: Literal["success", "warning", "error", "info"]
    message: str
    details: str | None = None

class SemanticUIResult(BaseModel):
    """Card-oriented semantic description of an agent result."""
    title: str
    summary: str | None = None
    payload: TablePayload | MetricsPayload | DetailPayload | StatusPayload \
        = Field(discriminator="result_type")
    actions: list[UIAction] = []            # rendered as card action buttons
```

### New Public Interfaces

```python
# parrot/integrations/msagentsdk/cards.py — design sketch

def render_card(result: SemanticUIResult, *, max_table_rows: int = 15,
                max_card_bytes: int = 25_000) -> dict:
    """SemanticUIResult → Adaptive Card 1.4 JSON dict.

    Raises CardRenderError when the result cannot be rendered within limits
    (caller falls back to render_text)."""

def render_text(result: SemanticUIResult) -> str:
    """SemanticUIResult → plain/markdown text fallback. Never raises."""

def build_card_attachment(card: dict) -> dict:
    """Wrap card JSON in the Bot Framework attachment envelope
    (contentType 'application/vnd.microsoft.card.adaptive')."""

class CardRenderError(Exception): ...

# Lazy re-exports added to parrot/integrations/msagentsdk/__init__.py:
#   SemanticUIResult, UIAction, render_card, render_text
```

---

## 3. Module Breakdown

> Modules map to Task Artifacts in Phase 2.

### Module 1: Semantic UI Model (`copilot-semantic-ui-model`)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/semantic.py`
- **Responsibility**: Pydantic contract — `SemanticUIResult`, four payload
  types (discriminated union on `result_type`), `UIAction` (with
  prompt-or-url validator), `UIField`, `UIMetric`. No `microsoft_agents.*`
  imports. Google-style docstrings (they document the contract for agent
  developers).
- **Depends on**: nothing new (pydantic only).

### Module 2: Adaptive Card renderer (`adaptive-card-renderer`)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/cards.py`
- **Responsibility**: `render_card()` (template per result type, AC 1.4,
  common-denominator elements only), `render_text()` fallback,
  `build_card_attachment()`, row-cap/size enforcement with "showing N of M"
  truncation note, empty-payload → "no results" status card,
  `messageBack` Action.Submit payload construction from `UIAction`,
  `CardRenderError`.
- **Depends on**: Module 1.

### Module 3: Bridge wiring + config (`msagentsdk` modification)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`,
  `models.py`, `__init__.py`
- **Responsibility**: detect `SemanticUIResult` on
  `response.structured_output` (then `response.data`) in
  `_handle_message()`; send card Activity with text fallback; catch-all
  fallback to `_send_text(render_text(result))`; `MSAgentSDKConfig` knobs
  (`enable_semantic_cards`, `max_table_rows`, `max_card_bytes`); lazy
  exports.
- **Depends on**: Modules 1–2.

### Module 4: Action round-trip invoke shim (`card-action-roundtrip`)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py`
- **Responsibility**: route `adaptiveCard/action` invoke in `on_turn()`
  (following the existing `signin/*` routing pattern at agent.py:140-147):
  acknowledge via `_send_invoke_response()`, extract the prompt text from the
  invoke payload, feed it through the message-handling path. messageBack
  clicks need no code (arrive as `message` activities).
- **Depends on**: Module 3.

### Module 5: Tests + docs
- **Path**: `packages/ai-parrot-integrations/tests/integrations/msagentsdk/`,
  `docs/`
- **Responsibility**: unit tests (model validation, per-type rendering,
  truncation, fallback, action payloads, invoke shim), integration test of
  `_handle_message()` card path with a stub TurnContext, import-isolation
  check (pattern: `tests/test_import_isolation.py`), short usage doc for
  agent developers.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_semantic_model_valid_payloads` | Module 1 | Each of the four payload types validates; discriminator routes correctly |
| `test_semantic_model_rejects_unknown_type` | Module 1 | Unknown `result_type` fails validation |
| `test_uiaction_prompt_xor_url` | Module 1 | `UIAction` requires exactly one of `prompt_template` / `url` |
| `test_render_table_card` | Module 2 | Table renders header + rows; valid AC 1.4; only allowed elements |
| `test_render_metrics_card` | Module 2 | Metrics render as FactSet/columns with delta text |
| `test_render_detail_card` | Module 2 | Detail renders FactSet of labeled fields |
| `test_render_status_card` | Module 2 | Each level renders with message + optional details |
| `test_table_truncation` | Module 2 | Rows capped at `max_table_rows` with "showing N of M" note |
| `test_card_size_guard` | Module 2 | Oversized card raises `CardRenderError` |
| `test_empty_table_renders_no_results` | Module 2 | Empty rows → "no results" status-style card, not empty ColumnSet |
| `test_render_text_fallback` | Module 2 | `render_text()` produces readable text for all four types; never raises |
| `test_action_messageback_payload` | Module 2 | `UIAction` with prompt → Action.Submit with `msteams.messageBack` and filled prompt; url → Action.OpenUrl |
| `test_handle_message_sends_card` | Module 3 | `structured_output=SemanticUIResult` → card attachment + text fallback on Activity |
| `test_handle_message_data_fallback_carrier` | Module 3 | Model on `response.data` also detected |
| `test_handle_message_plain_text_unchanged` | Module 3 | No model → existing `_send_text` behavior byte-identical |
| `test_render_error_falls_back_to_text` | Module 3 | Renderer raising → `_send_text(render_text(result))`; no exception escapes |
| `test_semantic_cards_disabled` | Module 3 | `enable_semantic_cards=False` → plain text even with model present |
| `test_on_turn_routes_adaptive_card_action` | Module 4 | `adaptiveCard/action` invoke → 200 ack + prompt re-enters ask() |
| `test_import_isolation_semantic` | Module 5 | `semantic.py`/`cards.py` importable without `microsoft_agents.*` installed |

### Integration Tests
| Test | Description |
|---|---|
| `test_card_turn_end_to_end` | Stub TurnContext + stub bot returning `SemanticUIResult` → `on_turn()` emits one message Activity with adaptive attachment; clicking (simulated messageBack activity) triggers a second `ask()` with the filled prompt |
| `test_existing_msagentsdk_suite_green` | Full existing test suite for the package passes unmodified (auth cards, proactive, HITL untouched) |

### Test Data / Fixtures
```python
# Key fixtures needed (tests/integrations/msagentsdk/conftest.py)
@pytest.fixture
def table_result() -> SemanticUIResult: ...      # 20 rows to exercise truncation
@pytest.fixture
def stub_turn_context(): ...                     # records send_activity() calls
@pytest.fixture
def stub_bot(): ...                              # AbstractBot stand-in; ask() returns
                                                 # a canned AIMessage with structured_output
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All four result types (table, metrics, detail, status) render valid
  Adaptive Card **1.4** JSON using only TextBlock, ColumnSet, FactSet,
  Container, Action.Submit, Action.OpenUrl.
- [ ] A `SemanticUIResult` on `AIMessage.structured_output` (or `.data`)
  is sent as an `application/vnd.microsoft.card.adaptive` attachment with a
  plain-text rendering in the Activity `text` field.
- [ ] Agents that do not return the model get byte-identical behavior to
  today (plain-text path unchanged; existing package tests pass unmodified).
- [ ] Card actions with `prompt_template` render as Action.Submit
  `messageBack` payloads whose click re-enters `ask()` through
  `_handle_message()`; `url` actions render as Action.OpenUrl.
- [ ] `on_turn()` acknowledges `adaptiveCard/action` invokes (200) and routes
  the payload prompt through the message path.
- [ ] Any render failure (unknown type at runtime, template error, oversized
  card) degrades to `render_text()` via `_send_text()`; no exception ever
  escapes the turn handler.
- [ ] Tables truncate at `max_table_rows` (default 15) with a
  "showing N of M" note; serialized cards exceeding `max_card_bytes`
  (default 25 000) trigger the text fallback.
- [ ] `enable_semantic_cards=False` disables card rendering per bot.
- [ ] `semantic.py` and `cards.py` import successfully without
  `microsoft-agents-*` installed; new names exposed via lazy exports in
  `msagentsdk/__init__.py`.
- [ ] No new runtime dependencies added to
  `packages/ai-parrot-integrations/pyproject.toml`.
- [ ] Auth flows (OAuthCard, static-key card, suspend/resume) untouched and
  their tests green.
- [ ] All unit + integration tests pass (`pytest packages/ai-parrot-integrations/tests/ -v`).
- [ ] Usage documentation for agent developers added under `docs/`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All references re-verified on 2026-07-14 against `dev` @ 75cb91bc1.

### Verified Imports
```python
# Lazy re-exports via PEP 562 __getattr__
# (packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py:18-23):
from parrot.integrations.msagentsdk import MSAgentSDKConfig, ParrotM365Agent, MSAgentSDKWrapper
# New public names (SemanticUIResult, UIAction, render_card, render_text)
# must be ADDED to _LAZY_EXPORTS in that __init__.py.

from parrot.models.responses import AIMessage            # responses.py:72
from parrot.models.outputs import OutputMode, StructuredOutputConfig   # outputs.py:36,73

# microsoft_agents imports are ALWAYS lazy, inside methods
# (see agent.py:131, 625, 661, 704, 788):
from microsoft_agents.activity import Activity, ActivityTypes, TextFormatTypes
```

### Existing Class Signatures
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py
class ParrotM365Agent:                                    # line 21
    def __init__(self, parrot_agent: AbstractBot, welcome_message: Optional[str] = None,
                 resolver=None, audit_ledger=None, broker=None, identity_mapper=None,
                 suspended_store=None, conv_ref_store=None, adapter=None,
                 agent_app_id: Optional[str] = None) -> None: ...   # line 46
    async def on_turn(self, context) -> None: ...         # line 117
        # routes: message → _handle_message (line 137); invoke by name:
        # "signin/verifyState" (142), "signin/tokenExchange" (144); else DEBUG-ignored.
        # The adaptiveCard/action route is ADDED here (Module 4).
    async def _handle_message(self, context) -> None: ... # line 214
        # response = await self.parrot_agent.ask(question=..., session_id=...,
        #     user_id=..., ctx=request_ctx, permission_context=pctx)   # lines 291-297
        # await self._send_text(context, str(response.content))        # line 298
        # ^ THE SEAM: card detection replaces line 298 only; the
        #   CredentialRequired except-branch (lines 299-351) stays untouched.
    @staticmethod
    async def _send_invoke_response(context, status_code: int = 200) -> None:  # line 618
    async def _emit_adaptive_card(self, context, capture_url: str, provider: str) -> None:  # line 680
        # attachment contentType "application/vnd.microsoft.card.adaptive" (lines 729-732)
        # Activity(type=message, text=<fallback>, attachments=[...])    (lines 733-737)
        # existing cards pin "version": "1.4"                           (line 710)
    @staticmethod
    async def _send_text(context, text: str) -> None: ... # line 771
        # sends Activity(text_format=TextFormatTypes.plain)

# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/wrapper.py
class MSAgentSDKWrapper:                                  # line 63
    def __init__(self, agent: AbstractBot, config: MSAgentSDKConfig,
                 app: web.Application, broker=None, identity_mapper=None,
                 agent_class: Optional[type] = None) -> None: ...    # line 88

# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py
class MSAgentSDKConfig:                                   # line 11 (dataclass)
    # fields include: anonymous_auth, api_key, api_key_header, endpoint
    # (verified via wrapper.py usage lines 118-120)
    # New knobs ADDED here: enable_semantic_cards, max_table_rows, max_card_bytes

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                               # line 72
    output: Any                                           # line 79
    response: Optional[str]                               # line 82
    data: Optional[Any]                                   # line 86
    structured_output: Optional[Any]                      # line 194
    @property
    def content(self) -> Any: ...                         # line 235

# packages/ai-parrot/src/parrot/bots/abstract.py
@abstractmethod
async def ask(self, question: str, session_id: Optional[str] = None,
              user_id: Optional[str] = None, ...,
              ctx: Optional[RequestContext] = None,
              structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,  # line 3778
              output_mode: OutputMode = OutputMode.DEFAULT,           # line 3779
              **kwargs) -> AIMessage: ...                             # line 3764

# Style references (do NOT extend these):
# packages/ai-parrot/src/parrot/forms/renderers/adaptive_card.py:69
#   class AdaptiveCardRenderer(AbstractFormRenderer)  — form-dialog renderer only
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py:51
#   class TeamsCardRenderer  — HITL card building style reference
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `cards.render_card()` | `SemanticUIResult` | function arg | new (Module 1→2) |
| `_handle_message()` card seam | `AIMessage.structured_output` / `.data` | attribute read | `responses.py:194,86` |
| `_handle_message()` card send | `context.send_activity(Activity(...))` | existing attachment pattern | `agent.py:729-738` |
| Text fallback | `ParrotM365Agent._send_text()` | static method call | `agent.py:771` |
| Invoke shim ack | `ParrotM365Agent._send_invoke_response()` | static method call | `agent.py:618` |
| Invoke shim routing | `on_turn()` invoke-name dispatch | new elif branch | `agent.py:140-147` |
| Config knobs | `MSAgentSDKConfig` | new dataclass fields | `models.py:11` |
| Public API | `msagentsdk/__init__.py` `_LAZY_EXPORTS` | dict entries | `__init__.py:18-23` |

### Configuration References
- SDK pins (optional deps — imports must stay lazy):
  `microsoft-agents-hosting-aiohttp~=0.9.0`,
  `microsoft-agents-authentication-msal~=0.9.0`
  (`packages/ai-parrot-integrations/pyproject.toml:73,77`).
- Adaptive Card attachment `contentType`:
  `"application/vnd.microsoft.card.adaptive"` (`agent.py:730`).
- Card schema version pinned to `"1.4"` (matches existing cards, `agent.py:710`).
- New config defaults (resolved at spec time): `enable_semantic_cards=True`,
  `max_table_rows=15`, `max_card_bytes=25_000`.
- Tests live at `packages/ai-parrot-integrations/tests/` (existing suites:
  `test_hitl_cards.py`, `test_import_isolation.py`, `test_proactive.py`).

### Does NOT Exist (Anti-Hallucination)
- ~~General output→Adaptive-Card rendering in `msagentsdk`~~ — only the OAuth
  sign-in card (`_emit_oauth_card`, agent.py:643) and static-key capture card
  (`_emit_adaptive_card`, agent.py:680) exist today; agent answers are always
  plain text.
- ~~`adaptiveCard/action` or `message/submitAction` invoke handling in
  `on_turn()`~~ — only `signin/verifyState` and `signin/tokenExchange` are
  routed (agent.py:140-147). Module 4 adds the former.
- ~~`OutputMode.ADAPTIVE_CARD`~~ — no such enum member (and this feature does
  NOT add one; detection is by `structured_output` type, not output mode).
- ~~`parrot/integrations/msagentsdk/semantic.py` / `cards.py` /
  `SemanticUIResult` / `UIAction` / `CardRenderError`~~ — created by this
  feature; do not import until their tasks land.
- ~~`MSAgentSDKConfig.enable_semantic_cards` / `.max_table_rows` /
  `.max_card_bytes`~~ — added by Module 3.
- ~~A Python `adaptivecards` / `adaptivecards-templating` dependency~~ — not
  in any pyproject; official template-language libs are JS/.NET only. Cards
  are plain dicts.
- ~~A generic result renderer in
  `parrot.forms.renderers.AdaptiveCardRenderer`~~ — that class is
  form-dialog-specific (`render`/`render_section`/`render_summary`); do not
  extend it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Lazy SDK imports**: `microsoft_agents.*` imports go inside methods, never
  at module top level (pattern: `agent.py:131,661,704,788`). `semantic.py`
  and `cards.py` must not import the SDK at all — cards are plain dicts;
  only `agent.py` wraps them in `Activity`.
- **Attachment shape**: copy the envelope used at `agent.py:729-738`
  (attachment dict + `Activity(type=message, text=<fallback>, attachments=[...])`).
- **Invoke routing**: follow the `signin/*` elif pattern in `on_turn()`
  (`agent.py:140-147`) and acknowledge with `_send_invoke_response()`.
- Async-first, Pydantic models, Google-style docstrings + strict type hints,
  `self.logger` (never print). Renderer functions are pure/sync (no I/O).
- Registered lazy exports keep `import parrot.integrations.msagentsdk`
  side-effect-free (PEP 562 pattern already in `__init__.py`).

### Known Risks / Gotchas
- **Copilot action delivery variance**: M365 Copilot may deliver clicks as
  `adaptiveCard/action` invokes rather than messageBack messages. Mitigated
  by shipping both paths (Module 4 shim). Needs live-tenant validation (§8).
- **Card size limit** (~28 KB Teams attachment): enforced pre-send via
  `max_card_bytes` guard → text fallback. Truncation must add the
  "showing N of M" note so users know data was cut.
- **Fallback must never raise**: `render_text()` is the last line of defense
  and must be total (handle every payload shape, never throw); the
  `_handle_message` card branch wraps everything in try/except → `_send_text`.
- **Do not disturb the `CredentialRequired` except-branch** in
  `_handle_message` (agent.py:299-351): the card seam replaces only the
  success-path send (line 298).
- **Empty payloads**: empty table/metrics must render a "no results" status
  card — an empty ColumnSet renders as a blank card in Teams.
- **Structured-output carrier ambiguity**: some bots put structured data on
  `.data` instead of `.structured_output`; check both, in that priority
  order, and require an actual `SemanticUIResult` instance (no dict duck-typing
  in v1).
- **Non-card channels** (e.g. Bot Framework Emulator): the Activity `text`
  fallback field carries the plain rendering — always populate it.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `microsoft-agents-hosting-aiohttp` | `~=0.9.0` (existing pin) | Activity/TurnContext, attachment delivery — unchanged |
| `microsoft-agents-authentication-msal` | `~=0.9.0` (existing pin) | auth — unchanged |
| `pydantic` | existing core dep | Semantic UI Model |
| *(none new)* | — | cards are plain dicts; no `adaptivecards` PyPI package |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Verify against a live M365 Copilot test tenant whether the
  `msteams messageBack` Action.Submit payload is honored in Copilot chat
  (not just Teams), or whether `Action.Execute` (Universal Actions) is
  required. Design ships both paths, so this determines validation emphasis,
  not architecture. — *Owner: Jesus*: agree
- [x] Confirm Adaptive Card 1.4 feature support in the current M365 Copilot
  custom-engine-agent rendering matrix (spec pins 1.4, matching existing
  cards; revisit only if the tenant test shows gaps). — *Owner: Jesus*: confirmed
- [x] Truncation defaults — *Resolved at spec time*: `max_table_rows=15`,
  `max_card_bytes=25_000` (under Teams' ~28 KB limit), both configurable via
  `MSAgentSDKConfig`.
- [x] Should charts be a v1 result type? — *Resolved in brainstorm*: no — v1
  covers table, metrics/KPI, entity detail, status/error only; charts remain
  available via the existing image/ECharts paths and may join in v2.
- [x] Reuse A2UI as the semantic contract? — *Resolved in brainstorm*: no —
  new lightweight card-oriented model in `ai-parrot-integrations`; A2UI stays
  the web-client protocol (FEAT-273).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree (`feat-303-ux-custom-engine-copilot`).
- **Rationale**: 5 tightly coupled modules in one package; Modules 3 and 4
  edit the same file (`agent.py`); the model (Module 1) is a hard dependency
  of everything downstream. Parallel worktrees would only create merge
  friction.
- **Cross-feature dependencies**: none — no in-flight spec touches
  `parrot/integrations/msagentsdk/` (FEAT-264 auth/suspend-resume is merged);
  core `parrot` package is untouched.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-14 | Jesus Lara | Initial draft from brainstorm (Option A) |

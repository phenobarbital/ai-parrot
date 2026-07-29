---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI Protocol Integration — Rendering Core (`parrot.outputs.a2ui`)

**Feature ID**: FEAT-273
**Date**: 2026-07-10
**Author**: Jesus Lara (decisions) + Claude (research/synthesis)
**Status**: approved
**Target version**: 0.26.0
**Brainstorm**: `sdd/proposals/a2ui-implementation.brainstorm.md` (authoritative input; decisions D1–D10 from `sdd/proposals/a2ui-outputs-brainstorm.md` carried forward)
**Follow-up feature**: FEAT-B — ActionRouter + interactive data-flow (gated by SPK-2; out of scope here)

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot's rich-output pipeline produces maps, charts, infographics, tables
and reports by having the LLM emit **arbitrary Python code or raw HTML** that
the framework executes or injects downstream. Code research confirmed the
scale: six chart renderers (`altair`, `plotly`, `matplotlib`, `seaborn`,
`echarts`, `map`) run LLM-generated Python through a raw `exec()` in
`BaseRenderer.execute_code` (same vulnerability class as the `python_repl`
incident); at least seven renderers emit full raw HTML documents injected
downstream; three tool-level producers build raw HTML outside `parrot.outputs`
entirely (`InteractiveToolkit`, `InfographicToolkit`, Google routes
`_generate_interactive_html_map`). Every output type is an ad-hoc,
non-standard contract.

[A2UI v1.0](https://a2ui.org/specification/v1.0-a2ui/) formalizes the pattern
the `STRUCTURED_*` renderers already pioneered internally: **producer emits a
declarative JSON envelope → validator checks it against a component catalog
(allowlist) → deterministic renderer materializes it**. Adopting it as the
wire format of a rewritten `parrot.outputs` kills the arbitrary-code channel,
standardizes the contract, and buys ecosystem interop (third-party renderers
such as Lynx) — while Parrot exceeds the spec with server-side rendering
(HTML → PDF/email via notifications) and semantic high-level components as
first-class catalog citizens.

### Goals

- **G1 — Security invariant**: the new pipeline contains zero `exec()`/raw-HTML
  injection paths. Catalog = allowlist; envelopes are data, never code.
- **G2 — Dual envelope producers (D1)**: tools emit envelopes deterministically
  from their own data (zero LLM tokens); the LLM produces envelopes only for
  freeform display UI via structured output plus a catalog-validate-retry loop.
- **G3 — A2UI v1.0 wire compatibility (D3/D10a)**: ship Pydantic models for the
  complete v1.0 message set (`createSurface`, `updateComponents`,
  `updateDataModel`, `action`, `actionResponse`, `callFunction`); one
  serialization layer owns the `version` field.
- **G4 — Custom catalog with mandatory lowering (D2/D7/D8)**: Parrot catalog
  (`https://parrot.dev/catalogs/v1`) extends the Basic Catalog; every custom
  component ships a pure deterministic `lower()` to a Basic Catalog tree,
  golden-file tested. No native-only islands.
- **G5 — Static delivery**: baked `RenderedArtifact` (new model) delivered via
  `NotificationMixin.send_notification()`; email/Telegram as real attachments,
  **Teams via new Graph-API file upload** (in scope per spec decision), Slack
  via public artifact URL downgrade.
- **G6 — Deep-link action degradation (D9, expanded)**: `requires_actions`
  components on static surfaces render as **navigator_auth-minted, single-use,
  TTL-bound deep links**; clicking resumes the originating channel/session and
  injects the action as a structured user message (no ActionRouter needed).
  Resume routes are per-channel integration responsibilities.
- **G7 — Coexist + deprecate**: legacy `OutputMode` formats keep working with
  deprecation warnings; new pipeline is additive behind `OutputMode.A2UI`.
  Removal is a later feature.
- **G8 — Packaging**: envelope models, catalog, registries, lowering in
  ai-parrot core under `parrot.outputs.a2ui`; ALL concrete renderers in
  `ai-parrot-visualizations` behind new `a2ui`/`a2ui-pdf` extras (PEP 420
  namespace merge). One-way import rule: core `parrot.outputs.a2ui` never
  imports agents, DatasetManager, or LLM clients.

### Non-Goals (explicitly out of scope)

- `ActionRouter`, transport action bindings, interactive components
  (forms/submit), `callFunction`/`actionResponse` **dispatch**, LLM-generated
  interactive UI → FEAT-B (gated by SPK-2). FEAT-A ships the *schemas* only.
- Incremental `updateComponents` streaming — envelope-complete per output in
  v1 (resolved OQ-D); FEAT-B revisits.
- Removal of legacy formats (deprecation only; cutover table in brainstorm).
- Slack real file upload (public-URL downgrade instead; only Teams Graph
  upload is in scope).
- Flowtask node, voice/LiveAvatar surface, catalog authoring UI, A2UI v0.9.1
  compatibility emit.
- Proprietary declarative format without A2UI compat and Basic-Catalog-only
  adapter — rejected in brainstorm (Options B and C,
  `sdd/proposals/a2ui-implementation.brainstorm.md`).

---

## 2. Architectural Design

### Overview

A new subsystem `parrot.outputs.a2ui` (core) implements the A2UI v1.0
envelope models, the Parrot custom catalog with mandatory lowering, and a
capability-declaring renderer registry. Concrete renderers ship from
`ai-parrot-visualizations` via the established core-registry →
`importlib`-over-namespace dispatch (the `supported_stores` /
`EmbeddingRegistry` pattern). Producers are dual (D1): typed builders for
tools; a structured-output + catalog-validate-retry path for the LLM
(display layouts only in v1 — every component's `requires_actions` flag is
enforced at validation time for LLM-produced envelopes).

Static surfaces get a **baking pass**: renderers resolve every data-model
JSON Pointer binding at render time, producing a self-contained
`RenderedArtifact` (new model — research confirmed nothing reusable exists)
that flows to `send_notification()` and/or `ArtifactStore`. Actions on dead
surfaces degrade to **deep links**: navigator_auth-minted single-use tokens
whose click re-enters the originating channel through a thin per-channel
resume route, injecting the action as a structured user message (Telegram's
suspended-session flow is the in-repo template).

Spike gates were waived by the user and embedded as early tasks: **SPK-1**
(rasterization) runs inside the feature with `weasyprint` as the default PDF
backend and `playwright` as a per-artifact-class fallback candidate; **SPK-3**
(LLM envelope fidelity on Claude + Gemini) calibrates the retry budget before
the LLM-producer module hardens.

Transition routing: a new `OutputMode.A2UI` member routes around the legacy
`OutputFormatter` in `bots/base.py` and `handlers/agent.py`; the envelope
travels in a new dedicated `AIMessage.a2ui_envelope` field (spec decision —
`output` stays untouched for legacy consumers, and the chunked-stream
envelope dict gains the same key).

### Component Diagram

```
 Tools (typed builders, D1) ──►┌──────────────────────────────┐◄── LLM structured output
                               │  parrot.outputs.a2ui.models  │    (catalog-validate-retry,
                               │  (v1.0 message set, version) │     display-only in v1)
                               └──────────────┬───────────────┘
                                              │ validate (catalog allowlist)
                               ┌──────────────▼───────────────┐
                               │ catalog: @register_component │
                               │ schema · instructions ·      │
                               │ requires_actions · lower()   │
                               └──────┬───────────────┬───────┘
                                      │ native        │ lowered Basic tree
                     ┌────────────────▼──────┐   ┌────▼─────────────────┐
                     │ renderer registry     │   │ third-party renderers│
                     │ (RendererCapabilities)│   │ (Lynx, …) + AC       │
                     └──┬───────────┬────────┘   │ fallback transcode   │
              live/chat │           │ static     └──────────────────────┘
        ┌───────────────▼──┐   ┌────▼──────────────────────┐
        │ AIMessage        │   │ baking (JSON Pointer      │
        │ .a2ui_envelope   │   │ resolution) →             │
        │ OutputMode.A2UI  │   │ RenderedArtifact          │
        │ ask_stream JSONL │   └────┬─────────────┬────────┘
        └──────────────────┘        │             │
                        send_notification()   ArtifactStore
                        email/TG attach ·     (public URL
                        Teams Graph upload ·  fallback: Slack)
                        deep-link degradation (navigator_auth token
                        → per-channel resume route → user message)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/outputs/` (core) | extends | new `a2ui/` subtree; legacy `formats/` untouched, deprecation warnings added |
| `ai-parrot-visualizations` | extends | new `parrot/outputs/a2ui_renderers/` modules + `a2ui`/`a2ui-pdf` extras |
| `parrot/models/outputs.py` `OutputMode` | extends | new `A2UI` member |
| `parrot/models/responses.py` `AIMessage` | modifies | new `a2ui_envelope: Optional[Dict[str, Any]]` field |
| `parrot/bots/base.py` ask/ask_stream | modifies | route `OutputMode.A2UI` around `self.formatter.format(...)` |
| `ai-parrot-server` `handlers/agent.py` (`AgentTalk`) | modifies | emit envelope in non-stream response and in the chunked-stream final envelope dict |
| `parrot/notifications/` `NotificationMixin` | modifies | `RenderedArtifact` accepted as `report=`; `_send_teams` gains Graph upload; `_send_slack` gains public-URL line |
| `msteams/graph.py` `GraphClient` | extends | new file-upload methods (Graph API) |
| `parrot/storage/artifacts.py` `ArtifactStore` | uses | envelope/artifact persistence + `get_public_url` |
| `parrot/integrations/{telegram,msteams}` + AgentTalk | extends | thin per-channel deep-link resume routes |
| `parrot/auth` / navigator_auth IdP | uses | token mint/verify for deep links (mint API needs verification — see §8) |
| `parrot/a2a/models.py` | extends | A2UI-A2A extension emit (display) — **after FEAT-272 merges** |
| `parrot/tools/{interactive,infographic}_toolkit.py` | modifies | migrate to deterministic envelope builders |
| `pyproject.toml` (host + visualizations) | extends | new extras; `jsonpointer` dep on the visualizations `a2ui` extra (core gets no new deps) |

### Data Models

```python
# parrot/outputs/a2ui/models.py — complete v1.0 message set (illustrative shape,
# field names follow the A2UI v1.0 spec; NOT implementation code)
class A2UIMessage(BaseModel): ...                     # discriminated union root; single owner of `version`
class CreateSurface(A2UIMessage): ...                 # inline components (one-shot, SSR-friendly)
class UpdateComponents(A2UIMessage): ...              # schema ships v1; dispatched in FEAT-B
class UpdateDataModel(A2UIMessage): ...
class Action(A2UIMessage): ...                        # schema ships v1; dispatch FEAT-B
class ActionResponse(A2UIMessage): ...
class CallFunction(A2UIMessage): ...

# parrot/outputs/a2ui/catalog/base.py
class ComponentDefinition(BaseModel):
    name: str                                          # e.g. "Infographic"
    catalog_id: str = "https://parrot.dev/catalogs/v1"
    schema_: Dict[str, Any]                            # jsonschema for the component payload
    instructions: str                                  # embedded LLM guidance (A2UI spec)
    requires_actions: bool = False                     # D10b

class RendererCapabilities(BaseModel):
    interactive: bool
    supports_actions: bool
    supports_updates: bool
    output: str                                        # mime type | "live"

# parrot/outputs/a2ui/artifacts.py — NEW (research: nothing reusable exists)
class RenderedArtifact(BaseModel):
    artifact_id: str
    mime_type: str
    content: Optional[bytes]                           # inline, XOR path
    path: Optional[Path]                               # temp file for attachments
    filename: str
    title: str
    surface: str                                       # renderer name
    source_envelope_ref: Optional[str]                 # ArtifactStore id / S3 URI
    deep_links: List[DeepLink] = []
    metadata: Dict[str, Any] = {}

class DeepLink(BaseModel):
    action_label: str
    url: str                                           # channel resume URL embedding the token
    token_id: str                                      # for audit/consume tracking
    expires_at: datetime
```

### New Public Interfaces

```python
# parrot/outputs/a2ui/catalog/__init__.py
def register_component(name: str, *, requires_actions: bool = False): ...   # decorator
# each component implements: def lower(self, component, data_model) -> BasicTree  # pure, deterministic (D8)

# parrot/outputs/a2ui/renderers/__init__.py — core registry, satellite classes
def register_a2ui_renderer(name: str, capabilities: RendererCapabilities): ...
def get_a2ui_renderer(name: str) -> "AbstractA2UIRenderer":
    # importlib.import_module(f"parrot.outputs.a2ui_renderers.{name}") — supported_stores pattern;
    # ImportError → actionable message naming the extra

class AbstractA2UIRenderer(ABC):
    capabilities: RendererCapabilities
    async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact | str: ...

# parrot/outputs/a2ui/producer.py — LLM path (D1b)
async def generate_envelope(client, prompt, *, catalog, max_attempts: int) -> CreateSurface:
    # structured_output=StructuredOutputConfig(output_type=CreateSurface) →
    # catalog validation → on failure re-prompt with error context (bounded)

# parrot/outputs/a2ui/deeplink.py
class DeepLinkService:
    async def mint(self, *, session_id, user_id, agent_id, channel, action_payload) -> DeepLink: ...
    async def consume(self, token: str) -> ResumePayload: ...   # single-use enforcement
```

---

## 3. Module Breakdown

> Modules map to Task Artifacts. SPK tasks first; A2A emit last (FEAT-272 dep).

### Module 0a: SPK-1 rasterization spike (embedded task)
- **Path**: `artifacts/spikes/spk1-rasterization/` (evidence), decision recorded in this spec §7
- **Responsibility**: one real infographic envelope → PDF + email-safe HTML via weasyprint AND playwright; measure size/latency/determinism; confirm or amend the weasyprint default.
- **Depends on**: Module 1 (minimal envelope fixture only)

### Module 0b: SPK-3 LLM envelope fidelity spike (embedded task)
- **Path**: `artifacts/spikes/spk3-envelope-fidelity/`
- **Responsibility**: measure structured-output validity rate for the catalog with embedded `instructions` on Claude + Gemini; output = retry budget for Module 8.
- **Depends on**: Modules 1–2

### Module 1: Envelope models + serialization layer
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/models.py`, `serialization.py`
- **Responsibility**: complete v1.0 message set (Pydantic v2, discriminated union), single owner of `version`, JSONL emit, binding-syntax validation (light regex — full JSON Pointer resolution lives in the bake pass).
- **Depends on**: none

### Module 2: Catalog registry + component contract
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/` (`base.py`, `__init__.py`)
- **Responsibility**: `@register_component`, `ComponentDefinition`, mandatory `lower()` contract, allowlist validation of envelopes, `requires_actions` enforcement for LLM-produced envelopes.
- **Depends on**: Module 1

### Module 3: Catalog v1 components + lowerings (parallelizable per component)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/{infographic,report,map,chart,datatable,kpicard,card,timeline,form}.py`
- **Responsibility**: nine components (Form schema-only, `requires_actions=True`), each with schema + instructions + `lower()` + golden-file tests. `STRUCTURED_CHART/TABLE/MAP` config schemas are the starting vocabulary for Chart/DataTable/Map.
- **Depends on**: Module 2

### Module 4: Renderer registry + capabilities (core side)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py`
- **Responsibility**: `register_a2ui_renderer`, `RendererCapabilities`, `AbstractA2UIRenderer`, core→satellite `importlib` dispatch with actionable ImportError.
- **Depends on**: Modules 1–2

### Module 5: Concrete renderers (satellite; parallelizable per renderer)
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/{ssr_html,folium_map,echarts,adaptive_cards,pdf}.py`
- **Responsibility**: ssr-html (baked full-document HTML), folium-map, echarts-payload (vendored `echarts.min.js`), adaptive-cards display subset (via lowered tree), pdf (SPK-1 backend). Static renderers bake; `requires_actions` components degrade to deep links or reject.
- **Depends on**: Modules 3–4 (+ Module 0a for pdf)

### Module 6: Baking pass + `RenderedArtifact`
- **Path**: core model `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py`; bake helper used by satellite renderers
- **Responsibility**: resolve all JSON Pointer bindings (jsonpointer lib, satellite dep), produce `RenderedArtifact`; `ArtifactStore` persistence incl. >200 KB S3 overflow convention.
- **Depends on**: Modules 1, 4

### Module 7: Delivery bridge + Teams Graph upload
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/delivery.py`; changes in `parrot/notifications/__init__.py`; `packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py`
- **Responsibility**: `RenderedArtifact` → `send_notification(report=…)` (attachment extraction reads `report.files`); **new Graph-API file upload on `GraphClient`** wired into `_send_teams`; Slack `_send_slack` gains public-URL line (`ArtifactStore.get_public_url`); degraded-delivery logging.
- **Depends on**: Module 6

### Module 8: Deep-link token service + per-channel resume routes
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py`; thin routes in `integrations/telegram`, `integrations/msteams`, and AgentTalk (web)
- **Responsibility**: mint/verify via navigator_auth IdP (single-use enforced by a Redis consume record — replay protection only; see §8 verification task), per-channel resume route verifies+consumes token and injects the action as a structured user message through the channel's existing inbound seam (Telegram suspended-session flow as template; web via AgentTalk POST).
- **Depends on**: Module 6 (DeepLink model); channel work parallelizable per channel

### Module 9: LLM producer (validate-retry loop)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/producer.py`
- **Responsibility**: `structured_output=StructuredOutputConfig(output_type=CreateSurface)` through existing client machinery; catalog-validation failure → bounded re-prompt with error context (budget from SPK-3); final failure degrades to plain text, never raw passthrough; display-only enforcement.
- **Depends on**: Modules 1–3, 0b

### Module 10: Emission wiring (OutputMode.A2UI + AIMessage + handlers)
- **Path**: `parrot/models/outputs.py`, `parrot/models/responses.py`, `parrot/bots/base.py`, `ai-parrot-server/src/parrot/handlers/agent.py`
- **Responsibility**: `OutputMode.A2UI` routing around the legacy formatter; `AIMessage.a2ui_envelope`; chunked-stream final-envelope dict gains the key; envelope-complete per output (resolved OQ-D).
- **Depends on**: Modules 1, 4

### Module 11: Tool builders migration
- **Path**: `parrot/tools/infographic_toolkit.py`, `parrot/tools/interactive_toolkit.py` (+ typed builder helpers in `parrot/outputs/a2ui/builders.py`)
- **Responsibility**: deterministic envelope builders (D1a); toolkits emit envelopes instead of raw HTML (legacy paths kept behind deprecation flag per G7).
- **Depends on**: Modules 3, 10

### Module 12: Legacy deprecation warnings
- **Path**: `parrot/outputs/formats/__init__.py`, affected format modules
- **Responsibility**: `DeprecationWarning` on `get_renderer` for modes in the replace column of the brainstorm cutover table; docs note. No behavior change.
- **Depends on**: Module 10 (so each warning can point at the A2UI replacement path)

### Module 13: A2UI-A2A extension emit (display) — **after FEAT-272**
- **Path**: `parrot/a2a/models.py` (+ emit glue)
- **Responsibility**: wrap display envelopes in A2A `Artifact.parts` per the A2UI-A2A official extension.
- **Depends on**: Module 10; **cross-feature: FEAT-272 merged**

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_message_set_roundtrip` | 1 | Every v1.0 message type serializes/deserializes; `version` set by serialization layer only |
| `test_envelope_rejects_unknown_component` | 2 | Allowlist: unknown component name → structured validation error |
| `test_llm_envelope_rejects_requires_actions` | 2 | LLM-produced envelope containing a `requires_actions` component fails validation in v1 |
| `test_component_lowering_golden[component]` | 3 | Each of the 9 components lowers to the expected Basic Catalog golden file (pure/deterministic: same input → identical tree) |
| `test_renderer_registry_missing_extra` | 4 | Missing satellite → ImportError naming `ai-parrot-visualizations[a2ui]` |
| `test_bake_resolves_all_pointers` | 6 | Baked output contains zero live bindings; unresolvable pointer → validation error |
| `test_rendered_artifact_notification_bridge` | 7 | `RenderedArtifact` maps onto `send_notification` attachment extraction (`report.files`) |
| `test_teams_graph_upload_called` | 7 | Teams delivery invokes GraphClient upload (mocked); Slack falls back to public URL |
| `test_deeplink_single_use` | 8 | Second consume of the same token fails; expired token fails |
| `test_producer_retry_bounded_then_degrades` | 9 | Validation failures re-prompt ≤ budget, then plain-text degradation (never raw passthrough) |
| `test_output_mode_a2ui_routes_around_formatter` | 10 | `OutputMode.A2UI` never enters `OutputFormatter.format` |
| `test_legacy_modes_unchanged` | 12 | Legacy formats still render; replaced modes emit `DeprecationWarning` |
| `test_no_exec_in_a2ui_subtree` | all | Static check: no `exec(`/`eval(` under `parrot/outputs/a2ui*` (both packages) |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_tool_envelope_to_html` | Tool builder → validate → SSR-HTML render → self-contained document, no script injection from data |
| `test_e2e_envelope_to_pdf_email` | Infographic envelope → bake → PDF `RenderedArtifact` → email attachment path (mock SMTP) |
| `test_e2e_deeplink_resume_telegram` | Baked artifact with degraded action → mint → resume route → action arrives as structured user message in session |
| `test_e2e_deeplink_resume_web` | Same round-trip through AgentTalk POST |
| `test_e2e_ask_stream_envelope_complete` | `ask_stream` emits one complete envelope in the final chunk dict; chunked contract (`X-Parrot-Stream`) unchanged |
| `test_core_importable_without_satellite` | `ai-parrot` alone: `import parrot.outputs.a2ui` works; renderer resolution raises the actionable error |

### Test Data / Fixtures
```python
@pytest.fixture
def infographic_envelope():
    """Golden CreateSurface envelope exercising Infographic + Chart + KPICard,
    with data-model bindings — shared by lowering, baking, SPK-1 and renderer tests."""
    return load_golden("tests/outputs/a2ui/golden/infographic_envelope.json")

@pytest.fixture
def catalog_v1():
    """Fully-registered v1 catalog (all nine components)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit + integration tests above pass (`pytest packages/ai-parrot/tests/outputs/a2ui packages/ai-parrot-visualizations/tests -v`)
- [ ] **G1**: `grep -rn "exec(\|eval(" packages/*/src/parrot/outputs/a2ui*` returns nothing; no A2UI code path invokes `BaseRenderer.execute_code`
- [ ] **G3**: all six v1.0 message types round-trip; `version` emitted by exactly one module
- [ ] **G4**: every registered component has a `lower()` implementation and passing golden-file test — components without one cannot register (enforced, not convention)
- [ ] **G2/D10b**: every component declares `requires_actions`; LLM producer rejects `requires_actions` components; producer retry is bounded and degrades to text
- [ ] **G5**: `RenderedArtifact` delivered end-to-end — email + Telegram real attachments, Teams via Graph upload, Slack via public URL with degraded-delivery log line
- [ ] **G6**: deep-link round-trip proven on Telegram AND web (mint → click → single-use consume → structured user message in the same session); replay + expiry rejected
- [ ] **G7**: full legacy test suite still green; replaced modes emit `DeprecationWarning`; no legacy behavior change
- [ ] **G8**: `ai-parrot` core installs/imports with zero new heavy deps; renderers resolve only with `ai-parrot-visualizations[a2ui]`; missing-extra error is actionable
- [ ] Envelope-complete streaming: `ask_stream` chunked contract unchanged (header `X-Parrot-Stream: chunked-aimessage` preserved)
- [ ] SPK-1 evidence committed under `artifacts/spikes/` with a recorded backend decision; SPK-3 fidelity numbers recorded and retry budget set from them
- [ ] A2A emit lands only after FEAT-272 is merged (task ordering enforced in the index)
- [ ] Documentation: `docs/` page covering catalog authoring (component + lowering + golden files) and renderer registration

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified during FEAT-273 research (2026-07-09/10, four parallel research
> passes over the monorepo; line numbers re-checked against current `dev`).

### Verified Imports
```python
from parrot.outputs.formats import register_renderer, get_renderer  # core formats __init__
from parrot.models.outputs import OutputMode, StructuredOutputConfig  # models/outputs.py
from parrot.notifications import NotificationMixin, NotificationProvider  # notifications/__init__.py
from parrot.storage.models import Artifact, ArtifactType  # storage/models.py:275/:244
from parrot.storage.artifacts import ArtifactStore  # storage/artifacts.py:27
from parrot.core.events.lifecycle.registry import EventRegistry  # registry.py:90
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/outputs/formats/base.py — LEGACY, do not extend for A2UI
class BaseRenderer(ABC):
    def execute_code(self, code, pandas_tool=None, ...) -> Tuple[Optional[Dict], Optional[str]]
        # anchor: `exec(code, namespace, locals_dict)` — the sink FEAT-273 replaces
    async def render(self, response, environment='terminal', export_format='html',
                     include_code=False, **kwargs) -> Tuple[Any, Optional[Any]]  # abstract

# packages/ai-parrot/src/parrot/outputs/formatter.py
class OutputFormatter:  # anchor `class OutputFormatter`
    async def format(self, mode: OutputMode, data, **kwargs) -> Tuple[str, Optional[str]]
    async def format_with_retry(self, mode, data, original_prompt=None, llm_client=None,
                                retry_config=None, **kwargs) -> OutputRetryResult
        # anchor `DEFAULT_RETRY_PROMPTS` — precedent for Module 9's retry loop

# packages/ai-parrot/src/parrot/clients/base.py — AbstractClient (NO completion() exists)
async def ask(self, prompt, model, max_tokens=4096, temperature=0.7, files=None,
    system_prompt=None, structured_output: Union[type, StructuredOutputConfig, None] = None,
    ...) -> MessageResponse
async def invoke(self, prompt, *, output_type: Optional[type] = None,
    structured_output: Optional[StructuredOutputConfig] = None, ...) -> InvokeResult
# _parse_structured_output degrades to RAW TEXT on ValidationError — no client-level re-prompt
# anchors: `def _get_structured_config`, `f"Fallback parsing failed: {e}."`

# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum): ...   # 32 members; add A2UI here
@dataclass
class StructuredOutputConfig:      # anchor `class StructuredOutputConfig:`
    output_type: type
    format: OutputFormat = OutputFormat.JSON
    custom_parser: Optional[Callable[[str], Any]] = None
    # methods: get_schema(), format_schema_instruction()

# packages/ai-parrot/src/parrot/notifications/__init__.py:131 — on BasicAgent only
async def send_notification(self, message, recipients,
    provider: Union[str, NotificationProvider] = NotificationProvider.EMAIL,
    subject=None, report=None, template=None, with_attachments: bool = True,
    provider_options=None, **kwargs) -> Dict[str, Any]
# Attachment sources: report.files → report.documents → content blocks (type=="file")
# EMAIL full attachments · TELEGRAM typed send_photo/send_document (:533)
# TEAMS (:655) filenames-in-text ONLY today (Module 7 fixes via Graph)
# SLACK (:525) text only today (Module 7 adds public-URL line)
# bots/agent.py:29 → `class BasicAgent(Chatbot, NotificationMixin)`

# packages/ai-parrot/src/parrot/models/responses.py — AIMessage
#   output: Any (:79) · response: Optional[str] (:82) · files: Optional[List[Path]] (:102)
#   output_mode: OutputMode (:210) · artifacts: List[Dict] (:206) · artifact_id (:214)
#   → add a2ui_envelope: Optional[Dict[str, Any]] (Module 10)

# packages/ai-parrot/src/parrot/storage/models.py:275 — chat Artifact (definitions, NOT files)
class Artifact(BaseModel):
    artifact_id: str; artifact_type: ArtifactType; title: str
    definition: Optional[Dict[str, Any]] = None
    definition_ref: Optional[str] = None  # S3 URI when serialized >200 KB
# ArtifactStore (storage/artifacts.py:27): save/get/list/update/delete, get_public_url
# Public HTML serving: ai-parrot-server handlers/artifacts.py:530 ArtifactPublicHTMLView

# packages/ai-parrot/src/parrot/embeddings/registry.py — dispatch pattern to COPY
cls_name = self._supported_embeddings[model_type]
module = importlib.import_module(f"parrot.embeddings.{model_type}")
klass = getattr(module, cls_name)
# anchor: `raise ImportError(f"Cannot import embedding module '{module_path}': {exc}")`

# packages/ai-parrot-server/src/parrot/handlers/agent.py — AgentTalk seams
# class AgentTalk(BaseView) :102 · chunked streaming only, anchor `'X-Parrot-Stream': 'chunked-aimessage'` (:2716)
# final stream envelope dict built :2753-2785, separator b'\n\x00' (:2786)
# non-stream: _prepare_response (:541) / _format_response (:2871)

# packages/ai-parrot-server/src/parrot/handlers/stream.py — navigator_auth verify seam
# :280 `idp = getattr(auth, '_idp', None)` · :288 `_, payload = idp.decode_token(code=token)`
# (decode VERIFIED; mint/encode API unverified — see §8)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py
class ResolvedTeamsUser(BaseModel)  # :48
class GraphClient                    # :76 — NO file-upload methods today (Module 7 adds them)

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py — resume template
# handle_message → _state_manager.get_suspended_session(...) (:2525)
# → session.session_id override (:2543) → orchestrator.resume_agent(...) (:2557)

# Packaging (verified): host parrot/__init__.py uses pkgutil extend_path;
# satellites have NO parrot/__init__.py (PEP 420 dirs) + `namespaces = true`;
# viz pyproject: [tool.uv.sources] ai-parrot = { workspace = true };
# host `charts` extra already = ai-parrot-visualizations[charts,infographic]
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Module 10 routing | `BaseBot.ask` formatter call | branch before `await self.formatter.format(...)` | `bots/base.py:487`, `:1431` |
| Module 10 stream emit | `AgentTalk._handle_stream_response` envelope dict | new key in final dict | `handlers/agent.py:2753-2786` |
| Module 7 bridge | `NotificationMixin` attachment extraction | `report.files` precedence | `notifications/__init__.py:256` (`_extract_message_content`) |
| Module 7 Teams upload | `GraphClient` | new upload methods | `msteams/graph.py:76` |
| Module 8 verify | navigator_auth IdP | `idp.decode_token(code=token)` | `handlers/stream.py:288` |
| Module 8 Telegram route | suspended-session seam | template to mirror | `telegram/wrapper.py:2525-2557` |
| Module 4 dispatch | namespace merge | `importlib.import_module(f"parrot.outputs.a2ui_renderers.{name}")` | pattern: `embeddings/registry.py` |
| Module 6 persistence | `ArtifactStore` | `save_artifact` / `get_public_url` | `storage/artifacts.py:27` |
| Module 9 producer | `AbstractClient.ask` | `structured_output=StructuredOutputConfig(...)` | `bots/base.py` anchor `llm_kwargs["structured_output"]` |

### Does NOT Exist (Anti-Hallucination)

- ~~`RenderedArtifact` / `RenderedOutput` / `OutputArtifact`~~ — no reusable rendered-file model anywhere; Module 6 creates it. (Input doc's CR-2 assumption was wrong.)
- ~~`Agent.notification()` / `Agent.notify()`~~ — surface is `NotificationMixin.send_notification` on `BasicAgent` only (not `AbstractBot`).
- ~~`AbstractClient.completion()`~~, ~~`response_model`~~, ~~public `response_format` param~~ — surface is `ask`/`ask_stream`/`invoke` with `structured_output`.
- ~~Client-level structured-output validate-retry loop~~ — `_parse_structured_output` silently degrades to raw text; Module 9 builds the loop.
- ~~`ActionRouter`~~, ~~any `Interceptor`/mutation hook~~ — lifecycle events are frozen/observe-only (FEAT-176 Phase 2 gap; FEAT-B territory).
- ~~First-party JWT signing in `parrot.auth`~~ — no `jwt.encode`/`jose` anywhere; only the OAuth2 Redis nonce machinery (`oauth2_base.py` `_NONCE_KEY_TEMPLATE` :40) is in-repo. Token mint delegated to navigator_auth (§8 verification).
- ~~Per-channel deep links / "resume chat by id" endpoint~~ — `deep_link` exists only as outbound live-chat escalation (`human/actions/backends/webhook.py`).
- ~~`GraphClient.upload_file()` or any Graph upload method~~ — must be added (Module 7).
- ~~Teams `on_invoke_activity` handler~~ — card submits arrive as `message` activities with `activity.value` (`msteams/wrapper.py:305`, :457).
- ~~Real file attachments for Teams/Slack notifications~~ — Teams lists filenames in text; Slack text-only (today).
- ~~SSE in AgentTalk~~ — chunked HTTP only; WS loop lives in `handlers/stream.py`.
- ~~A renderer for `OutputMode.CHART`~~ — `_MODULE_MAP` maps it but nothing registers; `INTERACTIVE`, `CODE`, `IMAGE`, `SQL_ANALYSIS`, `TELEGRAM`, `MSTEAMS`, `JUPYTER`, `NOTEBOOK` have no renderer entries.
- ~~`_try_create_faiss_store` in `parrot/stores/`~~ — it lives in `parrot_tools/database/cache.py` (different package; cited only as a lazy-import precedent).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Registry + `importlib` namespace dispatch** exactly as `embeddings/registry.py` / `supported_stores` — core dict, satellite modules, actionable ImportError naming the extra.
- **Decorator registration** as `formats/__init__.py` `register_renderer` (but on the new A2UI registries; never extend legacy `BaseRenderer`).
- **PEP 420 satellite layout** as `ai-parrot-visualizations`: no `parrot/__init__.py` in the satellite subtree, `namespaces = true`, `[tool.uv.sources] ai-parrot = { workspace = true }`.
- **Retry-loop shape** from `OutputFormatter.format_with_retry`/`DEFAULT_RETRY_PROMPTS`, lifted to catalog-validation errors (Module 9).
- **Redis one-shot consume** from `oauth2_base.py` nonce machinery (`_NONCE_KEY_TEMPLATE`, `secrets.token_urlsafe(32)`) — used for single-use enforcement alongside navigator_auth verification.
- **Telegram suspended-session resume** (`wrapper.py:2525-2557`) as the per-channel resume-route template.
- Async-first throughout; Pydantic v2 models; Google-style docstrings; `self.logger`, no prints (note: legacy formatter has a stray `print` — do not copy).
- Two-phase bake: CONFIGURE-bake (static) vs REQUEST-live (chat) — static renderers must resolve *all* pointers; a baked artifact contains zero live bindings.

### Known Risks / Gotchas
- **A2UI v1.0 is a candidate spec with no other implementer** — absorb forks in `serialization.py` only; nothing else may read/write `version`.
- **navigator_auth mint API unverified** — decode is proven (`stream.py:288`); whether the IdP exposes token *creation* usable for deep links must be verified in Module 8's first task; fallback (pre-approved in brainstorm lean): Redis-backed opaque one-shot token, same route contract, no schema change.
- **Invalid LLM envelope**: bounded retry then plain-text degradation — never raw passthrough (G1 must survive the failure path).
- **`requires_actions` on static surface with no session context**: render with actions stripped + visible notice (deep link impossible).
- **Expired/replayed deep link**: friendly "session expired" landing; token payload never client-side.
- **Oversized envelopes**: reuse `ArtifactStore` 200 KB S3-overflow convention (`definition_ref`).
- **Teams Graph upload scope creep**: Module 7 implements upload-to-chat via Graph; if tenant permissions block it at runtime, delivery falls back to the Slack-style public-URL downgrade with a degraded log (never silent drop).
- **playwright nondeterminism in containers** (SPK-1): weasyprint is default precisely for determinism; ECharts→static-SVG pre-render is the required companion if weasyprint wins.
- **Legacy formatter debug side-effects** (`static/html/tests/` writes): do not replicate; A2UI pipeline has no filesystem side-effects outside explicit artifact paths.
- **FEAT-272 collision** on `parrot/a2a/` — Module 13 is last and starts only after FEAT-272 merges.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `jsonpointer` | `>=2.4` | data-model binding resolution in the bake pass — dep of `ai-parrot-visualizations[a2ui]`, NOT core |
| `weasyprint` | existing (`pdf` extra) | default PDF backend (SPK-1) |
| `playwright` | existing (`agents` extra) | SPK-1 comparison / per-artifact-class fallback |
| `folium` | existing (viz `map` extra) | folium-map renderer |
| vendored `echarts.min.js` | existing (viz assets) | echarts SSR/HTML renderer |
| `msgraph-sdk` | existing (`agents` extra) | Teams Graph upload (confirm exact client used by `GraphClient`) |
| — | — | **core `ai-parrot` gains zero new dependencies** (G8) |

---

## Worktree Strategy

- **Default isolation unit**: `mixed`.
- **Sequential foundation (one primary worktree)**: Modules 1 → 2 → 4 → 6 → 10 (contracts everything else depends on), plus SPK-1/SPK-3 early.
- **Parallelizable after contracts merge**:
  - Module 3 components — one task per component, file-disjoint by construction.
  - Module 5 renderers — one task per renderer, disjoint satellite modules.
  - Module 8 per-channel resume routes — disjoint integration packages.
  - Modules 7, 9, 11, 12 — independent of each other once 6/10 land.
- **Cross-feature dependencies**: **FEAT-272 (a2a-protocol-compatibility) must merge before Module 13**. No other in-flight spec touches `parrot/outputs/` or the visualizations satellite.

---

## 8. Open Questions

> Resolved items are the audit trail of brainstorm + spec-session decisions.

- [x] Flow type / base branch — *Resolved in brainstorm*: feature → `dev`.
- [x] Packaging split — *Resolved in brainstorm*: contract (models/catalog/registries/lowering) in core `parrot.outputs.a2ui`; ALL renderers in `ai-parrot-visualizations`; supersedes D4's `parrot.interfaces.outputs` location.
- [x] OQ-D streaming granularity — *Resolved in brainstorm*: envelope-complete per output in v1; incremental `updateComponents` → FEAT-B.
- [x] Migration policy — *Resolved in brainstorm*: coexist + deprecate per cutover table; removals later.
- [x] OQ-B catalog v1 list — *Resolved in brainstorm*: Infographic, Report, Map, Chart, DataTable, KPICard, Card, Timeline, Form (schema-only, `requires_actions=True`); CR-1 inventory covered; `application` mode deprecated, not a component.
- [x] Deep-link scope — *Resolved in brainstorm*: signed-token resume IS in FEAT-A; action injected as structured user message; per-channel resume routes (no unified endpoint).
- [x] Spike gates vs spec timing — *Resolved in spec session*: gates waived; SPK-1/SPK-3 embedded as early tasks (Modules 0a/0b); weasyprint default pending SPK-1 evidence.
- [x] Deep-link token infrastructure — *Resolved in spec session*: **navigator_auth-minted token** (overrides the brainstorm's Redis lean); Redis one-shot record retained for single-use/replay enforcement only.
- [x] Teams/Slack attachment gap — *Resolved in spec session*: **Teams Graph upload pulled INTO FEAT-A** (Module 7); Slack keeps the public-URL downgrade.
- [x] A2A sequencing — *Resolved in spec session*: depend on FEAT-272; Module 13 last.
- [x] `AIMessage` envelope carrier — *Resolved by spec author*: dedicated `a2ui_envelope: Optional[Dict[str, Any]]` field (leaves `output` untouched for legacy consumers; same key added to the chunked-stream final dict).
- [x] `jsonpointer` dependency — *Resolved by spec author*: dep of `ai-parrot-visualizations[a2ui]`; core validates binding syntax only (no new core deps).
- [ ] navigator_auth token-mint API — does the IdP expose creation usable for deep links (decode verified at `stream.py:288`; mint unverified)? First task of Module 8; fallback = Redis opaque one-shot token. — *Owner: Module 8 implementer*
- [ ] OQ-C lowered-tree fidelity — golden-file review criteria for minimum acceptable Infographic/Report degradation. — *Owner: Module 3 implementer, first component task*
- [ ] Exact Graph API permission set / upload target (chat message attachment vs OneDrive share link) for Teams upload. — *Owner: Module 7 implementer*
- [x] SPK-1 outcome — *Resolved (TASK-1722)*: **weasyprint confirmed as the default
  for ALL static artifact classes** (intrinsic determinism, ~3.6× smaller output, no
  browser dependency); playwright not adopted as a per-class split in v1 (kept as a
  documented fallback). Companion: ECharts pre-renders to static SVG for the weasyprint
  path. Evidence: `artifacts/spikes/spk1-rasterization/results.md`.
- [x] SPK-3 outcome — *Resolved (TASK-1727, evidence-pending)*: recommended
  **`max_attempts = 3` (1 initial + 2 catalog-validate retries)** for Module 9, grounded
  in the in-repo `OutputFormatter` `max_retries=2` precedent. First-shot validity % was
  **NOT measured** in the build environment (both Claude & Gemini returned 404
  model-not-found — no fabricated numbers). Harness + 22-prompt set committed under
  `artifacts/spikes/spk3-envelope-fidelity/`; re-run with valid credentials to confirm.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-10 | Jesus Lara + Claude | Initial draft from brainstorm `a2ui-implementation.brainstorm.md` |

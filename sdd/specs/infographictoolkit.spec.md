---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Infographic Toolkit — Single-Turn Interactive HTML Artifacts

**Feature ID**: FEAT-197
**Date**: 2026-05-28
**Author**: Jesus
**Status**: draft
**Target version**: 0.25.0

> Source brainstorm: `sdd/proposals/infographictoolkit.brainstorm.md`
> (Recommended Option B; 13/13 open questions resolved).

---

## 1. Motivation & Business Requirements

### Problem Statement

Generating an infographic today is a two-step user-visible flow: the user asks
the agent a question and gets a conversational answer with the relevant
DataFrames; then the user (or the client) issues a separate
`POST /api/v1/agents/infographic/{agent_id}` call with a `query` and a
`template`. This second call disregards the DataFrames computed in step 1 —
it re-generates everything from scratch via `bot.get_infographic()`. The
result is wasted LLM cost, duplicated data work, no path to multi-dataset
dashboards, and no JavaScript interactivity.

Two capabilities are blocked by this design:

- **Multi-dataset infographics with reactive interactivity.** A
  financial-variance dashboard composed of three or four distinct DataFrames
  (revenue daily, EBITDA daily, cumulative revenue) feeding 4 hero cards + 2
  bar charts (DoD) + 1 cumulative line chart cannot be produced by the
  current single-pass `get_infographic`.
- **Single-turn delivery of interactive HTML apps from a normal agent
  conversation.** The user should be able to write `/financial_variance Q4 2025`
  in chat and receive, in a single agent turn, both the underlying DataFrames
  AND the rendered interactive HTML artifact.

The core architectural problem is that the agent's tool-calling loop normally
treats tool outputs as material for further LLM summarization. An infographic
HTML response must NOT be summarized, NOT converted to markdown, NOT
re-formatted — it must be returned to the caller verbatim while still
preserving the multi-dataset envelope so downstream consumers can use both
the visual and the data.

### Goals

- Deliver a `/skill_name` chat invocation that yields, in **one** agent turn,
  both the source DataFrames (under `response.data`) and a signed URL to a
  frozen, self-contained HTML artifact (`response.output`).
- Preserve multi-dataset state across the LLM tool-calling loop via the
  existing `_inject_multi_data_from_variables` path.
- Enforce a **deterministic** positional contract between LLM-produced
  blocks and `InfographicTemplate.block_specs`. Validation failures are
  loud and structured (`SLOT_MISSING`, `SLOT_TYPE_MISMATCH`,
  `SLOT_ITEM_COUNT_INVALID`, `DATA_VAR_MISSING`, `DATA_VAR_EMPTY`,
  `THEME_INVALID`, `EXTRA_BLOCKS`, `TEMPLATE_UNKNOWN`,
  `ENHANCE_OUTPUT_INVALID`).
- Bypass LLM re-summarization via the existing
  `AbstractToolkit.return_direct=True` lever — without touching any LLM
  client.
- Reuse the existing `SkillRegistry` `/trigger` middleware
  (`parrot/skills/middleware.py`) — no new prefix parsing in
  `AgentTalk.post()`.
- Reuse all 15 existing block models, `InfographicResponse`,
  `InfographicTemplate`, `BlockSpec`, `infographic_registry`,
  `theme_registry`, and the existing `InfographicHTMLRenderer`.
- Optional LLM-augmented JavaScript interactivity via `mode="enhance"`, with
  HTML output validated against the template's declared `js_bundles` SRI
  whitelist.
- Backward compatibility: `POST /api/v1/agents/infographic/{agent_id}` and
  `bot.get_infographic()` remain untouched.

### Non-Goals (explicitly out of scope)

- **Automatic intent detection** ("make me a dashboard" without explicit
  skill/mode/tool reference). Explicit invocation only in v1.
- **Re-rendering frozen HTML on demand from blocks.** v1 stores HTML as a
  frozen blob.
- **`!skill_name` parsing in `AgentTalk.post()`.** Rejected in brainstorm
  Round 1 — the `/trigger` SkillRegistry middleware handles activation
  instead.
- **Single-turn LLM retry on validation errors.** Rejected in brainstorm
  Round 1 — validation errors surface immediately to the user.
- **User-scoped signed URL authorization.** v1 uses signature-only auth
  (any caller with the URL can fetch).
- **Server-side composition without the toolkit** (brainstorm Option C —
  dedicated HTTP endpoint). Rejected because it eliminates the
  LLM-in-the-loop enhance capability.
- **Streaming response bodies for `output_mode=infographic`.** The mode
  forces a non-streamed final envelope containing the URL.
- Per-tenant `frame-ancestors` configuration. v1 uses a single env-driven
  whitelist (`INFOGRAPHIC_FRAME_ANCESTORS`).

---

## 2. Architectural Design

### Overview

The feature is delivered as **Option B** from the brainstorm: a new
`InfographicToolkit(AbstractToolkit)` exposing four tools, plus a thin
`OutputMode.INFOGRAPHIC` enum value that acts purely as a content-negotiation
and system-prompt hint. The toolkit is the engine; the OutputMode is the
canonical type-safe signal.

The pipeline is:

1. The user invokes a skill via `/skill_name <args>` (or sets
   `output_mode=infographic`, or names the tool in natural language).
2. The existing `SkillRegistry` trigger middleware
   (`parrot/skills/middleware.py:16-74`) detects the `/` prefix, looks the
   trigger up in `SkillFileRegistry`, sets `bot._active_skill`, and strips
   the trigger.
3. `AbstractBot._build_request_prompt` (`bots/abstract.py:2613-2640`)
   injects the skill's `template_body` as a transient `PromptLayer`
   (priority 90) for that single turn.
4. The skill body instructs the LLM to (a) fetch/compute DataFrames via
   `python_repl_pandas` / `fetch_dataset` and (b) close the turn with
   `infographic_render(template_name=..., theme=..., mode=..., blocks=[...], data_variables=[...])`.
5. `InfographicToolkit.render` runs the deterministic validation pipeline,
   renders the skeleton via `InfographicHTMLRenderer`, optionally runs
   `bot.enhance_infographic` for the JS-augmented pass, and saves the
   artifact through `ArtifactStore.save_artifact`.
6. Because `return_direct=True`, the tool result is the final agent output.
7. `PandasAgent.ask()` detects the `InfographicRenderResult` envelope,
   populates `response.data` via `_inject_multi_data_from_variables`,
   sets `response.output`, `response.output_mode = OutputMode.INFOGRAPHIC`,
   `response.artifact_id`, and bypasses both the formatter and the
   structured-output reformat path.
8. The HTTP layer (`_format_response` in `handlers/agent.py`) returns the
   JSON envelope (or `text/html` if requested) and streams are forcibly
   disabled for this mode.
9. The signed URL is served by `ArtifactDetailView.get` with strict CSP
   headers (`frame-ancestors` whitelisted via env).

### Component Diagram

```
User chat
   │  "/financial_variance Q4 2025"
   ▼
AgentTalk.post()
   │
   ▼
PandasAgent.ask()
   │
   ├──▶ _prompt_pipeline.apply()
   │       │
   │       └──▶ skill_trigger_middleware  (parrot/skills/middleware.py)
   │              · registry.get('/financial_variance')
   │              · bot._active_skill = skill
   │
   ├──▶ _build_request_prompt()  (bots/abstract.py:2613-2640)
   │       └──▶ injects skill PromptLayer (priority 90, transient)
   │
   ├──▶ LLM tool-calling loop
   │       ├── python_repl_pandas  (computes DataFrames)
   │       ├── fetch_dataset        (optional)
   │       └── infographic_render   ◀── InfographicToolkit (return_direct=True)
   │              │
   │              ├── validate template + blocks + data_vars + theme
   │              ├── InfographicHTMLRenderer.render_to_html(...)
   │              ├── (if enhance) bot.enhance_infographic(skeleton, brief, ...)
   │              │      └── validate HTML + js_bundles SRI whitelist
   │              ├── ArtifactStore.save_artifact(...)
   │              └── ArtifactStore.get_public_url(...)  ◀── NEW
   │
   └──▶ post-loop branch  ◀── NEW
           · isinstance(last_tool_result, InfographicRenderResult)
           · response.data ← _inject_multi_data_from_variables(...)
           · response.output ← html_url (or html_inline if < 50KB)
           · response.output_mode ← OutputMode.INFOGRAPHIC
           · response.artifact_id ← envelope.artifact_id   ◀── NEW field
           · skip formatter + structured reformat

HTTP response
   │  application/json    OR    text/html  (Accept-driven)
   ▼
client / iframe ──┐
                  │  GET /api/v1/artifacts/public/{sig}/{artifact_id}.html
                  ▼
        ArtifactDetailView.get()
           · CSP header with frame-ancestors from env
           · Content-Type: text/html; charset=utf-8
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` (`parrot/tools/toolkit.py:191`) | extends | `InfographicToolkit` subclass with `return_direct=True` (line 220) and `tool_prefix="infographic"` (line 242). |
| `SkillRegistryMixin` (`parrot/skills/mixin.py:27`) | uses | Existing `/trigger` middleware activates the skill; no new prefix parsing. |
| `SkillFileRegistry` (`parrot/skills/file_registry.py`) | uses | Skills loaded from `AGENTS_DIR/<agent>/skills/`; per-agent storage. |
| `InfographicHTMLRenderer` (`parrot/outputs/formats/infographic_html.py:582`) | uses | Renders `InfographicResponse` to HTML; `render_to_html(response, theme=...)` helper exposed in docstring (line 590). |
| `infographic_registry` (`parrot/models/infographic_templates.py:471`) | uses | Template lookup for validation + render. |
| `theme_registry` (`parrot/models/infographic.py:863`) | uses | Theme validation. |
| `PandasAgent.ask` (`parrot/bots/data.py`) | modifies | Post-loop branch detecting `InfographicRenderResult` (~30 lines, near `_rerun_for_map`). |
| `PandasAgent._inject_multi_data_from_variables` | uses | Already returns `response.data` as `List[DatasetResult.model_dump()]`. |
| `OutputMode` (`parrot/models/outputs.py`) | extends | New `INFOGRAPHIC` enum value. |
| `AIMessage` (`parrot/models/responses.py:72`) | extends | New `artifact_id: Optional[str]` top-level field. |
| `InfographicTemplate` (`parrot/models/infographic_templates.py:47`) | extends | New `js_bundles: Optional[List[JSBundle]]` field. |
| `ArtifactStore` (`parrot/storage/artifacts.py:18`) | extends | New `get_public_url(...)` method (S3 sigv4, 7-day max). |
| `OverflowStore` (`parrot/storage/overflow.py`) | extends | Expose signed-URL generation delegated to backend (S3). |
| `AgentTalk._format_response` (`parrot/handlers/agent.py`) | modifies | Add `OutputMode.INFOGRAPHIC` formatter branch; force-disable streaming. |
| `AgentTalk.post` (`parrot/handlers/agent.py`) | modifies | Inject `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` when `output_mode == 'infographic'`. |
| `ArtifactDetailView.get` (`parrot/handlers/artifacts.py`) | modifies | Accept `?format=html` / `Accept: text/html`; emit CSP headers. |
| `OUTPUT_SYSTEM_PROMPT` (`parrot/bots/prompts/__init__.py`) | extends | New `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` template. |
| `BasicAgent` (hosts `get_infographic`) | extends | New `enhance_infographic` method. |
| `ArtifactType` (`parrot/storage/models.py`) | uses | Reuses existing `ArtifactType.INFOGRAPHIC` (confirmed at `handlers/infographic.py:201`). |

### Data Models

```python
# --- New: parrot/tools/infographic_toolkit.py ---

class InfographicRenderResult(BaseModel):
    """Envelope returned by InfographicToolkit.render with return_direct=True.

    Consumed by PandasAgent.ask()'s post-loop branch via isinstance check.
    """
    artifact_id: str
    html_url: str
    html_inline: Optional[str] = None  # None when len(html) >= 50_000
    template_name: str
    theme: Optional[str] = None
    data_variables: List[str] = Field(default_factory=list)
    enhanced: bool = False


class InfographicValidationError(Exception):
    """Structured error raised by the toolkit's validation pipeline.

    All errors carry a stable `code` and `detail` payload for client routing.
    """
    code: Literal[
        "TEMPLATE_UNKNOWN", "SLOT_MISSING", "SLOT_TYPE_MISMATCH",
        "SLOT_ITEM_COUNT_INVALID", "EXTRA_BLOCKS",
        "DATA_VAR_MISSING", "DATA_VAR_EMPTY",
        "THEME_INVALID", "ENHANCE_OUTPUT_INVALID",
    ]
    detail: Dict[str, Any]


# --- New: parrot/models/infographic.py (or new sibling module) ---

class JSBundle(BaseModel):
    """JavaScript bundle declared by an InfographicTemplate.

    The enhance prompt lists allowed bundles to the LLM; the HTML-serving
    CSP whitelists their origins (when scope='cdn') and SRI hashes.
    """
    name: str
    url: Optional[str] = None       # required when scope='cdn'
    inline: Optional[str] = None    # required when scope='inline'
    sri_hash: Optional[str] = None  # 'sha384-...' — required when scope='cdn'
    scope: Literal["inline", "cdn"] = "inline"


# --- Modified: parrot/models/infographic_templates.py ---

class InfographicTemplate(BaseModel):  # existing
    name: str
    description: str
    block_specs: List[BlockSpec]
    default_theme: Optional[str] = None
    js_bundles: Optional[List[JSBundle]] = None   # NEW (FEAT-197)


# --- Modified: parrot/models/responses.py ---

class AIMessage(BaseModel):                       # existing
    # ... existing fields ...
    artifacts: List[Dict[str, Any]] = Field(...)  # existing, untouched
    artifact_id: Optional[str] = None             # NEW (FEAT-197)


# --- Modified: parrot/models/outputs.py ---

class OutputMode(str, Enum):                      # existing
    DEFAULT = "default"
    JSON = "json"
    HTML = "html"
    TABLE = "table"
    MAP = "map"
    MSTEAMS = "msteams"
    TELEGRAM = "telegram"
    TERMINAL = "terminal"
    INFOGRAPHIC = "infographic"                   # NEW (FEAT-197)
```

### New Public Interfaces

```python
# --- New: parrot/tools/infographic_toolkit.py ---

class InfographicToolkit(AbstractToolkit):
    """Toolkit producing frozen, multi-dataset HTML infographic artifacts."""
    return_direct: bool = True                     # the no-summarization lever
    tool_prefix: Optional[str] = "infographic"
    prefix_separator: str = "_"
    exclude_tools: tuple[str, ...] = ()

    def __init__(self, *, artifact_store: ArtifactStore, **kwargs) -> None: ...

    async def render(                              # tool name: infographic_render
        self,
        template_name: str,
        theme: Optional[str],
        mode: Literal["deterministic", "enhance"],
        blocks: List[Dict[str, Any]],              # raw dicts; coerced to InfographicBlock
        data_variables: List[str],
        enhance_brief: Optional[str] = None,
    ) -> InfographicRenderResult: ...

    async def list_templates(self) -> List[Dict[str, str]]: ...      # tool: infographic_list_templates
    async def get_template_contract(self, template_name: str) -> Dict[str, Any]: ...  # tool: infographic_get_template_contract
    async def validate_blocks(self, template_name: str, blocks: List[Dict[str, Any]]) -> Dict[str, Any]: ...  # tool: infographic_validate_blocks


# --- New method on the agent class that hosts get_infographic ---

async def enhance_infographic(
    self,
    *,
    skeleton: str,
    brief: str,
    data_context: Dict[str, Any],         # JSON-serialized DataFrames keyed by data_variable name
    js_bundles_available: List[JSBundle],
) -> str: ...                              # returns enhanced HTML (validated by caller)


# --- New method on ArtifactStore ---

async def get_public_url(
    self,
    user_id: Union[str, int],
    agent_id: str,
    session_id: str,
    artifact_id: str,
    *,
    format: Literal["html", "json"] = "html",
) -> str: ...                              # returns sigv4 presigned URL; max 7 days
```

---

## 3. Module Breakdown

> One module per New Capability from the brainstorm. Dependencies between
> modules drive task ordering in `/sdd-task`.

### Module 1: `infographic-toolkit`
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
- **Responsibility**: Define `InfographicToolkit(AbstractToolkit)`,
  `InfographicRenderResult`, `InfographicValidationError`, and the four
  tools (`render`, `list_templates`, `get_template_contract`,
  `validate_blocks`). Implement the deterministic guard pipeline (template,
  positional block, data-variable, theme, extra-blocks validation).
- **Depends on**: existing `parrot.tools.toolkit.AbstractToolkit`;
  `parrot.models.infographic_templates.infographic_registry`;
  `parrot.models.infographic.theme_registry`;
  `parrot.outputs.formats.infographic_html.InfographicHTMLRenderer`;
  Module 4 (`ArtifactStore.get_public_url`).
  Module 7 (`InfographicTemplate.js_bundles` — read-only consumer).

### Module 2: `infographic-enhance-pipeline`
- **Path**: extends `packages/ai-parrot/src/parrot/bots/agent.py` (or the
  same class hosting `bot.get_infographic` — Claude Code locates) and
  `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` (new
  `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` + enhance prompt template).
- **Responsibility**: New `enhance_infographic(skeleton, brief, data_context,
  js_bundles_available)` agent method. New post-output HTML validation
  utility: parses HTML and rejects any `<script src>` or
  `<link rel="stylesheet" href>` not in the `js_bundles_available` SRI
  whitelist.
- **Depends on**: Module 7 (`JSBundle`); existing `AbstractClient.ask`.

### Module 3: `pandas-agent-infographic-integration`
- **Path**: modifies `packages/ai-parrot/src/parrot/bots/data.py`
  (`PandasAgent.ask` post-loop branch, ~30 lines near `_rerun_for_map`).
- **Responsibility**: Detect `InfographicRenderResult` via isinstance,
  invoke `_inject_multi_data_from_variables`, populate `response.output`,
  `response.output_mode`, `response.artifact_id`, and bypass the formatter
  + structured-output reformat path.
- **Depends on**: Module 1 (imports `InfographicRenderResult`); Module 6
  (`AIMessage.artifact_id`); Module 8 (`OutputMode.INFOGRAPHIC`).

### Module 4: `artifact-public-url`
- **Path**: extends `packages/ai-parrot/src/parrot/storage/artifacts.py`
  (`ArtifactStore.get_public_url`) and
  `packages/ai-parrot/src/parrot/storage/overflow.py` (expose signed-URL
  generation on `OverflowStore`, delegating to S3 backend's
  `generate_presigned_url`).
- **Responsibility**: Produce a sigv4 presigned URL for the artifact's
  frozen HTML; signature-only authorization; max 7-day validity.
- **Depends on**: existing S3 client in the overflow store.

### Module 5: `artifact-html-serving`
- **Path**: modifies `packages/ai-parrot/src/parrot/handlers/artifacts.py`
  (`ArtifactDetailView.get` + new public-URL route handler).
- **Responsibility**: Accept `?format=html` / `Accept: text/html`; return
  `definition.html` with full CSP headers (`script-src 'self' 'unsafe-inline'
  <cdn-origins-from-js_bundles>`, `frame-ancestors <env-list>`, plus
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`).
  Read `INFOGRAPHIC_FRAME_ANCESTORS` from env (CSV, default `'self'`).
  Register the new public route `/api/v1/artifacts/public/{signature}/{artifact_id}.html`.
- **Depends on**: Module 4 (signature validation).

### Module 6: `aimessage-artifact-id-field`
- **Path**: modifies `packages/ai-parrot/src/parrot/models/responses.py`
  (`AIMessage` at line 72).
- **Responsibility**: Add `artifact_id: Optional[str] = None` as a
  top-level field. Existing `artifacts: List[Dict[str, Any]]` (line 206)
  remains untouched.
- **Depends on**: none.

### Module 7: `infographic-template-js-bundles`
- **Path**: modifies `packages/ai-parrot/src/parrot/models/infographic_templates.py`
  (`InfographicTemplate`); adds `JSBundle` to `parrot/models/infographic.py`
  (or a new sibling).
- **Responsibility**: Add `js_bundles: Optional[List[JSBundle]]` field.
  Update the seven built-in templates if any need declared bundles
  (deferred — they remain `None` until any template needs charts).
- **Depends on**: none.

### Module 8: `output-mode-infographic`
- **Path**: modifies `packages/ai-parrot/src/parrot/models/outputs.py`
  (adds `INFOGRAPHIC` enum value); modifies
  `packages/ai-parrot/src/parrot/handlers/agent.py` (adds
  `OutputMode.INFOGRAPHIC` branch in `_format_response`; injects
  `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` in `post()`; force-disables streaming
  when this mode is requested). Adds `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` to
  `parrot/bots/prompts/__init__.py`.
- **Responsibility**: Canonical type-safe signal for HTTP clients +
  system-prompt addendum.
- **Depends on**: Module 6 (`AIMessage.artifact_id` is surfaced in the
  formatter branch's response metadata).

### Module 9: `example-skill-financial-projection-variance`
- **Path**: `AGENTS_DIR/<agent>/skills/financial_projection_variance.md`
  (per-agent location).
- **Responsibility**: Reference skill demonstrating the contract —
  frontmatter `triggers: ['/financial_variance']`, body describing the
  queries to execute, the DataFrames to compute, and the mandatory
  closing `infographic_render(...)` call.
- **Depends on**: Modules 1, 2, 7.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_toolkit_return_direct_true` | 1 | `InfographicToolkit.return_direct` is `True`; generated `ToolkitTool` instances propagate the flag (verify `tool.return_direct`). |
| `test_render_template_unknown` | 1 | Unknown `template_name` raises `InfographicValidationError(code='TEMPLATE_UNKNOWN')`. |
| `test_render_slot_missing` | 1 | A required `BlockSpec` with no block at its position raises `SLOT_MISSING`. |
| `test_render_slot_type_mismatch` | 1 | A block whose `.type` doesn't match the spec's `block_type.value` raises `SLOT_TYPE_MISMATCH`. |
| `test_render_slot_item_count_invalid` | 1 | `min_items` / `max_items` violations on hero_cards / bullet lists raise `SLOT_ITEM_COUNT_INVALID`. |
| `test_render_extra_blocks_rejected` | 1 | More blocks than `block_specs` length raises `EXTRA_BLOCKS` (brainstorm decision). |
| `test_render_data_var_missing` | 1 | Missing `data_variables` entry in `pandas_tool.locals` raises `DATA_VAR_MISSING`. |
| `test_render_data_var_empty` | 1 | Present but empty/non-DataFrame raises `DATA_VAR_EMPTY`. |
| `test_render_theme_invalid` | 1 | Unknown theme raises `THEME_INVALID`. |
| `test_render_deterministic_skeleton_returned` | 1 | `mode="deterministic"` returns `InfographicRenderResult` with `enhanced=False`; `html_inline` populated when `len(html) < 50_000`. |
| `test_render_html_inline_truncated_when_large` | 1 | When `len(html) >= 50_000`, `html_inline` is `None`. |
| `test_render_artifact_persisted` | 1 | `ArtifactStore.save_artifact` invoked exactly once with `ArtifactType.INFOGRAPHIC` and `definition.html` populated. |
| `test_enhance_strips_external_script` | 2 | Enhanced HTML with `<script src="https://malicious">` triggers `ENHANCE_OUTPUT_INVALID` and the toolkit falls back to the skeleton (verify final `enhanced=False`). |
| `test_enhance_allows_sri_whitelisted_cdn` | 2 | `<script src>` whose origin + SRI hash matches a `JSBundle` in `js_bundles` is accepted. |
| `test_enhance_rejects_external_stylesheet` | 2 | `<link rel="stylesheet" href="https://...">` external raises `ENHANCE_OUTPUT_INVALID`. |
| `test_pandasagent_post_loop_detects_envelope` | 3 | `InfographicRenderResult` as last tool result causes `response.output_mode == OutputMode.INFOGRAPHIC`; formatter is NOT called; structured-reformat is skipped. |
| `test_pandasagent_inject_multi_data` | 3 | `response.data` is populated as `List[DatasetResult.model_dump()]` for every name in `data_variables`. |
| `test_pandasagent_artifact_id_propagated` | 3 | `response.artifact_id == envelope.artifact_id`. |
| `test_artifactstore_get_public_url_sigv4` | 4 | Returned URL is a valid sigv4 presigned URL with `X-Amz-Expires <= 604800` (7 days). |
| `test_artifactstore_get_public_url_no_user_scope` | 4 | URL does not embed `user_id`; signature alone authorizes. |
| `test_artifact_html_serving_csp_headers` | 5 | Response includes `Content-Security-Policy` with `frame-ancestors <env-list>`, `default-src 'self'`, `script-src 'self' 'unsafe-inline' <cdn-origins>`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. |
| `test_artifact_html_serving_frame_ancestors_env` | 5 | `INFOGRAPHIC_FRAME_ANCESTORS=https://a.example,https://b.example` produces `frame-ancestors https://a.example https://b.example`. |
| `test_artifact_html_serving_default_self` | 5 | Without env var, `frame-ancestors` defaults to `'self'`. |
| `test_artifact_html_serving_signature_invalid` | 5 | Tampered signature → 403; signed URL > 7 days old → 403 (sigv4 expiry). |
| `test_aimessage_artifact_id_optional_field` | 6 | `AIMessage(artifact_id=None)` validates; `AIMessage(artifact_id="x")` round-trips. |
| `test_aimessage_artifacts_list_untouched` | 6 | The existing `artifacts: List[Dict]` field is independent of `artifact_id`. |
| `test_js_bundle_validation` | 7 | `JSBundle(scope='cdn', url=None)` and `JSBundle(scope='cdn', sri_hash=None)` fail validation (model validators). |
| `test_template_with_js_bundles_serializes` | 7 | `InfographicTemplate.model_dump()` round-trips `js_bundles`. |
| `test_output_mode_infographic_enum` | 8 | `OutputMode("infographic") == OutputMode.INFOGRAPHIC`. |
| `test_format_response_infographic_branch` | 8 | `_format_response` for `OutputMode.INFOGRAPHIC` produces the documented JSON shape and emits `Content-Type: text/html` for `Accept: text/html`. |
| `test_streaming_disabled_for_infographic` | 8 | A request with `output_mode=infographic` and `stream=true` returns a non-streamed final envelope. |
| `test_system_prompt_addon_injected` | 8 | `AgentTalk.post` with `output_mode=infographic` injects `INFOGRAPHIC_SYSTEM_PROMPT_ADDON`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_slash_skill_end_to_end` | `/financial_variance Q4 2025` flows from `AgentTalk.post` → middleware → LLM tool loop (mocked) → `infographic_render` → artifact persisted → JSON envelope returned with `output_mode=infographic`, `data: List[DatasetResult]`, `metadata.artifact_id`. |
| `test_e2e_output_mode_request` | `POST /api/v1/agents/talk/{id}` with `output_mode=infographic` (no skill) produces the system-prompt addendum and an envelope of the same shape. |
| `test_e2e_html_serving` | `GET /api/v1/artifacts/public/{sig}/{artifact_id}.html` returns the frozen HTML with the documented CSP headers. |
| `test_e2e_enhance_fallback` | An enhance LLM call returns malicious HTML; the final envelope's HTML is the deterministic skeleton (`enhanced=False`). |
| `test_e2e_validation_error_surfaced` | `SLOT_TYPE_MISMATCH` from the toolkit surfaces immediately to the client as a structured error envelope; no retry loop. |
| `test_e2e_legacy_get_infographic_untouched` | `POST /api/v1/agents/infographic/{id}` still works unchanged (regression guard). |

### Test Data / Fixtures

```python
@pytest.fixture
def financial_variance_template():
    """Concrete InfographicTemplate exercising hero_card + chart positional slots."""
    return InfographicTemplate(
        name="financial_projection_variance",
        description="4 hero cards + 2 DoD bar charts + 1 cumulative line chart",
        block_specs=[
            BlockSpec(block_type=BlockType.HERO_CARD, min_items=4, max_items=4),
            BlockSpec(block_type=BlockType.CHART, required=True),
            BlockSpec(block_type=BlockType.CHART, required=True),
            BlockSpec(block_type=BlockType.CHART, required=True),
        ],
        default_theme="dark",
        js_bundles=[
            JSBundle(name="echarts", url="https://cdn.example/echarts.min.js",
                     sri_hash="sha384-AAAA...", scope="cdn"),
        ],
    )

@pytest.fixture
def sample_dataframes():
    """Three small DataFrames mimicking daily revenue, daily EBITDA, cumulative revenue."""
    ...

@pytest.fixture
def fake_artifact_store(monkeypatch):
    """In-memory ArtifactStore with a `get_public_url` that returns a sentinel URL."""
    ...

@pytest.fixture
def mock_llm_enhance(monkeypatch):
    """Stub AbstractClient.ask returning user-controlled enhanced HTML for the enhance pass."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests above pass: `pytest packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py -v` and the per-module test files for Modules 2–8.
- [ ] All integration tests above pass: `pytest packages/ai-parrot/tests/integration/test_infographic_e2e.py -v`.
- [ ] `mypy --strict` clean on the new toolkit module and the modified modules (Modules 1–8).
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` is clean.
- [ ] Existing `POST /api/v1/agents/infographic/{id}` integration tests still pass — **no breaking changes** to `bot.get_infographic()` or `InfographicTalk`.
- [ ] `OutputMode` exports `INFOGRAPHIC` and `_format_response` handles it.
- [ ] `AIMessage.artifact_id` is `Optional[str]` and round-trips through Pydantic.
- [ ] `InfographicTemplate.js_bundles` is optional and round-trips through Pydantic.
- [ ] `ArtifactStore.get_public_url` produces a sigv4 presigned URL whose `X-Amz-Expires` ≤ `604800` (7 days).
- [ ] Signed URL is signature-only (no `user_id` embedded in the path or query).
- [ ] The HTML-serving endpoint emits the full CSP header set (`default-src 'self'`, `script-src 'self' 'unsafe-inline' <CDN origins from js_bundles>`, `style-src 'self' 'unsafe-inline'`, `frame-ancestors <env list>`, `img-src 'self' data:`), plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
- [ ] `INFOGRAPHIC_FRAME_ANCESTORS` env var is read at request time; default `'self'` when unset.
- [ ] Streaming is disabled for `output_mode=infographic` — the final non-streamed envelope carries the URL.
- [ ] When `len(html) >= 50_000`, `html_inline` is `None` and `output` in the JSON envelope is the `html_url` (no 413).
- [ ] Validation errors (`TEMPLATE_UNKNOWN`, `SLOT_*`, `DATA_VAR_*`, `THEME_INVALID`, `EXTRA_BLOCKS`) surface immediately to the user with a structured error code and detail payload — no LLM retry loop.
- [ ] `mode="enhance"` falls back silently to the deterministic skeleton on `ENHANCE_OUTPUT_INVALID`, and the security event is logged via `self.logger.warning(...)`.
- [ ] The example skill `financial_projection_variance.md` ships under `AGENTS_DIR/<agent>/skills/` and triggers via `/financial_variance`.
- [ ] No new pip dependencies added to `packages/ai-parrot/pyproject.toml`.
- [ ] Documentation updated in `docs/` (toolkit reference + CSP / signed-URL operations notes).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying via `grep` or `Read`.

### Verified Imports

```python
# All imports below were verified against the codebase on 2026-05-28.
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool
# verified: parrot/tools/toolkit.py:191 (AbstractToolkit), :32 (ToolkitTool)

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
# verified: imported at parrot/tools/toolkit.py:25

from parrot.models.infographic import (
    InfographicBlock,        # parrot/models/infographic.py:634
    InfographicResponse,     # parrot/models/infographic.py:657
    BlockType, ChartType,    # parrot/models/infographic.py:45, :64
    theme_registry,          # parrot/models/infographic.py:863
)

from parrot.models.infographic_templates import (
    BlockSpec,                       # parrot/models/infographic_templates.py:21
    InfographicTemplate,             # parrot/models/infographic_templates.py:47
    infographic_registry,            # parrot/models/infographic_templates.py:471
)

from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
# verified: parrot/outputs/formats/infographic_html.py:582

from parrot.storage.artifacts import ArtifactStore
# verified: parrot/storage/artifacts.py:18

from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator
# verified (in use): parrot/handlers/infographic.py:201

from parrot.models.outputs import OutputMode
# verified (in use): parrot/bots/data.py:25
# Existing values: DEFAULT, JSON, HTML, TABLE, MAP, MSTEAMS, TELEGRAM, TERMINAL
# This feature adds: INFOGRAPHIC

from parrot.skills.middleware import create_skill_trigger_middleware
# verified: parrot/skills/middleware.py:16

from parrot.skills.mixin import SkillRegistryMixin
# verified: parrot/skills/mixin.py:27

from parrot.skills.file_registry import SkillFileRegistry
# verified (in use): parrot/skills/mixin.py:150
```

### Existing Class Signatures

```python
# parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                  # line 191
    return_direct: bool = False                              # line 220 — KEY LEVER
    exclude_tools: tuple[str, ...] = ()                      # line 228
    tool_prefix: Optional[str] = None                        # line 242
    prefix_separator: str = "_"                              # line 245

    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...      # line 306
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any: ...  # line 321
    def get_tools(self, ...) -> List[AbstractTool]: ...                       # line 337
    def _generate_tools(self) -> None: ...                                    # line 390

# parrot/tools/toolkit.py
class ToolkitTool(AbstractTool):                                              # line 32
    # __init__ stores bound_method; propagates return_direct from the toolkit
    # at lines 508-517 (verified via brainstorm).
```

```python
# parrot/models/infographic.py
class ChartBlock(BaseModel):                                                  # line 353
    type: Literal["chart"] = "chart"
    chart_type: ChartType
    title: Optional[str]
    description: Optional[str]
    labels: List[str]
    series: List[ChartDataSeries]
    x_axis_label: Optional[str]
    y_axis_label: Optional[str]
    stacked: Optional[bool] = False
    show_legend: Optional[bool] = True

InfographicBlock = Union[                                                     # line 634
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, BulletListBlock,
    TableBlock, ImageBlock, QuoteBlock, CalloutBlock, DividerBlock,
    TimelineBlock, ProgressBlock, AccordionBlock, ChecklistBlock, TabViewBlock,
]

class InfographicResponse(BaseModel):                                         # line 657
    template: Optional[str]
    theme: Optional[str]
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]]
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ThemeRegistry:                                                          # line 799
    def register(self, theme: ThemeConfig) -> None: ...
    def get(self, name: str) -> ThemeConfig: ...                              # raises KeyError (line 817)
    def list_themes(self) -> List[str]: ...

theme_registry = ThemeRegistry()                                              # line 863
# Built-in themes: light, dark, corporate, midnight (lines 867-929)
```

```python
# parrot/models/infographic_templates.py
class BlockSpec(BaseModel):                                                   # line 21
    block_type: BlockType                                                     # line 27
    required: bool = True
    description: Optional[str] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    constraints: Optional[Dict[str, str]] = Field(default_factory=dict)

class InfographicTemplate(BaseModel):                                         # line 47
    name: str
    description: str
    block_specs: List[BlockSpec]                                              # line 51 — positional contract
    default_theme: Optional[str] = None
    def to_prompt_instruction(self) -> str: ...                               # line 60

class InfographicTemplateRegistry:                                            # line 398
    def register(self, template: InfographicTemplate) -> None: ...
    def get(self, name: str) -> InfographicTemplate: ...                      # raises KeyError (line 441)
    def list_templates(self) -> List[str]: ...
    def list_templates_detailed(self) -> List[Dict[str, str]]: ...

infographic_registry = InfographicTemplateRegistry()                          # line 471
```

```python
# parrot/outputs/formats/infographic_html.py
class InfographicHTMLRenderer(BaseRenderer):                                  # line 582
    """Renders InfographicResponse as a self-contained HTML5 document."""

    def __init__(self) -> None: ...                                           # line 594
    async def render(                                                          # line 617
        self,
        response: Any,
        environment: str = 'terminal',
        export_format: str = 'html',
        include_code: bool = False,
        **kwargs,
    ) -> Tuple[str, Optional[Any]]: ...
    # Sync helper for direct use (per docstring example at line 590):
    # html = renderer.render_to_html(infographic_response, theme="dark")
```

```python
# parrot/storage/artifacts.py
class ArtifactStore:                                                          # line 18
    def __init__(self, dynamodb: ConversationBackend, s3_overflow: OverflowStore) -> None: ...
    async def save_artifact(self, user_id, agent_id, session_id, artifact: Artifact) -> None: ...  # line 30
    async def get_artifact(self, user_id, agent_id, session_id, artifact_id) -> Optional[Artifact]: ...  # line 58
    async def list_artifacts(self, user_id, agent_id, session_id) -> List[ArtifactSummary]: ...
    async def update_artifact(self, ...) -> None: ...
    async def delete_artifact(self, ...) -> bool: ...
    # NEW (FEAT-197, this spec):
    # async def get_public_url(self, user_id, agent_id, session_id,
    #                          artifact_id, *, format='html') -> str: ...

# OverflowStore.maybe_offload(definition, key_prefix) -> (inline, ref)
# parrot/storage/artifacts.py:55 — handles HTML > inline threshold automatically.
```

```python
# parrot/bots/data.py
class PandasAgent(BasicAgent):
    DEFAULT_MAX_ITERATIONS = 10                                    # ~line 520
    _prompt_builder = _build_pandas_prompt_builder()               # ~line 525

    async def ask(self, question, ...) -> AIMessage: ...           # ~line 800
    async def _rerun_for_map(self, *, client, question, ...): ...  # PATTERN TO REPLICATE
    async def _inject_multi_data_from_variables(
        self, response: AIMessage, data_variables: List[str],
    ) -> List[str]: ...    # populates response.data as List[DatasetResult.model_dump()]
    async def _inject_data_from_variable(self, response, data_variable: str): ...
    def _get_python_pandas_tool(self) -> Optional[PythonPandasTool]: ...
    def _get_repl_locals(self) -> Dict[str, Any]: ...
```

```python
# parrot/handlers/agent.py
class AgentTalk(BaseView):
    async def post(self) -> web.Response: ...
    async def _format_response(self, response, output_format, format_kwargs,
                                user_id, user_session, response_time_ms,
                                agent_name, session_id, client_message_id) -> web.Response: ...
    # OutputMode branches live here — add OutputMode.INFOGRAPHIC alongside JSON/HTML/MAP
```

```python
# parrot/handlers/artifacts.py
class ArtifactDetailView(BaseView):
    async def get(self) -> web.Response: ...
    async def put(self) -> web.Response: ...
    async def delete(self) -> web.Response: ...
```

```python
# parrot/skills/middleware.py
def create_skill_trigger_middleware(                                          # line 16
    registry: SkillFileRegistry,
    bot: "AbstractBot",
    priority: int = -10,
) -> PromptMiddleware:
    # Logic at lines 40-68:
    # if not query.startswith("/"): return query
    # parts = query.split(None, 1); trigger = parts[0]; remaining = parts[1] if any
    # Reserved: /skills, /help → list skills
    # skill = registry.get(trigger); if skill: bot._active_skill = skill; return remaining
```

```python
# parrot/skills/mixin.py
class SkillRegistryMixin:                                                     # line 27
    skill_paths: List[Path] = []
    inject_skills_into_prompt: bool = True
    _skill_file_registry: Optional[SkillFileRegistry] = None
    _active_skill: Optional[SkillDefinition] = None

    async def _configure_skill_file_registry(self) -> None:                   # line 139
        # Loads .md skills from AGENTS_DIR/<agent>/skills/
        # Registers create_skill_trigger_middleware in bot._prompt_pipeline (line 178)
```

```python
# parrot/bots/abstract.py
# _build_request_prompt() — lines 2613-2640
# When self._active_skill is not None, injects a transient PromptLayer:
#   priority=90 (after CUSTOM(80)), phase=RenderPhase.REQUEST
#   template = self._active_skill.template_body
# After build: prompt_builder.remove("skill_active"); self._active_skill = None
```

```python
# parrot/models/responses.py
class AIMessage(BaseModel):                                                   # line 72
    input: str
    output: Any
    response: Optional[str] = None
    data: Optional[Any] = None
    code: Optional[str] = None
    images: Optional[List[Path]] = Field(default_factory=list)
    media: Optional[List[Path]] = Field(default_factory=list)
    files: Optional[List[Path]] = Field(default_factory=list)
    documents: Optional[List[Any]] = Field(default_factory=list)
    model: str
    provider: str
    usage: CompletionUsage
    # ...
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)             # line 206 — generic, untouched
    def add_artifact(self, artifact_type: str, content: Any, **metadata) -> None: ...  # line 271
    # NEW field added by Module 6:
    # artifact_id: Optional[str] = None
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `InfographicToolkit` | `AbstractToolkit` | subclass | parrot/tools/toolkit.py:191 |
| `InfographicToolkit.render` (tool: `infographic_render`) | `infographic_registry.get` | method call | parrot/models/infographic_templates.py:471 |
| `InfographicToolkit.render` | `theme_registry.get` | method call | parrot/models/infographic.py:863 |
| `InfographicToolkit.render` | `InfographicHTMLRenderer` | composition | parrot/outputs/formats/infographic_html.py:582 |
| `InfographicToolkit.render` | `ArtifactStore.save_artifact` | method call | parrot/storage/artifacts.py:30 |
| `InfographicToolkit.render` | `ArtifactStore.get_public_url` (NEW) | method call | parrot/storage/artifacts.py (this feature) |
| `PandasAgent.ask` (post-loop) | `InfographicRenderResult` | isinstance check | parrot/tools/infographic_toolkit.py (this feature) |
| `PandasAgent.ask` (post-loop) | `_inject_multi_data_from_variables` | method call | parrot/bots/data.py |
| `AgentTalk.post` | `OUTPUT_SYSTEM_PROMPT` + `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` | string composition | parrot/bots/prompts/__init__.py (extends) |
| `AgentTalk._format_response` | `OutputMode.INFOGRAPHIC` | enum branch | parrot/models/outputs.py (extends) |
| `ArtifactDetailView.get` | `ArtifactStore.get_artifact` | method call | parrot/storage/artifacts.py:58 |
| Skill body (markdown) | `bot._active_skill` | template injection | parrot/bots/abstract.py:2613-2640 |
| `/financial_variance` trigger | `skill_trigger_middleware` | prompt pipeline | parrot/skills/middleware.py:40-68 |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.tools.infographic_toolkit.InfographicToolkit`~~ — created by this spec (Module 1).
- ~~`parrot.tools.infographic_toolkit.InfographicRenderResult`~~ — created by this spec (Module 1).
- ~~`parrot.tools.infographic_toolkit.InfographicValidationError`~~ — created by this spec (Module 1).
- ~~`BasicAgent.enhance_infographic`~~ — does not exist. `bot.get_infographic` exists but does NOT accept `enhance_skeleton` or `enhance_brief` parameters. Created by Module 2.
- ~~`ArtifactStore.get_public_url`~~ — created by this spec (Module 4).
- ~~`OutputMode.INFOGRAPHIC`~~ — created by this spec (Module 8). Existing values only: `DEFAULT`, `JSON`, `HTML`, `TABLE`, `MAP`, `MSTEAMS`, `TELEGRAM`, `TERMINAL`.
- ~~`AIMessage.artifact_id`~~ — does NOT exist as a top-level field. The generic `artifacts: List[Dict[str, Any]]` (line 206) and `add_artifact()` (line 271) ARE different things and remain untouched. Created by Module 6.
- ~~`BlockSpec.slot_id`~~ — does NOT exist and will NOT be added. Block identification is positional via `block_specs` order.
- ~~`InfographicTemplate.js_bundles`~~ — does NOT exist. Created by Module 7.
- ~~`JSBundle`~~ — model does NOT exist. Created by Module 7.
- ~~Public artifact URL route `/api/v1/artifacts/public/{...}`~~ — route does NOT exist. Registered by Module 5.
- ~~`!skill_name` parsing in `AgentTalk.post()`~~ — does NOT exist AND will NOT be added. Activation uses the existing `/trigger` SkillRegistry middleware (`parrot/skills/middleware.py:16`).
- ~~`INFOGRAPHIC_FRAME_ANCESTORS` env var~~ — does NOT exist. Introduced by Module 5.
- ~~`INFOGRAPHIC_SYSTEM_PROMPT_ADDON`~~ — does NOT exist. Introduced by Module 8.
- ~~Per-tenant CSP configuration~~ — out of scope for v1.
- ~~Re-rendering frozen HTML on demand from `definition.blocks`~~ — out of scope for v1. The HTML is stored as a frozen blob; legacy artifacts without `definition.html` may fall back to re-render but only for the legacy `_auto_save_infographic_artifact` path.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`AbstractToolkit` + `return_direct=True`**: the canonical lever to bypass
  LLM re-summarization. `ToolkitTool` propagates the flag automatically
  (`parrot/tools/toolkit.py:508-517`). No client-level changes.
- **`_rerun_for_map` pattern**: the post-loop branch in `PandasAgent.ask`
  follows the same shape — isinstance check on the last tool call's result,
  mutate `response` in place, return early. Place the new branch adjacent
  to it for reviewability.
- **Async-first throughout**: `render`, `enhance_infographic`,
  `get_public_url`, and the formatter branch are all async.
- **Logging with `self.logger`**: every validation failure, every enhance
  fallback, and every signed-URL issuance is logged at INFO; security
  events (`ENHANCE_OUTPUT_INVALID`) at WARNING.
- **Pydantic v2 models** for `InfographicRenderResult`, `JSBundle`, and
  validation error payloads. Use `model_validator` for `JSBundle`
  cross-field rules (`scope='cdn'` ⇒ `url` and `sri_hash` required;
  `scope='inline'` ⇒ `inline` required).
- **CSP via response headers** — not via `<meta http-equiv>` — so the
  policy is non-bypassable inside the iframe.
- **Reuse `OverflowStore.maybe_offload`** (`parrot/storage/artifacts.py:55`):
  it already handles the inline-vs-overflow threshold for `definition`
  payloads; the new `get_public_url` only adds the signed-URL emission.

### Known Risks / Gotchas

- **`return_direct=True` makes the toolkit responsible for any sensible
  output shape.** The LLM never gets a chance to apologize or reformat.
  All validation must be deterministic and the error envelope must be
  comprehensible to the *user*, not the LLM.
- **The skill `template_body` is injected as a transient `PromptLayer`
  per turn and cleared after the build.** Multi-turn dashboards that rely
  on the skill instructions surviving across turns would break — explicit
  invocation per turn is required (documented).
- **Multiple `infographic_render` calls in one turn**: only the last is
  inspected by the post-loop branch. Earlier calls' artifacts are still
  persisted (no orphan cleanup in v1). Documented; not engineered around.
- **S3 sigv4 max expiry is 7 days.** "Non-expiring URLs" are not literally
  achievable with sigv4. Acceptance criterion uses ≤ 604800 seconds.
  Clients that need permanence must call the session-scoped GET via
  `artifact_id`.
- **Streaming forcibly disabled** for `output_mode=infographic`. Clients
  that always set `stream=true` will receive a non-streamed envelope —
  document this in the API guide so client implementations don't assume
  a stream.
- **Concurrent renders in the same session** generate distinct `artifact_id`
  values (UUID-prefixed). Session-isolated `pandas_tool` clones (existing
  `AgentTalk` pattern) prevent DataFrame name collisions.
- **Legacy infographic artifacts** saved by the older
  `_auto_save_infographic_artifact` path do NOT carry `definition.html`.
  The HTML-serving endpoint falls back to re-rendering from
  `definition.blocks` for those, but the new path always populates
  `definition.html`. Tests must cover both branches of the serving
  endpoint.
- **CSP `script-src 'unsafe-inline'`** is required for the enhance JS.
  Mitigation: external scripts are restricted to the `js_bundles` SRI
  whitelist, validated by the HTML post-output check before the artifact
  is persisted.
- **Sync-down workflow (FEAT-187) is on.** This feature lands on `dev`;
  no special handling needed unless a release freeze is announced
  (which would switch `base_branch` to `staging`).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none new) | — | All capabilities use existing dependencies: `pydantic` v2, `aiohttp`, `boto3` (for sigv4 signed URLs via the existing S3 overflow store), `markdown_it` (already used by `InfographicHTMLRenderer`), `html.parser` (stdlib) or `lxml` (already in `pyproject.toml` if present — verify) for enhance HTML validation. |

---

## 8. Open Questions

> All 13 brainstorm questions resolved before this spec was drafted.
> No new blocking questions surfaced during codebase research.
> Items below are echoed for the audit trail.

- [x] Should `mode="enhance"` fall back silently to the deterministic
  skeleton on enhance LLM validation failure? — *Resolved in brainstorm
  (Owner: Jesus)*: yes — fall back silently and log a WARNING-level
  security event. Reflected in §2 (Step 5 of Internal Behavior in
  brainstorm; new path in Module 2) and §5 (acceptance criterion).
- [x] Are extra blocks beyond `block_specs` length silently ignored, or
  rejected with `EXTRA_BLOCKS`? — *Resolved in brainstorm (Owner: Jesus)*:
  rejected with `EXTRA_BLOCKS`. Reflected in §4 (`test_render_extra_blocks_rejected`).
- [x] Single-turn LLM retry on `SLOT_TYPE_MISMATCH` / `DATA_VAR_MISSING`? —
  *Resolved in brainstorm Round 1 (Owner: Jesus)*: no retry — surface
  immediately to the user. Reflected in §1 Non-Goals and §5.
- [x] `InfographicTemplate.js_bundles` shape — *Resolved in brainstorm
  Round 2 (Owner: Jesus)*: `Optional[List[JSBundle]]` where `JSBundle` is
  `{name, url, inline, sri_hash, scope}`. Reflected in §2 Data Models and
  §3 Module 7.
- [x] Signed-URL signing mechanism — *Resolved in brainstorm (Owner: Jesus)*:
  S3 sigv4 presigned URL, max 7 days, signature-only auth. Reflected in
  §3 Module 4 and §5.
- [x] `!skill_name` parsing vs. existing SkillRegistry — *Resolved in
  brainstorm Round 1 (Owner: Jesus)*: use the existing `/trigger`
  middleware (`parrot/skills/middleware.py:16-74`). No new parsing in
  `AgentTalk.post()`. Reflected in §1 Non-Goals, §2 Component Diagram,
  and §6 (verified imports).
- [x] `InfographicHTMLRenderer` location and public API — *Resolved by
  codebase verification (Owner: Claude Code)*: lives at
  `parrot/outputs/formats/infographic_html.py:582`, subclass of
  `BaseRenderer`; async `render()` at line 617; sync helper
  `render_to_html(infographic_response, theme=...)` per docstring example
  (line 590). Reflected in §6.
- [x] Streaming behavior with `output_mode=infographic` — *Resolved in
  brainstorm (Owner: Jesus)*: disable streaming; final non-streamed
  envelope carries the URL. Reflected in §1 Non-Goals, §3 Module 8, §5.
- [x] Auth scope of signed URLs — *Resolved in brainstorm (Owner: Jesus)*:
  signature-only for v1 (no `user_id` embedded). Reflected in §1
  Non-Goals and §5.
- [x] Iframe CSP — *Resolved in brainstorm Round 1 + Round 2
  (Owner: Jesus)*: strict CSP with `frame-ancestors` whitelisted via
  env var `INFOGRAPHIC_FRAME_ANCESTORS` (CSV, default `'self'`).
  Reflected in §3 Module 5 and §5.
- [x] JSON envelope when `html_inline` is `None` — *Resolved in
  brainstorm Round 2 (Owner: Jesus)*: `output: <html_url>` + metadata,
  no 413. Reflected in §3 Module 8 and §5.
- [x] Skill storage location — *Resolved in brainstorm Round 2
  (Owner: Jesus)*: per-agent at `AGENTS_DIR/<agent>/skills/`. Reflected
  in §3 Module 9.
- [x] `AIMessage.artifact_id` shape — *Resolved in brainstorm Round 1
  (Owner: Jesus)*: dedicated top-level field; generic `artifacts: List[Dict]`
  remains untouched. Reflected in §2 Data Models, §3 Module 6, and §6.

---

## Worktree Strategy

- **Default isolation unit**: `mixed`.
- **Rationale**: The 9 modules split into four largely-independent work
  units, but two pairs share a class boundary that benefits from
  intra-worktree co-development:
  1. **Cluster A — Storage + HTTP + OutputMode** (Modules 4, 5, 8). All
     touch `handlers/agent.py`, `handlers/artifacts.py`, `storage/*`,
     `models/outputs.py`, `bots/prompts/__init__.py`. Logical grouping.
  2. **Cluster B — Toolkit + JSBundle** (Modules 1, 7). Module 1 imports
     `JSBundle` from Module 7 read-only; co-develop in one worktree.
  3. **Cluster C — Enhance pipeline** (Module 2). Independent.
  4. **Cluster D — PandasAgent integration + AIMessage** (Modules 3, 6).
     Module 3 imports `InfographicRenderResult` from Cluster B; merge
     Cluster B first, then Cluster D.
  5. **Cluster E — Example skill** (Module 9). Authored after Clusters
     A–D are validated; tiny, no worktree needed.
- **Cross-feature dependencies**: monitor FEAT-196 (`agentsflow-migration`)
  for collisions in `bots/data.py` (`PandasAgent.ask`) and
  `handlers/agent.py` (`_format_response` / `post`). Coordinate merge
  order if both touch those files in overlapping regions.
- **Recommended PR order**: B → D → A → C → E (toolkit publishes the
  envelope class before its consumer; storage/HTTP next; enhance and
  skill last).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-28 | Jesus | Initial draft. Carries forward brainstorm `infographictoolkit.brainstorm.md` with all 13 resolved questions; Recommended Option B; codebase contract re-verified against `dev` HEAD at commit time. |

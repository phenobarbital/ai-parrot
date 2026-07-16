---
type: Wiki Overview
title: 'Feature Specification: Infographic Toolkit — Single-Turn Interactive HTML
  Artifacts'
id: doc:sdd-specs-infographictoolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Generating an infographic today is a two-step user-visible flow: the user
  asks'
relates_to:
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.models.infographic_templates
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats.infographic_html
  rel: mentions
- concept: mod:parrot.skills.file_registry
  rel: mentions
- concept: mod:parrot.skills.middleware
  rel: mentions
- concept: mod:parrot.skills.mixin
  rel: mentions
- concept: mod:parrot.storage.artifacts
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
---

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
**Status**: approved
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

…(truncated)…

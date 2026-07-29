---
type: Wiki Overview
title: 'Brainstorm: Infographic Toolkit — Single-Turn Interactive HTML Artifacts'
id: doc:sdd-proposals-infographictoolkit-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Generating an infographic today is a two-step user-visible flow:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.models.infographic_templates
  rel: mentions
- concept: mod:parrot.models.outputs
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
type: feature
base_branch: dev
---

# Brainstorm: Infographic Toolkit — Single-Turn Interactive HTML Artifacts

**Date**: 2026-05-28
**Author**: Jesus
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

Generating an infographic today is a two-step user-visible flow:

1. The user asks the agent a question; the agent answers conversationally and computes the relevant DataFrames.
2. The user (or the client) issues a separate `POST /api/v1/agents/infographic/{agent_id}` call with a `query` and a `template` name. This second call disregards the DataFrames computed in step 1 — it re-generates everything from scratch via `bot.get_infographic()`.

This is wasteful (LLM cost, latency, duplicated data work) and prevents two capabilities the system should support:

- **Multi-dataset infographics with reactive interactivity.** A financial-variance dashboard is composed of three or four distinct DataFrames (revenue daily, EBITDA daily, cumulative revenue) feeding multiple slots (hero cards + bar charts + cumulative chart). The current single-pass `get_infographic` cannot ground the visualization on multiple pre-computed datasets, and it produces static HTML with no JavaScript interactivity. The visual the user shared in the brainstorm session — 4 hero cards + 2 bar charts (DoD) + 1 cumulative line chart — is exactly this kind of artifact and cannot be produced by the current flow.
- **Single-turn delivery of interactive HTML apps from a normal agent conversation.** The user should be able to write `!financial_variance Q4 2025` (or a natural-language equivalent) in chat and receive, in a single agent turn, both the underlying DataFrames (so they can be explored, exported, drilled into) AND the rendered interactive HTML artifact (so it can be viewed, shared via signed URL, or embedded as an iframe).

The core architectural problem: the agent's tool-calling loop normally treats tool outputs as material for further LLM summarization. An infographic HTML response must NOT be summarized, NOT converted to markdown, NOT re-formatted — it must be returned to the caller verbatim while still preserving the multi-dataset envelope so downstream consumers can use both the visual and the data.

## Constraints & Requirements

- **Multi-dataset preservation.** The response envelope must carry both the rendered HTML artifact AND the list of DataFrames (`DatasetResult` entries via `response.data`) that fed it. Existing consumers of `PandasAgentResponse.data_variables` continue to work unchanged.
- **Deterministic contracts, no fallback hallucination.** Validation of the LLM-produced blocks against the template's `BlockSpec` sequence must fail loudly with a structured error code (`SLOT_MISSING`, `SLOT_TYPE_MISMATCH`, `DATA_VAR_MISSING`, `THEME_INVALID`). No silent degradation, no "I'll try to render anyway".
- **No invasive changes to LLM clients.** The mechanism that prevents tool-result re-summarization must use the existing `AbstractToolkit.return_direct=True` lever. We do not modify `GoogleGenAIClient.ask`, `AnthropicClient.ask`, etc. — they already honor `return_direct`.
- **Reuse, do not duplicate.** All 15 existing block models (`TitleBlock`, `HeroCardBlock`, `ChartBlock`, `TableBlock`, etc.), `InfographicResponse`, `InfographicTemplate`, `BlockSpec`, `infographic_registry`, `theme_registry`, and the existing `InfographicHTMLRenderer` MUST be reused. No parallel hierarchy of block models.
- **Frozen HTML storage.** The artifact's HTML is stored as a frozen blob (in overflow storage). The artifact is self-contained: it carries the rendered HTML, the source blocks (for back-reference), the source DataFrames (serialized as `DatasetResult`), the template name, the theme, and the enhance flag. Re-rendering on demand from blocks is NOT implemented in v1.
- **Signed URLs without expiration.** The `ArtifactStore` must expose a method returning a signed URL to the stored HTML. URLs do not expire (per user decision).
- **Latency budget.** Deterministic mode (no enhance) must complete in the time of the underlying analysis + one additional render call (~100-300ms for render). Enhance mode adds a second LLM call and is acceptable to budget at 3-8s extra.
- **Explicit invocation only.** No automatic intent-detection heuristic in v1 (unlike the `_detect_map_intent` auto-switch in `PandasAgent.ask()`). The agent uses the toolkit only when the user explicitly invokes a `!skill_name` command, or when natural-language phrasing names the tool, or when the request specifies `output_mode=infographic`.
- **Backward compatibility.** The existing `POST /api/v1/agents/infographic/{agent_id}` endpoint and `bot.get_infographic()` method continue to work unchanged. The new pipeline coexists.

---

## Options Explored

### Option A: Toolkit pure (no `OutputMode.INFOGRAPHIC` wrapper)

`InfographicToolkit` is the single entry point. The agent calls `infographic_render(...)` as a tool; `return_direct=True` short-circuits the loop; `PandasAgent.ask()` detects the typed envelope and populates `response.output_mode` from a constant string `"infographic"` without an enum entry. The HTTP layer receives the envelope and serves whatever format the `Accept` header asks for.

✅ **Pros:**
- Minimal surface area: a single new component (the toolkit) plus a small post-loop branch in `PandasAgent.ask()`.
- No coupling to `OutputMode` enum or the formatter machinery.
- Easy to add to other agent subclasses by just registering the toolkit.

❌ **Cons:**
- HTTP clients have no canonical way to request an infographic without knowing about skills. The system prompt addendum that nudges the LLM toward calling the tool has nowhere natural to live (today, `OUTPUT_SYSTEM_PROMPT.format(output_mode=...)` is the established place).
- `_format_response` in `handlers/agent.py` already branches on `output_mode`; adding string-based detection for `"infographic"` outside the enum is inconsistent with `MAP`, `TABLE`, `MSTEAMS`, `TELEGRAM`.
- No principled way to disable infographic generation on a per-request basis from the HTTP layer without reaching into the toolkit.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Reuses existing `AbstractToolkit`, `InfographicHTMLRenderer`, `ArtifactStore`. |

🔗 **Existing Code to Reuse:**
- `parrot/tools/toolkit.py` — `AbstractToolkit`, `ToolkitTool`, `return_direct` mechanism.
- `parrot/models/infographic.py` — all 15 block models + `InfographicResponse`.
- `parrot/models/infographic_templates.py` — `infographic_registry`, `InfographicTemplate.to_prompt_instruction()`.
- `parrot/storage/artifacts.py` — `ArtifactStore.save_artifact()`.

---

### Option B: Toolkit + thin `OutputMode.INFOGRAPHIC` wrapper (RECOMMENDED)

Same toolkit as Option A, plus a new `OutputMode.INFOGRAPHIC` enum value that acts purely as a content-negotiation and system-prompt hint:

- When a request arrives with `output_mode=infographic`, the system prompt gets an addendum nudging the LLM to use `infographic_render`.
- When `PandasAgent.ask()` detects an `InfographicRenderResult` envelope in the last tool call, it sets `response.output_mode = OutputMode.INFOGRAPHIC` automatically (whether or not the client requested it).
- The HTTP layer in `_format_response` adds an `INFOGRAPHIC` branch that returns the HTML or the signed URL with the correct `Content-Type: text/html` header.

The `OutputMode.INFOGRAPHIC` is the canonical type-safe signal; the toolkit is the engine. They are complementary, not redundant: the toolkit can be invoked without setting the mode (via skill or natural language), and the mode can be requested without the toolkit firing (in which case the LLM falls back to the existing `get_infographic` HTTP path — graceful degradation).

✅ **Pros:**
- Consistent with the existing `OutputMode.MAP` pattern (Folium maps work the same way: explicit mode + tool-driven generation + post-loop detection).
- HTTP clients have a canonical, discoverable way to request an infographic without knowing about skills.
- `_format_response` keeps its enum-based branching; no string comparisons.
- System-prompt addendum has a natural home: `OUTPUT_SYSTEM_PROMPT.format(output_mode="infographic")` plus a dedicated addon.
- Easy to disable per-request from the HTTP layer (don't pass the mode).

❌ **Cons:**
- One additional surface to maintain (the enum value, the formatter branch, the addendum).
- Slight risk of confusion: the mode is a hint, not a guarantee. The actual rendering only happens if the LLM calls the tool. We document this clearly.

📊 **Effort:** Low (incrementally over Option A; ~30 lines extra)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | Same as Option A. |

🔗 **Existing Code to Reuse:**
- Everything from Option A, plus:
- `parrot/models/outputs.py` — `OutputMode` enum (location based on `from ..models.outputs import OutputMode` import in `bots/data.py:25`).
- `parrot/bots/prompts/__init__.py` — `OUTPUT_SYSTEM_PROMPT` template, referenced in `bots/data.py:1109`.
- `parrot/outputs/__init__.py` — `OutputFormatter`, referenced in `handlers/agent.py:421`.

---

### Option C: Skill + dedicated HTTP endpoint, no toolkit

A purely server-side composition: `POST /api/v1/agents/dashboard/{agent_id}` accepts a skill name and orchestrates the full flow externally (run queries → compute → invoke a private rendering helper → return HTML + datasets). The agent's tool-calling loop is bypassed entirely. The conversational `!skill_name` invocation is just a thin wrapper that calls this endpoint internally.

✅ **Pros:**
- No need to invent the `return_direct` envelope detection or modify `PandasAgent.ask()`.
- Simplest mental model: one HTTP endpoint, one outcome.

❌ **Cons:**
- Cannot ground the rendering on an arbitrary preceding conversation (the dashboard handler starts fresh each time).
- The LLM does not participate in building the blocks, which kills the "LLM-augmented JavaScript interactivity" capability from day one.
- Splits the codebase into two parallel orchestration systems: agent tool-calling for conversational flows, dedicated handler for dashboards. Long-term maintenance burden.
- Skills become endpoint configurations rather than prompt-injectable assets — incompatible with the existing ai-parrot SkillRegistry pattern.
- No path for the agent to combine "answer this question conversationally" with "and by the way, build a dashboard of this".

📊 **Effort:** Medium (new orchestration layer in handlers)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | — |

🔗 **Existing Code to Reuse:**
- `parrot/handlers/infographic.py` — pattern of dedicated HTTP handler with PBAC guard and auto-save artifact (`_auto_save_infographic_artifact`).

---

## Recommendation

**Option B** is recommended.

It is the only option that satisfies the full constraint set:

- The toolkit + `return_direct=True` lever solves the no-summarization requirement without touching any LLM client.
- The thin `OutputMode.INFOGRAPHIC` wrapper aligns with the existing `MAP`/`TABLE`/`MSTEAMS` pattern and keeps `_format_response` consistent.
- The single-pass flow preserves multi-dataset state (`data_variables` are still injected by `_inject_multi_data_from_variables` in `bots/data.py`), and the LLM-in-the-loop enhance mode unlocks JavaScript-reactive dashboards.
- Frozen HTML artifacts with signed URLs (without expiration) deliver the "user can share a complete app via artifact_id" capability cleanly.
- Backward compatibility is preserved: the existing `bot.get_infographic()` and `InfographicTalk` HTTP endpoint stay untouched. The new pipeline is additive.

Option A is a strict subset of B and could be a phase-1 delivery if the OutputMode addition is contentious — but the cost difference is ~30 lines and the consistency win is substantial.

Option C is rejected because it eliminates the LLM-in-the-loop enhance capability that the user explicitly wants for "calculators, filterable dashboards" use cases.

---

## Feature Description

### User-Facing Behavior

A user in a chat session writes either:

```
!financial_variance Q4 2025
```

or, with a configured client:

```
output_mode=infographic
query=Create a financial projection variance dashboard for the last two weeks
```

or natural language:

```
Use create_infographic to generate a financial projection variance dashboard
for May 14 to May 27, with hero cards for revenue and EBITDA, daily bar
charts with day-over-day deltas, and a cumulative revenue line chart.
```

The agent completes the analysis in a single conversational turn and returns:

- A JSON envelope containing the underlying DataFrames (revenue daily, EBITDA daily, cumulative revenue) under `response.data` — exactly as PandasAgent already delivers multi-dataset responses today.
- A signed URL pointing to the rendered HTML artifact: `https://parrot.example.com/api/v1/artifacts/public/{artifact_id}.html`.
- The artifact_id itself, so the client can also retrieve via `GET /api/v1/threads/{session_id}/artifacts/{artifact_id}?format=html`.
- The `output_mode: "infographic"` discriminator in the envelope metadata.

The user (or the client UI) can:

- Render the HTML inline in chat (small artifacts, < 50KB inline option) or via iframe.
- Open the signed URL in a new tab as a standalone interactive app.
- Share the signed URL with a colleague who is not in the agent session (URL is auth-scoped via signing, not session-scoped).
- Drill into the underlying DataFrames programmatically via the `response.data` array.

For enhanced infographics (those generated with `mode="enhance"` per the skill instruction), the HTML includes inline JavaScript handlers added by the LLM in a second pass: tab toggles for "By project / By division" re-aggregation, hover tooltips with exact value + DoD delta, click-to-highlight interactions. The JavaScript runs entirely client-side, no external API calls.

### Internal Behavior

**Step 1 — Skill resolution and prompt assembly.**

When the user message starts with `!skill_name`, the AgentTalk handler resolves the skill via the SkillRegistry and prepends its content to the system prompt for that single turn. The skill's content describes:

1. The queries to execute (slug references for `DatasetManager.load_data`).
2. The python_repl_pandas computations to produce intermediate DataFrames with stable names (e.g., `daily_revenue`, `daily_ebitda`, `cumulative_revenue`).
3. The mandatory closing call: `infographic_render(template_name="financial_projection_variance", theme="navigator-dark", mode="enhance", enhance_brief="...", blocks=[...], data_variables=[...])`.

When the user message does not invoke a skill but specifies `output_mode=infographic`, the system prompt gets a generic addendum (added by `OUTPUT_SYSTEM_PROMPT.format(output_mode="infographic")` plus a dedicated `INFOGRAPHIC_SYSTEM_PROMPT_ADDON`) that explains the existence of the tool and how to call it.

**Step 2 — Tool-calling loop.**

The LLM proceeds as it would for any normal PandasAgent query:

- Calls `python_repl_pandas` one or more times to compute DataFrames.
- Calls `fetch_dataset` if the skill referenced unloaded datasets.
- Finally calls `infographic_render` with the blocks it has constructed from the computed data.

**Step 3 — Tool execution with deterministic guard.**

The `infographic_render` tool, with `return_direct=True`, executes the following validation pipeline:

1. **Template resolution.** `infographic_registry.get(template_name)` — raises `InfographicValidationError(code='TEMPLATE_UNKNOWN')` if missing.
2. **Positional block validation.** For each `BlockSpec` in `template.block_specs`:
   - If `spec.required` and no block at the expected position → `SLOT_MISSING`.
   - If the block's `.type` does not match `spec.block_type.value` → `SLOT_TYPE_MISMATCH`.
   - If `spec.min_items` / `spec.max_items` apply to the block type (hero_cards, bullet lists, etc.) and the count is out of range → `SLOT_ITEM_COUNT_INVALID`.
3. **Data variable resolution.** For each name in `data_variables`:
   - Look up in `pandas_tool.locals`. If absent → `DATA_VAR_MISSING`.
   - If present but not a non-empty DataFrame → `DATA_VAR_EMPTY`.
4. **Theme validation.** If `theme` is set, `theme_registry.get(theme)` must succeed → else `THEME_INVALID`.

All errors carry an actionable detail string and the failing context. The tool returns the error structured (not raised) so the LLM, despite `return_direct=True`, can inspect it and the agent loop can decide whether to surface it directly to the user or attempt a single guided retry — TBD whether retry-on-validation-error is in scope for v1.

**Step 4 — Deterministic render.**

Build an `InfographicResponse(template=template_name, theme=theme, blocks=blocks, metadata={...})`. Pass it to `InfographicHTMLRenderer` to produce the skeleton HTML string. This is unchanged behavior from how `get_infographic` renders today — it just bypasses the LLM call that normally constructs the blocks.

**Step 5 — Enhance pass (optional).**

If `mode == "enhance"`:
- Serialize the DataFrames referenced by `data_variables` to JSON (compact, no index, ISO dates).
- Call `bot.enhance_infographic(skeleton=skeleton_html, brief=enhance_brief, data_context=serialized_dfs, js_bundles_available=template.js_bundles)`. This is a new method on the agent (see Capability `infographic-enhance-pipeline`).
- The LLM returns enhanced HTML with inline `<script>` blocks.
- Validate the enhanced HTML: parseable (use stdlib `html.parser` or `lxml`), no `<script src="...">` tags pointing to external origins, no `<link rel="stylesheet" href="...">` external. If validation fails → `ENHANCE_OUTPUT_INVALID` and the toolkit falls back to the deterministic skeleton (this is the one place where graceful degradation is acceptable, because enhance is best-effort and the skeleton is already valid).

**Step 6 — Artifact persistence.**

Build the artifact `definition` dict:

```python
{
  "template_name": str,
  "theme": Optional[str],
  "blocks": [block.model_dump() for block in blocks],
  "datasets": [DatasetResult.model_dump() for each df in data_variables],
  "html": str,                    # the frozen HTML (skeleton or enhanced)
  "enhanced": bool,
  "enhance_brief": Optional[str],
}
```

Call `ArtifactStore.save_artifact(user_id, agent_id, session_id, Artifact(artifact_type=ArtifactType.INFOGRAPHIC, definition=...))`. The store offloads the HTML and the datasets to overflow storage automatically (existing `OverflowStore.maybe_offload` logic).

Generate the signed URL via the new `ArtifactStore.get_public_url(user_id, agent_id, session_id, artifact_id, format='html')`. This URL never expires.

**Step 7 — Return the envelope.**

The tool returns:

```python
InfographicRenderResult(
    artifact_id=artifact_id,
    html_url=signed_url,
    html_inline=html if len(html) < 50_000 else None,
    template_name=template_name,
    theme=theme,
    data_variables=data_variables,
    enhanced=enhanced,
)
```

Because `return_direct=True`, the agent loop ends here. The LLM does not see this result.

**Step 8 — PandasAgent post-loop branch.**

In `PandasAgent.ask()`, after the LLM loop, check if the last tool call's result is an `InfographicRenderResult` (isinstance check). If yes:

- `await self._inject_multi_data_from_variables(response, envelope.data_variables)` — populates `response.data` as a `List[DatasetResult]`.
- `response.output = envelope.html_url` (or `html_inline` if small).
- `response.output_mode = OutputMode.INFOGRAPHIC`.
- `response.artifact_id = envelope.artifact_id` (extend `AIMessage` if this field doesn't exist — Claude Code to verify).
- Skip the structured-output reformat path (no Google two-phase reformat call) and skip the formatter (`self.formatter.format(...)`).
- Return the response.

**Step 9 — HTTP layer.**

In `_format_response`, the existing JSON path produces an envelope with:

```json
{
  "input": "...",
  "output": "https://...artifact_id.html",
  "output_mode": "infographic",
  "data": [DatasetResult, DatasetResult, DatasetResult],
  "metadata": { ..., "artifact_id": "infog-abc12345" },
  "code": null,
  "sources": [],
  "tool_calls": [...]
}
```

The client renders this as a chat message with an embedded preview + link.

**Step 10 — Serving the HTML.**

The new endpoint `ArtifactDetailView.get` with `?format=html` or `Accept: text/html` checks `artifact.artifact_type == ArtifactType.INFOGRAPHIC`, retrieves `definition.html`, and returns it with `Content-Type: text/html; charset=utf-8`. Signed URL validation happens earlier in middleware (Claude Code to wire that).

### Edge Cases & Error Handling

- **LLM produces wrong number of blocks.** Caught by `SLOT_MISSING` / unexpected extra blocks (silently ignored if more than `block_specs` length, OR rejected with `EXTRA_BLOCKS` — TBD, prefer reject).
- **LLM produces blocks of wrong type at wrong position.** `SLOT_TYPE_MISMATCH`. Tool returns error envelope, agent surfaces it.
- **LLM produces correct blocks but references a `data_variable` that does not exist.** `DATA_VAR_MISSING`. Common cause: typo or referencing a DataFrame from a previous turn that was evicted. Tool error.
- **`bot.enhance_infographic` returns HTML with external `<script src="https://malicious.com/x.js">`.** `ENHANCE_OUTPUT_INVALID`, toolkit falls back to deterministic skeleton. Logged as a security event.
- **Artifact storage failure.** Bubble up as a 500-class error; the agent turn fails. No retry in v1.
- **Multiple `infographic_render` calls in one turn.** Only the last is considered the "final" tool call. The earlier calls produced artifacts that are still saved but not returned in the envelope. Document this; do not engineer around it.
- **Concurrent renders for the same session.** Different `artifact_id` per call (UUID-prefixed). Session-isolated `pandas_tool` clone (existing `AgentTalk` pattern) ensures DataFrame names don't collide. No coordination needed.
- **Template not found.** `TEMPLATE_UNKNOWN`. Tool error envelope.
- **HTML > 50KB.** `html_inline` field is `None`; only `html_url` is returned. Client must fetch the URL to display.
- **User has no `output_mode=infographic` set, no skill invoked, but the system prompt addendum is absent — and they ask "make me a dashboard".** The agent has no nudge to use the toolkit. Falls back to standard PandasAgent behavior (text answer). This is intentional; explicit invocation only in v1.

---

## Capabilities

### New Capabilities

- `infographic-toolkit`: The `InfographicToolkit(AbstractToolkit)` class itself, including the four tools (`render`, `list_templates`, `get_template_contract`, `validate_blocks`), the `InfographicRenderResult` envelope, the `InfographicValidationError` exception hierarchy, and the deterministic guard pipeline.
- `infographic-enhance-pipeline`: The new `bot.enhance_infographic(skeleton, brief, data_context, js_bundles_available, ...)` agent method, the dedicated prompt template for the enhance LLM call, and the post-output HTML validation (parseable + no external scripts).
- `pandas-agent-infographic-integration`: The post-loop branch in `PandasAgent.ask()` that detects `InfographicRenderResult` via isinstance, populates `response.data`, `response.output`, `response.output_mode`, and `response.artifact_id`, and bypasses the formatter and the structured-output reformat path.
- `artifact-public-url`: The new `ArtifactStore.get_public_url(user_id, agent_id, session_id, artifact_id, format='html')` method that produces a non-expiring signed URL via the overflow store's backend (S3 `generate_presigned_url` or equivalent).

…(truncated)…

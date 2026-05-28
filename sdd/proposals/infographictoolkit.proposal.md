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
- `artifact-html-serving`: Extension of `ArtifactDetailView.get` (in `handlers/artifacts.py`) to accept `?format=html` or `Accept: text/html` and return the frozen HTML for infographic artifacts. New URL route for signed public access (`/api/v1/artifacts/public/{signature}/{artifact_id}.html` or similar).
- `output-mode-infographic`: New `OutputMode.INFOGRAPHIC` enum value, plus the system-prompt addendum (`INFOGRAPHIC_SYSTEM_PROMPT_ADDON`) and the formatter branch in `_format_response` (in `handlers/agent.py`).

### Modified Capabilities

None. All changes are additive. The existing `bot.get_infographic()` method, the `InfographicTalk` HTTP handler, and the seven built-in templates remain unchanged in behavior. The `InfographicTemplate.block_specs` positional contract is preserved without modification.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/` | extends | New module `infographic_toolkit.py`. |
| `parrot/bots/agent.py` | extends | New `enhance_infographic` method on `BasicAgent` (or on the same mixin/class that hosts `get_infographic` — Claude Code to locate). |
| `parrot/bots/data.py` | modifies | Add post-loop branch in `PandasAgent.ask()` detecting `InfographicRenderResult`. ~30 lines, near the existing `_rerun_for_map` branch. |
| `parrot/models/outputs.py` | extends | Add `OutputMode.INFOGRAPHIC` enum value. |
| `parrot/models/responses.py` | extends | Add `artifact_id: Optional[str]` to `AIMessage` if not present (Claude Code to verify). |
| `parrot/storage/artifacts.py` | extends | New `ArtifactStore.get_public_url` method. |
| `parrot/storage/overflow.py` | extends | Expose signed-URL generation on the `OverflowStore` interface (delegated to S3 backend or equivalent). |
| `parrot/handlers/agent.py` | modifies | Add `OutputMode.INFOGRAPHIC` formatter branch in `_format_response` (~20 lines). Add system-prompt addendum injection in `post()` when `output_mode == 'infographic'` (~10 lines). |
| `parrot/handlers/artifacts.py` | modifies | Add HTML serving path to `ArtifactDetailView.get` (~30 lines). Add new public-URL route handler. |
| `parrot/bots/prompts/` | extends | New `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` template string. |
| `parrot/skills/` (if SkillRegistry lives here — Claude Code to verify) | extends | Add 1-2 example skills (`financial_projection_variance.md`) demonstrating the pattern. |

**Dependencies:** No new pip packages. All capabilities use existing dependencies (pydantic v2, aiohttp, the existing storage backends).

**Configuration:** The signed-URL feature may require S3 bucket policy adjustment to allow long-lived signed URLs. Document this in the storage operations guide.

**Deployment:** No data migrations. The new artifact type (`INFOGRAPHIC` — already exists in `ArtifactType` per `handlers/infographic.py:200`) is reused, but now with `definition.html` populated. Existing infographic artifacts (saved by the older `_auto_save_infographic_artifact` path) will not have `definition.html`, which is fine: the HTML serving endpoint detects absence and falls back to re-rendering from `definition` (which holds the InfographicResponse structure).

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (signature of existing get_infographic)
async def get_infographic(
    self,
    question: str,
    template: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    use_vector_context: bool = True,
    use_conversation_history: bool = False,
    theme: Optional[str] = None,
    accept: str = "text/html",
    ctx: Optional[RequestContext] = None,
    **kwargs,
) -> AIMessage:
    """Generate a structured infographic response.
    ...
    """
```

```python
# Source: parrot/models/infographic.py:353
class ChartBlock(BaseModel):
    """Chart specification block. Frontend renders using its preferred library."""
    type: Literal["chart"] = "chart"
    chart_type: ChartType = Field(..., description="Type of chart to render")
    title: Optional[str] = Field(None, description="Chart title")
    description: Optional[str] = Field(None, description="Caption or description")
    labels: List[str] = Field(
        ...,
        description="Category/axis labels (x-axis for bar/line, slices for pie)"
    )
    series: List[ChartDataSeries] = Field(
        ...,
        description="One or more data series"
    )
    x_axis_label: Optional[str] = Field(None, description="X-axis label")
    y_axis_label: Optional[str] = Field(None, description="Y-axis label")
    stacked: Optional[bool] = Field(False, description="Whether series are stacked")
    show_legend: Optional[bool] = Field(True, description="Whether to show the legend")
```

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/tools/toolkit.py:191
class AbstractToolkit(ABC):
    return_direct: bool = False              # line 220 — the key lever
    tool_prefix: Optional[str] = None        # line 242
    prefix_separator: str = "_"              # line 245
    exclude_tools: tuple[str, ...] = ()      # line 228

    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...   # line 306
    async def _post_execute(self, tool_name: str, result: Any, **kwargs) -> Any: ...  # line 321
    def get_tools(self, ...) -> List[AbstractTool]: ...                   # line 337
    def _generate_tools(self) -> None: ...                                # line 390
```

```python
# From parrot/tools/toolkit.py:32
class ToolkitTool(AbstractTool):
    def __init__(self, name, bound_method, description=None,
                 args_schema=None, **kwargs):
        self.bound_method = bound_method
        # passes return_direct from toolkit through to the tool
        # see toolkit.py:508-517
```

```python
# From parrot/models/infographic.py:657
class InfographicResponse(BaseModel):
    template: Optional[str]
    theme: Optional[str]
    blocks: List[Annotated[InfographicBlock, Discriminator("type")]]
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

```python
# From parrot/models/infographic.py:634
InfographicBlock = Union[
    TitleBlock, HeroCardBlock, SummaryBlock, ChartBlock, BulletListBlock,
    TableBlock, ImageBlock, QuoteBlock, CalloutBlock, DividerBlock,
    TimelineBlock, ProgressBlock, AccordionBlock, ChecklistBlock, TabViewBlock,
]
```

```python
# From parrot/models/infographic_templates.py:21
class BlockSpec(BaseModel):
    block_type: BlockType
    required: bool = True
    description: Optional[str] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    constraints: Optional[Dict[str, str]] = Field(default_factory=dict)

# From parrot/models/infographic_templates.py:47
class InfographicTemplate(BaseModel):
    name: str
    description: str
    block_specs: List[BlockSpec]
    default_theme: Optional[str] = None

    def to_prompt_instruction(self) -> str: ...    # line 60

# From parrot/models/infographic_templates.py:398
class InfographicTemplateRegistry:
    def register(self, template: InfographicTemplate) -> None: ...
    def get(self, name: str) -> InfographicTemplate: ...
    def list_templates(self) -> List[str]: ...
    def list_templates_detailed(self) -> List[Dict[str, str]]: ...

# Module singleton — used as-is by the toolkit:
infographic_registry = InfographicTemplateRegistry()    # line 471
```

```python
# From parrot/models/infographic.py:799
class ThemeRegistry:
    def register(self, theme: ThemeConfig) -> None: ...
    def get(self, name: str) -> ThemeConfig: ...
    def list_themes(self) -> List[str]: ...

theme_registry = ThemeRegistry()    # line 863
# Built-in themes: light, dark, corporate, midnight  (lines 867-929)
```

```python
# From parrot/storage/artifacts.py:18
class ArtifactStore:
    def __init__(self, dynamodb: ConversationBackend, s3_overflow: OverflowStore) -> None: ...
    async def save_artifact(self, user_id, agent_id, session_id, artifact: Artifact) -> None: ...    # line 30
    async def get_artifact(self, user_id, agent_id, session_id, artifact_id) -> Optional[Artifact]: ...    # line 58
    async def list_artifacts(self, user_id, agent_id, session_id) -> List[ArtifactSummary]: ...
    async def update_artifact(self, ...) -> None: ...
    async def delete_artifact(self, ...) -> bool: ...
    # NEW (does not exist yet):
    # async def get_public_url(self, user_id, agent_id, session_id, artifact_id, format='html') -> str: ...
```

```python
# From parrot/bots/data.py
class PandasAgent(BasicAgent):
    DEFAULT_MAX_ITERATIONS = 10                                    # line ~520
    _prompt_builder = _build_pandas_prompt_builder()               # line ~525

    async def ask(self, question, ...) -> AIMessage: ...           # main flow ~line 800
    async def _rerun_for_map(self, *, client, question, ...): ...  # pattern to replicate
    async def _inject_multi_data_from_variables(
        self, response: AIMessage, data_variables: List[str],
    ) -> List[str]: ...    # already returns DatasetResult-shaped list in response.data
    async def _inject_data_from_variable(self, response, data_variable: str): ...
    def _get_python_pandas_tool(self) -> Optional[PythonPandasTool]: ...
    def _get_repl_locals(self) -> Dict[str, Any]: ...
```

```python
# From parrot/handlers/agent.py
class AgentTalk(BaseView):
    async def post(self) -> web.Response: ...
    async def _format_response(self, response, output_format, format_kwargs,
                                user_id, user_session, response_time_ms,
                                agent_name, session_id, client_message_id) -> web.Response: ...
    # OutputMode branches live here — add OutputMode.INFOGRAPHIC alongside JSON/HTML
```

```python
# From parrot/handlers/artifacts.py
class ArtifactDetailView(BaseView):
    async def get(self) -> web.Response: ...
    async def put(self) -> web.Response: ...
    async def delete(self) -> web.Response: ...
```

```python
# From parrot/handlers/infographic.py:201 (already uses ArtifactType.INFOGRAPHIC)
from ..storage.models import Artifact, ArtifactType, ArtifactCreator
# ArtifactType.INFOGRAPHIC is confirmed to exist.
```

#### Verified Imports

```python
# These imports have been confirmed to work in the existing codebase:
from parrot.tools.toolkit import AbstractToolkit, ToolkitTool      # parrot/tools/toolkit.py:191,32
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema  # parrot/tools/toolkit.py:25

from parrot.models.infographic import (
    InfographicBlock,        # parrot/models/infographic.py:634
    InfographicResponse,     # parrot/models/infographic.py:657
    BlockType, ChartType,    # parrot/models/infographic.py:45,64
    theme_registry,          # parrot/models/infographic.py:863
)
from parrot.models.infographic_templates import (
    BlockSpec,                       # parrot/models/infographic_templates.py:21
    InfographicTemplate,             # parrot/models/infographic_templates.py:47
    infographic_registry,            # parrot/models/infographic_templates.py:471
)
from parrot.storage.artifacts import ArtifactStore    # parrot/storage/artifacts.py:18
from parrot.storage.models import Artifact, ArtifactType, ArtifactCreator  # via handlers/infographic.py:201

from parrot.models.outputs import OutputMode    # via bots/data.py:25
# Existing values: DEFAULT, JSON, HTML, TABLE, MAP, MSTEAMS, TELEGRAM, TERMINAL
# Add: INFOGRAPHIC
```

#### Key Attributes & Constants

- `AbstractToolkit.return_direct` → `bool` — parrot/tools/toolkit.py:220 — set to `True` in `InfographicToolkit`.
- `AbstractToolkit.tool_prefix` → `Optional[str]` — parrot/tools/toolkit.py:242 — set to `"infographic"` in `InfographicToolkit`.
- `ToolkitTool` inherits `return_direct` from the toolkit — parrot/tools/toolkit.py:513.
- `InfographicTemplate.block_specs` → `List[BlockSpec]` — parrot/models/infographic_templates.py:51 — positional contract.
- `BlockSpec.block_type` → `BlockType` enum — parrot/models/infographic_templates.py:27 — used for type validation against `block.type`.
- `infographic_registry.get(name)` raises `KeyError` if missing — parrot/models/infographic_templates.py:441.
- `theme_registry.get(name)` raises `KeyError` if missing — parrot/models/infographic.py:817.
- `PandasAgent._inject_multi_data_from_variables` already returns `response.data` as `List[Dict]` from `DatasetResult.model_dump()` — bots/data.py — reused as-is.
- `Artifact.definition` accepts arbitrary `Dict[str, Any]` — definition holds blocks + datasets + html.
- `OverflowStore.maybe_offload(definition, key_prefix) -> (inline, ref)` — parrot/storage/artifacts.py:55 — handles HTML > inline threshold automatically.

### Does NOT Exist (Anti-Hallucination)

The following do NOT exist in the codebase as of this brainstorm and must be created from scratch. Implementing agents must NOT assume any of these are available before the corresponding spec is delivered:

- ~~`parrot.tools.infographic_toolkit.InfographicToolkit`~~ — module and class do not exist.
- ~~`parrot.tools.infographic_toolkit.InfographicRenderResult`~~ — envelope model does not exist.
- ~~`parrot.tools.infographic_toolkit.InfographicValidationError`~~ — exception hierarchy does not exist.
- ~~`BasicAgent.enhance_infographic`~~ — method does not exist. `bot.get_infographic` exists but does NOT accept `enhance_skeleton` or `enhance_brief` parameters.
- ~~`ArtifactStore.get_public_url`~~ — method does not exist.
- ~~`OutputMode.INFOGRAPHIC`~~ — enum value does not exist. Existing values: `DEFAULT`, `JSON`, `HTML`, `TABLE`, `MAP`, `MSTEAMS`, `TELEGRAM`, `TERMINAL`.
- ~~`AIMessage.artifact_id`~~ — field may not exist; Claude Code must verify and add if absent.
- ~~`BlockSpec.slot_id`~~ — field does NOT exist and we explicitly chose NOT to add it. Block identification is positional via `block_specs` order. This is intentional — the existing positional contract is preserved.
- ~~`InfographicTemplate.js_bundles`~~ — field does not exist. If the enhance pipeline needs to declare available JS bundles per template, this is a new optional field to add (or stored as metadata in the template's `description` string for v1 — TBD).
- ~~Public artifact URL route at `/api/v1/artifacts/public/{...}`~~ — route does not exist; needs to be registered.
- ~~`SkillRegistry` integration with `!skill_name` prefix parsing in `AgentTalk.post()`~~ — Claude Code must verify whether this parsing already exists or is part of this feature's scope.
- ~~`InfographicHTMLRenderer` location~~ — referenced in `parrot/models/infographic.py:778` but the renderer's actual module path is not visible in the files reviewed. Claude Code must locate it before the toolkit's render step can be implemented.

---

## Parallelism Assessment

- **Internal parallelism**: HIGH. The feature decomposes cleanly into four largely independent work units:
  1. **Storage + HTML serving + OutputMode** (capability: `artifact-public-url`, `artifact-html-serving`, `output-mode-infographic`). Touches `storage/artifacts.py`, `storage/overflow.py`, `handlers/artifacts.py`, `handlers/agent.py`, `models/outputs.py`. No coupling to the toolkit code.
  2. **Toolkit + Envelope + Validation** (capability: `infographic-toolkit`). New module `tools/infographic_toolkit.py`. Reads existing models; no modifications to other modules.
  3. **Enhance pipeline** (capability: `infographic-enhance-pipeline`). New method `enhance_infographic` on the agent class hosting `get_infographic` (Claude Code locates). New prompt template. HTML validation utility. Used by worktree 2 but only via method-call boundary.
  4. **PandasAgent integration** (capability: `pandas-agent-infographic-integration`). Post-loop branch in `PandasAgent.ask()` detecting `InfographicRenderResult`. Depends on the envelope class from worktree 2 — easiest if worktree 2 publishes the envelope class in an early commit.

- **Cross-feature independence**: HIGH. This feature does not conflict with any other in-flight specs in the current backlog. Conflict points to monitor: any concurrent work on `bots/data.py` (modifications to `ask()` flow) and any concurrent work on `handlers/agent.py` (modifications to `_format_response` or `post()`). The `_rerun_for_map` pattern is the template we follow in `ask()`, so we should not collide with it.

- **Recommended isolation**: `per-spec`.

- **Rationale**: Each of the four capabilities listed under "New Capabilities" is independently testable and deliverable. Splitting them into four specs allows four parallel worktrees:
  - Worktrees 1 (storage+http+output_mode) and 3 (enhance pipeline) are fully independent of each other and of 2/4.
  - Worktrees 2 and 4 share the `InfographicRenderResult` class definition; we resolve this by treating worktree 2 as the publisher of that class and worktree 4 as the consumer. Worktree 4 can be merged immediately after worktree 2 lands, or 2+4 can be merged into a single PR if the team prefers fewer review cycles.
  - The capabilities `infographic-toolkit` and `pandas-agent-infographic-integration` MAY be merged into a single capability if review burden of 4 specs is too high — they are tightly coupled by `InfographicRenderResult`. Recommendation: keep them separate for clarity but flag the coupling in the specs.

---

## Open Questions

- [x] Should `infographic_render` allow `mode="enhance"` to fall back silently to deterministic skeleton when the enhance LLM call fails validation, or should it return an error envelope? — *Owner: Jesus*: allow `mode="enhance"` to fall back silently
- [x] Are extra blocks beyond the template's `block_specs` length silently ignored, or rejected with `EXTRA_BLOCKS`? Lean toward reject for strict contract; confirm. — *Owner: Jesus*: reject
- [ ] Single-turn retry on `SLOT_TYPE_MISMATCH` / `DATA_VAR_MISSING` — does the toolkit return the error to the LLM (despite `return_direct=True`) for one corrective retry, or surface immediately to the user? — *Owner: Jesus*
- [x] `InfographicTemplate.js_bundles` field — add now to declare which JS libraries are pre-bundled in the template (so enhance LLM knows what to use), or defer to v2 and pass via template `description` text for now? — *Owner: Jesus*: add now.
- [x] Public artifact URL signing mechanism — HMAC with a secret in env config, S3 presigned URL with `ExpiresIn=None` (or maximum permitted by backend), or a custom token table? S3 presigned URLs have a 7-day max with sigv4, so "no expiration" via S3 may not be literally achievable. — *Owner: Jesus*: ok with 7-day expiration.
- [x] `SkillRegistry` and `!skill_name` parsing — is the parsing layer already implemented in `AgentTalk.post()` (or upstream), or is it part of this feature's scope? — *Owner: Claude Code (verification task)*: yes.
- [ ] `InfographicHTMLRenderer` location and public API — Claude Code must locate the renderer module, confirm it accepts an `InfographicResponse` and returns an HTML string, and document its import path before the toolkit's render step can be specified in detail. — *Owner: Claude Code (verification task)*
- [x] Streaming behavior — when `output_mode=infographic` and `stream=true`, the streaming path in `_handle_stream_response` does not currently handle large HTML payloads. Should infographic mode disable streaming and force a non-streamed response, or include the HTML URL in the chunked envelope and let the client fetch separately? Lean toward disable streaming + URL in final envelope. — *Owner: Jesus*: disable streaming and URL in final envelope.
- [x] Auth scope of signed URLs — are signed URLs scoped to the user that generated them (HMAC includes user_id), or globally accessible by signature alone? The latter supports "share with a colleague who is not in the agent session" but raises privacy considerations. — *Owner: Jesus*: let's start with signature alone.
- [x] Iframe sandboxing — when the client embeds the HTML in an iframe, what CSP headers should the HTML-serving endpoint set? `frame-ancestors`, `script-src 'unsafe-inline'` (required for enhance JS), etc. Document the security model. — *Owner: Jesus*: accept suggestions for security.

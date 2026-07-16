---
type: Wiki Overview
title: InfographicToolkit — Reference
id: doc:docs-toolkits-infographic-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: artifacts in a single agent turn. With `return_direct=True` set on the toolkit,
---

# InfographicToolkit — Reference

**Feature**: FEAT-197  
**Module**: `parrot/tools/infographic_toolkit.py`  
**Class**: `InfographicToolkit(AbstractToolkit)`

---

## Overview

`InfographicToolkit` produces frozen, multi-dataset interactive HTML infographic
artifacts in a single agent turn.  With `return_direct=True` set on the toolkit,
the result of `infographic_render` is returned verbatim to the caller — the LLM
does not get a chance to summarise or reformat it.

The `PandasAgent.ask()` post-loop branch detects `InfographicRenderResult` objects
and populates `response.output`, `response.output_mode`, `response.artifact_id`,
and `response.data` before returning to the HTTP layer.

---

## Tools

### `infographic_render`

Validate blocks, render the deterministic HTML skeleton, optionally enhance it with
LLM-generated JavaScript interactivity, persist the artifact, and return the result.

| Parameter | Type | Description |
|---|---|---|
| `template_name` | `str` | Template identifier (see `infographic_list_templates`). |
| `theme` | `Optional[str]` | Color theme (`"light"`, `"dark"`, `"corporate"`, `"midnight"`). Pass `null` to use the template's default. |
| `mode` | `"deterministic" \| "enhance"` | Rendering mode. |
| `blocks` | `List[Dict]` | Ordered block dicts matching the template's positional contract. |
| `data_variables` | `List[str]` | Names of DataFrames in the pandas REPL locals. |
| `enhance_brief` | `Optional[str]` | Required when `mode="enhance"`. Short description of desired interactivity. |

**Returns**: `InfographicRenderResult`

```json
{
  "artifact_id": "infographic-abc123",
  "html_url": "https://...",
  "html_inline": "<html>...</html>",
  "template_name": "financial_projection_variance",
  "theme": "dark",
  "data_variables": ["rev_daily", "ebitda_daily"],
  "enhanced": false
}
```

---

### `infographic_render_template`

Render a **pre-registered HTML+Jinja2 template** with data you already have into a
self-contained infographic artifact. Unlike `infographic_render` (typed blocks
computed from DataFrames in a pandas REPL), this path fills a trusted template
directly, so it is usable by **any** agent — no pandas namespace required.

Templates are **trusted** and supplied by the developer (never LLM-authored Jinja),
so no sandbox is applied. Register them at construction or at runtime:

```python
toolkit = InfographicToolkit(
    artifact_store=store,
    template_dirs=["/path/to/templates"],           # filesystem templates
    templates={"summary.html.j2": "<h1>{{ data.title }}</h1>"},  # in-memory
)
toolkit.add_template("late.html.j2", "<b>{{ data.v }}</b>")       # runtime
toolkit.set_bot(agent)
```

| Parameter | Type | Description |
|---|---|---|
| `template_name` | `str` | Name of a registered template. |
| `data` | `Optional[Dict]` | Authoritative, JSON-serialisable payload exposed to the template as `data` (e.g. `{{ data.title }}`). This is the reliable channel. |
| `theme` | `Optional[str]` | Theme name, exposed as `theme` and stored on the artifact. |
| `title` | `Optional[str]` | Artifact title (defaults to `Infographic — <name>`). |

**Template context**: `data` (your payload), `message` (best-effort snapshot of the
bound bot's last `AIMessage` — may be `{}` mid-turn; prefer `data`), `meta`
(`message.metadata`), `theme`, `title`, and `now` (UTC). Autoescaping is on and
missing variables raise under `StrictUndefined`.

**Returns**: `InfographicRenderResult` (same shape as `infographic_render`;
`data_variables` is empty, `enhanced` is `false`).

Any agent (not only `PandasAgent`) finalizes the result: the `BaseBot.ask()`
post-loop detects `InfographicRenderResult` and sets `response.output` (HTML or
signed URL), `response.output_mode = infographic`, and `response.artifact_id`.

---

### `infographic_list_templates`

List all registered templates with name and description.

**Returns**: `List[{"name": str, "description": str}]`

---

### `infographic_get_template_contract`

Fetch the positional block contract for a template.

| Parameter | Type | Description |
|---|---|---|
| `template_name` | `str` | Template identifier. |

**Returns**: Dict with `name`, `description`, `default_theme`, `block_specs` (array with `position`, `block_type`, `required`, `min_items`, `max_items`, `constraints`), and `js_bundles`.

---

### `infographic_validate_blocks`

Dry-run block validation without rendering or persisting.  Always returns a dict —
never raises.

| Parameter | Type | Description |
|---|---|---|
| `template_name` | `str` | Template identifier. |
| `blocks` | `List[Dict]` | Blocks to validate. |

**Returns**: `{"ok": true}` on success; `{"ok": false, "code": "...", "detail": {...}}` on failure.

---

## Validation Error Codes

| Code | When |
|---|---|
| `TEMPLATE_UNKNOWN` | `template_name` not in the registry (or, for `render_template`, not a registered Jinja template). |
| `TEMPLATE_ENGINE_UNSET` | `render_template` called but no `template_dirs`/`templates`/`add_template()` were configured. |
| `TEMPLATE_RENDER_ERROR` | `render_template` hit a Jinja error (e.g. a missing variable under `StrictUndefined`). |
| `SLOT_MISSING` | A required block slot has no corresponding block. |
| `SLOT_TYPE_MISMATCH` | A block's `type` does not match the spec at that position. |
| `SLOT_ITEM_COUNT_INVALID` | A block violates `min_items` / `max_items` constraints. |
| `EXTRA_BLOCKS` | More blocks than `block_specs` positions. |
| `DATA_VAR_MISSING` | A `data_variables` entry is absent from the pandas REPL locals. |
| `DATA_VAR_EMPTY` | A `data_variables` entry is present but the DataFrame is empty. |
| `THEME_INVALID` | `theme` is not registered in `theme_registry`. |
| `ENHANCE_OUTPUT_INVALID` | The enhance LLM produced HTML with external resources outside the SRI whitelist. Toolkit silently falls back to the deterministic skeleton. |

---

## HTTP Response Shape

When `output_mode=infographic`, the JSON envelope is:

```json
{
  "input": "...",
  "output": "<html or url>",
  "output_mode": "infographic",
  "artifact_id": "infographic-abc123",
  "data": [ ... List[DatasetResult] ... ],
  "metadata": {
    "html_url": "https://...",
    "html_inline_omitted": false,
    "enhanced": false,
    "template_name": "...",
    "theme": "dark"
  }
}
```

`Accept: text/html` or `?format=html` returns `Content-Type: text/html` with
the raw HTML body.

---

## Streaming

Streaming is **disabled** for `output_mode=infographic`.  Clients that always set
`stream=true` will receive a non-streamed envelope.

---

## Invoking via a Skill

```
/financial_variance Q4 2025
```

The skill `financial_projection_variance.md` triggers the full pipeline via the
`SkillRegistry` `/trigger` middleware.

---

## Built-in Templates (FEAT-197)

| Name | Description |
|---|---|
| `financial_projection_variance` | 4 KPI hero cards + 2 DoD bar charts + 1 cumulative line chart. Declares ECharts CDN bundle. |

---

## See Also

- `docs/operations/infographic_csp_and_signed_urls.md` — CSP / signed-URL operations.
- `agents/troc_finance/skills/financial_projection_variance.md` — Example skill.

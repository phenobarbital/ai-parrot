---
type: Wiki Overview
title: Semantic UI Model → Adaptive Cards (FEAT-303)
id: doc:docs-integrations-msagentsdk-semantic-cards-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 365 Copilot / Teams.
relates_to:
- concept: mod:parrot.integrations.msagentsdk
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.cards
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.semantic
  rel: mentions
---

# Semantic UI Model → Adaptive Cards (FEAT-303)

**Feature**: FEAT-303
**Applies to**: `parrot.integrations.msagentsdk` (package `ai-parrot-integrations`)
**Audience**: agent developers building custom engine agents for Microsoft
365 Copilot / Teams.

## What this is

By default, the `msagentsdk` bridge (`ParrotM365Agent`) sends agent replies
as plain text. Domain agents that produce structured results — tables,
KPIs, entity details, statuses — read poorly as flat text. Microsoft's UX
guidance for custom engine agents recommends rendering rich results as
**Adaptive Cards** instead.

The **Semantic UI Model** (`parrot.integrations.msagentsdk.semantic`) is a
small, channel-neutral Pydantic contract you return from your agent to opt
in to card rendering. A deterministic renderer
(`parrot.integrations.msagentsdk.cards`) turns it into Adaptive Card 1.4
JSON — no LLM pass in the render path, so results are reproducible and
fast.

If you never return this model, nothing changes: your agent's replies are
sent as plain text exactly as before.

## The four result types

`SemanticUIResult` carries a `title`, an optional `summary`, a `payload`
(discriminated on `result_type`), and a list of `actions`. Exactly one of
four payload shapes is supported in v1:

### `table`

```json
{
  "title": "Recent Orders",
  "payload": {
    "result_type": "table",
    "columns": ["id", "total"],
    "rows": [["1001", "$42.00"], ["1002", "$17.50"]],
    "total_rows": 2
  }
}
```

### `metrics`

```json
{
  "title": "This Week's KPIs",
  "payload": {
    "result_type": "metrics",
    "metrics": [
      {"label": "Revenue", "value": "$12,400", "delta": "+8%"},
      {"label": "Active Users", "value": "342"}
    ]
  }
}
```

### `detail`

```json
{
  "title": "Order #1001",
  "payload": {
    "result_type": "detail",
    "fields": [
      {"label": "Status", "value": "Shipped"},
      {"label": "Customer", "value": "Jane Doe"}
    ]
  }
}
```

### `status`

```json
{
  "title": "Result",
  "payload": {
    "result_type": "status",
    "level": "success",
    "message": "Order #1001 has been cancelled.",
    "details": "A refund will be issued within 3-5 business days."
  }
}
```

`level` is one of `"success"`, `"warning"`, `"error"`, `"info"`.

Charts are **not** a v1 result type — they remain available via existing
image/ECharts paths and may be added in a future revision.

## Returning a `SemanticUIResult` from your agent

The adapter never infers this model from free text — you construct and
return it explicitly. Import the public names from the package's lazy
exports:

```python
from parrot.integrations.msagentsdk import SemanticUIResult, UIAction

result = SemanticUIResult(
    title="Recent Orders",
    payload={
        "result_type": "table",
        "columns": ["id", "total"],
        "rows": [["1001", "$42.00"], ["1002", "$17.50"]],
    },
    actions=[
        UIAction(title="Show details", prompt_template="Show details for order {id}",
                 params={"id": "1001"}),
        UIAction(title="Open dashboard", url="https://example.com/dashboard"),
    ],
)
```

There are two supported carriers, checked in this priority order by the
bridge:

1. Pass it to `ask()` as structured output:
   ```python
   response = await bot.ask(question, structured_output=SemanticUIResult)
   ```
2. Or set it directly on the response object your tool/agent returns —
   either `response.structured_output` or `response.data` — as long as it
   is an actual `SemanticUIResult` instance (no dict duck-typing).

## Actions and the round-trip

Each `UIAction` renders as a card action button and requires **exactly
one** of:

- `prompt_template` (+ optional `params`) — renders as `Action.Submit` with
  a `messageBack` payload. Clicking it re-enters your agent through the
  normal `ask()` pipeline as a natural-language message — no named
  tool/action dispatch, no new state machinery. `params` fill the
  template's `{placeholders}`.
- `url` — renders as `Action.OpenUrl`, simply opening the link.

Some surfaces (notably M365 Copilot in certain configurations) may deliver
the click as an `adaptiveCard/action` **invoke** instead of a `messageBack`
message. The bridge handles both automatically — you don't need to do
anything extra; both paths route to the same prompt.

## Configuration

Three knobs on `MSAgentSDKConfig` (all optional, with the defaults shown):

| Field | Default | Purpose |
|---|---|---|
| `enable_semantic_cards` | `True` | Set `False` to always send plain text, even if your agent returns a `SemanticUIResult`. |
| `max_table_rows` | `15` | Table rows beyond this are truncated with a "Showing N of M" note. |
| `max_card_bytes` | `25_000` | Serialized card size guard (Teams' attachment limit is ~28 KB). Exceeding it falls back to plain text. |

```yaml
# integrations_bots.yaml
my-bot:
  kind: msagentsdk
  chatbot_id: my-bot
  enable_semantic_cards: true
  max_table_rows: 20
  max_card_bytes: 20000
```

## Fallback behavior

The card path is designed to **never break a turn**:

- Any exception while rendering or sending the card falls back to plain
  text via `render_text()`.
- If `render_text()` itself somehow fails, the bridge sends
  `str(response.content)` as a last resort.
- Non-card channels (e.g. the Bot Framework Emulator) always receive a
  populated `text` field on the Activity — the plain-text rendering is
  never omitted, even when the card attachment is also present.
- Empty payloads (no rows, no metrics, no fields) render a "no results"
  status-style card rather than a blank Adaptive Card element.

## Direct renderer access (advanced)

For testing or custom pipelines, the renderer functions are also available
directly:

```python
from parrot.integrations.msagentsdk import render_card, render_text

card_json = render_card(result, max_table_rows=15, max_card_bytes=25_000)
fallback_text = render_text(result)
```

Both are pure functions — no I/O, no SDK dependency — so they can be unit
tested without a running bot or the `microsoft-agents-*` packages
installed.

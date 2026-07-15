---
type: Wiki Summary
title: parrot.integrations.parser
id: mod:parrot.integrations.parser
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared Response Parser for Integration Wrappers.
relates_to:
- concept: class:parrot.integrations.parser.ChartData
  rel: defines
- concept: class:parrot.integrations.parser.ParsedResponse
  rel: defines
- concept: func:parrot.integrations.parser.parse_response
  rel: defines
---

# `parrot.integrations.parser`

Shared Response Parser for Integration Wrappers.

Provides a unified way to parse AIMessage responses into structured content
for rendering in different platforms (Telegram, MS Teams, etc.).

## Classes

- **`ChartData`** — Metadata for a generated chart.
- **`ParsedResponse`** — Structured response content extracted from AIMessage.

## Functions

- `def parse_response(response: Any) -> ParsedResponse` — Parse an AIMessage or similar response into structured content.

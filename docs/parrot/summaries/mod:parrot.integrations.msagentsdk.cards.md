---
type: Wiki Summary
title: parrot.integrations.msagentsdk.cards
id: mod:parrot.integrations.msagentsdk.cards
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deterministic Adaptive Card renderer for the Semantic UI Model (FEAT-303).
relates_to:
- concept: class:parrot.integrations.msagentsdk.cards.CardRenderError
  rel: defines
- concept: func:parrot.integrations.msagentsdk.cards.build_card_attachment
  rel: defines
- concept: func:parrot.integrations.msagentsdk.cards.render_card
  rel: defines
- concept: func:parrot.integrations.msagentsdk.cards.render_text
  rel: defines
- concept: mod:parrot.integrations.msagentsdk.semantic
  rel: references
---

# `parrot.integrations.msagentsdk.cards`

Deterministic Adaptive Card renderer for the Semantic UI Model (FEAT-303).

Pure functions turning a :class:`~parrot.integrations.msagentsdk.semantic.
SemanticUIResult` into Adaptive Card 1.4 JSON (plain ``dict``), plus a total
plain-text fallback (:func:`render_text`) that never raises.

This module must be importable without ``microsoft_agents.*`` installed —
cards are plain dicts here; wrapping them in SDK ``Activity`` objects is the
bridge's job (``agent.py``, TASK-1753).

## Classes

- **`CardRenderError(Exception)`** — Raised when a `SemanticUIResult` cannot be rendered within limits.

## Functions

- `def render_card(result: SemanticUIResult, *, max_table_rows: int=15, max_card_bytes: int=25000) -> dict` — Render a `SemanticUIResult` as Adaptive Card 1.4 JSON.
- `def render_text(result: SemanticUIResult) -> str` — Render a `SemanticUIResult` as plain/markdown text.
- `def build_card_attachment(card: dict) -> dict` — Wrap card JSON in the Bot Framework attachment envelope.

---
type: Wiki Summary
title: parrot.auth.confirmation
id: mod:parrot.auth.confirmation
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Confirmation subsystem for per-call HITL tool-call review (FEAT-235).
relates_to:
- concept: class:parrot.auth.confirmation.ConfirmationConfig
  rel: defines
- concept: class:parrot.auth.confirmation.ConfirmationDecision
  rel: defines
- concept: class:parrot.auth.confirmation.ConfirmationGuard
  rel: defines
- concept: class:parrot.auth.confirmation.ConfirmationWindowStore
  rel: defines
- concept: class:parrot.auth.confirmation.InMemoryConfirmationWindowStore
  rel: defines
- concept: func:parrot.auth.confirmation.build_form_schema
  rel: defines
- concept: func:parrot.auth.confirmation.compute_args_hash
  rel: defines
- concept: func:parrot.auth.confirmation.render_briefing
  rel: defines
- concept: func:parrot.auth.confirmation.revalidate_edit
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.core.exceptions
  rel: references
- concept: mod:parrot.human.manager
  rel: references
- concept: mod:parrot.human.models
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.auth.confirmation`

Confirmation subsystem for per-call HITL tool-call review (FEAT-235).

This module implements the confirm-before-execute lifecycle:
  routing_meta gate → window check → briefing render → HITL ask → result mapping

Key types:
  - ConfirmationConfig: Configurable defaults (window, timeout, channel, retries).
  - ConfirmationDecision: Result returned by ConfirmationGuard.confirm().
  - ConfirmationWindowStore: Abstract window persistence (keyed by owner/tool/args).
  - InMemoryConfirmationWindowStore: asyncio.Lock-guarded dict with TTL expiry.
  - ConfirmationGuard: The Governor — asks HITL before each confirmed tool call.
  - compute_args_hash: Stable hash over normalized parameters for window keying.

Design notes:
  - Structurally mirrors ``parrot/auth/grants.py`` (GrantGuard) so the two guards
    stay symmetric and wiring patterns are identical.
  - Fail-closed: ``requires_confirmation`` + no HITL channel → cancelled immediately.
  - Dispatch order in ToolManager: grant → confirm (authorization before review).
  - ``window_seconds=0`` (default) means always re-ask — the safe default.

## Classes

- **`ConfirmationConfig(BaseModel)`** — Configurable defaults for the confirmation subsystem.
- **`ConfirmationDecision(BaseModel)`** — Result of ConfirmationGuard.confirm().
- **`ConfirmationWindowStore(ABC)`** — Abstract window persistence for the confirmation subsystem.
- **`InMemoryConfirmationWindowStore(ConfirmationWindowStore)`** — asyncio.Lock-guarded dict-backed window store with TTL expiry.
- **`ConfirmationGuard`** — The Governor: asks a human to confirm each marked tool call.

## Functions

- `def compute_args_hash(parameters: dict) -> str` — Produce a stable SHA-256 hash over normalized parameters.
- `def render_briefing(tool: 'AbstractTool', parameters: dict) -> str` — Render a confirmation briefing string for the tool call.
- `def build_form_schema(tool: 'AbstractTool', parameters: dict) -> dict` — Build a FORM interaction schema from the tool's args_schema.
- `def revalidate_edit(tool: 'AbstractTool', edited: dict) -> dict` — Validate edited values against the tool's args_schema.

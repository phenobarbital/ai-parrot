---
type: Wiki Summary
title: parrot.integrations.a2ui_resume
id: mod:parrot.integrations.a2ui_resume
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-channel A2UI deep-link resume helper (Module 8, channel half).
relates_to:
- concept: class:parrot.integrations.a2ui_resume.ChannelDeepLinkResume
  rel: defines
- concept: func:parrot.integrations.a2ui_resume.build_structured_message
  rel: defines
- concept: mod:parrot.outputs.a2ui.deeplink
  rel: references
---

# `parrot.integrations.a2ui_resume`

Per-channel A2UI deep-link resume helper (Module 8, channel half).

Deep links on baked surfaces resume the ORIGINATING channel/session. TASK-1735 shipped
:class:`~parrot.outputs.a2ui.deeplink.DeepLinkService` and the web route; this helper
encapsulates the shared per-channel resume flow (consume → structured user message →
inject → friendly failure) used by the Telegram and MS Teams wrappers, so each wrapper
only needs a thin detection hook.

The action is injected as a **structured user message** (not dispatched) — action
dispatch / ActionRouter is FEAT-B.

## Classes

- **`ChannelDeepLinkResume`** — Shared per-channel deep-link resume flow for Telegram / MS Teams.

## Functions

- `def build_structured_message(action_payload: dict[str, Any]) -> str` — Serialize a resumed action into a structured user-message query string.

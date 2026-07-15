---
type: Wiki Summary
title: parrot.integrations.slack.interactive
id: mod:parrot.integrations.slack.interactive
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Interactive Block Kit handler for Slack integration.
relates_to:
- concept: class:parrot.integrations.slack.interactive.ActionRegistry
  rel: defines
- concept: class:parrot.integrations.slack.interactive.SlackInteractiveHandler
  rel: defines
- concept: func:parrot.integrations.slack.interactive.build_clear_button
  rel: defines
- concept: func:parrot.integrations.slack.interactive.build_feedback_blocks
  rel: defines
- concept: mod:parrot.integrations.slack.wrapper
  rel: references
---

# `parrot.integrations.slack.interactive`

Interactive Block Kit handler for Slack integration.

Handles all interactive payloads from Slack Block Kit including:
- Button clicks (block_actions)
- Modal submissions (view_submission)
- Shortcuts and message actions
- Feedback collection

Part of FEAT-010: Slack Wrapper Integration Enhancements.

## Classes

- **`ActionRegistry`** — Registry for Block Kit action handlers.
- **`SlackInteractiveHandler`** — Handles all interactive payloads from Slack Block Kit.

## Functions

- `def build_feedback_blocks(message_id: str='') -> List[dict]` — Build feedback buttons to append to agent responses.
- `def build_clear_button() -> dict` — Build a clear conversation button.

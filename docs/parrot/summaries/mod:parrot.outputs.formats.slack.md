---
type: Wiki Summary
title: parrot.outputs.formats.slack
id: mod:parrot.outputs.formats.slack
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Slack output renderer.
relates_to:
- concept: class:parrot.outputs.formats.slack.SlackRenderer
  rel: defines
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.outputs.formats.base
  rel: references
---

# `parrot.outputs.formats.slack`

Slack output renderer.

Lightweight renderer that extracts plain text for Slack delivery.
Slack-specific mrkdwn formatting is handled downstream by the
SlackAgentWrapper._build_blocks() method via the ParsedResponse parser.

## Classes

- **`SlackRenderer(BaseRenderer)`** — Renderer for Slack output — returns plain text / markdown.

---
type: Concept
title: convert_markdown_to_mrkdwn()
id: func:parrot.integrations.slack.wrapper.convert_markdown_to_mrkdwn
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert standard Markdown to Slack mrkdwn format.
---

# convert_markdown_to_mrkdwn

```python
def convert_markdown_to_mrkdwn(text: str) -> str
```

Convert standard Markdown to Slack mrkdwn format.

Slack's mrkdwn is a subset of Markdown with different syntax:
- Bold: **text** → *text*
- Italic: *text* / _text_ → _text_
- Links: [label](url) → <url|label>
- Headings: # Heading → *Heading*
- Bullets: - item / * item → • item
- Horizontal rules: --- → (removed)

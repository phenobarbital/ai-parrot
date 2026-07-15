---
type: Concept
title: build_feedback_blocks()
id: func:parrot.integrations.slack.interactive.build_feedback_blocks
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build feedback buttons to append to agent responses.
---

# build_feedback_blocks

```python
def build_feedback_blocks(message_id: str='') -> List[dict]
```

Build feedback buttons to append to agent responses.

Creates a divider and action buttons for thumbs up/down feedback.

Args:
    message_id: Optional message timestamp to track which message
               the feedback is for.

Returns:
    List of Block Kit blocks (divider + actions).

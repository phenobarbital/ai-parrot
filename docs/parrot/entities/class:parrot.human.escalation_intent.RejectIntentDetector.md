---
type: Wiki Entity
title: RejectIntentDetector
id: class:parrot.human.escalation_intent.RejectIntentDetector
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Detects escalation intent from free-text user responses.
---

# RejectIntentDetector

Defined in [`parrot.human.escalation_intent`](../summaries/mod:parrot.human.escalation_intent.md).

```python
class RejectIntentDetector
```

Detects escalation intent from free-text user responses.

Usage::

    detector = RejectIntentDetector()
    if await detector.is_escalation_intent("I need a human"):
        ...

Args:
    regex_phrases: Override the default phrase list (list of regex strings).
        When provided, REPLACES (not extends) the defaults.
    llm_client: Optional async callable used as LLM fallback.  It is
        invoked as ``await llm_client(text) -> bool`` for short texts
        (< 80 chars) that do not match regex.  When ``None`` (default),
        the LLM fallback is disabled.
    llm_timeout_seconds: Maximum wait for the LLM response before
        returning ``False`` (default 1.5 s).

## Methods

- `async def is_escalation_intent(self, text: Any) -> bool` — Return True if *text* expresses a desire to escalate to a human.

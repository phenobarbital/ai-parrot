---
type: Concept
title: render_reply_text()
id: func:parrot.integrations.msagentsdk.agent.render_reply_text
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Produce human-readable reply text from an ``AIMessage``.
---

# render_reply_text

```python
def render_reply_text(response: Any) -> str
```

Produce human-readable reply text from an ``AIMessage``.

``parrot_agent.ask()`` returns an :class:`~parrot.models.responses.AIMessage`
whose ``content``/``output`` is a *structured Pydantic model* whenever the
bot is configured with a ``structured_output`` schema. ``str()`` of such a
model yields its field-by-field repr — e.g.
``explanation='...' data=None code=None metadata=None`` — which leaks into
the channel as garbled pseudo-JSON instead of a clean message. This helper
resolves the model's natural-language text instead, in priority order:

1. ``AIMessage.response`` — the plain-text response the model produced
   before any structured reformatting (``AIMessageFactory`` sets this from
   the raw ``text_response``).
2. ``AIMessage.content`` when it is already a plain string — the common
   no-structured-output case (``content`` aliases ``output``).
3. A text-ish field pulled from the structured payload
   (``structured_output`` first, then ``output``) — covers arbitrary
   downstream schemas that carry their prose in a named field
   (``explanation``, ``answer``, ``text`` …).
4. ``AIMessage.to_text`` — handles dict / DataFrame outputs.
5. ``str(response.content)`` as an absolute last resort (preserves the
   legacy behaviour for any non-string, non-model content).

Args:
    response: The object returned by ``parrot_agent.ask()`` (normally an
        ``AIMessage``); may be any object or ``None``.

Returns:
    A display string safe to send verbatim to the channel. Returns an empty
    string only when *response* itself is falsy.

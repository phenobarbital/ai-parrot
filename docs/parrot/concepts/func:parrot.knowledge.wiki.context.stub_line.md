---
type: Concept
title: stub_line()
id: func:parrot.knowledge.wiki.context.stub_line
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Render one search result as a compact single-line stub.
---

# stub_line

```python
def stub_line(result: dict[str, Any]) -> str
```

Render one search result as a compact single-line stub.

Format::

    - [<id>] <title> — <lead sentence> (score=0.87, ~120tok)

The token figure is the cost of reading the FULL page via
``wiki_read`` — it lets the model budget its next move.

Args:
    result: Result dict with at least an id field; ``score``,
        ``snippet``/``summary``, and ``token_count`` are optional.

Returns:
    The rendered stub line.

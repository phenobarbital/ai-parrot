---
type: Concept
title: build_transport()
id: func:parrot_tools.odoo.transport.detect.build_transport
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a transport for an explicit protocol choice.
---

# build_transport

```python
def build_transport(protocol: Protocol, config: OdooConfig) -> AbstractOdooTransport | None
```

Build a transport for an explicit protocol choice.

Returns ``None`` for ``"auto"`` — callers must invoke
:func:`auto_detect_transport` instead, which is async.

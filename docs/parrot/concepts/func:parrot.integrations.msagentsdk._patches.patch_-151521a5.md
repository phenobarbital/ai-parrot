---
type: Concept
title: patch_mcs_connector_empty_response()
id: func:parrot.integrations.msagentsdk._patches.patch_mcs_connector_empty_response
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Make the MCS connector tolerate an empty / non-JSON 200 response.
---

# patch_mcs_connector_empty_response

```python
def patch_mcs_connector_empty_response() -> None
```

Make the MCS connector tolerate an empty / non-JSON 200 response.

When an agent reply is sent through Microsoft Copilot Studio's
``pva-studio`` channel, the SDK's ``MCSConversations.send_to_conversation``
POSTs the activity to the Power Apps runtime and then calls
``response.json()`` unconditionally. The runtime acknowledges a successful
delivery with **HTTP 200 but an empty body and no ``Content-Type``**, so
aiohttp raises ``ContentTypeError`` ("Attempt to decode JSON with
unexpected mimetype") — even though the message was delivered fine. The
error then bubbles up, the turn fails, and the SDK retries (sending the
reply several times).

This patch replaces ``send_to_conversation`` with a version that reads the
body defensively: it still raises on real HTTP errors (status >= 300), but
treats an empty or non-JSON success body as an empty ``ResourceResponse``
instead of crashing.

Idempotent: safe to call multiple times. A no-op if the SDK is not
installed or its internals have changed shape.

---
type: Concept
title: register_pull_request_webhook()
id: func:parrot.flows.dev_loop.webhook.register_pull_request_webhook
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register the GitHub ``pull_request.closed`` webhook handler.
---

# register_pull_request_webhook

```python
def register_pull_request_webhook(orchestrator: Any, *, secret: str, path: str='/github/dev-loop', target_id: str='dev-loop-cleanup') -> None
```

Register the GitHub ``pull_request.closed`` webhook handler.

Args:
    orchestrator: A :class:`parrot.autonomous.AutonomousOrchestrator`.
    secret: HMAC secret configured on the GitHub webhook.
    path: HTTP path for the listener (default ``/github/dev-loop``).
    target_id: Logical target id used by the orchestrator's
        WebhookListener to dispatch to the cleanup helper.

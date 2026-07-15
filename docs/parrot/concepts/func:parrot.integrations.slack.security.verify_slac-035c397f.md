---
type: Concept
title: verify_slack_signature_raw()
id: func:parrot.integrations.slack.security.verify_slack_signature_raw
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Verify that an incoming request actually comes from Slack.
---

# verify_slack_signature_raw

```python
def verify_slack_signature_raw(raw_body: bytes, headers: Mapping[str, str], signing_secret: Optional[str], max_age_seconds: int=300) -> bool
```

Verify that an incoming request actually comes from Slack.

Uses HMAC-SHA256 to validate the X-Slack-Signature header against the
request body and timestamp. This prevents request forgery attacks.

Args:
    raw_body: The raw request body bytes (must be unparsed).
    headers: The request headers mapping (case-sensitive lookup).
    signing_secret: The Slack app's signing secret from app credentials.
        If empty/None, verification is skipped (dev mode).
    max_age_seconds: Maximum allowed age of the request in seconds.
        Defaults to 300 (5 minutes) to prevent replay attacks.

Returns:
    True if the signature is valid or dev mode is enabled.
    False if verification fails for any reason.

Example:
    >>> headers = {
    ...     "X-Slack-Request-Timestamp": "1234567890",
    ...     "X-Slack-Signature": "v0=abc123...",
    ... }
    >>> verify_slack_signature_raw(b'{"type": "event"}', headers, "secret")
    True

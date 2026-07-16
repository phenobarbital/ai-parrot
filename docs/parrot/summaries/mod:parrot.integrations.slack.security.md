---
type: Wiki Summary
title: parrot.integrations.slack.security
id: mod:parrot.integrations.slack.security
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Slack request signature verification.
relates_to:
- concept: func:parrot.integrations.slack.security.verify_slack_signature_raw
  rel: defines
---

# `parrot.integrations.slack.security`

Slack request signature verification.

This module provides HMAC-SHA256 signature verification to secure
Slack webhook endpoints against spoofing attacks.

Reference: https://api.slack.com/authentication/verifying-requests-from-slack

## Functions

- `def verify_slack_signature_raw(raw_body: bytes, headers: Mapping[str, str], signing_secret: Optional[str], max_age_seconds: int=300) -> bool` — Verify that an incoming request actually comes from Slack.

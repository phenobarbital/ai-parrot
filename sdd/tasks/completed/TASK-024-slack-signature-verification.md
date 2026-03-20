# TASK-024: Slack Signature Verification Module

**Feature**: Slack Wrapper Integration Enhancements
**Spec**: `sdd/specs/slack-wrapper-integration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task implements HMAC-SHA256 signature verification to secure the Slack webhook endpoint.
> Reference: Spec Section 1 (Verification de Firma de Slack) and Section 3 (Module 1).

Currently, any HTTP request to the Slack webhook is processed without verification. This is a critical security vulnerability that allows spoofing attacks. Slack signs all requests with HMAC-SHA256 using the app's signing secret.

---

## Scope

- Create `parrot/integrations/slack/security.py` module
- Implement `verify_slack_signature_raw()` function
- Validate timestamp to prevent replay attacks (max 5 minutes)
- Use `hmac.compare_digest()` for timing-safe comparison
- Log verification failures with appropriate detail

**NOT in scope**:
- Integrating into wrapper.py (TASK-024)
- Rate limiting or IP-based blocking
- OAuth flow verification

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/security.py` | CREATE | Signature verification module |
| `tests/unit/test_slack_security.py` | CREATE | Unit tests |
| `parrot/integrations/slack/__init__.py` | MODIFY | Export verify function |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/integrations/slack/security.py
"""Slack request signature verification."""
import hashlib
import hmac
import time
import logging
from typing import Mapping

logger = logging.getLogger("SlackSecurity")


def verify_slack_signature_raw(
    raw_body: bytes,
    headers: Mapping[str, str],
    signing_secret: str,
    max_age_seconds: int = 300,
) -> bool:
    """
    Verify that an incoming request actually comes from Slack.

    Uses HMAC-SHA256 to validate the X-Slack-Signature header.

    Args:
        raw_body: The raw request body bytes.
        headers: The request headers mapping.
        signing_secret: The Slack app's signing secret.
        max_age_seconds: Maximum allowed age of the request (default: 5 min).

    Returns:
        True if verified, False otherwise.
    """
    if not signing_secret:
        logger.warning("No signing_secret configured — skipping verification")
        return True  # Allow in dev mode

    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")

    if not timestamp or not signature:
        logger.warning("Missing Slack signature headers")
        return False

    # Replay attack protection
    try:
        if abs(time.time() - int(timestamp)) > max_age_seconds:
            logger.warning("Slack request timestamp too old: %s", timestamp)
            return False
    except ValueError:
        logger.warning("Invalid timestamp format: %s", timestamp)
        return False

    # Compute HMAC-SHA256
    sig_basestring = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed, signature):
        logger.warning("Slack signature verification failed")
        return False

    return True
```

### Key Constraints
- Must use `hmac.compare_digest()` for timing-safe comparison
- Must reject timestamps older than 5 minutes (configurable)
- Must handle missing headers gracefully
- Must log failures without exposing secrets

### References in Codebase
- Slack signing verification docs: https://api.slack.com/authentication/verifying-requests-from-slack
- Similar pattern in `parrot/integrations/telegram/` (token verification)

---

## Acceptance Criteria

- [x] `verify_slack_signature_raw()` returns True for valid signatures
- [x] Returns False for invalid signatures
- [x] Returns False for expired timestamps (> 5 min)
- [x] Returns False for missing headers
- [x] Returns True when `signing_secret` is empty (dev mode)
- [x] All tests pass: `pytest tests/unit/test_slack_security.py -v` (16 tests)
- [x] No linting errors: `ruff check parrot/integrations/slack/security.py`
- [x] Import works: `from parrot.integrations.slack.security import verify_slack_signature_raw`

---

## Test Specification

```python
# tests/unit/test_slack_security.py
import pytest
import time
import hmac
import hashlib
from parrot.integrations.slack.security import verify_slack_signature_raw


def make_signature(body: bytes, timestamp: str, secret: str) -> str:
    sig_base = f"v0:{timestamp}:{body.decode()}"
    return "v0=" + hmac.new(
        secret.encode(), sig_base.encode(), hashlib.sha256
    ).hexdigest()


class TestSlackSignatureVerification:
    def test_valid_signature(self):
        """Valid signature passes verification."""
        secret = "test_secret_123"
        body = b'{"type": "event_callback"}'
        timestamp = str(int(time.time()))
        signature = make_signature(body, timestamp, secret)

        headers = {
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        }

        assert verify_slack_signature_raw(body, headers, secret) is True

    def test_invalid_signature(self):
        """Invalid signature fails verification."""
        body = b'{"type": "event_callback"}'
        headers = {
            "X-Slack-Request-Timestamp": str(int(time.time())),
            "X-Slack-Signature": "v0=invalid_signature",
        }

        assert verify_slack_signature_raw(body, headers, "secret") is False

    def test_expired_timestamp(self):
        """Timestamp older than 5 minutes is rejected."""
        secret = "test_secret"
        body = b'{"test": "data"}'
        old_timestamp = str(int(time.time()) - 400)  # 6+ minutes ago
        signature = make_signature(body, old_timestamp, secret)

        headers = {
            "X-Slack-Request-Timestamp": old_timestamp,
            "X-Slack-Signature": signature,
        }

        assert verify_slack_signature_raw(body, headers, secret) is False

    def test_missing_headers(self):
        """Missing signature headers return False."""
        assert verify_slack_signature_raw(b'{}', {}, "secret") is False
        assert verify_slack_signature_raw(
            b'{}', {"X-Slack-Request-Timestamp": "123"}, "secret"
        ) is False

    def test_no_secret_allows_all(self):
        """Empty signing_secret allows all requests (dev mode)."""
        assert verify_slack_signature_raw(b'{}', {}, "") is True
        assert verify_slack_signature_raw(b'{}', {}, None) is True

    def test_invalid_timestamp_format(self):
        """Non-numeric timestamp is rejected."""
        headers = {
            "X-Slack-Request-Timestamp": "not-a-number",
            "X-Slack-Signature": "v0=abc",
        }
        assert verify_slack_signature_raw(b'{}', headers, "secret") is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-024-slack-signature-verification.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**:
- Created `parrot/integrations/slack/security.py` with `verify_slack_signature_raw()` function
- Added comprehensive test suite with 16 tests covering all edge cases
- Added additional tests beyond spec: future timestamps, custom max_age, tampered body, wrong secret, signature version mismatch, unicode bodies, large bodies, case-sensitive headers
- Updated `parrot/integrations/slack/__init__.py` to export the function
- All tests pass, no linting errors

**Deviations from spec**:
- Added `Optional[str]` type hint for `signing_secret` parameter to explicitly support `None`
- Added UTF-8 decode error handling for malformed request bodies
- Added more detailed logging with timestamp age in warning messages

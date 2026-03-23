"""Slack request signature verification.

This module provides HMAC-SHA256 signature verification to secure
Slack webhook endpoints against spoofing attacks.

Reference: https://api.slack.com/authentication/verifying-requests-from-slack
"""
import hashlib
import hmac
import logging
import time
from typing import Mapping, Optional

logger = logging.getLogger("SlackSecurity")


def verify_slack_signature_raw(
    raw_body: bytes,
    headers: Mapping[str, str],
    signing_secret: Optional[str],
    max_age_seconds: int = 300,
) -> bool:
    """
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
    """
    # Dev mode: skip verification if no secret configured
    if not signing_secret:
        logger.warning("No signing_secret configured — skipping verification")
        return True

    # Extract required headers
    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")

    if not timestamp or not signature:
        logger.warning("Missing Slack signature headers")
        return False

    # Replay attack protection: reject old timestamps
    try:
        request_time = int(timestamp)
        current_time = time.time()
        if abs(current_time - request_time) > max_age_seconds:
            logger.warning(
                "Slack request timestamp too old: %s (age: %d seconds)",
                timestamp,
                int(abs(current_time - request_time)),
            )
            return False
    except ValueError:
        logger.warning("Invalid timestamp format: %s", timestamp)
        return False

    # Compute expected signature using HMAC-SHA256
    # Format: v0:{timestamp}:{body}
    try:
        sig_basestring = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
    except UnicodeDecodeError:
        logger.warning("Failed to decode request body as UTF-8")
        return False

    computed = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Timing-safe comparison to prevent timing attacks
    if not hmac.compare_digest(computed, signature):
        logger.warning("Slack signature verification failed")
        return False

    return True

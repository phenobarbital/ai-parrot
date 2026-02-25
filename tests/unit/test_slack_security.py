"""Unit tests for Slack signature verification.

Tests the HMAC-SHA256 signature verification module.
"""
import hashlib
import hmac
import time

from parrot.integrations.slack.security import verify_slack_signature_raw


def make_signature(body: bytes, timestamp: str, secret: str) -> str:
    """Generate a valid Slack signature for testing."""
    sig_base = f"v0:{timestamp}:{body.decode()}"
    return "v0=" + hmac.new(
        secret.encode(), sig_base.encode(), hashlib.sha256
    ).hexdigest()


class TestSlackSignatureVerification:
    """Tests for verify_slack_signature_raw function."""

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

    def test_future_timestamp_within_window(self):
        """Timestamp slightly in the future is accepted (clock skew)."""
        secret = "test_secret"
        body = b'{"test": "data"}'
        future_timestamp = str(int(time.time()) + 60)  # 1 minute in future
        signature = make_signature(body, future_timestamp, secret)

        headers = {
            "X-Slack-Request-Timestamp": future_timestamp,
            "X-Slack-Signature": signature,
        }

        assert verify_slack_signature_raw(body, headers, secret) is True

    def test_future_timestamp_too_far(self):
        """Timestamp too far in the future is rejected."""
        secret = "test_secret"
        body = b'{"test": "data"}'
        future_timestamp = str(int(time.time()) + 400)  # 6+ minutes in future
        signature = make_signature(body, future_timestamp, secret)

        headers = {
            "X-Slack-Request-Timestamp": future_timestamp,
            "X-Slack-Signature": signature,
        }

        assert verify_slack_signature_raw(body, headers, secret) is False

    def test_missing_headers(self):
        """Missing signature headers return False."""
        assert verify_slack_signature_raw(b'{}', {}, "secret") is False
        assert verify_slack_signature_raw(
            b'{}', {"X-Slack-Request-Timestamp": "123"}, "secret"
        ) is False
        assert verify_slack_signature_raw(
            b'{}', {"X-Slack-Signature": "v0=abc"}, "secret"
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

    def test_empty_timestamp(self):
        """Empty timestamp is rejected."""
        headers = {
            "X-Slack-Request-Timestamp": "",
            "X-Slack-Signature": "v0=abc",
        }
        assert verify_slack_signature_raw(b'{}', headers, "secret") is False

    def test_custom_max_age(self):
        """Custom max_age_seconds is respected."""
        secret = "test_secret"
        body = b'{"test": "data"}'
        # 2 minutes old
        old_timestamp = str(int(time.time()) - 120)
        signature = make_signature(body, old_timestamp, secret)

        headers = {
            "X-Slack-Request-Timestamp": old_timestamp,
            "X-Slack-Signature": signature,
        }

        # Should pass with 5 minute window (default)
        assert verify_slack_signature_raw(body, headers, secret) is True
        # Should fail with 1 minute window
        assert verify_slack_signature_raw(body, headers, secret, max_age_seconds=60) is False

    def test_tampered_body(self):
        """Modified body fails verification."""
        secret = "test_secret"
        original_body = b'{"type": "event_callback"}'
        timestamp = str(int(time.time()))
        signature = make_signature(original_body, timestamp, secret)

        headers = {
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        }

        # Use different body
        tampered_body = b'{"type": "malicious"}'
        assert verify_slack_signature_raw(tampered_body, headers, secret) is False

    def test_wrong_secret(self):
        """Wrong signing secret fails verification."""
        correct_secret = "correct_secret"
        wrong_secret = "wrong_secret"
        body = b'{"test": "data"}'
        timestamp = str(int(time.time()))
        signature = make_signature(body, timestamp, correct_secret)

        headers = {
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        }

        assert verify_slack_signature_raw(body, headers, wrong_secret) is False

    def test_signature_version_mismatch(self):
        """Wrong signature version fails verification."""
        secret = "test_secret"
        body = b'{"test": "data"}'
        timestamp = str(int(time.time()))
        # Create v1 signature instead of v0
        sig_base = f"v1:{timestamp}:{body.decode()}"
        signature = "v1=" + hmac.new(
            secret.encode(), sig_base.encode(), hashlib.sha256
        ).hexdigest()

        headers = {
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        }

        assert verify_slack_signature_raw(body, headers, secret) is False

    def test_unicode_body(self):
        """UTF-8 body with special characters works correctly."""
        secret = "test_secret"
        body = '{"text": "Hello 🎉 Ñoño"}'.encode('utf-8')
        timestamp = str(int(time.time()))
        signature = make_signature(body, timestamp, secret)

        headers = {
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        }

        assert verify_slack_signature_raw(body, headers, secret) is True

    def test_large_body(self):
        """Large request bodies are handled correctly."""
        secret = "test_secret"
        body = b'{"data": "' + b'x' * 100000 + b'"}'
        timestamp = str(int(time.time()))
        signature = make_signature(body, timestamp, secret)

        headers = {
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        }

        assert verify_slack_signature_raw(body, headers, secret) is True

    def test_case_sensitive_headers(self):
        """Headers are case-sensitive (as per HTTP/2)."""
        secret = "test_secret"
        body = b'{"test": "data"}'
        timestamp = str(int(time.time()))
        signature = make_signature(body, timestamp, secret)

        # Wrong case should fail
        wrong_case_headers = {
            "x-slack-request-timestamp": timestamp,
            "x-slack-signature": signature,
        }
        assert verify_slack_signature_raw(body, wrong_case_headers, secret) is False

"""Tests for OutputScrubber policy + single-seam hook (FEAT-252 / TASK-1612)."""
from __future__ import annotations

import pytest

from parrot.security.redaction import OutputScrubber, ScrubPolicy


@pytest.fixture
def scrubber():
    """Default OutputScrubber with default ScrubPolicy."""
    return OutputScrubber(ScrubPolicy())


class TestOutputScrubber:
    """Unit tests for OutputScrubber."""

    def test_import_resolves(self):
        """Ensure the symbols are importable from the expected locations."""
        from parrot.security.redaction import OutputScrubber, ScrubPolicy  # noqa: F401
        from parrot.security import OutputScrubber as OS2, ScrubPolicy as SP2  # noqa: F401
        assert OS2 is OutputScrubber
        assert SP2 is ScrubPolicy

    def test_env_dump_redacted(self, scrubber):
        """KeysView / environ patterns trigger env_dump redaction."""
        s = "KeysView(environ({'ODOO_EPSON_PRODUCTION_PASSWORD': 's3cr3t'}))"
        out = scrubber.scrub(s)
        assert "s3cr3t" not in out
        assert "REDACTED" in out

    def test_os_environ_pattern_redacted(self, scrubber):
        """os.environ reference triggers env_dump redaction."""
        s = "os.environ.keys() returned many secrets"
        out = scrubber.scrub(s)
        assert "REDACTED" in out

    def test_idempotent(self, scrubber):
        """Re-scrubbing a scrubbed string is a no-op."""
        s = "PASSWORD=hunter2"
        once = scrubber.scrub(s)
        twice = scrubber.scrub(once)
        assert twice == once

    def test_idempotent_multiple_secrets(self, scrubber):
        """Idempotency holds for compound strings."""
        s = "API_KEY=AKIAABCDEFGHIJKLMNOP"
        assert scrubber.scrub(scrubber.scrub(s)) == scrubber.scrub(s)

    def test_audit_never_logs_value(self, scrubber, caplog):
        """Audit log records the tag but NEVER the secret value."""
        import logging
        with caplog.at_level(logging.WARNING, logger="parrot.security.redaction"):
            scrubber.scrub("API_KEY=AKIAABCDEFGHIJKLMNOP")
        # The secret must not appear in logs
        assert "AKIAABCDEFGHIJKLMNOP" not in caplog.text
        # But a redaction event must have been recorded
        assert "OutputScrubber" in caplog.text or "REDACTED" in caplog.text or len(caplog.records) > 0

    def test_recurses_structures_dict(self, scrubber):
        """Dicts with sensitive keys have their values scrubbed."""
        out = scrubber.scrub({"token": "abc123", "ok": "plain"})
        assert out["token"] != "abc123"
        assert "REDACTED" in str(out["token"])
        assert out["ok"] == "plain"

    def test_recurses_structures_nested(self, scrubber):
        """Nested dicts and lists are recursively scrubbed."""
        out = scrubber.scrub({"ok": [{"secret": "xyz"}]})
        assert out["ok"][0]["secret"] != "xyz"

    def test_recurses_list(self, scrubber):
        """Lists are recursively scrubbed."""
        out = scrubber.scrub(["PASSWORD=s3cr3t_value", "plain"])
        assert "s3cr3t_value" not in out[0]
        assert out[1] == "plain"

    def test_recurses_tuple(self, scrubber):
        """Tuples are recursively scrubbed."""
        out = scrubber.scrub(("TOKEN=abcdefgh12345", "ok"))
        assert "abcdefgh12345" not in str(out[0])
        assert out[1] == "ok"

    def test_reason_tag_format(self, scrubber):
        """Reason-tagged markers follow the ***REDACTED:<reason>*** format."""
        out = scrubber.scrub("PASSWORD=hunter2")
        assert "***REDACTED:" in out

    def test_no_reason_tag_when_disabled(self):
        """With reason_tags=False, plain [REDACTED] marker is used."""
        scrubber_plain = OutputScrubber(ScrubPolicy(reason_tags=False))
        out = scrubber_plain.scrub("PASSWORD=hunter2")
        assert "[REDACTED]" in out
        assert "***REDACTED:" not in out

    def test_allowlist_exempts_substring(self):
        """Strings containing an allowlisted substring are not scrubbed."""
        policy = ScrubPolicy(allowlist=frozenset({"token="}))
        scrubber = OutputScrubber(policy)
        s = "This ticket mentions token= as a documentation example"
        assert scrubber.scrub(s) == s

    def test_non_string_scalar_passthrough(self, scrubber):
        """Non-string, non-collection scalars pass through unchanged."""
        assert scrubber.scrub(42) == 42
        assert scrubber.scrub(3.14) == 3.14
        assert scrubber.scrub(None) is None
        assert scrubber.scrub(True) is True

    def test_bearer_token_redacted(self, scrubber):
        """Bearer tokens are scrubbed."""
        out = scrubber.scrub("Authorization: Bearer eyABCDEF123456789012")
        assert "eyABCDEF123456789012" not in out

    def test_aws_key_redacted(self, scrubber):
        """AWS access keys (AKIA…) are scrubbed."""
        out = scrubber.scrub("key = AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in out

    def test_dsn_redacted(self, scrubber):
        """DSN strings with embedded credentials are scrubbed."""
        out = scrubber.scrub("postgres://user:s3cr3t@db.internal/mydb")
        assert "s3cr3t" not in out

    def test_jwt_redacted(self, scrubber):
        """JWT tokens are scrubbed."""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        out = scrubber.scrub(jwt)
        assert "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c" not in out


class TestScrubPolicy:
    """Tests for the ScrubPolicy dataclass."""

    def test_default_policy(self):
        policy = ScrubPolicy()
        assert policy.reason_tags is True
        assert policy.audit_log is True
        assert len(policy.allowlist) == 0
        assert policy.max_output_bytes == 1_048_576

    def test_frozen(self):
        """ScrubPolicy is immutable."""
        policy = ScrubPolicy()
        with pytest.raises((AttributeError, TypeError)):
            policy.reason_tags = False  # type: ignore[misc]


class TestScrubSeamInAbstractTool:
    """Verify the scrub seam is wired into AbstractTool.execute()."""

    @pytest.mark.asyncio
    async def test_execute_scrubs_result(self):
        """A tool returning a secret string must have it scrubbed by execute()."""
        from parrot.tools.abstract import AbstractTool, ToolResult

        class SecretTool(AbstractTool):
            name = "secret_tool"
            description = "test tool"

            async def _execute(self, **kwargs):
                return "PASSWORD=super_secret_value_123"

        tool = SecretTool()
        tool.enable_redaction = True  # redaction is opt-in per agent
        result = await tool.execute()
        assert isinstance(result, ToolResult)
        assert "super_secret_value_123" not in str(result.result)
        assert "REDACTED" in str(result.result)

    @pytest.mark.asyncio
    async def test_execute_scrubs_dict_result(self):
        """Dict results with secret keys are scrubbed by execute()."""
        from parrot.tools.abstract import AbstractTool

        class DictTool(AbstractTool):
            name = "dict_tool"
            description = "test tool"

            async def _execute(self, **kwargs):
                return {"token": "my_secret_token", "ok": "plain"}

        tool = DictTool()
        tool.enable_redaction = True  # redaction is opt-in per agent
        result = await tool.execute()
        assert "my_secret_token" not in str(result.result)
        assert "plain" in str(result.result)

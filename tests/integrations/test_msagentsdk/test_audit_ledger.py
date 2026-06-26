"""
Unit tests for AuditLedger and AuditEntry.

Covers FEAT-261 Module 6 (AuditLedger).
"""
import hashlib
import pytest
import logging


class TestAuditEntry:
    """Tests for the AuditEntry dataclass."""

    def test_audit_entry_fields(self):
        """AuditEntry stores all fields correctly."""
        from parrot.auth.audit import AuditEntry

        entry = AuditEntry(
            timestamp="2026-06-26T00:00:00Z",
            user_id="00000000-0000-0000-0000-000000000001",
            channel="msagentsdk",
            tool="o365",
            connection="graph_sso",
            key_fingerprint="abc123",
            action="resolve",
        )
        assert entry.timestamp == "2026-06-26T00:00:00Z"
        assert entry.user_id == "00000000-0000-0000-0000-000000000001"
        assert entry.channel == "msagentsdk"
        assert entry.tool == "o365"
        assert entry.connection == "graph_sso"
        assert entry.key_fingerprint == "abc123"
        assert entry.action == "resolve"


class TestAuditLedger:
    """Tests for the AuditLedger class."""

    def test_audit_ledger_records_entry(self):
        """record() appends entry to internal list."""
        from parrot.auth.audit import AuditLedger, AuditEntry

        ledger = AuditLedger()
        entry = AuditEntry(
            timestamp="2026-06-26T00:00:00Z",
            user_id="user-1",
            channel="msagentsdk",
            tool="o365",
            connection="graph_sso",
            key_fingerprint="abc123",
            action="resolve",
        )
        ledger.record(entry)
        assert len(ledger.entries()) == 1
        assert ledger.entries()[0].tool == "o365"

    def test_audit_ledger_entries_returns_copy(self):
        """entries() returns a copy, not the internal list."""
        from parrot.auth.audit import AuditLedger, AuditEntry

        ledger = AuditLedger()
        entry = AuditEntry(
            timestamp="2026-06-26T00:00:00Z",
            user_id="user-1",
            channel="msagentsdk",
            tool="jira",
            connection="jira_oauth",
            key_fingerprint="def456",
            action="resolve",
        )
        ledger.record(entry)
        copy = ledger.entries()
        copy.clear()
        # Original should still have one entry
        assert len(ledger.entries()) == 1

    def test_audit_ledger_logs_json(self, caplog):
        """record() emits a structured JSON log line."""
        from parrot.auth.audit import AuditLedger, AuditEntry

        ledger = AuditLedger()
        entry = AuditEntry(
            timestamp="2026-06-26T00:00:00Z",
            user_id="user-1",
            channel="msagentsdk",
            tool="o365",
            connection="graph_sso",
            key_fingerprint="abc123",
            action="resolve",
        )
        with caplog.at_level(logging.INFO, logger="parrot.auth.audit"):
            ledger.record(entry)
        assert any("AUDIT" in r.message for r in caplog.records)
        assert any("o365" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_audit_ledger_flush_noop(self):
        """flush() completes without error (no-op for log backend)."""
        from parrot.auth.audit import AuditLedger

        ledger = AuditLedger()
        await ledger.flush()  # Should not raise

    def test_audit_ledger_multiple_entries(self):
        """Multiple records are all stored."""
        from parrot.auth.audit import AuditLedger, AuditEntry

        ledger = AuditLedger()
        for i in range(3):
            ledger.record(AuditEntry(
                timestamp=f"2026-06-26T0{i}:00:00Z",
                user_id=f"user-{i}",
                channel="msagentsdk",
                tool="o365",
                connection="graph_sso",
                key_fingerprint=f"fp{i}",
                action="resolve",
            ))
        assert len(ledger.entries()) == 3


class TestKeyFingerprintComputation:
    """Tests for the SHA-256 key fingerprint formula."""

    def test_key_fingerprint_formula(self):
        """SHA-256 of first 8 bytes produces a 64-char hex string."""
        token = "my-secret-token"
        raw = token.encode("utf-8")[:8]
        fingerprint = hashlib.sha256(raw).hexdigest()
        assert len(fingerprint) == 64
        assert fingerprint != token  # fingerprint is not the token itself

    def test_key_fingerprint_not_raw_token(self):
        """Fingerprint is not a simple substring of the token."""
        token = "super-secret-access-token-12345"
        raw = token.encode("utf-8")[:8]
        fingerprint = hashlib.sha256(raw).hexdigest()
        assert token not in fingerprint

    def test_key_fingerprint_deterministic(self):
        """Same token always produces same fingerprint."""
        token = "consistent-token"
        raw = token.encode("utf-8")[:8]
        fp1 = hashlib.sha256(raw).hexdigest()
        fp2 = hashlib.sha256(raw).hexdigest()
        assert fp1 == fp2

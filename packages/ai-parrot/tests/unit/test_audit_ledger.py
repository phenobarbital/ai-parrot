"""Unit tests for AuditLedger (FEAT-260 / TASK-1642).

Tests:
- append/verify round-trip produces a valid KMS signature.
- key_fingerprint is present; raw credential is absent from the entry.
- No mutation API is exposed (append-only).
- LocalHMACSigner signs and verifies correctly.
- derive_key_fingerprint is stable and deterministic.
"""
from __future__ import annotations

import inspect

import pytest

from parrot.security.audit_ledger import (
    AuditLedger,
    AuditLedgerEntry,
    LocalHMACSigner,
    derive_key_fingerprint,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_ledger(secret: bytes = b"test-secret-key-32-bytes-padding!") -> AuditLedger:
    """Return an AuditLedger backed by a deterministic LocalHMACSigner."""
    signer = LocalHMACSigner(secret=secret)
    return AuditLedger(signer=signer)


def _sample_entry_kwargs() -> dict:
    return dict(
        user_id="alice@example.com",
        channel="a2a:copilot",
        tool="jira_create_issue",
        provider="jira",
        credential_material="super-secret-jira-token-xyz",
    )


# ---------------------------------------------------------------------------
# TestAuditLedgerEntry — model shape
# ---------------------------------------------------------------------------


class TestAuditLedgerEntry:
    def test_has_required_fields(self):
        """AuditLedgerEntry exposes the seven spec-required fields."""
        fields = set(AuditLedgerEntry.model_fields.keys())
        assert {
            "entry_id",
            "user_id",
            "channel",
            "tool",
            "provider",
            "key_fingerprint",
            "signature",
            "created_at",
        }.issubset(fields)

    def test_canonical_bytes_excludes_signature(self):
        """canonical_bytes() serialises all fields except `signature`."""
        entry = AuditLedgerEntry(
            user_id="u@e.com",
            channel="a2a:copilot",
            tool="stub_tool",
            provider="stub",
            key_fingerprint="abc123",
            signature="should-not-appear",
        )
        canonical = entry.canonical_bytes().decode()
        assert "should-not-appear" not in canonical
        assert "abc123" in canonical
        assert "u@e.com" in canonical

    def test_canonical_bytes_is_deterministic(self):
        """canonical_bytes() produces the same output on repeated calls."""
        entry = AuditLedgerEntry(
            user_id="u@e.com",
            channel="a2a:copilot",
            tool="stub_tool",
            provider="stub",
            key_fingerprint="abc123",
        )
        assert entry.canonical_bytes() == entry.canonical_bytes()


# ---------------------------------------------------------------------------
# TestDeriveKeyFingerprint
# ---------------------------------------------------------------------------


class TestDeriveKeyFingerprint:
    def test_string_credential(self):
        fp = derive_key_fingerprint("my-token")
        assert len(fp) == 64  # SHA-256 hex
        assert fp == derive_key_fingerprint("my-token")  # deterministic

    def test_bytes_credential(self):
        fp = derive_key_fingerprint(b"my-token")
        # bytes and string encoding of the same content should match
        assert fp == derive_key_fingerprint("my-token")

    def test_dict_credential(self):
        fp = derive_key_fingerprint({"access_token": "tok", "refresh_token": "ref"})
        assert len(fp) == 64

    def test_different_credentials_produce_different_fingerprints(self):
        fp1 = derive_key_fingerprint("token-A")
        fp2 = derive_key_fingerprint("token-B")
        assert fp1 != fp2


# ---------------------------------------------------------------------------
# TestLocalHMACSigner
# ---------------------------------------------------------------------------


class TestLocalHMACSigner:
    @pytest.mark.asyncio
    async def test_sign_and_verify_succeed(self):
        signer = LocalHMACSigner(secret=b"test-key")
        data = b"some canonical bytes"
        sig = await signer.sign(data)
        assert await signer.verify(data, sig)

    @pytest.mark.asyncio
    async def test_wrong_signature_fails(self):
        signer = LocalHMACSigner(secret=b"test-key")
        data = b"data"
        sig = await signer.sign(data)
        tampered = sig[:-4] + "0000"
        assert not await signer.verify(data, tampered)

    @pytest.mark.asyncio
    async def test_different_data_fails(self):
        signer = LocalHMACSigner(secret=b"test-key")
        sig = await signer.sign(b"original")
        assert not await signer.verify(b"tampered", sig)

    def test_default_signer_generates_random_secret(self):
        """Two default LocalHMACSigners have different secrets (random)."""
        s1 = LocalHMACSigner()
        s2 = LocalHMACSigner()
        assert s1._secret != s2._secret


# ---------------------------------------------------------------------------
# TestAuditLedger
# ---------------------------------------------------------------------------


class TestAuditLedger:
    @pytest.mark.asyncio
    async def test_append_then_verify(self):
        """append() + verify() round-trips a valid KMS signature."""
        ledger = _make_ledger()
        entry = await ledger.append(**_sample_entry_kwargs())

        assert entry.entry_id
        assert entry.signature  # non-empty
        assert await ledger.verify(entry.entry_id)

    @pytest.mark.asyncio
    async def test_fingerprint_not_secret(self):
        """Entry carries key_fingerprint; raw credential never appears anywhere."""
        ledger = _make_ledger()
        raw_credential = "super-secret-jira-token-xyz"
        entry = await ledger.append(**_sample_entry_kwargs())

        # The entry must NOT contain the raw credential in any field
        entry_json = entry.model_dump_json()
        assert raw_credential not in entry_json
        assert raw_credential not in entry.key_fingerprint
        assert raw_credential not in entry.signature

        # But the fingerprint is present and is a 64-char hex
        assert len(entry.key_fingerprint) == 64

    @pytest.mark.asyncio
    async def test_verify_unknown_entry_returns_false(self):
        """verify() returns False for a non-existent entry_id."""
        ledger = _make_ledger()
        assert not await ledger.verify("does-not-exist")

    @pytest.mark.asyncio
    async def test_multiple_entries_are_independent(self):
        """Two entries are stored and verified independently."""
        ledger = _make_ledger()
        e1 = await ledger.append(
            user_id="alice@example.com",
            channel="a2a:copilot",
            tool="jira_create",
            provider="jira",
            credential_material="token-alice",
        )
        e2 = await ledger.append(
            user_id="bob@example.com",
            channel="a2a:copilot",
            tool="stub_tool",
            provider="stub",
            credential_material="token-bob",
        )
        assert await ledger.verify(e1.entry_id)
        assert await ledger.verify(e2.entry_id)
        assert ledger.entry_count == 2

    @pytest.mark.asyncio
    async def test_storage_backend_called(self):
        """Optional storage backend receives the serialised entry JSON."""
        stored: list = []

        async def _backend(json_str: str) -> None:
            stored.append(json_str)

        signer = LocalHMACSigner(secret=b"s")
        ledger = AuditLedger(signer=signer, storage=_backend)
        entry = await ledger.append(**_sample_entry_kwargs())

        assert len(stored) == 1
        assert entry.entry_id in stored[0]

    def test_no_mutation_api(self):
        """AuditLedger exposes no update/delete/clear surface."""
        ledger = AuditLedger()
        public_methods = {
            name for name, _ in inspect.getmembers(ledger, predicate=inspect.ismethod)
            if not name.startswith("_")
        }
        forbidden = {"update", "delete", "remove", "clear", "reset", "pop"}
        assert not (public_methods & forbidden), (
            f"Mutation methods found on AuditLedger: {public_methods & forbidden}"
        )

    @pytest.mark.asyncio
    async def test_storage_failure_does_not_raise(self):
        """Storage backend failure is logged but does NOT propagate."""
        async def _failing_backend(json_str: str) -> None:
            raise RuntimeError("DB unavailable")

        signer = LocalHMACSigner(secret=b"s")
        ledger = AuditLedger(signer=signer, storage=_failing_backend)
        # Should not raise — in-memory record is still intact
        entry = await ledger.append(**_sample_entry_kwargs())
        assert await ledger.verify(entry.entry_id)

"""Unit tests for TASK-1675: Audit ledger reconciliation + Azure Key Vault signer.

Tests:
- parrot.security.audit_ledger.AuditLedger is the single canonical ledger
- LocalHMACSigner verify() round-trips an appended entry
- AzureKeyVaultSigner is import-guarded (skips cleanly when SDK absent)
- parrot.auth.audit.AuditLedger emits DeprecationWarning (migration notice)
- Fingerprint semantics preserved (SHA-256, no raw secret)
"""
import warnings

import pytest

from parrot.security.audit_ledger import (
    AuditLedger,
    AuditLedgerEntry,
    AbstractKMSSigner,
    LocalHMACSigner,
    derive_key_fingerprint,
)


# ---------------------------------------------------------------------------
# Canonical ledger: append + verify round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canonical_ledger_append_returns_entry():
    """AuditLedger.append returns a signed AuditLedgerEntry."""
    ledger = AuditLedger()
    entry = await ledger.append(
        user_id="alice@corp.com",
        channel="a2a:copilot",
        tool="jira_create_issue",
        provider="jira",
        credential_material="jira-token-abc123",
    )
    assert isinstance(entry, AuditLedgerEntry)
    assert entry.user_id == "alice@corp.com"
    assert entry.provider == "jira"
    assert entry.signature  # must be signed


@pytest.mark.asyncio
async def test_canonical_ledger_verify_round_trip():
    """verify() returns True for a freshly-appended entry (LocalHMACSigner)."""
    ledger = AuditLedger()
    entry = await ledger.append(
        user_id="alice@corp.com",
        channel="a2a:copilot",
        tool="jira_create_issue",
        provider="jira",
        credential_material="jira-token-abc123",
    )
    is_valid = await ledger.verify(entry.entry_id)
    assert is_valid is True


@pytest.mark.asyncio
async def test_canonical_ledger_never_stores_raw_credential():
    """The raw credential material is NOT stored in the entry."""
    secret = "super-secret-jira-token"
    ledger = AuditLedger()
    entry = await ledger.append(
        user_id="alice@corp.com",
        channel="chat",
        tool="jira",
        provider="jira",
        credential_material=secret,
    )
    # Fingerprint is the SHA-256, not the raw secret
    assert entry.key_fingerprint != secret
    assert len(entry.key_fingerprint) == 64  # SHA-256 hex
    # The secret must not appear in any serialised field
    entry_json = entry.model_dump_json()
    assert secret not in entry_json


@pytest.mark.asyncio
async def test_canonical_ledger_verify_fails_on_tampered_entry():
    """verify() returns False when the signature does not match."""
    ledger = AuditLedger()
    entry = await ledger.append(
        user_id="alice@corp.com",
        channel="a2a:copilot",
        tool="jira_create_issue",
        provider="jira",
        credential_material="token",
    )
    # Tamper with the stored entry
    entry.user_id = "mallory@evil.com"
    ledger._entries[entry.entry_id] = entry

    is_valid = await ledger.verify(entry.entry_id)
    assert is_valid is False


# ---------------------------------------------------------------------------
# LocalHMACSigner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_hmac_signer_sign_verify():
    """LocalHMACSigner.sign + verify round-trips correctly."""
    secret = b"test-secret-key-32bytes-padded!!"
    signer = LocalHMACSigner(secret=secret)
    data = b"canonical entry bytes"

    sig = await signer.sign(data)
    assert await signer.verify(data, sig) is True


@pytest.mark.asyncio
async def test_local_hmac_signer_wrong_data_fails():
    """LocalHMACSigner.verify returns False for mismatched data."""
    signer = LocalHMACSigner()
    sig = await signer.sign(b"original")
    assert await signer.verify(b"tampered", sig) is False


# ---------------------------------------------------------------------------
# AzureKeyVaultSigner: import-guarded
# ---------------------------------------------------------------------------


def test_azure_key_vault_signer_import_guarded():
    """AzureKeyVaultSigner raises ImportError when azure SDK is not installed.

    If azure-keyvault-keys IS installed in this environment the test is skipped
    rather than forced to fail — the guard is tested by the missing-import path.
    """
    try:
        import azure.keyvault.keys  # noqa: F401
        pytest.skip("azure-keyvault-keys is installed; import-guard path not testable")
    except ImportError:
        pass

    from parrot.security.audit_ledger import AzureKeyVaultSigner
    with pytest.raises(ImportError, match="azure-keyvault-keys"):
        AzureKeyVaultSigner(
            vault_url="https://myvault.vault.azure.net/",
            key_name="audit-key",
        )


def test_azure_key_vault_signer_is_abstract_kms_signer():
    """AzureKeyVaultSigner is a subclass of AbstractKMSSigner (structural check)."""
    from parrot.security.audit_ledger import AzureKeyVaultSigner
    assert issubclass(AzureKeyVaultSigner, AbstractKMSSigner)


# ---------------------------------------------------------------------------
# parrot.auth.audit deprecation
# ---------------------------------------------------------------------------


def test_deprecated_audit_ledger_emits_deprecation_warning():
    """Instantiating the old AuditLedger emits a DeprecationWarning about migration."""
    from parrot.auth.audit import AuditLedger as OldAuditLedger

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        old_ledger = OldAuditLedger()  # noqa: F841

    # Find the specific deprecation warning about our migration path
    migration_warnings = [
        x for x in w
        if issubclass(x.category, DeprecationWarning)
        and "parrot.security.audit_ledger" in str(x.message)
    ]
    assert len(migration_warnings) >= 1, (
        f"Expected DeprecationWarning mentioning 'parrot.security.audit_ledger', "
        f"got: {[str(x.message) for x in w]}"
    )


# ---------------------------------------------------------------------------
# derive_key_fingerprint (canonical helper)
# ---------------------------------------------------------------------------


def test_derive_key_fingerprint_string():
    """derive_key_fingerprint of a string is its SHA-256."""
    import hashlib
    token = "my-api-key-value"
    expected = hashlib.sha256(token.encode()).hexdigest()
    assert derive_key_fingerprint(token) == expected


def test_derive_key_fingerprint_dict():
    """derive_key_fingerprint of a dict serialises with sorted keys."""
    import hashlib
    import json
    token = {"access_token": "abc", "refresh_token": "def"}
    expected = hashlib.sha256(json.dumps(token, sort_keys=True).encode()).hexdigest()
    assert derive_key_fingerprint(token) == expected

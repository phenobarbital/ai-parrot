"""Tests for the envelope cipher backing the encrypted secret store.

Pure crypto, so these run with no database and no environment. The AAD
relocation tests are the important ones: they are what distinguishes this
envelope from the repository's existing ``encrypt_for_db`` helper, which
passes ``aad=None``.
"""
from __future__ import annotations

import os

import pytest

from parrot.security.secrets.base import (
    MasterKeyUnavailable,
    SecretDecryptionError,
)
from parrot.security.secrets.envelope import (
    DEK_SIZE,
    EncryptedValue,
    EnvelopeCipher,
    WrappedDEK,
    generate_dek,
)

SECRET = "sk-ant-super-secret-value"
KEYS = {1: b"\x01" * 32, 2: b"\x02" * 32}


@pytest.fixture
def cipher() -> EnvelopeCipher:
    """A cipher with two master-key versions loaded, active = 1."""
    return EnvelopeCipher(KEYS, active_key_id=1)


# ---------------------------------------------------------------------------
# Construction — must fail closed
# ---------------------------------------------------------------------------


def test_rejects_empty_master_keys() -> None:
    """No key material is a fatal configuration error, not a fallback."""
    with pytest.raises(MasterKeyUnavailable, match="no vault master keys"):
        EnvelopeCipher({}, active_key_id=1)


def test_rejects_wrong_length_master_key() -> None:
    """A short master key is rejected at construction, not at first write."""
    with pytest.raises(MasterKeyUnavailable, match="expected 32"):
        EnvelopeCipher({1: b"too-short"}, active_key_id=1)


def test_rejects_active_key_not_loaded() -> None:
    """An active version with no matching key is a configuration error."""
    with pytest.raises(MasterKeyUnavailable, match="VAULT_ACTIVE_KEY_ID=9"):
        EnvelopeCipher(KEYS, active_key_id=9)


# ---------------------------------------------------------------------------
# DEK layer
# ---------------------------------------------------------------------------


def test_generate_dek_is_random_and_correct_length() -> None:
    """Data keys are 32 random bytes."""
    a, b = generate_dek(), generate_dek()
    assert len(a) == len(b) == DEK_SIZE
    assert a != b


def test_wrap_unwrap_roundtrip(cipher: EnvelopeCipher) -> None:
    """A wrapped data key comes back intact."""
    dek = generate_dek()
    wrapped = cipher.wrap_dek(dek, tenant_id="bar-pepe", dek_version=1)

    assert wrapped.kek_id == 1
    assert cipher.unwrap_dek(wrapped) == dek


def test_wrap_rejects_wrong_size_dek(cipher: EnvelopeCipher) -> None:
    """Only 32-byte data keys may be wrapped."""
    with pytest.raises(ValueError, match="must be 32 bytes"):
        cipher.wrap_dek(b"short", tenant_id="bar-pepe", dek_version=1)


def test_wrapped_dek_relocated_to_another_tenant_fails(
    cipher: EnvelopeCipher,
) -> None:
    """A wrapped DEK row copied to another tenant must not unwrap.

    Without AAD binding this would succeed and hand one tenant another
    tenant's data key.
    """
    dek = generate_dek()
    wrapped = cipher.wrap_dek(dek, tenant_id="bar-pepe", dek_version=1)
    relocated = WrappedDEK(
        tenant_id="hotel-x",
        dek_version=wrapped.dek_version,
        kek_id=wrapped.kek_id,
        nonce=wrapped.nonce,
        ciphertext=wrapped.ciphertext,
    )

    with pytest.raises(SecretDecryptionError, match="copied from another tenant"):
        cipher.unwrap_dek(relocated)


def test_wrapped_dek_with_forged_version_fails(cipher: EnvelopeCipher) -> None:
    """Claiming a different DEK version must not unwrap."""
    wrapped = cipher.wrap_dek(generate_dek(), tenant_id="bar-pepe", dek_version=1)
    forged = WrappedDEK(
        tenant_id=wrapped.tenant_id,
        dek_version=2,
        kek_id=wrapped.kek_id,
        nonce=wrapped.nonce,
        ciphertext=wrapped.ciphertext,
    )

    with pytest.raises(SecretDecryptionError):
        cipher.unwrap_dek(forged)


def test_tampered_ciphertext_fails(cipher: EnvelopeCipher) -> None:
    """A flipped byte is detected by the GCM tag."""
    wrapped = cipher.wrap_dek(generate_dek(), tenant_id="bar-pepe", dek_version=1)
    corrupted = WrappedDEK(
        tenant_id=wrapped.tenant_id,
        dek_version=wrapped.dek_version,
        kek_id=wrapped.kek_id,
        nonce=wrapped.nonce,
        ciphertext=bytes([wrapped.ciphertext[0] ^ 0xFF]) + wrapped.ciphertext[1:],
    )

    with pytest.raises(SecretDecryptionError):
        cipher.unwrap_dek(corrupted)


def test_unwrap_with_retired_key_still_works(cipher: EnvelopeCipher) -> None:
    """A DEK wrapped under an older master key stays readable.

    This is what makes a KEK rotation a window rather than an outage.
    """
    dek = generate_dek()
    wrapped = cipher.wrap_dek(dek, tenant_id="bar-pepe", dek_version=1, kek_id=2)

    assert wrapped.kek_id == 2
    assert cipher.unwrap_dek(wrapped) == dek


def test_unwrap_reports_missing_master_key_clearly() -> None:
    """Dropping a still-referenced master key gives an actionable error."""
    cipher = EnvelopeCipher({1: KEYS[1]}, active_key_id=1)
    wrapped = WrappedDEK(
        tenant_id="bar-pepe",
        dek_version=1,
        kek_id=7,
        nonce=os.urandom(12),
        ciphertext=b"x" * 48,
    )

    with pytest.raises(MasterKeyUnavailable, match="keep retired keys configured"):
        cipher.unwrap_dek(wrapped)


# ---------------------------------------------------------------------------
# Value layer
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_value_roundtrip(cipher: EnvelopeCipher) -> None:
    """A value encrypted under a data key comes back verbatim."""
    dek = generate_dek()
    enc = cipher.encrypt_value(
        dek, SECRET, tenant_id="bar-pepe", key="anthropic:api_key", dek_version=1
    )

    plain = cipher.decrypt_value(
        dek, enc, tenant_id="bar-pepe", key="anthropic:api_key"
    )
    assert plain == SECRET


def test_ciphertext_does_not_contain_plaintext(cipher: EnvelopeCipher) -> None:
    """Sanity check that nothing is stored in the clear."""
    dek = generate_dek()
    enc = cipher.encrypt_value(
        dek, SECRET, tenant_id="bar-pepe", key="k", dek_version=1
    )

    assert SECRET.encode() not in enc.ciphertext


def test_same_value_encrypts_differently_each_time(
    cipher: EnvelopeCipher,
) -> None:
    """A fresh nonce per write means identical values are not correlatable."""
    dek = generate_dek()
    first = cipher.encrypt_value(
        dek, SECRET, tenant_id="bar-pepe", key="k", dek_version=1
    )
    second = cipher.encrypt_value(
        dek, SECRET, tenant_id="bar-pepe", key="k", dek_version=1
    )

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext


def test_value_relocated_to_another_tenant_fails(cipher: EnvelopeCipher) -> None:
    """A secret row copied to another tenant must not decrypt."""
    dek = generate_dek()
    enc = cipher.encrypt_value(
        dek, SECRET, tenant_id="bar-pepe", key="anthropic:api_key", dek_version=1
    )

    with pytest.raises(SecretDecryptionError, match="another tenant or key"):
        cipher.decrypt_value(
            dek, enc, tenant_id="hotel-x", key="anthropic:api_key"
        )


def test_value_relocated_to_another_key_name_fails(
    cipher: EnvelopeCipher,
) -> None:
    """A secret row copied to a different key name must not decrypt.

    Otherwise a tenant could rename a low-value secret onto a high-value key
    and have the platform serve it as that credential.
    """
    dek = generate_dek()
    enc = cipher.encrypt_value(
        dek, SECRET, tenant_id="bar-pepe", key="webhook:hmac", dek_version=1
    )

    with pytest.raises(SecretDecryptionError):
        cipher.decrypt_value(
            dek, enc, tenant_id="bar-pepe", key="anthropic:api_key"
        )


def test_value_decrypted_with_wrong_dek_fails(cipher: EnvelopeCipher) -> None:
    """Another tenant's data key must not open this tenant's value."""
    enc = cipher.encrypt_value(
        generate_dek(), SECRET, tenant_id="bar-pepe", key="k", dek_version=1
    )

    with pytest.raises(SecretDecryptionError):
        cipher.decrypt_value(generate_dek(), enc, tenant_id="bar-pepe", key="k")


def test_forged_dek_version_on_value_fails(cipher: EnvelopeCipher) -> None:
    """The DEK version is authenticated, not merely advisory."""
    dek = generate_dek()
    enc = cipher.encrypt_value(
        dek, SECRET, tenant_id="bar-pepe", key="k", dek_version=1
    )
    forged = EncryptedValue(
        dek_version=2, nonce=enc.nonce, ciphertext=enc.ciphertext
    )

    with pytest.raises(SecretDecryptionError):
        cipher.decrypt_value(dek, forged, tenant_id="bar-pepe", key="k")


def test_wrapping_key_is_domain_separated_from_navigator_vault(
    cipher: EnvelopeCipher,
) -> None:
    """The DEK-wrapping key must differ from navigator's own db key.

    Both derive from the same master key, so without distinct HKDF contexts
    one subsystem's ciphertext would be readable by the other's key.
    """
    from navigator_session.vault.crypto import derive_key

    from parrot.security.secrets.envelope import WRAP_CONTEXT

    ours = derive_key(KEYS[1], WRAP_CONTEXT.format(key_id=1))
    theirs = derive_key(KEYS[1], "vault-db-v1")

    assert ours != theirs

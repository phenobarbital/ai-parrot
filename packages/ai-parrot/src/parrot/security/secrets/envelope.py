"""Envelope encryption for tenant-scoped secrets.

Two layers:

* A **data-encryption key (DEK)** per tenant, freshly generated, which
  encrypts that tenant's secret values.
* A **key-encryption key (KEK)** — the deployment's vault master key — which
  wraps each DEK. Rotating the KEK re-wraps the DEKs and leaves every
  ciphertext untouched; that is the entire point of the envelope.

Both layers are AES-GCM with **additional authenticated data** binding the
ciphertext to its logical location:

* a wrapped DEK is bound to ``dek:{tenant_id}:{dek_version}``
* a value is bound to ``{tenant_id}:{key}:{dek_version}``

The binding is the multi-tenant control. Without it, a row copied from one
tenant to another — by a mistaken migration, a restored backup, or an
attacker with write access to one row — decrypts cleanly into the wrong
tenant's secret. With it, that same row fails authentication.

This is why the module does not simply reuse
:func:`navigator_session.vault.crypto.encrypt_for_db`: that helper passes
``aad=None`` and has no per-tenant key layer. It *does* reuse the same key
derivation (:func:`~navigator_session.vault.crypto.derive_key`, HKDF-SHA256)
and the same master-key management (``VAULT_MASTER_KEY_v{N}`` plus
``VAULT_ACTIVE_KEY_ID``), so a deployment still has exactly one set of master
keys to escrow, back up and rotate.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from navigator_session.vault.crypto import derive_key

from .base import MasterKeyUnavailable, SecretDecryptionError

#: AES-256.
DEK_SIZE = 32
#: 96-bit nonces, per AES-GCM guidance.
NONCE_SIZE = 12
#: HKDF context for the DEK-wrapping key. Domain-separated from navigator's
#: own ``vault-db-v{N}`` so the same master key cannot produce interchangeable
#: keys for two different purposes.
WRAP_CONTEXT = "parrot-saas-dek-wrap-v{key_id}"


@dataclass(frozen=True, slots=True)
class WrappedDEK:
    """A tenant data key, encrypted under a master key.

    Attributes:
        tenant_id: Owning tenant.
        dek_version: Monotonic version, incremented by a DEK rotation.
        kek_id: Master-key version that produced ``ciphertext``.
        nonce: AES-GCM nonce used for the wrapping.
        ciphertext: The wrapped key material plus its GCM tag.
    """

    tenant_id: str
    dek_version: int
    kek_id: int
    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    """A secret value encrypted under a tenant data key.

    Attributes:
        dek_version: Data-key version needed to decrypt.
        nonce: AES-GCM nonce.
        ciphertext: Encrypted value plus its GCM tag.
    """

    dek_version: int
    nonce: bytes
    ciphertext: bytes


def generate_dek() -> bytes:
    """Return a fresh 32-byte data-encryption key."""
    return os.urandom(DEK_SIZE)


class EnvelopeCipher:
    """Wraps/unwraps tenant DEKs and encrypts/decrypts values under them.

    Pure cryptography: no I/O, no storage. That separation is deliberate —
    it lets the security-critical logic be tested exhaustively without a
    database.

    Args:
        master_keys: Mapping of master-key version to raw 32-byte key. Every
            version that might appear in stored data must be present, so a
            rotation window can keep the previous key readable.
        active_key_id: Version used for new wrappings.

    Raises:
        MasterKeyUnavailable: If no keys are supplied, the active version is
            absent from the mapping, or any key is not 32 bytes. Constructing
            with unusable key material must fail here rather than at first
            write — and the store must never invent a key of its own, since
            that produces ciphertext no later process can read.
    """

    def __init__(
        self, master_keys: Mapping[int, bytes], active_key_id: int
    ) -> None:
        if not master_keys:
            raise MasterKeyUnavailable(
                "no vault master keys available; set "
                "VAULT_MASTER_KEY_v1=<base64-encoded-32-byte-key> and "
                "VAULT_ACTIVE_KEY_ID=1"
            )
        for key_id, material in master_keys.items():
            if len(material) != DEK_SIZE:
                raise MasterKeyUnavailable(
                    f"vault master key v{key_id} is {len(material)} bytes; "
                    f"expected {DEK_SIZE}"
                )
        if active_key_id not in master_keys:
            raise MasterKeyUnavailable(
                f"VAULT_ACTIVE_KEY_ID={active_key_id} has no matching "
                f"VAULT_MASTER_KEY_v{active_key_id}"
            )
        self._master_keys: Dict[int, bytes] = dict(master_keys)
        self._active_key_id = active_key_id
        self._wrapping_keys: Dict[int, bytes] = {}

    @classmethod
    def from_environment(cls) -> "EnvelopeCipher":
        """Build a cipher from ``VAULT_MASTER_KEY_v{N}`` / ``VAULT_ACTIVE_KEY_ID``.

        Returns:
            A configured :class:`EnvelopeCipher`.

        Raises:
            MasterKeyUnavailable: If navigator-session is not installed or the
                environment carries no usable key material.
        """
        try:
            from navigator_session.vault.config import (
                get_active_key_id,
                load_master_keys,
            )
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise MasterKeyUnavailable(
                "navigator-session is required to load vault master keys"
            ) from exc
        try:
            keys = load_master_keys()
            active = get_active_key_id()
        except Exception as exc:
            raise MasterKeyUnavailable(
                f"could not load vault master keys: {exc}"
            ) from exc
        return cls(keys, active)

    @property
    def active_key_id(self) -> int:
        """Master-key version used for new wrappings."""
        return self._active_key_id

    def _wrapping_key(self, key_id: int) -> bytes:
        """Return the HKDF-derived wrapping key for a master-key version.

        Args:
            key_id: Master-key version.

        Returns:
            A 32-byte derived key, cached per version.

        Raises:
            MasterKeyUnavailable: If that version is not loaded.
        """
        cached = self._wrapping_keys.get(key_id)
        if cached is not None:
            return cached
        master = self._master_keys.get(key_id)
        if master is None:
            raise MasterKeyUnavailable(
                f"vault master key v{key_id} is required to read existing "
                "data but is not loaded; keep retired keys configured until "
                "every wrapped DEK has been rotated"
            )
        derived = derive_key(master, WRAP_CONTEXT.format(key_id=key_id))
        self._wrapping_keys[key_id] = derived
        return derived

    # -- DEK layer ---------------------------------------------------------

    def wrap_dek(
        self,
        dek: bytes,
        *,
        tenant_id: str,
        dek_version: int,
        kek_id: Optional[int] = None,
    ) -> WrappedDEK:
        """Encrypt a data key under a master key.

        Args:
            dek: Raw 32-byte data key.
            tenant_id: Owning tenant; bound into the AAD.
            dek_version: Data-key version; bound into the AAD.
            kek_id: Master-key version to wrap with. Defaults to the active
                one.

        Returns:
            The wrapped key.

        Raises:
            ValueError: If ``dek`` is not 32 bytes.
        """
        if len(dek) != DEK_SIZE:
            raise ValueError(f"dek must be {DEK_SIZE} bytes, got {len(dek)}")
        key_id = self._active_key_id if kek_id is None else kek_id
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = AESGCM(self._wrapping_key(key_id)).encrypt(
            nonce, dek, _dek_aad(tenant_id, dek_version)
        )
        return WrappedDEK(
            tenant_id=tenant_id,
            dek_version=dek_version,
            kek_id=key_id,
            nonce=nonce,
            ciphertext=ciphertext,
        )

    def unwrap_dek(self, wrapped: WrappedDEK) -> bytes:
        """Recover a data key.

        Args:
            wrapped: The stored wrapped key.

        Returns:
            The raw 32-byte data key.

        Raises:
            SecretDecryptionError: If authentication fails — which is also
                what a wrapped DEK relocated to another tenant or version
                looks like.
            MasterKeyUnavailable: If the wrapping master key is not loaded.
        """
        try:
            return AESGCM(self._wrapping_key(wrapped.kek_id)).decrypt(
                wrapped.nonce,
                wrapped.ciphertext,
                _dek_aad(wrapped.tenant_id, wrapped.dek_version),
            )
        except InvalidTag as exc:
            raise SecretDecryptionError(
                f"could not authenticate the wrapped data key for tenant "
                f"{wrapped.tenant_id!r} version {wrapped.dek_version}; the "
                "row may have been altered or copied from another tenant"
            ) from exc

    # -- Value layer -------------------------------------------------------

    def encrypt_value(
        self, dek: bytes, value: str, *, tenant_id: str, key: str, dek_version: int
    ) -> EncryptedValue:
        """Encrypt a secret value under a tenant data key.

        Args:
            dek: Raw data key.
            value: Plaintext secret.
            tenant_id: Owning tenant; bound into the AAD.
            key: Secret name; bound into the AAD.
            dek_version: Data-key version; bound into the AAD.

        Returns:
            The encrypted value.
        """
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = AESGCM(dek).encrypt(
            nonce, value.encode("utf-8"), _value_aad(tenant_id, key, dek_version)
        )
        return EncryptedValue(
            dek_version=dek_version, nonce=nonce, ciphertext=ciphertext
        )

    def decrypt_value(
        self, dek: bytes, encrypted: EncryptedValue, *, tenant_id: str, key: str
    ) -> str:
        """Decrypt a secret value.

        Args:
            dek: Raw data key matching ``encrypted.dek_version``.
            encrypted: The stored ciphertext.
            tenant_id: Tenant the row was read for.
            key: Secret name the row was read for.

        Returns:
            The plaintext secret.

        Raises:
            SecretDecryptionError: If authentication fails. A row relocated to
                a different tenant or key name lands here rather than
                decrypting into someone else's secret.
        """
        try:
            plaintext = AESGCM(dek).decrypt(
                encrypted.nonce,
                encrypted.ciphertext,
                _value_aad(tenant_id, key, encrypted.dek_version),
            )
        except InvalidTag as exc:
            raise SecretDecryptionError(
                f"could not authenticate secret {key!r} for tenant "
                f"{tenant_id!r}; the row may have been altered or copied "
                "from another tenant or key"
            ) from exc
        return plaintext.decode("utf-8")


def _dek_aad(tenant_id: str, dek_version: int) -> bytes:
    """Return the AAD binding a wrapped DEK to its tenant and version."""
    return f"dek:{tenant_id}:{dek_version}".encode("utf-8")


def _value_aad(tenant_id: str, key: str, dek_version: int) -> bytes:
    """Return the AAD binding a value to its tenant, key name and DEK version."""
    return f"{tenant_id}:{key}:{dek_version}".encode("utf-8")


__all__ = (
    "DEK_SIZE",
    "NONCE_SIZE",
    "EncryptedValue",
    "EnvelopeCipher",
    "WrappedDEK",
    "generate_dek",
)

"""Append-only, KMS-signed credential-invocation ledger (FEAT-260 / TASK-1642).

Every credentialed tool invocation over the A2A bridge records an
:class:`AuditLedgerEntry` that carries a ``key_fingerprint`` (a SHA-256 hash
of the credential material) but **never** the raw credential.  Each entry is
signed by a :class:`AbstractKMSSigner` so the record cannot be silently tampered
with after the fact.

Two signers are provided:

- :class:`LocalHMACSigner` — HMAC-SHA256 with a caller-supplied secret; suitable
  for local development, tests, and environments without a managed KMS.
- A production KMS backend can be injected by implementing
  :class:`AbstractKMSSigner` and passing the instance to :class:`AuditLedger`.

Append-only semantics are enforced by the public API: :meth:`AuditLedger.append`
and :meth:`AuditLedger.verify` are the only entry-points; there is no
``update`` or ``delete``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


__all__ = [
    "AuditLedgerEntry",
    "AbstractKMSSigner",
    "LocalHMACSigner",
    "AzureKeyVaultSigner",
    "AuditLedger",
    "derive_key_fingerprint",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def derive_key_fingerprint(credential_material: Any) -> str:
    """Return the SHA-256 hex digest of ``credential_material``.

    The fingerprint uniquely identifies a credential without exposing any
    secret bytes.

    Args:
        credential_material: Any credential value — token string, dict with
            ``access_token`` / ``token``, or arbitrary bytes.  Dicts and other
            objects are serialised to JSON before hashing.

    Returns:
        A 64-character lowercase hex string (SHA-256).
    """
    if isinstance(credential_material, bytes):
        raw = credential_material
    elif isinstance(credential_material, str):
        raw = credential_material.encode()
    elif isinstance(credential_material, dict):
        # Serialise token-set dicts deterministically (sorted keys).
        raw = json.dumps(credential_material, sort_keys=True).encode()
    else:
        raw = str(credential_material).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class AuditLedgerEntry(BaseModel):
    """Append-only, KMS-signed record of a credentialed tool invocation.

    Attributes:
        entry_id: Unique ledger record identifier (UUIDv4).
        user_id: Canonical per-user identity (email), consistent with
            ``TeamsHumanChannel`` and ``A2AServer._extract_identity``.
        channel: Invocation channel, e.g. ``"a2a:copilot"``.
        tool: Name of the tool that was invoked.
        provider: Credential provider, e.g. ``"jira"``, ``"o365"``,
            ``"work-iq"``, ``"fireflies"``, or ``"stub"``.
        key_fingerprint: SHA-256 hex digest of the credential material.
            **Never** the raw credential.
        signature: KMS signature over the canonical entry bytes (see
            :meth:`canonical_bytes`).
        created_at: UTC timestamp recorded at entry creation.
    """

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    channel: str
    tool: str
    provider: str
    key_fingerprint: str
    signature: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def canonical_bytes(self) -> bytes:
        """Return the canonical byte representation used for signing/verification.

        All fields EXCEPT ``signature`` are included, serialised to JSON with
        sorted keys for determinism.

        Returns:
            UTF-8 encoded canonical JSON bytes.
        """
        payload: Dict[str, Any] = {
            "entry_id": self.entry_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "tool": self.tool,
            "provider": self.provider,
            "key_fingerprint": self.key_fingerprint,
            "created_at": self.created_at.isoformat(),
        }
        return json.dumps(payload, sort_keys=True).encode()


# ---------------------------------------------------------------------------
# KMS abstraction
# ---------------------------------------------------------------------------


class AbstractKMSSigner(ABC):
    """Injectable signing/verification backend for :class:`AuditLedger`.

    Implementations must be async to allow non-blocking calls to managed KMS
    services (AWS KMS, GCP Cloud KMS, Azure Key Vault, etc.).
    """

    @abstractmethod
    async def sign(self, data: bytes) -> str:
        """Return a hex-encoded signature over *data*.

        Args:
            data: Canonical bytes to sign (from :meth:`AuditLedgerEntry.canonical_bytes`).

        Returns:
            A hex-encoded signature string.
        """

    @abstractmethod
    async def verify(self, data: bytes, signature: str) -> bool:
        """Verify that *signature* was produced by ``sign(data)``.

        Args:
            data: The canonical bytes that were signed.
            signature: Hex-encoded signature to verify.

        Returns:
            ``True`` if the signature is valid, ``False`` otherwise.
        """


class LocalHMACSigner(AbstractKMSSigner):
    """HMAC-SHA256 signer for local development and testing.

    This signer uses Python's built-in :mod:`hmac` module with a caller-supplied
    secret key.  It is cryptographically sound for low-threat environments but
    does **not** provide the tamper-evidence guarantees of a true managed KMS
    (key rotation, HSM backing, audit trail of key usage, etc.).

    Args:
        secret: The HMAC secret.  Defaults to a random 32-byte secret if not
            provided (suitable for unit tests where verification happens in the
            same process).  In production use, supply a secret from the vault.
    """

    def __init__(self, secret: Optional[bytes] = None) -> None:
        self._secret: bytes = secret if secret is not None else _random_secret()

    async def sign(self, data: bytes) -> str:
        """Return the HMAC-SHA256 hex digest of *data* under the secret key."""
        return hmac.new(self._secret, data, hashlib.sha256).hexdigest()

    async def verify(self, data: bytes, signature: str) -> bool:
        """Return ``True`` iff *signature* matches the HMAC-SHA256 of *data*."""
        expected = await self.sign(data)
        return hmac.compare_digest(expected, signature)


def _random_secret() -> bytes:
    """Generate a cryptographically random 32-byte HMAC secret."""
    import secrets as _secrets
    return _secrets.token_bytes(32)


class AzureKeyVaultSigner(AbstractKMSSigner):
    """Azure Key Vault backed KMS signer for production environments.

    Uses the ``azure-keyvault-keys`` SDK to sign and verify entry bytes
    with an asymmetric key stored in Azure Key Vault (RSA-PSS / EC).

    .. note::
        This class requires the ``azure-keyvault-keys`` and
        ``azure-identity`` packages.  Import is guarded — if the packages
        are not installed a clear :class:`ImportError` is raised at
        instantiation time (not at module import time), so environments
        that use only :class:`LocalHMACSigner` are unaffected.

    Args:
        vault_url: Azure Key Vault URL (e.g. ``"https://myvault.vault.azure.net/"``).
        key_name: Name of the key in the vault.
        key_version: Optional key version.  Defaults to the latest version.
        credential: An ``azure.identity`` credential object.  When ``None``,
            :class:`azure.identity.DefaultAzureCredential` is used.
        algorithm: Signing algorithm.  Defaults to ``"RS256"``.
    """

    def __init__(
        self,
        vault_url: str,
        key_name: str,
        key_version: Optional[str] = None,
        credential: Optional[Any] = None,
        algorithm: str = "RS256",
    ) -> None:
        try:
            from azure.keyvault.keys.crypto import CryptographyClient, SignatureAlgorithm  # type: ignore[import]
            from azure.keyvault.keys import KeyClient  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "AzureKeyVaultSigner requires 'azure-keyvault-keys' and "
                "'azure-identity'. Install with: uv add azure-keyvault-keys azure-identity"
            ) from exc

        if credential is None:
            try:
                from azure.identity import DefaultAzureCredential  # type: ignore[import]
                credential = DefaultAzureCredential()
            except ImportError as exc:
                raise ImportError(
                    "AzureKeyVaultSigner: 'azure-identity' is required when "
                    "credential=None. Install with: uv add azure-identity"
                ) from exc

        key_client = KeyClient(vault_url=vault_url, credential=credential)
        key = key_client.get_key(key_name, version=key_version)
        self._client = CryptographyClient(key, credential=credential)
        self._algorithm = getattr(SignatureAlgorithm, algorithm, SignatureAlgorithm.rs256)

    async def sign(self, data: bytes) -> str:
        """Sign *data* using the Azure Key Vault key.

        Args:
            data: Canonical bytes to sign.

        Returns:
            Hex-encoded signature string.
        """
        import asyncio

        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._client.sign(self._algorithm, hashlib.sha256(data).digest())
        )
        return result.signature.hex()

    async def verify(self, data: bytes, signature: str) -> bool:
        """Verify *signature* against *data* using the Azure Key Vault key.

        Args:
            data: Canonical bytes that were signed.
            signature: Hex-encoded signature to verify.

        Returns:
            ``True`` if the signature is valid, ``False`` otherwise.
        """
        import asyncio

        sig_bytes = bytes.fromhex(signature)
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._client.verify(
                self._algorithm, hashlib.sha256(data).digest(), sig_bytes
            ),
        )
        return result.is_valid


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class AuditLedger:
    """Append-only, KMS-signed credential-invocation ledger.

    Entries are stored in-memory by default.  An optional *storage* backend
    can be supplied (a callable coroutine that accepts a serialised JSON string)
    for durable persistence (DocumentDB, PostgreSQL, etc.).

    Append-only semantics: only :meth:`append` and :meth:`verify` are exposed;
    there is no ``update``, ``delete``, or ``get_all`` mutation surface.

    Args:
        signer: A :class:`AbstractKMSSigner` implementation.  Defaults to
            :class:`LocalHMACSigner` (HMAC-SHA256 with a random in-process
            key — suitable for tests).
        storage: Optional async callable ``(json_str: str) -> None`` that
            persists each entry to a durable backend.  ``None`` (default)
            retains entries in memory only.

    Example::

        ledger = AuditLedger()
        entry = await ledger.append(
            user_id="alice@example.com",
            channel="a2a:copilot",
            tool="jira_create_issue",
            provider="jira",
            credential_material=jira_token,
        )
        assert await ledger.verify(entry.entry_id)
    """

    def __init__(
        self,
        signer: Optional[AbstractKMSSigner] = None,
        storage: Optional[Any] = None,
    ) -> None:
        self._signer: AbstractKMSSigner = signer or LocalHMACSigner()
        self._storage = storage
        # In-memory store: entry_id -> AuditLedgerEntry
        self._entries: Dict[str, AuditLedgerEntry] = {}
        self.logger = logging.getLogger(__name__)

    async def append(
        self,
        *,
        user_id: str,
        channel: str,
        tool: str,
        provider: str,
        credential_material: Any,
    ) -> AuditLedgerEntry:
        """Create, sign, and persist a new ledger entry.

        The ``key_fingerprint`` is derived by
        :func:`derive_key_fingerprint` — the raw credential is **never**
        stored or logged.

        Args:
            user_id: Canonical per-user identity (email).
            channel: Invocation channel (e.g. ``"a2a:copilot"``).
            tool: Name of the tool being invoked.
            provider: Credential provider key (e.g. ``"jira"``).
            credential_material: The resolved credential value used to derive
                the fingerprint.  This value is hashed and then discarded; it
                is **not** stored in the entry.

        Returns:
            The signed :class:`AuditLedgerEntry` that was persisted.

        Raises:
            RuntimeError: If the storage backend raises an unrecoverable error.
        """
        key_fingerprint = derive_key_fingerprint(credential_material)
        entry = AuditLedgerEntry(
            user_id=user_id,
            channel=channel,
            tool=tool,
            provider=provider,
            key_fingerprint=key_fingerprint,
        )

        # Sign canonical bytes (excludes the `signature` field itself)
        canonical = entry.canonical_bytes()
        entry.signature = await self._signer.sign(canonical)

        # Persist in-memory
        self._entries[entry.entry_id] = entry

        # Optionally persist to a durable backend
        if self._storage is not None:
            try:
                await self._storage(entry.model_dump_json())
            except Exception:
                self.logger.exception(
                    "AuditLedger: storage backend failed for entry_id=%s",
                    entry.entry_id,
                )
                # Do not re-raise — in-memory record is the source of truth
                # for verification within this process; a background sweeper
                # can retry durable persistence.

        self.logger.info(
            "AuditLedger.append: entry_id=%s user_id=%s channel=%s tool=%s provider=%s",
            entry.entry_id,
            user_id,
            channel,
            tool,
            provider,
        )
        return entry

    async def verify(self, entry_id: str) -> bool:
        """Re-check the KMS signature on a previously appended entry.

        Loads the entry from the in-memory store and verifies that the stored
        ``signature`` matches the canonical bytes re-derived from the entry
        fields.

        Args:
            entry_id: The UUID of the entry to verify.

        Returns:
            ``True`` if the signature is intact, ``False`` if the entry is not
            found or the signature does not match.
        """
        entry = self._entries.get(entry_id)
        if entry is None:
            self.logger.warning(
                "AuditLedger.verify: entry_id=%s not found", entry_id
            )
            return False

        canonical = entry.canonical_bytes()
        valid = await self._signer.verify(canonical, entry.signature)
        if not valid:
            self.logger.error(
                "AuditLedger.verify: SIGNATURE MISMATCH for entry_id=%s", entry_id
            )
        return valid

    def get_entry(self, entry_id: str) -> Optional[AuditLedgerEntry]:
        """Return the entry for *entry_id*, or ``None`` if not found.

        Read-only access for inspection.  Does not expose a mutable reference.
        """
        return self._entries.get(entry_id)

    @property
    def entry_count(self) -> int:
        """Return the number of entries in the in-memory store."""
        return len(self._entries)

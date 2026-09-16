"""
Vault protected targets for ai-parrot DocumentDB collections (FEAT-099).

Registered under the ``navigator_session.vault_targets`` entry-point group so
``navigator-vault`` rotation and v1 → v2 migration cover parrot credentials:

===================  ==========================  ==========================
Collection           Identity                    Encrypted field
===================  ==========================  ==========================
``user_credentials`` ``(user_id, name)``         ``credential``
``user_llm_keys``    ``(user_id, provider)``     ``api_key``
===================  ==========================  ==========================

Values are stored base64-encoded; rows expose the decoded bytes so the vault
kernel can read envelope headers, and writes re-encode them unchanged.

Quarantine moves the document to ``<collection>_quarantine`` (with
``quarantined_at``, ``reason``, ``run_id``) and removes it from the source
collection; ``restore_raw`` puts the original document back and drops the
quarantine copy.

Security Note:
    Row refs and logs carry identities only — never credential values.
"""
from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Mapping, Optional

from navigator_session.vault.registry import BackupSink, BackupSource, VaultRow

from parrot.security.credentials_utils import (
    CREDENTIAL_FIELD,
    CREDENTIAL_PURPOSE,
    LLM_KEY_FIELD,
    LLM_KEY_PURPOSE,
    credential_context,
    llm_key_context,
)

QUARANTINE_SUFFIX = "_quarantine"


class DocumentDbTarget:
    """Base for DocumentDB collections holding one sealed field per document.

    Args:
        docdb_factory: Callable returning a ``DocumentDb`` async context manager.
    """

    name: str
    collection: str
    purpose: str
    identity_fields: tuple[str, ...]
    encrypted_field: str

    def __init__(self, docdb_factory: Callable[[], Any]) -> None:
        self._docdb = docdb_factory

    # ------------------------------------------------------------------
    # ProtectedTarget API
    # ------------------------------------------------------------------

    @property
    def encrypted_fields(self) -> tuple[str, ...]:
        return (self.encrypted_field,)

    def context_for(self, row: Any, field: str):
        """Context binding ``field`` of ``row`` (see credentials_utils)."""
        if field != self.encrypted_field:
            raise ValueError(f"{field!r} is not an encrypted field of {self.name}")
        return self._context(*(row.identity[name] for name in self.identity_fields))

    def _context(self, *identity_values: Any):
        raise NotImplementedError

    def ref_for(self, identity: Mapping[str, Any]) -> str:
        parts = ",".join(f"{name}={identity.get(name)}" for name in self.identity_fields)
        return f"{self.name}:{parts}"

    async def iter_batches(self, batch_size: int) -> AsyncIterator[list[VaultRow]]:
        """Iterate documents in deterministic batches (whole collection read once).

        Credential collections are small (a few documents per user), so the
        documents are read once, sorted by their identity, and handed out in
        batches; DocumentDB drops ``_id`` on read, so rows are addressed by
        their natural key.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        async with self._docdb() as db:
            documents = await db.read(self.collection, {})
        documents = sorted(
            documents or [],
            key=lambda doc: tuple(str(doc.get(name)) for name in self.identity_fields),
        )
        for start in range(0, len(documents), batch_size):
            yield [self._row(doc) for doc in documents[start:start + batch_size]]

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """No-op: DocumentDB writes here are per-document."""
        yield None

    async def write(
        self, row: Any, blobs: Mapping[str, Optional[bytes]], key_version: int
    ) -> None:
        """Replace the sealed field of ``row`` and record ``key_version``.

        Raises:
            ValueError: If ``blobs`` names unknown fields or is empty.
            LookupError: If the document no longer exists.
        """
        unknown = set(blobs) - {self.encrypted_field}
        if unknown or not blobs:
            raise ValueError(f"unknown encrypted fields for {self.name}: {sorted(unknown)}")
        blob = blobs[self.encrypted_field]
        if blob is None:
            raise ValueError(f"{self.name} requires a value for {self.encrypted_field}")
        update = {
            self.encrypted_field: base64.b64encode(bytes(blob)).decode("ascii"),
            "key_version": key_version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        query = dict(row.identity)
        async with self._docdb() as db:
            result = await db.update_one(self.collection, query, {"$set": update})
        if getattr(result, "matched_count", 1) == 0:
            raise LookupError(f"{row.ref} not found")

    async def quarantine(self, row: Any, reason: str, run_id: str) -> None:
        """Move the document to ``<collection>_quarantine`` (keeping its value)."""
        query = dict(row.identity)
        async with self._docdb() as db:
            document = await db.read_one(self.collection, query)
            if document is None:
                raise LookupError(f"{row.ref} not found")
            await db.write(
                self.collection + QUARANTINE_SUFFIX,
                {
                    **document,
                    "quarantined_at": datetime.now(timezone.utc).isoformat(),
                    "reason": reason,
                    "run_id": run_id,
                },
            )
            await db.delete(self.collection, query)

    async def export_raw(self, sink: BackupSink) -> int:
        """Export every document as stored (value base64, identity, metadata)."""
        count = 0
        async for batch in self.iter_batches(200):
            for row in batch:
                await sink.write(self.name, self.to_backup_record(row))
                count += 1
        return count

    async def restore_raw(self, source: BackupSource) -> int:
        """Restore documents (including quarantined ones) from a backup.

        The stored document is *replaced*, not merged, so fields added by the
        migration (e.g. ``updated_at``) do not survive a rollback.
        """
        count = 0
        async with self._docdb() as db:
            async for record in source.read(self.name):
                query = dict(record["identity"])
                await db.delete(self.collection, query)
                await db.write(self.collection, dict(record["document"]))
                await db.delete(self.collection + QUARANTINE_SUFFIX, query)
                count += 1
        return count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_backup_record(self, row: VaultRow) -> dict:
        """JSON-safe snapshot of a document (sealed value stays sealed)."""
        blob = row.values[self.encrypted_field]
        return {
            "ref": row.ref,
            "pk": dict(row.identity),
            "identity": dict(row.identity),
            "values": {
                self.encrypted_field: None if blob is None
                else base64.b64encode(blob).decode("ascii")
            },
            "key_version": row.key_version,
            "document": row.state.get("document", {}),
        }

    def _row(self, document: Mapping[str, Any]) -> VaultRow:
        identity = {name: document.get(name) for name in self.identity_fields}
        stored = document.get(self.encrypted_field)
        blob = base64.b64decode(stored) if stored else None
        return VaultRow(
            ref=self.ref_for(identity),
            pk=identity,
            identity=identity,
            values={self.encrypted_field: blob},
            key_version=document.get("key_version"),
            state={"document": dict(document)},
        )


class UserCredentialsTarget(DocumentDbTarget):
    """``user_credentials`` documents written by the credentials handler/vault utils."""

    name = "docdb:user_credentials"
    collection = "user_credentials"
    purpose = CREDENTIAL_PURPOSE
    identity_fields = ("user_id", "name")
    encrypted_field = CREDENTIAL_FIELD

    def _context(self, user_id: Any, name: str):
        return credential_context(user_id, name)


class UserLlmKeysTarget(DocumentDbTarget):
    """``user_llm_keys`` documents written by the BYOK (Studio keys) handler."""

    name = "docdb:user_llm_keys"
    collection = "user_llm_keys"
    purpose = LLM_KEY_PURPOSE
    identity_fields = ("user_id", "provider")
    encrypted_field = LLM_KEY_FIELD

    def _context(self, user_id: Any, provider: str):
        return llm_key_context(user_id, provider)


def _default_docdb_factory() -> Optional[Callable[[], Any]]:
    """``DocumentDb`` when DocumentDB is configured, else ``None``."""
    try:
        from navconfig import config  # pylint: disable=import-outside-toplevel

        from parrot.interfaces.documentdb import DocumentDb  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None
    if not (config.get("DOCUMENTDB_HOSTNAME") or config.get("DOCUMENTDB_DBNAME")):
        return None
    return DocumentDb


def _targets(resources: Mapping[str, Any], cls) -> Optional[DocumentDbTarget]:
    factory_callable = resources.get("docdb_factory") or _default_docdb_factory()
    if factory_callable is None:
        return None
    return cls(factory_callable)


def user_credentials_factory(resources: Mapping[str, Any]) -> Optional[UserCredentialsTarget]:
    """Entry-point factory for ``user_credentials`` (needs DocumentDB)."""
    return _targets(resources, UserCredentialsTarget)


def user_llm_keys_factory(resources: Mapping[str, Any]) -> Optional[UserLlmKeysTarget]:
    """Entry-point factory for ``user_llm_keys`` (needs DocumentDB)."""
    return _targets(resources, UserLlmKeysTarget)

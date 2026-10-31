"""AES-GCM local cache of provider access tokens + remote resolver (FEAT-774 M4). Never stores refresh tokens."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field

from parrot.auth.broker.core import CredentialBroker
from parrot.auth.credentials import CredentialResolver
from parrot.auth.oauth2.remote_client import NotConnected, ServerConnectionsClient
from parrot.cli.login import LoginStore

logger = logging.getLogger(__name__)
_MAGIC = b"PCC1"
_AAD = b"parrot-connections-cache-v1"


class CachedConnection(BaseModel):
    """Locally cached provider access token metadata."""

    provider: str
    access_token: str
    expires_at: float
    scopes: List[str] = Field(default_factory=list)
    account_id: str = ""
    pulled_at: float


class ConnectionCache:
    """Encrypted JSON map provider → CachedConnection at ``path`` (0600)."""

    def __init__(self, path: Path, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("connection cache key must be 32 bytes")
        self.path = Path(path)
        self._aead = AESGCM(key)
        self._lock = asyncio.Lock()
        self.logger = logger

    def _read_sync(self) -> Dict[str, CachedConnection]:
        """Read and decrypt cache entries, treating corrupt data as empty."""
        try:
            blob = self.path.read_bytes()
            if not blob.startswith(_MAGIC) or len(blob) <= len(_MAGIC) + 12:
                raise ValueError("invalid connection cache format")
            nonce = blob[len(_MAGIC) : len(_MAGIC) + 12]
            plaintext = self._aead.decrypt(nonce, blob[len(_MAGIC) + 12 :], _AAD)
            payload = json.loads(plaintext)
            if not isinstance(payload, dict):
                raise ValueError("invalid connection cache payload")
            return {provider: CachedConnection.model_validate(entry) for provider, entry in payload.items()}
        except FileNotFoundError:
            return {}
        except (InvalidTag, OSError, TypeError, ValueError):
            self.logger.warning("connection cache unreadable; treating as empty")
            return {}

    def _write_sync(self, entries: Dict[str, CachedConnection]) -> None:
        """Atomically encrypt and persist cache entries with private permissions."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {provider: entry.model_dump(mode="json") for provider, entry in entries.items()}
        nonce = os.urandom(12)
        blob = _MAGIC + nonce + self._aead.encrypt(nonce, json.dumps(payload).encode("utf-8"), _AAD)
        fd, temporary_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(blob)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
            os.chmod(self.path, 0o600)
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    async def get(self, provider: str) -> Optional[CachedConnection]:
        """Return a provider entry when it is present in the encrypted cache."""
        return (await asyncio.to_thread(self._read_sync)).get(provider)

    async def put(self, entry: CachedConnection) -> None:
        """Store or replace one provider's access-token entry."""
        async with self._lock:
            entries = await asyncio.to_thread(self._read_sync)
            entries[entry.provider] = entry
            await asyncio.to_thread(self._write_sync, entries)

    async def delete(self, provider: Optional[str] = None) -> None:
        """Delete one provider, or the whole file when ``provider`` is None."""
        async with self._lock:
            if provider is None:
                await asyncio.to_thread(self.path.unlink, missing_ok=True)
                return
            entries = await asyncio.to_thread(self._read_sync)
            if provider in entries:
                del entries[provider]
                await asyncio.to_thread(self._write_sync, entries)


class RemoteConnectionResolver(CredentialResolver):
    """Answer from cache, otherwise pull a token from the server once per provider."""

    def __init__(
        self, provider: str, *, cache: ConnectionCache, client: ServerConnectionsClient, skew_s: int = 60
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.client = client
        self.skew_s = skew_s
        self._lock = asyncio.Lock()

    def _valid(self, entry: Optional[CachedConnection]) -> bool:
        """Return whether an entry remains usable after the refresh skew."""
        return entry is not None and entry.expires_at - self.skew_s > time.time()

    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        """Return a fresh access token, or ``None`` when the provider is disconnected."""
        entry = await self.cache.get(self.provider)
        if self._valid(entry):
            return entry.access_token

        async with self._lock:
            entry = await self.cache.get(self.provider)
            if self._valid(entry):
                return entry.access_token
            try:
                pulled = await self.client.pull_token(self.provider)
            except NotConnected:
                return None
            cached = CachedConnection(
                provider=pulled.provider,
                access_token=pulled.access_token,
                expires_at=pulled.expires_at,
                scopes=pulled.scopes,
                account_id=pulled.account_id,
                pulled_at=time.time(),
            )
            await self.cache.put(cached)
            return cached.access_token

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Start the server-owned authorization flow and return its URL."""
        return (await self.client.start_connect(self.provider, channel=channel)).auth_url


def open_connection_cache(store: LoginStore) -> ConnectionCache:
    """Build a cache next to the login file using its per-login cache key."""
    record = store.load_optional()
    if record is None:
        raise ValueError("no login — run `parrot login`")
    padded = record.cache_key + "=" * (-len(record.cache_key) % 4)
    return ConnectionCache(store.cache_path, base64.urlsafe_b64decode(padded))


def build_cli_broker(
    store: LoginStore, providers: Iterable[str], *, client: Optional[ServerConnectionsClient] = None
) -> CredentialBroker:
    """Register an OAuth2 remote resolver for every declared provider."""
    cache = open_connection_cache(store)
    client = client or ServerConnectionsClient(store)
    broker = CredentialBroker()
    for provider in sorted(set(providers)):
        broker.register(provider, RemoteConnectionResolver(provider, cache=cache, client=client), auth_kind="oauth2")
    return broker

"""AES-GCM local cache of provider access tokens + remote resolver (FEAT-774 M4). Never stores refresh tokens."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import fcntl
import json
import logging
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional

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
    """Encrypted JSON map provider → CachedConnection at ``path`` (0600).

    Reads accept only a regular, non-symlink file owned by the current user with no group/other
    permission bits. Writes hold an exclusive ``flock`` on the 0600 sidecar ``<path>.lock`` across
    the whole read-modify-write, so concurrent processes (REPL, ``mcp-local``) never lose an entry.
    """

    def __init__(self, path: Path, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("connection cache key must be 32 bytes")
        self.path = Path(path)
        self._aead = AESGCM(key)
        self._lock = asyncio.Lock()
        self.logger = logger

    @property
    def lock_path(self) -> Path:
        """Return the sidecar lock path held across read-modify-write cycles."""
        return self.path.with_name(self.path.name + ".lock")

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold an exclusive cross-process lock on the sidecar lock file (never through a symlink)."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _read_blob(self) -> bytes:
        """Read the cache file, refusing symlinks, non-regular files, foreign owners and loose modes."""
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise ValueError("connection cache is not a regular file")
            if file_stat.st_uid != os.getuid():
                raise ValueError("connection cache is not owned by the current user")
            if file_stat.st_mode & 0o077:
                raise ValueError("connection cache is accessible by group or other users")
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                return handle.read()
        finally:
            if fd >= 0:
                os.close(fd)

    def _read_sync(self) -> Dict[str, CachedConnection]:
        """Read and decrypt cache entries, treating unsafe or corrupt data as empty."""
        try:
            blob = self._read_blob()
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
        except (InvalidTag, OSError, TypeError, ValueError) as exc:
            self.logger.warning("connection cache unreadable; treating as empty (%s)", type(exc).__name__)
            return {}

    def _update_sync(self, mutate: Callable[[Dict[str, CachedConnection]], bool]) -> None:
        """Read, mutate and (when ``mutate`` returns True) rewrite the cache under the file lock."""
        with self._locked():
            entries = self._read_sync()
            if mutate(entries):
                self._write_sync(entries)

    def _delete_file_sync(self) -> None:
        """Remove the cache file under the file lock."""
        with self._locked():
            self.path.unlink(missing_ok=True)

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

        def _mutate(entries: Dict[str, CachedConnection]) -> bool:
            entries[entry.provider] = entry
            return True

        async with self._lock:
            await asyncio.to_thread(self._update_sync, _mutate)

    async def delete(self, provider: Optional[str] = None) -> None:
        """Delete one provider, or the whole file when ``provider`` is None."""

        def _mutate(entries: Dict[str, CachedConnection]) -> bool:
            return entries.pop(provider, None) is not None

        async with self._lock:
            if provider is None:
                await asyncio.to_thread(self._delete_file_sync)
                return
            await asyncio.to_thread(self._update_sync, _mutate)


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

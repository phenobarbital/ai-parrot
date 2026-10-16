"""Local Jira OAuth 2.0 token store and credential resolver (FEAT-696 M3)."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Iterator, Optional

import aiohttp
from pydantic import BaseModel, Field

from parrot.auth.credentials import CredentialResolver
from parrot.auth.jira_oauth import JiraTokenSet, refresh_access_token

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = Path("~/.parrot/jira/settings.local.json")


class LocalSettings(BaseModel):
    """Schema for the local settings file."""

    version: int = 1
    default_site: Optional[str] = None
    sites: dict[str, dict[str, Any]] = Field(default_factory=dict)


class LocalJiraTokenStore:
    """Atomic, locked file store for Jira OAuth tokens."""

    def __init__(self, path: Optional[Path] = None) -> None:
        env_path = os.environ.get("JIRA_LOCAL_SETTINGS")
        self.path = Path(env_path) if env_path else (path or DEFAULT_SETTINGS_PATH)
        self.path = Path(self.path).expanduser()

    @property
    def lock_path(self) -> Path:
        """Sidecar lock file (the data file is replaced atomically, so it cannot hold the lock)."""
        return self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold an exclusive ``fcntl.flock`` on the sidecar lock file."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def load(self) -> LocalSettings:
        """Load settings from disk, returning defaults if missing."""
        if not self.path.exists():
            return LocalSettings()
        with self.path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return LocalSettings.model_validate(data)

    def get(self, site: Optional[str] = None) -> Optional[JiraTokenSet]:
        """Return the token set for a site, or the default site."""
        settings = self.load()
        key = site or settings.default_site
        if not key or key not in settings.sites:
            return None
        return JiraTokenSet.model_validate(settings.sites[key])

    def _write(self, settings: LocalSettings) -> None:
        """Atomically write settings (temp file + os.replace, mode 0600). Caller holds the lock."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=self.path.name + ".", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(settings.model_dump(mode="json"), fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
            os.chmod(self.path, 0o600)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _site_key(token: JiraTokenSet) -> str:
        return token.site_url or token.cloud_id

    def _save_unlocked(self, token: JiraTokenSet, *, make_default: bool = True, key: Optional[str] = None) -> None:
        settings = self.load()
        key = key or self._site_key(token)
        settings.sites[key] = token.model_dump(mode="json")
        if make_default or not settings.default_site:
            settings.default_site = key
        self._write(settings)

    def save(self, token: JiraTokenSet, *, make_default: bool = True) -> None:
        """Persist a token set atomically with mode 0600."""
        with self.locked():
            self._save_unlocked(token, make_default=make_default)

    def delete(self, site: Optional[str] = None) -> bool:
        """Remove a site entry; delete the file if no sites remain.

        Returns:
            True if an entry was removed.
        """
        with self.locked():
            settings = self.load()
            key = site or settings.default_site
            if not key or key not in settings.sites:
                return False
            settings.sites.pop(key)
            if settings.default_site == key:
                settings.default_site = next(iter(settings.sites), None)
            if settings.sites:
                self._write(settings)
            else:
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
            return True


class FileTokenCredentialResolver(CredentialResolver):
    """Resolves Jira credentials from the local token file."""

    single_user: ClassVar[bool] = True

    def __init__(
        self,
        store: LocalJiraTokenStore,
        client_id: str,
        client_secret: str,
        site: Optional[str] = None,
        allowed_channels: Optional[set[str]] = None,
    ) -> None:
        self.store = store
        self.client_id = client_id
        self.client_secret = client_secret
        self.site = site
        self.allowed_channels = allowed_channels or {"cli", "local"}

    @classmethod
    def from_env(cls) -> "FileTokenCredentialResolver":
        """Build from JIRA_CLIENT_ID, JIRA_CLIENT_SECRET, JIRA_LOCAL_SITE."""
        client_id = os.environ.get("JIRA_CLIENT_ID", "")
        client_secret = os.environ.get("JIRA_CLIENT_SECRET", "")
        site = os.environ.get("JIRA_LOCAL_SITE")
        channels_env = os.environ.get("JIRA_LOCAL_ALLOWED_CHANNELS")
        channels = {c.strip() for c in channels_env.split(",") if c.strip()} if channels_env else None
        return cls(
            store=LocalJiraTokenStore(),
            client_id=client_id,
            client_secret=client_secret,
            site=site,
            allowed_channels=channels,
        )

    def _resolve_key(self) -> Optional[str]:
        return self.site or self.store.load().default_site

    async def resolve(self, channel: str, user_id: str) -> Optional[JiraTokenSet]:
        """Return the stored token, refreshing if expired."""
        token = self.store.get(self.site)
        if token is None:
            return None
        if not token.is_expired:
            return token
        key = self._resolve_key()
        # Acquire the cross-process lock without blocking the event loop.
        cm = self.store.locked()
        await asyncio.to_thread(cm.__enter__)
        try:
            # Another process may have refreshed while we waited.
            current = self.store.get(self.site)
            if current is None:
                return None
            if not current.is_expired:
                return current
            async with aiohttp.ClientSession() as session:
                data = await refresh_access_token(
                    session,
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    refresh_token=current.refresh_token,
                )
            now = time.time()
            refreshed = current.model_copy(
                update={
                    "access_token": data["access_token"],
                    # Atlassian sometimes omits a rotated refresh token: keep the old one.
                    "refresh_token": data.get("refresh_token") or current.refresh_token,
                    "expires_at": now + float(data.get("expires_in", 3600)),
                    "last_refreshed_at": now,
                }
            )
            self.store._save_unlocked(refreshed, make_default=False, key=key)
            return refreshed
        finally:
            cm.__exit__(None, None, None)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Not supported for local auth — use the CLI."""
        raise NotImplementedError("Use `parrot jiratoolkit auth` to authenticate locally.")

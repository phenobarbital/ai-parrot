# TASK-4419: Local Token Store and Credential Resolver

**Feature**: FEAT-696 — JiraToolkit upgrades
**Spec**: `sdd/specs/jiratoolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4418
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 3 — `LocalJiraTokenStore` (atomic file persistence with
> `fcntl` locking) and `FileTokenCredentialResolver` (subclass of `CredentialResolver`
> that refreshes expired tokens transparently). Depends on TASK-4418 for the
> `refresh_access_token` helper. Consumed by TASK-4421 (toolkit wiring) and
> TASK-4422 (CLI).

---

## Scope

- Create `jira_local_auth.py` with `LocalSettings`, `LocalJiraTokenStore`, and
  `FileTokenCredentialResolver`.
- Atomic writes via `os.replace` + temp file, `chmod 0600`, `fcntl.flock`.
- Transparent token refresh in `resolve()`: lock → re-read → refresh if still expired →
  keep old refresh_token when response omits one → write back.
- `get_auth_url()` raises `NotImplementedError`.
- `from_env()` class method reads `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`, `JIRA_LOCAL_SITE`.
- Write unit tests.

**NOT in scope**: toolkit wiring (TASK-4421), CLI commands (TASK-4422), or any
`jiratoolkit.py` edits.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py` | CREATE | Store + resolver |
| `packages/ai-parrot-tools/tests/unit/test_jira_local_auth.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import CredentialResolver              # verified: credentials.py:162
from parrot.auth.jira_oauth import (                                # verified: jira_oauth.py:59, :48
    JiraTokenSet, refresh_access_token,                             # refresh_access_token created by TASK-4418
)
```

### Existing Signatures to Use
```python
# parrot/auth/credentials.py:162
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]   # L166 (abstract)
    async def get_auth_url(self, channel: str, user_id: str) -> str        # abstract
    async def is_connected(self, channel: str, user_id: str) -> bool       # L179

# parrot/auth/jira_oauth.py:59
class JiraTokenSet(BaseModel):
    access_token: str; refresh_token: str; expires_at: float
    cloud_id: str; site_url: str; account_id: str; display_name: str
    is_expired: bool  # property, 60s leeway
```

### Does NOT Exist
- ~~`parrot_tools.jira_local_auth`~~ — does not exist yet; this task creates it
- ~~`LocalJiraTokenStore`~~ — does not exist yet
- ~~`FileTokenCredentialResolver`~~ — does not exist yet
- ~~`python-dotenv`~~ — not a declared dependency; do not `import dotenv`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jira_local_auth.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#CredentialResolver",
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraTokenSet"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- File mode `0600`, parent dir `0700`.
- `fcntl.flock` held across read → refresh → write in `resolve()`.
- After taking the lock, re-read the file — another process may have already refreshed.
- Keep old `refresh_token` when the response omits one (Atlassian sometimes does this).
- `single_user = True` class attribute on the resolver.
- Default path: `~/.parrot/jira/settings.local.json`, overridable via `JIRA_LOCAL_SETTINGS`.

---

## Implementation Blueprint

### Steps (in order)
1. Create `jira_local_auth.py` with `LocalSettings`, `LocalJiraTokenStore`, `FileTokenCredentialResolver` — *why*: core deliverable.
2. Create `test_jira_local_auth.py` — *why*: validates atomic save, 0600, refresh, NotImplementedError.

### `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py` (CREATE)
```python
"""Local Jira OAuth 2.0 token store and credential resolver (FEAT-696 M3)."""
from __future__ import annotations

import fcntl
import json
import logging
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar, Optional

import aiohttp
from pydantic import BaseModel

from parrot.auth.credentials import CredentialResolver  # verified: credentials.py:162
from parrot.auth.jira_oauth import JiraTokenSet          # verified: jira_oauth.py:59

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = Path("~/.parrot/jira/settings.local.json")


class LocalSettings(BaseModel):
    """Schema for the local settings file."""
    version: int = 1
    default_site: Optional[str] = None
    sites: dict[str, dict[str, Any]] = {}


class LocalJiraTokenStore:
    """Atomic, locked file store for Jira OAuth tokens."""

    def __init__(self, path: Optional[Path] = None) -> None:
        env_path = os.environ.get("JIRA_LOCAL_SETTINGS")
        self.path = Path(env_path) if env_path else (path or DEFAULT_SETTINGS_PATH)
        self.path = self.path.expanduser()

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

    def save(self, token: JiraTokenSet, *, make_default: bool = True) -> None:
        """Persist a token set atomically with mode 0600."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # FILL IN: fcntl lock → load → update sites dict → write temp file → os.replace
        #          → chmod 0600 — bounded by spec §2 M3 (atomic, 0600, fcntl lock)
        raise NotImplementedError

    def delete(self, site: Optional[str] = None) -> bool:
        """Remove a site entry; delete the file if empty."""
        # FILL IN: load → pop site → save or unlink — bounded by spec §2 M5 logout
        raise NotImplementedError


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
        channels = set(channels_env.split(",")) if channels_env else None
        return cls(
            store=LocalJiraTokenStore(),
            client_id=client_id,
            client_secret=client_secret,
            site=site,
            allowed_channels=channels,
        )

    async def resolve(self, channel: str, user_id: str) -> Optional[JiraTokenSet]:
        """Return the stored token, refreshing if expired."""
        token = self.store.get(self.site)
        if token is None:
            return None
        if not token.is_expired:
            return token
        # FILL IN: fcntl lock → re-read → skip if already refreshed →
        #          refresh_access_token() → keep old refresh_token if omitted →
        #          store.save() — bounded by spec §2 M3 + §7 Risks (rotating refresh tokens)
        raise NotImplementedError

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Not supported for local auth — use the CLI."""
        raise NotImplementedError("Use `parrot jiratoolkit auth` to authenticate locally.")
```
**Why this shape**: matches spec §3 M3 interface skeleton. `fcntl` locking and atomic
writes are security-critical (spec §7). `allowed_channels` supports the identity
guard (S9) consumed by TASK-4421.

### `packages/ai-parrot-tools/tests/unit/test_jira_local_auth.py` (CREATE)
```python
"""Tests for LocalJiraTokenStore and FileTokenCredentialResolver (FEAT-696 M3)."""
from __future__ import annotations

import json
import os
import stat
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class TestLocalJiraTokenStore:
    def test_save_creates_file_0600(self, tmp_path):
        # FILL IN: save a token, check file mode — bounded by AC4
        pass

    def test_save_atomic_replace(self, tmp_path):
        # FILL IN: save twice, verify second overwrites — bounded by spec §2 M3
        pass

    def test_get_default_site(self, tmp_path):
        # FILL IN: save with make_default, get without site — bounded by spec §2 M3
        pass

    def test_delete_removes_entry(self, tmp_path):
        # FILL IN: save then delete, verify gone — bounded by spec §2 M5
        pass


class TestFileTokenCredentialResolver:
    @pytest.mark.asyncio
    async def test_resolve_returns_valid_token(self, tmp_path):
        # FILL IN: store a non-expired token, resolve returns it — bounded by AC5
        pass

    @pytest.mark.asyncio
    async def test_resolve_refreshes_expired(self, tmp_path):
        # FILL IN: store an expired token, mock refresh_access_token, verify refresh
        #          and that rotated refresh_token is persisted — bounded by AC5
        pass

    @pytest.mark.asyncio
    async def test_get_auth_url_raises(self):
        # FILL IN: call get_auth_url, expect NotImplementedError — bounded by spec §3 M3
        pass

    def test_from_env(self, monkeypatch):
        # FILL IN: set env vars, call from_env, verify fields — bounded by spec §3 M3
        pass
```
**Why this shape**: spec §4 M3 test rows.

### FILL IN checklist
- [ ] `jira_local_auth.py::LocalJiraTokenStore.save` — atomic write with fcntl + 0600; bounded by spec §2 M3
- [ ] `jira_local_auth.py::LocalJiraTokenStore.delete` — pop site, unlink if empty; bounded by spec §2 M5
- [ ] `jira_local_auth.py::FileTokenCredentialResolver.resolve` — locked refresh flow; bounded by spec §2 M3 + §7
- [ ] `test_jira_local_auth.py` — all test bodies; bounded by spec §4 M3

---

## Acceptance Criteria

- [ ] `LocalJiraTokenStore.save()` creates a file with mode `0600` (AC4)
- [ ] Writes are atomic (`tempfile` + `os.replace`)
- [ ] `resolve()` refreshes an expired token and persists the rotated refresh token (AC5)
- [ ] `resolve()` keeps the old `refresh_token` when the response omits one
- [ ] `get_auth_url()` raises `NotImplementedError`
- [ ] `from_env()` reads `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`, `JIRA_LOCAL_SITE`
- [ ] `ruff check` clean; no new dependency

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jira_local_auth.py -q`

---

## Test Specification

See `test_jira_local_auth.py` in the blueprint above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug jiratoolkit-upgrades --feature-id FEAT-696`
2. **Read the spec** at `sdd/specs/jiratoolkit-upgrades.spec.md`
3. **Check dependencies** — TASK-4418 must be `"done"` (provides `refresh_access_token`)
4. **Verify the Codebase Contract** — confirm `CredentialResolver` at `credentials.py:162`
5. **Update status** in `sdd/tasks/index/jiratoolkit-upgrades.json` → `"in-progress"`
6. **Implement** — start from the blueprint, complete FILL IN markers
7. **Verify** acceptance criteria
8. **Commit** — stage only `jira_local_auth.py` and `test_jira_local_auth.py`
9. **Close** with `scripts/sdd/close_task.sh TASK-4419 jiratoolkit-upgrades verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any

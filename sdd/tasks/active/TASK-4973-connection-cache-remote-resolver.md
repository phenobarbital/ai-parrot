# TASK-4973: Encrypted ConnectionCache, RemoteConnectionResolver and build_cli_broker

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4972
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (G3, S4, S5, S9, AC-6): provider **access tokens only** are pulled from the server into
`~/.parrot/connections.cache`, AES-GCM encrypted with the login's random `cache_key` (§8 Q2: file only, no keyring),
mode 0600, every read/write off the event loop, single-flight refresh per provider. `RemoteConnectionResolver` is a
FEAT-264 `CredentialResolver`; `build_cli_broker` wires one per declared `credential_provider` into a
`CredentialBroker`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py`: `CachedConnection`, `ConnectionCache`,
  `RemoteConnectionResolver`, `open_connection_cache(store)`, `build_cli_broker(store, providers, *, client=None)`.
- Tests: encrypt round-trip, tamper/wrong key → empty + warning, `to_thread` spy, single-flight, hit/miss/not-connected,
  broker registration.

**NOT in scope**: who calls `build_cli_broker` (TASK-4976, TASK-4978); `parrot connect` (TASK-4977); OS keyring (§8 Q2: rejected).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py` | CREATE | cache + resolver + broker builder |
| `packages/ai-parrot/tests/auth/test_connection_cache.py` | CREATE | cache/resolver/broker tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM      # cryptography 50.x (transitive via navigator-auth/pyopenssl)
from cryptography.exceptions import InvalidTag
from parrot.auth.credentials import CredentialResolver               # credentials.py:192
from parrot.auth.broker.core import CredentialBroker                 # broker/core.py:32
from parrot.auth.oauth2.remote_client import NotConnected, ServerConnectionsClient   # TASK-4972
from parrot.cli.login import LoginStore                              # TASK-4968 (LoginStore.cache_path, load_optional)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialResolver(ABC):                                        # :192
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]   # abstract
    async def get_auth_url(self, channel: str, user_id: str) -> str        # abstract
    async def is_connected(self, channel: str, user_id: str) -> bool       # concrete
# packages/ai-parrot/src/parrot/auth/broker/core.py
class CredentialBroker:                                               # :32
    def __init__(self, *, audit_ledger=None, identity_mapper=None) -> None   # :68
    def register(self, provider: str, resolver: CredentialResolver, auth_kind: str = "oauth2") -> None   # :81
    async def resolve(self, provider, channel, user_id, **ctx) -> ResolvedCredential | NeedsAuth   # :156 (miss → NeedsAuth(auth_url=resolver.get_auth_url))
# TASK-4972: ServerConnectionsClient(store).pull_token(provider) -> PulledToken | raises NotConnected ;
#            start_connect(provider, *, channel="cli") -> ConnectAttempt(.auth_url)
# TASK-4968: LoginStore.cache_path (login dir / "connections.cache") ; LoginRecord.cache_key (urlsafe b64 of 32 bytes)
```

### Does NOT Exist
- ~~AES-GCM helpers in `parrot.security.vault_utils`~~ — the spec's §2 pointer is wrong: `vault_utils` is the DocumentDB
  vault (`store_vault_credential` …) and `credentials_utils` seals with a navigator-session `KeyRing`. Use
  `cryptography`'s `AESGCM` directly with the raw 32-byte `cache_key`.
- ~~`CredentialBroker.add_resolver()`~~ — the method is `register()` (`core.py:81`).
- ~~a refresh token in the cache~~ — never (S5): `CachedConnection` has no such field.
- ~~exporting from `parrot/auth/oauth2/__init__.py`~~ — import cycle (see TASK-4972); import from the module.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_connection_cache.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#CredentialResolver",
    "sym:packages/ai-parrot/src/parrot/auth/broker/core.py#CredentialBroker"
  ]
}
```

---

## Implementation Notes

- File format: `b"PCC1" + nonce(12) + AESGCM(key).encrypt(nonce, json_bytes, b"parrot-connections-cache-v1")`; JSON is
  `{provider: CachedConnection.model_dump(mode="json")}`. A fresh random nonce on every write.
- Missing file → empty. Bad magic / `InvalidTag` / bad JSON → `self.logger.warning("connection cache unreadable; treating
  as empty")` and empty (AC-6). Wrong key behaves like tamper.
- All file I/O in `asyncio.to_thread`; an `asyncio.Lock` serializes read-modify-write within the process; atomic write
  (mkstemp + fchmod 0600 + os.replace) like `LoginStore.save`.
- `RemoteConnectionResolver.resolve`: cache hit when `expires_at - skew_s > time.time()`; otherwise, under the
  per-provider lock, re-check the cache then `pull_token` → `cache.put` → token. `NotConnected` → `None` (broker then
  yields `NeedsAuth`). Other client errors propagate (fail closed, the tool surfaces an error).
- `get_auth_url` returns `(await client.start_connect(provider, channel=channel)).auth_url`.
- `build_cli_broker` is sync: login missing → `ValueError("no login")`; key = `urlsafe_b64decode(cache_key + padding)`
  must be 32 bytes.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `local_cache.py` from the block — *why*: §3 M4 fixes the four public names.
2. Complete the cache I/O and resolver single-flight FILL INs — *why*: AC-6, S9.
3. Write the tests and run the validation commands (FEAT-264 broker tests must stay green).

### `packages/ai-parrot/src/parrot/auth/oauth2/local_cache.py` (CREATE)
```python
"""AES-GCM local cache of provider access tokens + remote resolver (FEAT-774 M4). Never stores refresh tokens."""
from __future__ import annotations

import asyncio, base64, json, logging, os, tempfile, time
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
        # FILL IN: missing → {}; magic/nonce split; decrypt with _AAD; InvalidTag/ValueError/JSON error → warning + {} — AC-6
        raise NotImplementedError

    def _write_sync(self, entries: Dict[str, CachedConnection]) -> None:
        # FILL IN: nonce = os.urandom(12); blob = _MAGIC + nonce + encrypt(...); mkstemp in parent (mkdir 0o700),
        #          fchmod 0600, fsync, os.replace — AC-6
        raise NotImplementedError

    async def get(self, provider: str) -> Optional[CachedConnection]:
        return (await asyncio.to_thread(self._read_sync)).get(provider)

    async def put(self, entry: CachedConnection) -> None:
        async with self._lock:
            entries = await asyncio.to_thread(self._read_sync)
            entries[entry.provider] = entry
            await asyncio.to_thread(self._write_sync, entries)

    async def delete(self, provider: Optional[str] = None) -> None:
        """Delete one provider, or the whole file when ``provider`` is None."""
        # FILL IN: provider None → unlink(missing_ok=True) in to_thread; else read-modify-write under self._lock
        raise NotImplementedError


class RemoteConnectionResolver(CredentialResolver):
    """Answer from the cache; otherwise pull the access token from the server (single-flight per provider)."""

    def __init__(self, provider: str, *, cache: ConnectionCache, client: ServerConnectionsClient, skew_s: int = 60) -> None:
        self.provider = provider
        self.cache = cache
        self.client = client
        self.skew_s = skew_s
        self._lock = asyncio.Lock()

    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        # FILL IN: hit when expires_at - skew_s > time.time(); else under self._lock re-check, pull_token → cache.put(
        #          CachedConnection(..., pulled_at=time.time())) → access_token; NotConnected → None — S9, AC-6
        raise NotImplementedError

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return (await self.client.start_connect(self.provider, channel=channel)).auth_url


def open_connection_cache(store: LoginStore) -> ConnectionCache:
    """Cache next to the login file, keyed by the login's cache_key; ValueError without a login."""
    record = store.load_optional()
    if record is None:
        raise ValueError("no login — run `parrot login`")
    padded = record.cache_key + "=" * (-len(record.cache_key) % 4)
    return ConnectionCache(store.cache_path, base64.urlsafe_b64decode(padded))


def build_cli_broker(
    store: LoginStore, providers: Iterable[str], *, client: Optional[ServerConnectionsClient] = None,
) -> CredentialBroker:
    """One RemoteConnectionResolver per provider, ``auth_kind="oauth2"`` (verified: broker/core.py:68, :81)."""
    cache = open_connection_cache(store)
    client = client or ServerConnectionsClient(store)
    broker = CredentialBroker()
    for provider in sorted(set(providers)):
        broker.register(provider, RemoteConnectionResolver(provider, cache=cache, client=client), auth_kind="oauth2")
    return broker
```
**Why this shape**: spec §3 M4 fixes `ConnectionCache`, `RemoteConnectionResolver` and `build_cli_broker`;
`open_connection_cache` is the shared constructor `parrot connect` and `parrot disconnect` (TASK-4977) reuse so the
key/path rule lives in one place.

### `packages/ai-parrot/tests/auth/test_connection_cache.py` (CREATE)
```python
"""ConnectionCache / RemoteConnectionResolver / build_cli_broker (FEAT-774 M4, AC-6)."""
import asyncio, os, time
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.local_cache import CachedConnection, ConnectionCache, RemoteConnectionResolver, build_cli_broker


async def test_connection_cache_encrypt_roundtrip_and_tamper(tmp_path, caplog):
    # FILL IN: put/get round-trip; file mode 0600; plaintext token not in raw bytes; flip a byte → get() None + warning;
    #          other key → None
    ...

async def test_cache_io_off_event_loop_and_single_flight(tmp_path, monkeypatch):
    # FILL IN: spy asyncio.to_thread; 10 concurrent resolve() → client.pull_token awaited once
    ...

async def test_remote_resolver_hit_miss_not_connected(tmp_path):
    # FILL IN: fresh entry → no pull; expired → pull; NotConnected → None; get_auth_url == start_connect().auth_url
    ...

def test_build_cli_broker_registers_declared_providers(tmp_path):
    # FILL IN: providers {"jira", "fake"} → broker has both, auth_kind "oauth2"
    ...
```

### FILL IN checklist
- [ ] `ConnectionCache._read_sync` / `_write_sync` / `delete` — format, tamper handling, atomic 0600 write; bounded by AC-6
- [ ] `RemoteConnectionResolver.resolve` — skew check + single-flight; bounded by S9
- [ ] tests — encryption, tamper, to_thread spy, single-flight, broker

---

## Acceptance Criteria

- [ ] Cache file is AES-GCM encrypted with the login `cache_key`, mode 0600; tampered/undecryptable → empty with a warning (AC-6)
- [ ] Every cache read/write runs via `asyncio.to_thread`; concurrent resolves for one provider pull once (S9)
- [ ] `NotConnected` → `resolve()` returns `None`; `get_auth_url` returns the server-issued auth URL
- [ ] `build_cli_broker` registers one `oauth2` resolver per provider; no refresh token is ever cached (S5)
- [ ] FEAT-264 broker tests stay green; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_connection_cache.py -q`
- `pytest packages/ai-parrot/tests/unit/test_credential_broker.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/auth/test_connection_cache.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

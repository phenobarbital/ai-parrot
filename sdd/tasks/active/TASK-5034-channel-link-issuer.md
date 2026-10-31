# TASK-5034: ChannelLinkIssuer — single-use Slack link nonces + link config

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Slack linking (M2, D2)": Slack `/login` DMs an opaque one-time link; the logged-in admin UI previews and
confirms it. The nonce only says *which Slack user* is being linked — the principal always comes from the web
session. This task builds the core primitive: a Redis-backed issuer with `issue` / `peek` / `consume`, plus the two
config values. Consumers: the server confirm handler (TASK-5041) and the Slack `/login` command (TASK-5044).
**D5**: `CONNECTIONS_LINK_BASE_URL` is required config with no default.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/channel_link.py` with `ChannelLinkClaim` (Pydantic) and `ChannelLinkIssuer`.
- Redis key `channel_link:{nonce}`, nonce `secrets.token_urlsafe(32)`, TTL `ttl_seconds` (default 600), value = claim JSON.
- `issue()` returns `f"{base_url}/account/link?token={nonce}"` (base URL with trailing `/` stripped); `ValueError` on empty
  `channel` / `channel_user_id` or empty `base_url` (D5: unset config is not silently defaulted).
- `peek()` reads without deletion or TTL extension (`GET`); `consume()` is atomic single-use (`GETDEL`).
  Both return `None` for missing/expired/consumed or malformed values (malformed → logged).
- `extra` holds non-secret strings only; reject keys `access_token`, `refresh_token`, `id_token`, `token`, `client_secret` (`ValueError`).
- Add `CONNECTIONS_LINK_BASE_URL` (fallback `""`) and `CHANNEL_LINK_TTL_SECONDS` (getint, fallback 600) to `parrot/conf.py`.
- Write tests against real Redis db 15 (skip if unreachable).

**NOT in scope**: HTTP handlers (TASK-5041), Slack commands (TASK-5044), identity writes (TASK-5036), `ChannelLinkPreview` (TASK-5035).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/channel_link.py` | CREATE | `ChannelLinkClaim`, `ChannelLinkIssuer` |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `CONNECTIONS_LINK_BASE_URL`, `CHANNEL_LINK_TTL_SECONDS` |
| `packages/ai-parrot/tests/unit/auth/test_channel_link.py` | CREATE | Real-Redis unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import secrets, time, logging                                       # stdlib
from pydantic import BaseModel, Field                               # pydantic v2 (project standard)
import redis.asyncio as aioredis                                    # tests only; redis 5.2.1 (GETDEL needs Redis server >= 6.2)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py
REDIS_URL = config.get("REDIS_URL", fallback=...)                                          # :308
WEB_OAUTH_ALLOWED_ORIGINS = config.get("WEB_OAUTH_ALLOWED_ORIGINS", fallback=[])           # :756
if isinstance(WEB_OAUTH_ALLOWED_ORIGINS, str):                                             # :757
    WEB_OAUTH_ALLOWED_ORIGINS = [o.strip() for o in WEB_OAUTH_ALLOWED_ORIGINS.split(",") if o.strip()]  # :758
ONTOLOGY_CACHE_TTL = config.getint("ONTOLOGY_CACHE_TTL", fallback=86400)                   # :160 (getint pattern)
# The server's shared client is app["redis"] = aioredis.from_url(REDIS_URL, decode_responses=True)
#   (packages/ai-parrot-server/src/parrot/manager/manager.py:1732-1735) — values come back as str.
```

### Does NOT Exist
- ~~`parrot.auth.channel_link`~~, ~~`CONNECTIONS_LINK_BASE_URL`~~, ~~`CHANNEL_LINK_TTL_SECONDS`~~ — created here.
- ~~A default link base URL derived from `WEB_OAUTH_ALLOWED_ORIGINS`~~ — rejected by D5.
- ~~`fakeredis`~~ — not installed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/channel_link.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/auth/test_channel_link.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Core module: no server/integrations imports; the Redis client is injected (`Any`), works with `decode_responses=True`
  (str) and `False` (bytes — decode before parsing).
- Never log the nonce or the full link (it is a bearer token for linking); log channel only.
- `consume` must be a single atomic command (`GETDEL`) — never `GET` then `DEL` (race → double use).

---

## Implementation Blueprint

### Steps (in order)
1. Add the two config values after the `WEB_OAUTH_ALLOWED_ORIGINS` normalisation — *why*: keeps OAuth/link web settings together.
2. Create `channel_link.py` from the block below and fill the gaps.
3. Write the tests and run them.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    WEB_OAUTH_ALLOWED_ORIGINS = [o.strip() for o in WEB_OAUTH_ALLOWED_ORIGINS.split(",") if o.strip()]' packages/ai-parrot/src/parrot/conf.py)
# AFTER — insert below that line (verified: conf.py:758)
# FEAT-777 (D5): base URL of the admin UI used in Slack /login account-link DMs. Required — no default;
# when empty, Slack /login replies "account linking is not configured".
CONNECTIONS_LINK_BASE_URL = config.get("CONNECTIONS_LINK_BASE_URL", fallback="")
# FEAT-777: lifetime of a single-use channel-link nonce, in seconds.
CHANNEL_LINK_TTL_SECONDS = config.getint("CHANNEL_LINK_TTL_SECONDS", fallback=600)
```

### `packages/ai-parrot/src/parrot/auth/channel_link.py` (CREATE)
```python
"""Single-use channel-link nonces (FEAT-777 M2, D2).

A nonce binds *which* channel user is being linked; the Navigator principal always comes from the
authenticated web session that confirms it.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_KEY_PREFIX = "channel_link:"
_SECRET_KEYS = frozenset({"access_token", "refresh_token", "id_token", "token", "client_secret"})


class ChannelLinkClaim(BaseModel):
    """The channel identity a link nonce stands for."""

    channel: str                                   # "slack" in v1
    channel_user_id: str                           # team-qualified: "{team_id}:{slack_user_id}"
    extra: Dict[str, str] = Field(default_factory=dict)   # {team_id, slack_user_id}; never secrets
    issued_at: float


class ChannelLinkIssuer:
    """Redis key ``channel_link:{nonce}``, TTL ``ttl_seconds``, ``GETDEL`` on consume."""

    def __init__(self, redis_client: Any, *, base_url: str, ttl_seconds: int = 600) -> None:
        self._redis = redis_client
        self._base_url = (base_url or "").rstrip("/")
        self._ttl = int(ttl_seconds)
        self.logger = logger

    async def issue(self, channel: str, channel_user_id: str, extra: Optional[Dict[str, str]] = None) -> str:
        """Store a claim and return ``{base_url}/account/link?token={nonce}``.

        Raises:
            ValueError: empty channel / channel_user_id / base_url, or a secret-looking key in ``extra``.
        """
        # FILL IN: validations (D5 → empty base_url raises), build ChannelLinkClaim(issued_at=time.time()),
        #   nonce = secrets.token_urlsafe(32), SET key value EX ttl (NX), return the URL — bounded by spec M2 skeleton
        ...

    async def peek(self, nonce: str) -> Optional[ChannelLinkClaim]:
        """Read without deletion or TTL extension; ``None`` when missing or expired."""
        # FILL IN: GET; None/empty nonce → None; parse via self._parse — bounded by AC-5 (load never consumes)
        ...

    async def consume(self, nonce: str) -> Optional[ChannelLinkClaim]:
        """Single use: ``None`` when missing, expired or already consumed."""
        # FILL IN: GETDEL (await self._redis.getdel(key)); parse via self._parse — bounded by "atomic single use"
        ...

    def _parse(self, raw: Any) -> Optional[ChannelLinkClaim]:
        """Decode bytes/str JSON into a claim; malformed → log (no nonce) and ``None``."""
        # FILL IN
        ...
```
**Why this shape**: the constructor and three async methods are fixed by spec §3 M2; `_parse` keeps `peek`/`consume`
symmetric. `NX` on `SET` guards the astronomically unlikely nonce collision instead of overwriting a live claim.

### `packages/ai-parrot/tests/unit/auth/test_channel_link.py` (CREATE)
```python
"""Real-Redis tests for ChannelLinkIssuer (FEAT-777 M2). Skips when Redis db 15 is unreachable."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
import redis.asyncio as aioredis

from parrot.auth.channel_link import ChannelLinkClaim, ChannelLinkIssuer


@pytest.fixture
async def redis_client():
    client = aioredis.from_url("redis://localhost:6379/15", decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        pytest.skip(f"Redis unreachable: {exc}")
    yield client
    await client.aclose()


def _nonce(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


@pytest.mark.asyncio
async def test_channel_link_issue_consume_single_use(redis_client) -> None:
    """consume once → claim; second consume → None; after TTL → None."""
    # FILL IN: issuer(ttl_seconds=1); issue("slack", "T01:U02", {"team_id": "T01", "slack_user_id": "U02"});
    #   consume → claim fields; consume again → None; a second issued link after asyncio.sleep(1.2) → None
    ...


@pytest.mark.asyncio
async def test_peek_does_not_consume_or_extend(redis_client) -> None:
    # FILL IN: peek twice returns claim; TTL (await redis_client.ttl(key)) not increased; consume still works once
    ...


@pytest.mark.asyncio
async def test_issue_validation(redis_client) -> None:
    # FILL IN: empty channel_user_id, empty base_url (D5) and extra={"token": "x"} raise ValueError; URL shape is
    #   f"{base}/account/link?token=..." with a trailing "/" on base_url stripped
    ...
```

### FILL IN checklist
- [ ] `issue` validations + SET EX NX — bounded by spec M2 skeleton and D5.
- [ ] `peek` (GET only) / `consume` (GETDEL) — bounded by AC-5.
- [ ] `_parse` bytes/str + malformed handling, never logging the nonce.
- [ ] Three test bodies — bounded by spec §4 `test_channel_link_issue_consume_single_use`, `test_channel_link_preview_read_only` (issuer side).

---

## Acceptance Criteria

- [ ] `from parrot.auth.channel_link import ChannelLinkIssuer, ChannelLinkClaim` works.
- [ ] `from parrot.conf import CONNECTIONS_LINK_BASE_URL, CHANNEL_LINK_TTL_SECONDS` works (defaults `""`, `600`).
- [ ] `consume` is single-use and atomic; `peek` never deletes or extends TTL.
- [ ] Empty base URL raises (D5); secrets rejected in `extra`; nonce never logged.
- [ ] Tests pass (or skip without Redis); `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_channel_link.py -q`

---

## Test Specification

See the CREATE test block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (§2 "Slack linking (M2, D2)", §3 Module 2, §8 D5)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing code
5. **Update status** → `"in-progress"` and commit only the index file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5034 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

# TASK-5058: End-to-end integration tests for web + Slack connections

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5040, TASK-5041, TASK-5044, TASK-5046, TASK-5047, TASK-5051
**Assigned-to**: unassigned

---

## Context

Spec §4 "Integration Tests" and AC-12 ("the multi-worker SSE, Slack linked/unlinked and O365 exactly-once migration
tests pass"). Unit tests in each module task prove the parts; these five tests prove the flows across them:

| Test | Proves | Built by |
|---|---|---|
| `test_e2e_slack_link_then_connect` | `/login` → read-only preview → explicit confirm → authorized `/connect jira` → callback → Slack DM + principal-owned row (AC-5, AC-6, AC-14) | TASK-5034 TASK-5036 TASK-5041 TASK-5042 TASK-5044 |
| `test_e2e_forwarded_slack_link` | opening another Slack user's link never binds automatically; Cancel/no-confirm leaves identities untouched (AC-5) | TASK-5041 |
| `test_e2e_chat_partial_execution_auth` | a mutation completes before another tool needs auth → no automatic replay in either mode (AC-7) | TASK-5050 TASK-5051 |
| `test_e2e_web_panel_live_update` | callback on `channel="telegram"` → SSE subscriber of the same principal gets `connection.completed`; another principal gets nothing (AC-2, AC-3) | TASK-5032 TASK-5033 TASK-5040 |
| `test_e2e_o365_device_and_web_share_record` | device grant stored → `GET /api/v1/connections` shows o365 connected with `grant_origin=device_code` → 3LO reconnect replaces it (AC-8) | TASK-5045 TASK-5046 TASK-5047 |

---

## Scope

- Create four test modules under `tests/integration/oauth2/` (one per flow; the two Slack-link tests share a module).
- Reuse the existing doubles: `FakeManager`, `FakeCredentialStore`, `MemRedis` from
  `tests/integration/oauth2/test_connections_isolation_matrix.py`, `make_mock_db` from `tests/integration/oauth2/helpers.py`,
  and the fixtures in `tests/integration/oauth2/conftest.py` (`web_user_id`, `jira_token_set_factory`, `allowed_origins`).
- Redis-backed flows (SSE, link nonces) use a real Redis db 15 with a unique key prefix and `pytest.skip` when Redis is
  unreachable — **fakeredis is not installed** in this venv.
- The identity-ownership step uses a real DB only where an existing fixture provides one; otherwise a
  `claim_channel_identity` double that enforces the single-owner rule (the real-DB race test lives in TASK-5036).

**NOT in scope**: changing production code — if a flow fails, file the defect against the owning task
(`wikitoolkit ledger open ... --discovered-from spec:FEAT-777`) instead of patching here; UI flows (vitest in
TASK-5053–TASK-5057).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integration/oauth2/test_e2e_slack_link.py` | CREATE | `test_e2e_slack_link_then_connect`, `test_e2e_forwarded_slack_link` |
| `tests/integration/oauth2/test_e2e_chat_partial_execution_auth.py` | CREATE | `test_e2e_chat_partial_execution_auth` |
| `tests/integration/oauth2/test_e2e_web_panel_live_update.py` | CREATE | `test_e2e_web_panel_live_update` |
| `tests/integration/oauth2/test_e2e_o365_device_and_web_share_record.py` | CREATE | `test_e2e_o365_device_and_web_share_record` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                                       # verified: test_e2e_web_connect.py
from aiohttp.test_utils import make_mocked_request                            # verified: test_e2e_web_connect.py
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher, ConnectionEvent  # verified: events.py:41, :70, :17
from parrot.auth.oauth2.models import AuthRequiredEnvelope                    # verified: oauth2/models.py:118
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry                # verified: registry.py:69
from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider               # verified: used in test_e2e_web_connect.py
from parrot.auth.oauth2.service import IntegrationsService                    # verified: service.py:65
from parrot.auth.oauth2_routes import make_oauth2_callback                    # verified: used in test_e2e_web_connect.py
from parrot.auth.principal import Principal, set_principal_resolver           # verified: principal.py:18, :62
from parrot.tools import tool                                                 # verified: test_connections_isolation_matrix.py:24
from parrot.tools.manager import ToolManager                                  # verified: test_connections_isolation_matrix.py:25
from .test_connections_isolation_matrix import FakeCredentialStore, FakeManager, MemRedis   # verified: test_e2e_web_connect.py
from .helpers import make_mock_db                                             # verified: tests/integration/oauth2/helpers.py
# Created by this feature (verify the merged names before use):
#   parrot.auth.channel_link.ChannelLinkIssuer (TASK-5034)
#   parrot.handlers.channel_links.ChannelLinksHandler (TASK-5041)
#   parrot.handlers.connection_events.ConnectionEventsHandler (TASK-5040)
#   parrot.services.connection_push.RedisConnectionPush (TASK-5033)
#   parrot.integrations.slack.commands.connection_commands.register_connection_commands (TASK-5044)
#   parrot.integrations.slack.notifier.SlackConnectionNotifier (TASK-5042)
#   parrot.auth.o365_oauth.O365OAuthManager.store_device_grant (TASK-5045)
#   parrot.auth.retry_safety (TASK-5050); AgentTalk trailer/envelope helpers (TASK-5051)
```

### Existing Signatures to Use
```python
# tests/integration/oauth2/test_e2e_web_connect.py — pattern for a full callback round trip:
#   manager = FakeManager("client", "https://app.example.com/oauth/callback", client_secret="secret",
#                         redis_client=MemRedis(), credential_store=FakeCredentialStore())
#   OAuth2ProviderRegistry().register(JiraOAuth2Provider(manager=manager))
#   _, nonce = await manager.create_authorization_url("web", uid, principal=..., extra_state={...})
#   request = make_mocked_request("GET", f"/api/auth/jira/callback?code=code-1&state={nonce}", app=app)
#   with patch("parrot.auth.oauth2.persistence.DocumentDb", mock_db_cls): response = await make_oauth2_callback("jira")(request)
# tests/integration/oauth2/test_connections_isolation_matrix.py:217-263 — cross-channel reuse, isolation, unlinked-user patterns
# tests/integration/oauth2/test_e2e_telegram_regression.py:25-62 — dict-backed principal resolver double for several channels
```

### Does NOT Exist
- ~~`fakeredis`~~ — not installed in the venv or any pyproject; use real Redis db 15 + skip-if-unreachable.
- ~~A shared Redis fixture under `tests/integration/oauth2/`~~ — write a local one (unique prefix, `FLUSH` only your keys).
- ~~`tests/integration/oauth2/test_e2e_slack_*.py`~~ — none exist yet.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/integration/oauth2/test_e2e_slack_link.py", "action": "CREATE"},
    {"path": "tests/integration/oauth2/test_e2e_chat_partial_execution_auth.py", "action": "CREATE"},
    {"path": "tests/integration/oauth2/test_e2e_web_panel_live_update.py", "action": "CREATE"},
    {"path": "tests/integration/oauth2/test_e2e_o365_device_and_web_share_record.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEventPublisher",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ChannelNotifierRegistry",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService",
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#set_principal_resolver"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Reset process-wide singletons between tests: `ChannelNotifierRegistry._reset()` (events.py:53-55),
  `OAuth2ProviderRegistry` registrations, and `set_principal_resolver(None)` — in fixtures' teardown.
- The chat test must assert on **observable side effects** (a counter incremented by the mutating tool), not only on
  `retry_safe=False`: AC-7 says "mutation-before-auth tests prove no duplicate side effects".
- The SSE test opens two subscribers (same principal on two app instances sharing one Redis → both receive; a second
  principal → receives nothing within a bounded wait, e.g. 0.5 s).
- Never print; assert with clear messages.

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged public APIs of every "created by this feature" symbol above — *why*: tests must use real names.
2. Write the four modules with shared local fixtures — *why*: one flow per module keeps failures attributable.
3. Run them; any failure is a production defect for the owning task, not a test to loosen.

### `tests/integration/oauth2/test_e2e_slack_link.py` (CREATE)
```python
"""Slack link → connect flows (FEAT-777 AC-5, AC-6, AC-14)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_e2e_slack_link_then_connect() -> None:
    # FILL IN: /login via register_connection_commands → token in returned URL; GET preview (session user 1042) shows
    # T01/U02 and does not consume; POST confirm {confirm: true} → linked; resolver now maps ("slack","T01:U02") → 1042;
    # /connect jira with an ALLOW authorizer → start_connect state; callback → credential row for 1042 and one
    # SlackConnectionNotifier DM (mock client) — bounded by AC-5/AC-6/AC-14
    ...


async def test_e2e_forwarded_slack_link() -> None:
    # FILL IN: user B (session 2077) opens A's link: preview shows A's Slack ids; no confirm → no identity row and the
    # nonce still peeks; resolve_principal("slack", A) stays None — bounded by AC-5
    ...
```

### `tests/integration/oauth2/test_e2e_chat_partial_execution_auth.py` (CREATE)
```python
"""Mutation before auth never replays (FEAT-777 AC-7)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("mode", ["non_streaming", "streaming"])
async def test_e2e_chat_partial_execution_auth(mode: str) -> None:
    # FILL IN: one turn calls tool A (increments a counter) then tool B returning authorization_required; the response
    # carries auth_required with retry_safe False (envelope or trailer per mode); simulate connection.completed and
    # assert no automatic resend path is taken and the counter is still 1 — bounded by AC-7
    ...
```

### `tests/integration/oauth2/test_e2e_web_panel_live_update.py` (CREATE)
```python
"""Cross-channel completion reaches the web SSE stream (FEAT-777 AC-2, AC-3)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_e2e_web_panel_live_update() -> None:
    # FILL IN: real Redis db 15 (skip if unreachable); publisher with RedisConnectionPush sink; two subscribers for
    # user 1042 (separate RedisConnectionPush instances = two workers) and one for 2077; callback/publish with
    # channel="telegram" for 1042 → both 1042 streams get connection.completed within 2 s; 2077 gets nothing;
    # payload keys == ConnectionEvent fields (no token keys) — bounded by AC-2/AC-3
    ...
```

### `tests/integration/oauth2/test_e2e_o365_device_and_web_share_record.py` (CREATE)
```python
"""One O365 record for device code and 3LO (FEAT-777 AC-8)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_e2e_o365_device_and_web_share_record() -> None:
    # FILL IN: O365OAuthManager with FakeCredentialStore; store_device_grant(principal 1042, payload, channel="cli") →
    # IntegrationsService.list_for_principal shows o365 connected; stored token set grant_origin == "device_code";
    # a 3LO callback for the same principal replaces it (grant_origin == "authorization_code"); VaultTokenSync never
    # called for o365 — bounded by AC-8
    ...
```

### FILL IN checklist
- [ ] Five test bodies, each asserting the AC it names.
- [ ] Local Redis fixture with skip-if-unreachable and prefix cleanup.
- [ ] Singleton resets in teardown.

---

## Acceptance Criteria

- [ ] All five tests exist and pass (Redis-backed ones may skip only when Redis is unreachable).
- [ ] The chat test proves no duplicate side effect in both response modes (AC-7).
- [ ] No production file is modified by this task.

---

## Validation Commands

- `pytest tests/integration/oauth2/test_e2e_slack_link.py -q`
- `pytest tests/integration/oauth2/test_e2e_chat_partial_execution_auth.py -q`
- `pytest tests/integration/oauth2/test_e2e_web_panel_live_update.py -q`
- `pytest tests/integration/oauth2/test_e2e_o365_device_and_web_share_record.py -q`

---

## Test Specification

See the four CREATE blocks above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (§4 Integration Tests; AC-2/3/5/6/7/8/14)
3. **Check dependencies** — all `Depends-on` tasks `"done"`
4. **Verify** every created-by-this-feature symbol's merged name and signature
5. **Update status** → `"in-progress"`; commit only the index
6. **Implement** the tests
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-integrations/src`
8. **Commit** only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-5058 connections-web-slack verified`
10. **Completion Note** — list any production defects filed to the ledger

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat codex luna
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any

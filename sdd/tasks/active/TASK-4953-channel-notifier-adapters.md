# TASK-4953: ChannelNotifier adapters for Telegram, Slack and MS Teams Jira completion

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4938
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 adapters (G6, G8, U5, AC-7, AC-9). Today `jira_oauth_callback` (routes.py:232) calls channel code
directly: the Telegram session stamper + `TelegramOAuthNotifier`, `handle_slack_jira_callback` (DM + identity write)
and `handle_msteams_jira_callback` (proactive card + nav_user_id-guarded identity write). Those side effects move
into three `ChannelNotifier` adapters that the publisher awaits. Behaviour must be the same as before (parity).

---

## Scope

- New `integrations/core/auth/notifiers.py`: `TelegramJiraNotifierAdapter(app)` (channel `telegram`),
  `SlackJiraNotifierAdapter(app)` (`slack`), `MSTeamsJiraNotifierAdapter(app)` (`msteams`). Each reads its wrapped
  notifier from `app` at notify time (`app['jira_oauth_notifier']`, `app['slack_jira_oauth_notifier']`,
  `app['msteams_jira_oauth_notifier']`) and the stamper / `identity_mapping_service` the old handlers used.
- On `connection.completed`: same messages and identity writes as the old handlers, using `state_payload["extra"]`
  (chat_id / team_id / slack_user_id / conversation_reference) and `state_payload["connection_meta"]["site_url"]`.
- On `connection.refresh_failed` / `connection.revoked`: Telegram/Slack `notify_failure`; Teams: best-effort message or no-op (document).
- Only act when `event.provider == "jira"` (these adapters are Jira-specific); other providers → no-op.
- Test `test_notifier_adapters_delegate`.

**NOT in scope**: registering the adapters (TASK-4955); deleting the old callback (TASK-4958).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | CREATE | three adapters |
| `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.oauth2.events import ChannelNotifier, ConnectionEvent           # TASK-4938
from parrot.integrations.telegram.jira_commands import TelegramOAuthNotifier     # verified: telegram/jira_commands.py:192
from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier          # verified: slack/oauth_callback.py:74
from parrot.integrations.msteams.oauth_callback import MSTeamsOAuthNotifier      # verified: msteams/oauth_callback.py:89
```

### Existing Signatures to Use
```python
# telegram/jira_commands.py
class TelegramOAuthNotifier:                                  # :192
    async def notify_connected(self, chat_id: int, display_name: str, site_url: str) -> None   # :205
    async def notify_failure(self, chat_id: int, reason: str) -> None
# telegram/wrapper.py:473  app["telegram_jira_session_stamper"] = _stamp   — called as stamper(str(telegram_user_id), token_set)
#   (routes.py:300-310); the adapter has no token_set: FILL IN — verify what _stamp reads from token_set and pass a
#   minimal object with those non-secret attributes (display_name, site_url, account_id, cloud_id)
# slack/oauth_callback.py
class SlackOAuthNotifier:                                     # :74
    async def notify_connected(self, team_id: str, slack_user_id: str, display_name: str, site_url: str) -> None   # :97
    async def notify_failure(...)                             # :127
async def handle_slack_jira_callback(request, token_set, state_payload)   # :157 — fields via _field(name) from extra/state;
                                                                          #   identity write via app["identity_mapping_service"].upsert_identity(...) (:238-260)
# msteams/oauth_callback.py
class MSTeamsOAuthNotifier:                                   # :89
    async def notify_connected(self, conversation_ref_dict: Dict[str, Any], display_name: str, site_url: str) -> None  # :105
async def handle_msteams_jira_callback(request, token_set, state_payload)  # :182 — nav_user_id digit-guarded identity write (:258-290)
# routes.py:232-331 jira_oauth_callback — the behaviour to reproduce (Telegram stamper + notifier via asyncio.create_task)
# IdentityMappingService.upsert_identity(*, nav_user_id, auth_provider, provider_user_id, auth_data, display_name=None,
#   email=None, token=None)   # identity_mapping.py:173
```

### Does NOT Exist
- ~~a navigator_eventbus consumer in integrations~~ — none; adapters are in-process.
- ~~`ConnectionEvent.site_url`~~ — not a field; read `state_payload["connection_meta"]["site_url"]` (TASK-4940/4954).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py#TelegramOAuthNotifier",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py#MSTeamsOAuthNotifier",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py#SlackOAuthNotifier"
  ]
}
```

---

## Implementation Notes

- Read the three old handlers fully before writing: copy their guards (digit check on nav_user_id, composite Slack
  ids never written as nav ids) exactly.
- Adapters may raise; the publisher logs. Do not create fire-and-forget tasks — the publisher already isolates failures.
- Import the wrapped notifier classes lazily inside methods if module import would pull heavy channel SDKs.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Read routes.py:232-331, slack/oauth_callback.py:157-280, msteams/oauth_callback.py:182-300 — *why*: parity (AC-9).
2. Write the adapters (block) — *why*: U5 decoupled completion.
3. Tests with fake notifiers on a dict `app`.

### `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` (CREATE)
```python
"""ChannelNotifier adapters for Jira connection events (FEAT-773 M8)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping

from parrot.auth.oauth2.events import ConnectionEvent

logger = logging.getLogger(__name__)


class _JiraAdapterBase:
    channel: str = ""

    def __init__(self, app: Mapping[str, Any]) -> None:
        self._app = app

    @staticmethod
    def _extra(state_payload: Dict[str, Any]) -> Dict[str, Any]:
        return dict(state_payload.get("extra") or {})

    @staticmethod
    def _site_url(state_payload: Dict[str, Any]) -> str:
        return str((state_payload.get("connection_meta") or {}).get("site_url") or "")


class TelegramJiraNotifierAdapter(_JiraAdapterBase):
    channel = "telegram"

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        # FILL IN: provider != "jira" → return; completed → stamper(channel_user_id, <meta object>) then
        #          app["jira_oauth_notifier"].notify_connected(int(chat_id), event.display_name, site_url);
        #          refresh_failed/revoked → notify_failure(chat_id, "...") when chat_id known — parity with routes.py:296-330
        raise NotImplementedError


class SlackJiraNotifierAdapter(_JiraAdapterBase):
    channel = "slack"

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        # FILL IN: parity with handle_slack_jira_callback (identity write rules + DM)
        raise NotImplementedError


class MSTeamsJiraNotifierAdapter(_JiraAdapterBase):
    channel = "msteams"

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        # FILL IN: parity with handle_msteams_jira_callback (nav_user_id digit guard + proactive notify)
        raise NotImplementedError
```

### FILL IN checklist
- [ ] three `notify` bodies with parity guards; bounded by AC-9
- [ ] tests for each adapter + non-jira no-op

---

## Acceptance Criteria

- [ ] AC-9: each adapter calls the wrapped notifier with the same arguments the old callback used; identity-write guards preserved
- [ ] Non-Jira events are ignored; missing app notifier → logged no-op

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py
@pytest.mark.asyncio
async def test_notifier_adapters_delegate(): ...   # fake app dict with recording notifiers + identity_mapping_service
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

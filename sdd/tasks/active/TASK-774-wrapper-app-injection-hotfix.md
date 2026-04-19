# TASK-774: Wrapper App Injection — FEAT-108 Hotfix

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (2-4h)
**Depends-on**: TASK-763
**Assigned-to**: unassigned

---

## Context

FEAT-108 shipped with a wiring gap: `TelegramAgentWrapper._init_post_auth_providers()`
(at `wrapper.py:329-390`) reads `config.jira_oauth_manager`, `config.db_pool`, and
`config.redis` via `getattr`, but **nothing ever sets them** on the
`TelegramAgentConfig` dataclass. `IntegrationBotManager._start_telegram_bot()`
(`integrations/manager.py:170-213`) builds the wrapper with just
`(agent, bot, config)` and does not thread the aiohttp `Application` through.

Result: any bot that declares `post_auth_actions: [{provider: jira}]` in
`env/integrations_bots.yaml` silently logs
`"post_auth_actions includes 'jira' but config.jira_oauth_manager is not set;
skipping."` and falls back to plain BasicAuth. The same applies to
`/connect_jira` when wired through `_register_jira_commands()` (`wrapper.py:306`).

The MS Teams and WhatsApp wrappers already receive `app` as a constructor argument
(`integrations/manager.py:235-240,254`). This task aligns the Telegram wrapper
with that pattern: the aiohttp `Application` is the natural source of shared
services (`jira_oauth_manager`, `authdb`, `redis`) — not the per-agent config.

---

## Scope

- **Modify `TelegramAgentWrapper.__init__`**:
  - Add `app: Optional[web.Application] = None` parameter (between `config` and
    `agent_commands` for minimal disruption).
  - Store on `self.app`.

- **Modify `_init_post_auth_providers()`**:
  - Resolve `jira_oauth_manager`, `db_pool`, `redis` from `self.app.get(...)`
    instead of `getattr(self.config, …)`.
  - Accept `authdb` OR `database` as the db-pool key (Navigator uses `authdb`
    for the auth schema; some deployments expose `database`).
  - When `self.app is None` but `post_auth_actions` is non-empty, log a warning
    and disable the combined flow (same graceful degradation as today).

- **Modify `_register_jira_commands()`** (`wrapper.py:306-323`):
  - Resolve `oauth_manager` from `self.app.get("jira_oauth_manager")` instead of
    `getattr(self.config, "jira_oauth_manager", None)`.
  - Keep the early-return behavior when the manager is not registered.

- **Modify `IntegrationBotManager._start_telegram_bot()`**:
  - Pass `app=self.bot_manager.get_app()` to the `TelegramAgentWrapper`
    constructor (line 178).

- **Spec cleanup** (`sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`):
  - §6 Codebase Contract: update the "Integration Points" table row for
    `PostAuthRegistry` → services come from `app[...]`, not config.
  - §6 Existing Class Signatures: show the new `app` parameter on
    `TelegramAgentWrapper.__init__`.
  - §7 Implementation Notes / Known Risks: replace the "Vault access without HTTP
    context" bullet — the wrapper now receives the `app` directly, so
    `db_pool`/`redis` are obtained via `self.app.get(...)` without needing a
    request context.
  - Open Question about "how to get db_pool and redis in the Telegram wrapper"
    (§8) is now resolved → mark as closed with the chosen approach.

- **Docstring cleanup** in `wrapper.py`:
  - Line 309: "The Jira OAuth manager is provided via `config.jira_oauth_manager`"
    → "…via `app['jira_oauth_manager']`".
  - Lines 332-337 (`_init_post_auth_providers` docstring): replace references to
    `config.jira_oauth_manager`/`config.db_pool`/`config.redis` with
    `app['jira_oauth_manager']`/`app['authdb']`/`app['redis']`.
  - Any other comments/log messages mentioning `config.jira_oauth_manager`
    (e.g. line 351) updated to say `app['jira_oauth_manager']`.

- **Update tests** (`tests/unit/test_wrapper_combined_auth.py` and any other
  FEAT-108 test file that mocks `config.jira_oauth_manager`):
  - Replace config-attribute mocking with an aiohttp `web.Application` fixture
    that exposes `jira_oauth_manager`, `authdb`, `redis` keys.
  - Pass the fixture as `app=` to the wrapper constructor.

**NOT in scope**:
- Declaring `jira_oauth_manager`/`db_pool`/`redis` as dataclass fields on
  `TelegramAgentConfig` (the whole point is to move them off the config).
- Changing `MSTeamsAgentWrapper` / `WhatsAppAgentWrapper` — they already accept
  `app`.
- Adding new post-auth providers beyond Jira.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Add `app` param to `__init__`; update `_init_post_auth_providers` and `_register_jira_commands` to read from `self.app`; update docstrings/log messages |
| `packages/ai-parrot/src/parrot/integrations/manager.py` | MODIFY | Pass `app=self.bot_manager.get_app()` to `TelegramAgentWrapper` at line 178 |
| `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md` | MODIFY | Update §6 contract, §7 risks, close relevant §8 open question |
| `packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py` | MODIFY | Switch mocks from `config.jira_oauth_manager` to `app.get(...)` |

---

## Codebase Contract (Anti-Hallucination)

### Verified locations
- `TelegramAgentWrapper.__init__` — `wrapper.py:75-140` (constructor to extend)
- `_init_post_auth_providers` — `wrapper.py:329-390`
- `_register_jira_commands` — `wrapper.py:306-323`
- `IntegrationBotManager._start_telegram_bot` — `integrations/manager.py:170-213`
- `BotManager.get_app` — `packages/ai-parrot/src/parrot/manager/manager.py:697-701`
- MS Teams/WhatsApp precedent (wrapper receives `app`) —
  `integrations/manager.py:235-240` and `:254`
- `app['jira_oauth_manager']` publisher — `autonomous/orchestrator.py:272` (set
  by FEAT-107 bootstrap)

### Verified imports
```python
from aiohttp import web                                       # for type hint
# already present in wrapper.py scope:
from parrot.integrations.telegram.post_auth import PostAuthRegistry
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider
from parrot.services.identity_mapping import IdentityMappingService
from parrot.services.vault_token_sync import VaultTokenSync
```

### Does NOT exist (anti-hallucination)
- ~~`TelegramAgentConfig.jira_oauth_manager`~~ — dataclass field was never
  declared; the current `getattr(config, …)` pattern relies on dynamic
  injection that nobody performs.
- ~~`app['db_pool']`~~ — Navigator publishes the auth pool as `app['authdb']`;
  some apps also expose a generic `app['database']`. The wrapper must accept
  both. Confirm actual key in the consuming application before relying on one
  name — verify via `grep -n "app\['authdb'\]\|app\['database'\]"` in the
  deployment repo and document the chosen key in the implementation.

---

## Implementation Notes

### Constructor signature
```python
# parrot/integrations/telegram/wrapper.py
from aiohttp import web

class TelegramAgentWrapper:
    def __init__(
        self,
        agent: 'AbstractBot',
        bot: Bot,
        config: TelegramAgentConfig,
        app: Optional[web.Application] = None,
        agent_commands: list = None,
    ):
        self.agent = agent
        self.bot = bot
        self.config = config
        self.app = app
        ...
```

`app` is `Optional` to avoid breaking existing tests and any ad-hoc callsite.
When `None`, post-auth providers and `/connect_jira` commands are simply not
registered — the bot still works for plain BasicAuth.

### Service resolution
```python
def _init_post_auth_providers(self) -> None:
    actions = getattr(self.config, "post_auth_actions", None) or []
    if not actions:
        return
    if self.app is None:
        self.logger.warning(
            "post_auth_actions configured but aiohttp app not provided; "
            "combined flow disabled."
        )
        return

    jira_oauth   = self.app.get("jira_oauth_manager")
    db_pool      = self.app.get("authdb") or self.app.get("database")
    redis_client = self.app.get("redis")
    # …rest of the existing logic, unchanged
```

### Manager wiring
```python
# parrot/integrations/manager.py:178
wrapper = TelegramAgentWrapper(
    agent,
    bot,
    config,
    app=self.bot_manager.get_app(),
)
```

### Backward compatibility
- Constructors called as `TelegramAgentWrapper(agent, bot, config)` (no `app`)
  keep working; `post_auth_actions` silently degrades with a warning.
- Constructors called as `TelegramAgentWrapper(agent, bot, config, [...])` with
  `agent_commands` as the 4th positional arg **break** (now `app` takes that
  slot). Search the codebase for positional callsites before merging — at the
  time of writing, only `integrations/manager.py:178` instantiates the wrapper;
  tests typically use kwargs. If any positional 4th-arg callsite exists, switch
  it to a keyword argument.

---

## Acceptance Criteria

- [ ] `TelegramAgentWrapper.__init__` accepts `app: Optional[web.Application] = None`.
- [ ] `_init_post_auth_providers` resolves services via `self.app.get(...)` and
      no longer via `getattr(self.config, …)`.
- [ ] `_register_jira_commands` resolves `oauth_manager` from
      `self.app.get("jira_oauth_manager")`.
- [ ] `IntegrationBotManager._start_telegram_bot` passes
      `app=self.bot_manager.get_app()` to the wrapper.
- [ ] With a bot declaring `post_auth_actions: [{provider: jira, required: true}]`
      in `env/integrations_bots.yaml`, startup logs
      `"Registered PostAuthProvider 'jira' (required=True)"` — not the
      "skipping" warning — when `app['jira_oauth_manager']`, `app['authdb']`
      (or `app['database']`), and `app['redis']` are present.
- [ ] When `app` is `None`, `post_auth_actions` logs the graceful-degradation
      warning and the bot still handles plain BasicAuth.
- [ ] Spec §6 / §7 / §8 updated to reflect `app[...]` injection.
- [ ] All `config.jira_oauth_manager` / `config.db_pool` / `config.redis`
      references in `wrapper.py` docstrings and log messages are replaced with
      the `app['...']` equivalents.
- [ ] FEAT-108 tests updated to provide an `app` fixture; all tests pass:
      `pytest packages/ai-parrot/tests/unit/test_wrapper_combined_auth.py
      packages/ai-parrot/tests/unit/test_post_auth*.py -v`
- [ ] No regression in `/connect_jira` standalone flow — verified by existing
      tests for `jira_commands.py`.

---

## Test Specification

```python
# tests/unit/test_wrapper_combined_auth.py — fixture update example

@pytest.fixture
def mock_app(mock_jira_oauth_manager, mock_db_pool, mock_redis):
    """aiohttp Application with the services FEAT-108 expects."""
    from aiohttp import web
    app = web.Application()
    app["jira_oauth_manager"] = mock_jira_oauth_manager
    app["authdb"] = mock_db_pool
    app["redis"] = mock_redis
    return app


def test_wrapper_registers_jira_provider_when_app_wired(
    agent_stub, bot_stub, post_auth_config, mock_app,
):
    wrapper = TelegramAgentWrapper(
        agent_stub, bot_stub, post_auth_config, app=mock_app,
    )
    assert "jira" in wrapper._post_auth_registry


def test_wrapper_skips_jira_provider_when_app_is_none(
    agent_stub, bot_stub, post_auth_config, caplog,
):
    wrapper = TelegramAgentWrapper(
        agent_stub, bot_stub, post_auth_config,  # no app
    )
    assert "jira" not in wrapper._post_auth_registry
    assert "aiohttp app not provided" in caplog.text


def test_wrapper_skips_jira_provider_when_manager_missing(
    agent_stub, bot_stub, post_auth_config, mock_db_pool, mock_redis, caplog,
):
    from aiohttp import web
    app = web.Application()
    app["authdb"] = mock_db_pool
    app["redis"] = mock_redis
    # jira_oauth_manager deliberately absent
    wrapper = TelegramAgentWrapper(
        agent_stub, bot_stub, post_auth_config, app=app,
    )
    assert "jira" not in wrapper._post_auth_registry
    assert "app['jira_oauth_manager'] is not set" in caplog.text
```

---

## Output

When complete, the agent must:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/.index.json` status to `done`
3. Add a brief completion note below

### Completion Note
(Agent fills this in when done)

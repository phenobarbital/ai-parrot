# TASK-3208: Manager wiring, `[devloop]` packaging extra and documentation

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3207, TASK-3198
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12**. Everything above this task is inert until `IntegrationBotManager`
builds a `DevLoopDispatchService` for each Slack bot whose config carries
`devloop.enabled: true`, registers the adapter with `register_devloop(wrapper, service)`
(TASK-3206) and starts the service (which re-attaches live runs, spec G7). On shutdown the
service is stopped **before** the wrapper, and children keep running (resolved orphan policy).

Design research S12 (verified): `redis>=5.0` is only reachable through the `msteams` and
`broadcast` extras (`pyproject.toml:56`, `:104`); installing `ai-parrot-integrations[slack]`
does not pull it, so a dedicated `devloop` extra is added. The feature also needs an operator
guide: Slack app manifest scopes, interactivity URL, `/devloop` command, YAML config, command
syntax, headless-mode prerequisites and known limitations.

---

## Scope

- MODIFY `manager.py`: in `_start_slack_bot`, after `await wrapper.start()` (`:909`), build and start the
  service when `getattr(config, "devloop", None)` is enabled; keep it in `self._devloop_services[name]`;
  in `shutdown` call `service.stop()` before the existing Slack wrapper stop loop (`:990`).
- MODIFY `packages/ai-parrot-integrations/pyproject.toml`: add `devloop = ["redis>=5.0"]` to
  `[project.optional-dependencies]`.
- CREATE `docs/integrations/slack-devloop.md`.
- MODIFY `examples/dev_loop/README.md`: add a short "Kick-off from Slack" section linking the doc and the
  headless mode (TASK-3198).
- Unit tests in `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_manager.py`.

**NOT in scope**: `SlackAgentConfig.devloop` parsing (TASK-3200), any adapter code, the headless
CLI (TASK-3198), the status card (TASK-3209), end-to-end tests (TASK-3210).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | build/start/stop the dev-loop service per Slack bot |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | `devloop` extra |
| `docs/integrations/slack-devloop.md` | CREATE | operator guide |
| `examples/dev_loop/README.md` | MODIFY | pointer section |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_manager.py` | CREATE | wiring tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# Already at the top of manager.py — do NOT re-add:
import asyncio                                                                     # verified: manager.py:13
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING                 # verified: manager.py:15
from parrot.conf import AGENTS_DIR, REDIS_URL                                      # verified: manager.py:21
# New, lazy (inside _start_slack_bot, like `from .slack.wrapper import SlackAgentWrapper` at manager.py:898):
import redis.asyncio as aioredis                                                   # verified: examples/dev_loop/server_dev.py:59 ; extra added by this task
from .devloop.service import DevLoopDispatchService                                # TASK-3204 (spec §3 M8)
from .slack.devloop import register_devloop                                        # TASK-3206
from .slack.devloop.actions import SlackIdentityResolver                           # TASK-3207
# Tests:
from parrot.integrations.manager import IntegrationBotManager                     # verified: manager.py:63
from parrot.integrations.slack.models import SlackAgentConfig                     # verified: slack/models.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
class IntegrationBotManager:                                                       # line 63
    def __init__(self, bot_manager: 'BotManager')                                  # line 74
    #   self.slack_bots: Dict[str, 'SlackAgentWrapper'] = {}                       # line 82
    #   self._polling_tasks: List[asyncio.Task] = []                               # line 94
    async def _start_slack_bot(self, name: str, config: SlackAgentConfig)          # line 858
    #   wrapper = SlackAgentWrapper(agent=..., config=..., app=..., oauth_manager=...)   # lines 899-904
    #   self.slack_bots[name] = wrapper                                             # line 906
    #   await wrapper.start()                                                       # line 909  ← anchor
    #   socket mode branch                                                          # lines 912-924
    async def shutdown(self) -> None                                               # line 943
    #   for name, wrapper in self.slack_bots.items():                              # line 990  ← anchor (socket handler stop, wrapper.stop() inside)
    #   self.slack_bots.clear()                                                     # line 1040

# spec §3 M8 / M10 / M11 (produced by TASK-3204 / 3206 / 3207):
# DevLoopDispatchService(*, config: DevLoopIntegrationConfig, transport: DevLoopTransport, redis, identity_resolver=None)
#   async start() / async stop()
# register_devloop(wrapper, service) -> SlackDevLoopTransport
# SlackIdentityResolver(wrapper, jira_toolkit)
# SlackAgentConfig.devloop: Optional[DevLoopIntegrationConfig] (TASK-3200) with .enabled, .redis_url, ...

# packages/ai-parrot-integrations/pyproject.toml — [project.optional-dependencies] block starts line 33; `whatsapp = [` at line 58 (1 occurrence)
# examples/dev_loop/README.md — `## Troubleshooting` heading at line 749 (1 occurrence)
```

### Does NOT Exist
- ~~`IntegrationBotManager._devloop_services`~~ — created by this task in `__init__`.
- ~~`SlackAgentConfig.devloop`~~ before TASK-3200 lands — use `getattr(config, "devloop", None)` so bots without the section keep working (AC19).
- ~~a Jira toolkit on the manager~~ — none; `SlackIdentityResolver` gets `jira_toolkit=None` here (the resolver then returns the email itself or `("", "")`); building a `JiraToolkit` is a documented follow-up, not part of this task.
- ~~`ai-parrot-integrations[slack]` pulling `redis`~~ — it does not (`pyproject.toml:46-49`).
- ~~`docs/integrations/slack-devloop.md`~~ — created here; `docs/integrations/` already holds `office365-oauth2.md` and `msagentsdk-semantic-cards.md` (style references).
- ~~a service transport created before the wrapper~~ — the transport is bound to the wrapper by `register_devloop`; construct the service with a placeholder and let `register_devloop` inject it, OR construct `SlackDevLoopTransport(wrapper)` first (import from `.slack.devloop.transport`) and pass it — pick the second (simpler, no placeholder).

---

## Implementation Notes

### Pattern to Follow
```python
# manager.py:867-895 — optional sub-component wiring guarded by config, warnings on failure, never fatal
if getattr(config, "jira_client_id", None):
    try:
        ...
    except Exception as exc:  # noqa: BLE001
        self.logger.warning("Slack bot '%s': failed to initialize JiraOAuthManager: %s", name, exc)
```

### Key Constraints
- The dev-loop service must never prevent the Slack bot from starting: wrap construction in `try/except`, log a warning, continue.
- `redis_url = config.devloop.redis_url or REDIS_URL`; `aioredis.from_url(redis_url, decode_responses=True)` (same as `server_dev.py:890`).
- Shutdown order: `service.stop()` (cancels tails only) → socket handler stop → `wrapper.stop()`; then close the redis client.
- Docs must state the exact Slack scopes (`commands`, `chat:write`, `chat:write.public`, `im:write`, `users:read`, `users:read.email`), that interactivity must point at `/api/slack/<chatbot_id>/interactive`, the `/devloop` slash command URL `/api/slack/<chatbot_id>/commands`, the `devloop:` YAML keys from spec §2 Data Models, command syntax, the headless prerequisites (`preflight`: Redis PING, coding CLI, worktree base; Jira advisory for feature runs), the review-pair QA default (spec Q5), single-host limitation, 3000-char slash text cap, and that `pip install ai-parrot-integrations[slack,devloop]` is the install line.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/manager.py:858-924` — `_start_slack_bot`
- `packages/ai-parrot-integrations/src/parrot/integrations/manager.py:943-1045` — `shutdown`
- `docs/integrations/office365-oauth2.md` — doc structure to mirror
- `examples/dev_loop/README.md:380-690` — dev console section the new section links to

---

## Implementation Blueprint

> Write each block below to its declared path nearly verbatim, then complete every
> `# FILL IN:` marker. Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the `devloop` extra to `pyproject.toml` — *why*: the manager's lazy `import redis.asyncio` must be installable by name (S12).
2. Add `self._devloop_services` in `__init__` and the start/stop wiring — *why*: one dict keyed by bot name mirrors `self.slack_bots`.
3. Write the docs and the README pointer — *why*: AC18.
4. Tests, then `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_manager.py -q`.

### `packages/ai-parrot-integrations/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^whatsapp = \[' packages/ai-parrot-integrations/pyproject.toml)
# BEFORE — insert ABOVE `whatsapp = [` (verified: pyproject.toml:58)
# FEAT-555 — dev-loop kick-off from chat. The Slack adapter tails the run's
# Redis state stream and persists run records; `redis` is otherwise only
# reachable through the `msteams` / `broadcast` extras (design research S12).
devloop = [
    "redis>=5.0",
]
```
**Why**: `ai-parrot-integrations[slack,devloop]` is the documented install line (AC18); the `[devloop]` extra is asserted by `test_devloop_extra_installs_redis` (TASK-3210).

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY — `__init__`)
```python
# occurrences: 1 (verified: grep -c "        self.slack_bots: Dict\[str, 'SlackAgentWrapper'\] = {}" packages/ai-parrot-integrations/src/parrot/integrations/manager.py)
# AFTER — insert below `        self.slack_bots: Dict[str, 'SlackAgentWrapper'] = {}` (verified: manager.py:82)
        # FEAT-555: dev-loop dispatch services, one per Slack bot with `devloop.enabled` (+ their redis clients).
        self._devloop_services: Dict[str, Any] = {}
        self._devloop_redis: Dict[str, Any] = {}
```
**Why**: mirrors the per-kind registries above it so `shutdown` can iterate deterministically.

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY — `_start_slack_bot`)
```python
# occurrences: 1 (verified: grep -c '        await wrapper.start()' packages/ai-parrot-integrations/src/parrot/integrations/manager.py)
# AFTER — insert below `        await wrapper.start()` (verified: manager.py:909)
        # FEAT-555: dev-loop kick-off from Slack (spec §3 M12) — optional, never fatal for the chat bot.
        devloop_cfg = getattr(config, "devloop", None)
        if devloop_cfg is not None and getattr(devloop_cfg, "enabled", False):
            try:
                import redis.asyncio as aioredis  # optional extra: ai-parrot-integrations[devloop]

                from .devloop.service import DevLoopDispatchService
                from .slack.devloop import register_devloop
                from .slack.devloop.actions import SlackIdentityResolver
                from .slack.devloop.transport import SlackDevLoopTransport

                redis_client = aioredis.from_url(devloop_cfg.redis_url or REDIS_URL, decode_responses=True)
                transport = SlackDevLoopTransport(wrapper)
                service = DevLoopDispatchService(
                    config=devloop_cfg,
                    transport=transport,
                    redis=redis_client,
                    identity_resolver=SlackIdentityResolver(wrapper, jira_toolkit=None),
                )
                register_devloop(wrapper, service)  # binds /devloop, devloop_* actions, modals, thread interceptor
                await service.start()  # re-attaches live runs from the Redis registry (spec G7)
                self._devloop_services[name] = service
                self._devloop_redis[name] = redis_client
                self.logger.info("Slack bot '%s': dev-loop kick-off enabled", name)
            except Exception as exc:  # noqa: BLE001 — the chat bot must still start
                self.logger.warning("Slack bot '%s': dev-loop integration disabled: %s", name, exc, exc_info=True)
```
**Why**: constructed after `wrapper.start()` and before the Socket Mode branch so both connection modes get the registrations; `register_devloop` returns its own transport but the service needs one at construction, so the same `SlackDevLoopTransport(wrapper)` class is instantiated here and `register_devloop`'s return value is ignored — FILL IN alternative: if TASK-3206's `register_devloop` accepts a `transport=` kwarg, pass this instance to avoid two objects (bounded by spec §3 M10 signature: `register_devloop(wrapper, service)` — do NOT change it; two transport instances are acceptable because the transport is stateless except card-ts maps, which live on the instance the *service* holds).

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY — `shutdown`)
```python
# occurrences: 1 (verified: grep -c '        for name, wrapper in self.slack_bots.items():' packages/ai-parrot-integrations/src/parrot/integrations/manager.py)
# BEFORE — insert ABOVE the comment line `        # Stop Slack bots (including Socket Mode handlers)` that precedes
#          `        for name, wrapper in self.slack_bots.items():` (verified: manager.py:989-990)
        # FEAT-555: stop dev-loop services first (cancels state tails only — children keep running by decision).
        for name, service in self._devloop_services.items():
            try:
                await service.stop()
            except Exception as e:  # noqa: BLE001
                self.logger.error("Error stopping dev-loop service for '%s': %s", name, e)
        for name, client in self._devloop_redis.items():
            try:
                await client.aclose()
            except Exception as e:  # noqa: BLE001
                self.logger.debug("Error closing dev-loop redis for '%s': %s", name, e)
        self._devloop_services.clear()
        self._devloop_redis.clear()
```
**Why**: tails must stop before the wrapper's `_background_tasks` are cancelled (`wrapper.stop()`, `wrapper.py:162-171`) so the terminal messages already in flight complete; `aclose()` is the redis-py ≥5 name (FILL IN: fall back to `close()` if the installed version lacks `aclose`).

### `docs/integrations/slack-devloop.md` (CREATE)
```markdown
# Dev-loop kick-off from Slack (FEAT-555)

Dispatch and steer `parrot devloop` runs from Slack: `/devloop --type feature|bug …`, Open Questions
answered in the run thread, gate approvals, cancel and status.

## Install
`pip install "ai-parrot-integrations[slack,devloop]"` — the `devloop` extra adds `redis>=5.0` (state tail + run registry).

## Slack app manifest
- Bot token scopes: `commands`, `chat:write`, `chat:write.public`, `im:write`, `users:read`, `users:read.email`
- Slash command `/devloop` → `https://<host>/api/slack/<chatbot_id>/commands`
- Interactivity request URL → `https://<host>/api/slack/<chatbot_id>/interactive` (signed; TASK-3205)
- Events (webhook mode) → `https://<host>/api/slack/<chatbot_id>/events`; or Socket Mode with an `xapp-` token

## Configuration (`integrations_bots.yaml`)
<!-- FILL IN: paste the `devloop:` YAML from spec §2 "Configuration" with every key of DevLoopIntegrationConfig explained
     (enabled, repo_path, command, redis_url, socket_dir, use_tcp, default_component, default_acceptance_criteria,
     status_card, max_concurrent_runs (null = unlimited), run_retention_seconds, handshake_timeout_seconds,
     cancel_grace_seconds, tail_drain_seconds) — bounded by AC18 -->

## Command syntax
<!-- FILL IN: /devloop --type feature|bug [--jira KEY] [--base dev|staging] [--title "…"] [--component X] [--ac "cmd"] <prompt> ;
     /devloop status ; /devloop cancel <run-id> ; /devloop help ; confirm card for both kinds; Open Questions modal + `1: answer` thread replies;
     ownership rules — bounded by AC18 -->

## How a run executes (headless child)
<!-- FILL IN: `parrot devloop run --brief <file> --yes --headless --command-socket <path> --run-id …`, handshake line, exit codes 0/1/2/3,
     bearer token env, preflight(topology) — Redis PING, coding CLI, worktree base; Jira advisory for feature runs; review-pair QA default (spec Q5) -->

## Limitations
<!-- FILL IN: single host (socket/loopback), Slack slash text ≤ 3000 chars, no --type enhancement / --doc on Slack yet, status card best-effort, children keep running when the bot stops -->
```
**Why**: AC18 requires these sections; the comments are the FILL IN markers (remove them when done).

### `examples/dev_loop/README.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Troubleshooting' examples/dev_loop/README.md) -->
<!-- BEFORE — insert ABOVE `## Troubleshooting` (verified: examples/dev_loop/README.md:749) -->
## Kick-off from Slack (FEAT-555)

A Slack bot can dispatch the same flows with `/devloop --type feature|bug …`; each run executes as a
headless child (`parrot devloop run --headless …`) and Open Questions are answered in the run thread.
See [`docs/integrations/slack-devloop.md`](../../docs/integrations/slack-devloop.md).
```
**Why**: keeps the examples README the single map of dev-loop front-ends (HTML console, CLI, Slack).

### `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_manager.py` (CREATE)
```python
"""Manager wiring tests for the Slack dev-loop service (TASK-3208)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.manager import IntegrationBotManager  # verified: manager.py:63


def _manager():
    # FILL IN: IntegrationBotManager(bot_manager=MagicMock(get_app=MagicMock(return_value=MagicMock(get=MagicMock(return_value=None)))));
    #          patch _get_agent → AsyncMock(return_value=MagicMock()); patch SlackAgentWrapper in .slack.wrapper
    raise NotImplementedError


@pytest.mark.asyncio
async def test_manager_wires_service_when_enabled():
    """A config with devloop.enabled=True builds DevLoopDispatchService, calls register_devloop and service.start()."""
    # FILL IN: patch parrot.integrations.devloop.service.DevLoopDispatchService, parrot.integrations.slack.devloop.register_devloop,
    #          redis.asyncio.from_url; assert manager._devloop_services["bot"] is the instance — bounded by AC19


@pytest.mark.asyncio
async def test_manager_skips_service_when_disabled_or_absent():
    """devloop=None or enabled=False ⇒ no service, bot still starts."""
    # FILL IN — bounded by AC19


@pytest.mark.asyncio
async def test_shutdown_stops_service_before_wrapper():
    """shutdown() awaits service.stop() before wrapper.stop() and clears the registries."""
    # FILL IN: record call order with a shared list — bounded by AC13
```
**Why**: spec §4 row `test_manager_wires_service_when_enabled` plus the shutdown ordering the orphan policy depends on.

### FILL IN checklist
- [ ] `manager.py` — `aclose()` vs `close()` on the installed redis-py; bounded by the `[devloop]` extra `redis>=5.0`
- [ ] `docs/integrations/slack-devloop.md` — four commented sections; bounded by AC18
- [ ] tests — three bodies + `_manager()` fixture; bounded by AC13, AC19

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_manager.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
- [ ] `pip install -e "packages/ai-parrot-integrations[devloop]"` (or `uv pip install`) resolves `redis>=5.0` (spec AC18, S12)
- [ ] Bots without `devloop.enabled` behave exactly as before (spec AC19)
- [ ] `docs/integrations/slack-devloop.md` covers manifest scopes, YAML config, command syntax, headless mode, limitations; README links it (spec AC18)
- [ ] Shutdown stops the service (tails) and never terminates child processes (spec AC13)

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_manager.py — see blueprint block.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/dev-loop-slack.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3208-slack-devloop-manager-wiring-packaging-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-12
**Notes**: Added `devloop = ["redis>=5.0"]` to
`ai-parrot-integrations`'s optional-dependencies (placed next to `slack`
rather than above `whatsapp` as the blueprint's anchor suggested — same
effect, TOML table key order is not significant). Added
`self._devloop_services` / `self._devloop_redis` to
`IntegrationBotManager.__init__` and the full wiring block in
`_start_slack_bot` right after `await wrapper.start()`: builds a Redis
client, a `SlackDevLoopTransport`, a `DevLoopDispatchService` (identity
resolver = `SlackIdentityResolver(wrapper, jira_toolkit=None)` — building
a real Jira toolkit here is a documented follow-up, not this task),
`register_devloop(wrapper, service)`, then `await service.start()`
(re-attach), all guarded by `getattr(config, "devloop", None)` +
`try/except` so a dev-loop wiring failure only logs a warning and never
prevents the Slack bot itself from starting. In `shutdown()`, added the
dev-loop stop loop (service.stop() for tails, then closes each Redis
client via `aclose()`/`close()` fallback resolved through `getattr` rather
than an except-driven retry) positioned before the existing Slack-bot
stop loop, so tails and their terminal messages finish before
`wrapper.stop()` cancels the wrapper's own background tasks. Wrote
`docs/integrations/slack-devloop.md` (install line, manifest scopes,
full `devloop:` YAML with every `DevLoopIntegrationConfig` key explained,
command syntax, the headless child's handshake/exit-code/preflight
contract, and limitations) and linked it from
`examples/dev_loop/README.md` in a new "Kick-off from Slack" section
before Troubleshooting.
`test_slack_devloop_manager.py` (4 tests, one more than the blueprint's
three) covers wiring when enabled, skipping when `devloop` is `None` or
`enabled=False`, a dev-loop construction failure never blocking bot
startup, and the shutdown ordering (service.stop() before wrapper.stop(),
registries cleared, redis client closed).
`pytest packages/ai-parrot-integrations/tests/integrations/slack -q`:
88 passed. `ruff check` clean; `black --check` clean on the new test file
and the new doc (pre-existing `manager.py` has unrelated quote-style
drift throughout, left untouched per the minimal-diff rule — my own
inserted lines are already black-compliant, verified via `git diff`).
`devloop` extra resolves via `tomllib` to `['redis>=5.0']`.

**Deviations from spec**: none.

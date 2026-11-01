# TASK-5070: Generic connection commands, Jira aliases, and wrapper command registration

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5065, TASK-5069
**Assigned-to**: unassigned

---

## Context

Spec §2 "Commands (M3)" (last paragraph), §2 "Server (M7)" (registration no longer gated on Jira), §3 Module 3,
AC-4. Registers `/connect [<provider>]`, `/disconnect <provider>`, `/connections [<provider>]` on
`MSTeamsCommandRouter`, reading arguments via `command_args` (TASK-5065) so typed text and card `Action.Submit`
behave identically. `jira_commands.py` shrinks to aliases onto `TeamsConnector`; `register_jira_commands` keeps
its public name with the new signature `(router, connector)`.

Because that signature changes, the wrapper's call site (wrapper.py:202-221) changes **in this task** — splitting
it would leave the wrapper calling the old signature. The wrapper builds a `TeamsConnector` and registers the
commands when `OAuth2ProviderRegistry().all()` is nonempty, regardless of `oauth_manager`. The connector's service
comes from a new `connection_service_factory` constructor parameter; until TASK-5073 passes a real one, the default
factory builds `IntegrationsService()` **without** an evaluator, so every context call is denied (fail closed).

Kept until TASK-5072: the `app["msteams_jira_oauth_notifier"] = MSTeamsOAuthNotifier(...)` assignment (FEAT-773's
`MSTeamsJiraNotifierAdapter` still reads it).

---

## Scope

- `connect_commands.py`: `register_connection_commands(router, *, connector)` — `connect`, `disconnect`,
  `connections` (also serves plain `connections`), then `register_jira_commands(router, connector)`.
  `/connect` → `pick_provider`; `/connect <p>` → `connect(tc, p.lower())`; `/disconnect` → usage reply;
  `/disconnect <p>` → `disconnect`; `/connections [<p>]` → `status(tc, p or None)`.
- `jira_commands.py`: aliases `connect_jira` / `disconnect_jira` / `jira_status` → provider `"jira"`; plain `jira`
  and `integrations` → `status(tc)`. Delete `connect_jira_handler`, `disconnect_jira_handler`,
  `jira_status_handler`, `jira_menu_handler` and helpers only they used; keep `_MSTEAMS_CHANNEL`.
- `wrapper.py`:
  - constructor gains `connection_service_factory: Optional[Callable[[], Any]] = None` (after `oauth_manager`);
  - replace `register_jira_commands(...)` inside `if oauth_manager is not None:` — keep only the notifier
    assignment there;
  - after the auth-lane block, build `self._principal_source = MSTeamsPrincipalSource(self._session_store)` and
    `self._connector = TeamsConnector(...)`; register via `register_connection_commands` when
    `OAuth2ProviderRegistry().all()` is nonempty, else `self._connector = None`;
  - plain dispatch tuple `("jira", "integrations")` → `("jira", "integrations", "connections")`.
- Migrate tests: `test_msteams_jira_commands.py` (`test_jira_aliases_map_to_generic`), the
  `register_jira_commands` cases in `test_msteams_wrapper_jira.py`, the Teams half of
  `test_slack_msteams_jira_principal.py` (Slack half untouched). New `test_msteams_connection_routing.py`.

**NOT in scope**: permission context at agent call sites (TASK-5071), removing `MSTeamsOAuthNotifier` and notifier
attach (TASK-5072), manager wiring (TASK-5073).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/connect_commands.py` | MODIFY | append `register_connection_commands` |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py` | MODIFY | shrink to aliases |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | connector construction + registration |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py` | MODIFY | alias tests |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py` | MODIFY | registration tests |
| `packages/ai-parrot-integrations/tests/test_slack_msteams_jira_principal.py` | MODIFY | Teams half → connector |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_routing.py` | CREATE | routing tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.msteams.commands import MSTeamsCommandRouter, command_args   # :30; command_args (TASK-5065)
from parrot.integrations.msteams.commands.connect_commands import TeamsConnector, register_connection_commands  # TASK-5069 / here
from parrot.integrations.msteams.connections import MSTeamsPrincipalSource           # TASK-5066
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry                       # registry.py (all :117)
from parrot.auth.oauth2.service import IntegrationsService                           # service.py:65 (import lazily in the default factory)
```

### Existing Signatures to Use
```python
# msteams/commands/jira_commands.py
_MSTEAMS_CHANNEL = "msteams"                                                     # :42 (imported by test_msteams_jira_commands.py:387)
async def connect_jira_handler(...) :251; disconnect_jira_handler :310; jira_status_handler :340; jira_menu_handler :379
def register_jira_commands(router, oauth_manager, nav_user_id_resolver=None) -> None   # :399

# msteams/wrapper.py
from .commands.jira_commands import register_jira_commands                       # :47
    def __init__(self, agent, config, app, forms_directory=None, voice_config=None,
                 oauth_manager: Optional["JiraOAuthManager"] = None,):            # :132-140 (`oauth_manager` line :139)
        if oauth_manager is not None:                                            # :202 — register_jira_commands :203-209; notifier :214-221
        self._session_store = MSTeamsSessionStore(...)                           # :225
        self._auth: Optional[MSTeamsAuthStrategy] = None ... register_auth_commands  # :230-245
                if plain in ("jira", "integrations"):                            # :720
#   config.client_id = bot app id (used for MSTeamsOAuthNotifier at :215)
```

### Does NOT Exist
- ~~`register_connection_commands`~~ — created here.
- ~~`app["integrations_service"]` / an app evaluator key~~ — do not invent; the factory is a constructor parameter.
- ~~Slack/Telegram changes~~ — separate modules; untouched.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/connect_commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/test_slack_msteams_jira_principal.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_routing.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py#register_jira_commands",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py#MSTeamsCommandRouter",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Append `register_connection_commands`. 2. Rewrite `register_jira_commands`; delete the manager handlers.
3. Wrapper: param, Jira-block reduction, connector after the auth lane, plain tuple. 4. `grep -rn
"connect_jira_handler\|jira_status_handler\|disconnect_jira_handler\|jira_menu_handler" packages/ai-parrot-integrations`
→ only Slack/Telegram hits. 5. Migrate tests.

### `.../commands/connect_commands.py` (MODIFY — append at end of file)
```python
def register_connection_commands(router: "MSTeamsCommandRouter", *, connector: TeamsConnector) -> None:
    """Register /connect, /disconnect, /connections (+ plain 'connections') and the Jira aliases."""
    from parrot.integrations.msteams.commands import command_args
    from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

    def _first_arg(turn_context: TurnContext) -> str:
        parts = command_args(turn_context).split()
        return parts[0].lower() if parts else ""

    async def _connect(turn_context: TurnContext) -> None:
        provider_id = _first_arg(turn_context)
        if provider_id:
            await connector.connect(turn_context, provider_id)
        else:
            await connector.pick_provider(turn_context)

    async def _disconnect(turn_context: TurnContext) -> None:
        # FILL IN: no arg → "Usage: `/disconnect <provider>`"; else connector.disconnect — bounded by AC-4
        ...

    async def _connections(turn_context: TurnContext) -> None:
        await connector.status(turn_context, _first_arg(turn_context) or None)

    router.register("connect", _connect)
    router.register("disconnect", _disconnect)
    router.register("connections", _connections)
    register_jira_commands(router, connector)
    logger.info("Registered Teams connection commands")
```

### `.../commands/jira_commands.py` (MODIFY)
```python
# REPLACE from `def register_jira_commands(` (verified: jira_commands.py:399, occurrences: 1) to end of file
def register_jira_commands(router: "MSTeamsCommandRouter", connector: "TeamsConnector") -> None:
    """Register the legacy Jira commands as aliases of the generic connection commands."""

    async def _connect(turn_context: "TurnContext") -> None:
        await connector.connect(turn_context, "jira")

    async def _disconnect(turn_context: "TurnContext") -> None:
        await connector.disconnect(turn_context, "jira")

    async def _status(turn_context: "TurnContext") -> None:
        await connector.status(turn_context, "jira")

    async def _menu(turn_context: "TurnContext") -> None:
        await connector.status(turn_context)

    for name, handler in (("connect_jira", _connect), ("disconnect_jira", _disconnect), ("jira_status", _status),
                          ("jira", _menu), ("integrations", _menu)):
        router.register(name, handler)
    logger.info("Registered Jira alias commands on MSTeamsCommandRouter")
```

### `.../msteams/wrapper.py` (MODIFY)
```python
# 1. AFTER `        oauth_manager: Optional["JiraOAuthManager"] = None,` (verified: wrapper.py:139, occurrences: 1)
        connection_service_factory: Optional[Callable[[], Any]] = None,

# 2. In the block opened by `        if oauth_manager is not None:` (verified: wrapper.py:202, occurrences: 1):
#    delete the `register_jira_commands(...)` call (:203-209) and its comment; keep the notifier lines (:210-221).

# 3. BEFORE `        # FEAT-734: TeamsFormDesignerMixin seams (no-op for agents without the mixin)`
#    (FILL IN: verify occurrences == 1 with grep -cxF before relying on it)
        self._principal_source = MSTeamsPrincipalSource(self._session_store)
        self._connector: Optional[TeamsConnector] = None
        if OAuth2ProviderRegistry().all():
            self._connector = TeamsConnector(
                principal_source=self._principal_source,
                service_factory=connection_service_factory or _default_connection_service,
                provider_ids=lambda: [p.provider_id for p in OAuth2ProviderRegistry().all()],
                bot_app_id=config.client_id or "",
                auth_enabled=self._auth is not None,
            )
            register_connection_commands(self._command_router, connector=self._connector)

# 4. REPLACE `                if plain in ("jira", "integrations"):` (verified: wrapper.py:720, occurrences: 1)
                if plain in ("jira", "integrations", "connections"):
```
Module level: replace `from .commands.jira_commands import register_jira_commands` (:47) with
`from .commands.connect_commands import TeamsConnector, register_connection_commands`; add
`from .connections import MSTeamsPrincipalSource`, `from parrot.auth.oauth2.registry import OAuth2ProviderRegistry`,
`Callable` to the typing import, and:
```python
def _default_connection_service() -> Any:
    """Service without an evaluator: every channel call is denied until the manager injects one (TASK-5073)."""
    from parrot.auth.oauth2.service import IntegrationsService

    return IntegrationsService()
```
**Why**: the connector needs `self._session_store` (created at :225), so registration moves below the auth lane.

### `.../tests/integrations/msteams/test_msteams_connection_routing.py` (CREATE)
```python
"""FEAT-775 M3: generic command routing (AC-4)."""
# FILL IN: fake connector (AsyncMock methods) + real MSTeamsCommandRouter + register_connection_commands.
# test_connect_with_and_without_provider — "/connect Jira" → connect(tc, "jira"); "/connect" → pick_provider
# test_card_submit_equals_typed — same text through try_dispatch from the card path → same call
# test_disconnect_requires_provider — "/disconnect" → usage reply, no connector call
# test_connections_plain_and_slash — "/connections", try_dispatch_plain("connections"), "/connections jira"
# test_wrapper_registers_without_oauth_manager — registry nonempty + oauth_manager=None → commands registered
# test_wrapper_skips_when_registry_empty — no providers → no "connect" handler
```

### FILL IN checklist
- [ ] `_disconnect` body; FEAT-734 anchor count check
- [ ] dead-helper cleanup in `jira_commands.py`
- [ ] six routing tests; alias test; migrated wrapper / principal test call sites

---

## Acceptance Criteria

- [ ] Generic commands and the five Jira aliases route to the connector; typed = card (AC-4).
- [ ] Registration happens without `oauth_manager` when providers exist (spec M7 "not gated on jira_client_id").
- [ ] Without an injected factory, connector service calls are denied (no evaluator).
- [ ] No Teams import of the removed handlers remains; `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_routing.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_jira_commands.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_slack_msteams_jira_principal.py -q`

---

## Test Specification

Listed in the test-file block and Scope.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


# TASK-5073: Integration manager wiring — evaluator-backed services, Teams notifier registration, adapter removal

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5063, TASK-5072
**Assigned-to**: unassigned

---

## Context

Spec §2 "Service authorization bridge" (last paragraph), "Notifier (M4)", "Server (M7)", §3 Module 7, AC-6, AC-14.
`IntegrationManager._start_msteams_bot` gates Teams connections on `config.jira_client_id` (manager.py:420) and
`_register_channel_notifiers` installs FEAT-773's `MSTeamsJiraNotifierAdapter` (manager.py:141). This task:
1. builds Teams services with the shared PDP evaluator (`pdp_permission_evaluator(app["abac"])`, TASK-5063) and a
   vault reader, passed to the wrapper as `connection_service_factory` (TASK-5070);
2. registers the single `app["msteams_connection_notifier"]` (TASK-5072) in `ChannelNotifierRegistry` for
   `channel="msteams"` regardless of whether Jira was set up before or after the Teams bot;
3. deletes `MSTeamsJiraNotifierAdapter` and its import/registration, keeping Slack/Telegram adapters.

There is no pre-existing server service factory and no app evaluator key — do not invent one (spec M7).

**Cross-feature warning**: FEAT-776 TASK-5023 and FEAT-777 TASK-5042 also edit `_register_channel_notifiers` and
`core/auth/notifiers.py` (Telegram/Slack adapters). Before starting, `git fetch origin` and rebase onto
`origin/dev`; edit only the Teams lines; if those functions were restructured, re-anchor and record it.

---

## Scope

- `_start_msteams_bot`: keep the existing JiraOAuthManager setup (provider registration side effect), stop using it
  as a registration gate, and pass `connection_service_factory=_channel_service_factory(app)` to the wrapper.
- `_channel_service_factory(app) -> Callable[[], IntegrationsService]`: evaluator =
  `pdp_permission_evaluator(app["abac"])` when `app.get("abac")` is set, else `None` (→ every context call denied);
  `vault_token_sync = VaultTokenSync(db_pool=app["authdb"], redis=app.get("redis"))` when `authdb` exists.
- `_register_channel_notifiers`: replace `registry.register(MSTeamsJiraNotifierAdapter(app))` with registration of
  `get_or_create_connection_notifier(app, ref_store)`; also call that registration from `_start_msteams_bot`
  (registry `register` replaces by channel, so repeated calls are idempotent).
- `core/auth/notifiers.py`: delete `MSTeamsJiraNotifierAdapter`.
- Tests: `packages/ai-parrot-server/tests/test_teams_connections_wiring.py`; migrate `test_jira_notifier_adapters.py`
  (drop Teams assertions, keep Slack/Telegram).

**NOT in scope**: the identity alias (TASK-5074), Slack (line 984 `jira_client_id` gate belongs to Slack).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | factory, Teams start, notifier registration |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | MODIFY | delete `MSTeamsJiraNotifierAdapter` |
| `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py` | MODIFY | drop Teams cases |
| `packages/ai-parrot-server/tests/test_teams_connections_wiring.py` | CREATE | wiring + end-to-end tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher, setup_connection_fanout  # manager.py:22
from parrot.auth.oauth2.service import IntegrationsService, pdp_permission_evaluator   # service.py:65; adapter from TASK-5063
from parrot.services.vault_token_sync import VaultTokenSync                            # verified pattern: service.py:178 (lazy, optional)
from parrot.integrations.msteams.connections import (                                  # TASK-5067 / TASK-5072
    MSTeamsConversationRefStore, get_or_create_connection_notifier,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
from parrot.integrations.core.auth.notifiers import (
    MSTeamsJiraNotifierAdapter,                                                  # :32
    SlackJiraNotifierAdapter, TelegramJiraNotifierAdapter,
)
def _register_channel_notifiers(app: Any) -> ChannelNotifierRegistry:           # :134
    registry = ChannelNotifierRegistry()
    if app.get("connection_channel_notifiers_registered"): return registry
    registry.register(TelegramJiraNotifierAdapter(app)); registry.register(SlackJiraNotifierAdapter(app))
    registry.register(MSTeamsJiraNotifierAdapter(app))                           # :141
    app["connection_channel_notifiers_registered"] = True
async def _start_msteams_bot(self, name, config)                                 # :411
    app = self.bot_manager.get_app(); _build_principal_resolver(app)
    if getattr(config, "jira_client_id", None): ... JiraOAuthManager(... event_publisher=_connection_publisher(app))   # :420 (occurrences of this line: 2 — :420 Teams, :984 Slack)
    wrapper = MSTeamsAgentWrapper(agent=..., config=..., app=..., forms_directory=..., oauth_manager=jira_oauth_manager)  # :449-456
#     `            oauth_manager=jira_oauth_manager,` occurs at :456 (Teams) and :1015 (Slack) — edit :456 only

# packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py
class MSTeamsJiraNotifierAdapter(_JiraAdapterBase):                             # :139
# ChannelNotifierRegistry.register(notifier) replaces by notifier.channel        # events.py:57-59
```

### Does NOT Exist
- ~~a server-side Integrations service factory~~ / ~~`app["permission_evaluator"]`~~ — none; build it here.
- ~~`app["abac"].is_allowed` for channel calls~~ — use `pdp_permission_evaluator`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/test_teams_connections_wiring.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#_register_channel_notifiers",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#IntegrationManager._start_msteams_bot",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py#MSTeamsJiraNotifierAdapter",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ChannelNotifierRegistry"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Cross-feature rebase check. 2. Module helpers. 3. `_register_channel_notifiers` Teams line. 4. `_start_msteams_bot`.
5. Delete the adapter class + import. 6. Tests.

### `.../integrations/manager.py` (MODIFY) — module helpers, BEFORE `def _register_channel_notifiers(app: Any) -> ChannelNotifierRegistry:` (verified: :134, occurrences: 1)
```python
def _channel_service_factory(app: Any) -> Callable[[], Any]:
    """Build IntegrationsService instances for channel callers with the shared PDP evaluator.

    Without ``app["abac"]`` the evaluator is ``None`` and every context-authorized call is denied (fail closed).
    """
    from parrot.auth.oauth2.service import IntegrationsService, pdp_permission_evaluator

    pdp = app.get("abac")
    evaluator = pdp_permission_evaluator(pdp) if pdp is not None else None

    def _factory() -> Any:
        # FILL IN: vault = VaultTokenSync(db_pool=app["authdb"], redis=app.get("redis")) when app.get("authdb") and the
        # optional import succeeds (pattern service.py:175-185), else None; return IntegrationsService(vault, permission_evaluator=evaluator)
        ...

    return _factory


def _register_teams_notifier(app: Any) -> None:
    """Register the app's single Teams connection notifier for channel "msteams" (idempotent)."""
    from parrot.integrations.msteams.connections import MSTeamsConversationRefStore, get_or_create_connection_notifier

    redis = app.get("redis")
    ref_store = MSTeamsConversationRefStore(redis) if redis is not None else None
    ChannelNotifierRegistry().register(get_or_create_connection_notifier(app, ref_store))
```
Import `Callable` from typing if absent.

### Same file — edits
```python
# REPLACE `    registry.register(MSTeamsJiraNotifierAdapter(app))` (verified: :141, occurrences: 1)
    _register_teams_notifier(app)
# DELETE `    MSTeamsJiraNotifierAdapter,` (verified: :32, occurrences: 1)
# _start_msteams_bot (:411): after `_build_principal_resolver(app)` add `_register_teams_notifier(app)`;
# REPLACE the Teams `            oauth_manager=jira_oauth_manager,` (:456 — NOT :1015) with:
            oauth_manager=jira_oauth_manager,
            connection_service_factory=_channel_service_factory(app),
```
**Why**: the Teams notifier must be registered even when no Jira manager (and thus no `_connection_publisher`) is
built, and Jira-first ordering must not reinstall the removed adapter.

### `.../core/auth/notifiers.py` (MODIFY)
```python
# DELETE `class MSTeamsJiraNotifierAdapter(_JiraAdapterBase):` (verified: notifiers.py:139, occurrences: 1) and its whole body
#   up to the next top-level definition or EOF. Remove it from `__all__` if listed. Do not touch the Slack/Telegram adapters.
```

### `packages/ai-parrot-server/tests/test_teams_connections_wiring.py` (CREATE)
```python
"""FEAT-775 M7: Teams connection wiring (AC-6, AC-14)."""
# FILL IN fixtures: fresh ChannelNotifierRegistry (ChannelNotifierRegistry._reset()), a dict-like app with/without "abac".
# test_registry_holds_teams_notifier_only — get("msteams") is MSTeamsConnectionNotifier, never MSTeamsJiraNotifierAdapter
# test_registration_order_jira_before_and_after_teams — both orders → same notifier instance registered
# test_factory_injects_evaluator_or_denies — with abac → service has an evaluator; without → context calls denied
# test_teams_connect_end_to_end — /connect jira → card URL from start_connect → simulate FEAT-773 callback publish
#   (ConnectionEventPublisher.publish with the stored state) → issuing bot's adapter receives "connected" text
# test_teams_tool_needs_auth_card — covered in TASK-5075; leave out here
```

### FILL IN checklist
- [ ] factory body
- [ ] adapter-class deletion boundaries
- [ ] four tests; Teams cases removed from `test_jira_notifier_adapters.py`

---

## Acceptance Criteria

- [ ] `MSTeamsConnectionNotifier` is the only notifier for `channel="msteams"`, in either startup order (AC-6).
- [ ] `MSTeamsJiraNotifierAdapter` no longer exists in `packages/`; Slack/Telegram adapters unchanged.
- [ ] Teams services carry the PDP evaluator; without a PDP they deny (AC-14).
- [ ] Teams command registration no longer depends on `jira_client_id`. `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-server/tests/test_teams_connections_wiring.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py -q`
- `pytest packages/ai-parrot/tests/unit/auth/test_connection_events.py -q`

---

## Test Specification

Four tests listed in the test-file block.

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


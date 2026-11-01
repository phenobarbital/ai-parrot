# TASK-5072: Attach bots to `MSTeamsConnectionNotifier`; remove `MSTeamsOAuthNotifier` and the legacy Teams callback

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5071
**Assigned-to**: unassigned

---

## Context

Spec §2 "Notifier (M4)", §3 Module 4, Integration Points ("replaces"), AC-6, AC-7. Every `MSTeamsAgentWrapper`
today overwrites the app-global `app["msteams_jira_oauth_notifier"]` (wrapper.py:214-221), so with two Teams bots
the last one wins. Replace it with one app-scoped `MSTeamsConnectionNotifier` at
`app["msteams_connection_notifier"]` to which each wrapper `attach`es `(config.client_id, self.adapter)`. Remove
`MSTeamsOAuthNotifier` and the retained, unrouted `handle_msteams_jira_callback` (the active generic FEAT-773
callback is preserved — it lives in core, not in this file). `oauth_callback.py` contains only those two symbols
(+ an inner helper) and is imported only by the wrapper, so the file is deleted.

**Ordering with TASK-5073**: FEAT-773's `MSTeamsJiraNotifierAdapter` reads `app["msteams_jira_oauth_notifier"]`;
after this task that key is gone, so Teams proactive messages flow only once TASK-5073 registers the new notifier
in `ChannelNotifierRegistry`. Both land in the same feature branch before merge.

---

## Scope

- `connections.py`: `get_or_create_connection_notifier(app, ref_store) -> MSTeamsConnectionNotifier` — returns
  `app["msteams_connection_notifier"]`, creating it once (with the given ref store) when absent.
- `wrapper.py`: delete the `if oauth_manager is not None:` notifier block; after the connector/ref-store setup,
  `if config.client_id: get_or_create_connection_notifier(app, self._convref_store).attach(config.client_id, self.adapter)`
  else a warning (no proactive messages); remove `from .oauth_callback import MSTeamsOAuthNotifier`.
- `git rm` `msteams/oauth_callback.py`.
- Tests: delete `test_msteams_oauth_callback.py`, moving surviving notifier assertions (send text via
  `continue_conversation`, failure logged not raised) into `test_msteams_connection_notifier.py`; remove the
  `TestJiraCallbackRegression` legacy-helper cases from `test_msteams_auth_lane.py` (the helper no longer exists;
  the identity write it covered is not on the active route — spec §1 gap 3); update `test_msteams_wrapper_jira.py`
  notifier assertions to the new key + `attach`.

**NOT in scope**: `ChannelNotifierRegistry` registration and `MSTeamsJiraNotifierAdapter` removal (TASK-5073).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` | MODIFY | `get_or_create_connection_notifier` |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` | MODIFY | attach; drop old notifier |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py` | MODIFY | delete the file (`git rm`) |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_oauth_callback.py` | MODIFY | delete; assertions moved |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_notifier.py` | MODIFY | moved assertions |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py` | MODIFY | drop legacy-helper cases |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py` | MODIFY | notifier assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.msteams.connections import MSTeamsConnectionNotifier   # TASK-5067
```

### Existing Signatures to Use
```python
# msteams/wrapper.py
from .oauth_callback import MSTeamsOAuthNotifier                                  # :52 (only importer in src)
        if oauth_manager is not None:                                             # :202 (after TASK-5070: notifier lines only)
            if config.client_id:                                                  # :214
                app["msteams_jira_oauth_notifier"] = MSTeamsOAuthNotifier(        # :215
        self.adapter = Adapter(config=self.config, ...)                           # :185
# msteams/oauth_callback.py (327 lines): class MSTeamsOAuthNotifier :89; async def handle_msteams_jira_callback :182
# MSTeamsConnectionNotifier.attach(app_id, adapter) (TASK-5067); self._convref_store (TASK-5071)
# tests/integrations/msteams/test_msteams_auth_lane.py: class TestJiraCallbackRegression (:373-440) imports the helper
```

### Does NOT Exist (after this task)
- ~~`MSTeamsOAuthNotifier`~~, ~~`handle_msteams_jira_callback`~~, ~~`app["msteams_jira_oauth_notifier"]` writes~~ in `packages/` (AC-6)
  — `core/auth/notifiers.py` still *reads* the key until TASK-5073 removes the adapter.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_oauth_callback.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_notifier.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py#MSTeamsOAuthNotifier",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py#handle_msteams_jira_callback",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py#MSTeamsAgentWrapper"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the helper to `connections.py`. 2. Wrapper edits. 3. `git rm` the module and its test. 4. Move assertions;
trim `test_msteams_auth_lane.py`. 5. `grep -rn "MSTeamsOAuthNotifier\|handle_msteams_jira_callback" packages/` → only
`core/auth/notifiers.py`'s key read may remain (removed by TASK-5073).

### `.../msteams/connections.py` (MODIFY — append at end of file)
```python
CONNECTION_NOTIFIER_KEY = "msteams_connection_notifier"


def get_or_create_connection_notifier(app: Any, ref_store: Optional[MSTeamsConversationRefStore]) -> MSTeamsConnectionNotifier:
    """Return the app's single Teams notifier, creating it on first use (one per aiohttp app)."""
    notifier = app.get(CONNECTION_NOTIFIER_KEY)
    if notifier is None:
        notifier = MSTeamsConnectionNotifier(ref_store)
        app[CONNECTION_NOTIFIER_KEY] = notifier
    # FILL IN: when an existing notifier has no ref store and ref_store is given, adopt it — bounded by spec §2
    #   (refresh/revoke delivery needs the store regardless of which bot started first)
    return notifier
```

### `.../msteams/wrapper.py` (MODIFY)
```python
# DELETE the whole `        if oauth_manager is not None:` block (verified: wrapper.py:202, occurrences: 1) — after
#   TASK-5070 it only holds the MSTeamsOAuthNotifier assignment (`if config.client_id:` :214 / :215) and its else-warning.
# DELETE `from .oauth_callback import MSTeamsOAuthNotifier` (verified: wrapper.py:52, occurrences: 1).
# AFTER the TASK-5071 ref-store construction (`self._convref_store = ...`):
        if config.client_id:
            get_or_create_connection_notifier(app, self._convref_store).attach(config.client_id, self.adapter)
        else:
            self.logger.warning("No client_id configured — Teams connection notifications are disabled for this bot")
```
Import `get_or_create_connection_notifier` from `.connections`. `oauth_manager` stays an accepted (unused) constructor
parameter until TASK-5073 stops passing it — remove it there if nothing else reads it.

### FILL IN checklist
- [ ] ref-store adoption rule in the helper
- [ ] assertion migration list recorded in the Completion Note (which old tests moved, which were dropped and why)

---

## Acceptance Criteria

- [ ] Each wrapper attaches its own adapter under its app id; one notifier per app (AC-6).
- [ ] `MSTeamsOAuthNotifier` / `handle_msteams_jira_callback` gone from `packages/` (AC-6).
- [ ] Surviving notifier assertions pass in `test_msteams_connection_notifier.py` (AC-7).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_notifier.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_wrapper_jira.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py -q`

---

## Test Specification

Moved notifier assertions + `test_wrapper_attaches_each_bot` (two wrappers, one notifier, two adapters) in
`test_msteams_wrapper_jira.py`.

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

Implemented by gpt-5.6-terra (codex), 1 attempt; fidelity gate and lint clean; own validation 20 passed; msteams+auth suites green except pre-existing test_o365_refresh (2, also red on origin/dev). 0 review corrections.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


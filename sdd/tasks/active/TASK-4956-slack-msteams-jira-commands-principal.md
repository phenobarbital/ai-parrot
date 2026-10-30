# TASK-4956: Slack and MS Teams Jira commands resolve the principal

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4954
**Assigned-to**: unassigned

---

## Context

G8 / AC-9 parity. The Slack and MS Teams Jira commands call `validate_token(channel, <raw id>)`,
`revoke(channel, <raw id>)` and `create_authorization_url(channel, <raw id>)`. With principal keys they must resolve
the principal first (`resolve_principal(channel, raw_id)`); an unresolved user gets a "link your account first"
reply. Not listed in the spec's M8 path, but required for AC-9 ("Slack and Teams … behave as before") — record
this in the Completion Note.

---

## Scope

- `slack/commands/jira_commands.py` and `msteams/commands/jira_commands.py`: resolve the principal at each of the
  connect/status/disconnect call sites; pass `principal=` to `create_authorization_url`; keep reply texts; unresolved →
  link-first reply.
- Tests for both modules.

**NOT in scope**: Teams Adaptive-Card connect action (S-3b); Slack first-link owner fix (S-3a).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py` | MODIFY | principal resolution |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py` | MODIFY | principal resolution |
| `packages/ai-parrot-integrations/tests/test_slack_msteams_jira_principal.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.principal import resolve_principal     # TASK-4937
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py
    existing = await oauth_manager.validate_token(_SLACK_CHANNEL, user_id)          # :81
    url, _nonce = await oauth_manager.create_authorization_url(                       # :91
    await oauth_manager.revoke(_SLACK_CHANNEL, user_id)                               # :122
    token = await oauth_manager.validate_token(_SLACK_CHANNEL, user_id)               # :151
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py
    existing = await oauth_manager.validate_token(_MSTEAMS_CHANNEL, user_id)        # :243
    url, _nonce = await oauth_manager.create_authorization_url(                       # :268
    await oauth_manager.revoke(_MSTEAMS_CHANNEL, user_id)                             # :289
    token = await oauth_manager.validate_token(_MSTEAMS_CHANNEL, user_id)             # :309
```

### Does NOT Exist
- ~~a Slack/Teams session nav_user_id lookup~~ — not available here; use `resolve_principal` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/test_slack_msteams_jira_principal.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Slack's channel user id may be the composite `team:user` — pass it unchanged to `resolve_principal` (the resolver decides).
- Keep the `extra_state` each command builds today (team_id/slack_user_id/conversation_reference) — the notifier adapters need it.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Add a small `_principal(user_id)` helper per module and use it at the 4 call sites each — *why*: AC-9.
2. Tests with a fake manager + fake resolver.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py` (MODIFY)
```python
# AFTER the module imports add:
_LINK_FIRST = "Link your Slack account to the platform first, then try again."

async def _principal(user_id: str) -> Optional["Principal"]:
    from parrot.auth.principal import resolve_principal
    return await resolve_principal(_SLACK_CHANNEL, user_id)
# FILL IN at :81/:91/:122/:151 — principal None → reply _LINK_FIRST and return; else use principal.user_id for
#          validate_token/revoke and create_authorization_url(_SLACK_CHANNEL, user_id, extra_state=…, principal=principal)
```
### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py` (MODIFY)
```python
# Same pattern with _MSTEAMS_CHANNEL at :243/:268/:289/:309.
```

### FILL IN checklist
- [ ] slack helper + four call sites
- [ ] msteams helper + four call sites
- [ ] tests

---

## Acceptance Criteria

- [ ] AC-9: bound Slack/Teams users connect, see status and disconnect against the principal key; unbound users get the link-first reply and no OAuth state

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_slack_msteams_jira_principal.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/test_slack_msteams_jira_principal.py
@pytest.mark.asyncio
async def test_slack_connect_unbound_user_gets_link_first(): ...
@pytest.mark.asyncio
async def test_msteams_status_uses_principal_key(): ...
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

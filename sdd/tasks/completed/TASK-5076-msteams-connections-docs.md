# TASK-5076: Docs — `docs/integrations/msteams-connections.md`

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5073, TASK-5074, TASK-5075
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, AC-11, §7 "Live-session requirement". Operators and users need one page describing the Teams
connection model after FEAT-775. Write it from the merged behavior (read the implemented modules, not only the spec).

---

## Scope

Sections (all required):
1. **Overview** — principal-keyed connections on Teams; relation to FEAT-773 (S-1) and FEAT-729 `/login`.
2. **Commands** — `/connect [<provider>]`, `/disconnect <provider>`, `/connections [<provider>]`, card buttons,
   aliases `/connect_jira`, `/disconnect_jira`, `/jira_status`, `jira`, `integrations`, `connections`.
3. **Prerequisites** — `/login` (live FEAT-729 session with AAD oid; stricter than before — even an existing identity
   row is not enough); `navigator_auth_url` must be configured or users get the operator message.
4. **Personal-only rule** — why group/channel conversations get a "message me directly" hint.
5. **Automatic Connect cards** — needs-auth from a tool → response, then card; device-code flow; scope upgrades.
6. **Notifications & multi-bot routing** — one `MSTeamsConnectionNotifier` per app; completed / revoked /
   refresh_failed messages; routing by bot app id; 30-day conversation-reference store.
7. **Permissions** — request-less PBAC via the URI-parity mapping table (copy it from spec §2) and what an operator
   must allow in policies for `/api/v1/connections*`.
8. **Operator checklist** — registered OAuth redirect URIs, `navigator_auth_url`, `client_id` per bot, PBAC policies,
   Redis available.
9. **Migration note** — `/connect_jira` users: existing grants keep working while `OAUTH2_LEGACY_KEYS_UNTIL` is open;
   after that, reconnect with `/connect jira`.

**NOT in scope**: code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/integrations/msteams-connections.md` | CREATE | user + operator guide |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None (documentation). Every command, key and message quoted in the doc must be copied from the merged code
(`msteams/commands/connect_commands.py`, `msteams/connections.py`, `auth/oauth2/service.py`).

### Existing Signatures to Use
- `OAUTH2_LEGACY_KEYS_UNTIL` — `parrot/auth/oauth2_base.py:79` (`_legacy_window_open`).
- Routes `/api/v1/connections`, `/api/v1/connections/{provider}`, `/api/v1/connections/{provider}/start` —
  `parrot/manager/manager.py:2488-2490`.

### Does NOT Exist
- ~~Teams SSO for third-party providers~~, ~~group-chat connect~~, ~~auto-retry after connect~~ — out of scope (spec §1); say so.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/integrations/msteams-connections.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the merged modules listed above. 2. Write the nine sections. 3. Run the doc check below.

### `docs/integrations/msteams-connections.md` (CREATE)
```markdown
# Connections on Microsoft Teams

<!-- FILL IN: the nine sections from Scope, in order; every quoted string copied from code — bounded by AC-11 -->
```

### FILL IN checklist
- [ ] nine sections
- [ ] mapping table copied from spec §2

---

## Acceptance Criteria

- [ ] The doc exists and covers commands, the `/login` prerequisite, the personal-only rule and multi-bot routing (AC-11).

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_agent_commands.py -q`

---

## Test Specification

Documentation task; the validation command is a smoke run of the existing Teams command tests.

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

Implemented by gpt-5.6-luna (codex), 1 attempt; docs/integrations/msteams-connections.md; validation test_agent_commands 29 passed. 0 review corrections.

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


# TASK-5043: Slack OAuth callback — team-qualified identity through the exclusive claim

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5036
**Assigned-to**: unassigned

---

## Context

Spec Module 2 ("slack/oauth_callback.py (modifies; :251) provider_user_id=f"{team_id}:{slack_user_id}"; use
the exclusive claim operation, never raw upsert") and AC-5/AC-6 ("Slack `provider_user_id` is
`"{team_id}:{slack_user_id}"` everywhere"; "Every Slack writer atomically enforces exclusive ownership").

`handle_slack_jira_callback` still writes `auth.user_identities` with the **bare** `slack_user_id`
(`oauth_callback.py:248-258`) through raw `upsert_identity`. Verified while writing this task:
it has **no caller in `packages/*/src`** after S-1 (completion now flows through the publisher) — only
`packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py` calls it. It is still a
public helper, so it must not remain a non-exclusive Slack writer. Integrations reach the server's
`IdentityMappingService` only through `request.app["identity_mapping_service"]` (duck-typed; integrations never
import server code) — keep that.

---

## Scope

- In `handle_slack_jira_callback`, replace the `identity_service.upsert_identity(...)` call with
  `identity_service.claim_channel_identity(...)` (method added by TASK-5036), using
  `provider_user_id=f"{team_id}:{slack_user_id}"` and the same non-secret `auth_data`.
- Skip the write (warning, as today) when `team_id`, `slack_user_id` or a numeric `nav_user_id` is missing.
- An ownership conflict is logged without owner details and never changes the browser response (the HTML page
  and DM still follow, as today).
- Update `test_slack_oauth_callback.py` assertions from `upsert_identity` to `claim_channel_identity` with the
  team-qualified id; add a conflict test.

**NOT in scope**: deleting the helper (a separate decision; it is public API); `SlackJiraNotifierAdapter`
(TASK-5042 deletes it); link confirm route (TASK-5041); resolver lookup (TASK-5037); `upsert_identity` itself (TASK-5036
routes its Slack branch through the claim).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` | MODIFY | team-qualified id via `claim_channel_identity` |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py` | MODIFY | assertions + conflict test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports. The identity service is duck-typed from request.app (oauth_callback.py:238).
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py
async def handle_slack_jira_callback(request: "web.Request", token_set: Optional["JiraTokenSet"],
                                     state_payload: Dict[str, Any]) -> "web.Response":      # :157
    extra = state_payload.get("extra") or {}                                                # :190
    def _field(name, default="") -> str: return extra.get(name) or state_payload.get(name, default)   # :192-193
    team_id = _field("team_id"); slack_user_id = _field("slack_user_id")                   # :226-227
    nav_user_id = str(_field("nav_user_id") or "")                                          # :235
    identity_service = request.app.get("identity_mapping_service")                          # :238
    if identity_service is not None and slack_user_id and not nav_user_id: logger.warning(...)   # :239-245
    elif identity_service is not None and slack_user_id:
        try:
            await identity_service.upsert_identity(                                          # :248 (anchor, 1 occurrence)
                nav_user_id=nav_user_id, auth_provider="slack",
                provider_user_id=slack_user_id,                                              # :251 (anchor, 1 occurrence)
                auth_data={"team_id": team_id, "slack_user_id": slack_user_id},
                display_name=token_set.display_name or None, email=token_set.email or None)  # :252-258
        except Exception: logger.exception(...)                                              # :259-264

# packages/ai-parrot-server/src/parrot/services/identity_mapping.py (after TASK-5036)
async def claim_channel_identity(self, *, nav_user_id: str, auth_provider: str, provider_user_id: str,
                                 auth_data: Dict[str, Any], display_name: Optional[str] = None,
                                 email: Optional[str] = None) -> ClaimResult
class ClaimResult(BaseModel): status: Literal["claimed", "already_owned", "conflict"]   # never carries the other owner
# Defined by TASK-5036 (identity_mapping.py). Re-read the merged method before coding; it raises ValueError on a
# non-numeric nav_user_id like upsert_identity does.
```

### Does NOT Exist
- ~~`claim_channel_identity` before TASK-5036 merges~~ — do not start until TASK-5036 is done.
- ~~An import of `parrot.services.identity_mapping` from integrations~~ — forbidden; use `request.app.get("identity_mapping_service")`.
- ~~An owner id on `ClaimResult`~~ — it only has `status`; there is nothing to log about the other owner.
- ~~Secrets in `auth_data`~~ — `team_id`/`slack_user_id` only.
- ~~A `src` caller of `handle_slack_jira_callback`~~ — none (grep `packages/*/src`); tests only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py#handle_slack_jira_callback"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The identity write must stay non-fatal for the browser flow (existing behaviour, :259-264).
- Never log the other owner's id on conflict (spec: "409 on ownership conflict, without owner details").
- Keep the module docstring accurate: change item 1 to "claiming a team-qualified `auth.user_identities` row
  through `IdentityMappingService.claim_channel_identity`".

---

## Implementation Blueprint

### Steps (in order)
1. Re-read TASK-5036's merged `claim_channel_identity` / `ClaimResult` — *why*: the callback branches on `status`.
2. Replace the `upsert_identity` block — *why*: exclusive ownership + team-qualified key (AC-5/AC-6).
3. Update the tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            await identity_service.upsert_identity(' oauth_callback.py)
# REPLACE the call at oauth_callback.py:248-258 (anchor `            await identity_service.upsert_identity(`
# through the closing `)` after `email=token_set.email or None,`) with:
            if not team_id or not nav_user_id.isdigit():
                logger.warning("Skipping Slack identity claim: missing team_id or numeric nav_user_id")
            else:
                outcome = await identity_service.claim_channel_identity(
                    nav_user_id=nav_user_id,
                    auth_provider="slack",
                    provider_user_id=f"{team_id}:{slack_user_id}",
                    auth_data={"team_id": team_id, "slack_user_id": slack_user_id},
                    display_name=token_set.display_name or None,
                    email=token_set.email or None,
                )
                if outcome.status == "conflict":
                    logger.warning(
                        "Slack identity %s:%s is owned by another account; not linked", team_id, slack_user_id
                    )
```
**Why**: the claim is the only allowed Slack writer; the key must be team-qualified everywhere.

### `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py` (MODIFY)
```python
# FILL IN: change every `upsert_identity` assertion to `claim_channel_identity` with
# provider_user_id="<team>:<user>" (claim returns ClaimResult(status="claimed")); add
# test_claim_conflict_keeps_success_page (claim reports conflict → 200 HTML success, DM still scheduled)
# and test_bare_slack_user_id_never_written — bounded by AC-5/AC-6
```

### FILL IN checklist
- [ ] Conflict branch verified against TASK-5036's merged `ClaimResult`.
- [ ] Test file updated + two new tests.

---

## Acceptance Criteria

- [ ] `grep -n "upsert_identity" packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` returns no call (docstring mentions excepted).
- [ ] The callback claims `provider_user_id="{team_id}:{slack_user_id}"` (AC-6).
- [ ] Conflicts never break the browser response and never log owner details.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py -q`

---

## Test Specification

See the test-file block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (Module 2, "Exclusive ownership contract")
3. **Check dependencies** — TASK-5036 must be `"done"`
4. **Verify the Codebase Contract**, especially TASK-5036's merged method
5. **Update status** → `"in-progress"`; commit only the index
6. **Implement** from the blueprint
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit** only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-5043 connections-web-slack verified`
10. **Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol/luna + native sonnet
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any

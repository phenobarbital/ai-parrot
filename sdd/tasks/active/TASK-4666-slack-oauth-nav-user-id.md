# TASK-4666: Stop the Slack Jira callback writing a composite id into auth.user_identities.user_id

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (<2h)
**Depends-on**: TASK-4664
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:a671f989e8e7`

---

## Context

Follow-up on the known-and-open item TASK-4664 left in its Completion Note:
*"Slack fallback nav_user_id 'team:user' is not a bigint and now fails
(logged)"*, filed as `issue:a671f989e8e7`.

`handle_slack_jira_callback`
(`packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py`)
computed

```python
nav_user_id = state_payload.get("user_id") or f"{team_id}:{slack_user_id}"
```

and handed it to `IdentityMappingService.upsert_identity`.
`auth.user_identities.user_id` is `bigint` with an FK to `auth.users`, and
TASK-4664's `$1::text::bigint` cast makes a non-numeric id fail loudly
server-side instead of being silently coerced. Verified against the live
table on 2026-10-23:

```
InvalidTextRepresentationError: invalid input syntax for type bigint: "T0001:U1234"
```

Both branches of that expression are wrong, not only the fallback:
`connect_jira_handler`
(`packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/jira_commands.py:79`)
passes `f"{team_id}:{slack_user_id}"` as the `JiraOAuthManager` *token-vault
key*, so `state_payload["user_id"]` is **always** that composite string for
the Slack lane — never a Navigator user id. So the Slack identity row could
never be written at all.

Resolution chosen (the second option the ledger issue offers): there is no
Slack→Navigator resolver today — `SlackIdentityResolver`
(`slack/devloop/actions.py:236`) maps a Slack email to a **Jira accountId**,
not to an `auth.users` row — so the callback skips the identity write
explicitly, and only writes when the state carries a real Navigator id under
the `nav_user_id` key that `JiraPostAuthProvider` already established for
Telegram (`telegram/post_auth_jira.py:118`). The column is not relaxed.

## Scope

- Read `nav_user_id` for the Slack identity write from the `nav_user_id` key
  of the OAuth state (`extra` first, then top level, via the existing
  `_field` helper), never from `state_payload["user_id"]`.
- Skip the `upsert_identity` call with an explicit `logger.warning` when no
  Navigator id is present, leaving the browser flow and the DM untouched.
- Cover both paths in `test_slack_oauth_callback.py`, including the
  state-payload shape-parity test.

**NOT in scope**: changing `auth.user_identities`; changing the Slack
token-vault key (`connect_jira_handler` keeps `team_id:slack_user_id`);
building a Slack→Navigator user resolver or a Slack auth lane; the MS Teams
and Telegram call sites (already correct); the `?error=` branch.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py` | Modify — `nav_user_id` resolution + explicit skip |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py` | Modify — new fixture + 2 new tests + parity assertions |

## Codebase Contract (Anti-Hallucination)

**Verified Imports / Existing Signatures** (checked 2026-10-23 in this worktree):

- `handle_slack_jira_callback(request, token_set, state_payload) -> web.Response`
  — `slack/oauth_callback.py:156`.
- The local helper `_field(name, default="") -> str` returning
  `extra.get(name) or state_payload.get(name, default)` —
  `slack/oauth_callback.py:189`.
- `IdentityMappingService.upsert_identity(*, nav_user_id, auth_provider,
  provider_user_id, auth_data, display_name=None, email=None, token=None)`
  — `packages/ai-parrot-server/src/parrot/services/identity_mapping.py:170`.
- `_UPSERT_SQL` casts `$1::text::bigint` —
  `services/identity_mapping.py:44`.
- `connect_jira_handler` builds `user_id = f"{team_id}:{slack_user_id}"` and
  passes it as the second positional of `create_authorization_url` —
  `slack/commands/jira_commands.py:79,91`.
- `JiraPostAuthProvider` stashes `extra_state["nav_user_id"]` —
  `telegram/post_auth_jira.py:118`.
- The MS Teams sibling already skips on a missing id:
  `nav_user_id = state_payload.get("user_id") or extra.get("user_id", "")`
  guarded by `if identity_service is not None and nav_user_id:` —
  `msteams/oauth_callback.py:246,251`.

**Does NOT exist**: any Slack→Navigator (`auth.users`) resolver; a
`nav_user_id` field on any Slack session object; a Slack auth lane.

## Acceptance Criteria

1. `upsert_identity` is called with the state's `nav_user_id` when one is
   present, and `":" not in nav_user_id`.
2. `upsert_identity` is NOT called when the state carries no `nav_user_id`,
   even though `state_payload["user_id"]` holds `"T0001:U1234"`.
3. The skip path logs a warning and still returns the 200 success page; the
   DM notification is unaffected.
4. The shape-parity test drives the real `JiraOAuthManager` payload and
   asserts the Navigator id survives the `extra` nesting.
5. `ruff check` clean on both files.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src:packages/ai-parrot-server/src \
  python -m pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_oauth_callback.py -q
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src:packages/ai-parrot-server/src \
  python -m pytest packages/ai-parrot-integrations/tests/integrations/slack/ -q
```

## Test Specification

- `test_writes_identity_when_service_available` — now driven by the
  `slack_state_payload_with_nav_user` fixture; asserts `nav_user_id="4210"`.
- `test_skips_identity_write_without_nav_user_id` — new; asserts
  `upsert_identity.assert_not_called()` and a 200 success page.
- `test_never_passes_composite_vault_key_as_nav_user_id` — new; asserts the
  value handed over carries no `":"` and is all digits.
- `TestStatePayloadShapeParity::test_manager_payload_drives_identity_and_dm`
  — extended: `nav_user_id` in `extra_state`, asserted through the real
  nonce round-trip alongside the untouched composite `user_id`.

## Completion Note

_(filled on close)_

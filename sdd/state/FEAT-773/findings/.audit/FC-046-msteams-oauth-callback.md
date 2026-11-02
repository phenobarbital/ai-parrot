---
id: FC-046
query_id: Q055-F1
type: read
intent: "Follow-up: read msteams/oauth_callback.py — Teams callback branch + proactive notification."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-036
depth: 1
---

# FC-046 — MS Teams already has a Jira OAuth callback branch with proactive Bot Framework notification (adapter.continue_conversation on a stored ConversationReference) and identity write guarded by numeric nav_user_id

## Summary

327 lines (FEAT-225). `MSTeamsOAuthNotifier(adapter, app_id)` with `notify_connected(conversation_ref_dict, display_name, site_url)` / `notify_failure` deserialising `ConversationReference` and calling `adapter.continue_conversation(ref, callback, app_id)`. `handle_msteams_jira_callback(request, token_set, state_payload)` (:182-327): writes `auth.user_identities` only when `nav_user_id` is numeric (AAD GUID is the provider account id, never user_id), returns HTML success/error, fires proactive notification (fire-and-forget). Notifier registered as `app["msteams_jira_oauth_notifier"]` by `MSTeamsAgentWrapper` (TASK-1473). `conversation_reference` is serialised into `extra_state` during `/connect_jira`.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: 1-22
  symbol: `module docstring`
  excerpt: |
    Teams uses the Bot Framework proactive messaging pattern: adapter.continue_conversation(ref, callback, app_id). The conversation_reference was serialized to JSON and stored in extra_state during /connect_jira
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: 89-143
  symbol: `MSTeamsOAuthNotifier`
  excerpt: |
    class MSTeamsOAuthNotifier:
        def __init__(self, adapter: BotFrameworkAdapter, app_id: str)
        async def notify_connected(self, conversation_ref_dict, display_name, site_url)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: 182-305
  symbol: `handle_msteams_jira_callback`
  excerpt: |
    async def handle_msteams_jira_callback(request, token_set, state_payload) -> web.Response
        # 2. Fire-and-forget proactive notification

## Notes

Brainstorm S-3b 'Teams ConnectionChannel + proactive message' — the proactive-message mechanism and the aadObjectId→nav_user_id handling already exist for Jira (Bot Framework `botbuilder`, not `TeamsHumanChannel`). Slack has the analogous `slack/oauth_callback.py` (DM via Web API).

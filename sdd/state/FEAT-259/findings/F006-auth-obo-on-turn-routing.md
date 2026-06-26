---
id: F006
query: "Verify on_turn activity routing and invoke handling"
type: read
path: packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py
lines: 52-108
---

## Finding

`on_turn()` routes by activity type:
- `message` → `_handle_message()` ✓
- `conversationUpdate` → `_handle_conversation_update()` ✓
- ALL OTHER types (including `invoke`) → logged as DEBUG and IGNORED

This confirms that `signin/verifyState` and `signin/tokenExchange` invoke
activities cannot be handled. The sign-in round-trip cannot complete.

Identity extraction uses `activity.from_property.id` (channel id) only.
No `aad_object_id` extraction from the Activity or claims.

`_handle_message()` calls `self.parrot_agent.ask(question, session_id, user_id)`
with no token/credential injection — no RequestContext, no _pctx_var, no
trace_context. Tools have no path to receive user credentials.

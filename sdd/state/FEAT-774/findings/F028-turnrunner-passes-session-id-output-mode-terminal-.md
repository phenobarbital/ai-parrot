---
id: F028
query_id: Q042
type: read
intent: "CLI TurnRunner identity kwargs"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-028]
---

# F028 — TurnRunner passes session_id, output_mode=TERMINAL, permission_context, user_id (if set) to bot.ask/ask_stream

## Summary

`TurnRunner._identity_kwargs()` is the single place CLI identity enters the bot: `session_id`, `output_mode=OutputMode.TERMINAL`, `permission_context=config.permission_context`, plus `user_id` when not None. `load_history` uses `config.user_id or "cli-user"`. No persistence of identity/tokens; `save_session_pointer` stores only the last session id per agent.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/session.py`
  lines: 105-114, 202-205, 236-237, 283-287
  symbol: `TurnRunner._identity_kwargs / run_turn / load_history`
  excerpt: |
    kwargs = {"session_id": self.config.session_id, "output_mode": OutputMode.TERMINAL,
              "permission_context": self.config.permission_context}
    if self.config.user_id is not None: kwargs["user_id"] = self.config.user_id
    stream = self.bot.ask_stream(question=query, **self._identity_kwargs())
    history = await self.bot.get_conversation_history(self.config.user_id or "cli-user", session_id)

## Notes

S-4 can inject a Navigator-keyed `PermissionContext` here without touching the REPL/TUI presenters.

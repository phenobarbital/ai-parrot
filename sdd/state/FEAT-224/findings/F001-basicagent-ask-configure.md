---
id: F001
query_id: Q001
type: grep
intent: Confirm BasicAgent.ask()/configure() exist and the REQUEST/CONFIGURE entrypoints.
executed_at: 2026-06-05T13:08:40Z
duration_ms: 220
parent_id: null
depth: 0
---

# F001 — `BasicAgent`, `ask()`, `configure()`, `conversation()` all exist

## Summary

`BasicAgent` is real: `bots/agent.py:37` — `class BasicAgent(Chatbot, NotificationMixin)`.
The base `AbstractBot` defines both `ask()` (abstract.py:3660) and the REQUEST
workhorse `conversation()` (abstract.py:3107), plus `configure()`
(abstract.py:1231) used as the CONFIGURE-phase setup across all concrete bots
(chatbot, voice, document, data, database). `basic.py` itself only defines
`BasicBot(BaseBot)` — the agent base used by the brainstorm is `BasicAgent` from
`bots/agent.py`, not `bots/basic.py`.

## Citations

- path: `parrot/bots/agent.py`
  lines: 37
  symbol: `BasicAgent`
  excerpt: |
    class BasicAgent(Chatbot, NotificationMixin):

- path: `parrot/bots/abstract.py`
  lines: 1231, 3107, 3660, 3715
  symbol: `configure`, `conversation`, `ask`, `ask_stream`
  excerpt: |
    async def configure(self, app=None) -> None: ...
    async def conversation(self, ...): ...
    async def ask(self, ...): ...

## Notes

Concrete agents override `configure(self, app=None)` and call
`await super().configure(...)` — the cooperative pattern the mixin would use.
Cross-ref F006 (existing mixin overrides `conversation`, not `ask`).

---
id: F035
query_id: FC-013-f1
type: grep
intent: "Depth-2: ServerAgentProxy bearer token"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: FC-013
depth: 1
merged_from: [FC-035]
---

# F035 — ServerAgentProxy sends Authorization: Bearer <token>; user_id never sent in server mode (Q8)

## Summary

`parrot.cli.loaders.ServerAgentProxy(server_url, token=None)` sends `Authorization: Bearer <token>` on every request (loaders.py:482-506); `_ServerBotProxy.ask/ask_stream` take `user_id` but document it as unused — 'identity comes only from the bearer token (Q8); never send user_id' (249-311). This is the CLI's only existing server-authenticated identity path: a navigator-auth bearer token the user supplies by hand via `--token` / `PARROT_SERVER_TOKEN`.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/loaders.py`
  lines: 466-506
  symbol: `ServerAgentProxy.__init__ / headers`
  excerpt: |
    class ServerAgentProxy:
        def __init__(self, server_url, ..., token: Optional[str] = None):
            self._token = token
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else None
- path: `packages/ai-parrot/src/parrot/cli/loaders.py`
  lines: 249-280
  symbol: `_ServerBotProxy.ask`
  excerpt: |
    async def ask(self, question, ..., user_id: Optional[str] = None, ...):
        # Q8: identity comes from the bearer token only -- never send user_id.

## Notes

How the token is obtained is out of band today (no `parrot login`). S-4's CLI principal resolver could introspect this token server-side (same path as principal_guard) to get the Navigator user_id.

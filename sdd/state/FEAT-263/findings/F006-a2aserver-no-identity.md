# F006 — A2AServer.process_message has NO identity / NO suspend hook (GAP)

**Query**: Q007 (read `ai-parrot-server/.../a2a/server.py`)
**Verdict**: GAP CONFIRMED — this is the core new wiring.

- `A2AServer` (server.py:31) wraps an agent; `setup()` mounts `/.well-known/agent.json`, `/a2a/message/send`, `/a2a/message/stream`, `/a2a/tasks/*`, `/a2a/rpc`.
- `process_message(message)` (l.245): creates Task → `_ask_agent` → `agent.ask(question, session_id=context_id)`. **No user identity is extracted from the request; no credential check; no suspend path.**
- `_handle_jsonrpc` (l.691) handles `message/send`, `tasks/get`, `tasks/list` only — no `input-required` / resume handling.
- `_handle_send_message` runs the task to completion synchronously and returns `task.to_dict()`.

**Implication**: The A2A→credential bridge is genuinely NEW: (1) derive per-user identity at `process_message` (OQ#1 gate), (2) on missing credential, suspend (F004) + return a TEXT artifact with the consent link from `CredentialResolver.get_auth_url` (F001), (3) resume after OAuth callback (F003) by nonce. None of this exists in the A2A surface today.

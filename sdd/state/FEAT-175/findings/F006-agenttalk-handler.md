---
id: F006
query: "AgentTalk POST handler"
type: read
file: packages/ai-parrot/src/parrot/handlers/agent.py
lines: 1245-1627
---

POST handler uses `async with agent.retrieval(self.request, app=app, user_id=user_id,
session_id=user_session) as bot:` (line 1504).

Inside: calls bot.ask() or bot.ask_stream() depending on `stream` flag.
Complex setup before retrieval: PBAC, session tools, memory, DatasetManager.
Complex teardown in finally: restore original tools, managers, ContextVars.

Migration target: replace retrieval() with session() at line 1504.
PBAC enforcement must still happen — either inside session() or separately.

---
id: F002
query: "RequestContext class definition"
type: read
file: packages/ai-parrot/src/parrot/utils/helpers.py
lines: 5-41
---

Simple container class with fields: request (web.Request), app, llm, user_id,
session_id, **kwargs. Async context manager with no-op __aenter__/__aexit__.

No cleanup logic, no lifecycle hooks — purely a data holder.

---
id: F010
query: "Tool RequestContext access"
type: read
file: packages/ai-parrot/src/parrot/tools/abstract.py
lines: 375-421
---

Tools receive _permission_context (PermissionContext), NOT RequestContext.
No tool currently has access to the web request, user_id, or session_id
via RequestContext.

ContextVar would unlock current_context() for tools — per the user's stated
goal of giving tools current_context().user_id "from thin air."

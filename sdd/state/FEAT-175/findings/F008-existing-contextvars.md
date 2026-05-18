---
id: F008
query: "Existing ContextVar usage in codebase"
type: grep
pattern: "ContextVar"
---

Four existing ContextVar usages, all following the same pattern:

1. handlers/web_hitl.py:29 — current_web_session (WebSocket channel ID)
2. clients/nvidia.py:31 — _thinking_ctx (per-task thinking context)
3. integrations/telegram/context.py:14 — current_telegram_chat_id
4. tools/dataset_manager/tool.py:41 — _pctx_var (PermissionContext)

All use module-level ContextVar + accessor functions. The proposed _current_ctx
follows this established pattern exactly.

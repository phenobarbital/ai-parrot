---
type: Concept
title: hotswap_to_full_toolkit()
id: func:parrot.tools.jira_connect_tool.hotswap_to_full_toolkit
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Replace :class:`JiraConnectTool` in-place with the full toolkit.
---

# hotswap_to_full_toolkit

```python
async def hotswap_to_full_toolkit(tool_manager: 'ToolManager', build_full_toolkit: Callable[[], Awaitable[Any]], *, bot: Any=None) -> List[Any]
```

Replace :class:`JiraConnectTool` in-place with the full toolkit.

Called after the OAuth callback persists the user's tokens.  Safe to
call multiple times — if the placeholder is already gone, the
registered toolkit is still returned.

Args:
    tool_manager: The session's :class:`ToolManager`.
    build_full_toolkit: Async factory returning a fresh toolkit.
    bot: Optional bot/agent instance.  If it exposes
        ``_sync_tools_to_llm``, it is invoked to update the live LLM
        tool list; otherwise the swap takes effect on the next turn.

Returns:
    The list of AbstractTool instances registered from the toolkit.

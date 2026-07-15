---
type: Wiki Summary
title: parrot.tools.jira_connect_tool
id: mod:parrot.tools.jira_connect_tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Placeholder tool and session helpers for Jira OAuth 2.0 (3LO) in AgenTalk.
relates_to:
- concept: class:parrot.tools.jira_connect_tool.JiraConnectTool
  rel: defines
- concept: func:parrot.tools.jira_connect_tool.hotswap_to_full_toolkit
  rel: defines
- concept: func:parrot.tools.jira_connect_tool.setup_jira_oauth_session
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.tools.jira_connect_tool`

Placeholder tool and session helpers for Jira OAuth 2.0 (3LO) in AgenTalk.

When a user opens an AgenTalk session without prior Jira tokens, we cannot
register the full :class:`JiraToolkit` (it has no credentials to operate
with).  Instead we register a lightweight :class:`JiraConnectTool` that,
when invoked by the LLM, returns the OAuth authorization URL so the user
can connect their account.

Once tokens land in Redis (via the OAuth callback), the placeholder is
hot-swapped for the full toolkit using :func:`hotswap_to_full_toolkit`,
keeping the conversation alive.

## Classes

- **`JiraConnectTool(AbstractTool)`** — Placeholder tool returning the Jira OAuth authorization URL.

## Functions

- `async def setup_jira_oauth_session(tool_manager: 'ToolManager', credential_resolver: 'CredentialResolver', channel: str, user_id: str, *, build_full_toolkit: Optional[Callable[[], Awaitable[Any]]]=None) -> None` — Register either :class:`JiraConnectTool` or the full Jira toolkit.
- `async def hotswap_to_full_toolkit(tool_manager: 'ToolManager', build_full_toolkit: Callable[[], Awaitable[Any]], *, bot: Any=None) -> List[Any]` — Replace :class:`JiraConnectTool` in-place with the full toolkit.

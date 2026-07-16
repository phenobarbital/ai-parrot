---
type: Concept
title: setup_jira_oauth_session()
id: func:parrot.tools.jira_connect_tool.setup_jira_oauth_session
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register either :class:`JiraConnectTool` or the full Jira toolkit.
---

# setup_jira_oauth_session

```python
async def setup_jira_oauth_session(tool_manager: 'ToolManager', credential_resolver: 'CredentialResolver', channel: str, user_id: str, *, build_full_toolkit: Optional[Callable[[], Awaitable[Any]]]=None) -> None
```

Register either :class:`JiraConnectTool` or the full Jira toolkit.

On session start, check whether tokens exist via the resolver.  If yes,
invoke ``build_full_toolkit`` (typically a factory that instantiates
``JiraToolkit(auth_type='oauth2_3lo', credential_resolver=resolver)``)
and register the resulting toolkit.  If no, register the placeholder
:class:`JiraConnectTool`.

Args:
    tool_manager: The session's :class:`ToolManager`.
    credential_resolver: Resolver used to check the token store and
        generate auth URLs.
    channel: Originating channel (e.g., ``"agentalk"``).
    user_id: User identifier scoped to the channel.
    build_full_toolkit: Optional async factory building the full
        :class:`JiraToolkit` — call sites that only need the
        placeholder (e.g., early in the bootstrap) can omit it.

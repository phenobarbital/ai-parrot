---
type: Wiki Entity
title: O365Tool
id: class:parrot_tools.o365.base.O365Tool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for Office365 tools that interact with Microsoft Graph API.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# O365Tool

Defined in [`parrot_tools.o365.base`](../summaries/mod:parrot_tools.o365.base.md).

```python
class O365Tool(AbstractTool)
```

Base class for Office365 tools that interact with Microsoft Graph API.

This class provides:
- Integration with O365Client
- Multiple authentication modes
- Error handling and logging
- Async execution support

Subclasses should implement:
- _execute_graph_operation(): Perform the actual Graph API operation

Authentication Modes:
1. DIRECT: Uses client credentials (app-only access)
   - Best for: Admin operations, bulk operations
   - Requires: client_id, client_secret, tenant_id

2. ON_BEHALF_OF: Uses OBO flow with user assertion
   - Best for: Acting on behalf of authenticated user
   - Requires: client_id, client_secret, tenant_id, user_assertion

3. DELEGATED: Interactive user login
   - Best for: User-specific operations with full permissions
   - Requires: Interactive browser login

4. CACHED: Reuse cached interactive session
   - Best for: Subsequent operations after interactive login
   - Requires: Previous interactive_login() call

## Methods

- `async def cleanup(self)` — Clean up resources.

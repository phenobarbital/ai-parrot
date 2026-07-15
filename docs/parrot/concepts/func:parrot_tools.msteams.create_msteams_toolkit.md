---
type: Concept
title: create_msteams_toolkit()
id: func:parrot_tools.msteams.create_msteams_toolkit
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create and return a configured MSTeamsToolkit instance.
---

# create_msteams_toolkit

```python
def create_msteams_toolkit(tenant_id: Optional[str]=None, client_id: Optional[str]=None, client_secret: Optional[str]=None, as_user: bool=False, username: Optional[str]=None, password: Optional[str]=None, **kwargs) -> MSTeamsToolkit
```

Create and return a configured MSTeamsToolkit instance.

Args:
    tenant_id: Azure AD tenant ID
    client_id: Azure AD application client ID
    client_secret: Azure AD application client secret
    as_user: If True, use delegated user permissions
    username: Username for delegated auth
    password: Password for delegated auth
    **kwargs: Additional toolkit arguments

Returns:
    Configured MSTeamsToolkit instance

---
type: Concept
title: create_sharepoint_toolkit()
id: func:parrot_tools.o365.bundle.create_sharepoint_toolkit
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory function to create a SharePoint toolkit.
---

# create_sharepoint_toolkit

```python
def create_sharepoint_toolkit(client_id: str, client_secret: str, tenant_id: str, **kwargs) -> SharePointToolkit
```

Factory function to create a SharePoint toolkit.

Args:
    client_id: Azure AD application client ID
    client_secret: Azure AD application client secret
    tenant_id: Azure AD tenant ID
    **kwargs: Additional toolkit arguments

Returns:
    Configured SharePointToolkit instance

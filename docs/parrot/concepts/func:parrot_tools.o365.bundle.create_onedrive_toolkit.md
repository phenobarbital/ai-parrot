---
type: Concept
title: create_onedrive_toolkit()
id: func:parrot_tools.o365.bundle.create_onedrive_toolkit
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory function to create a OneDrive toolkit.
---

# create_onedrive_toolkit

```python
def create_onedrive_toolkit(client_id: str, client_secret: str, tenant_id: str, **kwargs) -> OneDriveToolkit
```

Factory function to create a OneDrive toolkit.

Args:
    client_id: Azure AD application client ID
    client_secret: Azure AD application client secret
    tenant_id: Azure AD tenant ID
    **kwargs: Additional toolkit arguments

Returns:
    Configured OneDriveToolkit instance

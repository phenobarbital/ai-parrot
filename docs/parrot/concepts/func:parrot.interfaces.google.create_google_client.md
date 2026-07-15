---
type: Concept
title: create_google_client()
id: func:parrot.interfaces.google.create_google_client
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory function to create a GoogleClient.
---

# create_google_client

```python
def create_google_client(credentials: Optional[Union[str, dict, Path]]=None, scopes: Optional[Union[List[str], str]]=None, **kwargs) -> GoogleClient
```

Factory function to create a GoogleClient.

Args:
    credentials: Credentials specification
    scopes: Service scopes
    **kwargs: Additional GoogleClient arguments

Returns:
    GoogleClient instance

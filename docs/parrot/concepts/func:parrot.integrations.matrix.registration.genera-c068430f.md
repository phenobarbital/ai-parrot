---
type: Concept
title: generate_registration()
id: func:parrot.integrations.matrix.registration.generate_registration
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generate an AS registration YAML.
---

# generate_registration

```python
def generate_registration(as_token: str, hs_token: str, *, bot_localpart: str='parrot', namespace_regex: str='parrot-.*', as_url: str='http://localhost:9090', as_id: str='ai-parrot', output_path: Optional[str]=None) -> dict
```

Generate an AS registration YAML.

Args:
    as_token: Application Service token (AS → HS auth).
    hs_token: Homeserver token (HS → AS auth).
    bot_localpart: Localpart for the bot user.
    namespace_regex: Regex for the exclusive user namespace.
    as_url: URL where the AS HTTP server listens.
    as_id: Unique identifier for this AS.
    output_path: If provided, write YAML to this path.

Returns:
    The registration dict.

---
type: Wiki Entity
title: OdooConfig
id: class:parrot.interfaces.odoointerface.OdooConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for Odoo JSON-RPC connection.
---

# OdooConfig

Defined in [`parrot.interfaces.odoointerface`](../summaries/mod:parrot.interfaces.odoointerface.md).

```python
class OdooConfig(BaseModel)
```

Configuration for Odoo JSON-RPC connection.

Attributes:
    url: Odoo instance base URL (e.g., https://myodoo.com).
    database: Odoo database name.
    username: Odoo login username.
    password: Odoo login password or API key.
    timeout: Request timeout in seconds.
    verify_ssl: Whether to verify SSL certificates.

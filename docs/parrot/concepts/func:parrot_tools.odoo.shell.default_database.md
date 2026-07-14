---
type: Concept
title: default_database()
id: func:parrot_tools.odoo.shell.default_database
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the default Odoo database from the environment.
---

# default_database

```python
def default_database() -> str
```

Return the default Odoo database from the environment.

Returns:
    Database name string (may be empty if env var is unset).

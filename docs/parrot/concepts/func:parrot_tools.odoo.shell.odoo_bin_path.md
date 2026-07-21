---
type: Concept
title: odoo_bin_path()
id: func:parrot_tools.odoo.shell.odoo_bin_path
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the path to the odoo-bin binary, or None when not configured.
---

# odoo_bin_path

```python
def odoo_bin_path() -> Optional[str]
```

Return the path to the odoo-bin binary, or None when not configured.

Checks the ``ODOO_BIN`` environment variable first; falls back to
``shutil.which`` so a binary on ``PATH`` is also accepted.

Returns:
    Absolute path string, or None if unavailable.

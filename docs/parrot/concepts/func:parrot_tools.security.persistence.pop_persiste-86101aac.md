---
type: Concept
title: pop_persistence_kwargs()
id: func:parrot_tools.security.persistence.pop_persistence_kwargs
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pop ``file_manager`` and ``report_store`` from a toolkit's ``**kwargs``.
---

# pop_persistence_kwargs

```python
def pop_persistence_kwargs(kwargs: dict[str, Any]) -> tuple[FileManagerInterface | None, SecurityReportStore | None]
```

Pop ``file_manager`` and ``report_store`` from a toolkit's ``**kwargs``.

Call this BEFORE ``super().__init__(**kwargs)`` in producer toolkit
constructors to prevent unknown-kwarg errors in ``AbstractToolkit``.

Args:
    kwargs: The ``**kwargs`` dict from the toolkit constructor.  Modified
        in place — both keys are removed if present.

Returns:
    A ``(file_manager, report_store)`` tuple; either may be ``None`` if
    not present in ``kwargs``.

---
type: Wiki Entity
title: WorkdayWriteTypeBase
id: class:parrot_tools.interfaces.workday.handlers.base.WorkdayWriteTypeBase
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Single-call (non-paginated) write base for Workday write operations.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# WorkdayWriteTypeBase

Defined in [`parrot_tools.interfaces.workday.handlers.base`](../summaries/mod:parrot_tools.interfaces.workday.handlers.base.md).

```python
class WorkdayWriteTypeBase(WorkdayTypeBase)
```

Single-call (non-paginated) write base for Workday write operations.

Reuses ``WorkdayTypeBase.__init__(service, max_retries, retry_delay)``
and the bounded retry idiom from ``_paginate_soap_operation``, but issues
EXACTLY ONE ``self.service.call_operation(operation=...)`` call and parses
an acknowledgment instead of paging over results.

Subclasses MUST implement:
    ``_operation_name(self) -> str``
        Return the Workday SOAP operation name (e.g. ``"Put_Time_Clock_Events"``).
    ``build_request(self, **kwargs) -> dict``
        Build the SOAP request body dict to pass to ``call_operation``.
    ``parse_ack(self, raw: Any) -> pd.DataFrame``
        Parse the raw Zeep response into a per-row status DataFrame.

The ``execute(**kwargs)`` template drives the retry loop and delegates to
``build_request`` / ``call_operation`` / ``parse_ack``.

## Methods

- `def build_request(self, **kwargs) -> Dict[str, Any]` — Build the SOAP request body from validated models.
- `def parse_ack(self, raw: Any) -> Any` — Parse the raw Zeep acknowledgment into a per-row status DataFrame.
- `async def execute(self, **kwargs) -> Any` — Issue exactly one SOAP write call with retry, then parse the ack.

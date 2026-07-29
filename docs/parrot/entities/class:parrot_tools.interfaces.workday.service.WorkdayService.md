---
type: Wiki Entity
title: WorkdayService
id: class:parrot_tools.interfaces.workday.service.WorkdayService
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Workday operational interface — composable without a FlowComponent.
relates_to:
- concept: class:parrot.interfaces.soap.SOAPClient
  rel: extends
---

# WorkdayService

Defined in [`parrot_tools.interfaces.workday.service`](../summaries/mod:parrot_tools.interfaces.workday.service.md).

```python
class WorkdayService(SOAPClient)
```

Workday operational interface — composable without a FlowComponent.

Args:
    config: Explicit credentials / tenant.  ``None`` → falls back to the
        ``WORKDAY_*`` settings in ``parrot.conf`` (G3).
    operation_type: Determines the WSDL to load.  Defaults to
        ``"get_workers"`` (staffing WSDL).
    **kwargs: Forwarded to ``SOAPClient.__init__`` (e.g. ``redis_url``).

Example::

    async with WorkdayService(config=WorkdayConfig()) as svc:
        df = await svc.fetch("get_workers")

## Methods

- `async def call_operation(self, operation: str, **kwargs: Any) -> Any` — Raw SOAP invoke — the single choke point for all handlers (G4).
- `async def fetch(self, operation_type: str, **params: Any) -> pd.DataFrame` — Dispatch to the registered handler and return a DataFrame.
- `async def fetch_models(self, operation_type: str, **params: Any) -> list` — Typed path returning the underlying Pydantic models (C7).
- `async def get_custom_report(self, report_name: str, report_owner: str | None=None, **query_params: Any) -> pd.DataFrame` — Execute any Workday RaaS (Reports as a Service) custom report.
- `async def put_time_clock_events(self, events: 'list[ClockEvent]', *, auto_submit: bool | None=None) -> pd.DataFrame` — Submit clock events via Put_Time_Clock_Events; return per-event status.
- `async def import_time_clock_events(self, events: 'list[ClockEvent]', *, batch_id: str | None=None) -> pd.DataFrame` — Batch-import clock events via Import_Time_Clock_Events.
- `async def import_reported_time_blocks(self, blocks: 'list[ReportedTimeBlock]') -> pd.DataFrame` — Import reported time blocks via Import_Reported_Time_Blocks.
- `async def get_calculated_time_blocks(self, **criteria: Any) -> pd.DataFrame` — Typed wrapper over the existing get_time_blocks handler (G3, read-only).
- `async def start(self, **_kwargs: Any) -> None` — Initialise Redis, OAuth token, and Zeep transport/client.
- `async def close(self) -> None` — Release transport, Redis, and Zeep client.
- `def serialize_object(self, obj: Any) -> Any` — Custom serialiser that preserves Zeep ID objects.
- `def split_parts(self, task_list: list, num_parts: int=5) -> list` — Divide ``task_list`` into ``num_parts`` roughly equal sublists.
- `def add_metric(self, key: str, value: Any) -> None` — Store a named metric. Called by handlers to record counts.

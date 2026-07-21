---
type: Wiki Entity
title: WorkdayResponseParser
id: class:parrot_tools.workday.models.WorkdayResponseParser
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parser that transforms verbose Zeep responses into clean Pydantic models.
---

# WorkdayResponseParser

Defined in [`parrot_tools.workday.models`](../summaries/mod:parrot_tools.workday.models.md).

```python
class WorkdayResponseParser
```

Parser that transforms verbose Zeep responses into clean Pydantic models.

Supports:
- Default models per object type
- Custom output formats via output_format parameter
- Graceful handling of missing fields

## Methods

- `def parse_worker_response(cls, response: Any, output_format: Optional[Type[T]]=None) -> Union[WorkerModel, T]` — Parse a worker response into a structured model.
- `def parse_workers_response(cls, response: Any, output_format: Optional[Type[T]]=None) -> List[Union[WorkerModel, T]]` — Parse multiple workers from Get_Workers response.
- `def parse_contact_response(cls, response: Any, worker_id: str, output_format: Optional[Type[T]]=None) -> Union[ContactModel, T]` — Parse contact information from Get_Workers response.
- `def parse_time_off_balance_response(cls, response: Any, worker_id: str, output_format: Optional[Type[T]]=None) -> Union[TimeOffBalanceModel, T]` — Parse time off balance information from Get_Workers response.
- `def parse_time_off_plan_balances_response(cls, response: Any, worker_id: str, output_format: Optional[Type[T]]=None) -> Union[TimeOffBalanceModel, T]` — Parse Get_Time_Off_Plan_Balances response from Absence Management API.

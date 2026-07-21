---
type: Concept
title: parse_time_off_balance_data()
id: func:parrot_tools.interfaces.workday.parsers.time_off_balance_parsers.parse_time_off_balance_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse time off plan balance data from the SOAP response.
---

# parse_time_off_balance_data

```python
def parse_time_off_balance_data(balance_data: Dict[str, Any]) -> List[Dict[str, Any]]
```

Parse time off plan balance data from the SOAP response.

Note: The structure is:
- Time_Off_Plan_Balance (one per worker)
  - Employee_Reference (worker info)
  - Time_Off_Plan_Balance_Data
    - Time_Off_Plan_Balance_Record[] (array of plans)

Returns a list of parsed records (one per plan).

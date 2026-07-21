---
type: Concept
title: parse_position_management_chain_data()
id: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_position_management_chain_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse management chain data from Position_Management_Chains_Data.
---

# parse_position_management_chain_data

```python
def parse_position_management_chain_data(worker_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse management chain data from Position_Management_Chains_Data.
This is different from Worker_Management_Chain_Data and contains the actual management chain.

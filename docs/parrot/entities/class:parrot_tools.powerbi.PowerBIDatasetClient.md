---
type: Wiki Entity
title: PowerBIDatasetClient
id: class:parrot_tools.powerbi.PowerBIDatasetClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Client for executing DAX queries against a Power BI dataset.
---

# PowerBIDatasetClient

Defined in [`parrot_tools.powerbi`](../summaries/mod:parrot_tools.powerbi.md).

```python
class PowerBIDatasetClient(BaseModel)
```

Client for executing DAX queries against a Power BI dataset.

## Methods

- `def request_url(self) -> str`
- `def run(self, command: str, timeout: int=30) -> Dict[str, Any]`
- `async def arun(self, command: str, timeout: int=30) -> Dict[str, Any]`
- `def get_table_info(self, tables: Optional[Union[str, List[str]]]=None) -> str`
- `async def aget_table_info(self, tables: Optional[Union[str, List[str]]]=None) -> str`

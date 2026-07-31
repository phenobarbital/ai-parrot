---
type: Wiki Entity
title: Message
id: class:parrot.a2a.models.Message
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Communication unit between agents.
---

# Message

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class Message
```

Communication unit between agents.

## Methods

- `def user(cls, content: Union[str, Dict, List[Part]], **kwargs) -> 'Message'`
- `def agent(cls, content: Union[str, Dict, List[Part]], **kwargs) -> 'Message'`
- `def get_text(self) -> str` — Extract all text content from parts.
- `def get_data(self) -> Optional[Dict[str, Any]]` — Extract structured data from parts.
- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
- `def from_dict(cls, data: Dict[str, Any]) -> 'Message'`

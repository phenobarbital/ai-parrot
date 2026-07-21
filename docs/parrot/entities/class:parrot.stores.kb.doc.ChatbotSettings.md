---
type: Wiki Entity
title: ChatbotSettings
id: class:parrot.stores.kb.doc.ChatbotSettings
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Knowledge Base for chatbot-specific settings.
relates_to:
- concept: class:parrot.stores.kb.redis.RedisKnowledgeBase
  rel: extends
---

# ChatbotSettings

Defined in [`parrot.stores.kb.doc`](../summaries/mod:parrot.stores.kb.doc.md).

```python
class ChatbotSettings(RedisKnowledgeBase)
```

Knowledge Base for chatbot-specific settings.

## Methods

- `async def search(self, query: str, chatbot_id: Optional[str]=None, **kwargs) -> List[Dict[str, Any]]` — Retrieve chatbot settings.
- `async def get_setting(self, chatbot_id: str, setting: str, default: Any=None) -> Any` — Get a specific chatbot setting.
- `async def set_setting(self, chatbot_id: str, setting: str, value: Any) -> bool` — Set a specific chatbot setting.

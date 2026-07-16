---
type: Concept
title: create_simple_whatsapp_hook()
id: func:parrot.core.hooks.models.create_simple_whatsapp_hook
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a simple WhatsApp hook that routes all messages to one agent.
---

# create_simple_whatsapp_hook

```python
def create_simple_whatsapp_hook(agent_name: str, allowed_phones: Optional[List[str]]=None, command_prefix: str='') -> WhatsAppRedisHookConfig
```

Create a simple WhatsApp hook that routes all messages to one agent.

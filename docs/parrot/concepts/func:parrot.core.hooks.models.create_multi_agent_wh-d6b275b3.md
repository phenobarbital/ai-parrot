---
type: Concept
title: create_multi_agent_whatsapp_hook()
id: func:parrot.core.hooks.models.create_multi_agent_whatsapp_hook
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create a multi-agent WhatsApp hook with keyword/phone routing.
---

# create_multi_agent_whatsapp_hook

```python
def create_multi_agent_whatsapp_hook(default_agent: str, routes: List[Dict[str, Any]], command_prefix: str='') -> WhatsAppRedisHookConfig
```

Create a multi-agent WhatsApp hook with keyword/phone routing.

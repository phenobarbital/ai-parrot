---
type: Concept
title: create_crew_whatsapp_hook()
id: func:parrot.core.hooks.models.create_crew_whatsapp_hook
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create a WhatsApp hook that routes messages to an AgentCrew.
---

# create_crew_whatsapp_hook

```python
def create_crew_whatsapp_hook(crew_id: str, allowed_phones: Optional[List[str]]=None, command_prefix: str='!') -> WhatsAppRedisHookConfig
```

Create a WhatsApp hook that routes messages to an AgentCrew.

---
type: Concept
title: create_live_client()
id: func:parrot.clients.live.create_live_client
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Factory function to create a GeminiLiveClient.
---

# create_live_client

```python
def create_live_client(model: Optional[Union[str, GoogleVoiceModel]]=None, voice_name: str='Puck', tools: Optional[List[AbstractTool]]=None, use_tools: bool=True, **kwargs) -> GeminiLiveClient
```

Factory function to create a GeminiLiveClient.

Args:
    model: Model identifier (defaults to latest native audio)
    voice_name: Voice for synthesis
    tools: List of tools to register
    use_tools: Enable tool usage
    **kwargs: Additional client configuration

Returns:
    Configured GeminiLiveClient instance

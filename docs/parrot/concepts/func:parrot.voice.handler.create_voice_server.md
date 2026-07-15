---
type: Concept
title: create_voice_server()
id: func:parrot.voice.handler.create_voice_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create complete voice server application.
---

# create_voice_server

```python
def create_voice_server(bot_factory: Optional[Callable[[], VoiceBot]]=None, bot_config: Optional[Union[BotConfig, Dict[str, Any]]]=None, *, require_auth: bool=False, secret_key: Optional[str]=None, static_dir: Optional[str]=None, **kwargs) -> web.Application
```

Create complete voice server application.

Args:
    bot_factory: Custom bot factory
    bot_config: Default bot configuration
    require_auth: Require JWT authentication
    secret_key: JWT secret key
    static_dir: Static files directory
    **kwargs: Additional handler arguments

Returns:
    Configured aiohttp Application

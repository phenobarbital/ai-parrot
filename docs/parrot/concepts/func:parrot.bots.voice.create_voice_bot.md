---
type: Concept
title: create_voice_bot()
id: func:parrot.bots.voice.create_voice_bot
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory to create a configured VoiceBot.
---

# create_voice_bot

```python
def create_voice_bot(name: str='Voice Assistant', system_prompt: Optional[str]=None, voice_name: str='Puck', language: str='en-US', tools: Optional[List[Any]]=None, **kwargs) -> VoiceBot
```

Factory to create a configured VoiceBot.

Args:
    name: Bot name
    system_prompt: System instructions
    voice_name: Voice to use (Puck, Charon, Kore, etc.)
    language: Language code
    tools: List of tools
    **kwargs: Additional configuration

Returns:
    Configured VoiceBot

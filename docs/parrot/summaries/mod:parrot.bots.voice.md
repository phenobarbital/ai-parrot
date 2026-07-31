---
type: Wiki Summary
title: parrot.bots.voice
id: mod:parrot.bots.voice
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: VoiceBot - Bot implementation with voice interaction capabilities.
relates_to:
- concept: class:parrot.bots.voice.VoiceBot
  rel: defines
- concept: func:parrot.bots.voice.create_voice_bot
  rel: defines
- concept: mod:parrot.a2a.server
  rel: references
- concept: mod:parrot.bots.base
  rel: references
- concept: mod:parrot.bots.prompts
  rel: references
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.clients.factory
  rel: references
- concept: mod:parrot.clients.live
  rel: references
- concept: mod:parrot.clients.models
  rel: references
- concept: mod:parrot.clients.nova_sonic
  rel: references
- concept: mod:parrot.mcp
  rel: references
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.models.voice
  rel: references
- concept: mod:parrot.tools
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.bots.voice`

VoiceBot - Bot implementation with voice interaction capabilities.

Extends BaseBot to support voice input/output using native speech-to-speech
models like Gemini Live API.

## Classes

- **`VoiceBot(A2AEnabledMixin, BaseBot)`** — Bot with native voice interaction capabilities.

## Functions

- `def create_voice_bot(name: str='Voice Assistant', system_prompt: Optional[str]=None, voice_name: str='Puck', language: str='en-US', tools: Optional[List[Any]]=None, **kwargs) -> VoiceBot` — Factory to create a configured VoiceBot.

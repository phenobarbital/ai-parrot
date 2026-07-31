---
type: Wiki Entity
title: AgentVoiceTalk
id: class:parrot.handlers.agent_voice.AgentVoiceTalk
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Voice-capable REST handler: audio → STT → text agent → TTS → audio.'
relates_to:
- concept: class:parrot.handlers.agent.AgentTalk
  rel: extends
---

# AgentVoiceTalk

Defined in [`parrot.handlers.agent_voice`](../summaries/mod:parrot.handlers.agent_voice.md).

```python
class AgentVoiceTalk(AgentTalk)
```

Voice-capable REST handler: audio → STT → text agent → TTS → audio.

Endpoint: ``POST /api/v1/agents/voice/{agent_id}``

Inherits everything from :class:`AgentTalk` (agent resolution, PBAC, HITL,
auth envelopes, session and output negotiation) and overrides only the two
voice seams (``handle_upload`` inbound, ``post`` outbound). The text path
(``AgentTalk.post``) is reused unchanged.

## Methods

- `def post_init(self, *args, **kwargs) -> None` — Initialise the logger and per-request voice state.
- `async def handle_upload(self, *args, **kwargs) -> Tuple[Dict[str, Any], dict]` — Override the inherited multipart parse to transcribe voice input.
- `async def post(self) -> web.Response` — Run the inherited text dispatch, then attach synthesized audio.

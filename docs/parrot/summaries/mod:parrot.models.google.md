---
type: Wiki Summary
title: parrot.models.google
id: mod:parrot.models.google
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Google Related Models to be used in GenAI.
relates_to:
- concept: class:parrot.models.google.AspectRatio
  rel: defines
- concept: class:parrot.models.google.ConversationalScriptConfig
  rel: defines
- concept: class:parrot.models.google.FictionalSpeaker
  rel: defines
- concept: class:parrot.models.google.GoogleModel
  rel: defines
- concept: class:parrot.models.google.GoogleVoiceModel
  rel: defines
- concept: class:parrot.models.google.ImageResolution
  rel: defines
- concept: class:parrot.models.google.LyriaModel
  rel: defines
- concept: class:parrot.models.google.MusicBatchRequest
  rel: defines
- concept: class:parrot.models.google.MusicBatchResponse
  rel: defines
- concept: class:parrot.models.google.MusicGenerationRequest
  rel: defines
- concept: class:parrot.models.google.MusicGenre
  rel: defines
- concept: class:parrot.models.google.MusicMood
  rel: defines
- concept: class:parrot.models.google.TTSVoice
  rel: defines
- concept: class:parrot.models.google.VertexAIModel
  rel: defines
- concept: class:parrot.models.google.VideoReelRequest
  rel: defines
- concept: class:parrot.models.google.VideoReelScene
  rel: defines
- concept: class:parrot.models.google.VoiceProfile
  rel: defines
- concept: class:parrot.models.google.VoiceRegistry
  rel: defines
---

# `parrot.models.google`

Google Related Models to be used in GenAI.

## Classes

- **`GoogleModel(Enum)`** — Enum for Google AI models.
- **`GoogleVoiceModel(str, Enum)`** — Available models for Gemini Live API.
- **`TTSVoice(str, Enum)`** — Google TTS voices.
- **`MusicGenre(str, Enum)`** — Music Genres supported by Lyria.
- **`MusicMood(str, Enum)`** — Music Moods/Descriptions supported by Lyria.
- **`MusicGenerationRequest(BaseModel)`** — Request payload for Lyria music generation.
- **`LyriaModel(str, Enum)`** — Available Lyria models for music generation.
- **`MusicBatchRequest(BaseModel)`** — Request payload for Lyria batch music generation (Vertex AI).
- **`MusicBatchResponse(BaseModel)`** — Response from Lyria batch API.
- **`VertexAIModel(Enum)`** — Enum for Vertex AI models.
- **`AspectRatio(str, Enum)`** — Supported aspect ratios for Gemini Image Generation.
- **`ImageResolution(str, Enum)`** — Supported resolutions for Gemini Image Generation.
- **`FictionalSpeaker(BaseModel)`** — Configuration for a fictional character in the generated script.
- **`ConversationalScriptConfig(BaseModel)`** — Configuration for generating a conversational script with fictional characters.
- **`VoiceProfile(BaseModel)`** — Represents a single pre-built generative voice, mapping its name
- **`VoiceRegistry`** — A comprehensive registry for managing and querying available voice profiles.
- **`VideoReelScene(BaseModel)`** — Configuration for a single scene in a video reel.
- **`VideoReelRequest(BaseModel)`** — Request configuration for generating a complete video reel.

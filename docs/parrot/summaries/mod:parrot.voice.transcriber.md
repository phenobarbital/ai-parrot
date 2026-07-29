---
type: Wiki Summary
title: parrot.voice.transcriber
id: mod:parrot.voice.transcriber
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shared Voice Transcription Module.
relates_to:
- concept: mod:parrot.voice
  rel: references
- concept: mod:parrot.voice.models
  rel: references
---

# `parrot.voice.transcriber`

Shared Voice Transcription Module.

Provides voice transcription capabilities for all integrations
(MS Teams, Telegram, etc.) using pluggable backends.

Supported backends:
- FasterWhisper: Local GPU-accelerated transcription
- OpenAI Whisper: Cloud-based transcription via OpenAI API

Originally part of FEAT-008 (MS Teams Voice Note Support),
refactored to shared location for FEAT-039 (Telegram Voice Note Support).

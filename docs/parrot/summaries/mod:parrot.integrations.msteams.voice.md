---
type: Wiki Summary
title: parrot.integrations.msteams.voice
id: mod:parrot.integrations.msteams.voice
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MS Teams Voice Module.
relates_to:
- concept: mod:parrot.integrations.msteams.models
  rel: references
- concept: mod:parrot.voice.transcriber
  rel: references
---

# `parrot.integrations.msteams.voice`

MS Teams Voice Module.

Provides voice transcription capabilities for MS Teams integration,
enabling agents to process voice note attachments from users.

Part of FEAT-008: MS Teams Voice Note Support.

Note: The core transcription infrastructure has been refactored to
`parrot.voice.transcriber` (FEAT-039) for sharing across integrations.
This module re-exports those symbols for backward compatibility and
keeps only MS Teams-specific components (AudioAttachment).

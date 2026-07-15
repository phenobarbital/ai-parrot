---
type: Wiki Entity
title: VoiceRegistry
id: class:parrot.models.google.VoiceRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A comprehensive registry for managing and querying available voice profiles.
---

# VoiceRegistry

Defined in [`parrot.models.google`](../summaries/mod:parrot.models.google.md).

```python
class VoiceRegistry
```

A comprehensive registry for managing and querying available voice profiles.

## Methods

- `def find_voice_by_name(self, name: str) -> Optional[VoiceProfile]` — Finds a voice profile by its name (case-insensitive).
- `def get_all_voices(self) -> List[VoiceProfile]` — Returns a list of all voice profiles in the registry.
- `def get_voices_by_gender(self, gender: Gender) -> List[VoiceProfile]` — Filters and returns all voices matching the specified gender.
- `def get_voices_by_characteristic(self, characteristic: str) -> List[VoiceProfile]` — Filters and returns all voices with a specific characteristic (case-insensitive).

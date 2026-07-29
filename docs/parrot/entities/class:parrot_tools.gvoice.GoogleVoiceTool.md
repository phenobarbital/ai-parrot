---
type: Wiki Entity
title: GoogleVoiceTool
id: class:parrot_tools.gvoice.GoogleVoiceTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for generating speech audio from text using Google Cloud Text-to-Speech.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# GoogleVoiceTool

Defined in [`parrot_tools.gvoice`](../summaries/mod:parrot_tools.gvoice.md).

```python
class GoogleVoiceTool(AbstractTool)
```

Tool for generating speech audio from text using Google Cloud Text-to-Speech.

This tool converts text content (including Markdown) into high-quality speech audio
using Google's neural voice models. It supports multiple languages, voice customization,
and various audio output formats.

Features:
- Automatic Markdown to SSML conversion for natural speech
- Multiple voice models and languages
- Configurable speech parameters (rate, pitch)
- Various audio output formats (OGG, MP3, WAV, etc.)
- Async processing for better performance
- Comprehensive error handling and logging

## Methods

- `def execute_sync(self, text: str, voice_model: Optional[str]=None, voice_gender: str='FEMALE', language_code: str='en-US', output_format: str='OGG_OPUS', file_prefix: str='podcast', speaking_rate: float=1.0, pitch: float=0.0, use_ssml: bool=True) -> Dict[str, Any]` — Execute TTS synthesis synchronously.
- `def get_available_voices(self, language_code: Optional[str]=None) -> Dict[str, Any]` — Get available voice models for a language or all languages.
- `def get_supported_formats(self) -> Dict[str, str]` — Get supported audio output formats.
- `def preview_ssml(self, text: str) -> str` — Preview how text would be converted to SSML.
- `def estimate_cost(self, text: str, use_ssml: bool=True) -> Dict[str, Any]` — Estimate the cost for TTS synthesis (rough calculation).

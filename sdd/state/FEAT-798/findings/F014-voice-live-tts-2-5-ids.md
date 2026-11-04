---
id: F014
query_id: Q023
type: grep
intent: "Voice / live paths: gemini-2.5-flash-live, native-audio and TTS ids used by GoogleLive / voice integrations (a 2.5 retirement may or may not include them)."
executed_at: 2026-11-04T01:42:07Z
duration_ms: 400
parent_id: null
depth: 0
---

# F014 — A separate core enum GoogleVoiceModel defaults to gemini-2.5-flash-native-audio; TTS ids are 2.5-preview in GoogleModel

## Summary

Live/voice ids live in a *second* catalogue, `packages/ai-parrot/src/parrot/models/google.py::GoogleVoiceModel(str, Enum)` (core, not the client satellite): `GEMINI_2_5_FLASH_NATIVE_AUDIO_LATEST/_DEC_2025/_SEP_2025`, `GEMINI_2_5_FLASH_PREVIEW_TTS`, `GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"` and `DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"` (lines 22-28). In the client catalogue, `GEMINI_2_5_FLASH_TTS`/`GEMINI_2_5_PRO_TTS` (2.5 preview TTS) coexist with `GEMINI_3_1_FLASH_TTS_PREVIEW` and `GEMINI_3_1_FLASH_LIVE_PREVIEW` (models.py:37-39). `generation.py:572` defaults speech to `GEMINI_2_5_FLASH_TTS`. The user's request names only pro/flash; whether Google's 2026-12-01 deprecation covers native-audio/TTS previews is not answerable from the repo.

## Citations

- path: `packages/ai-parrot/src/parrot/models/google.py`
  lines: 13-28
  symbol: `GoogleVoiceModel`
  excerpt: |
    class GoogleVoiceModel(str, Enum):
        """Available models for Gemini Live API. ..."""
        GEMINI_2_5_FLASH_NATIVE_AUDIO_LATEST = "gemini-2.5-flash-native-audio-preview-12-2025"
        GEMINI_2_5_FLASH_NATIVE_AUDIO_DEC_2025 = "gemini-2.5-flash-native-audio-preview-12-2025"
        GEMINI_2_5_FLASH_NATIVE_AUDIO_SEP_2025 = "gemini-2.5-flash-native-audio-preview-09-2025"
        GEMINI_2_5_FLASH_PREVIEW_TTS = "gemini-2.5-flash-preview-tts"
        GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"
        # Aliases
        DEFAULT = "gemini-2.5-flash-native-audio-preview-12-2025"

- path: `packages/ai-parrot/src/parrot/models/google.py`
  lines: 456-456, 602-602
  symbol: (video-reel director default)
  excerpt: |
    "None resolves to the default director model ('gemini-2.5-flash')."
    return self.director_model or "gemini-2.5-flash"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: 37-39, 46-47
  symbol: `GoogleModel` (TTS / live members)
  excerpt: |
    GEMINI_3_1_FLASH_TTS_PREVIEW = "gemini-3.1-flash-tts-preview"
    GEMINI_3_FLASH_TTS = "gemini-3.1-flash-tts-preview"
    GEMINI_3_1_FLASH_LIVE_PREVIEW = "gemini-3.1-flash-live-preview"
    GEMINI_2_5_FLASH_TTS = "gemini-2.5-flash-preview-tts"
    GEMINI_2_5_PRO_TTS = "gemini-2.5-pro-preview-tts"

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py`
  lines: 572-572
  symbol: (speech default)
  excerpt: |
    model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_TTS,

## Notes

- `models/google.py:602` is the video-reel `director_model` fallback (`gemini-2.5-flash`) — a text-model default hiding in the core models module, within the pro/flash scope.
- `bots/voice.py:438` text LLM default (F006) is in scope; the native-audio `DEFAULT` is a distinct product question (unknown for the synthesis).

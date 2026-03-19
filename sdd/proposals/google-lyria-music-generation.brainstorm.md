# Brainstorm: Google Lyria Music Generation Enhancement

**Date**: 2026-03-02
**Author**: Claude
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The `GoogleGenAIClient` already has a `generate_music` method using **Lyria RealTime** (streaming WebSocket API). However, this implementation:

1. **Streams raw PCM bytes** — requires external handling to create usable audio files
2. **Only supports Lyria RealTime** — the Vertex AI batch endpoint (`lyria-002`) offers simpler, non-streaming generation
3. **Lacks Lyria 3 features** — the newest model (Feb 2026) supports AI vocals, multimodal input (text + images), and 8-language support
4. **No real-time steering** — existing implementation sends prompts once, doesn't support mid-stream transitions

**Users affected**: Developers building AI music applications, video reel generation (already uses music), conversational agents with audio output.

**Why now**: Lyria 3 launched Feb 2026 with significant new capabilities. The current implementation works but doesn't expose the full Lyria ecosystem.

## Constraints & Requirements

- Must maintain async-first patterns (existing `generate_music` is async generator)
- Must work with both Gemini API (API key) and Vertex AI (service account)
- Must not break existing `generate_music` or `_generate_reel_music` methods
- Output should integrate with existing `_save_audio_file` helper (48kHz stereo PCM → WAV)
- Should follow existing patterns from `generate_images`, `generate_speech`, `generate_videos`

---

## Options Explored

### Option A: Add Vertex AI Lyria Batch API

Add a new `generate_music_batch` method that uses the Vertex AI `lyria-002` endpoint for non-streaming, complete 30-second WAV file generation.

This approach is simpler for use cases that don't need streaming — request in, WAV file out.

**API Endpoint:**
```
POST https://LOCATION-aiplatform.googleapis.com/v1/projects/PROJECT_ID/locations/LOCATION/publishers/google/models/lyria-002:predict
```

**Response:** Base64-encoded WAV (30 seconds, 48kHz)

**Key difference from RealTime:** No WebSocket, no streaming, simpler error handling, deterministic seeds possible.

✅ **Pros:**
- Simpler implementation — single HTTP POST, no WebSocket management
- Returns complete WAV file — no PCM-to-WAV conversion needed
- Supports `seed` parameter for reproducible generation
- Supports `negative_prompt` for excluding unwanted elements
- Better for batch processing workflows
- Clear pricing model ($0.06 per 30-second output)

❌ **Cons:**
- Requires Vertex AI (service account auth) — not available via Gemini API key
- Fixed 30-second output — no variable duration control
- Instrumental only — same as RealTime
- Additional dependency on Vertex AI project/location configuration

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | Async HTTP requests | Already in dependencies |
| `google-auth` | Service account authentication | Already used for Vertex AI |

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/client.py:get_client()` — Vertex AI credentials handling
- `parrot/clients/google/generation.py:_save_audio_file()` — WAV file creation
- `parrot/models/google.py:MusicGenerationRequest` — Request validation model

---

### Option B: Add Lyria 3 Support with AI Vocals

Integrate Lyria 3, Google's newest music generation model (Feb 2026) that supports:
- Full AI vocals (not just instrumental)
- Auto-lyrics generation
- Multimodal input (text + images + video as context)
- 8-language support
- SynthID watermarking

This would be a new method `generate_music_with_vocals` or extend `generate_music` with a `model` parameter.

✅ **Pros:**
- Access to AI-generated vocals — major differentiator
- Multimodal input opens creative possibilities (image-to-music, video-to-music)
- 8-language lyric support for internationalization
- Latest model with best audio quality
- Built-in SynthID watermarking for content authenticity

❌ **Cons:**
- Currently only available in Gemini app — API availability unclear
- May require experimental/preview API access
- More complex implementation (multimodal input handling)
- Potential content moderation/safety considerations for lyrics

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai` | Gemini API SDK | Already in dependencies |
| `PIL/Pillow` | Image preprocessing | Already in dependencies |

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/generation.py:_load_image()` — Image loading for multimodal
- `parrot/models/google.py:MusicGenre`, `MusicMood` — Existing enums
- `parrot/clients/google/client.py:get_client()` — Client initialization

---

### Option C: Add High-Level `generate_music_file` Method

Create a convenience method that wraps the existing `generate_music` streaming API and outputs a complete audio file. This addresses the common use case of "I just want a music file."

```python
async def generate_music_file(
    self,
    prompt: str,
    output_path: Path,
    duration: int = 30,
    format: str = "wav",
    **kwargs
) -> Path:
```

✅ **Pros:**
- Leverages existing, working `generate_music` implementation
- Solves the most common developer need (get a file, not a stream)
- Minimal code changes — just wraps existing method
- Duration control via timeout parameter
- Multiple output formats (WAV, MP3 with ffmpeg)

❌ **Cons:**
- Still uses RealTime API — inherits its limitations
- Adds redundancy with `_generate_reel_music` which does similar work
- No new capabilities — just convenience wrapper
- Duration is approximate (timeout-based, not precise)

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiofiles` | Async file writing | Already in dependencies |
| `ffmpeg` (optional) | MP3/OGG conversion | System dependency |

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/generation.py:generate_music()` — Core streaming method
- `parrot/clients/google/generation.py:_save_audio_file()` — WAV encoding
- `parrot/clients/google/generation.py:_generate_reel_music()` — Reference implementation

---

### Option D: Add Real-Time Steering Capabilities

Enhance the existing `generate_music` to support real-time prompt transitions (crossfading between styles) as documented in the Lyria RealTime API.

```python
async def generate_music_interactive(
    self,
    initial_prompt: str,
    **kwargs
) -> MusicSession:
    """Returns a session object for real-time steering."""
```

The session would expose:
- `set_prompt(prompt, weight)` — Transition to new style
- `set_config(bpm, density, ...)` — Adjust parameters mid-stream
- `receive()` — Async iterator for audio chunks

✅ **Pros:**
- Unlocks full RealTime API potential
- Enables DJ-style mixing applications
- Interactive music experiences (user controls music in real-time)
- Differentiating feature for AI-Parrot

❌ **Cons:**
- Complex implementation — session management, concurrent async tasks
- Limited use cases — most users want static music, not real-time control
- Requires client-side handling of smooth transitions
- Testing complexity — real-time interactions are hard to test

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai` | Gemini Live API | Already in dependencies |
| `asyncio` | Async session management | Standard library |

🔗 **Existing Code to Reuse:**
- `parrot/clients/google/generation.py:generate_music()` — Base WebSocket handling
- `parrot/models/google.py:MusicGenerationRequest` — Config model

---

## Recommendation

**Option A** (Vertex AI Lyria Batch API) is recommended because:

1. **Low effort, high value**: Single HTTP request vs. WebSocket management
2. **Complements existing streaming**: Users get choice — streaming for real-time, batch for files
3. **Better developer experience**: Returns complete WAV file, no assembly required
4. **Reproducibility**: `seed` parameter enables deterministic generation
5. **Clear cost model**: $0.06 per track, easy to budget

**Trade-offs accepted:**
- Requires Vertex AI credentials (most production deployments already have this)
- Fixed 30-second duration (acceptable for most music applications)
- Instrumental only (same as current implementation)

**Follow-up**: Once Lyria 3 API becomes publicly available, Option B can be implemented as an enhancement.

---

## Feature Description

### User-Facing Behavior

Developers call `generate_music_batch()` with a text prompt describing desired music:

```python
client = GoogleGenAIClient(vertexai=True)
result = await client.generate_music_batch(
    prompt="Upbeat electronic music with synthesizer arpeggios",
    negative_prompt="drums, percussion",
    seed=42,  # For reproducibility
    output_directory=Path("./output"),
    sample_count=2  # Generate 2 variations
)
# Returns: List[Path] pointing to saved WAV files
```

The method returns paths to generated WAV files (30 seconds each, 48kHz stereo).

### Internal Behavior

1. **Validation**: Validate prompt (non-empty), seed/sample_count mutual exclusivity
2. **Authentication**: Get Vertex AI credentials via existing `get_client()` path
3. **Request**: Build JSON payload per Lyria API spec
4. **HTTP POST**: Send to `lyria-002:predict` endpoint
5. **Response parsing**: Extract base64-encoded WAV from `predictions[].audioContent`
6. **File saving**: Decode and save to output directory with unique filenames
7. **Return**: List of saved file paths

### Edge Cases & Error Handling

| Scenario | Handling |
|---|---|
| Empty prompt | Raise `ValueError("Prompt cannot be empty")` |
| Both seed and sample_count provided | Raise `ValueError("Cannot combine seed with sample_count")` |
| Invalid seed value | Pass through to API, let Vertex AI validate |
| API rate limit | Raise `RateLimitError` with retry-after if available |
| Content safety rejection | Log warning, return empty list |
| Network timeout | Raise `asyncio.TimeoutError` with context |
| Invalid credentials | Raise `AuthenticationError` with guidance |
| Output directory doesn't exist | Create it automatically |

---

## Capabilities

### New Capabilities
- `lyria-batch-music-generation`: Generate complete music files via Vertex AI Lyria batch API

### Modified Capabilities
- `google-client`: Extends `GoogleGenAIClient` with new generation method

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/google/generation.py` | extends | Add `generate_music_batch()` method |
| `parrot/clients/google/client.py` | depends on | Uses existing Vertex AI auth |
| `parrot/models/google.py` | extends | Add `MusicBatchRequest` model, `LyriaModel` enum |
| `examples/` | extends | Add usage example |
| `tests/` | extends | Add unit tests for new method |

---

## Open Questions

- [ ] Should `generate_music_batch` be added to `GoogleGeneration` mixin or directly to `GoogleGenAIClient`? — *Owner: maintainer*: add to GoogleGeneration mixin.
- [ ] Should we deprecate the name `generate_music` in favor of `generate_music_stream` for clarity? — *Owner: maintainer*: yes
- [ ] What's the timeline for Lyria 3 API public availability? — *Owner: Google*: IDK
- [ ] Should output include SynthID metadata/detection utility? — *Owner: TBD*: No

---

## References

- [Lyria API Reference (Vertex AI)](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/lyria-music-generation)
- [Lyria RealTime (Gemini API)](https://ai.google.dev/gemini-api/docs/music-generation)
- [Lyria 3 Announcement](https://deepmind.google/models/lyria/)
- [Google Lyria Model Overview](https://blog.google/innovation-and-ai/products/gemini-app/lyria-3/)

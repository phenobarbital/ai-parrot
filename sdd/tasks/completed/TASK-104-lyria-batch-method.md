# TASK-104: Implement generate_music_batch Method

**Feature**: google-lyria-music-generation
**Spec**: `sdd/specs/google-lyria-music-generation.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-103
**Assigned-to**: claude-session

---

## Context

This task implements Module 2 from the spec — the core `generate_music_batch()` method in the `GoogleGeneration` mixin.

This method calls the Vertex AI Lyria REST API (`lyria-002`) to generate complete 30-second WAV files, providing an alternative to the existing streaming approach.

---

## Scope

- Implement `generate_music_batch()` method in `GoogleGeneration` mixin
- Build correct JSON payload for Lyria API
- Handle authentication via existing Vertex AI credentials
- Parse base64-encoded WAV response
- Save files to output directory using existing `_save_audio_file()` pattern
- Validate seed/sample_count mutual exclusivity
- Handle errors gracefully (empty prompt, auth failure, content safety)

**NOT in scope**:
- Data models (TASK-103)
- Renaming existing methods (TASK-105)
- Tests (TASK-107)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/google/generation.py` | MODIFY | Add `generate_music_batch()` method |

---

## Implementation Notes

### API Endpoint

```
POST https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/lyria-002:predict
```

### Request Format

```json
{
  "instances": [{
    "prompt": "Calm acoustic folk song with gentle guitar",
    "negative_prompt": "drums, electric guitar",
    "seed": 42
  }],
  "parameters": {
    "sample_count": 1
  }
}
```

### Response Format

```json
{
  "predictions": [{
    "audioContent": "<base64-encoded-wav>",
    "mimeType": "audio/wav"
  }]
}
```

### Pattern to Follow

Follow the existing `generate_images()` method pattern:

```python
async def generate_music_batch(
    self,
    prompt: str,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
    sample_count: int = 1,
    output_directory: Optional[Path] = None,
    genre: Optional[Union[str, MusicGenre]] = None,
    mood: Optional[Union[str, MusicMood]] = None,
) -> List[Path]:
    """
    Generate music using Vertex AI Lyria batch API.

    Returns complete 30-second WAV files (48kHz stereo).
    """
    # 1. Validation
    if not prompt or not prompt.strip():
        raise ValueError("Prompt cannot be empty")
    if seed is not None and sample_count > 1:
        raise ValueError("Cannot combine seed with sample_count > 1")

    # 2. Build prompt with genre/mood
    full_prompt = prompt
    if genre:
        full_prompt += f", Genre: {genre}"
    if mood:
        full_prompt += f", Mood: {mood}"

    # 3. Build request payload
    instance = {"prompt": full_prompt}
    if negative_prompt:
        instance["negative_prompt"] = negative_prompt
    if seed is not None:
        instance["seed"] = seed

    payload = {
        "instances": [instance],
        "parameters": {"sample_count": sample_count} if sample_count > 1 else {}
    }

    # 4. Get credentials and make request
    # Use aiohttp with Vertex AI auth
    ...

    # 5. Parse response and save files
    output_paths = []
    for i, prediction in enumerate(response.get("predictions", [])):
        audio_b64 = prediction.get("audioContent")
        if audio_b64:
            audio_data = base64.b64decode(audio_b64)
            filename = f"lyria_batch_{uuid.uuid4().hex}_{i}.wav"
            file_path = output_dir / filename
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(audio_data)
            output_paths.append(file_path)

    return output_paths
```

### Key Constraints

- Must use `aiohttp` for HTTP requests (consistent with codebase)
- Use `google.oauth2.service_account` for auth (existing pattern)
- Create output directory if it doesn't exist
- Log key operations with `self.logger`
- Return empty list (don't raise) on content safety rejection

### References in Codebase

- `parrot/clients/google/generation.py:67` — `generate_images()` pattern
- `parrot/clients/google/client.py:88` — `get_client()` for credentials
- `parrot/clients/google/generation.py:1907` — `_generate_reel_music()` for file saving

---

## Acceptance Criteria

- [ ] Method signature matches spec
- [ ] Validates empty prompt (raises `ValueError`)
- [ ] Validates seed + sample_count > 1 (raises `ValueError`)
- [ ] Builds correct API payload with prompt, negative_prompt, seed
- [ ] Appends genre/mood to prompt if provided
- [ ] Makes authenticated POST to Vertex AI endpoint
- [ ] Decodes base64 WAV and saves to output directory
- [ ] Creates output directory if needed
- [ ] Returns `List[Path]` of saved files
- [ ] Logs key operations
- [ ] No linting errors

---

## Test Specification

```python
# Tests in TASK-107
# Key test cases to support:

async def test_generate_music_batch_empty_prompt():
    """Empty prompt raises ValueError."""
    client = GoogleGenAIClient(vertexai=True)
    with pytest.raises(ValueError, match="Prompt cannot be empty"):
        await client.generate_music_batch(prompt="")

async def test_generate_music_batch_seed_with_samples():
    """Seed + sample_count > 1 raises ValueError."""
    client = GoogleGenAIClient(vertexai=True)
    with pytest.raises(ValueError, match="Cannot combine"):
        await client.generate_music_batch(prompt="test", seed=42, sample_count=2)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/google-lyria-music-generation.spec.md`
2. **Check dependencies** — verify TASK-103 is in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the method following the pattern above
5. **Verify** acceptance criteria manually (full tests in TASK-107)
6. **Move this file** to `sdd/tasks/completed/TASK-104-lyria-batch-method.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-02
**Notes**: Implemented `generate_music_batch()` method in GoogleGeneration mixin (~160 lines). The method:
- Validates prompt (non-empty) and seed/sample_count exclusivity
- Builds Lyria API payload with prompt, negative_prompt, seed, genre, mood
- Authenticates with Vertex AI using service account or default credentials
- Makes async HTTP POST to lyria-002:predict endpoint
- Parses base64-encoded WAV responses and saves to output directory
- Handles error cases (content safety, auth failure, rate limits, timeouts)
- Logs key operations

**Deviations from spec**:
- Added additional validation for `sample_count` range (1-4)
- Added `timeout` parameter (default 120s) for HTTP request timeout
- Added explicit RuntimeError for non-Vertex AI clients (more helpful error message)

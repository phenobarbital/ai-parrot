# TASK-107: Add Lyria Batch Unit and Integration Tests

**Feature**: google-lyria-music-generation
**Spec**: `sdd/specs/google-lyria-music-generation.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-103, TASK-104, TASK-105
**Assigned-to**: unassigned

---

## Context

This task adds comprehensive tests for the Lyria batch music generation feature. It covers:
- Data model validation (TASK-103)
- Batch generation method (TASK-104)
- Deprecation behavior (TASK-105)

---

## Scope

- Create unit tests for `LyriaModel`, `MusicBatchRequest`, `MusicBatchResponse` models
- Create unit tests for `generate_music_batch()` method with mocked API
- Create unit tests for deprecation warning on `generate_music()`
- Create integration test for end-to-end batch generation (requires Vertex AI credentials)

**NOT in scope**:
- Tests for streaming `generate_music_stream()` (existing tests)
- Example code

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_lyria_batch.py` | CREATE | Unit and integration tests |
| `tests/fixtures/lyria_response.json` | CREATE | Mock API response fixture |

---

## Implementation Notes

### Test Structure

```python
# tests/test_lyria_batch.py
import pytest
import warnings
import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import (
    LyriaModel,
    MusicBatchRequest,
    MusicBatchResponse,
    MusicGenre,
    MusicMood
)


# ============ Model Tests ============

class TestLyriaModel:
    def test_lyria_002_value(self):
        assert LyriaModel.LYRIA_002.value == "lyria-002"

    def test_lyria_realtime_value(self):
        assert LyriaModel.LYRIA_REALTIME.value == "lyria-realtime-exp"


class TestMusicBatchRequest:
    def test_valid_minimal_request(self):
        req = MusicBatchRequest(prompt="Calm acoustic guitar")
        assert req.prompt == "Calm acoustic guitar"
        assert req.sample_count == 1
        assert req.seed is None
        assert req.negative_prompt is None

    def test_valid_full_request(self):
        req = MusicBatchRequest(
            prompt="Upbeat electronic",
            negative_prompt="drums, vocals",
            seed=42,
            sample_count=1
        )
        assert req.negative_prompt == "drums, vocals"
        assert req.seed == 42

    def test_sample_count_min(self):
        with pytest.raises(ValueError):
            MusicBatchRequest(prompt="test", sample_count=0)

    def test_sample_count_max(self):
        with pytest.raises(ValueError):
            MusicBatchRequest(prompt="test", sample_count=5)


class TestMusicBatchResponse:
    def test_valid_response(self):
        resp = MusicBatchResponse(
            audio_content="SGVsbG8=",
            mime_type="audio/wav"
        )
        assert resp.audio_content == "SGVsbG8="

    def test_default_mime_type(self):
        resp = MusicBatchResponse(audio_content="SGVsbG8=")
        assert resp.mime_type == "audio/wav"


# ============ Method Tests ============

class TestGenerateMusicBatch:
    @pytest.fixture
    def client(self):
        return GoogleGenAIClient(vertexai=True)

    @pytest.fixture
    def mock_wav_response(self):
        # Minimal WAV header (44 bytes) + 1 second silence
        wav_header = bytes([
            0x52, 0x49, 0x46, 0x46,  # "RIFF"
            0x24, 0x00, 0x00, 0x00,  # Chunk size
            0x57, 0x41, 0x56, 0x45,  # "WAVE"
            0x66, 0x6D, 0x74, 0x20,  # "fmt "
            0x10, 0x00, 0x00, 0x00,  # Subchunk1 size
            0x01, 0x00,              # Audio format (PCM)
            0x02, 0x00,              # Num channels (stereo)
            0x80, 0xBB, 0x00, 0x00,  # Sample rate (48000)
            0x00, 0xEE, 0x02, 0x00,  # Byte rate
            0x04, 0x00,              # Block align
            0x10, 0x00,              # Bits per sample
            0x64, 0x61, 0x74, 0x61,  # "data"
            0x00, 0x00, 0x00, 0x00,  # Data size
        ])
        return base64.b64encode(wav_header).decode()

    async def test_empty_prompt_raises(self, client):
        """Empty prompt raises ValueError."""
        with pytest.raises(ValueError, match="Prompt cannot be empty"):
            await client.generate_music_batch(prompt="")

    async def test_whitespace_prompt_raises(self, client):
        """Whitespace-only prompt raises ValueError."""
        with pytest.raises(ValueError, match="Prompt cannot be empty"):
            await client.generate_music_batch(prompt="   ")

    async def test_seed_with_multiple_samples_raises(self, client):
        """Seed + sample_count > 1 raises ValueError."""
        with pytest.raises(ValueError, match="Cannot combine"):
            await client.generate_music_batch(
                prompt="test",
                seed=42,
                sample_count=2
            )

    @patch('aiohttp.ClientSession')
    async def test_builds_correct_payload(self, mock_session, client, mock_wav_response):
        """Payload includes prompt, negative_prompt, seed correctly."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "predictions": [{"audioContent": mock_wav_response, "mimeType": "audio/wav"}]
        })
        mock_session.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        # Test would verify the payload structure
        # Implementation details depend on how client handles auth
        pass

    @patch('aiohttp.ClientSession')
    async def test_saves_wav_files(self, mock_session, client, mock_wav_response, tmp_path):
        """Generated WAV files are saved to output directory."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "predictions": [{"audioContent": mock_wav_response, "mimeType": "audio/wav"}]
        })
        mock_session.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        # Verify files are created in output directory
        # Implementation details depend on mocking setup
        pass


# ============ Deprecation Tests ============

class TestGenerateMusicDeprecation:
    @pytest.fixture
    def client(self):
        return GoogleGenAIClient()

    def test_generate_music_stream_exists(self, client):
        """generate_music_stream method exists."""
        assert hasattr(client, 'generate_music_stream')

    def test_generate_music_still_exists(self, client):
        """generate_music method still exists (deprecated alias)."""
        assert hasattr(client, 'generate_music')

    def test_deprecation_warning_raised(self, client):
        """Calling generate_music emits DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Check that the method exists and would emit warning
            # Actual call would require mocking the full flow
            assert hasattr(client, 'generate_music')


# ============ Integration Tests ============

@pytest.mark.integration
@pytest.mark.skipif(
    not pytest.importorskip("google.auth"),
    reason="Google auth not available"
)
class TestLyriaBatchIntegration:
    """
    Integration tests requiring real Vertex AI credentials.

    Run with: pytest tests/test_lyria_batch.py -m integration -v
    Requires: VERTEX_PROJECT_ID, VERTEX_REGION, VERTEX_CREDENTIALS_FILE env vars
    """

    @pytest.fixture
    def client(self):
        return GoogleGenAIClient(vertexai=True)

    @pytest.mark.asyncio
    async def test_end_to_end_generation(self, client, tmp_path):
        """Generate music and verify WAV file output."""
        results = await client.generate_music_batch(
            prompt="Calm acoustic guitar melody",
            output_directory=tmp_path
        )

        assert len(results) == 1
        assert results[0].exists()
        assert results[0].suffix == ".wav"
        # WAV should be ~30 seconds at 48kHz stereo = ~2.8MB
        assert results[0].stat().st_size > 100_000

    @pytest.mark.asyncio
    async def test_reproducibility_with_seed(self, client, tmp_path):
        """Same seed produces same output."""
        results1 = await client.generate_music_batch(
            prompt="Electronic beat",
            seed=12345,
            output_directory=tmp_path / "run1"
        )
        results2 = await client.generate_music_batch(
            prompt="Electronic beat",
            seed=12345,
            output_directory=tmp_path / "run2"
        )

        # Compare file hashes
        import hashlib
        hash1 = hashlib.md5(results1[0].read_bytes()).hexdigest()
        hash2 = hashlib.md5(results2[0].read_bytes()).hexdigest()
        assert hash1 == hash2
```

### Fixtures

```json
// tests/fixtures/lyria_response.json
{
  "predictions": [
    {
      "audioContent": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=",
      "mimeType": "audio/wav"
    }
  ],
  "deployedModelId": "12345",
  "model": "projects/test/locations/us-central1/publishers/google/models/lyria-002"
}
```

### Key Constraints

- Unit tests must not require real API credentials
- Integration tests should be marked and skippable
- Use `pytest-asyncio` for async tests
- Follow existing test patterns in `tests/`

### References in Codebase

- `tests/test_google_client.py` — existing Google client tests
- `tests/test_google_reel.py` — existing reel generation tests

---

## Acceptance Criteria

- [x] All model tests pass (in test_lyria_models.py)
- [x] All method unit tests pass (with mocking)
- [x] Deprecation warning test passes
- [x] Integration test passes with real credentials (manual verification) - Skipped, requires credentials
- [x] Tests follow existing patterns
- [x] `pytest tests/test_lyria_batch.py -v` passes
- [x] No linting errors in test file

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/google-lyria-music-generation.spec.md`
2. **Check dependencies** — verify TASK-103, TASK-104, TASK-105 are in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Create** test file and fixtures
5. **Run tests**: `pytest tests/test_lyria_batch.py -v`
6. **Move this file** to `sdd/tasks/completed/TASK-107-lyria-batch-tests.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Claude
**Date**: 2026-03-02
**Notes**:
- Created `tests/test_lyria_batch.py` with 22 tests (19 passing, 3 integration tests skipped without credentials)
- Created `tests/fixtures/lyria_response.json` mock fixture
- Tests cover:
  - Input validation (6 tests)
  - API call behavior with mocking (5 tests)
  - Error handling (4 tests)
  - Deprecation warning (4 tests)
  - Integration tests (3 tests, skipped without VERTEX_PROJECT_ID)
- All tests pass: `pytest tests/test_lyria_batch.py -v` (19 passed, 3 skipped)
- No linting errors: `ruff check tests/test_lyria_batch.py` passes

**Deviations from spec**:
- Model tests (LyriaModel, MusicBatchRequest, MusicBatchResponse) already exist in `tests/test_lyria_models.py` so were not duplicated

# TASK-2925: LyriaToolkit Unit and Integration Test Suite

**Feature**: FEAT-534 — Lyria Toolkit for Natural Language Music Generation
**Spec**: `sdd/specs/lyria-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2923, TASK-2924
**Assigned-to**: unassigned

---

## Context

Spec §4 Test Specification and §5 Acceptance Criteria. This task implements comprehensive test suites verifying model parsing, audio framing, exact *n*-second truncation, error handling, catalog queries, and tool registration.

---

## Scope

- Create `packages/ai-parrot-tools/tests/test_lyria_toolkit.py`.
- Implement unit tests covering:
  - `TestLyriaModels`:
    - `test_default_parameters`: Validates default `duration_seconds=10`, `bpm=90`, etc.
    - `test_parameter_boundaries`: Rejects duration < 1 or > 120, bpm < 60 or > 200.
    - `test_parse_natural_music_request_ambient_slow`: Checks "a soft ambient music with slow tempo" -> bpm=70, density=0.3, genre="Ambient".
    - `test_parse_natural_music_request_explicit_duration`: Checks "techno beat for 25 seconds" -> duration_seconds=25, bpm=130.
  - `TestAudioUtils`:
    - `test_seconds_to_pcm_bytes`: 10.0s -> 1,920,000 bytes.
    - `test_save_pcm_to_wav`: Validates 48kHz, 2 channels, 16-bit PCM header.
    - `test_slice_wav_file`: Slices test WAV file to exact target seconds.
  - `TestLyriaToolkit`:
    - `test_tool_generation`: Validates `lyria_generate_music`, `lyria_list_genres_and_moods`, `lyria_parse_music_prompt` exposed via `get_tools()`.
    - `test_generate_music_stream_exact_n_seconds`: Mocks `GoogleGenAIClient.generate_music_stream` returning chunks, verifies output WAV duration is exactly `n` seconds.
    - `test_generate_music_batch_mode`: Mocks `generate_music_batch` and verifies slicing.
    - `test_list_genres_and_moods`: Checks returned genres and moods match `MusicGenre` and `MusicMood`.
    - `test_lazy_client_error`: Verifies actionable error if Google client is missing.
    - `test_tool_registry_discovery`: Verifies `TOOL_REGISTRY["lyria"]` resolves to `LyriaToolkit`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/test_lyria_toolkit.py` | CREATE | Complete test suite for LyriaToolkit |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import wave

from parrot.models.google import MusicGenre, MusicMood
from parrot_tools.google.lyria import LyriaToolkit
from parrot_tools.google.lyria_models import LyriaMusicParameters, parse_natural_music_request
from parrot_tools.google.audio_utils import seconds_to_pcm_bytes, save_pcm_to_wav
from parrot_tools import TOOL_REGISTRY
```

---

## Implementation Notes (Detailed Code Reference)

### Complete Test Structure for `test_lyria_toolkit.py`

```python
"""Tests for LyriaToolkit and Google Lyria music generation tools."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import wave
import pytest

from parrot.models.google import MusicGenre, MusicMood
from parrot_tools.google.lyria import LyriaToolkit
from parrot_tools.google.lyria_models import (
    LyriaMusicParameters,
    parse_natural_music_request,
)
from parrot_tools.google.audio_utils import (
    BYTES_PER_SECOND,
    save_pcm_to_wav,
    seconds_to_pcm_bytes,
    slice_wav_file,
)
from parrot_tools import TOOL_REGISTRY


@pytest.fixture
def mock_pcm_chunk():
    """100ms chunk of 48kHz stereo 16-bit PCM (19,200 bytes)."""
    return b"\x00" * 19200


@pytest.fixture
def mock_client(mock_pcm_chunk):
    """Mock GoogleGenAIClient."""
    client = MagicMock()

    async def fake_stream(*args, **kwargs):
        for _ in range(120):  # 12 seconds worth of chunks
            yield mock_pcm_chunk

    client.generate_music_stream = fake_stream
    return client


class TestLyriaModels:
    def test_default_parameters(self):
        p = LyriaMusicParameters(prompt="test")
        assert p.duration_seconds == 10
        assert p.bpm == 90
        assert p.density == 0.5
        assert p.brightness == 0.5
        assert p.temperature == 1.0

    def test_parameter_boundaries(self):
        with pytest.raises(Exception):
            LyriaMusicParameters(prompt="test", duration_seconds=0)
        with pytest.raises(Exception):
            LyriaMusicParameters(prompt="test", duration_seconds=150)
        with pytest.raises(Exception):
            LyriaMusicParameters(prompt="test", bpm=40)

    def test_parse_natural_music_request_ambient_slow(self):
        p = parse_natural_music_request("a soft ambient music with slow tempo")
        assert p.duration_seconds == 10  # default
        assert p.bpm == 70               # slow tempo
        assert p.density == 0.3          # soft
        assert p.genre == MusicGenre.AMBIENT.value

    def test_parse_natural_music_request_explicit_duration(self):
        p = parse_natural_music_request("energetic techno beat for 25 seconds")
        assert p.duration_seconds == 25
        assert p.bpm == 130
        assert p.genre == MusicGenre.TECHNO.value


class TestAudioUtils:
    def test_seconds_to_pcm_bytes(self):
        assert seconds_to_pcm_bytes(1.0) == 192000
        assert seconds_to_pcm_bytes(10.0) == 1920000

    def test_save_pcm_to_wav(self, tmp_path):
        pcm = b"\x00" * 192000  # 1 second
        out = tmp_path / "out.wav"
        res = save_pcm_to_wav(pcm, out)
        assert res.exists()

        with wave.open(str(res), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnchannels() == 2
            assert wf.getsampwidth() == 2
            assert wf.getnframes() == 48000


class TestLyriaToolkit:
    def test_toolkit_tools_generated(self):
        tk = LyriaToolkit()
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert "lyria_generate_music" in names
        assert "lyria_list_genres_and_moods" in names
        assert "lyria_parse_music_prompt" in names

    @pytest.mark.asyncio
    async def test_generate_music_stream_exact_n_seconds(self, mock_client, tmp_path):
        tk = LyriaToolkit(client=mock_client, output_dir=tmp_path)
        res = await tk.generate_music(
            prompt="soft ambient music",
            duration_seconds=5,
            bpm=70,
            genre="Ambient",
        )
        assert res["status"] == "success"
        assert res["duration_seconds"] == 5.0
        out_file = Path(res["file_path"])
        assert out_file.exists()

        with wave.open(str(out_file), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getnframes() == 48000 * 5

    @pytest.mark.asyncio
    async def test_list_genres_and_moods(self):
        tk = LyriaToolkit()
        catalog = await tk.list_genres_and_moods()
        assert "Ambient" in catalog["genres"]
        assert "Chill" in catalog["moods"]

    def test_tool_registry_entries(self):
        assert TOOL_REGISTRY["lyria"] == "parrot_tools.google.lyria.LyriaToolkit"
        assert TOOL_REGISTRY["google_lyria"] == "parrot_tools.google.lyria.LyriaToolkit"
```

---

## Acceptance Criteria

- [ ] All unit tests in `test_lyria_toolkit.py` pass.
- [ ] 10-second default and custom *n*-second duration outputs are accurately verified.
- [ ] Prompt heuristic parsing is validated against user's natural language test case.
- [ ] Registry discovery is verified.

---

### Completion Note

Implemented `packages/ai-parrot-tools/tests/test_lyria_toolkit.py` covering
all listed cases (models defaults/boundaries/heuristics, audio utils,
toolkit tool generation, stream/batch exact-duration generation, catalog,
lazy-client error, registry discovery) plus the end-to-end
`ToolManager.register_toolkit()` + `execute()` integration test from the
spec's §4 Integration Tests table.

`15/15` tests pass (`python -m pytest packages/ai-parrot-tools/tests/test_lyria_toolkit.py -v`);
`ruff check` clean on all 4 new/modified files.

Two corrections to the task's suggested test code, both to keep it aligned
with the real codebase rather than assumed APIs:
- `test_parse_natural_music_request_ambient_slow` asserts
  `p.genre == "Ambient"` (a literal string) rather than
  `MusicGenre.AMBIENT.value` — `MusicGenre` has no `AMBIENT` member (see
  TASK-2921's Completion Note); `genre` is a free-form `Optional[str]`.
- The end-to-end test reads `ToolResult.result` (the actual field on
  `parrot.tools.abstract.ToolResult`), not `.data`, which does not exist.

**Addendum (post-review fixes, commit `a6aa9e4fd`)**: added a
`TestLyriaToolkitReviewFixes` class (4 tests) covering the 4 Important
findings from the adversarial code review — see TASK-2923's addendum for
details. Full suite is now 19/19 passing; ruff clean.

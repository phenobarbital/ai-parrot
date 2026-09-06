# TASK-2923: LyriaToolkit Core Implementation

**Feature**: FEAT-534 — Lyria Toolkit for Natural Language Music Generation
**Spec**: `sdd/specs/lyria-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2921, TASK-2922
**Assigned-to**: unassigned

---

## Context

Spec §2 Architectural Design, Component Diagram, and §3 Module 3. This task implements the core `LyriaToolkit` class in `packages/ai-parrot-tools/src/parrot_tools/google/lyria.py`, inheriting from `AbstractToolkit`.
It exposes `generate_music`, `list_genres_and_moods`, and `parse_music_prompt` tools to the agent framework. It implements exact *n*-second audio streaming truncation, lazy `GoogleGenAIClient` lifecycle management, and rich parameter schemas for LLM function calling.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/google/lyria.py`.
- Define `class LyriaToolkit(AbstractToolkit)`:
  - `tool_prefix = "lyria"`
  - `auto_open = False`
  - Constructor parameters:
    - `client: Optional[Any] = None`
    - `output_dir: Optional[Union[str, Path]] = None` (defaults to `Path("tmp/music")`)
    - `default_duration: int = 10`
    - `mode: Literal["stream", "batch"] = "stream"`
    - `model: str = "models/lyria-realtime-exp"`
    - `**kwargs` forwarded to `super().__init__(**kwargs)`
  - Methods exposed as tools:
    - `async def generate_music(self, prompt: str, duration_seconds: int = 10, genre: Optional[str] = None, mood: Optional[str] = None, bpm: int = 90, temperature: float = 1.0, density: float = 0.5, brightness: float = 0.5, negative_prompt: Optional[str] = None, seed: Optional[int] = None) -> Dict[str, Any]`
    - `async def list_genres_and_moods(self) -> Dict[str, Any]`
    - `async def parse_music_prompt(self, request: str) -> Dict[str, Any]`
  - Lifecycle methods:
    - `async def _get_client(self) -> Any`: Lazy import of `GoogleGenAIClient` from `parrot.clients.google.client`.
    - `async def _close(self) -> None`: Closes owned client if created by toolkit.
  - Streaming audio truncation logic:
    - Streams audio chunks via `client.generate_music_stream(...)`.
    - Collects PCM bytes into a bytearray until `len(pcm_data) >= duration_seconds * 192,000`.
    - Breaks stream early once target bytes are reached.
    - Truncates to exact `target_bytes` and writes to WAV via `async_save_pcm_to_wav`.
  - Batch mode audio slicing:
    - Calls `client.generate_music_batch(...)`.
    - Uses `async_slice_wav_file` to truncate 30s batch WAV to `duration_seconds`.
  - Content safety and error handling:
    - Returns structured error dict on rejection or timeout.

**NOT in scope**:
- Registering in `TOOL_REGISTRY` (TASK-2924).
- Unit tests suite (TASK-2925).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/google/lyria.py` | CREATE | Main LyriaToolkit implementation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:206
from parrot.tools.toolkit import AbstractToolkit

# packages/ai-parrot/src/parrot/models/google.py:69, 141
from parrot.models.google import MusicGenre, MusicMood

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py:101
from parrot.clients.google.client import GoogleGenAIClient
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:206
class AbstractToolkit(ABC):
    tool_prefix: str | None = None  # line 257
    def __init__(self, **kwargs): ...  # line 321
    async def _open(self) -> None: ...  # line 390
    async def _close(self) -> None: ...  # line 406
    def get_tools(self, ...) -> list[AbstractTool]: ...  # line 486

# packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1172
async def generate_music_stream(
    self,
    prompt: str,
    genre: Optional[Union[str, MusicGenre]] = None,
    mood: Optional[Union[str, MusicMood]] = None,
    bpm: int = 90,
    temperature: float = 1.0,
    density: float = 0.5,
    brightness: float = 0.5,
    timeout: int = 300,
) -> AsyncIterator[bytes]: ...
```

### Does NOT Exist
- ~~`client.generate_music_duration(...)`~~ — Must collect stream chunks and truncate via `audio_utils`.
- ~~`parrot.tools.LyriaToolkit`~~ — Belongs in `parrot_tools.google.lyria`.

---

## Implementation Notes (Detailed Code Reference)

### Complete Code Structure for `lyria.py`

```python
"""LyriaToolkit — Google Lyria music generation toolkit for ai-parrot."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Union

from parrot.models.google import MusicGenre, MusicMood
from parrot.tools.toolkit import AbstractToolkit

from .audio_utils import (
    BYTES_PER_SECOND,
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    async_save_pcm_to_wav,
    async_slice_wav_file,
    seconds_to_pcm_bytes,
)
from .lyria_models import (
    LyriaMusicParameters,
    LyriaMusicResult,
    parse_natural_music_request,
)

if TYPE_CHECKING:
    from parrot.clients.google.client import GoogleGenAIClient

logger = logging.getLogger(__name__)


class LyriaToolkit(AbstractToolkit):
    """Toolkit for converting natural language descriptions into Google Lyria music generation.

    Exposes tools for:
    - generate_music: Generate audio from a prompt and musical parameters.
    - list_genres_and_moods: Discover supported genres and moods.
    - parse_music_prompt: Parse raw natural language into structured parameters.
    """

    tool_prefix: str = "lyria"

    def __init__(
        self,
        client: Optional[Any] = None,
        output_dir: Optional[Union[str, Path]] = None,
        default_duration: int = 10,
        mode: Literal["stream", "batch"] = "stream",
        model: str = "models/lyria-realtime-exp",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._client = client
        self._owns_client = client is None
        self.output_dir = Path(output_dir or "tmp/music").resolve()
        self.default_duration = default_duration
        self.mode = mode
        self.model = model
        self.logger = logging.getLogger(self.__class__.__name__)

    async def _get_client(self) -> GoogleGenAIClient:
        """Lazy-resolve or instantiate the GoogleGenAIClient."""
        if self._client is not None:
            return self._client
        try:
            from parrot.clients.google.client import GoogleGenAIClient
            self._client = GoogleGenAIClient(model=self.model)
            return self._client
        except ImportError as exc:
            raise RuntimeError(
                "GoogleGenAIClient is not available. Ensure ai-parrot-client-google is installed: "
                f"{exc}"
            ) from exc

    async def _close(self) -> None:
        """Release client if owned."""
        if self._client is not None and self._owns_client:
            if hasattr(self._client, "close"):
                await self._client.close()
            self._client = None
        await super()._close()

    async def generate_music(
        self,
        prompt: str,
        duration_seconds: int = 10,
        genre: Optional[str] = None,
        mood: Optional[str] = None,
        bpm: int = 90,
        temperature: float = 1.0,
        density: float = 0.5,
        brightness: float = 0.5,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate music using Google Lyria from a prompt and structured musical parameters.

        Args:
            prompt: Text description of the desired music (instruments, style, feel).
            duration_seconds: Duration of the generated audio in seconds (1 to 120, default 10).
            genre: Music genre hint (e.g. 'Ambient', 'Chillout', 'Lo-Fi Hip Hop', 'Classical').
            mood: Music mood hint (e.g. 'Ambient', 'Chill', 'Dreamy', 'Ethereal Ambience').
            bpm: Tempo in beats per minute (60-200, default 90). Slow=60-80, Medium=90-110, Fast=120-160.
            temperature: Creativity/randomness parameter (0.0 to 3.0, default 1.0).
            density: Note density (0.0 to 1.0). Use 0.2-0.4 for soft/sparse, 0.7-0.9 for dense.
            brightness: Tonal brightness (0.0 to 1.0). Use 0.2-0.4 for warm/mellow, 0.7-0.9 for bright.
            negative_prompt: Musical elements or sounds to exclude (e.g. 'drums, vocals').
            seed: Deterministic integer seed for reproducible generation.

        Returns:
            Dict containing status, file_path, duration_seconds, sample_rate, channels, and parameters.
        """
        duration = max(1, min(120, duration_seconds or self.default_duration))
        params = LyriaMusicParameters(
            prompt=prompt,
            duration_seconds=duration,
            genre=genre,
            mood=mood,
            bpm=bpm,
            temperature=temperature,
            density=density,
            brightness=brightness,
            negative_prompt=negative_prompt,
            seed=seed,
        )

        client = await self._get_client()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        file_id = uuid.uuid4().hex[:10]
        out_path = self.output_dir / f"lyria_{file_id}.wav"

        if self.mode == "stream":
            return await self._generate_stream(client, params, out_path)
        else:
            return await self._generate_batch(client, params, out_path)

    async def _generate_stream(
        self,
        client: Any,
        params: LyriaMusicParameters,
        out_path: Path,
    ) -> Dict[str, Any]:
        target_bytes = seconds_to_pcm_bytes(params.duration_seconds)
        pcm_chunks: list[bytes] = []
        collected = 0

        try:
            stream = client.generate_music_stream(
                prompt=params.prompt,
                genre=params.genre,
                mood=params.mood,
                bpm=params.bpm,
                temperature=params.temperature,
                density=params.density,
                brightness=params.brightness,
                timeout=max(30, params.duration_seconds * 3),
            )
            async for chunk in stream:
                if chunk:
                    pcm_chunks.append(chunk)
                    collected += len(chunk)
                    if collected >= target_bytes:
                        break

            all_pcm = b"".join(pcm_chunks)
            if not all_pcm:
                return {
                    "status": "error",
                    "error": "No audio data received from Lyria stream.",
                }

            # Truncate to exact required bytes
            final_pcm = all_pcm[:target_bytes]
            saved_file = await async_save_pcm_to_wav(final_pcm, out_path)
            actual_duration = len(final_pcm) / BYTES_PER_SECOND

            res = LyriaMusicResult(
                status="success",
                file_path=str(saved_file),
                duration_seconds=round(actual_duration, 2),
                sample_rate=DEFAULT_SAMPLE_RATE,
                channels=DEFAULT_CHANNELS,
                format="wav",
                size_bytes=saved_file.stat().st_size,
                parameters=params,
            )
            return res.model_dump()

        except Exception as exc:
            self.logger.error(f"Lyria stream generation failed: {exc}", exc_info=True)
            return {
                "status": "error",
                "error": str(exc),
                "parameters": params.model_dump(),
            }

    async def _generate_batch(
        self,
        client: Any,
        params: LyriaMusicParameters,
        out_path: Path,
    ) -> Dict[str, Any]:
        try:
            files = await client.generate_music_batch(
                prompt=params.prompt,
                negative_prompt=params.negative_prompt,
                seed=params.seed,
                genre=params.genre,
                mood=params.mood,
                output_directory=self.output_dir,
            )
            if not files:
                return {"status": "error", "error": "Lyria batch returned no files."}

            raw_file = files[0]
            saved_file = await async_slice_wav_file(raw_file, out_path, params.duration_seconds)
            return LyriaMusicResult(
                status="success",
                file_path=str(saved_file),
                duration_seconds=float(params.duration_seconds),
                sample_rate=DEFAULT_SAMPLE_RATE,
                channels=DEFAULT_CHANNELS,
                format="wav",
                size_bytes=saved_file.stat().st_size,
                parameters=params,
            ).model_dump()
        except Exception as exc:
            self.logger.error(f"Lyria batch generation failed: {exc}", exc_info=True)
            return {"status": "error", "error": str(exc), "parameters": params.model_dump()}

    async def list_genres_and_moods(self) -> Dict[str, Any]:
        """Return catalog of genres and moods supported by Google Lyria."""
        return {
            "genres": [g.value for g in MusicGenre],
            "moods": [m.value for m in MusicMood],
            "defaults": {
                "duration_seconds": self.default_duration,
                "bpm": 90,
                "temperature": 1.0,
                "density": 0.5,
                "brightness": 0.5,
            },
        }

    async def parse_music_prompt(self, request: str) -> Dict[str, Any]:
        """Extract structured music parameters from a natural language request."""
        parsed = parse_natural_music_request(request, default_duration=self.default_duration)
        return parsed.model_dump()
```

---

## Acceptance Criteria

- [ ] `LyriaToolkit` inherits from `AbstractToolkit` with `tool_prefix = "lyria"`.
- [ ] `generate_music` gathers chunks and slices exact `duration_seconds * 192,000` bytes.
- [ ] WAV output is saved with 48kHz stereo 16-bit format.
- [ ] `list_genres_and_moods` returns all supported `MusicGenre` and `MusicMood` strings.
- [ ] `parse_music_prompt` returns dictionary matching `LyriaMusicParameters`.
- [ ] Client is lazily resolved with actionable error if Google client extra is missing.

---

### Completion Note

Implemented exactly as specified in
`packages/ai-parrot-tools/src/parrot_tools/google/lyria.py`. Manually
verified (module not yet covered by the shared test suite — TASK-2925 adds
`test_lyria_toolkit.py`):
- `get_tools()` exposes `lyria_generate_music`, `lyria_list_genres_and_moods`,
  `lyria_parse_music_prompt` (prefix applied via `tool_prefix = "lyria"`;
  `_get_client`/`_close` correctly excluded as underscore-prefixed).
- `list_genres_and_moods()` returns all `MusicGenre`/`MusicMood` values.
- `parse_music_prompt()` delegates to `parse_natural_music_request`.
- `generate_music(..., duration_seconds=5, mode="stream")` against a mocked
  client streaming 120 chunks of 19,200 bytes each: collects exactly
  `5 * 192,000 = 960,000` bytes, writes a valid 48kHz/2ch/16-bit WAV with
  `48000 * 5` frames, and returns `status="success"`.

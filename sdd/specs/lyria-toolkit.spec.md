---
type: feature
base_branch: dev
---

# Feature Specification: Lyria Toolkit for Natural Language Music Generation

**Feature ID**: FEAT-534
**Date**: 2026-09-06
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.0

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot supports Google Lyria music generation at the client layer via `GoogleGenAIClient` (`generate_music_stream` using the Gemini Live v1alpha WebSocket API and `generate_music_batch` using Vertex AI's `lyria-002` REST endpoint), as well as via an HTTP endpoint (`LyriaMusicHandler`). However:

1. **No Agent/Toolkit Integration**: Agents and tool-calling LLMs cannot currently invoke Lyria directly because there is no `AbstractToolkit` implementation exposing Lyria tools to the agent framework.
2. **Natural Language to Structured Music Parameters**: A user typically specifies music desires in natural language (e.g., *"a soft ambient music with slow tempo"*). Lyria requires structured musical parameters: `bpm` (beats per minute, e.g., 60–200), `genre` (e.g., "Ambient"), `mood` (e.g., "Chill", "Ambient"), `density` (0.0–1.0), `brightness` (0.0–1.0), `temperature` (0.0–3.0), and `negative_prompt`. There is no dedicated toolkit interface with schema definitions and parameter semantics that allow the LLM to cleanly translate natural expressions into these controls.
3. **Controllable Duration (`n` seconds)**: Lyria RealTime streams audio continuously while Vertex AI Lyria-002 returns fixed 30-second WAV files. Users need a reliable `n`-second output parameter (with a sensible default of 10 seconds) that accurately truncates and delivers a valid, playable WAV audio file of exactly that length.

### Goals

- Implement `LyriaToolkit` inheriting from `AbstractToolkit` in `packages/ai-parrot-tools/src/parrot_tools/google/lyria.py`.
- Expose primary tool `generate_music` with rich docstrings, parameter types, and ranges that enable agent LLMs to map free-form natural language queries (e.g., "soft ambient music with slow tempo") into structured Lyria inputs:
  - `prompt`: Refined descriptive prompt string.
  - `duration_seconds`: Desired audio duration in seconds, defaulting to `10` (range 1–120s).
  - `genre`: Hint from `MusicGenre` enum or free text.
  - `mood`: Hint from `MusicMood` enum or free text.
  - `bpm`: Integer tempo (60–200, default 90; e.g., slow=60–80, medium=90–110, fast=120–160).
  - `temperature`: Creativity float (0.0–3.0, default 1.0).
  - `density`: Note density float (0.0–1.0, default 0.5; e.g., soft/sparse=0.2–0.4).
  - `brightness`: Tonal brightness float (0.0–1.0, default 0.5; e.g., soft/warm=0.3–0.4).
  - `negative_prompt`: Optional unwanted musical elements.
  - `seed`: Optional deterministic seed.
- Expose discovery tool `list_genres_and_moods` returning cataloged genres and moods from `MusicGenre` and `MusicMood` for agent inspection.
- Provide a heuristic/NLP helper `parse_music_prompt` to extract structured parameters from raw text when invoked outside of an agent function-calling loop.
- Deliver exact `n`-second duration handling:
  - For streaming (`models/lyria-realtime-exp`): Collect 48kHz 16-bit stereo PCM audio (`duration_seconds * 192,000` bytes), stop receiver task, and encode into a valid WAV file using Python's standard `wave` library.
  - For batch (`lyria-002`): Trim returned 30-second WAV to `n` seconds of frames (`duration_seconds * 48,000` frames).
- Register `LyriaToolkit` in `parrot_tools` discovery (`TOOL_REGISTRY["google_lyria"]`, `TOOL_REGISTRY["lyria"]`).
- Support lazy client instantiation with `GoogleGenAIClient` from `parrot.clients.google.client`, adhering to optional dependency isolation rules.

### Non-Goals (explicitly out of scope)

- Modifying existing `GoogleGenAIClient.generate_music_stream` or `GoogleGenAIClient.generate_music_batch` core signatures.
- Implementing local audio DSP filters, equalization, or MP3/OGG transcode pipelines (standard WAV container is sufficient and universally compatible).
- Replacing or refactoring `LyriaMusicHandler` in `ai-parrot-server`.
- Multimodal audio-to-audio prompting (Lyria 3 features pending public general availability).

---

## 2. Architectural Design

### Overview

`LyriaToolkit` subclasses `AbstractToolkit` (`packages/ai-parrot/src/parrot/tools/toolkit.py`) under namespace `lyria` (`tool_prefix = "lyria"`).

When registered with an agent (`ToolManager`), `LyriaToolkit` automatically publishes its public coroutine methods as tools with JSON schemas inferred from Python type hints and Google-style docstrings. When the user says *"generate a soft ambient music with slow tempo for 15 seconds"*, the agent LLM selects `lyria_generate_music`, maps *"slow tempo"* to `bpm=70`, *"soft ambient"* to `genre="Ambient", mood="Ambient", density=0.3, brightness=0.4`, and sets `duration_seconds=15`.

```
User Prompt: "a soft ambient music with slow tempo"
      │
      ▼
Agent LLM (Function Calling)
      │
      │ maps to tool arguments:
      │   prompt = "soft ambient music"
      │   duration_seconds = 10 (default)
      │   genre = "Ambient"
      │   mood = "Chill"
      │   bpm = 70
      │   density = 0.3
      ▼
LyriaToolkit.generate_music(...)
      │
      ├─► Calls GoogleGenAIClient.generate_music_stream(...) [or batch]
      │   ├── Receives 48kHz 16-bit stereo PCM stream
      │   └── Collects duration_seconds * 192,000 bytes
      │
      ├─► wav_utils.save_pcm_to_wav(...)
      │   └── Wraps PCM into WAV container via stdlib wave module
      │
      ▼
Output: Dict[str, Any]
  {
    "status": "success",
    "file_path": "/tmp/music/lyria_abc123.wav",
    "duration_seconds": 10.0,
    "sample_rate": 48000,
    "channels": 2,
    "format": "wav",
    "size_bytes": 1920044,
    "parameters": { ... }
  }
```

### Component Diagram

```
┌────────────────────────────────────────────────────────────┐
│                    ai-parrot Agent Loop                    │
└─────────────────────────────┬──────────────────────────────┘
                              │
                              ▼ Tool Execution
┌────────────────────────────────────────────────────────────┐
│         parrot_tools.google.lyria.LyriaToolkit             │
│  Inherits from AbstractToolkit                             │
│  - tool_prefix = "lyria"                                   │
│  Methods:                                                  │
│    * generate_music(prompt, duration_seconds=10, ...)      │
│    * list_genres_and_moods()                               │
│    * parse_music_prompt(request)                           │
└──────────────┬───────────────────────────────┬─────────────┘
               │                               │
               ▼                               ▼
┌───────────────────────────────┐ ┌──────────────────────────┐
│ parrot.models.google          │ │ GoogleGenAIClient        │
│ - MusicGenre                  │ │ (parrot.clients.google)  │
│ - MusicMood                   │ │                          │
│ - MusicGenerationRequest      │ │ - generate_music_stream  │
│ - LyriaModel                  │ │ - generate_music_batch   │
└───────────────────────────────┘ └────────────┬─────────────┘
                                               │
                                               ▼
                              ┌──────────────────────────────┐
                              │ Google GenAI / Vertex AI     │
                              │ - models/lyria-realtime-exp  │
                              │ - lyria-002:predict          │
                              └──────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | inherits | `packages/ai-parrot/src/parrot/tools/toolkit.py:206` |
| `GoogleGenAIClient` | delegates to | `packages/ai-parrot-client-google/src/parrot/clients/google/client.py:101` (lazy imported) |
| `MusicGenre` & `MusicMood` | uses | `packages/ai-parrot/src/parrot/models/google.py:69,141` |
| `MusicGenerationRequest` | references | `packages/ai-parrot/src/parrot/models/google.py:177` |
| `TOOL_REGISTRY` | registers | `packages/ai-parrot-tools/src/parrot_tools/__init__.py:12` |
| Python `wave` module | uses | Standard library WAV encoding and framing |

### Data Models

```python
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

from parrot.models.google import MusicGenre, MusicMood


class LyriaMusicParameters(BaseModel):
    """Structured parameters for a Lyria music generation call."""

    prompt: str = Field(..., description="Text description of the desired music.")
    duration_seconds: int = Field(
        default=10,
        ge=1,
        le=120,
        description="Duration of the generated audio in seconds (default: 10).",
    )
    genre: Optional[str] = Field(None, description="Musical genre hint.")
    mood: Optional[str] = Field(None, description="Musical mood hint.")
    bpm: int = Field(
        default=90,
        ge=60,
        le=200,
        description="Tempo in beats per minute (60-200). Slow=60-80, Medium=90-110, Fast=120-160.",
    )
    temperature: float = Field(
        default=1.0,
        ge=0.0,
        le=3.0,
        description="Generation creativity/randomness (0.0-3.0).",
    )
    density: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Note density (0.0-1.0). Sparse/soft=0.2-0.4, Dense=0.7-0.9.",
    )
    brightness: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Tonal brightness (0.0-1.0). Warm/dark=0.2-0.4, Bright=0.7-0.9.",
    )
    negative_prompt: Optional[str] = Field(
        default=None,
        description="Elements to exclude from generation (e.g. 'drums, vocals, heavy distortion').",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Deterministic seed for reproducible generation.",
    )


class LyriaMusicResult(BaseModel):
    """Output descriptor returned after successful music generation."""

    status: Literal["success", "error"] = "success"
    file_path: str = Field(..., description="Absolute path to generated WAV file.")
    duration_seconds: float = Field(..., description="Actual duration of generated audio.")
    sample_rate: int = Field(default=48000, description="Audio sample rate in Hz.")
    channels: int = Field(default=2, description="Channel count (2 for stereo).")
    format: str = Field(default="wav", description="Audio container format.")
    size_bytes: int = Field(..., description="Size of the audio file in bytes.")
    parameters: LyriaMusicParameters = Field(..., description="Applied parameters.")
```

### New Public Interfaces

```python
class LyriaToolkit(AbstractToolkit):
    """Toolkit for AI-driven music generation using Google Lyria.

    Exposes tools for generating music from natural language descriptions,
    cataloging supported genres/moods, and mapping free-form natural language
    cues into structured parameters for Lyria.
    """

    tool_prefix: str = "lyria"

    def __init__(
        self,
        client: Optional[Any] = None,
        output_dir: Optional[Union[str, Path]] = None,
        default_duration: int = 10,
        mode: Literal["stream", "batch"] = "stream",
        **kwargs: Any,
    ) -> None:
        ...

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
        """Generate audio music from a prompt and musical parameters via Google Lyria.

        The LLM should translate natural language descriptions into these structured parameters:
        - prompt: Refined descriptive text for the music.
        - duration_seconds: Duration in seconds to generate (default 10).
        - genre: Music genre (e.g., 'Ambient', 'Chillout', 'Classical', 'Lo-Fi Hip Hop').
        - mood: Mood description (e.g., 'Ambient', 'Chill', 'Dreamy', 'Ethereal Ambience').
        - bpm: Tempo in beats per minute (60-200). Use 60-80 for slow tempo, 90-110 for medium, 120-160 for fast.
        - density: Note density (0.0-1.0). Use 0.2-0.4 for soft/sparse, 0.7-0.9 for dense.
        - brightness: Tonal brightness (0.0-1.0). Use 0.2-0.4 for warm/mellow, 0.7-0.9 for bright.
        """
        ...

    async def list_genres_and_moods(self) -> Dict[str, Any]:
        """Return the catalog of genres and moods supported by Google Lyria."""
        ...

    async def parse_music_prompt(self, request: str) -> Dict[str, Any]:
        """Parse a natural language request into structured Lyria parameters."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Data Models & Prompt Heuristics
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/google/lyria_models.py`
- **Responsibility**: Define `LyriaMusicParameters`, `LyriaMusicResult`, duration bounds, and natural language heuristic parsing (`parse_natural_music_request`) that maps keywords like "slow tempo" -> `bpm=70`, "soft" -> `density=0.3`, "ambient" -> `genre="Ambient", mood="Ambient"`.
- **Depends on**: `parrot.models.google` (`MusicGenre`, `MusicMood`).

### Module 2: Audio Extraction & WAV Framing Engine
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/google/audio_utils.py`
- **Responsibility**:
  - `save_pcm_to_wav(pcm_bytes, output_path, sample_rate=48000, channels=2, sample_width=2)` using stdlib `wave`.
  - `slice_wav_file(input_path, output_path, target_seconds)` using stdlib `wave` for batch mode.
  - Byte duration calculation helpers (`seconds_to_pcm_bytes(seconds, sample_rate=48000, channels=2, sample_width=2) -> int`).
- **Depends on**: Python standard library `wave`, `pathlib`.

### Module 3: `LyriaToolkit` Implementation
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/google/lyria.py`
- **Responsibility**: Implement `LyriaToolkit(AbstractToolkit)`:
  - `tool_prefix = "lyria"`
  - `generate_music`: Validates parameters, executes generation (streaming chunks up to `duration_seconds * 192,000` bytes or batch), packages into WAV, returns structured result dict.
  - `list_genres_and_moods`: Returns catalog.
  - `parse_music_prompt`: Exposes heuristic parser.
  - Lifecycle: `_open()`, `_close()` for client management.
- **Depends on**: Module 1, Module 2, `parrot.tools.toolkit.AbstractToolkit`, `parrot.clients.google.GoogleGenAIClient` (lazy imported).

### Module 4: Discovery & Package Registration
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py`, `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
- **Responsibility**:
  - Export `LyriaToolkit` from `parrot_tools.google`.
  - Register `"google_lyria"` and `"lyria"` in `TOOL_REGISTRY`.
- **Depends on**: Module 3.

### Module 5: Test Suite
- **Path**: `packages/ai-parrot-tools/tests/google/test_lyria_toolkit.py`
- **Responsibility**: Unit tests with mocked `GoogleGenAIClient`:
  - Parameter validation and defaults (10s default duration).
  - Exact `n`-second PCM slice calculation (10s = 1,920,000 bytes at 48kHz 16-bit stereo).
  - WAV header verification (valid RIFF/WAVE header, 48kHz, 2 channels, 16-bit).
  - Natural language heuristic extraction ("soft ambient music with slow tempo").
  - `list_genres_and_moods` catalog return.
  - Graceful handling of empty prompts, invalid BPM, timeouts, and safety blocks.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_lyria_parameters_defaults` | Module 1 | Default duration is 10s, bpm=90, temperature=1.0, density=0.5, brightness=0.5 |
| `test_lyria_parameters_validation` | Module 1 | Rejects duration < 1 or > 120, bpm < 60 or > 200, density < 0 or > 1 |
| `test_parse_natural_music_request` | Module 1 | Maps "soft ambient music with slow tempo" -> bpm=70, density=0.3, genre/mood="Ambient" |
| `test_save_pcm_to_wav` | Module 2 | Creates valid WAV file with correct sample rate (48000), stereo channels (2), and 16-bit PCM |
| `test_slice_wav_file` | Module 2 | Correctly truncates 30s WAV to exact `n` seconds of audio frames |
| `test_lyria_toolkit_tools_generated` | Module 3 | `get_tools()` exposes `lyria_generate_music`, `lyria_list_genres_and_moods`, `lyria_parse_music_prompt` |
| `test_generate_music_streaming_success` | Module 3 | Streams chunks, terminates once 10s of PCM bytes are gathered, saves WAV |
| `test_generate_music_custom_duration` | Module 3 | User-supplied `duration_seconds=5` gathers exactly 5 * 192,000 bytes = 960,000 bytes |
| `test_generate_music_batch_mode` | Module 3 | Calls `generate_music_batch` and slices WAV output to specified `duration_seconds` |
| `test_list_genres_and_moods` | Module 3 | Returns non-empty list of genres and moods matching `MusicGenre` and `MusicMood` |
| `test_discovery_registry` | Module 4 | `TOOL_REGISTRY["lyria"]`, `TOOL_REGISTRY["google_lyria"]`, resolve to `LyriaToolkit` |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_agent_tool_calling` | Registers `LyriaToolkit` in `ToolManager`, executes `lyria_generate_music` with mock client, verifies resulting WAV on disk |

### Test Data / Fixtures

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_pcm_chunk():
    """100ms of silence in 48kHz 16-bit stereo PCM (48000 * 2 * 2 * 0.1 = 19,200 bytes)."""
    return b" " * 19200


@pytest.fixture
def mock_google_client(mock_pcm_chunk):
    """Mock GoogleGenAIClient yielding PCM chunks."""
    client = MagicMock()

    async def fake_stream(*args, **kwargs):
        for _ in range(120):  # Plenty of chunks
            yield mock_pcm_chunk

    client.generate_music_stream = fake_stream
    return client
```

---

## 5. Acceptance Criteria

- [ ] `LyriaToolkit` exists at `packages/ai-parrot-tools/src/parrot_tools/google/lyria.py` and inherits from `AbstractToolkit`.
- [ ] `generate_music` tool accepts `prompt: str`, `duration_seconds: int = 10` (default 10), `genre`, `mood`, `bpm`, `temperature`, `density`, `brightness`, `negative_prompt`, `seed`.
- [ ] Natural request prompt parsing heuristic converts `"a soft ambient music with slow tempo"" into structured Lyria inputs with slow BPM (60–80), soft density (0.2–0.4), and ambient mood/genre.
- [ ] Generated audio output is truncated to exact `n` seconds of 48kHz 16-bit stereo audio (`duration_seconds * 192,000` PCM bytes) and saved as a valid WAV file.
- [ ] Tool returns structured result dict containing `file_path`, `duration_seconds`, `sample_rate`, `channels`, `size_bytes`, and `parameters`.
- [ ] `list_genres_and_moods` tool returns available `MusicGenre` and `MusicMood` options.
- [ ] Registered under `TOOL_REGISTRY["lyria"]`, `TOOL_REGISTRY["google_lyria"]`.
- [ ] Lazy import protects against missing `google-genai` / `ai-parrot-client-google` package at module import time.
- [ ] All unit and integration tests pass with 100% assertions satisfied.
- [ ] No breaking changes to existing `GoogleGenAIClient` or `LyriaMusicHandler`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> The following paths, line numbers, and signatures have been verified in the codebase.

### Verified Imports

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:206
from parrot.tools.toolkit import AbstractToolkit

# packages/ai-parrot/src/parrot/models/google.py:69, 141, 177, 190
from parrot.models.google import (
    MusicGenre,
    MusicMood,
    MusicGenerationRequest,
    LyriaModel,
)

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py:101
from parrot.clients.google.client import GoogleGenAIClient

# packages/ai-parrot-tools/src/parrot_tools/__init__.py:12
from parrot_tools import TOOL_REGISTRY
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:206
class AbstractToolkit(ABC):
    input_class: type[BaseModel] | None = None  # line 234
    return_direct: bool = False  # line 235
    tool_prefix: str | None = None  # line 257
    prefix_separator: str = "_"  # line 260
    auto_open: bool = False  # line 319
    def __init__(self, **kwargs): ...  # line 321
    def get_tools(self, ...): ...  # line 486
    def _create_tool_from_method(self, name: str, method: Callable) -> ToolkitTool: ...  # line 603

# packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:60
class GoogleGeneration:
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
    ) -> AsyncIterator[bytes]: ...  # line 1172

    async def generate_music_batch(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        sample_count: int = 1,
        output_directory: Optional[Union[str, Path]] = None,
        genre: Optional[Union[str, MusicGenre]] = None,
        mood: Optional[Union[str, MusicMood]] = None,
        timeout: int = 120,
    ) -> List[Path]: ...  # line 1342

# packages/ai-parrot/src/parrot/models/google.py:69, 141
class MusicGenre(str, Enum): ...  # line 69
class MusicMood(str, Enum): ...  # line 141
class MusicGenerationRequest(BaseModel): ...  # line 177
class LyriaModel(str, Enum): ...  # line 190
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `LyriaToolkit` | `AbstractToolkit` | Subclass inheritance | `packages/ai-parrot/src/parrot/tools/toolkit.py:206` |
| `LyriaToolkit.generate_music` | `GoogleGenAIClient.generate_music_stream` | Coroutine call & async iteration | `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1172` |
| `LyriaToolkit.generate_music` | `GoogleGenAIClient.generate_music_batch` | Method call | `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1342` |
| `LyriaToolkit.list_genres_and_moods` | `MusicGenre`, `MusicMood` | Enum iteration | `packages/ai-parrot/src/parrot/models/google.py:69,141` |
| `parrot_tools/__init__.py` | `LyriaToolkit` | `TOOL_REGISTRY` entry | `packages/ai-parrot-tools/src/parrot_tools/__init__.py:12` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.lyria`~~ — Does not exist yet; will be created.
- ~~`parrot_tools.google.lyria.LyriaToolkit`~~ — Does not exist yet; will be created.
- ~~`GoogleGenAIClient.generate_music_seconds`~~ — Does not exist; chunk accumulation to `n * 192,000` bytes is handled in `LyriaToolkit`.
- ~~`parrot.tools.LyriaToolkit`~~ — Third-party vendor toolkits belong in `parrot_tools`, not `parrot.tools` core.
- ~~`MusicGenerationRequest.duration_seconds`~~ — Existing model only has `timeout`; `duration_seconds` is managed by `LyriaMusicParameters`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`AbstractToolkit` Inheritance**: Methods become tools automatically. Docstrings must follow Google style because `_create_tool_from_method` extracts argument descriptions from docstring Google blocks.
- **Async-First & Non-Blocking**: Audio streaming and writing run asynchronously. File operations use non-blocking patterns or thread pool if necessary (`asyncio.to_thread` for disk write).
- **PCM Byte Calculation**:
  - Sample rate: 48,000 Hz
  - Channels: 2 (stereo)
  - Bit depth: 16-bit PCM (2 bytes/sample)
  - 1 second = 48,000 * 2 * 2 = 192,000 bytes
  - `n` seconds = `n * 192,000` bytes.
- **Standard Library `wave`**: Python's built-in `wave` module generates clean RIFF/WAVE containers without external heavy binary dependencies like ffmpeg.
- **Lazy Imports**: `GoogleGenAIClient` must only be imported inside methods or under `TYPE_CHECKING` so `parrot_tools` can load without requiring `ai-parrot-client-google` to be installed.

### Known Risks / Gotchas

- **Network Stalls during Stream**: If Google Lyria stream stalls before `n` seconds are reached, the toolkit uses a timeout loop and flushes the partially gathered audio rather than hanging indefinitely.
- **Safety Policy Blocks**: Lyria can return empty audio or content safety rejection (status 400). The toolkit must detect this and raise a clean `RuntimeError` or return error status dict.
- **Concurrent Tool Calls**: When multiple tools from the toolkit are executed concurrently, `_open_lock` in `AbstractToolkit` prevents double-initialization.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `ai-parrot` | `>=0.29.0` | Core toolkit classes and models |
| `ai-parrot-tools` | workspace | Host package for the toolkit |
| `ai-parrot-client-google` | workspace (optional) | Lyria client implementation |
| `wave` | Python stdlib | PCM to WAV container generation |

---

## 8. Worktree Strategy

- Flow type: `feature`
- Base branch: `dev`
- Isolation: `per-spec` (`.claude/worktrees/feat-FEAT-534-lyria-toolkit`)
- Task breakdown: Atomic tasks decomposing Models, Audio Utils, LyriaToolkit, Discovery, and Tests.

---

## 9. Open Questions

- [x] Should `LyriaToolkit` support both streaming (`models/lyria-realtime-exp`) and batch (`lyria-002`) modes? — *Owner: Jesus Lara*
  - **Resolution**: Yes. Streaming is the default because it allows immediate cancellation once `n` seconds of PCM are gathered. Batch mode is supported as an option (`mode="batch"`).
- [x] What default duration should be applied if the user prompt omits seconds? — *Owner: Jesus Lara*
  - **Resolution**: 10 seconds, as requested in prompt.
- [x] Where should the generated audio files be saved? — *Owner: Jesus Lara*
  - **Resolution**: Default to `Path("tmp/music")` (created automatically) or a custom `output_dir` passed to `LyriaToolkit(__init__)`, returning the absolute path in the tool response.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-06 | Jesus Lara | Initial draft specification for FEAT-534 |

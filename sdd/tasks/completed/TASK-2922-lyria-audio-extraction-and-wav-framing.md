# TASK-2922: Lyria Audio Extraction and WAV Framing Engine

**Feature**: FEAT-534 — Lyria Toolkit for Natural Language Music Generation
**Spec**: `sdd/specs/lyria-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Architectural Design and §3 Module 2. Google Lyria streams audio as raw 48kHz 16-bit stereo PCM chunks, while Lyria batch produces 30-second WAV files. To satisfy the requirement of returning exact *n*-second music files, this task builds the audio extraction and WAV framing utility in `packages/ai-parrot-tools/src/parrot_tools/google/audio_utils.py`. It uses Python standard library `wave` (no heavy third-party C binaries or ffmpeg required).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/google/audio_utils.py`.
- Implement `seconds_to_pcm_bytes(seconds: float, sample_rate: int = 48000, channels: int = 2, sample_width: int = 2) -> int`:
  - Formula: `int(seconds * sample_rate * channels * sample_width)`.
  - For 10s: `10 * 48000 * 2 * 2 = 1,920,000` bytes.
- Implement `save_pcm_to_wav(pcm_bytes: bytes, output_path: Union[str, Path], sample_rate: int = 48000, channels: int = 2, sample_width: int = 2) -> Path`:
  - Writes PCM data to output path with standard RIFF/WAVE header.
  - Ensures parent directories exist.
  - Returns `Path(output_path).resolve()`.
- Implement `slice_wav_file(input_wav: Union[str, Path], output_wav: Union[str, Path], target_seconds: float) -> Path`:
  - Opens `input_wav`, reads headers (`framerate`, `nchannels`, `sampwidth`).
  - Computes `target_frames = int(target_seconds * framerate)`.
  - Reads `target_frames` from input and writes them into `output_wav`.
  - Returns `Path(output_wav).resolve()`.
- Implement async wrappers:
  - `async def async_save_pcm_to_wav(...) -> Path` via `asyncio.to_thread`.
  - `async def async_slice_wav_file(...) -> Path` via `asyncio.to_thread`.

**NOT in scope**:
- Direct Google API calls (TASK-2923).
- Pydantic models (TASK-2921).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/google/audio_utils.py` | CREATE | WAV packaging, PCM byte calculation, and audio slicing |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
import io
from pathlib import Path
from typing import Union
import wave
```

### Existing Patterns in Codebase
```python
# packages/ai-parrot/src/parrot/clients/base.py:2563
# Reference: Existing WAV header writer uses wave.open with setsampwidth, setframerate, setnchannels
def _save_audio_file(self, audio_data: bytes, output_path: Path, mime_format: str):
    import wave
    with wave.open(str(output_path), mode="wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(audio_data)
```

### Does NOT Exist
- ~~`scipy.io.wavfile`~~ — Not installed as mandatory dependency; use stdlib `wave`.
- ~~`pydub.AudioSegment`~~ — Optional extra; use stdlib `wave` for core PCM/WAV framing to avoid missing dependency failures.

---

## Implementation Notes (Detailed Code Reference)

### Complete Code Structure for `audio_utils.py`

```python
"""Audio utilities for Google Lyria PCM streaming and WAV framing."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Union
import wave


#: Lyria RealTime audio stream parameters
DEFAULT_SAMPLE_RATE = 48000  # 48 kHz
DEFAULT_CHANNELS = 2         # Stereo
DEFAULT_SAMPLE_WIDTH = 2     # 16-bit PCM (2 bytes per sample per channel)

#: Byte rate per second = 48,000 * 2 * 2 = 192,000 bytes/sec
BYTES_PER_SECOND = DEFAULT_SAMPLE_RATE * DEFAULT_CHANNELS * DEFAULT_SAMPLE_WIDTH


def seconds_to_pcm_bytes(
    seconds: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_width: int = DEFAULT_SAMPLE_WIDTH,
) -> int:
    """Calculate required PCM bytes for a given duration in seconds.

    Args:
        seconds: Target duration in seconds.
        sample_rate: Audio sampling frequency in Hz (default: 48000).
        channels: Channel count (default: 2 for stereo).
        sample_width: Bytes per sample per channel (default: 2 for 16-bit).

    Returns:
        Total bytes representing the duration.
    """
    if seconds <= 0:
        return 0
    return int(seconds * sample_rate * channels * sample_width)


def pcm_bytes_to_seconds(
    byte_count: int,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_width: int = DEFAULT_SAMPLE_WIDTH,
) -> float:
    """Calculate audio duration in seconds from raw PCM byte count."""
    frame_size = channels * sample_width
    if frame_size == 0 or sample_rate == 0:
        return 0.0
    return byte_count / (sample_rate * frame_size)


def save_pcm_to_wav(
    pcm_bytes: bytes,
    output_path: Union[str, Path],
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_width: int = DEFAULT_SAMPLE_WIDTH,
) -> Path:
    """Package raw PCM bytes into a valid RIFF/WAVE file on disk.

    Args:
        pcm_bytes: Raw PCM audio bytes.
        output_path: Target file path (will ensure .wav extension).
        sample_rate: Sample rate in Hz (default 48000).
        channels: Number of channels (default 2 for stereo).
        sample_width: Bytes per sample (default 2 for 16-bit).

    Returns:
        Resolved Path to written WAV file.
    """
    target = Path(output_path).resolve()
    if target.suffix.lower() != ".wav":
        target = target.with_suffix(".wav")

    target.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(target), mode="wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.setcomptype("NONE", "not compressed")
        wf.writeframes(pcm_bytes)

    return target


def slice_wav_file(
    input_wav: Union[str, Path],
    output_wav: Union[str, Path],
    target_seconds: float,
) -> Path:
    """Truncate an existing WAV file to exactly target_seconds.

    Args:
        input_wav: Path to source WAV file.
        output_wav: Destination path for truncated WAV.
        target_seconds: Desired duration in seconds.

    Returns:
        Resolved Path to truncated output WAV file.
    """
    src = Path(input_wav).resolve()
    dst = Path(output_wav).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(src), "rb") as r_wf:
        params = r_wf.getparams()
        framerate = r_wf.getframerate()
        target_frames = int(target_seconds * framerate)
        frames = r_wf.readframes(target_frames)

    with wave.open(str(dst), "wb") as w_wf:
        w_wf.setparams(params)
        w_wf.writeframes(frames)

    return dst


async def async_save_pcm_to_wav(
    pcm_bytes: bytes,
    output_path: Union[str, Path],
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_width: int = DEFAULT_SAMPLE_WIDTH,
) -> Path:
    """Non-blocking async wrapper around save_pcm_to_wav."""
    return await asyncio.to_thread(
        save_pcm_to_wav,
        pcm_bytes,
        output_path,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )


async def async_slice_wav_file(
    input_wav: Union[str, Path],
    output_wav: Union[str, Path],
    target_seconds: float,
) -> Path:
    """Non-blocking async wrapper around slice_wav_file."""
    return await asyncio.to_thread(
        slice_wav_file,
        input_wav,
        output_wav,
        target_seconds,
    )
```

---

## Acceptance Criteria

- [ ] `seconds_to_pcm_bytes(10.0)` returns `1920000`.
- [ ] `save_pcm_to_wav` writes a valid WAV file readable by `wave.open`.
- [ ] Written WAV file has 48,000 Hz, 2 channels, 16-bit (sample width 2).
- [ ] `slice_wav_file` truncates audio correctly without header corruption.
- [ ] `async_save_pcm_to_wav` and `async_slice_wav_file` coroutines execute via `asyncio.to_thread` without blocking the event loop.

---

### Completion Note

Implemented exactly as specified in
`packages/ai-parrot-tools/src/parrot_tools/google/audio_utils.py`. Manually
verified (module not yet covered by the shared test suite — TASK-2925 adds
`test_lyria_toolkit.py`):
- `seconds_to_pcm_bytes(10.0) == 1920000`, `seconds_to_pcm_bytes(1.0) == 192000`.
- `save_pcm_to_wav` produces a WAV readable by `wave.open` with 48000 Hz,
  2 channels, sample width 2.
- `slice_wav_file` truncates a 3s PCM WAV down to exactly 1s (48000 frames)
  without header corruption.
- `async_save_pcm_to_wav`/`async_slice_wav_file` run correctly via
  `asyncio.to_thread`.

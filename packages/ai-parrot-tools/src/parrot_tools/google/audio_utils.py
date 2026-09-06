"""Audio utilities for Google Lyria PCM streaming and WAV framing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Union
import wave


#: Lyria RealTime audio stream parameters
DEFAULT_SAMPLE_RATE = 48000  # 48 kHz
DEFAULT_CHANNELS = 2  # Stereo
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit PCM (2 bytes per sample per channel)

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
    """Calculate audio duration in seconds from raw PCM byte count.

    Args:
        byte_count: Number of raw PCM bytes.
        sample_rate: Audio sampling frequency in Hz (default: 48000).
        channels: Channel count (default: 2 for stereo).
        sample_width: Bytes per sample per channel (default: 2 for 16-bit).

    Returns:
        Duration in seconds represented by the given byte count.
    """
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
    """Non-blocking async wrapper around :func:`save_pcm_to_wav`.

    Args:
        pcm_bytes: Raw PCM audio bytes.
        output_path: Target file path (will ensure .wav extension).
        sample_rate: Sample rate in Hz (default 48000).
        channels: Number of channels (default 2 for stereo).
        sample_width: Bytes per sample (default 2 for 16-bit).

    Returns:
        Resolved Path to written WAV file.
    """
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
    """Non-blocking async wrapper around :func:`slice_wav_file`.

    Args:
        input_wav: Path to source WAV file.
        output_wav: Destination path for truncated WAV.
        target_seconds: Desired duration in seconds.

    Returns:
        Resolved Path to truncated output WAV file.
    """
    return await asyncio.to_thread(
        slice_wav_file,
        input_wav,
        output_wav,
        target_seconds,
    )

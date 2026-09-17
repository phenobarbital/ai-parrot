"""Managed-process media assembly (FEAT-564, spec module M6).

Runs the actual MoviePy encode in a separate OS process — never a thread —
so cancellation can genuinely terminate in-progress encoding, per repository
convention ("new CPU-bound media work uses a managed process"). The worker
process is pure, blocking MoviePy code; ``assemble_reel()`` is the only
public entry point, and it owns the process's full lifecycle (start,
result handoff via a queue, and termination on timeout/cancellation).

Verified codec findings (offline, real ``ffmpeg``/MoviePy 2.1.2 probes in
this environment — not guessed, see this task's Completion Note for the
full diagnostic trail):

- MoviePy's ``audio_codec="libopus"`` write silently produces a ZERO-BYTE
  file unless the audio sample rate is one Opus actually supports (8000,
  12000, 16000, 24000 or 48000 Hz) — 44100 Hz (AAC's usual default) fails
  with no error raised. WebM/Opus output therefore forces ``audio_fps``
  to 48000.
- MoviePy's internal codec→extension lookup table has no entry for
  ``"libopus"`` at all, so ``write_videofile`` raises
  ``ValueError: The audio_codec you chose is unknown by MoviePy`` unless an
  explicit ``temp_audiofile`` path with a recognized extension (``.ogg``) is
  supplied, bypassing that lookup.
"""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing
import queue
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from .timeline import TimelinePlan

AudioMode = Literal["separate", "native", "muted"]

# Verified via real ffmpeg/MoviePy probes in this environment (see module
# docstring) — never invented. Opus requires one of its legal sample rates;
# 48000 is the one this feature's music service also verifies from the wire
# (reel/music.py), so reusing it here is consistent, not coincidental.
_CODEC_BY_FORMAT = {
    "mp4": {"codec": "libx264", "audio_codec": "aac", "audio_fps": None},
    "webm": {"codec": "libvpx", "audio_codec": "libopus", "audio_fps": 48000},
}

_RESULT_POLL_SECONDS = 0.5
_WORKER_JOIN_TIMEOUT_SECONDS = 10.0
_WORKER_KILL_JOIN_TIMEOUT_SECONDS = 5.0


class AssemblyFailure(Exception):
    """Raised when the managed assembly process fails or its deadline elapses."""


async def assemble_reel(
    plan: TimelinePlan,
    *,
    music_path: Optional[Path],
    audio_mode: AudioMode,
    output_format: Literal["mp4", "webm"],
    work_dir: Path,
    deadline: float,
) -> Path:
    """Assembles the final reel video in a managed (spawned) process.

    Trims every clip to its planned edit duration, applies the planned
    crossfade overlap, and wires audio per ``audio_mode``: ``"native"`` keeps
    each clip's own audio untouched; ``"separate"`` strips it and attaches
    narration (padded with silence to the segment's duration, never
    stretched) plus background music aligned to the final assembled length;
    ``"muted"`` emits no audio track at all.

    Args:
        plan: The explicit timeline plan (TASK-3328) to assemble.
        music_path: Background music WAV path, used only when
            ``audio_mode == "separate"``.
        audio_mode: ``"separate"``, ``"native"`` or ``"muted"``.
        output_format: ``"mp4"`` (H.264/AAC) or ``"webm"`` (VP8/Opus).
        work_dir: Per-job working directory the output file is written into
            (caller-owned; never deleted by this function).
        deadline: Absolute ``time.monotonic()``-comparable deadline for the
            whole assembly.

    Returns:
        The path to the assembled output file, inside ``work_dir``.

    Raises:
        ValueError: Unsupported ``output_format``.
        AssemblyFailure: The managed process failed, produced no result, or
            the deadline elapsed before it finished.
        asyncio.CancelledError: Propagated unchanged — the managed process
            is terminated and joined first.
    """
    if output_format not in _CODEC_BY_FORMAT:
        raise ValueError(f"Unsupported output_format: {output_format!r}")

    await asyncio.get_running_loop().run_in_executor(None, lambda: work_dir.mkdir(parents=True, exist_ok=True))
    output_path = work_dir / f"final_reel_{uuid.uuid4().hex}.{output_format}"

    segments_payload = [
        {
            "scene_index": s.scene_index,
            "clip_path": str(s.clip_path),
            "edit_seconds": s.edit_seconds,
            "narration_path": str(s.narration_path) if s.narration_path else None,
            "overlap_with_next_seconds": s.overlap_with_next_seconds,
        }
        for s in plan.segments
    ]

    ctx = multiprocessing.get_context("spawn")
    result_queue: "multiprocessing.Queue" = ctx.Queue()
    process = ctx.Process(
        target=_assembly_worker,
        args=(
            segments_payload,
            str(music_path) if music_path else None,
            audio_mode,
            output_format,
            str(output_path),
            result_queue,
        ),
        daemon=True,
    )
    process.start()

    try:
        loop = asyncio.get_running_loop()
        status = payload = None
        remaining_budget = max(0.1, deadline - time.monotonic())
        start = time.monotonic()
        while True:
            if time.monotonic() - start > remaining_budget:
                raise AssemblyFailure(f"Assembly timed out after {remaining_budget:.1f}s.")
            try:
                # Polled in small bounded slices (never one giant blocking
                # wait): if this coroutine is cancelled, the executor thread
                # underneath unblocks within one slice, not up to the full
                # remaining deadline — a cancelled call must not leave a
                # long-lived orphaned thread behind.
                status, payload = await loop.run_in_executor(
                    None, _get_with_timeout, result_queue, _RESULT_POLL_SECONDS
                )
                break
            except queue.Empty:
                continue
    except asyncio.CancelledError:
        _terminate_and_join(process)
        raise
    else:
        _terminate_and_join(process)

    if status == "error":
        raise AssemblyFailure(payload)
    return Path(payload)


def _get_with_timeout(result_queue: "multiprocessing.Queue", timeout: float):
    """Blocking helper run in an executor thread: ``queue.get`` with a real timeout."""
    return result_queue.get(block=True, timeout=timeout)


def _terminate_and_join(process: "multiprocessing.Process") -> None:
    """Terminates the worker if still running, then joins it (escalating to kill if needed).

    Always called before ``assemble_reel`` returns or re-raises — on
    success, failure, timeout AND cancellation — so the worker process is
    never leaked.
    """
    if process.is_alive():
        process.terminate()
    process.join(timeout=_WORKER_JOIN_TIMEOUT_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(timeout=_WORKER_KILL_JOIN_TIMEOUT_SECONDS)


def _assembly_worker(
    segments: list,
    music_path_str: Optional[str],
    audio_mode: str,
    output_format: str,
    output_path_str: str,
    result_queue: "multiprocessing.Queue",
) -> None:
    """Runs entirely in a separate spawned process — pure blocking MoviePy work.

    Never imports anything from this package at module scope beyond stdlib
    (a spawned process re-imports this module fresh); MoviePy itself is
    imported lazily here, matching the repository's lazy-provider-import
    convention applied to heavy optional dependencies.
    """
    clips: list = []
    music = None
    final_video = None
    try:
        from moviepy import AudioFileClip, CompositeAudioClip, VideoFileClip, concatenate_videoclips, vfx

        for idx, seg in enumerate(segments):
            raw_clip = VideoFileClip(seg["clip_path"])
            # Verified environment finding: container encode/decode round-trip
            # can quantize a clip's decoded duration marginally SHORTER than
            # what was requested (frame-boundary rounding) — trusting
            # edit_seconds blindly can then raise "end_time should be smaller
            # or equal to the clip's duration". Clamp to whichever is
            # shorter; a shortfall here is exactly what the one-frame
            # tolerance elsewhere in this feature (reel/timeline.py's
            # check_measured_duration) already treats as acceptable.
            end_time = min(seg["edit_seconds"], raw_clip.duration)
            clip = raw_clip.subclipped(0, end_time)

            if audio_mode == "muted":
                clip = clip.without_audio()
            elif audio_mode == "separate":
                clip = clip.without_audio()
                if seg["narration_path"]:
                    narration = AudioFileClip(seg["narration_path"])
                    narration_track = CompositeAudioClip([narration]).with_duration(seg["edit_seconds"])
                    clip = clip.with_audio(narration_track)
            # audio_mode == "native": keep the clip's own audio untouched.

            if idx > 0 and segments[idx - 1]["overlap_with_next_seconds"] > 0:
                clip = clip.with_effects([vfx.CrossFadeIn(segments[idx - 1]["overlap_with_next_seconds"])])

            clips.append(clip)

        # Verified environment finding: applying vfx.CrossFadeIn alone does
        # NOT shorten concatenate_videoclips' total duration — it only blends
        # the visual within each clip's own timespan. The actual temporal
        # OVERLAP (the "Σ edit − Σ overlaps" the plan computed) requires a
        # matching NEGATIVE `padding` on the concatenation itself
        # ("a clip will partly play at the same time as the clip it
        # follows... cool for clips who fade in on one another" — MoviePy's
        # own docstring). `padding` is a single scalar applied to every
        # consecutive pair, so this assumes a uniform overlap across the
        # plan — true of every plan `reel/timeline.py.plan_timeline` builds
        # today (one crossfade_seconds for the whole timeline); a future
        # per-pair-varying overlap would need a different concatenation
        # strategy.
        overlap = next((s["overlap_with_next_seconds"] for s in segments if s["overlap_with_next_seconds"] > 0), 0.0)
        final_video = concatenate_videoclips(clips, method="compose", padding=-overlap if overlap > 0 else 0)

        if audio_mode == "separate" and music_path_str:
            music = AudioFileClip(music_path_str)
            if music.duration < final_video.duration:
                music = music.with_effects([vfx.Loop(duration=final_video.duration)])
            else:
                music = music.subclipped(0, final_video.duration)
            if hasattr(music, "with_volume_scaled"):
                music = music.with_volume_scaled(0.3)
            elif hasattr(music, "multiply_volume"):
                music = music.multiply_volume(0.3)

            if final_video.audio is not None:
                final_audio = CompositeAudioClip([final_video.audio, music])
            else:
                final_audio = music
            final_video = final_video.with_audio(final_audio)

        codec_cfg = _CODEC_BY_FORMAT[output_format]
        # Verified environment finding: MoviePy derives its temp audio
        # filename via `os.path.join(temp_audiofile_path, ...)` with
        # `temp_audiofile_path` defaulting to `""` — an EMPTY string, not the
        # output directory — so the temp file lands CWD-relative unless this
        # is set explicitly, which fails outside a writable/expected cwd.
        # Always pin it next to the real output, for every format.
        write_kwargs: dict = {
            "codec": codec_cfg["codec"],
            "audio_codec": codec_cfg["audio_codec"],
            "logger": None,
            "temp_audiofile_path": str(Path(output_path_str).parent),
        }
        if codec_cfg["audio_fps"] is not None:
            # Verified requirement (module docstring): Opus needs a legal
            # sample rate, and MoviePy's codec→extension lookup has no
            # "libopus" entry — both worked around explicitly.
            write_kwargs["audio_fps"] = codec_cfg["audio_fps"]
            write_kwargs["temp_audiofile"] = str(Path(output_path_str).with_suffix(".temp_audio.ogg"))
        final_video.write_videofile(output_path_str, **write_kwargs)

        result_queue.put(("ok", output_path_str))
    except Exception as exc:  # noqa: BLE001 - forwarded to the parent process via the queue
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        for clip in clips:
            with contextlib.suppress(Exception):
                clip.close()
        if music is not None:
            with contextlib.suppress(Exception):
                music.close()
        if final_video is not None:
            with contextlib.suppress(Exception):
                final_video.close()

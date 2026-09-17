"""TASK-3329: managed-process media assembly tests.

Uses REAL, tiny MoviePy-generated clips (ColorClip, no network — matching
the spec's own `tiny_clip` fixture pattern) so the actual `assemble_reel()`
process spawn/encode/terminate lifecycle is exercised end to end, not
mocked. Kept small (64x64, <=1s per clip) to stay fast despite doing real
ffmpeg encoding.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import time
from pathlib import Path

import pytest

from parrot.clients.google.reel.assembly import AssemblyFailure, _terminate_and_join, assemble_reel
from parrot.clients.google.reel.timeline import TimelineEntry, plan_timeline

FAR_DEADLINE = lambda: time.monotonic() + 60.0  # noqa: E731


def _make_clip(path: Path, *, duration: float = 1.0, color=(255, 0, 0), with_tone: bool = True) -> Path:
    """Writes a real tiny MP4 clip (ColorClip + optional sine tone) to `path`.

    Explicitly pins `temp_audiofile_path` next to `path` — MoviePy's own
    default (an empty string, joined as a bare relative filename) writes the
    intermediate audio track CWD-relative instead of next to the output,
    which fails outside a specific writable cwd (see assembly.py's own
    verified-finding comment for the same issue in the production worker).
    """
    from moviepy import AudioClip, ColorClip

    clip = ColorClip(size=(64, 64), color=color, duration=duration).with_fps(24)
    if with_tone:
        tone = AudioClip(lambda t: 0.1, duration=duration, fps=44100)
        clip = clip.with_audio(tone)
    clip.write_videofile(
        str(path), codec="libx264", audio_codec="aac", logger=None, temp_audiofile_path=str(path.parent)
    )
    clip.close()
    return path


def _make_narration(path: Path, *, duration: float = 0.3) -> Path:
    """Writes a tiny real WAV narration clip."""
    from moviepy import AudioClip

    tone = AudioClip(lambda t: 0.2, duration=duration, fps=24000)
    tone.write_audiofile(str(path), logger=None)
    tone.close()
    return path


class TestPlayableOutput:
    def test_mp4_aac_assembly_produces_playable_output(self, tmp_path):
        clip0 = _make_clip(tmp_path / "scene_0.mp4", duration=0.5, color=(255, 0, 0))
        clip1 = _make_clip(tmp_path / "scene_1.mp4", duration=0.5, color=(0, 255, 0))
        entries = [
            TimelineEntry(scene_index=0, clip_path=clip0, edit_seconds=0.5),
            TimelineEntry(scene_index=1, clip_path=clip1, edit_seconds=0.5),
        ]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        output = asyncio.run(
            assemble_reel(
                plan,
                music_path=None,
                audio_mode="native",
                output_format="mp4",
                work_dir=tmp_path,
                deadline=FAR_DEADLINE(),
            )
        )

        assert output.exists()
        from moviepy import VideoFileClip

        check = VideoFileClip(str(output))
        try:
            assert check.duration == pytest.approx(1.0, abs=1.0 / 24.0)
            assert check.audio is not None  # native mode: original clip audio preserved
        finally:
            check.close()

    def test_webm_opus_assembly_produces_playable_output_with_audio(self, tmp_path):
        """Verified environment finding: Opus needs a legal sample rate (48000)
        and an explicit temp_audiofile — both handled internally by assemble_reel."""
        clip0 = _make_clip(tmp_path / "scene_0.mp4", duration=0.5)
        entries = [TimelineEntry(scene_index=0, clip_path=clip0, edit_seconds=0.5)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        output = asyncio.run(
            assemble_reel(
                plan,
                music_path=None,
                audio_mode="native",
                output_format="webm",
                work_dir=tmp_path,
                deadline=FAR_DEADLINE(),
            )
        )

        assert output.suffix == ".webm"
        assert output.exists()
        from moviepy import VideoFileClip

        check = VideoFileClip(str(output))
        try:
            assert check.duration == pytest.approx(0.5, abs=1.0 / 24.0)
            assert check.audio is not None
        finally:
            check.close()


class TestTimelineDurationFidelity:
    def test_cut_total_duration_within_one_frame(self, tmp_path):
        fps = 24.0
        clips = [_make_clip(tmp_path / f"scene_{i}.mp4", duration=0.5, with_tone=False) for i in range(4)]
        entries = [TimelineEntry(scene_index=i, clip_path=c, edit_seconds=0.5) for i, c in enumerate(clips)]
        plan = plan_timeline(entries, transition="cut", fps=fps)
        assert plan.final_duration_seconds == 2.0

        output = asyncio.run(
            assemble_reel(
                plan,
                music_path=None,
                audio_mode="muted",
                output_format="mp4",
                work_dir=tmp_path,
                deadline=FAR_DEADLINE(),
            )
        )

        from moviepy import VideoFileClip

        check = VideoFileClip(str(output))
        try:
            assert check.duration == pytest.approx(plan.final_duration_seconds, abs=1.0 / fps)
        finally:
            check.close()

    def test_crossfade_total_duration_within_one_frame(self, tmp_path):
        fps = 24.0
        clips = [_make_clip(tmp_path / f"scene_{i}.mp4", duration=0.5, with_tone=False) for i in range(4)]
        entries = [TimelineEntry(scene_index=i, clip_path=c, edit_seconds=0.5) for i, c in enumerate(clips)]
        plan = plan_timeline(entries, transition="crossfade", crossfade_seconds=0.1, fps=fps)
        assert plan.final_duration_seconds == pytest.approx(1.7)  # 2.0 - 3*0.1

        output = asyncio.run(
            assemble_reel(
                plan,
                music_path=None,
                audio_mode="muted",
                output_format="mp4",
                work_dir=tmp_path,
                deadline=FAR_DEADLINE(),
            )
        )

        from moviepy import VideoFileClip

        check = VideoFileClip(str(output))
        try:
            assert check.duration == pytest.approx(plan.final_duration_seconds, abs=1.0 / fps)
        finally:
            check.close()


class TestAudioModes:
    def test_narration_padded_with_silence_never_stretches_clip(self, tmp_path):
        clip = _make_clip(tmp_path / "scene_0.mp4", duration=1.0, with_tone=False)
        narration = _make_narration(tmp_path / "narr_0.wav", duration=0.3)
        entries = [TimelineEntry(scene_index=0, clip_path=clip, edit_seconds=1.0, narration_path=narration)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        output = asyncio.run(
            assemble_reel(
                plan,
                music_path=None,
                audio_mode="separate",
                output_format="mp4",
                work_dir=tmp_path,
                deadline=FAR_DEADLINE(),
            )
        )

        from moviepy import VideoFileClip

        check = VideoFileClip(str(output))
        try:
            # Duration stays the segment's edit_seconds (1.0s) — the 0.3s
            # narration is padded with silence, never stretched to fill it
            # and never truncates the video.
            assert check.duration == pytest.approx(1.0, abs=1.0 / 24.0)
            assert check.audio is not None
        finally:
            check.close()

    def test_muted_mode_has_no_audio_track(self, tmp_path):
        clip = _make_clip(tmp_path / "scene_0.mp4", duration=0.5, with_tone=True)
        entries = [TimelineEntry(scene_index=0, clip_path=clip, edit_seconds=0.5)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        output = asyncio.run(
            assemble_reel(
                plan,
                music_path=None,
                audio_mode="muted",
                output_format="mp4",
                work_dir=tmp_path,
                deadline=FAR_DEADLINE(),
            )
        )

        from moviepy import VideoFileClip

        check = VideoFileClip(str(output))
        try:
            assert check.audio is None
        finally:
            check.close()

    def test_native_mode_preserves_original_clip_audio(self, tmp_path):
        clip = _make_clip(tmp_path / "scene_0.mp4", duration=0.5, with_tone=True)
        entries = [TimelineEntry(scene_index=0, clip_path=clip, edit_seconds=0.5)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        output = asyncio.run(
            assemble_reel(
                plan,
                music_path=None,
                audio_mode="native",
                output_format="mp4",
                work_dir=tmp_path,
                deadline=FAR_DEADLINE(),
            )
        )

        from moviepy import VideoFileClip

        check = VideoFileClip(str(output))
        try:
            assert check.audio is not None
        finally:
            check.close()


class TestFailureAndConcurrency:
    def test_unsupported_output_format_raises_value_error(self, tmp_path):
        entries = [TimelineEntry(scene_index=0, clip_path=tmp_path / "x.mp4", edit_seconds=1.0)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        with pytest.raises(ValueError):
            asyncio.run(
                assemble_reel(
                    plan,
                    music_path=None,
                    audio_mode="muted",
                    output_format="avi",  # not in _CODEC_BY_FORMAT
                    work_dir=tmp_path,
                    deadline=FAR_DEADLINE(),
                )
            )

    def test_encoder_failure_reports_assembly_failure(self, tmp_path):
        """A missing/unreadable clip file must surface as AssemblyFailure, not hang or crash the parent."""
        entries = [TimelineEntry(scene_index=0, clip_path=tmp_path / "does_not_exist.mp4", edit_seconds=1.0)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        with pytest.raises(AssemblyFailure):
            asyncio.run(
                assemble_reel(
                    plan,
                    music_path=None,
                    audio_mode="muted",
                    output_format="mp4",
                    work_dir=tmp_path,
                    deadline=FAR_DEADLINE(),
                )
            )

    def test_concurrent_jobs_never_overwrite_each_others_output(self, tmp_path):
        clip_a = _make_clip(tmp_path / "job_a_scene.mp4", duration=0.3, with_tone=False)
        clip_b = _make_clip(tmp_path / "job_b_scene.mp4", duration=0.3, with_tone=False)
        plan_a = plan_timeline(
            [TimelineEntry(scene_index=0, clip_path=clip_a, edit_seconds=0.3)], transition="cut", fps=24.0
        )
        plan_b = plan_timeline(
            [TimelineEntry(scene_index=0, clip_path=clip_b, edit_seconds=0.3)], transition="cut", fps=24.0
        )

        async def _run_both():
            return await asyncio.gather(
                assemble_reel(
                    plan_a,
                    music_path=None,
                    audio_mode="muted",
                    output_format="mp4",
                    work_dir=tmp_path,  # SAME work_dir for both jobs
                    deadline=FAR_DEADLINE(),
                ),
                assemble_reel(
                    plan_b,
                    music_path=None,
                    audio_mode="muted",
                    output_format="mp4",
                    work_dir=tmp_path,
                    deadline=FAR_DEADLINE(),
                ),
            )

        output_a, output_b = asyncio.run(_run_both())

        assert output_a != output_b
        assert output_a.exists()
        assert output_b.exists()


class TestCancellationAndTermination:
    def test_terminate_and_join_kills_a_running_process(self):
        """Direct test of the exact mechanism assemble_reel uses for
        'terminate and await the worker' on timeout/cancellation."""
        ctx = multiprocessing.get_context("spawn")
        process = ctx.Process(target=time.sleep, args=(30,), daemon=True)
        process.start()
        assert process.is_alive()

        start = time.monotonic()
        _terminate_and_join(process)
        elapsed = time.monotonic() - start

        assert process.is_alive() is False
        assert elapsed < 5.0  # terminated promptly, not waited out the 30s sleep

    def test_cancellation_during_assembly_propagates_and_leaves_no_child(self, tmp_path):
        clips = [_make_clip(tmp_path / f"scene_{i}.mp4", duration=0.5, with_tone=False) for i in range(3)]
        entries = [TimelineEntry(scene_index=i, clip_path=c, edit_seconds=0.5) for i, c in enumerate(clips)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        async def _run_and_cancel():
            task = asyncio.create_task(
                assemble_reel(
                    plan,
                    music_path=None,
                    audio_mode="muted",
                    output_format="mp4",
                    work_dir=tmp_path,
                    deadline=FAR_DEADLINE(),
                )
            )
            await asyncio.sleep(0.05)  # let the spawned process actually start
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(_run_and_cancel())

        # No leaked child process after cancellation settles.
        time.sleep(0.2)
        assert multiprocessing.active_children() == []

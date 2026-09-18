"""TASK-3328: deterministic scene timeline planning and duration-check tests.

Verifies plan_timeline's cut/crossfade math (AC05: four 5s scenes -> 20s cut
or 18.5s crossfade), original-index preservation, invalid fps/overlap
rejection, and check_measured_duration/check_narration_fits' one-frame
tolerance and never-stretch behavior (AC04).
"""

from pathlib import Path

import pytest

from parrot.clients.google.reel.errors import ReelError, ReelErrorCode, ReelValidationError
from parrot.clients.google.reel.timeline import (
    TimelineEntry,
    check_measured_duration,
    check_narration_fits,
    plan_timeline,
)


def _entry(index: int, seconds: float = 5.0, narration: bool = False) -> TimelineEntry:
    return TimelineEntry(
        scene_index=index,
        clip_path=Path(f"/tmp/scene_{index}.mp4"),
        edit_seconds=seconds,
        narration_path=Path(f"/tmp/narration_{index}.wav") if narration else None,
    )


class TestPlanTimelineCutAndCrossfade:
    def test_four_5s_scenes_cut_totals_20s(self):
        entries = [_entry(i) for i in range(4)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        assert plan.final_duration_seconds == 20.0
        assert [s.overlap_with_next_seconds for s in plan.segments] == [0.0, 0.0, 0.0, 0.0]
        assert [s.start_seconds for s in plan.segments] == [0.0, 5.0, 10.0, 15.0]

    def test_four_5s_scenes_crossfade_totals_18_5s(self):
        entries = [_entry(i) for i in range(4)]
        plan = plan_timeline(entries, transition="crossfade", crossfade_seconds=0.5, fps=24.0)

        assert plan.final_duration_seconds == 18.5
        # Three overlaps consumed (between 4 scenes), last segment has none.
        assert [s.overlap_with_next_seconds for s in plan.segments] == [0.5, 0.5, 0.5, 0.0]
        assert [s.start_seconds for s in plan.segments] == [0.0, 4.5, 9.0, 13.5]

    def test_original_scene_indices_preserved_and_out_of_order_ok(self):
        """Skipped-index scenario: only scenes 0 and 3 survived (1, 2 skipped
        upstream); the plan must retain the ORIGINAL indices."""
        entries = [_entry(0), _entry(3)]
        plan = plan_timeline(entries, transition="cut", fps=24.0)

        assert [s.scene_index for s in plan.segments] == [0, 3]
        assert plan.final_duration_seconds == 10.0

    def test_single_entry_plan(self):
        plan = plan_timeline([_entry(0)], transition="crossfade", crossfade_seconds=0.5, fps=24.0)

        assert plan.final_duration_seconds == 5.0
        assert plan.segments[0].overlap_with_next_seconds == 0.0

    def test_no_entries_rejected(self):
        with pytest.raises(ReelValidationError) as exc_info:
            plan_timeline([], transition="cut", fps=24.0)
        assert exc_info.value.code is ReelErrorCode.INVALID_CONFIGURATION


class TestPlanTimelineValidation:
    def test_invalid_fps_rejected(self):
        for bad_fps in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ReelValidationError) as exc_info:
                plan_timeline([_entry(0)], transition="cut", fps=bad_fps)
            assert exc_info.value.code is ReelErrorCode.INVALID_CONFIGURATION

    def test_invalid_edit_seconds_rejected(self):
        bad_entry = TimelineEntry(scene_index=0, clip_path=Path("/tmp/x.mp4"), edit_seconds=0.0)
        with pytest.raises(ReelValidationError) as exc_info:
            plan_timeline([bad_entry], transition="cut", fps=24.0)
        assert exc_info.value.code is ReelErrorCode.INVALID_CONFIGURATION

    def test_overlap_equal_to_neighbor_duration_rejected(self):
        """A crossfade consuming an ENTIRE neighboring scene leaves no
        content for that scene — must be rejected, not just > ."""
        entries = [_entry(0, seconds=5.0), _entry(1, seconds=5.0)]
        with pytest.raises(ReelValidationError) as exc_info:
            plan_timeline(entries, transition="crossfade", crossfade_seconds=5.0, fps=24.0)
        assert exc_info.value.code is ReelErrorCode.INVALID_CONFIGURATION

    def test_overlap_longer_than_neighbor_rejected(self):
        entries = [_entry(0, seconds=5.0), _entry(1, seconds=3.0)]
        with pytest.raises(ReelValidationError) as exc_info:
            plan_timeline(entries, transition="crossfade", crossfade_seconds=4.0, fps=24.0)
        assert exc_info.value.code is ReelErrorCode.INVALID_CONFIGURATION

    def test_negative_crossfade_rejected(self):
        entries = [_entry(0), _entry(1)]
        with pytest.raises(ReelValidationError) as exc_info:
            plan_timeline(entries, transition="crossfade", crossfade_seconds=-0.5, fps=24.0)
        assert exc_info.value.code is ReelErrorCode.INVALID_CONFIGURATION

    def test_zero_crossfade_is_legal_cut_equivalent(self):
        """crossfade_seconds=0 is a degenerate-but-legal crossfade (no actual overlap)."""
        entries = [_entry(0), _entry(1)]
        plan = plan_timeline(entries, transition="crossfade", crossfade_seconds=0.0, fps=24.0)
        assert plan.final_duration_seconds == 10.0


class TestCheckMeasuredDuration:
    def test_exact_match_passes(self):
        check_measured_duration(target=5.0, measured=5.0, fps=24.0)  # must not raise

    def test_within_one_frame_tolerance_passes(self):
        tolerance = 1.0 / 24.0
        check_measured_duration(target=5.0, measured=5.0 - tolerance, fps=24.0)  # exactly at boundary

    def test_shorter_than_tolerance_raises_insufficient_duration(self):
        tolerance = 1.0 / 24.0
        with pytest.raises(ReelError) as exc_info:
            check_measured_duration(target=5.0, measured=5.0 - tolerance - 0.01, fps=24.0)
        assert exc_info.value.code is ReelErrorCode.INSUFFICIENT_DURATION
        assert exc_info.value.retryable is False

    def test_longer_measured_never_raises(self):
        check_measured_duration(target=5.0, measured=5.5, fps=24.0)  # must not raise; never trimmed here

    def test_invalid_fps_rejected(self):
        with pytest.raises(ReelValidationError) as exc_info:
            check_measured_duration(target=5.0, measured=5.0, fps=0.0)
        assert exc_info.value.code is ReelErrorCode.INVALID_CONFIGURATION


class TestCheckNarrationFits:
    def test_narration_within_target_passes(self):
        check_narration_fits(target=5.0, narration_seconds=4.5)  # must not raise

    def test_narration_exactly_at_target_passes(self):
        check_narration_fits(target=5.0, narration_seconds=5.0)  # must not raise

    def test_narration_overflow_raises(self):
        with pytest.raises(ReelError) as exc_info:
            check_narration_fits(target=5.0, narration_seconds=6.0)
        assert exc_info.value.code is ReelErrorCode.NARRATION_TOO_LONG
        assert exc_info.value.retryable is False

    def test_shorter_narration_never_raises_and_is_not_stretched(self):
        """Nothing in this function pads/stretches — it only ever rejects too-long narration."""
        check_narration_fits(target=5.0, narration_seconds=2.0)  # must not raise

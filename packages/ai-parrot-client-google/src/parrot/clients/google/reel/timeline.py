"""Pure scene-timeline planning and duration checks (FEAT-564, spec module M6).

Every function here is pure computation — no MoviePy, no provider calls, no
I/O. ``plan_timeline`` produces one explicit :class:`TimelinePlan` that the
assembly stage (a later task) consumes as its sole source of truth for clip
placement; nothing here loops, stretches or regenerates a short clip —
:func:`check_measured_duration` only ever raises.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from .errors import ReelError, ReelErrorCode, ReelValidationError

# One output frame's worth of measurement slack (spec §2 item 4: "shorter than
# the target by more than one frame fails"). Callers supply their own fps.
_DEFAULT_CROSSFADE_SECONDS = 0.5


class TimelineEntry(BaseModel):
    """One scene's generated clip, as input to timeline planning.

    Args:
        scene_index: The scene's original index — preserved through the plan
            even if scenes were skipped elsewhere in the pipeline.
        clip_path: Local path to the scene's generated (and trimmed-target)
            clip.
        edit_seconds: The scene's edit target duration (the timeline slot
            this clip occupies, not necessarily its raw generated length).
        narration_path: Optional narration audio path for this scene.
    """

    scene_index: int = Field(..., description="Original scene index, preserved even under skip.")
    clip_path: Path = Field(..., description="Local path to the scene's generated clip.")
    edit_seconds: float = Field(..., description="The scene's edit target duration (timeline slot length).")
    narration_path: Optional[Path] = Field(None, description="Optional narration audio path for this scene.")


class TimelineSegment(BaseModel):
    """One entry's placement within the final assembled timeline.

    Args:
        scene_index: The scene's original index (from :class:`TimelineEntry`).
        clip_path: Local path to the scene's clip.
        start_seconds: This segment's start position in the final timeline.
        edit_seconds: This segment's own duration (unchanged from the entry).
        narration_path: Optional narration audio path for this scene.
        overlap_with_next_seconds: Crossfade overlap consumed between this
            segment and the next one (``0.0`` for a cut transition, or for
            the last segment).
    """

    scene_index: int
    clip_path: Path
    start_seconds: float = Field(..., ge=0.0)
    edit_seconds: float
    narration_path: Optional[Path] = None
    overlap_with_next_seconds: float = Field(0.0, ge=0.0)


class TimelinePlan(BaseModel):
    """The one explicit plan assembly consumes for clip placement.

    Args:
        transition: The transition style used to build this plan.
        fps: The output frame rate this plan (and its one-frame tolerances)
            were computed for.
        segments: Ordered segments, original scene indices preserved.
        final_duration_seconds: Total assembled duration — sum of every
            segment's ``edit_seconds`` minus every consumed overlap.
    """

    transition: Literal["cut", "crossfade"]
    fps: float
    segments: List[TimelineSegment]
    final_duration_seconds: float = Field(..., ge=0.0)


def plan_timeline(
    entries: Sequence[TimelineEntry],
    *,
    transition: Literal["cut", "crossfade"],
    crossfade_seconds: float = _DEFAULT_CROSSFADE_SECONDS,
    fps: float,
) -> TimelinePlan:
    """Computes the final assembled timeline for a sequence of scene clips.

    Cuts: the final duration is the sum of every entry's ``edit_seconds``.
    Crossfades: the final duration subtracts every ACTUAL consumed overlap
    (``crossfade_seconds`` between each adjacent pair) — four 5 s scenes give
    20 s with cuts, or 18.5 s with three 0.5 s crossfades.

    Args:
        entries: Ordered scene clips to place on the timeline. Original
            scene indices are preserved on the output segments.
        transition: ``"cut"`` (no overlap) or ``"crossfade"``.
        crossfade_seconds: The overlap duration between adjacent segments,
            only used when ``transition == "crossfade"``.
        fps: The output frame rate this plan is computed for.

    Returns:
        The computed :class:`TimelinePlan`.

    Raises:
        ReelValidationError: Non-finite/non-positive ``fps``, an empty
            ``entries`` sequence, a non-finite/non-positive
            ``edit_seconds`` on any entry, a non-finite/negative
            ``crossfade_seconds``, or a crossfade overlap that is not
            strictly shorter than BOTH of its neighboring segments'
            durations (an overlap consuming an entire scene, or more,
            leaves no content for that scene to show).
    """
    if not math.isfinite(fps) or fps <= 0:
        raise ReelValidationError(
            ReelErrorCode.INVALID_CONFIGURATION, f"fps must be a finite positive number, got {fps!r}."
        )
    if not entries:
        raise ReelValidationError(ReelErrorCode.INVALID_CONFIGURATION, "plan_timeline requires at least one entry.")
    for entry in entries:
        if not math.isfinite(entry.edit_seconds) or entry.edit_seconds <= 0:
            raise ReelValidationError(
                ReelErrorCode.INVALID_CONFIGURATION,
                f"Scene {entry.scene_index} has an invalid edit duration: {entry.edit_seconds!r}.",
            )

    effective_crossfade = 0.0
    if transition == "crossfade":
        if not math.isfinite(crossfade_seconds) or crossfade_seconds < 0:
            raise ReelValidationError(
                ReelErrorCode.INVALID_CONFIGURATION,
                f"crossfade_seconds must be a finite, non-negative number, got {crossfade_seconds!r}.",
            )
        for left, right in zip(entries, entries[1:], strict=False):  # deliberately offset-by-one pairing
            if crossfade_seconds >= left.edit_seconds or crossfade_seconds >= right.edit_seconds:
                raise ReelValidationError(
                    ReelErrorCode.INVALID_CONFIGURATION,
                    f"Crossfade of {crossfade_seconds}s is not shorter than a neighboring scene's duration "
                    f"(scenes {left.scene_index}/{right.scene_index}, durations "
                    f"{left.edit_seconds}s/{right.edit_seconds}s).",
                )
        effective_crossfade = crossfade_seconds

    segments: List[TimelineSegment] = []
    start = 0.0
    total_overlap = 0.0
    last_index = len(entries) - 1
    for i, entry in enumerate(entries):
        overlap_with_next = effective_crossfade if i < last_index else 0.0
        segments.append(
            TimelineSegment(
                scene_index=entry.scene_index,
                clip_path=entry.clip_path,
                start_seconds=start,
                edit_seconds=entry.edit_seconds,
                narration_path=entry.narration_path,
                overlap_with_next_seconds=overlap_with_next,
            )
        )
        start += entry.edit_seconds - overlap_with_next
        total_overlap += overlap_with_next

    final_duration = sum(entry.edit_seconds for entry in entries) - total_overlap
    return TimelinePlan(transition=transition, fps=fps, segments=segments, final_duration_seconds=final_duration)


def check_measured_duration(target: float, measured: float, fps: float) -> None:
    """Verifies a measured clip is not shorter than its target by more than one frame.

    Never loops, stretches or regenerates a short clip — this function only
    ever raises or silently passes.

    Args:
        target: The scene's edit target duration in seconds.
        measured: The clip's actually-measured duration in seconds.
        fps: The output frame rate, used to compute the one-frame tolerance.

    Raises:
        ReelValidationError: Non-finite/non-positive ``fps``.
        ReelError: ``insufficient_duration`` when ``measured`` is shorter
            than ``target`` by more than one output frame
            (``1.0 / fps`` seconds).
    """
    if not math.isfinite(fps) or fps <= 0:
        raise ReelValidationError(
            ReelErrorCode.INVALID_CONFIGURATION, f"fps must be a finite positive number, got {fps!r}."
        )
    tolerance = 1.0 / fps
    if measured < target - tolerance:
        raise ReelError(
            ReelErrorCode.INSUFFICIENT_DURATION,
            f"Measured duration {measured}s is shorter than target {target}s by more than one frame "
            f"({tolerance}s tolerance at {fps} fps).",
            stage="timeline_check",
            retryable=False,
        )


def check_narration_fits(target: float, narration_seconds: float) -> None:
    """Verifies narration audio fits within its scene's edit target.

    Shorter narration is left as-is (padded with silence elsewhere, never
    time-stretched) — this function only rejects narration that is too long.

    Args:
        target: The scene's edit target duration in seconds.
        narration_seconds: The narration audio's duration in seconds.

    Raises:
        ReelError: ``narration_too_long`` when ``narration_seconds`` exceeds
            ``target``.
    """
    if narration_seconds > target:
        raise ReelError(
            ReelErrorCode.NARRATION_TOO_LONG,
            f"Narration ({narration_seconds}s) exceeds the scene's edit target ({target}s).",
            stage="timeline_check",
            retryable=False,
        )

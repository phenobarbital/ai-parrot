"""Unit tests for the strip orchestration and flattening join (FEAT-592, TASK-3642)."""

from __future__ import annotations

from typing import List

import numpy as np
from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import (
    Identification,
    IdentificationResponse,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    Shape,
    Slot,
)
from parrot_pipelines.planogram.identification.vision import VisionError

from identify import _id_allocator, _plan_chunks, flatten, identify_strips_closed_set
from prompt import PlanogramVocabulary


def _box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _perception() -> PerceptionResult:
    """Build one image with two slots, including a gap-filled slot."""
    return PerceptionResult(
        image_id="img0",
        image_size=(1000, 800),
        slots=[
            Slot(
                slot_id="img0:r0:s1",
                image_id="img0",
                row_index=0,
                slot_index=1,
                box=_box(10, 20, 110, 220),
                inferred=False,
            ),
            Slot(
                slot_id="img0:r0:s2",
                image_id="img0",
                row_index=0,
                slot_index=2,
                box=_box(120, 20, 220, 220),
                inferred=True,
            ),
        ],
    )


def _identification(shape_id: str, **values: object) -> Identification:
    return Identification(shape_id=shape_id, raw_confidence=0.9, **values)


def test_flatten_joins_slot_ids_to_source_pixels() -> None:
    """A slot identification gets that slot's source-pixel box."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[
            _identification("img0:r0:s1", product="9C228AN", brand="HP", occupancy="occupied"),
        ],
    )

    rows = flatten(result, _perception())

    assert [row.bbox for row in rows] == [[10, 20, 110, 220]]
    assert rows[0].brand == "HP"
    assert rows[0].occupancy == "occupied"


def test_flatten_marks_inferred_slots() -> None:
    """A gap-filled slot carries its inferred flag into the flat row."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[_identification("img0:r0:s2", occupancy="empty")],
    )

    rows = flatten(result, _perception())

    assert rows[0].inferred is True


def test_flatten_joins_added_shapes() -> None:
    """An LLM-added shape uses its own box and llm_added source."""
    added = Shape(
        shape_id="img0:added:1",
        image_id="img0",
        box=_box(300, 20, 400, 220),
        source=ObservationSource.LLM_ADDED,
    )
    result = IdentificationResult(
        image_id="img0",
        identifications=[_identification("img0:added:1", occupancy="occupied")],
        added=[added],
    )

    rows = flatten(result, _perception())

    assert rows[0].bbox == [300, 20, 400, 220]
    assert rows[0].source == "llm_added"


def test_flatten_skips_unmatched_ids() -> None:
    """An id without a source box is omitted rather than emitted with a null box."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[_identification("img0:r9:s9")],
    )

    assert flatten(result, _perception()) == []


def test_flatten_never_emits_normalised_coordinates() -> None:
    """Every flattened coordinate remains in the source image's pixel bounds."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[
            _identification("img0:r0:s1"),
            _identification("img0:r0:s2"),
        ],
    )

    rows = flatten(result, _perception())

    assert all(
        0 <= coordinate <= bound
        for row in rows
        for coordinate, bound in zip(row.bbox, (1000, 800, 1000, 800), strict=True)
    )


# ---------------------------------------------------------------------------
# identify_strips_closed_set orchestration: chunking, repair, cache/call
# accounting and per-strip failure isolation. Mirrors the pipeline's own
# InlineExecutor/StubAdapter pattern (packages/ai-parrot-pipelines/tests/
# planogram_cycle/test_identify.py) so no real CpuExecutor process pool or
# live Nova/Bedrock call is ever needed.
# ---------------------------------------------------------------------------


class InlineExecutor:
    """Synchronous stand-in for CpuExecutor — no process pool needed for these tests."""

    async def run(self, fn, *args):
        return fn(*args)


class FakeNovaClient:
    """Tracks 'reached Bedrock' calls/usage exactly like NovaVisionClient does (nova_vision.py)."""

    def __init__(self) -> None:
        self.calls_made = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_image_bytes_sent = 0


class CacheHit:
    """Marks a queued answer as served from VisionAdapter's own response cache.

    A real cache hit means ``ask_to_image`` is never invoked, so the wrapped
    answer is returned WITHOUT touching ``.client`` — the only way a cache
    hit is distinguishable from a live answer (see identify.py's
    reconciliation comment in ``identify_strips_closed_set``).
    """

    def __init__(self, answer: IdentificationResponse) -> None:
        self.answer = answer


class StubVisionAdapter:
    """Pops queued answers/exceptions/cache hits; exposes ``.client`` like the real adapter.

    Verified: ``VisionAdapter.__init__`` (vision.py:157-165) sets the public
    ``self.client = client`` attribute this stub mirrors.
    """

    def __init__(self, *answers, input_tokens: int = 10, output_tokens: int = 5, image_bytes: int = 100) -> None:
        self.answers: List[object] = list(answers)
        self.calls: List[str] = []
        self.client = FakeNovaClient()
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._image_bytes = image_bytes

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append(prompt)
        item = self.answers.pop(0)
        if isinstance(item, CacheHit):
            return item.answer
        if isinstance(item, Exception):
            raise item
        self.client.calls_made += 1
        self.client.total_input_tokens += self._input_tokens
        self.client.total_output_tokens += self._output_tokens
        self.client.total_image_bytes_sent += self._image_bytes
        return item


def _orchestration_slot(slot_id: str, row: int, index: int, x1: int, y1: int, x2: int, y2: int) -> Slot:
    return Slot(slot_id=slot_id, image_id="img0", row_index=row, slot_index=index, box=_box(x1, y1, x2, y2))


def _orchestration_perception(*, rows: int = 1, per_row: int = 1) -> PerceptionResult:
    """A perception result with ``rows`` rows of ``per_row`` slots, sized to crop safely."""
    slots = []
    for row in range(rows):
        for index in range(1, per_row + 1):
            x1 = 10 + (index - 1) * 60
            y1 = 10 + row * 60
            slots.append(_orchestration_slot(f"img0:r{row}:s{index}", row, index, x1, y1, x1 + 50, y1 + 50))
    width = 10 + per_row * 60 + 10
    height = 10 + rows * 60 + 10
    return PerceptionResult(image_id="img0", image_size=(width, height), slots=slots, row_count=rows)


def _identification_answer(ids: List[str]) -> IdentificationResponse:
    return IdentificationResponse(
        existing_identifications=[
            Identification(shape_id=i, product="9C228AN", brand="HP", occupancy="occupied", raw_confidence=0.9)
            for i in ids
        ]
    )


def _orchestration_image(perception: PerceptionResult) -> np.ndarray:
    width, height = perception.image_size
    return np.full((height, width, 3), 30, dtype=np.uint8)


async def test_identify_strips_counts_only_real_bedrock_calls() -> None:
    """A single successful call is reflected as one real call with its own token usage."""
    perception = _orchestration_perception()
    adapter = StubVisionAdapter(
        _identification_answer(["img0:r0:s1"]), input_tokens=42, output_tokens=7, image_bytes=999
    )

    result, stats = await identify_strips_closed_set(
        _orchestration_image(perception),
        perception,
        adapter,
        PlanogramVocabulary(products=[], brands=[]),
        executor=InlineExecutor(),
        schema_instruction="SCHEMA",
    )

    assert stats.strips == 1
    assert stats.calls == 1
    assert stats.cache_hits == 0
    assert stats.incomplete_retries == 0
    assert stats.failed_strips == 0
    assert stats.input_tokens == 42
    assert stats.output_tokens == 7
    assert stats.image_bytes_sent == 999  # reconciled against the transport's real total, not the render count
    assert result.identifications[0].product == "9C228AN"


async def test_identify_strips_missing_id_repair_is_a_second_real_call() -> None:
    """A response missing a requested id triggers exactly one repair call, itself counted for real."""
    perception = _orchestration_perception(per_row=2)
    first = _identification_answer(["img0:r0:s1"])  # omits img0:r0:s2
    repair = _identification_answer(["img0:r0:s1", "img0:r0:s2"])
    adapter = StubVisionAdapter(first, repair, input_tokens=10, output_tokens=5)

    result, stats = await identify_strips_closed_set(
        _orchestration_image(perception),
        perception,
        adapter,
        PlanogramVocabulary(products=[], brands=[]),
        executor=InlineExecutor(),
        schema_instruction="SCHEMA",
    )

    assert len(adapter.calls) == 2
    assert "CORRECTION" in adapter.calls[1]
    assert stats.incomplete_retries == 1
    assert stats.calls == 2  # both attempts genuinely reached Bedrock
    assert stats.input_tokens == 20 and stats.output_tokens == 10
    by_id = {item.shape_id: item for item in result.identifications}
    assert not by_id["img0:r0:s2"].uncertain


async def test_identify_strips_cache_hit_reduces_calls_not_attempts() -> None:
    """A cache hit is one attempted ask but zero real Bedrock calls — the point of the TASK-3640/3642/3643 review fix."""
    perception = _orchestration_perception()
    adapter = StubVisionAdapter(CacheHit(_identification_answer(["img0:r0:s1"])))

    result, stats = await identify_strips_closed_set(
        _orchestration_image(perception),
        perception,
        adapter,
        PlanogramVocabulary(products=[], brands=[]),
        executor=InlineExecutor(),
        schema_instruction="SCHEMA",
    )

    assert stats.calls == 0
    assert stats.cache_hits == 1
    assert stats.input_tokens == 0 and stats.output_tokens == 0
    assert stats.image_bytes_sent == 0  # nothing reached Bedrock -> zero real bytes transmitted
    assert result.identifications[0].product == "9C228AN"


async def test_identify_strips_failed_strip_is_isolated() -> None:
    """A VisionError on one row's strip never propagates and never counts as a real call."""
    perception = _orchestration_perception(rows=2)
    adapter = StubVisionAdapter(_identification_answer(["img0:r0:s1"]), VisionError("boom"))

    result, stats = await identify_strips_closed_set(
        _orchestration_image(perception),
        perception,
        adapter,
        PlanogramVocabulary(products=[], brands=[]),
        executor=InlineExecutor(),
        schema_instruction="SCHEMA",
    )

    assert stats.strips == 2
    assert stats.failed_strips == 1
    assert stats.calls == 1  # only the successful strip reached Bedrock
    by_id = {item.shape_id: item for item in result.identifications}
    assert not by_id["img0:r0:s1"].uncertain
    assert by_id["img0:r1:s1"].uncertain
    assert "identify_failed" in by_id["img0:r1:s1"].evidence[0]
    assert len(result.errors) == 1 and "boom" in result.errors[0]


def test_plan_chunks_splits_large_rows_into_balanced_groups() -> None:
    """20 targets in one row, cap 8, split into balanced chunks of 7/7/6 (mirrors identify_strips)."""
    slots = [_orchestration_slot(f"img0:r0:s{i}", 0, i, i * 50, 10, i * 50 + 40, 90) for i in range(1, 21)]

    chunks = _plan_chunks(slots, substrip_max_slots=8)

    assert [len(chunk) for chunk in chunks] == [7, 7, 6]
    assert sum(len(chunk) for chunk in chunks) == 20


def test_id_allocator_increments_sequentially() -> None:
    """Each call returns a new pipeline-owned id scoped to the image."""
    perception = PerceptionResult(image_id="img0", image_size=(10, 10), slots=[])
    allocate = _id_allocator(perception)

    assert [allocate(), allocate(), allocate()] == ["img0:added:1", "img0:added:2", "img0:added:3"]

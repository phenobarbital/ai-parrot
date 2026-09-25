"""FEAT-601 M7 — video alignment."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("bm25s")

import parrot.knowledge.manuals.video as vd  # noqa: E402
from parrot.knowledge.common.provenance import Evidence, Extracted  # noqa: E402
from parrot.knowledge.manuals.models import (  # noqa: E402
    ManualCard,
    Procedure,
    Step,
    StepIdentity,
    content_hash,
)


def _transcript(texts: list[str]) -> dict[str, list[dict[str, object]]]:
    """Build evenly timestamped Whisper chunks for tests."""
    return {"chunks": [{"timestamp": (index * 10.0, index * 10.0 + 9.0), "text": text} for index, text in enumerate(texts)]}


def _step(order: int, text: str) -> Step:
    """Build a substantiated manual step."""
    return Step(
        identity=StepIdentity(step_id=f"manual:procedure:{order}", content_hash=content_hash(text)),
        order=order,
        text=Extracted[str](value=text, evidence=Evidence(node_id="node", quote=text), confidence=0.9),
    )


def _card(steps: list[Step]) -> ManualCard:
    """Build a minimal single-procedure card."""
    title = "Install assembly"
    return ManualCard(
        manual_id="manual-1",
        revision="A",
        procedures=[
            Procedure(
                procedure_id="procedure-1",
                slug="install",
                kind="assembly",
                title=Extracted[str](value=title, evidence=Evidence(node_id="node", quote=title), confidence=0.9),
                steps=steps,
            )
        ],
    )


def test_align_deterministic_monotonic() -> None:
    """BM25 alignments remain ordered and leave unmatched steps behind."""
    steps = [_step(1, "tighten alpha bolt"), _step(2, "inspect beta panel"), _step(3, "route gamma cable")]
    blocks = vd.blocks_from_transcript(_transcript(["tighten alpha bolt", "route gamma cable"]))

    alignments, unaligned = vd.align_deterministic(steps, blocks)

    assert [alignment.step_id for alignment in alignments] == [steps[0].identity.step_id, steps[2].identity.step_id]
    assert [step.identity.step_id for step in unaligned] == [steps[1].identity.step_id]
    assert all(left.t_end <= right.t_start for left, right in zip(alignments, alignments[1:], strict=False))


class _ScriptedAdapter:
    """Structured-output adapter returning supplied judgement payloads."""

    model = "test-model"

    def __init__(self, payload: dict[str, object]) -> None:
        """Save the payload returned by ``ask_structured``."""
        self.payload = payload
        self.calls = 0

    async def ask_structured(self, prompt: str, schema: type[vd.JudgementDraft], *, temperature: float) -> dict[str, object]:
        """Return the scripted structured response."""
        assert "UNTRUSTED TRANSCRIPT DATA" in prompt
        assert schema is vd.JudgementDraft
        assert temperature == 0.0
        self.calls += 1
        return self.payload


async def test_judge_alignment_drops_hallucinated_ids(tmp_path) -> None:
    """Candidate filtering and force reset permit only valid fresh judgements."""
    step = _step(1, "tighten alpha bolt")
    blocks = vd.blocks_from_transcript(_transcript(["tighten alpha bolt"]))
    timestamp = datetime.now(timezone.utc).isoformat()
    adapter = _ScriptedAdapter(
        {
            "judgements": [
                {"step_id": step.identity.step_id, "block_ids": [1], "confidence": 0.9, "judged_at": timestamp},
                {"step_id": "invented", "block_ids": [999], "confidence": 0.9, "judged_at": timestamp},
            ]
        }
    )
    log = vd.JudgementLog(tmp_path / "judgements.json")

    judgements = await vd.judge_alignment(adapter, [step], blocks, judged=set(), model_name="test-model")
    log.record("https://example.test/video", judgements)

    assert [judgement.step_id for judgement in judgements] == [step.identity.step_id]
    assert log.judged("https://example.test/video") == {step.identity.step_id}
    card = _card([step])
    await vd.align_video(
        card,
        uri="https://example.test/video",
        transcript=_transcript(["unrelated vocabulary"]),
        adapter=adapter,
        judgement_log=log,
        force=True,
    )
    assert adapter.calls == 2


async def test_align_video_low_coverage_overview(tmp_path) -> None:
    """Low transcript coverage yields only an overview media reference."""
    steps = [_step(index, f"operation token{index}") for index in range(1, 11)]
    card = _card(steps)

    refs, links, report = await vd.align_video(
        card,
        uri="https://example.test/video",
        transcript=_transcript(["operation token1", "operation token2"]),
        adapter=None,
        judgement_log=vd.JudgementLog(tmp_path / "judgements.json"),
    )

    assert report.coverage == pytest.approx(0.2)
    assert report.overview_only
    assert len(refs) == len(links) == 1
    assert refs[0].kind == "video_segment"
    assert links[0].role == "overview"

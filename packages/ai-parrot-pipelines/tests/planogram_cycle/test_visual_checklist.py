"""FEAT-685 (TASK-4365): opt-in visual_features checklist — counted zone evidence and its rule."""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import (
    RuleBinding,
    SlotsDefinitionError,
    load_slots_definition,
    validate_bindings,
)
from parrot_pipelines.planogram.comparison.rules import evaluate_rules
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    RuleOutcome,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.identification.evidence import (
    ChecklistCount,
    ZoneEvidenceAnswer,
    build_zone_prompt,
    collect_rule_evidence,
)

SHAQ = "Shaquille O'Neal"
THUMBS = "person giving a thumbs up"
GAMER = "person wearing headphones and holding a game controller"
CHECKLIST = [{"feature": SHAQ, "min_count": 2}, {"feature": THUMBS}, {"feature": GAMER}]


class InlineExecutor:
    """Run crop helpers inline."""

    async def run(self, fn, *args):
        """Invoke the CPU helper directly."""
        return fn(*args)


class RecordingVision:
    """Return one queued answer per call and keep the prompts."""

    def __init__(self, *answers):
        """Store the answers in request order."""
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        """Record the prompt and return the next answer."""
        self.prompts.append(prompt)
        return self.answers.pop(0)


def _box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _zone_shape(image_id: str = "img0", shape_id: str = "img0:zone0") -> Shape:
    return Shape(
        shape_id=shape_id,
        image_id=image_id,
        kind=ShapeKind.ZONE,
        box=_box(20, 10, 380, 80),
        membership=FixtureMembership.ON_FIXTURE,
        membership_evidence=["zone_selector:zone-header-1"],
        source=ObservationSource.CV,
    )


def _binding(**params: object) -> RuleBinding:
    return RuleBinding(
        rule_id="visual_features:zone-header-1", kind="visual_features", target_id="zone-header-1", params=params
    )


def _definition():
    return load_slots_definition(
        {
            "shelves": [{"shelf_id": "s1", "shelf_number": 1, "level": "header", "facings": []}],
            "zones": [{"zone_id": "zone-header-1", "kind": "header", "shelf_id": "s1"}],
        }
    )


# --------------------------------------------------------------------------- prompt


def test_zone_prompt_without_checklist_is_unchanged() -> None:
    for flags in itertools.product([False, True], repeat=3):
        assert build_zone_prompt(*flags) == build_zone_prompt(*flags, checklist=())
        assert "checklist" not in build_zone_prompt(*flags).lower()


def test_zone_prompt_lists_checklist_features() -> None:
    prompt = build_zone_prompt(False, True, checklist=[SHAQ, THUMBS])
    assert f"- {SHAQ}" in prompt and f"- {THUMBS}" in prompt
    assert "number of distinct instances" in prompt
    assert prompt.rstrip().endswith("Provide one concise evidence sentence.")


# --------------------------------------------------------------------------- evidence


@pytest.mark.asyncio
async def test_checklist_observation_recorded() -> None:
    answer = ZoneEvidenceAnswer(
        visual_features=["two photos of Shaquille O'Neal"],
        checklist=[ChecklistCount(feature=SHAQ, count=2), ChecklistCount(feature=THUMBS, count=1)],
    )
    vision = RecordingVision(answer)
    ctx = CycleContext(vision=vision, executor=InlineExecutor(), bindings=[_binding(checklist=CHECKLIST)])
    observations = await collect_rule_evidence(
        np.zeros((300, 400, 3), np.uint8),
        PerceptionResult(image_id="img0", image_size=(400, 300), zones=[_zone_shape()]),
        ctx,
    )
    by_kind = {observation.kind: observation for observation in observations}
    assert by_kind["visual_features"].value == ["two photos of Shaquille O'Neal"]
    checklist = by_kind["visual_checklist"]
    assert checklist.value == {SHAQ: 2, THUMBS: 1, GAMER: -1}
    assert all(isinstance(count, int) for count in checklist.value.values())
    assert checklist.assessed and checklist.target_id == "img0:zone0"
    assert f"- {GAMER}" in vision.prompts[0]


@pytest.mark.asyncio
async def test_no_checklist_no_checklist_observation() -> None:
    vision = RecordingVision(ZoneEvidenceAnswer(visual_features=["logo"]))
    ctx = CycleContext(vision=vision, executor=InlineExecutor(), bindings=[_binding(expected=["logo"])])
    observations = await collect_rule_evidence(
        np.zeros((300, 400, 3), np.uint8),
        PerceptionResult(image_id="img0", image_size=(400, 300), zones=[_zone_shape()]),
        ctx,
    )
    assert [observation.kind for observation in observations] == ["visual_features"]
    assert "checklist" not in vision.prompts[0].lower()


# --------------------------------------------------------------------------- rule


def _evaluate(binding: RuleBinding, images: list[tuple[str, dict[str, int] | None, list[str]]]) -> RuleOutcome:
    """Evaluate one binding; each image carries its checklist counts and its neutral features."""
    perceptions = [
        PerceptionResult(image_id=image_id, image_size=(400, 300), zones=[_zone_shape(image_id, f"{image_id}:zone0")])
        for image_id, _, _ in images
    ]
    identifications = []
    for image_id, counts, features in images:
        observations = [
            RuleObservation(
                image_id=image_id,
                target_id=f"{image_id}:zone0",
                kind="visual_features",
                value=features,
                assessed=True,
                source=ObservationSource.LLM,
            )
        ]
        if counts is not None:
            observations.append(
                RuleObservation(
                    image_id=image_id,
                    target_id=f"{image_id}:zone0",
                    kind="visual_checklist",
                    value=counts,
                    assessed=any(count >= 0 for count in counts.values()),
                    source=ObservationSource.LLM,
                )
            )
        identifications.append(
            IdentificationResult(image_id=image_id, identifications=[], rule_observations=observations)
        )
    context = CycleContext(definition=_definition(), bindings=[binding], layout=SimpleNamespace(zone_selectors=[]))
    return evaluate_rules(perceptions, identifications, [], context)[binding.rule_id]


def test_rule_visual_checklist_pass() -> None:
    outcome = _evaluate(_binding(checklist=CHECKLIST), [("img0", {SHAQ: 2, THUMBS: 1, GAMER: 1}, [])])
    assert outcome.assessed and outcome.passed and outcome.score == 1.0 and outcome.detail is None


def test_rule_visual_checklist_count_short() -> None:
    outcome = _evaluate(_binding(checklist=CHECKLIST), [("img0", {SHAQ: 1, THUMBS: 1, GAMER: 1}, [])])
    assert outcome.assessed and not outcome.passed
    assert outcome.score == pytest.approx(2 / 3)
    assert outcome.detail == f"{SHAQ}: 1 (expected >= 2)"


def test_rule_visual_checklist_max_across_images() -> None:
    outcome = _evaluate(
        _binding(checklist=CHECKLIST),
        [("img0", {SHAQ: 1, THUMBS: 1, GAMER: -1}, []), ("img1", {SHAQ: 2, THUMBS: 0, GAMER: 1}, [])],
    )
    assert outcome.passed and outcome.score == 1.0


def test_rule_visual_checklist_unknown() -> None:
    unknown = _evaluate(_binding(checklist=CHECKLIST), [("img0", {SHAQ: -1, THUMBS: -1, GAMER: -1}, [])])
    assert not unknown.assessed
    partial = _evaluate(_binding(checklist=CHECKLIST), [("img0", {SHAQ: 2, THUMBS: 1, GAMER: -1}, [])])
    assert partial.assessed and not partial.passed
    assert partial.detail == f"{GAMER}: unknown (expected >= 1)"


def test_rule_visual_without_checklist_unchanged() -> None:
    binding = _binding(expected=["Shaquille O'Neal", "thumbs up"])
    outcome = _evaluate(binding, [("img0", None, ["Shaquille O'Neal promotional photos"])])
    assert outcome.assessed and outcome.passed and outcome.score == 0.5


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "checklist",
    [
        [],
        "Shaquille O'Neal",
        [SHAQ],
        [{"min_count": 2}],
        [{"feature": "  "}],
        [{"feature": SHAQ, "min_count": 0}],
        [{"feature": SHAQ, "min_count": "2"}],
        [{"feature": SHAQ, "min_count": True}],
    ],
)
def test_validate_bindings_rejects_bad_checklist(checklist: object) -> None:
    config = {"rule_bindings": [_binding(checklist=checklist).model_dump()]}
    with pytest.raises(SlotsDefinitionError):
        validate_bindings(_definition(), config)


def test_validate_bindings_accepts_checklist() -> None:
    present = RuleBinding(rule_id="zone_present:zone-header-1", kind="zone_present", target_id="zone-header-1")
    config = {"rule_bindings": [present.model_dump(), _binding(checklist=CHECKLIST).model_dump()]}
    assert validate_bindings(_definition(), config)[1].params["checklist"] == CHECKLIST

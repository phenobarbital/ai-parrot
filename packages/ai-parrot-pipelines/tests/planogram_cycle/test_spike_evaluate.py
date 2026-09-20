"""Offline tests for the spike evaluator, loaded by path (examples/ is not a package)."""

import importlib.util
import sys
from pathlib import Path

import pytest

_EVALUATE = Path(__file__).resolve().parents[4] / "examples/planogram/perception_spike/evaluate.py"
_ALL_SYNTHETIC = {"partial_shelf": True, "absent_anchors": True, "adjacent_fixture": True}


@pytest.fixture(scope="module")
def ev():
    """The evaluator module, loaded from its file path."""
    spec = importlib.util.spec_from_file_location("perception_spike_evaluate", _EVALUATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # pydantic resolves postponed annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _photo(ev, index, recall=1.0, precision=1.0, admitted=0, conditions=("partial_view",)):
    """A synthetic PhotoResult with the given slot metrics."""
    return ev.PhotoResult(
        index=index,
        conditions=list(conditions),
        per_profile=[],
        slot_precision=precision,
        slot_recall=recall,
        off_fixture_proposals=0,
        off_fixture_admitted=admitted,
    )


def _three_photos(ev, **overrides):
    """Three evaluable photos exercising every required condition."""
    return [
        _photo(ev, 1, conditions=("partial_view",), **overrides),
        _photo(ev, 2, conditions=("adjacent_fixture",)),
        _photo(ev, 3, conditions=("absent_anchors",)),
    ]


def test_iou_identity_disjoint_and_degenerate(ev):
    """Identical ⇒ 1.0, disjoint ⇒ 0.0, degenerate ⇒ 0.0, symmetric."""
    assert ev.iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert ev.iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert ev.iou((0, 0, 0, 10), (0, 0, 10, 10)) == 0.0
    a, b = (0, 0, 10, 10), (5, 0, 15, 10)
    assert ev.iou(a, b) == pytest.approx(ev.iou(b, a)) == pytest.approx(50 / 150)


def test_spike_evaluator_one_to_one_matching(ev):
    """AC-2: a duplicate proposal over one truth is a false positive, not a second match."""
    annotation = ev.PhotoAnnotation(
        image="x.jpg",
        image_size=(200, 100),
        objects=[
            ev.AnnotatedObject(id="t1", kind="price_tag", box=(0, 0, 20, 10)),
            ev.AnnotatedObject(id="t2", kind="price_tag", box=(50, 0, 70, 10)),
        ],
    )
    proposals = [
        ev.Proposal(profile="price_tag", kind="price_tag", box=(0, 0, 20, 10)),
        ev.Proposal(profile="price_tag", kind="price_tag", box=(1, 0, 20, 10)),  # duplicate of t1
        ev.Proposal(profile="price_tag", kind="price_tag", box=(50, 0, 70, 10)),
    ]
    result = ev.evaluate_photo(1, annotation, proposals, {"price_tag": "price_tag"})
    metrics = result.per_profile[0]
    assert (metrics.true_positives, metrics.false_positives, metrics.false_negatives) == (2, 1, 0)
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(1.0)


def test_matching_is_deterministic_on_ties(ev):
    """Equal IoU ⇒ lower proposal index, then lower truth index wins."""
    matches = ev.match_one_to_one([(0, 0, 10, 10), (0, 0, 10, 10)], [(0, 0, 10, 10)])
    assert matches == [(0, 0, pytest.approx(1.0))]
    matches = ev.match_one_to_one([(0, 0, 10, 10)], [(0, 0, 10, 10), (0, 0, 10, 10)])
    assert matches == [(0, 0, pytest.approx(1.0))]


def test_evaluate_photo_counts_off_fixture_and_tristate_admission(ev):
    """Off-fixture proposals are counted; admission is None unless membership was evaluated."""
    annotation = ev.PhotoAnnotation(
        image="x.jpg",
        image_size=(400, 200),
        conditions=["adjacent_fixture"],
        objects=[
            ev.AnnotatedObject(id="p1", kind="product", box=(200, 50, 260, 150), slot_target=True),
            ev.AnnotatedObject(id="d1", kind="product", box=(10, 50, 70, 150), membership="off_fixture"),
        ],
    )
    unevaluated = [
        ev.Proposal(profile="body", kind="product", box=(200, 50, 260, 150)),
        ev.Proposal(profile="body", kind="product", box=(10, 50, 70, 150)),
    ]
    result = ev.evaluate_photo(1, annotation, unevaluated, {"body": "product"})
    assert result.off_fixture_proposals == 1
    assert result.off_fixture_admitted is None
    assert result.slot_recall == pytest.approx(1.0)
    assert result.slot_precision == pytest.approx(0.5)  # the distractor pollutes the slot proposals

    evaluated = [p.model_copy(update={"admitted": i == 0}) for i, p in enumerate(unevaluated)]
    result = ev.evaluate_photo(1, annotation, evaluated, {"body": "product"})
    assert result.off_fixture_admitted == 0
    assert result.slot_precision == pytest.approx(1.0)  # rejected by membership ⇒ not a slot proposal


def test_outcome_inconclusive_without_photos(ev):
    """No photos ⇒ inconclusive."""
    outcome, gates = ev.decide_outcome([], dict(_ALL_SYNTHETIC))
    assert outcome == "inconclusive"
    assert gates["slot_recall"] == "untested"


def test_outcome_inconclusive_when_membership_untested(ev):
    """An untested membership gate ⇒ inconclusive even if everything else passes."""
    outcome, gates = ev.decide_outcome(_three_photos(ev, admitted=None), dict(_ALL_SYNTHETIC))
    assert outcome == "inconclusive"
    assert gates["off_fixture_admitted"] == "untested"


def test_outcome_inconclusive_when_condition_never_exercised(ev):
    """A required condition never exercised on a real photo ⇒ inconclusive."""
    photos = [_photo(ev, i, conditions=("full_view",)) for i in (1, 2, 3)]
    outcome, _ = ev.decide_outcome(photos, dict(_ALL_SYNTHETIC))
    assert outcome == "inconclusive"


def test_outcome_failed_when_a_photo_misses_recall(ev):
    """One photo under the recall gate ⇒ failed."""
    outcome, gates = ev.decide_outcome(_three_photos(ev, recall=0.5), dict(_ALL_SYNTHETIC))
    assert outcome == "failed"
    assert gates["slot_recall"] == "failed"


def test_outcome_passed_only_when_every_gate_passes(ev):
    """Every gate passed ⇒ passed; a failing synthetic case ⇒ failed."""
    outcome, gates = ev.decide_outcome(_three_photos(ev), dict(_ALL_SYNTHETIC))
    assert outcome == "passed"
    assert set(gates.values()) == {"passed"}
    outcome, gates = ev.decide_outcome(_three_photos(ev), {**_ALL_SYNTHETIC, "adjacent_fixture": False})
    assert outcome == "failed"
    assert gates["synthetic"] == "failed"

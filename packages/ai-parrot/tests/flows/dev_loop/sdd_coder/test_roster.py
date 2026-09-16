import itertools

import pytest

from parrot.flows.dev_loop.task_scheduler import TaskRef
from parrot.flows.dev_loop.sdd_coder import ChunkAssigner, RosterConfig, RosterProbe, RosterSeat, available_seats
from parrot.flows.dev_loop.sdd_coder.roster import eligible_seats
from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityAssessment,
    ComplexityContract,
    ComplexityEvidence,
    ComplexityPolicy,
    StrongModelIdentity,
)


def _roster(n):
    seats = [
        RosterSeat(label="q", backend="nova"),
        RosterSeat(label="g", backend="nvidia"),
        RosterSeat(label="c", backend="codex"),
        RosterSeat(label="h", kind="native"),
    ]
    return RosterConfig(seats=seats[:n])


def _wave(n):
    return [TaskRef(id=f"TASK-{i:04d}", status="pending") for i in range(n)]


@pytest.mark.parametrize("tasks,seats", list(itertools.product(range(1, 21), range(1, 5))))
def test_assign_distinct_seats_per_chunk(tasks, seats):
    chunks = ChunkAssigner(_roster(seats).seats).assign(_wave(tasks), {})
    for ch in chunks:
        labels = [t.seat_label for t in ch.tasks]
        assert len(labels) == len(set(labels)) and len(labels) <= seats


def test_assign_rotates_start_between_chunks():
    chunks = ChunkAssigner(_roster(4).seats).assign(_wave(5), {})
    assert chunks[1].tasks[0].seat_label == _roster(4).seats[1].label


def test_assign_single_seat_is_serial():
    assert all(len(c.tasks) == 1 for c in ChunkAssigner(_roster(1).seats).assign(_wave(6), {}))


def test_retry_seat_is_different():
    a = ChunkAssigner(_roster(3).seats)
    assert a.retry_seat("q", {"q"}).label != "q"
    assert a.retry_seat("q", {"q", "g", "c"}) is None


async def test_probe_drops_seat_without_key():
    probe = RosterProbe(config_getter=lambda k, fallback=None: None, which=lambda b: None)
    res = await probe.probe(_roster(4))
    by = {r.label: r for r in res}
    assert not by["q"].available and "BEDROCK_MANTLE_API_KEY" in by["q"].reason
    assert not by["c"].available and by["h"].available


async def test_probe_codex_requires_binary():
    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: None)
    res = await probe.probe(RosterConfig(seats=[RosterSeat(label="c", backend="codex")]))
    assert not res[0].available and "not found" in res[0].reason


async def test_probe_native_always_available():
    probe = RosterProbe(config_getter=lambda k, fallback=None: None, which=lambda b: None)
    res = await probe.probe(RosterConfig(seats=[RosterSeat(label="h", kind="native")]))
    assert res[0].available


async def test_probe_switches_to_fallback_model():
    async def smoke(seat, model):
        return model == "fb"

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    seat = RosterSeat(label="c", backend="codex", model="primary", fallback_model="fb")
    res = (await probe.probe(RosterConfig(seats=[seat])))[0]
    assert res.available and res.fallback_used and res.model_used == "fb"
    assert available_seats(RosterConfig(seats=[seat]), [res])[0].model == "fb"


async def test_probe_never_raises():
    async def smoke(seat, model):
        raise RuntimeError("boom")

    probe = RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/bin/x", smoke=smoke)
    res = (await probe.probe(_roster(1)))[0]
    assert not res.available and "boom" in res.reason


def test_assign_exclusive_tasks_run_alone_and_first():
    wave = _wave(4)
    wave[2] = TaskRef(id="TASK-0002", status="pending", parallel=False)
    chunks = ChunkAssigner(_roster(4).seats).assign(wave, {})
    assert [[t.task_id for t in c.tasks] for c in chunks] == [["TASK-0002"], ["TASK-0000", "TASK-0001", "TASK-0003"]]


def _assessment(classification: str) -> ComplexityAssessment:
    evidence = ComplexityEvidence(
        task_id="TASK-0001",
        contract=ComplexityContract(targets=()),
        metrics={},
        head_sha="abc",
        task_sha256="abc",
        index_sha256="abc",
        policy_sha256="abc",
        target_hashes={},
        wiki_evidence_hashes={},
        collector_versions={},
        details={},
    )
    return ComplexityAssessment(
        policy_version="v1",
        task_id="TASK-0001",
        classification=classification,
        total_points=0 if classification == "standard" else 10,
        component_points={},
        reason_codes=(),
        evidence=evidence,
        assessment_id="abc",
    )


def test_eligible_seats_standard_returns_all_seats_unchanged():
    policy = ComplexityPolicy(
        strong_models=(StrongModelIdentity(canonical_model="sonnet-5", backend="codex", model="claude-3-5-sonnet"),)
    )
    seats = [
        RosterSeat(label="q", backend="nova", model="nova-model"),
        RosterSeat(label="c", backend="codex", model="claude-3-5-sonnet"),
    ]
    res = eligible_seats(_assessment("standard"), seats, policy)
    assert res == seats


def test_eligible_seats_complex_restricts_to_strong_models():
    policy = ComplexityPolicy(
        strong_models=(
            StrongModelIdentity(canonical_model="sonnet-5", backend="codex", model="claude-3-5-sonnet"),
            StrongModelIdentity(canonical_model="native-sonnet", backend="native", model="claude-3-5-sonnet-native"),
        )
    )
    seats = [
        RosterSeat(label="q", backend="nova", model="nova-model"),
        RosterSeat(label="c", backend="codex", model="claude-3-5-sonnet"),
        RosterSeat(label="h", kind="native", model="claude-3-5-sonnet-native"),
    ]
    res = eligible_seats(_assessment("complex"), seats, policy)
    assert [s.label for s in res] == ["c", "h"]


def test_eligible_seats_unknown_restricts_like_complex():
    policy = ComplexityPolicy(
        strong_models=(StrongModelIdentity(canonical_model="sonnet-5", backend="codex", model="claude-3-5-sonnet"),)
    )
    seats = [
        RosterSeat(label="q", backend="nova", model="nova-model"),
        RosterSeat(label="c", backend="codex", model="claude-3-5-sonnet"),
    ]
    res = eligible_seats(_assessment("unknown"), seats, policy)
    assert [s.label for s in res] == ["c"]


def test_eligible_seats_no_alias_match():
    """A seat model that merely resembles a strong candidate (e.g. 'sonnet'
    instead of the exact configured 'claude-3-5-sonnet') is never eligible."""
    policy = ComplexityPolicy(
        strong_models=(StrongModelIdentity(canonical_model="sonnet-5", backend="codex", model="claude-3-5-sonnet"),)
    )
    seats = [RosterSeat(label="c", backend="codex", model="sonnet")]
    assert eligible_seats(_assessment("complex"), seats, policy) == []


def test_assign_with_eligible_labels_distinct_seats_per_chunk():
    seats = [
        RosterSeat(label="q", backend="nova", model="nova-model"),
        RosterSeat(label="c", backend="codex", model="claude-3-5-sonnet"),
    ]
    assigner = ChunkAssigner(seats)
    wave = _wave(3)
    eligible_labels = {
        "TASK-0000": {"q", "c"},
        "TASK-0001": {"c"},
        "TASK-0002": {"q"},
    }
    chunks = assigner.assign(wave, {}, eligible_labels=eligible_labels)
    assert [[(t.task_id, t.seat_label) for t in c.tasks] for c in chunks] == [
        [("TASK-0000", "q"), ("TASK-0001", "c")],
        [("TASK-0002", "q")],
    ]


def test_assign_closes_chunk_early_when_eligible_seat_already_used():
    """When the only eligible seat for the next task is already used in the
    current chunk, that chunk is closed early rather than filling the gap
    with an ineligible seat (spec "Models and dispatch rules")."""
    seats = [
        RosterSeat(label="q", backend="nova", model="nova-model"),
        RosterSeat(label="c", backend="codex", model="claude-3-5-sonnet"),
    ]
    assigner = ChunkAssigner(seats)
    wave = _wave(2)
    # Both tasks are only eligible for "c" -- the second cannot share a chunk
    # with the first since a chunk uses each seat at most once.
    eligible_labels = {"TASK-0000": {"c"}, "TASK-0001": {"c"}}
    chunks = assigner.assign(wave, {}, eligible_labels=eligible_labels)
    assert [[(t.task_id, t.seat_label) for t in c.tasks] for c in chunks] == [
        [("TASK-0000", "c")],
        [("TASK-0001", "c")],
    ]


def test_assign_with_missing_eligible_labels_raises():
    seats = [RosterSeat(label="q", backend="nova", model="nova-model")]
    assigner = ChunkAssigner(seats)
    wave = _wave(2)
    with pytest.raises(ValueError):
        assigner.assign(wave, {}, eligible_labels={"TASK-0000": {"q"}})


def test_assign_with_empty_eligible_labels_raises():
    seats = [RosterSeat(label="q", backend="nova", model="nova-model")]
    assigner = ChunkAssigner(seats)
    wave = _wave(1)
    with pytest.raises(ValueError):
        assigner.assign(wave, {}, eligible_labels={"TASK-0000": set()})


def test_retry_seat_with_eligible_labels():
    seats = [
        RosterSeat(label="q", backend="nova", model="nova-model"),
        RosterSeat(label="g", backend="nvidia", model="nvidia-model"),
        RosterSeat(label="c", backend="codex", model="claude-3-5-sonnet"),
    ]
    assigner = ChunkAssigner(seats)
    res = assigner.retry_seat("q", {"q"}, eligible_labels={"c"})
    assert res is not None
    assert res.label == "c"


def test_retry_seat_with_eligible_labels_none_match_returns_none():
    seats = [
        RosterSeat(label="q", backend="nova", model="nova-model"),
        RosterSeat(label="g", backend="nvidia", model="nvidia-model"),
    ]
    assigner = ChunkAssigner(seats)
    assert assigner.retry_seat("q", {"q"}, eligible_labels={"c"}) is None

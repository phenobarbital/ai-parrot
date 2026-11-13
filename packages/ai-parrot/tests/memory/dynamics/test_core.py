"""Behavioral acceptance tests for pure FSRS transition and retrievability."""

from datetime import datetime

import pytest

from parrot.memory.dynamics import fsrs
from parrot.memory.dynamics.fsrs import retrievability, transition
from parrot.memory.dynamics.models import Grade, MemoryParameters, MemoryState


def _parameters(*, time_policy: str = "days-v1", parameter_id: str = "fsrs-6-default") -> MemoryParameters:
    """Return the accepted immutable parameter set."""
    return MemoryParameters(
        algorithm="fsrs-6",
        time_policy=time_policy,
        parameter_id=parameter_id,
        provenance="py-fsrs-v6.3.2",
    )


@pytest.mark.parametrize(
    ("grade", "expected_stability", "expected_difficulty"),
    (
        (Grade.AGAIN, 0.212, 6.4133),
        (Grade.HARD, 1.2931, 5.112170705601056),
        (Grade.GOOD, 2.3065, 2.118103970459016),
        (Grade.EASY, 8.2956, 1.0),
    ),
)
def test_reference_parity_all_grades(
    grade: Grade,
    expected_stability: float,
    expected_difficulty: float,
) -> None:
    """Match pinned FSRS-6 initial vectors and the accepted all-grade sequence."""
    parameters = _parameters()
    initial = MemoryState()
    first_at = datetime.fromisoformat("2026-01-01T00:00:00+00:00")

    result = transition(initial, grade, reviewed_at=first_at, parameters=parameters)

    assert result.stability == pytest.approx(expected_stability, abs=1e-12)
    assert result.difficulty == pytest.approx(expected_difficulty, abs=1e-12)
    assert result.review_count == 1
    assert result.apply_revision == 1
    assert result.parameter_id == parameters.parameter_id
    assert initial == MemoryState()

    if grade == Grade.GOOD:
        sequence = (
            (Grade.HARD, "2026-01-01T00:05:00+00:00", 2.3065, 4.752858488532557),
            (Grade.EASY, "2026-01-08T00:00:00+00:00", 25.472308857157397, 2.984736681491411),
            (Grade.AGAIN, "2026-04-08T00:00:00+00:00", 2.661428283374772, 7.679359020293631),
        )
        for next_grade, reviewed_at, stability, difficulty in sequence:
            result = transition(
                result,
                next_grade,
                reviewed_at=datetime.fromisoformat(reviewed_at),
                parameters=parameters,
            )
            assert result.stability == pytest.approx(stability, abs=1e-9)
            assert result.difficulty == pytest.approx(difficulty, abs=1e-9)
        assert result.review_count == 4
        assert result.apply_revision == 4


def test_same_day_and_out_of_order() -> None:
    """Apply the reference short-term branch to same-day and out-of-order reviews."""
    parameters = _parameters()
    first_at = datetime.fromisoformat("2026-01-02T00:00:00+00:00")
    state = transition(MemoryState(), Grade.GOOD, reviewed_at=first_at, parameters=parameters)

    same_day = transition(
        state,
        Grade.HARD,
        reviewed_at=datetime.fromisoformat("2026-01-02T00:05:00+00:00"),
        parameters=parameters,
    )
    out_of_order = transition(
        state,
        Grade.HARD,
        reviewed_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        parameters=parameters,
    )

    assert same_day.stability == pytest.approx(state.stability, abs=1e-12)
    assert out_of_order.stability == pytest.approx(same_day.stability, abs=1e-12)
    assert out_of_order.difficulty == pytest.approx(same_day.difficulty, abs=1e-12)
    assert retrievability(state, now=datetime.fromisoformat("2025-12-01T00:00:00+00:00"), parameters=parameters) == 1.0
    assert state.reviewed_at == first_at

    later_at = datetime.fromisoformat("2026-01-03T12:00:00+00:00")
    days_state = transition(state, Grade.GOOD, reviewed_at=later_at, parameters=parameters)
    hours_parameters = _parameters(time_policy="hours-v1", parameter_id="fsrs-6-hours")
    hours_initial = transition(MemoryState(), Grade.GOOD, reviewed_at=first_at, parameters=hours_parameters)
    hours_state = transition(hours_initial, Grade.GOOD, reviewed_at=later_at, parameters=hours_parameters)
    assert days_state.stability != hours_state.stability

    with pytest.raises(ValueError, match="parameter_id"):
        transition(
            state,
            Grade.GOOD,
            reviewed_at=datetime.fromisoformat("2026-01-03T00:00:00+00:00"),
            parameters=_parameters(parameter_id="refit-v2"),
        )
    with pytest.raises(ValueError, match="parameter_id"):
        retrievability(
            state,
            now=datetime.fromisoformat("2026-01-03T00:00:00+00:00"),
            parameters=_parameters(parameter_id="refit-v2"),
        )


def test_legacy_neutral_and_no_global_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy state neutral and require callers to supply every evaluation clock."""
    parameters = _parameters()
    evaluation_at = datetime.fromisoformat("2026-01-01T00:00:00+00:00")

    class ClockTrap:
        """Fail if production code attempts to obtain an ambient clock."""

        @classmethod
        def now(cls) -> datetime:
            """Reject access to a global clock."""
            raise AssertionError("global clock accessed")

    monkeypatch.setattr(fsrs, "datetime", ClockTrap)
    neutral = MemoryState()
    assert retrievability(neutral, now=evaluation_at, parameters=parameters) == 1.0

    reviewed = transition(neutral, Grade.GOOD, reviewed_at=evaluation_at, parameters=parameters)
    assert retrievability(reviewed, now=evaluation_at, parameters=parameters) == 1.0
    after_ninety_days = retrievability(
        reviewed,
        now=datetime.fromisoformat("2026-04-01T00:00:00+00:00"),
        parameters=parameters,
    )
    assert 0.0 < after_ninety_days < 1.0
    assert reviewed.reviewed_at == evaluation_at
    assert parameters.time_policy == "days-v1"

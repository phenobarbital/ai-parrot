"""Golden tests for derive_conditions (FEAT-598 S5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import parrot.outputs.a2ui.linked as linked
from parrot.outputs.a2ui.linked.conditions import LANE_TIME_KEYS, derive_conditions, locked_values
from parrot.outputs.a2ui.linked.models import SourceRequest

FIXTURES = Path(linked.__file__).parent / "contract" / "fixtures" / "conditions"
CASES = sorted(FIXTURES.glob("*.json"))


@pytest.mark.parametrize("path", CASES, ids=[p.stem for p in CASES])
def test_derive_conditions_golden(path: Path) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    got = derive_conditions(SourceRequest.model_validate(case["request"]), locked=case["locked"])
    assert got == case["expected"]
    assert list(got) == list(case["expected"])  # key order is contractual


def test_fixture_dir_not_empty() -> None:
    assert len(CASES) >= 4


def test_never_emits_lane_time_keys() -> None:
    request = SourceRequest(placeholders={"a": 1}, limit=50, offset=5)
    got = derive_conditions(request, locked={})
    forbidden = LANE_TIME_KEYS | {"limit"}
    assert not (forbidden & got.keys())


def test_request_not_mutated() -> None:
    request = SourceRequest(
        placeholders={"program": "pokemon"},
        filter={"region": ["East"]},
        fields=["day"],
        ordering=["day"],
        grouping=["program"],
        limit=10,
        offset=5,
    )
    before = request.model_dump()
    derive_conditions(request, locked={"program": "epson", "store_id": 42})
    after = request.model_dump()
    assert before == after


def test_locked_values_reads_conditions(linked_source) -> None:
    source = linked_source.model_copy(update={"locked": ["firstdate"]})
    assert locked_values(source) == {"firstdate": "YESTERDAY"}


def test_lazy_export() -> None:
    from parrot.outputs.a2ui.linked import derive_conditions as exported

    assert exported is derive_conditions

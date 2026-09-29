"""FEAT-611 M8 / §9 S6 — Python side of the shared Epson parity fixture (conditions, ignored params, rows)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import parrot.outputs.a2ui.linked as linked_pkg
from parrot.outputs.a2ui.linked import executor as executor_mod
from parrot.outputs.a2ui.linked.dsl import apply_transform, frame_from_records, frame_to_records
from parrot.outputs.a2ui.linked.models import LinkedDataSource

FIXTURE = json.loads(
    (Path(linked_pkg.__file__).parent / "contract/fixtures/parity/epson_dashboard_params.json").read_text()
)


def _descriptor(key: str) -> LinkedDataSource:
    raw = FIXTURE["locked_source"] if key == "activity_locked" else FIXTURE["sources"][key]
    return LinkedDataSource.model_validate(raw)


@pytest.mark.parametrize("case", FIXTURE["param_cases"], ids=lambda c: c["id"])
def test_parity_conditions(case):
    conditions, ignored = executor_mod._conditions_for(
        _descriptor(case["source"]), case["overrides"], max_fetch_rows=FIXTURE["max_fetch_rows"]
    )
    assert conditions == case["expected_conditions"]
    assert list(conditions) == list(case["expected_conditions"])  # key order is part of the contract
    assert ignored == case["expected_ignored"]


def test_parity_rows():
    raw = {slug: frame_from_records(rows) for slug, rows in FIXTURE["input_frames"].items()}
    frames: dict = {}
    for key in ("targets", "activity", "daily", "attainment", "kpis"):  # dependency order (targets first)
        src = _descriptor(key)
        frames[key] = apply_transform(raw[src.slug], src.transform, frames=frames)
        assert frame_to_records(frames[key]) == FIXTURE["expected_rows"][key], key

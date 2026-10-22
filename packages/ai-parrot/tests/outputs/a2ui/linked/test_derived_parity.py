"""Linked dashboards — Python side of the shared derived-sources parity fixture (order, fetches, params, rows)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import parrot.outputs.a2ui.linked as linked_pkg
from parrot.outputs.a2ui.linked import executor as executor_mod
from parrot.outputs.a2ui.linked.dsl import frame_from_records, frame_to_records
from parrot.outputs.a2ui.linked.executor import execute_sources, execution_order
from parrot.outputs.a2ui.linked.models import LinkedSources
from parrot.tools.dataset_manager.sources import query_slug as qsmod

FIXTURE = json.loads((Path(linked_pkg.__file__).parent / "contract/fixtures/parity/derived_dashboard.json").read_text())
SOURCES = LinkedSources.model_validate(FIXTURE["sources"]).root


@pytest.fixture(autouse=True)
def _real_querysource(monkeypatch):
    for name in list(sys.modules):
        if name == "querysource" or name.startswith("querysource."):
            monkeypatch.delitem(sys.modules, name, raising=False)


def test_parity_order():
    order, failed = execution_order(SOURCES)
    assert order == FIXTURE["expected_order"]
    assert failed == {}


@pytest.mark.parametrize("case", FIXTURE["param_cases"], ids=lambda c: c["id"])
def test_parity_params(case):
    src = SOURCES[case["source"]]
    if src.kind == "derived":
        # A derived source has no conditions at all: every override is ignored.
        assert sorted(case["overrides"]) == case["expected_ignored"]
        return
    conditions, ignored = executor_mod._conditions_for(src, case["overrides"], max_fetch_rows=FIXTURE["max_fetch_rows"])
    assert conditions == case["expected_conditions"]
    assert ignored == case["expected_ignored"]


@pytest.mark.asyncio
async def test_parity_rows_and_fetches(monkeypatch):
    fetched: list[str] = []
    frames: dict[str, Any] = {slug: frame_from_records(rows) for slug, rows in FIXTURE["input_frames"].items()}

    class _FakeQS:
        def __init__(self, *, slug, conditions, **kwargs):
            self.slug = slug
            fetched.append(slug)

        async def query(self, output_format=None):
            return frames[self.slug], None

        async def close(self):
            return None

    monkeypatch.setattr(qsmod, "QS", None)
    monkeypatch.setattr(qsmod, "_get_qs", lambda: _FakeQS)

    outcome = await execute_sources(SOURCES, param_overrides={"by_program": FIXTURE["param_cases"][0]["overrides"]})

    assert [SOURCES[key].slug for key in FIXTURE["expected_fetches"]] == fetched
    assert list(outcome.frames) == FIXTURE["expected_order"]
    for key, rows in FIXTURE["expected_rows"].items():
        assert outcome.outcomes[key].error is None, key
        assert frame_to_records(outcome.frames[key]) == rows, key
    assert outcome.outcomes["by_program"].ignored_params == FIXTURE["param_cases"][0]["expected_ignored"]
    assert isinstance(outcome.frames["by_program"], pd.DataFrame)

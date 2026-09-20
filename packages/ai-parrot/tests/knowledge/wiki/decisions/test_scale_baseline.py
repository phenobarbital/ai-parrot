"""Inventory bound and the AC14 scale baseline (FEAT-578 Module 7).

AC14 asks for a RECORDED baseline, explicitly not a latency SLA. This module
measures and writes evidence; it asserts only correctness, never speed.
"""

from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionError, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService

#: Repo root, anchored to this file rather than ``Path.cwd()`` — importing
#: ``parrot`` (Navigator/navconfig) chdirs the process to wherever the
#: shared editable-install package root resolves, which is the MAIN
#: checkout even when pytest is invoked from inside a feature worktree.
#: A bare relative path would silently write this feature's own evidence
#: into a different checkout entirely.
_REPO_ROOT = Path(__file__).resolve().parents[6]

#: AC12: evidence is saved under artifacts/logs/.
BASELINE_REPORT = _REPO_ROOT / "artifacts" / "logs" / "feat-578-scale-baseline.json"

SYNTHETIC_RECORD_COUNT = 1000

_SMALL_BOUND = 5


def _seed(n: int) -> list[DecisionRecord]:
    return [
        DecisionRecord(decision_id=f"adr:doc:{i}", decision=f"decision number {i}", origin="documented")
        for i in range(n)
    ]


class TestInventoryBound:
    async def test_exceeding_max_records_is_an_explicit_error(self, adr_store):
        """AC14: an explicit error, never a silent 'no decisions'."""
        repo = DecisionRepository(adr_store, max_records=_SMALL_BOUND)
        for record in _seed(_SMALL_BOUND + 1):
            await repo.save(record, None)

        with pytest.raises(DecisionError) as exc:
            await repo.inventory()
        assert exc.value.code == "ADR_INVENTORY_LIMIT"

        service = DecisionService(adr_store, None, DecisionConfig(max_records=_SMALL_BOUND))
        with pytest.raises(DecisionError) as exc:
            await service.why("decision")
        assert exc.value.code == "ADR_INVENTORY_LIMIT"

    async def test_serialization_roundtrips_at_the_configured_bound(self, adr_store):
        """AC14: exactly max_records records still round-trip."""
        repo = DecisionRepository(adr_store, max_records=_SMALL_BOUND)
        seeded = _seed(_SMALL_BOUND)
        for record in seeded:
            await repo.save(record, None)

        records = await repo.inventory()
        assert len(records) == _SMALL_BOUND
        by_id = {r.decision_id: r for r in records}
        for record in seeded:
            assert by_id[record.decision_id] == record


class TestScaleBaseline:
    async def test_record_1000_adr_baseline(self, adr_store):
        """Measure and RECORD; assert correctness only (AC14)."""
        repo = DecisionRepository(adr_store, max_records=DecisionConfig().max_records)
        seeded = _seed(SYNTHETIC_RECORD_COUNT)

        tracemalloc.start()
        started = time.perf_counter()

        for record in seeded:
            await repo.save(record, None)

        service = DecisionService(adr_store, None, DecisionConfig())
        inventory = await repo.inventory()
        dossier = await service.why("decision")

        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert len(inventory) == SYNTHETIC_RECORD_COUNT
        # Every seeded record's decision text contains "decision", so this
        # query legitimately matches all 1000 hits and hits the packing
        # limit/budget — render.py correctly reports "partial" (not "ok")
        # whenever that happens. Assert the call succeeded and returned
        # real content, not the specific status a smaller corpus would get.
        assert dossier.status in ("ok", "partial")
        assert dossier.documented or dossier.candidates

        BASELINE_REPORT.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_REPORT.write_text(
            json.dumps(
                {
                    "feature": "FEAT-578",
                    "records": SYNTHETIC_RECORD_COUNT,
                    "elapsed_seconds": round(elapsed, 3),
                    "peak_memory_bytes": peak,
                    "note": "Baseline measurement only — AC14 asserts no latency SLA.",
                },
                indent=2,
            )
        )
        # Deliberately NO timing assertion here. AC14: "no unmeasured latency
        # SLA is asserted." Adding one would invent a contract the spec refuses.

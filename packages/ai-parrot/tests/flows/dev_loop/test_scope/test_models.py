"""Tests for the test-scope Pydantic boundary (`test_scope/models.py`).

`ScopePlanModel` is the only thing standing between `ScopePlan` and the JSON
emitted by `scripts/sdd/select_tests.py --json`, so a field added to the
dataclass but not to the mirror is lost silently — exactly how `cap_hits` /
`cap_impacted` went missing after FEAT-604 (ledger issue:ea746bd95a97).
`test_mirror_covers_every_scope_plan_field` fails on the next such omission.
"""

from __future__ import annotations

import dataclasses
import json
from types import MappingProxyType

from parrot.flows.dev_loop.test_scope.datatypes import CoreHit, Invocation, ScopePlan, TestTarget
from parrot.flows.dev_loop.test_scope.models import ScopePlanModel


def _plan(**overrides: object) -> ScopePlan:
    defaults: dict[str, object] = {
        "tier": "merge",
        "invocations": (
            Invocation(
                distribution="ai-parrot",
                argv=("pytest", "packages/ai-parrot/tests/a.py"),
                targets=(TestTarget(path="packages/ai-parrot/tests/a.py", distribution="ai-parrot", reason="declared"),),
            ),
        ),
        "escalated": ("ai-parrot",),
        "core_hits": (
            CoreHit(
                path="packages/ai-parrot/src/parrot/x.py",
                module="parrot.x",
                fanin=42,
                forced=False,
                distributions=("ai-parrot",),
            ),
        ),
        "skipped_escalations": ("ai-parrot-tools",),
        "notes": ("a note",),
    }
    defaults.update(overrides)
    return ScopePlan(**defaults)  # type: ignore[arg-type]


def test_mirror_covers_every_scope_plan_field() -> None:
    """Every ScopePlan field has a counterpart on the Pydantic mirror."""
    plan_fields = {f.name for f in dataclasses.fields(ScopePlan)}
    model_fields = set(ScopePlanModel.model_fields)

    assert plan_fields <= model_fields, f"ScopePlanModel is missing: {sorted(plan_fields - model_fields)}"


def test_from_plan_carries_cap_hits_and_cap_impacted() -> None:
    """cap_hits/cap_impacted survive the dataclass -> Pydantic conversion."""
    plan = _plan(
        cap_hits=MappingProxyType({"ai-parrot": ("parrot.a", "parrot.b")}),
        cap_impacted=MappingProxyType({"ai-parrot": "cap_exceeded"}),
    )

    model = ScopePlanModel.from_plan(plan)

    assert model.cap_hits == {"ai-parrot": ["parrot.a", "parrot.b"]}
    assert model.cap_impacted == {"ai-parrot": "cap_exceeded"}


def test_cap_attribution_reaches_the_json_cli_output() -> None:
    """The --json payload consumed by external tooling carries the cap attribution."""
    plan = _plan(
        cap_hits=MappingProxyType({"ai-parrot": ("parrot.a",)}),
        cap_impacted=MappingProxyType({"ai-parrot": "cap_exceeded"}),
    )

    payload = json.loads(ScopePlanModel.from_plan(plan).model_dump_json())

    assert payload["cap_hits"] == {"ai-parrot": ["parrot.a"]}
    assert payload["cap_impacted"] == {"ai-parrot": "cap_exceeded"}


def test_cap_fields_default_to_empty_when_absent() -> None:
    """A plan with no cap escalation mirrors as empty mappings, not null."""
    model = ScopePlanModel.from_plan(_plan())

    assert model.cap_hits == {}
    assert model.cap_impacted == {}


def test_from_plan_still_carries_the_pre_existing_fields() -> None:
    """The fields that already worked are unaffected by the cap additions."""
    model = ScopePlanModel.from_plan(_plan())

    assert model.tier == "merge"
    assert model.escalated == ["ai-parrot"]
    assert model.notes == ["a note"]
    assert model.skipped_escalations == ["ai-parrot-tools"]
    assert [inv.distribution for inv in model.invocations] == ["ai-parrot"]
    assert [hit.module for hit in model.core_hits] == ["parrot.x"]

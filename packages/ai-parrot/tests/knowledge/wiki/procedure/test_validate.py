"""Tests for the procedure graph validator (FEAT-891)."""

from typing import Any

import pytest

from parrot.knowledge.wiki.procedure.models import ProbeCost, ProcedureSpec
from parrot.knowledge.wiki.procedure.validate import validate_graph

PROBES: dict[str, ProbeCost] = {"spec.exists": "local", "pr.open": "remote"}


def _spec(node_id: str, **overrides: Any) -> ProcedureSpec:
    """Build a minimal procedure node with selected overrides."""
    return ProcedureSpec(**{"id": node_id, "title": node_id, "kind": "command", **overrides})


def _codes(specs: list[ProcedureSpec], **kwargs: Any) -> list[str]:
    """Return finding codes for ``specs``."""
    return [finding.code for finding in validate_graph(specs, known_probes=PROBES, **kwargs)]


@pytest.mark.parametrize(
    ("specs", "kwargs", "code"),
    [
        ([_spec("a", next=["missing"])], {}, "broken-edge"),
        ([_spec("a", requires_procedures=["b"]), _spec("b", requires_procedures=["a"])], {}, "requires-cycle"),
        ([_spec("a", preconditions=[{"probe": "missing"}])], {}, "unknown-probe"),
        (
            [
                _spec(
                    "a",
                    preconditions=[{"probe": "pr.open"}],
                    guards=[{"kind": "entry", "executable": "gh"}],
                )
            ],
            {},
            "remote-probe-in-guard",
        ),
        ([_spec("a", mode="mandatory")], {}, "mandatory-without-enforcement"),
        (
            [_spec("a", guards=[{"kind": "bypass", "executable": "mv"}])],
            {},
            "bypass-without-alternative",
        ),
        ([_spec("a", source="learned", confirm=True)], {}, "learned-mandatory"),
        ([_spec("a", command="sdd-task")], {"known_commands": ["sdd-done"]}, "uncovered-command"),
        ([_spec("a", advice="x" * 301)], {}, "advice-too-long"),
    ],
)
def test_validate_codes(specs: list[ProcedureSpec], kwargs: dict[str, Any], code: str) -> None:
    """Each finding code fires on its minimal graph."""
    assert code in _codes(specs, **kwargs)


def test_clean_graph_and_next_cycle() -> None:
    """A valid graph with a ``next`` cycle produces no finding."""
    specs = [
        _spec("a", next=["b"]),
        _spec("b", next=["a"], requires_procedures=["a"]),
    ]

    assert validate_graph(specs, known_probes=PROBES) == []


def test_findings_sorted_and_stable() -> None:
    """Two runs return the same list, sorted by ``(code, subjects)``."""
    specs = [_spec("b", advice="x" * 301, next=["missing"]), _spec("a", preconditions=[{"probe": "missing"}])]

    first = validate_graph(specs, known_probes=PROBES)
    second = validate_graph(specs, known_probes=PROBES)

    assert first == second
    assert [(finding.code, finding.subjects) for finding in first] == sorted(
        (finding.code, finding.subjects) for finding in first
    )


def test_edge_exemptions_do_not_require_procedure_targets() -> None:
    """Entity and provenance edges may point outside the procedure graph."""
    spec = _spec("a", applies_to=["Task"], learned_from=["history:1"])

    assert validate_graph([spec], known_probes=PROBES) == []


def test_requires_cycles_are_deduplicated_by_members() -> None:
    """A cycle is reported once with sorted member ids."""
    specs = [
        _spec("c", requires_procedures=["a"]),
        _spec("a", requires_procedures=["b"]),
        _spec("b", requires_procedures=["c"]),
    ]

    findings = validate_graph(specs, known_probes=PROBES)

    assert [(finding.code, finding.subjects) for finding in findings] == [("requires-cycle", ["a", "b", "c"])]


def test_uncovered_command_requires_a_whole_token() -> None:
    """Hyphenated command names do not match prefixes or space-separated words."""
    specs = [_spec("a", command="parrot sdd-tasks"), _spec("b", command="parrot sdd task")]

    findings = validate_graph(specs, known_probes=PROBES, known_commands=["sdd-task"])

    assert [(finding.code, finding.subjects) for finding in findings] == [("uncovered-command", ["sdd-task"])]

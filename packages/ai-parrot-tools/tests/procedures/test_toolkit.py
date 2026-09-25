"""Tests for the procedure toolkit's protected public surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from parrot.knowledge.common.provenance import Evidence
from parrot.knowledge.manuals.models import Applicability, SerialRange
from parrot_tools.procedures.retrieval import AuthorizationDenied, PatternPlan
from parrot_tools.procedures.toolkit import ProceduresToolkit

from ._doubles import make_card, make_context


@dataclass
class _Retrieval:
    """Small retrieval double that applies the task's authorization contract."""

    calls: list[PatternPlan]

    def authorize(self, context: Any, *, pattern: str | None = None, curator_only: bool = False) -> None:
        """Require the technician role for test reads."""
        if "technician" not in context.roles:
            raise AuthorizationDenied("technician is required", pattern=pattern)

    async def execute_graph(self, plan: PatternPlan, context: Any) -> list[dict[str, Any]]:
        """Return the part projection for its fixed traversal."""
        self.calls.append(plan)
        return [{"part": {"part_number": "P-7", "name": "Bolt"}, "confidence": 1.0}]


class _Catalog:
    """Catalog double exposing the bounded listing API used by serial validation."""

    def __init__(self, card: Any) -> None:
        self.card = card

    async def list_cards(self) -> list[Any]:
        """Return the one configured manual card."""
        return [self.card]


class _Service:
    """Toolkit service double with only collaborators this test path uses."""

    def __init__(self, card: Any) -> None:
        self.retrieval = _Retrieval([])
        self.catalog = _Catalog(card)


def test_toolkit_tool_names_and_confirming() -> None:
    """Tool names are proc-prefixed and task-memory internals stay hidden."""
    toolkit = ProceduresToolkit(service=_Service(make_card()), request_context=make_context())
    names = {tool.name for tool in toolkit.get_tools()}

    assert names
    assert all(name.startswith("proc_") for name in names)
    assert "proc_begin_task" not in names
    assert toolkit.confirming_tools == {"add_tip", "verify_procedure", "retire_tip"}


async def test_tools_deny_without_role() -> None:
    """A context without a read role receives an LLM-safe denial."""
    toolkit = ProceduresToolkit(service=_Service(make_card()), request_context=make_context(roles=()))

    result = await toolkit.find_part("figure-1", "7")

    assert result["status"] == "denied"


async def test_find_part_traversal() -> None:
    """The callout path uses the fixed part_for_callout traversal plan."""
    service = _Service(make_card())
    toolkit = ProceduresToolkit(service=service, request_context=make_context())

    result = await toolkit.find_part("figure-1", "7")

    assert result["status"] == "ok"
    assert result["parts"][0]["part"]["part_number"] == "P-7"
    assert service.retrieval.calls[0].pattern == "part_for_callout"
    assert service.retrieval.calls[0].bind_vars == {"media_id": "figure-1", "callout": "7"}


async def test_set_equipment_serial_validates() -> None:
    """Only serials matching a manual serial-range format enter trusted context."""
    card = make_card()
    step = card.procedures[0].steps[0]
    evidence = Evidence(node_id="serial", quote="A100", page=1)
    card.procedures[0].steps[0] = step.model_copy(
        update={"applicability": Applicability(serial_ranges=[SerialRange(format="A000")], evidence=evidence)}
    )
    toolkit = ProceduresToolkit(service=_Service(card), request_context=make_context(equipment_model="Model X"))

    invalid = await toolkit.set_equipment_serial("123")
    valid = await toolkit.set_equipment_serial("A123")

    assert invalid["status"] == "invalid"
    assert valid == {"status": "ok", "equipment_serial": "A123"}
    assert toolkit.request_context.equipment_serial == "A123"

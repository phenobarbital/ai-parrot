"""Tests for the procedure toolkit's protected public surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from parrot.knowledge.common.provenance import Evidence
from parrot.knowledge.manuals.models import Applicability, ManualVersion, SerialRange
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore
from parrot.tools.working_memory.task_memory.tools import TaskMemory
from parrot.tools.working_memory.task_memory.models import TaskScope
from parrot_tools.procedures.retrieval import AuthorizationDenied, PatternPlan, ProcedureRetrieval
from parrot_tools.procedures.service import ProceduresAnswerService
from parrot_tools.procedures.toolkit import ProceduresToolkit
from parrot_tools.procedures.verifier import ProcedureVerifier

from ._doubles import FakeCatalog, FakeOntology, FakePattern, make_card, make_context


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


class _ProjectingGraphStore:
    """Project the procedure traversal used by :class:`ProceduresAnswerService` from one card."""

    def __init__(self, card: Any) -> None:
        self.card = card

    async def execute_traversal(
        self, ctx: Any, aql: str, bind_vars: Optional[dict[str, Any]] = None, collection_binds: Any = None
    ) -> list[dict[str, Any]]:
        """Return the fixed traversal rows for the ``procedure_steps`` pattern only."""
        del ctx, collection_binds
        if aql != "procedure_steps":
            return []
        procedure_id = (bind_vars or {}).get("procedure_id")
        procedure = next(item for item in self.card.procedures if item.procedure_id == procedure_id)
        return [
            {
                "procedure": {"procedure_id": procedure.procedure_id},
                "step": {"step_id": step.identity.step_id},
                "order": step.order,
            }
            for step in procedure.steps
        ]


class _Evidence:
    """Evidence archive double retaining each verbatim step quote."""

    def __init__(self, card: Any) -> None:
        self.sections = {step.text.evidence.node_id: step.text.evidence.quote for step in card.procedures[0].steps}

    async def load_section(self, manual_id: str, version_n: int, node_id: str) -> str | None:
        """Return the archived body used by the verifier."""
        del manual_id, version_n
        return self.sections.get(node_id)


class _Files:
    """File-manager double that mints deterministic presigned figure URLs."""

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Return a fake HTTPS URL for a stored media object."""
        del expiry
        return f"https://fake/{path}"


class _Episodic:
    """Episodic memory double recording every ``record_episode`` call."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def record_episode(self, namespace: Any, **kwargs: Any) -> None:
        """Record the call without persisting anything real."""
        self.calls.append((namespace, kwargs))


def _answer_service(card: Any) -> ProceduresAnswerService:
    """Wire a real :class:`ProceduresAnswerService` around in-memory collaborators (same pattern
    as ``test_end_to_end.py``'s own ``_service`` — duplicated locally so this file's guided-mode
    tests exercise the production release pipeline, not a hand-rolled answer stub).
    """
    version = ManualVersion(n=1, revision=card.revision, valid_from=date(2026, 1, 1), source_sha256="")
    card = card.model_copy(update={"versions": [version]})
    catalog = FakeCatalog(cards=[card])
    retrieval = ProcedureRetrieval(
        catalog=catalog,
        graph_store=_ProjectingGraphStore(card),
        tenant_context=None,
        ontology=FakeOntology({"procedure_steps": FakePattern("procedure_steps")}),
        authorization=None,
    )
    return ProceduresAnswerService(
        retrieval=retrieval,
        verifier_factory=lambda selected: ProcedureVerifier(
            catalog=catalog, evidence=_Evidence(card), allowed_revision=selected
        ),
        catalog=catalog,
        file_manager=_Files(),
    )


def _task_memory(*, scope: Optional[TaskScope] = None) -> TaskMemory:
    """Build a real, in-memory-backed :class:`TaskMemory` composition root for guided-mode tests."""
    return TaskMemory(
        InMemoryTaskMemoryStore(),
        InMemoryArtifactStore(),
        scope or TaskScope(chatbot_id="bot-a", user_id="u1", session_id="s1"),
    )


async def test_guided_round_trip_start_next_mark_done() -> None:
    """start_guided -> next_step -> mark_done for every step -> a WORKFLOW_PATTERN episode.

    Regression test for a confirmed review finding: zero test coverage existed anywhere for
    the toolkit's own start_guided/next_step/mark_done wiring (only guided.py's pure helpers
    were tested) — this exercises the full round trip over the real release pipeline.
    """
    card = make_card()
    episodic = _Episodic()
    tm = _task_memory()
    toolkit = ProceduresToolkit(
        service=_answer_service(card), request_context=make_context(), task_memory=tm, episodic=episodic
    )

    started = await toolkit.start_guided("assemble-x")
    assert started["status"] == "started"
    task_id = started["task_id"]
    ordered_step_ids = [step["step_id"] for step in sorted(started["steps"], key=lambda s: s["order"])]
    assert len(ordered_step_ids) == 5

    for expected_order, step_id in enumerate(ordered_step_ids, start=1):
        pending = await toolkit.next_step(task_id)
        assert pending["status"] == "ok"
        assert pending["step"]["step_id"] == step_id
        assert pending["step"]["order"] == expected_order

        result = await toolkit.mark_done(task_id, step_id, note="done")
        assert result["status"] == "updated"

    assert await toolkit.next_step(task_id) == {"status": "complete"}
    assert len(episodic.calls) == 1
    namespace, kwargs = episodic.calls[0]
    assert namespace is tm.scope
    assert kwargs["category"].value == "workflow_pattern"
    assert kwargs["metadata"]["procedure_id"] == "assemble-x"


async def test_guided_state_rehydrates_on_a_different_toolkit_instance() -> None:
    """A SECOND ``ProceduresToolkit`` instance (simulating a different gunicorn worker / a
    restart) can ``next_step``/``mark_done`` a guided task the FIRST instance started, using
    only durable task-memory state — never the first instance's in-process ``_guided`` cache.

    Regression test for a confirmed review finding: ``self._guided`` was a plain in-process
    dict with no rehydration path, so resuming on any other toolkit instance hard-failed with
    "guided procedure state is unavailable".
    """
    card = make_card()
    tm = _task_memory()
    service = _answer_service(card)

    toolkit_a = ProceduresToolkit(service=service, request_context=make_context(), task_memory=tm)
    started = await toolkit_a.start_guided("assemble-x")
    assert started["status"] == "started"
    task_id = started["task_id"]
    first_step_id = min(started["steps"], key=lambda s: s["order"])["step_id"]

    # A brand-new toolkit instance, same durable task_memory, with NO ``_guided`` entry at all.
    toolkit_b = ProceduresToolkit(service=service, request_context=make_context(), task_memory=tm)
    assert task_id not in toolkit_b._guided

    pending = await toolkit_b.next_step(task_id)
    assert pending["status"] == "ok"
    assert pending["step"]["step_id"] == first_step_id

    result = await toolkit_b.mark_done(task_id, first_step_id, note="resumed on another worker")
    assert result["status"] == "updated"

"""Procedures toolkit — every action is authorized before it runs (FEAT-601 M11)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.knowledge.manuals.models import ManualVersion, Prerequisites, normalize_serial
from parrot.knowledge.manuals.tips import add_tip as _add_tip
from parrot.knowledge.manuals.tips import retire_tip as _retire_tip
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory.task_memory.models import ScopeViolation, StepStatus
from parrot.tools.working_memory.task_memory.service import TaskNotFound
from parrot.tools.working_memory.task_memory.tools import TASK_TOOL_METHODS, TaskMemoryToolsMixin
from parrot_tools.procedures.assembly import AssembledProcedure
from parrot_tools.procedures.guided import record_completion, task_steps_for
from parrot_tools.procedures.retrieval import AuthorizationDenied, Clarification, PatternPlan, RequestContext
from parrot_tools.procedures.service import ProceduresAnswerService

logger = logging.getLogger(__name__)
MAX_ROWS = 50
GUIDED_TOOLS: tuple[str, ...] = ("start_guided", "next_step", "mark_done", "resume_guided")


class ProceduresToolkit(TaskMemoryToolsMixin, AbstractToolkit):
    """Read assembly procedures, guide technicians, and curate technician tips."""

    name: str = "procedures"
    tool_prefix: str = "proc"
    confirming_tools: frozenset = frozenset({"add_tip", "verify_procedure", "retire_tip"})
    exclude_tools: tuple[str, ...] = ("get_tools", "get_tools_sync", *TASK_TOOL_METHODS)

    def __init__(
        self,
        *,
        service: ProceduresAnswerService,
        request_context: RequestContext,
        library: Any | None = None,
        task_memory: Any | None = None,
        episodic: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the toolkit with trusted request-scoped collaborators."""
        super().__init__(**kwargs)
        self.service = service
        self.request_context = request_context
        self.library = library
        self._task_memory = task_memory
        self.episodic = episodic
        self._guided: dict[str, dict[str, Any]] = {}
        if task_memory is None:
            self.exclude_tools = (*type(self).exclude_tools, *GUIDED_TOOLS)

    def _gate(self, *, pattern: Optional[str] = None, curator_only: bool = False) -> None:
        """Authorize the trusted context before any procedure operation."""
        self.service.retrieval.authorize(self.request_context, pattern=pattern, curator_only=curator_only)

    @staticmethod
    def _denied(exc: AuthorizationDenied) -> dict[str, Any]:
        """Turn an authorization refusal into an LLM-safe result."""
        return {"status": "denied", "reason": exc.reason}

    async def _card_for_procedure(self, procedure_id: str) -> Any | None:
        """Return the bounded catalog card containing ``procedure_id``."""
        cards = await self.service.catalog.list_cards()
        return next(
            (card for card in cards if any(item.procedure_id == procedure_id for item in card.procedures)), None
        )

    async def _released_answer(self, procedure_id: str, *, order: int | None = None) -> dict[str, Any]:
        """Use the release service for a resolved procedure identifier."""
        card = await self._card_for_procedure(procedure_id)
        if card is None:
            return {"status": "not_found"}
        procedure = next(item for item in card.procedures if item.procedure_id == procedure_id)
        equipment = card.equipment[0].model if card.equipment else "equipment"
        question = f"how do I assemble {procedure.title.value} {equipment}"
        if order is not None:
            question = f"step {order} {question}"
        outcome = await self.service.answer(question, request_context=self.request_context)
        if isinstance(outcome, Clarification):
            return {"status": "clarification", **outcome.model_dump(mode="json")}
        return outcome.answer.model_dump(mode="json")

    async def _build_assembled(self, procedure_id: str) -> AssembledProcedure | dict[str, Any]:
        """Rebuild the released :class:`AssembledProcedure` for ``procedure_id``.

        Returns an error dict (``not_found``/``clarification``/anything else
        :meth:`_released_answer` returns for a non-"procedure" answer) instead when it cannot.
        """
        answer_data = await self._released_answer(procedure_id)
        if answer_data.get("answer_kind") != "procedure":
            return answer_data
        card = await self._card_for_procedure(procedure_id)
        if card is None:
            return {"status": "not_found"}
        revision = next((item for item in card.versions if item.revision == answer_data.get("manual_revision")), None)
        revision = revision or ManualVersion(n=1, revision=answer_data.get("manual_revision") or card.revision)
        return AssembledProcedure(
            procedure=answer_data["procedure"],
            steps=answer_data["steps"],
            prerequisites=answer_data.get("prerequisites") or Prerequisites(),
            hazards=answer_data.get("hazards", []),
            media=answer_data.get("media", []),
            tips=answer_data.get("tips", []),
            citations=answer_data.get("citations", []),
            revision=revision,
        )

    async def _guided_state(self, task_id: str) -> Optional[dict[str, Any]]:
        """Return this task's guided-mode state, rehydrating it from durable task-memory storage
        if this process never ran :meth:`start_guided` for it (a different gunicorn worker, a
        restart, a fresh deploy — the in-process ``self._guided`` cache does not survive any of
        those). ``None`` means the task genuinely does not exist or is not a guided procedure.
        """
        cached = self._guided.get(task_id)
        if cached is not None:
            return cached
        tm = self._tm()
        try:
            snapshot = await tm.service.get_task(tm.scope, task_id)
        except (TaskNotFound, ScopeViolation):
            return None
        procedure_id = next(
            (
                constraint.text.split("=", 1)[1]
                for constraint in snapshot.state.active_constraints
                if constraint.text.startswith("procedure_id=")
            ),
            None,
        )
        if procedure_id is None:
            return None
        assembled = await self._build_assembled(procedure_id)
        if isinstance(assembled, dict):
            return None
        labels: dict[str, str] = {}
        completed: set[str] = set()
        for tm_step in snapshot.state.steps:
            try:
                order = int(tm_step.title.split(".", 1)[0])
            except (ValueError, IndexError):
                continue
            view = next((item for item in assembled.steps if item.order == order), None)
            if view is None:
                continue
            labels[view.step_id] = tm_step.step_id
            if tm_step.status == StepStatus.COMPLETED:
                completed.add(view.step_id)
        state = {"procedure": assembled, "labels": labels, "completed": completed, "recorded": False}
        self._guided[task_id] = state
        return state

    async def find_procedure(self, query: str, equipment: Optional[str] = None) -> dict[str, Any]:
        """Find a procedure without guessing when multiple candidates match."""
        try:
            self._gate(pattern="procedures_for_equipment")
            context = self.request_context.model_copy(
                update={"equipment_model": equipment or self.request_context.equipment_model}
            )
            resolved_equipment = await self.service.retrieval.resolve_equipment(equipment or query, context)
            if isinstance(resolved_equipment, Clarification):
                return {"status": "clarification", **resolved_equipment.model_dump(mode="json")}
            resolved = await self.service.retrieval.resolve_procedure(query, resolved_equipment, context)
            if isinstance(resolved, Clarification):
                return {"status": "clarification", **resolved.model_dump(mode="json")}
            return {"status": "ok", "procedure": resolved.model_dump(mode="json")}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def get_steps(self, procedure_id: str) -> dict[str, Any]:
        """Return the released ordered steps for one procedure."""
        try:
            self._gate(pattern="procedure_steps")
            return await self._released_answer(procedure_id)
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def get_step(self, procedure_id: str, order: int) -> dict[str, Any]:
        """Return one released procedure step with its safety context."""
        try:
            self._gate(pattern="step_detail")
            return await self._released_answer(procedure_id, order=order)
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def prerequisites(self, procedure_id: str) -> dict[str, Any]:
        """Return the released parts, tools, and hazards needed before starting."""
        try:
            self._gate(pattern="procedure_prerequisites")
            answer = await self._released_answer(procedure_id)
            return answer
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def media_for_step(self, step_id: str) -> dict[str, Any]:
        """Return bounded media metadata for a procedure step."""
        try:
            self._gate(pattern="step_detail")
            rows = await self.service.retrieval.execute_graph(
                PatternPlan(pattern="step_detail", bind_vars={"step_id": step_id}), self.request_context
            )
            return {"status": "ok", "media": rows[:MAX_ROWS]}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def tips_for_step(self, step_id: str) -> dict[str, Any]:
        """Return active, non-orphaned tips associated with one step."""
        try:
            self._gate(pattern="tips_for_procedure")
            rows = await self.service.retrieval.execute_graph(
                PatternPlan(pattern="tips_for_procedure", bind_vars={"step_id": step_id}), self.request_context
            )
            tips = [
                row["tip"]
                for row in rows
                if row.get("step_id") == step_id
                and row.get("tip", {}).get("active", True)
                and not row.get("tip", {}).get("orphaned", False)
            ]
            return {"status": "ok", "tips": tips[:MAX_ROWS]}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def related_equipment(self, equipment_id: str) -> dict[str, Any]:
        """Return equipment sharing a module with the supplied equipment."""
        try:
            self._gate(pattern="equipment_sharing_module")
            rows = await self.service.retrieval.execute_graph(
                PatternPlan(pattern="equipment_sharing_module", bind_vars={"equipment_id": equipment_id}),
                self.request_context,
            )
            return {"status": "ok", "equipment": rows[:MAX_ROWS]}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def find_part(self, media_id: str, callout: str) -> dict[str, Any]:
        """Resolve an exploded-view callout to its manual part."""
        try:
            self._gate(pattern="part_for_callout")
            rows = await self.service.retrieval.execute_graph(
                PatternPlan(pattern="part_for_callout", bind_vars={"media_id": media_id, "callout": callout}),
                self.request_context,
            )
            if not rows:
                return {"status": "not_found"}
            return {"status": "ok", "parts": rows[:MAX_ROWS]}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def set_equipment_serial(self, serial: str) -> dict[str, Any]:
        """Validate and retain the current equipment serial in trusted request context."""
        try:
            self._gate()
            cards = await self.service.catalog.list_cards()
            formats = [
                serial_range.format
                for card in cards
                if self.request_context.equipment_model is None
                or any(item.model == self.request_context.equipment_model for item in card.equipment)
                for procedure in card.procedures
                for step in procedure.steps
                for serial_range in step.applicability.serial_ranges
            ]
            if formats and not any(_valid_serial(serial, format_value) for format_value in formats):
                return {"status": "invalid", "reason": "serial does not match the manual format"}
            self.request_context = self.request_context.model_copy(update={"equipment_serial": serial})
            return {"status": "ok", "equipment_serial": serial}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def add_tip(self, step_id: str, text: str) -> dict[str, Any]:
        """Attach a technician-authored tip to a procedure step."""
        try:
            self._gate(pattern="tips_for_procedure")
            if not self.request_context.employee_id:
                raise AuthorizationDenied("tips require an authenticated employee identity")
            tip = await _add_tip(
                self.service.retrieval.graph_store,
                self.service.retrieval.tenant_context,
                step_id=step_id,
                text=text,
                author_employee_id=self.request_context.employee_id,
                source_revision="current",
            )
            return {"status": "ok", "tip": tip.model_dump(mode="json")}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def retire_tip(self, tip_id: str) -> dict[str, Any]:
        """Retire a tip as a curator-only action."""
        try:
            self._gate(curator_only=True)
            await _retire_tip(
                self.service.retrieval.graph_store,
                self.service.retrieval.tenant_context,
                tip_id=tip_id,
                by=self.request_context.user_id,
            )
            return {"status": "ok", "tip_id": tip_id}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def verification_queue(self, limit: int = 20) -> dict[str, Any]:
        """Return a bounded curator verification queue."""
        try:
            self._gate(curator_only=True)
            queue = await self.service.catalog.verification_queue(limit=min(limit, MAX_ROWS))
            return {"status": "ok", "queue": [item.model_dump(mode="json") for item in queue]}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def verify_procedure(self, procedure_id: str) -> dict[str, Any]:
        """Mark one procedure verified as a curator-only operation."""
        try:
            self._gate(curator_only=True)
            if self.library is None:
                return {"status": "unavailable", "reason": "manual library is not configured"}
            card = await self._card_for_procedure(procedure_id)
            if card is None:
                return {"status": "not_found"}
            verified = await self.library.verify_procedure(
                card.manual_id, procedure_id, user=self.request_context.user_id
            )
            return {"status": "ok", "procedure": procedure_id, "manual_id": verified.manual_id}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def start_guided(self, procedure_id: str) -> dict[str, Any]:
        """Start a durable, linear guided task for a released procedure."""
        try:
            self._gate(pattern="procedure_steps")
            if self._task_memory is None:
                return {"status": "unavailable", "reason": "task memory is not configured"}
            assembled = await self._build_assembled(procedure_id)
            if isinstance(assembled, dict):
                return assembled
            result = await self.begin_task(
                goal=assembled.procedure.title,
                # Durable — not just an in-process cache — so any worker can rehydrate this
                # guided task's full state later via ``_guided_state`` (see there for why).
                constraints=[f"procedure_id={procedure_id}"],
                steps=task_steps_for(assembled),
                plan_complete=True,
            )
            if result.get("status") != "started":
                return result
            labels = {
                view.step_id: item["step_id"] for view, item in zip(assembled.steps, result["steps"], strict=True)
            }
            self._guided[result["task_id"]] = {
                "procedure": assembled,
                "labels": labels,
                "completed": set(),
                "recorded": False,
            }
            return {
                "status": "started",
                "task_id": result["task_id"],
                "revision": result["revision"],
                "steps": assembled.steps and [item.model_dump(mode="json") for item in assembled.steps],
            }
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def next_step(self, task_id: str) -> dict[str, Any]:
        """Return the next pending guided step and persist a resume hint."""
        try:
            self._gate(pattern="step_detail")
            recalled = await self.recall_task(task_id)
            if recalled.get("status") != "recalled":
                return recalled
            state = recalled["snapshot"]
            pending = next((item for item in state.get("steps", []) if item.get("status") == "pending"), None)
            if pending is None:
                return {"status": "complete"}
            guided = await self._guided_state(task_id)
            step = None
            if guided is not None:
                # ``pending["step_id"]`` is task-memory's own runtime id (freshly minted per step,
                # never equal to our procedure's step_id — see ``_resolve_initial_plan``); translate
                # through ``labels`` (procedure step_id -> task-memory step_id) the other way round.
                reverse_labels = {taskmem_id: proc_id for proc_id, taskmem_id in guided["labels"].items()}
                proc_step_id = reverse_labels.get(pending["step_id"])
                if proc_step_id is not None:
                    step = next((item for item in guided["procedure"].steps if item.step_id == proc_step_id), None)
            await self.set_resume_hint(task_id, "complete the next procedure step", step_id=pending["step_id"])
            return {"status": "ok", "step": step.model_dump(mode="json") if step else pending}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def mark_done(self, task_id: str, step_id: str, note: Optional[str] = None) -> dict[str, Any]:
        """Complete one procedure step with synthetic revision-pinned evidence."""
        try:
            self._gate(pattern="step_detail")
            guided = await self._guided_state(task_id)
            if guided is None or step_id not in guided["labels"]:
                return {"status": "not_found", "reason": "guided procedure state is unavailable"}
            recalled = await self.recall_task(task_id)
            if recalled.get("status") != "recalled":
                return recalled
            revision = recalled["snapshot"]["revision"]
            procedure = guided["procedure"]
            completion_note = note or "completed by technician"
            # update_step's default AGENT_ASSERTED completion policy requires evidence_refs to
            # resolve to a REAL artifact ("a tool call that merely succeeded is never on its own
            # evidence that a step is done") — a synthetic, never-registered "procedure:X@N"
            # string always fails with completion_refused. Register the completion itself as a
            # tiny artifact first, then cite ITS resolved ref.
            tm = self._tm()
            descriptor = await tm.artifacts.put(
                tm.scope,
                f"procedure_step_completion:{task_id}:{step_id}",
                {
                    "procedure_id": procedure.procedure.procedure_id,
                    "manual_revision": procedure.revision.revision,
                    "step_id": step_id,
                    "note": completion_note,
                },
                task_id=task_id,
                description="Guided-mode step completion evidence (FEAT-601 M11)",
            )
            result = await self.update_step(
                task_id,
                guided["labels"][step_id],
                expected_revision=revision,
                status="completed",
                evidence_refs=[str(descriptor.ref)],
                note=completion_note,
            )
            if result.get("status") != "updated":
                return result
            guided["completed"].add(step_id)
            if len(guided["completed"]) == len(procedure.steps) and not guided["recorded"]:
                await record_completion(
                    self.episodic,
                    namespace=self._task_memory.scope,
                    procedure=procedure,
                    user_id=self.request_context.user_id,
                )
                guided["recorded"] = True
            return result
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def resume_guided(self) -> dict[str, Any]:
        """Resume the task-memory selected guided procedure without guessing."""
        try:
            self._gate(pattern="step_detail")
            recalled = await self.recall_task()
            if recalled.get("status") != "recalled":
                return recalled
            task_id = recalled["snapshot"]["task_id"]
            await self.select_task(task_id)
            return await self.next_step(task_id)
        except AuthorizationDenied as exc:
            return self._denied(exc)


def _valid_serial(serial: str, format_value: str) -> bool:
    """Return whether ``serial`` matches a vendor-preserved serial format."""
    try:
        normalize_serial(serial, format=format_value)
    except ValueError:
        return False
    return True

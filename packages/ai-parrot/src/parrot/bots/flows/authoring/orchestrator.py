"""``FlowAuthoringOrchestrator`` — drives skeleton → nodes → transitions → compile.

The user-facing entry point. Mirrors ``AgentFactoryOrchestrator``'s shape
(request in, typed result out, progress surfaced along the way) but without
its HITL gates: authoring produces a *definition*, which is inert until
someone runs or persists it, so there is nothing to gate.

Its one judgement call is engine selection under ``engine="auto"``. Everything
else is mechanical: run the stages, validate, repair once, compile, and be
honest in the result about anything that did not work.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Union

from .assembler import AssemblyError, assemble, to_crew_definition, to_flow_definition
from .author import FlowAuthor, FlowAuthoringError
from .blueprint import BlueprintNode, BlueprintSkeleton, WorkflowBlueprint
from .catalog import ComponentCatalog, build_catalog
from .contracts import (
    AuthoringProgress,
    AuthoringStage,
    AuthoringStatus,
    CapabilityGap,
    FlowAuthoringRequest,
    FlowAuthoringResult,
)
from .validator import ValidationReport, validate_blueprint

__all__ = ("FlowAuthoringOrchestrator",)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[AuthoringProgress], Union[None, Awaitable[None]]]


class FlowAuthoringOrchestrator:
    """Turns a natural-language request into a runnable workflow definition."""

    def __init__(
        self,
        planner_llm: Optional[Union[str, Dict[str, Any], type, Any]] = None,
        *,
        client: Any = None,
        tool_manager: Any = None,
        catalog: Optional[ComponentCatalog] = None,
        concurrency: int = 4,
    ) -> None:
        """Bind the planner model and the component catalog.

        Args:
            planner_llm: ``"provider:model"``, an ``AbstractClient`` subclass
                or instance, or a ``model_config`` dict.
            client: A pre-built client used as-is, bypassing resolution.
            tool_manager: Optional live ``ToolManager``, which lets the
                catalog carry real tool descriptions and argument summaries.
            catalog: Pre-built catalog. Supplying one skips reflection.
            concurrency: How many nodes to author at once.

        Raises:
            ValueError: If neither ``planner_llm`` nor ``client`` is given.
        """
        if client is None and planner_llm is None:
            raise ValueError(
                "FlowAuthoringOrchestrator needs either 'planner_llm' or 'client'."
            )
        self._planner_llm = planner_llm
        self._client = client
        self._tool_manager = tool_manager
        self._catalog = catalog
        self._concurrency = concurrency
        self.logger = logging.getLogger(f"{__name__}.FlowAuthoringOrchestrator")

    async def build(
        self,
        request: FlowAuthoringRequest,
        *,
        on_progress: Optional[ProgressCallback] = None,
    ) -> FlowAuthoringResult:
        """Author, validate and compile a workflow.

        Args:
            request: The authoring request.
            on_progress: Optional callback invoked at each stage. May be sync
                or async; exceptions from it are logged and swallowed, since
                progress reporting must never fail the run.

        Returns:
            A :class:`FlowAuthoringResult`. ``status`` is ``DEGRADED`` when a
            workflow was produced but something was lost — a node that could
            not be authored, or a capability the platform lacks — and
            ``FAILED`` when there is no usable workflow at all.
        """
        catalog = self._catalog or build_catalog(
            tool_manager=self._tool_manager,
            allowed_tools=request.allowed_tools,
        )
        engine = self._resolve_engine(request, catalog)
        author = FlowAuthor(
            self._planner_llm,
            catalog,
            client=self._client,
            max_nodes=request.max_nodes,
            concurrency=self._concurrency,
        )

        try:
            skeleton = await self._skeleton_stage(author, request, engine, on_progress)
            nodes, dropped = await self._nodes_stage(author, skeleton, on_progress)
            if not nodes:
                return FlowAuthoringResult(
                    status=AuthoringStatus.FAILED,
                    engine=engine,
                    dropped_nodes=dropped,
                    error="No node could be authored.",
                )

            transitions = await self._transitions_stage(
                author, skeleton, nodes, on_progress
            )
            blueprint = assemble(skeleton, nodes, transitions)

            blueprint, report, repair_rounds = await self._validate_and_repair(
                author, skeleton, blueprint, catalog, on_progress
            )
            return self._compile_stage(
                request=request,
                engine=engine,
                blueprint=blueprint,
                report=report,
                repair_rounds=repair_rounds,
                dropped=dropped,
                on_progress=on_progress,
            )
        except (FlowAuthoringError, AssemblyError) as exc:
            self.logger.exception("Authoring failed")
            return FlowAuthoringResult(
                status=AuthoringStatus.FAILED, engine=engine, error=str(exc)
            )

    # ── stages ───────────────────────────────────────────────────────────

    async def _skeleton_stage(
        self,
        author: FlowAuthor,
        request: FlowAuthoringRequest,
        engine: str,
        on_progress: Optional[ProgressCallback],
    ) -> BlueprintSkeleton:
        """Run stage 1 and report progress."""
        await self._report(
            on_progress,
            AuthoringProgress(
                stage=AuthoringStage.SKELETON, message="Planning workflow shape"
            ),
        )
        skeleton = await author.skeleton(
            request.description, engine=engine, name=request.name
        )
        self.logger.info(
            "Skeleton: %d node(s) for engine=%s", len(skeleton.nodes), engine
        )
        return skeleton

    async def _nodes_stage(
        self,
        author: FlowAuthor,
        skeleton: BlueprintSkeleton,
        on_progress: Optional[ProgressCallback],
    ) -> tuple[List[BlueprintNode], List[str]]:
        """Run stage 2 and report progress."""
        total = len(skeleton.nodes)
        await self._report(
            on_progress,
            AuthoringProgress(
                stage=AuthoringStage.NODES,
                nodes_total=total,
                message=f"Authoring {total} node(s)",
            ),
        )
        nodes, dropped = await author.author_nodes(skeleton)
        await self._report(
            on_progress,
            AuthoringProgress(
                stage=AuthoringStage.NODES,
                nodes_total=total,
                nodes_done=len(nodes),
                message=f"Authored {len(nodes)}/{total} node(s)",
            ),
        )
        return nodes, dropped

    async def _transitions_stage(
        self,
        author: FlowAuthor,
        skeleton: BlueprintSkeleton,
        nodes: Sequence[BlueprintNode],
        on_progress: Optional[ProgressCallback],
    ) -> List[Any]:
        """Run stage 3 and report progress."""
        await self._report(
            on_progress,
            AuthoringProgress(
                stage=AuthoringStage.TRANSITIONS, message="Connecting nodes"
            ),
        )
        return await author.author_transitions(skeleton, nodes)

    async def _validate_and_repair(
        self,
        author: FlowAuthor,
        skeleton: BlueprintSkeleton,
        blueprint: WorkflowBlueprint,
        catalog: ComponentCatalog,
        on_progress: Optional[ProgressCallback],
    ) -> tuple[WorkflowBlueprint, ValidationReport, int]:
        """Validate, and run at most one bounded repair round.

        One round, not a loop: if a model cannot fix a fault when handed the
        exact validation report, more rounds mostly buy tokens. What survives
        is reported rather than retried.

        Args:
            author: The author, for the repair calls.
            skeleton: The skeleton, for repair context.
            blueprint: The assembled blueprint.
            catalog: The component catalog.
            on_progress: Progress callback.

        Returns:
            ``(blueprint, report, repair_rounds)`` — the best blueprint
            obtained and the report describing what is still wrong with it.
        """
        await self._report(
            on_progress,
            AuthoringProgress(stage=AuthoringStage.VALIDATE, message="Validating"),
        )
        report = validate_blueprint(blueprint, catalog)
        if report.ok:
            return blueprint, report, 0

        self.logger.info("Validation found %d error(s); repairing", len(report.errors))
        await self._report(
            on_progress,
            AuthoringProgress(
                stage=AuthoringStage.REPAIR,
                message=f"Repairing {len(report.errors)} issue(s)",
            ),
        )

        repaired_nodes = await self._repair_nodes(author, skeleton, blueprint, report)
        transitions = blueprint.transitions
        if any(issue.node_id is None for issue in report.errors):
            try:
                transitions = await author.repair_transitions(
                    skeleton, repaired_nodes, report
                )
            except FlowAuthoringError:
                self.logger.exception("Transition repair failed; keeping originals")

        try:
            repaired = assemble(skeleton, repaired_nodes, transitions)
        except AssemblyError:
            self.logger.exception("Repaired fragments did not assemble")
            return blueprint, report, 1

        repaired_report = validate_blueprint(repaired, catalog)
        # Keep whichever attempt is actually better — a repair round can make
        # things worse, and silently shipping the worse one would be a
        # regression the caller cannot see.
        if len(repaired_report.errors) <= len(report.errors):
            return repaired, repaired_report, 1
        return blueprint, report, 1

    async def _repair_nodes(
        self,
        author: FlowAuthor,
        skeleton: BlueprintSkeleton,
        blueprint: WorkflowBlueprint,
        report: ValidationReport,
    ) -> List[BlueprintNode]:
        """Re-author only the nodes that have their own errors."""
        by_node: Dict[str, List[Any]] = {}
        for issue in report.errors:
            if issue.node_id:
                by_node.setdefault(issue.node_id, []).append(issue)
        if not by_node:
            return list(blueprint.nodes)

        stubs = {stub.id: stub for stub in skeleton.nodes}
        repaired: List[BlueprintNode] = []
        for node in blueprint.nodes:
            issues = by_node.get(node.id)
            stub = stubs.get(node.id)
            if not issues or stub is None:
                repaired.append(node)
                continue
            try:
                repaired.append(await author.repair_node(stub, skeleton, issues))
            except FlowAuthoringError:
                self.logger.exception("Repair failed for node %r", node.id)
                repaired.append(node)
        return repaired

    def _compile_stage(
        self,
        *,
        request: FlowAuthoringRequest,
        engine: str,
        blueprint: WorkflowBlueprint,
        report: ValidationReport,
        repair_rounds: int,
        dropped: List[str],
        on_progress: Optional[ProgressCallback],
    ) -> FlowAuthoringResult:
        """Compile the blueprint, or report why it could not be compiled."""
        gaps = self._dedupe_gaps(report.capability_gaps)

        if not report.ok:
            return FlowAuthoringResult(
                status=AuthoringStatus.FAILED,
                engine=engine,
                blueprint=blueprint,
                capability_gaps=gaps,
                validation_issues=[str(issue) for issue in report.issues],
                repair_rounds=repair_rounds,
                dropped_nodes=dropped,
                error=(
                    f"Blueprint still has {len(report.errors)} error(s) after "
                    "repair."
                ),
            )

        try:
            if engine == "crew":
                definition = to_crew_definition(blueprint, tenant=request.tenant)
                crew_payload = definition.model_dump(mode="json")
                flow_payload = None
            else:
                definition = to_flow_definition(blueprint)
                crew_payload = None
                flow_payload = definition.model_dump(mode="json", by_alias=True)
        except (AssemblyError, ValueError) as exc:
            self.logger.exception("Compilation failed")
            return FlowAuthoringResult(
                status=AuthoringStatus.FAILED,
                engine=engine,
                blueprint=blueprint,
                capability_gaps=gaps,
                repair_rounds=repair_rounds,
                dropped_nodes=dropped,
                error=f"Compilation failed: {exc}",
            )

        degraded = bool(dropped or gaps)
        return FlowAuthoringResult(
            status=AuthoringStatus.DEGRADED if degraded else AuthoringStatus.SUCCESS,
            engine=engine,
            blueprint=blueprint,
            crew_definition=crew_payload,
            flow_definition=flow_payload,
            capability_gaps=gaps,
            validation_issues=[str(issue) for issue in report.warnings],
            repair_rounds=repair_rounds,
            dropped_nodes=dropped,
        )

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _dedupe_gaps(gaps: Sequence[CapabilityGap]) -> List[CapabilityGap]:
        """Collapse gaps that name the same missing thing."""
        seen: Dict[tuple, CapabilityGap] = {}
        for gap in gaps:
            seen.setdefault((gap.kind, gap.requested), gap)
        return list(seen.values())

    def _resolve_engine(
        self, request: FlowAuthoringRequest, catalog: ComponentCatalog
    ) -> str:
        """Pick the compile target.

        ``auto`` resolves to ``flow`` only when there are registered agents to
        wire together, because ``AgentsFlow`` resolves every ``agent_ref``
        through the ``AgentRegistry`` and raises when one is missing. With an
        empty registry a flow could not be built at all, whereas a crew
        constructs its agents from the blueprint — so ``crew`` is the honest
        default.

        Args:
            request: The authoring request.
            catalog: The component catalog.

        Returns:
            ``"crew"`` or ``"flow"``.
        """
        if request.engine != "auto":
            return request.engine
        engine = "flow" if catalog.agents else "crew"
        self.logger.info(
            "engine='auto' resolved to %r (%d registered agent(s))",
            engine, len(catalog.agents),
        )
        return engine

    async def _report(
        self, on_progress: Optional[ProgressCallback], progress: AuthoringProgress
    ) -> None:
        """Invoke the progress callback, tolerating sync or async callables."""
        if on_progress is None:
            return
        try:
            result = on_progress(progress)
            if hasattr(result, "__await__"):
                await result
        except Exception:  # pragma: no cover - progress must never break a run
            self.logger.warning("Progress callback raised", exc_info=True)

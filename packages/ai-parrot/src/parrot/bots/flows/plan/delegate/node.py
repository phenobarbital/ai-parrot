"""``DelegateToolNode`` — a runtime-decided tool call inside an ExecutionPlan (FEAT-590).

The delegate proposes; code disposes. Everything from dispatch onward is the
inherited ``PlanToolNode`` path (retries, receipts, execute_tool, storage).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Set, Tuple

from pydantic import Field, PrivateAttr

from ..guards import PlanGuard, compile_guard
from ..models import ArtifactRef, DelegatePlanNode
from ..node import PlanToolNode, ToolExecutionError, _Attempt
from .protocol import DelegateBackendError, DelegateTrace, ToolCallProposal, tool_specs

__all__ = ("DelegateEscalation", "DelegateRejectedError", "DelegateToolNode", "make_delegate_node_factory")

logger = logging.getLogger(__name__)


class DelegateRejectedError(ToolExecutionError):
    """The proposal failed the accept gate and ``on_reject`` did not recover it."""


class DelegateEscalation(DelegateRejectedError):
    """``on_reject='escalate'`` — always recorded, message prefixed ``escalate:``."""


class DelegateToolNode(PlanToolNode):
    """Execute one :class:`DelegatePlanNode`."""

    plan_node: DelegatePlanNode  # type: ignore[assignment] — narrowed field
    delegates: Tuple[Any, ...] = Field(default_factory=tuple)
    trace_sink: Optional[Any] = None
    allow_delegate_side_effects: bool = False

    _accept_guard: Optional[PlanGuard] = PrivateAttr(default=None)

    def model_post_init(self, __context: Any) -> None:
        """Compile ``accept_when`` once, after the base compiles ``when``."""
        super().model_post_init(__context)
        object.__setattr__(self, "_accept_guard", compile_guard(self.plan_node.accept_when))

    def _template_source(self) -> Any:
        return {"instruction": self.plan_node.instruction, "facts": dict(self.plan_node.facts)}

    def _action_label(self) -> str:
        return "delegate:" + "|".join(self.plan_node.tools)

    def _is_escalation(self, exc: BaseException) -> bool:
        return isinstance(exc, DelegateEscalation)

    async def _invoke(
        self,
        prior: Mapping[str, ArtifactRef],
        bodies: Mapping[str, Any],
        *,
        item: Any = None,
        index: Optional[int] = None,
    ) -> _Attempt:
        """Resolve → budget → propose → gate → dispatch (or apply on_reject)."""
        resolved = self._resolve_args(self._template_source(), prior, bodies, item=item, index=index)
        instruction: str = str(resolved["instruction"])
        facts: Dict[str, str] = {k: str(v) for k, v in resolved["facts"].items()}
        specs = tool_specs(self.tool_manager, self.plan_node.tools)
        proposal, verdict = await self._propose_with_chain(instruction, facts, specs, prior, index)
        if verdict != "accepted":
            message = f"{verdict}: node {self.node_id!r} proposal {proposal.name!r} rejected"
            if self.plan_node.on_reject == "escalate":
                raise DelegateEscalation(f"escalate: {message}")
            raise DelegateRejectedError(message)
        return await self._call_with_retry(dict(proposal.arguments), index=index, tool=proposal.name)

    async def _propose_with_chain(
        self,
        instruction: str,
        facts: Dict[str, str],
        specs: Sequence[Any],
        prior: Mapping[str, ArtifactRef],
        index: Optional[int],
    ) -> Tuple[ToolCallProposal, str]:
        """Walk the delegate chain per on_reject; trace every hop. Returns (last proposal, verdict)."""
        tools = self.plan_node.tools
        if self.plan_node.on_reject == "retry_backend":
            candidates: Sequence[Any] = tuple(d for d in self.delegates if getattr(d, "max_tools", 0) >= len(tools))
        else:
            candidates = self.delegates[:1]

        if not candidates:
            # AC10 requires a DelegateTrace for every hop, including this one -- an
            # empty candidate chain (e.g. every delegate's max_tools below
            # len(tools) under on_reject="retry_backend") is still a real proposal
            # attempt that a trace sink needs to see, not a silent early exit.
            empty_proposal = ToolCallProposal(name=None, arguments={}, confidence=None, backend="none", latency_ms=0.0)
            await self._trace(
                item_index=index,
                instruction=instruction,
                facts=facts,
                tools=list(tools),
                proposal=empty_proposal,
                verdict="declined",
                final_call=None,
            )
            return empty_proposal, "declined"

        facts_rendered = json.dumps(facts, sort_keys=True)
        proposal: Optional[ToolCallProposal] = None
        verdict = "declined"
        for delegate in candidates:
            backend_name = getattr(delegate, "backend_name", "unknown")
            max_input_chars = getattr(delegate, "max_input_chars", None)
            if max_input_chars is not None and len(instruction) + len(facts_rendered) > max_input_chars:
                proposal = ToolCallProposal(
                    name=None, arguments={}, confidence=None, backend=backend_name, latency_ms=0.0
                )
                verdict = "input_too_long"
            else:
                try:
                    proposal = await delegate.propose_call(instruction, specs, facts)
                except DelegateBackendError:
                    proposal = ToolCallProposal(
                        name=None, arguments={}, confidence=None, backend=backend_name, latency_ms=0.0
                    )
                    verdict = "backend_error"
                else:
                    verdict = self._gate(proposal, prior)
            await self._trace(
                item_index=index,
                instruction=instruction,
                facts=facts,
                tools=list(tools),
                proposal=proposal,
                verdict=verdict,
                final_call={"name": proposal.name, "arguments": proposal.arguments} if verdict == "accepted" else None,
            )
            if verdict == "accepted":
                break

        return proposal, verdict

    def _gate(self, proposal: ToolCallProposal, prior: Mapping[str, ArtifactRef]) -> str:
        """Return the verdict string for ``proposal`` (order fixed by spec M5 / §8 Q-S8)."""
        if proposal.name is None:
            return "declined"
        if proposal.name not in self.plan_node.tools:
            return "unknown_tool"

        tool = self.tool_manager.get_tool(proposal.name)
        if hasattr(tool, "get_schema"):
            parameters = tool.get_schema()["parameters"]
        else:
            parameters = tool.input_schema
        properties = parameters.get("properties") or {}
        required = parameters.get("required") or []
        arguments = proposal.arguments
        if (set(arguments) - set(properties)) or (set(required) - set(arguments)):
            return "invalid_args"
        if hasattr(tool, "validate_args"):
            try:
                tool.validate_args(**arguments)
            except Exception:  # noqa: BLE001 - any validation failure is invalid_args
                return "invalid_args"

        side_effect_ok = getattr(tool, "delegate_safe", False) or (
            self.plan_node.allow_side_effects and self.allow_delegate_side_effects
        )
        if not side_effect_ok:
            return "side_effect_denied"

        if self.plan_node.min_confidence is not None:
            if proposal.confidence is None:
                return "unscored"
            if proposal.confidence < self.plan_node.min_confidence:
                return "low_confidence"

        if self._accept_guard is not None:
            artifacts = {nid: ref.facets for nid, ref in prior.items()}
            statuses = {nid: ref.status for nid, ref in prior.items()}
            failures = sum(1 for ref in prior.values() if ref.status == "error")
            extra = {
                "proposal": {
                    "name": proposal.name,
                    "arguments": proposal.arguments,
                    "confidence": proposal.confidence,
                }
            }
            if not self._accept_guard.evaluate(artifacts, statuses, failures, extra=extra):
                return "guard_false"

        return "accepted"

    async def _trace(self, **fields: Any) -> None:
        """Record one DelegateTrace; never raises."""
        if self.trace_sink is None:
            return
        try:
            await self.trace_sink.record(DelegateTrace(plan_run_id=self.plan_run_id, node_id=self.node_id, **fields))
        except Exception as exc:  # noqa: BLE001 - AC10: a trace failure never fails the node
            self.logger.warning("Node %r: delegate trace failed: %s", self.node_id, exc)


def make_delegate_node_factory(
    tool_manager: Any,
    working_memory: Any,
    delegates: Sequence[Any],
    *,
    trace_sink: Optional[Any] = None,
    allow_delegate_side_effects: bool = False,
    permission_context: Optional[Any] = None,
    plan_run_id: Optional[str] = None,
    step_mapping: Optional[Mapping[str, str]] = None,
) -> Callable[[Any, Set[str], Set[str]], DelegateToolNode]:
    """Build the ``node_factories["delegate"]`` callable (mirror of make_tool_node_factory)."""
    chain = tuple(delegates)
    mapping = dict(step_mapping or {})

    def factory(node_def: Any, deps: Set[str], succs: Set[str]) -> DelegateToolNode:
        return DelegateToolNode(
            node_id=node_def.id,
            plan_node=DelegatePlanNode.model_validate(node_def.config),
            tool_manager=tool_manager,
            working_memory=working_memory,
            dependencies=set(deps or ()),
            successors=set(succs or ()),
            permission_context=permission_context,
            plan_run_id=plan_run_id,
            step_mapping=mapping,
            delegates=chain,
            trace_sink=trace_sink,
            allow_delegate_side_effects=allow_delegate_side_effects,
        )

    return factory

"""Plan-specific checkpoint policy around the existing flow scheduler."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Tuple

from parrot.bots.flows.core.checkpoint import CheckpointStore
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import FlowResult
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.bots.flows.plan import (
    ExecutionPlan,
    PlanToolNode,
    ensure_tool_node_registered,
    make_tool_node_factory,
    to_flow_definition,
)
from parrot.registry.registry import AgentRegistry

from .models import PLAN_RUN_SHARED_KEY, PlanRunMetadata
from .runs import register_plan_checkpoint_types

__all__ = ("PlanFlow", "build_plan_flow", "plan_run_projector")
_logger = logging.getLogger(__name__)


def plan_run_projector(ctx: FlowContext) -> Dict[str, Any]:
    """Project only the validated plan-run envelope into checkpoint shared data."""
    envelope = ctx.shared_data.get(PLAN_RUN_SHARED_KEY)
    return {PLAN_RUN_SHARED_KEY: envelope} if isinstance(envelope, dict) else {}


class PlanFlow(AgentsFlow):
    """Apply plan-specific checkpoint policy around the existing scheduler."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        """Force required persistence and plan-only projection when enabled."""
        if kwargs.get("checkpoint"):
            kwargs["checkpoint_required"] = True
            kwargs["checkpoint_shared_data"] = plan_run_projector
            kwargs["checkpoint_include_responses"] = False
        super().__init__(name, **kwargs)

    async def _run_flow_scheduler(
        self,
        ctx: FlowContext,
        *,
        on_complete: Tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
    ) -> FlowResult:
        """Write start and terminal records within the checkpointer lease."""
        checkpointer = self._checkpointer
        if checkpointer is not None:
            await checkpointer.checkpoint(ctx, status="running")
        try:
            result = await super()._run_flow_scheduler(ctx, on_complete=on_complete)
        except asyncio.CancelledError:
            raise
        if checkpointer is not None:
            status = "failed" if ctx.errors else "completed"
            await checkpointer.checkpoint(ctx, status=status)
        return result


def build_plan_flow(
    plan: ExecutionPlan,
    *,
    run: PlanRunMetadata,
    tool_manager: Any,
    working_memory: Any,
    agent_registry: AgentRegistry,
    permission_context: Any,
    step_mapping: Mapping[str, str],
    store: Optional[CheckpointStore],
    durable_store: Optional[CheckpointStore],
) -> PlanFlow:
    """Compile a plan and bind its run identity and checkpoint policy."""
    ensure_tool_node_registered(PlanToolNode)
    register_plan_checkpoint_types()
    definition = to_flow_definition(plan)
    factory = make_tool_node_factory(
        tool_manager,
        working_memory,
        permission_context=permission_context,
        plan_run_id=run.run_id,
        step_mapping=dict(step_mapping),
    )
    enabled = store is not None and plan.metadata.checkpoint
    flow = PlanFlow.from_definition(
        definition,
        agent_registry=agent_registry,
        node_factories={"tool": factory},
        checkpoint=enabled,
        durable=enabled and durable_store is not None,
        checkpoint_store=store,
        durable_store=durable_store,
        flow_id=run.run_id,
    )
    _logger.debug(
        "built PlanFlow run_id=%s checkpoint=%s durable=%s",
        run.run_id,
        enabled,
        durable_store is not None,
    )
    return flow

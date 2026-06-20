"""DevLoopNode — shared base for the dev-loop flow nodes.

Adapts the dev-loop nodes to the FEAT-163 ``AgentsFlow`` scheduler
contract:

- carries the ``dependencies`` / ``successors`` / ``fsm`` fields the
  event-driven scheduler expects (the FSM is auto-created per node and
  re-created per run by ``AgentsFlow._materialize_nodes``);
- normalizes the execute signature to ``execute(ctx, deps, **kwargs)``
  where ``ctx`` is a :class:`FlowContext`. For unit-test ergonomics a
  plain dict is also accepted and treated as the shared state itself.

Cross-node payloads (``bug_brief``, ``research_output``,
``development_output``, ``qa_report``, ``run_id``, …) travel in
``FlowContext.shared_data``.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Set, Union

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node


# Matches the userinfo (``user:secret@``) of an https remote URL, e.g. the
# ``x-access-token:<token>@github.com`` form GitToolkit injects for private
# clones — so a token can never surface in git CLI error output (R2).
_GIT_URL_USERINFO_RE = re.compile(r"(https://)[^@/\s]+:[^@/\s]+@")


def scrub_git_output(text: str) -> str:
    """Redact credentials from raw git CLI output before surfacing it.

    Scrubs the userinfo of any https remote URL and, defensively, the value of
    ``GITHUB_TOKEN`` if it appears verbatim. Used by the push paths so a
    ``git push`` failure message never leaks a token.
    """
    redacted = _GIT_URL_USERINFO_RE.sub(r"\1***@", text)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        redacted = redacted.replace(token, "***")
    return redacted


def register_dev_loop_node(name: str):
    """Idempotent ``@register_node`` for the dev-loop node types (FEAT-250).

    The engine's :func:`register_node` deliberately raises on a duplicate
    registration. The dev-loop's lazy-import guarantee (spec §7 R1, exercised
    by ``test_lazy_import``) re-imports ``parrot.flows.dev_loop`` after purging
    it from ``sys.modules`` while the engine's ``NODE_REGISTRY`` persists — so a
    plain ``@register_node`` decorator would raise on the second import. This
    wrapper makes registration a no-op when ``name`` is already registered.
    """

    def _decorator(cls):
        if name in NODE_REGISTRY:
            return cls
        return register_node(name)(cls)

    return _decorator


class DevLoopNode(Node):
    """Base node for the dev-loop flow (FEAT-129 / FEAT-132).

    Subclasses implement ``execute(ctx, deps, **kwargs)`` and use
    :meth:`shared_state` to read/write cross-node payloads.

    Args:
        node_id: Unique identifier within the flow graph.
        dependencies: Upstream node_ids (optional — ``AgentsFlow`` derives
            them from the edge list in explicit-edge mode).
        successors: Downstream node_ids (optional, same reason).
        fsm: Per-run task FSM; auto-created when ``None``.
    """

    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create the FSM; initialise the base logger."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(
                self, "fsm", AgentTaskMachine(agent_name=self.node_id)
            )

    @property
    def name(self) -> str:
        """Node identifier used by the flow router."""
        return self.node_id

    # ── Context helpers ──────────────────────────────────────────────────

    @staticmethod
    def shared_state(ctx: Union[FlowContext, Dict[str, Any]]) -> Dict[str, Any]:
        """Return the mutable cross-node state dict for *ctx*.

        Args:
            ctx: The flow execution context. A :class:`FlowContext` yields
                its ``shared_data``; a plain dict (unit tests) is returned
                as-is.

        Returns:
            The shared mutable mapping.

        Raises:
            TypeError: When *ctx* is neither a FlowContext nor a dict.
        """
        if isinstance(ctx, FlowContext):
            return ctx.shared_data
        if isinstance(ctx, dict):
            return ctx
        raise TypeError(
            f"dev-loop nodes expect FlowContext or dict, got {type(ctx)!r}"
        )

    @staticmethod
    def initial_prompt(ctx: Union[FlowContext, Dict[str, Any]]) -> str:
        """Return the run's initial task/prompt string.

        Args:
            ctx: The flow execution context.

        Returns:
            ``FlowContext.initial_task`` (or the dict's ``"initial_task"``
            key), empty string when absent.
        """
        if isinstance(ctx, FlowContext):
            return ctx.initial_task or ""
        if isinstance(ctx, dict):
            return str(ctx.get("initial_task") or "")
        return ""


__all__ = ["DevLoopNode", "register_dev_loop_node", "scrub_git_output"]

"""Node factories that bind live dependencies into the declarative dev-loop.

:func:`build_dev_loop_node_factories` returns the ``{node_type: factory}`` map
consumed by ``AgentsFlow.from_definition(..., node_factories=...)`` (FEAT-250
TASK-001). Each factory closes over the live dependencies (dispatcher,
toolkits, redis url, repo specs) that a plain ``NodeDefinition.config`` dict
cannot carry, constructs the node with ``node_id == node_def.id``, and stamps
the ``dependencies``/``successors`` the materializer derived from the edges.

Importing this module also triggers ``@register_node`` registration of every
``dev_loop.*`` node type (the node classes are imported here).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from parrot.bots.flows.flow.definition import NodeDefinition
from parrot.flows.dev_loop.models import RepoSpec
from parrot.flows.dev_loop.nodes.base import DevLoopNode
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.research import ResearchNode
from parrot.flows.dev_loop.nodes.revision_handoff import RevisionHandoffNode

# Factory signature consumed by AgentsFlow._materialize_nodes.
NodeFactory = Callable[[NodeDefinition, set, set], DevLoopNode]


def _with_graph(node: DevLoopNode, deps: set, succs: set) -> DevLoopNode:
    """Stamp the edge-derived ``dependencies``/``successors`` onto ``node``."""
    return node.model_copy(update={"dependencies": set(deps), "successors": set(succs)})


def build_dev_loop_node_factories(
    *,
    dispatcher: Any,
    jira_toolkit: Any,
    redis_url: str,
    development_dispatcher: Optional[Any] = None,
    development_profile: Optional[Any] = None,
    development_pool_config: Optional[Any] = None,
    development_dispatcher_builder: Optional[Any] = None,
    development_pool_max: int = 4,
    git_toolkit: Optional[Any] = None,
    log_toolkits: Optional[Dict[str, Any]] = None,
    repos: Optional[List[RepoSpec]] = None,
    codereview_dispatcher: Optional[Any] = None,
    require_deployment_approval: bool = False,
) -> Dict[str, NodeFactory]:
    """Return the ``{dev_loop.* type: factory}`` map binding live deps.

    Args:
        dispatcher: Shared dispatcher for Research/QA and the default
            Development path.
        jira_toolkit: Service-account JiraToolkit.
        redis_url: Redis URL for the intake nodes' event streams.
        development_dispatcher: Optional dispatcher used only by
            ``DevelopmentNode``. Defaults to ``dispatcher``.
        development_profile: Optional dispatch profile passed only to
            ``DevelopmentNode``.
        development_pool_config: Optional :class:`DevAgentPoolConfig`
            (FEAT-323) passed to ``DevelopmentNode``. A
            ``WorkBrief.dev_agents`` found in shared state at run time
            always takes priority over this. ``None`` (default) preserves
            the single-agent behaviour exactly.
        development_dispatcher_builder: Optional ``(DevAgentSpec) ->
            (dispatcher, profile)`` callable (FEAT-323, see
            ``agent_builder.build_dispatcher``) used to materialize pool
            workers and the conflict resolver's claude-code fallback.
        development_pool_max: Hard cap on total pool workers (FEAT-323,
            ``DEV_LOOP_DEV_POOL_MAX``). Defaults to ``4``.
        git_toolkit: Optional ``GitToolkit`` for repo provisioning (FEAT-250).
        log_toolkits: Optional ``{source_kind: toolkit}`` map for ResearchNode.
        repos: Optional ``RepoSpec`` list cloned/pulled before Development.
        codereview_dispatcher: Optional ``AbstractCodeReviewDispatcher``
            (FEAT-270) used by ``QANode`` for the code-review gate. Defaults
            to ``None``, in which case ``QANode`` auto-wraps ``dispatcher``
            in a ``ClaudeCodeReviewDispatcher`` (backward compat).
        require_deployment_approval: FEAT-322 — forwarded to
            ``DeploymentHandoffNode``. Defaults to ``False`` (today's
            behavior, unchanged); set ``True`` to require a
            ``deployment_approval`` HITL gate (resolved via the REST
            command layer, TASK-1855) before the Jira "Ready to Deploy"
            transition. This was previously reachable only by reaching
            into an already-constructed node from a test — code review
            flagged it as dead-end wiring with no real activation path.

    Returns:
        A mapping suitable for ``node_factories=`` on
        ``AgentsFlow.from_definition``.
    """
    log_toolkits = log_toolkits or {}
    repos = repos or []
    development_dispatcher = development_dispatcher or dispatcher

    def intent_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(IntentClassifierNode(redis_url=redis_url, name=nd.id), deps, succs)

    def bug_intake_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(BugIntakeNode(redis_url=redis_url, name=nd.id), deps, succs)

    def research_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            ResearchNode(
                dispatcher=dispatcher,
                jira_toolkit=jira_toolkit,
                log_toolkits=log_toolkits,
                git_toolkit=git_toolkit,
                repos=repos,
                name=nd.id,
            ),
            deps,
            succs,
        )

    def development_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            DevelopmentNode(
                dispatcher=development_dispatcher,
                dispatch_profile=development_profile,
                pool_config=development_pool_config,
                dispatcher_builder=development_dispatcher_builder,
                pool_max=development_pool_max,
                name=nd.id,
            ),
            deps,
            succs,
        )

    def qa_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            QANode(
                dispatcher=dispatcher,
                codereview_dispatcher=codereview_dispatcher,
                name=nd.id,
            ),
            deps,
            succs,
        )

    def handoff_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            DeploymentHandoffNode(
                jira_toolkit=jira_toolkit, git_toolkit=git_toolkit, name=nd.id,
                require_deployment_approval=require_deployment_approval,
            ),
            deps,
            succs,
        )

    def failure_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(FailureHandlerNode(jira_toolkit=jira_toolkit, name=nd.id), deps, succs)

    def close_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(DevLoopCloseNode(jira_toolkit, name=nd.id), deps, succs)

    def revision_handoff_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(RevisionHandoffNode(git_toolkit, name=nd.id), deps, succs)

    return {
        "dev_loop.intent_classifier": intent_factory,
        "dev_loop.bug_intake": bug_intake_factory,
        "dev_loop.research": research_factory,
        "dev_loop.development": development_factory,
        "dev_loop.qa": qa_factory,
        "dev_loop.deployment_handoff": handoff_factory,
        "dev_loop.failure_handler": failure_factory,
        "dev_loop.close": close_factory,
        "dev_loop.revision_handoff": revision_handoff_factory,
    }


__all__ = ["build_dev_loop_node_factories"]

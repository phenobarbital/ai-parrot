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
from parrot.flows.dev_loop.nodes.feature_handoff import FeatureHandoffNode
from parrot.flows.dev_loop.nodes.feedback_router import FeedbackRouterNode
from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
from parrot.flows.dev_loop.nodes.planner import PlannerNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.research import ResearchNode
from parrot.flows.dev_loop.nodes.revision_handoff import RevisionHandoffNode
from parrot.flows.dev_loop.nodes.synthesis import SynthesisNode

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
    wiki_toolkit: Optional[Any] = None,
    graph_memory: Optional[Any] = None,
    require_plan_approval: bool = False,
    skip_qa: bool = False,
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
        wiki_toolkit: FEAT-378 — optional pre-wired ``LLMWikiToolkit``
            used by ``FeatureHandoffNode``'s docs-page ingest (feature-mode
            only; ``None`` degrades that ingest step with a warning).
        graph_memory: FEAT-377 TASK-1915 — an optional
            ``DevLoopGraphMemory`` (built via ``DevLoopGraphMemory.
            from_config()``) forwarded to ``ResearchNode``, ``QANode``,
            ``DevLoopCloseNode`` and ``FailureHandlerNode``. ``None``
            (default) makes every graph-memory seam in those nodes a
            strict no-op — byte-identical to pre-TASK-1914 behavior.
        require_plan_approval: FEAT-377 TASK-1916 (G5) — forwarded to
            ``DevelopmentNode``. Defaults to ``False`` (today's behavior,
            unchanged); set ``True`` to require a ``plan_approval`` HITL
            gate (opened by ``DevelopmentNode`` on its first entry — the
            earliest point after ``ResearchNode`` where a node can block
            the engine's dispatch of the next step, mirroring
            ``require_deployment_approval``'s node-side shape) before the
            agent fleet dispatches. Only takes effect when the run also
            has a ``SessionHost``.
        skip_qa: When ``True``, ``QANode`` returns a synthetic passing
            ``QAReport`` without running deterministic checks or code
            review. Useful for trivial fixes where QA overhead exceeds
            the research + development cycle. Defaults to ``False``.

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
                graph_memory=graph_memory,
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
                require_plan_approval=require_plan_approval,
                jira_toolkit=jira_toolkit,
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
                graph_memory=graph_memory,
                skip_qa=skip_qa,
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
        return _with_graph(
            FailureHandlerNode(
                jira_toolkit=jira_toolkit, graph_memory=graph_memory, name=nd.id,
            ),
            deps,
            succs,
        )

    def close_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            DevLoopCloseNode(jira_toolkit, graph_memory=graph_memory, name=nd.id),
            deps,
            succs,
        )

    def revision_handoff_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(RevisionHandoffNode(git_toolkit, name=nd.id), deps, succs)

    # -- FEAT-378 feature-mode factories ----------------------------------

    def planner_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            PlannerNode(
                dispatcher=dispatcher,
                development_pool_max=development_pool_max,
                name=nd.id,
            ),
            deps,
            succs,
        )

    def synthesis_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(SynthesisNode(dispatcher=dispatcher, name=nd.id), deps, succs)

    def feedback_router_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            FeedbackRouterNode(dispatcher=dispatcher, name=nd.id), deps, succs
        )

    def feature_handoff_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            FeatureHandoffNode(
                jira_toolkit=jira_toolkit,
                git_toolkit=git_toolkit,
                wiki_toolkit=wiki_toolkit,
                name=nd.id,
            ),
            deps,
            succs,
        )

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
        "dev_loop.planner": planner_factory,
        "dev_loop.synthesis": synthesis_factory,
        "dev_loop.feedback_router": feedback_router_factory,
        "dev_loop.feature_handoff": feature_handoff_factory,
    }


__all__ = ["build_dev_loop_node_factories"]

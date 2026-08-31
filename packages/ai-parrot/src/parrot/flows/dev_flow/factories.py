"""Node factories for the dev-flow topology (FEAT-412).

Binds live dependencies to the ``dev-flow`` node types. The eight reused
``dev_loop.*`` types come straight from
:func:`build_dev_loop_node_factories` — dev-flow does not re-implement or
wrap them — and this module only adds the two dev-flow-owned intake types:

* ``dev_flow.dev_intake`` → :class:`DevIntakeNode`
* ``dev_flow.ideation``   → :class:`IdeationNode`

Importing this module imports both node packages, which is what guarantees
their ``@register_dev_loop_node`` decorators have run before the definition
is materialized.
"""

from __future__ import annotations

from typing import Any

from parrot.bots.flows.flow.definition import NodeDefinition
from parrot.flows.dev_flow.complementary_research import (
    ComplementaryResearchCoordinator,
)
from parrot.flows.dev_flow.nodes.dev_intake import DevIntakeNode
from parrot.flows.dev_flow.nodes.ideation import IdeationNode
from parrot.flows.dev_loop.factories import (
    NodeFactory,
    build_dev_loop_node_factories,
)
from parrot.flows.dev_loop.nodes.base import DevLoopNode


def _with_graph(node: DevLoopNode, deps: set, succs: set) -> DevLoopNode:
    """Stamp the edge-derived ``dependencies``/``successors`` onto ``node``.

    Same helper as ``dev_loop.factories._with_graph`` (kept local rather than
    importing a private symbol across packages).
    """
    return node.model_copy(
        update={"dependencies": set(deps), "successors": set(succs)}
    )


def build_dev_flow_node_factories(
    *,
    dispatcher: Any,
    redis_url: str,
    jira_toolkit: Any | None = None,
    git_toolkit: Any | None = None,
    wiki_toolkit: Any | None = None,
    codereview_dispatcher: Any | None = None,
    development_dispatcher_builder: Any | None = None,
    development_pool_max: int = 4,
    graph_memory: Any | None = None,
    wiki_search: Any | None = None,
    require_plan_approval: bool = False,
    skip_qa: bool = False,
    ideation_max_rounds: int | None = None,
    research_coordinator: ComplementaryResearchCoordinator | None = None,
) -> dict[str, NodeFactory]:
    """Return the ``{node type: factory}`` map for the dev-flow graph.

    Args:
        dispatcher: Shared ``ClaudeCodeDispatcher`` for ideation, planner,
            synthesis, QA and the feedback router.
        redis_url: Redis URL for the intake node's event stream.
        jira_toolkit: Optional service-account ``JiraToolkit`` — dev-flow
            Jira is link-only; ``None`` means zero Jira calls anywhere.
        git_toolkit: Optional ``GitToolkit`` (parity with the ops flows).
        wiki_toolkit: Optional ``LLMWikiToolkit`` for ``FeatureHandoffNode``'s
            docs-page ingest.
        codereview_dispatcher: Optional review dispatcher for ``QANode``
            (typically a ``JudgePanelReviewDispatcher``).
        development_dispatcher_builder: Optional ``(DevAgentSpec) ->
            (dispatcher, profile)`` callable for the dev-agent pool.
        development_pool_max: Hard cap on pool workers, also passed to
            ``PlannerNode`` for its own pool sizing.
        graph_memory: Optional ``DevLoopGraphMemory`` forwarded to the reused
            QA/close/failure nodes.
        wiki_search: Optional ``DevLoopWikiSearch``. Forwarded to BOTH the
            reused ``dev_loop`` factories and :class:`IdeationNode`, which
            uses it to inject ranked repo context into its dispatch.
        require_plan_approval: Build-time default for ``DevelopmentNode``'s
            ``plan_approval`` gate. A per-run
            ``shared["require_plan_approval"]`` overrides it (FEAT-412).
        skip_qa: Forwarded to the reused QA factory.
        ideation_max_rounds: Override for ``conf.DEV_FLOW_IDEATION_MAX_ROUNDS``
            on :class:`IdeationNode`. ``None`` reads the conf key at execute
            time.
        research_coordinator: Optional :class:`ComplementaryResearchCoordinator`
            (FEAT-482) injected into :class:`IdeationNode`. ``None``
            (default) builds a fresh one — itself an inert no-op until
            ``DEV_FLOW_RESEARCH_PARTNER`` is configured, so omitting this
            kwarg preserves the pure-addition guarantee.

    Returns:
        A factory map covering the two ``dev_flow.*`` types plus every
        ``dev_loop.*`` type (the reused chain).
    """
    factories: dict[str, NodeFactory] = dict(
        build_dev_loop_node_factories(
            dispatcher=dispatcher,
            jira_toolkit=jira_toolkit,
            redis_url=redis_url,
            git_toolkit=git_toolkit,
            wiki_toolkit=wiki_toolkit,
            development_dispatcher_builder=development_dispatcher_builder,
            development_pool_max=development_pool_max,
            codereview_dispatcher=codereview_dispatcher,
            graph_memory=graph_memory,
            wiki_search=wiki_search,
            require_plan_approval=require_plan_approval,
            skip_qa=skip_qa,
        )
    )

    def dev_intake_factory(
        nd: NodeDefinition, deps: set, succs: set
    ) -> DevLoopNode:
        return _with_graph(
            DevIntakeNode(redis_url=redis_url, name=nd.id), deps, succs
        )

    coordinator = research_coordinator if research_coordinator is not None else ComplementaryResearchCoordinator()

    def ideation_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            IdeationNode(
                dispatcher=dispatcher,
                wiki_search=wiki_search,
                ideation_max_rounds=ideation_max_rounds,
                coordinator=coordinator,
                name=nd.id,
            ),
            deps,
            succs,
        )

    factories["dev_flow.dev_intake"] = dev_intake_factory
    factories["dev_flow.ideation"] = ideation_factory
    return factories


__all__ = ["build_dev_flow_node_factories"]

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

FEAT-486 adds the ``model_plan`` seam: a :class:`DevFlowModelPlan` selects
the LLM for each dev-flow seat, and this module turns it into the wiring
the (reused) ``dev_loop`` factories already accept — a
``DevAgentPoolConfig`` plus ``agent_builder.build_dispatcher`` for the
development pool, and a ``ParallelPerspectiveReviewDispatcher`` pairing a
write-enabled primary reviewer with the read-only Mantle counter-reviewer
for ``QANode``. Omitting ``model_plan`` leaves every factory kwarg
byte-identical to pre-FEAT-486.
"""

from __future__ import annotations

from typing import Any

from parrot.bots.flows.flow.definition import NodeDefinition
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan, resolve_model_plan
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
    return node.model_copy(update={"dependencies": set(deps), "successors": set(succs)})


def _build_primary_reviewer(spec: Any, shared_dispatcher: Any) -> Any:
    """Build the write-enabled primary reviewer named by ``spec``.

    ``claude-code`` (the default) reuses the shared ``ClaudeCodeDispatcher``
    the flow was built with — no second dispatcher is constructed, matching
    how ``build_dev_loop_node_factories`` already wires QA. Any other
    backend is materialized through ``agent_builder.build_dispatcher`` and
    wrapped by its registered review dispatcher, so a ``codex`` primary
    gets a ``CodexCodeDispatcher`` rather than being handed the Claude one.

    Args:
        spec: The plan's ``DevAgentSpec`` for the primary review seat.
        shared_dispatcher: The flow's shared ``ClaudeCodeDispatcher``.

    Returns:
        A write-enabled ``AbstractCodeReviewDispatcher``.

    Raises:
        ValueError: If the backend has no registered *primary* review
            dispatcher — named, with the supported set, before any run.
    """
    from parrot.flows.dev_loop.catalog import PRIMARY_REVIEW_BACKENDS
    from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory

    if spec.agent not in PRIMARY_REVIEW_BACKENDS:
        raise ValueError(
            f"backend {spec.agent!r} cannot serve as the primary reviewer — "
            f"supported: {', '.join(PRIMARY_REVIEW_BACKENDS)}"
        )
    if spec.agent == "claude-code":
        review_dispatcher = shared_dispatcher
    else:
        from parrot.flows.dev_loop.agent_builder import build_dispatcher

        review_dispatcher, _profile = build_dispatcher(spec)
    kwargs: dict[str, Any] = {"dispatcher": review_dispatcher}
    if spec.model:
        kwargs["model"] = spec.model
    return CodeReviewDispatcherFactory.create(spec.agent, **kwargs)


def _assemble_review_pair(plan: DevFlowModelPlan, shared_dispatcher: Any) -> Any:
    """Assemble the plan's review pair as a parallel-perspective reviewer.

    Spec G5: a write-enabled primary (default claude-code /
    ``claude-opus-5``) runs concurrently with the read-only,
    Mantle-hosted counter-reviewer (default ``gpt-5.6-sol``), and
    ``ParallelPerspectiveReviewDispatcher`` merges the two verdicts
    deterministically. ``JudgeSpec`` and the judge panel are NOT involved
    — the pair deliberately rides the parallel dispatcher instead.

    The judge synthesis stays off (``judge_enabled=False``), matching the
    deterministic-merge-is-authoritative default of
    ``DEV_LOOP_CODEREVIEW_JUDGE``.

    Args:
        plan: The already-resolved model plan.
        shared_dispatcher: The flow's shared ``ClaudeCodeDispatcher``.

    Returns:
        A ``ParallelPerspectiveReviewDispatcher`` over the configured pair.
    """
    from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory
    from parrot.flows.dev_loop.dispatchers.mantle import (
        MantleAdversarialReviewDispatcher,
    )

    primary = _build_primary_reviewer(plan.review.primary, shared_dispatcher)
    adversary = MantleAdversarialReviewDispatcher(model=plan.review.counter_model)
    return CodeReviewDispatcherFactory.create("parallel", primary=primary, adversary=adversary)


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
    model_plan: DevFlowModelPlan | None = None,
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
            (typically a ``JudgePanelReviewDispatcher``). FEAT-486: an
            explicit value always wins over ``model_plan.review`` — the
            plan only assembles a pair when this is ``None``.
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
        model_plan: FEAT-486 — per-seat LLM configuration. ``None``
            (default) is byte-identical to pre-FEAT-486: no pool config is
            derived and no dispatcher builder is defaulted. Supplying a
            plan (even an all-defaults one) additionally opts the run into
            ``DEV_FLOW_*`` env resolution via
            :func:`~parrot.flows.dev_flow.model_plan.resolve_model_plan`;
            a non-empty ``dev_pool`` then reaches ``DevelopmentNode`` as a
            ``DevAgentPoolConfig`` with ``agent_builder.build_dispatcher``
            as its worker builder, and ``plan.review`` assembles
            ``QANode``'s review pair (unless ``codereview_dispatcher`` was
            passed explicitly), and ``plan.research_primary`` selects
            :class:`IdeationNode`'s model.

    Returns:
        A factory map covering the two ``dev_flow.*`` types plus every
        ``dev_loop.*`` type (the reused chain).
    """
    # FEAT-486: the plan is resolved (env defaults applied) only when one
    # was actually supplied — an omitted plan must not let a stray
    # DEV_FLOW_DEV_POOL in the environment silently turn a single-agent
    # deployment into a pool (backward-compat acceptance criterion).
    pool_config: Any | None = None
    pool_builder: Any | None = development_dispatcher_builder
    resolved_plan: DevFlowModelPlan | None = None
    if model_plan is not None:
        resolved_plan = resolve_model_plan(model_plan)
        pool_config = resolved_plan.to_pool_config()
        if pool_config is not None and pool_builder is None:
            # Imported lazily: agent_builder pulls in every coding-agent
            # client module, and a plan-less build must not pay for it.
            from parrot.flows.dev_loop.agent_builder import build_dispatcher

            pool_builder = build_dispatcher

    # FEAT-486 (spec G5): assemble the configurable adversarial review
    # pair. Precedence is explicit argument > plan > None (which leaves
    # QANode's own ClaudeCodeReviewDispatcher fallback, qa.py:147-148,
    # exactly as before).
    review_dispatcher = codereview_dispatcher
    if review_dispatcher is None and resolved_plan is not None:
        review_dispatcher = _assemble_review_pair(resolved_plan, dispatcher)

    factories: dict[str, NodeFactory] = dict(
        build_dev_loop_node_factories(
            dispatcher=dispatcher,
            jira_toolkit=jira_toolkit,
            redis_url=redis_url,
            git_toolkit=git_toolkit,
            wiki_toolkit=wiki_toolkit,
            development_pool_config=pool_config,
            development_dispatcher_builder=pool_builder,
            development_pool_max=development_pool_max,
            codereview_dispatcher=review_dispatcher,
            graph_memory=graph_memory,
            wiki_search=wiki_search,
            require_plan_approval=require_plan_approval,
            skip_qa=skip_qa,
        )
    )

    def dev_intake_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(DevIntakeNode(redis_url=redis_url, name=nd.id), deps, succs)

    def ideation_factory(nd: NodeDefinition, deps: set, succs: set) -> DevLoopNode:
        return _with_graph(
            IdeationNode(
                dispatcher=dispatcher,
                wiki_search=wiki_search,
                ideation_max_rounds=ideation_max_rounds,
                # FEAT-486: the research-primary seat's model. `None`
                # (no plan) leaves the node to resolve
                # conf.DEV_FLOW_IDEATION_MODEL itself.
                model=resolved_plan.research_primary if resolved_plan else None,
                name=nd.id,
            ),
            deps,
            succs,
        )

    factories["dev_flow.dev_intake"] = dev_intake_factory
    factories["dev_flow.ideation"] = ideation_factory
    return factories


__all__ = ["build_dev_flow_node_factories"]

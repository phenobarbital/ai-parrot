"""Executable dev-flow builder (FEAT-412).

Mirrors ``build_dev_loop_feature_flow``'s
declarative-materialize-then-explicit-edge pattern (``dev_loop/runner.py``):
the nodes come from :func:`build_dev_flow_definition` through the dev-flow
factories, then every edge is re-declared imperatively because the graph's
OR-joins (``planner`` from two intakes, ``feature_handoff`` from two
predecessors, the ``failure_handler`` fan-in) cannot be fired by the
``from_definition`` AND-join scheduler.

The routing predicates for the reused chain are **imported** from
``dev_loop.flow`` rather than re-implemented, so the dev-flow and
feature-mode graphs cannot silently diverge.
"""

from __future__ import annotations

from typing import Any

from parrot.bots.flows import AgentsFlow
from parrot.flows.dev_flow.definition import (
    DEV_INTAKE,
    IDEATION,
    build_dev_flow_definition,
)
from parrot.flows.dev_flow.factories import build_dev_flow_node_factories
from parrot.flows.dev_loop.definition import (
    CLOSE,
    DEVELOPMENT,
    FAILURE,
    FEATURE_HANDOFF,
    FEEDBACK_ROUTER,
    PLANNER,
    QA,
    SYNTHESIS,
)
from parrot.flows.dev_loop.flow import (
    FlowEventPublisher,
    _feedback_accept,
    _feedback_escalate,
    _feedback_retry,
    _NullAgentRegistry,
    _qa_failed,
    _qa_passed,
)


def _is_nl_request(result: Any) -> bool:
    """True for a natural-language intake (``enhancement``/``new_feature``).

    Python twin of ``definition._CEL_IS_NL_REQUEST``. Checked by ``kind``
    value rather than ``isinstance`` so a dict-like stub still routes
    correctly (same rationale as ``dev_loop.flow._is_feature``).
    """
    return getattr(result, "kind", None) in ("enhancement", "new_feature")


def _is_feature_doc(result: Any) -> bool:
    """True for a document intake (``kind == "feature"``).

    Python twin of ``definition._CEL_IS_FEATURE_DOC``. Equivalent to
    ``dev_loop.flow._is_feature``, redeclared here only so this module's
    predicate set reads as one coherent group.
    """
    return getattr(result, "kind", None) == "feature"


def build_dev_flow(
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
    skip_qa: bool = False,
    require_plan_approval: bool = False,
    ideation_max_rounds: int | None = None,
    name: str = "dev-flow",
    publish_flow_events: bool = True,
    lifecycle_events: bool = True,
) -> AgentsFlow:
    """Build the executable ``dev-flow`` :class:`AgentsFlow`.

    Topology: ``dev_intake`` -(enhancement|new_feature)-> ``ideation`` ->
    ``planner`` (or ``dev_intake`` -(feature)-> ``planner`` directly) ->
    ``development`` -> ``synthesis`` -> ``qa`` -(passed)-> ``feature_handoff``
    -> ``close``; QA failure -> ``feedback_router`` -(escalate)->
    ``failure_handler`` / -(accept_with_notes)-> ``feature_handoff`` /
    -(retry)-> ``development`` (bounded in
    ``FeedbackRouterNode._retry_allowed()``).

    Args:
        dispatcher: Shared ``ClaudeCodeDispatcher`` for ideation and the
            reused planner/synthesis/QA/feedback nodes.
        redis_url: Redis URL for intake/flow-lifecycle events.
        jira_toolkit: Optional ``JiraToolkit`` — link-only, never created.
        git_toolkit: Optional ``GitToolkit`` (parity with the ops flows).
        wiki_toolkit: Optional ``LLMWikiToolkit`` for the handoff's docs ingest.
        codereview_dispatcher: Optional review dispatcher for ``QANode``.
        development_dispatcher_builder: Optional dev-agent pool builder.
        development_pool_max: Hard cap on pool workers.
        graph_memory: Optional ``DevLoopGraphMemory``.
        wiki_search: Optional ``DevLoopWikiSearch`` — repo context for
            ideation and the reused nodes that accept it.
        skip_qa: Forwarded to the reused QA factory.
        require_plan_approval: Build-time default for the ``plan_approval``
            gate; a per-run ``extra_shared["require_plan_approval"]``
            overrides it (FEAT-412 / TASK-2123).
        ideation_max_rounds: Override for ``conf.DEV_FLOW_IDEATION_MAX_ROUNDS``.
        name: Flow name (default ``"dev-flow"``).
        publish_flow_events: When True (default), attach a
            :class:`FlowEventPublisher` to the engine's ``on_node_event`` hook.
        lifecycle_events: When True (default), also attach a
            :class:`parrot.bots.flows.flow.telemetry.FlowLifecycleAdapter`
            (FEAT-479).

    Returns:
        A wired :class:`AgentsFlow` ready to ``run_flow()``.
    """
    definition = build_dev_flow_definition()
    factories = build_dev_flow_node_factories(
        dispatcher=dispatcher,
        redis_url=redis_url,
        jira_toolkit=jira_toolkit,
        git_toolkit=git_toolkit,
        wiki_toolkit=wiki_toolkit,
        codereview_dispatcher=codereview_dispatcher,
        development_dispatcher_builder=development_dispatcher_builder,
        development_pool_max=development_pool_max,
        graph_memory=graph_memory,
        wiki_search=wiki_search,
        require_plan_approval=require_plan_approval,
        skip_qa=skip_qa,
        ideation_max_rounds=ideation_max_rounds,
    )
    staged = AgentsFlow.from_definition(
        definition,
        agent_registry=_NullAgentRegistry(),
        node_factories=factories,
    )
    nodes = staged._materialize_nodes()

    run_id_holder: dict[str, str] = {}
    publisher = FlowEventPublisher(redis_url, run_id_holder) if publish_flow_events else None
    flow = AgentsFlow(name=name, on_node_event=publisher)
    flow._run_id_holder = run_id_holder  # type: ignore[attr-defined]
    flow._event_publisher = publisher  # type: ignore[attr-defined]
    flow._dev_loop_definition = definition  # type: ignore[attr-defined]

    lifecycle_adapter = None
    if lifecycle_events:
        from parrot.bots.flows.flow.telemetry import (  # noqa: PLC0415
            FlowLifecycleAdapter,
        )

        lifecycle_adapter = FlowLifecycleAdapter()
        flow.add_node_event_listener(lifecycle_adapter)
    flow._lifecycle_adapter = lifecycle_adapter  # type: ignore[attr-defined]

    for node in nodes.values():
        flow.add_node(node)

    # -- intake fork (the planner OR-join) --------------------------------
    flow.add_edge(DEV_INTAKE, IDEATION, predicate=_is_nl_request)
    flow.add_edge(DEV_INTAKE, PLANNER, predicate=_is_feature_doc)
    flow.add_edge(IDEATION, PLANNER)

    # -- reused FEAT-378 chain, verbatim ---------------------------------
    flow.add_edge(PLANNER, DEVELOPMENT)
    flow.add_edge(DEVELOPMENT, SYNTHESIS)
    flow.add_edge(SYNTHESIS, QA)
    flow.add_edge(QA, FEATURE_HANDOFF, predicate=_qa_passed)
    flow.add_edge(QA, FEEDBACK_ROUTER, predicate=_qa_failed)
    flow.add_edge(FEEDBACK_ROUTER, FAILURE, predicate=_feedback_escalate)
    flow.add_edge(FEEDBACK_ROUTER, FEATURE_HANDOFF, predicate=_feedback_accept)
    # Bounded repair loop back-edge (FEAT-377/A): the engine's cyclic
    # re-entry resets the development->synthesis->qa->feedback_router cycle.
    # The stop rule lives in FeedbackRouterNode._retry_allowed(), not here.
    flow.add_edge(FEEDBACK_ROUTER, DEVELOPMENT, predicate=_feedback_retry)
    flow.add_edge(FEATURE_HANDOFF, CLOSE)

    for source in (
        DEV_INTAKE,
        IDEATION,
        PLANNER,
        DEVELOPMENT,
        SYNTHESIS,
        QA,
        FEEDBACK_ROUTER,
        FEATURE_HANDOFF,
    ):
        flow.add_edge(source, FAILURE, condition="on_error")

    return flow


__all__ = ["build_dev_flow"]

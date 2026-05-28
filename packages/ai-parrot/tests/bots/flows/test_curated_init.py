"""Verifies the curated parrot.bots.flows.__all__ list (FEAT-196 TASK-1315).

Acceptance criteria:
- All curated symbols are in __all__
- Demoted symbols are NOT in __all__
- Package imports without errors
- Demoted symbols are not importable from root
"""
import parrot.bots.flows as flows_pkg


CURATED_SYMBOLS = {
    "AgentLike", "AgentRef", "DependencyResults", "PromptBuilder",
    "ActionCallback", "CrewHookCallback", "FlowStatus",
    "AgentTaskMachine", "TransitionCondition",
    "Node", "AgentNode", "StartNode", "EndNode",
    "FlowResult", "NodeResult", "NodeExecutionInfo",
    "FlowContext", "FlowTransition",
    "ExecutionMemory", "VectorStoreMixin", "PersistenceMixin", "SynthesisMixin",
    "AgentCrew", "CrewAgentNode",
    "OrchestratorAgent", "A2AOrchestratorAgent",
    "ResultRetrievalTool",
    "AgentsFlow", "NODE_REGISTRY", "register_node", "CompletionEvent",
    "FlowDefinition", "NodeDefinition", "EdgeDefinition",
    "DecisionFlowNode", "InteractiveDecisionNode",
    "BinaryDecision", "ApprovalDecision", "MultiChoiceDecision",
}

DEMOTED_SYMBOLS = {
    "CELPredicateEvaluator",
    "ACTION_REGISTRY", "register_action", "create_action", "BaseAction",
    "LogAction", "NotifyAction", "WebhookAction", "MetricAction",
    "SetContextAction", "ValidateAction", "TransformAction",
    "from_svelteflow", "to_svelteflow",
    "FlowLoader",
}


def test_curated_symbols_in_all():
    """All curated symbols are present in parrot.bots.flows.__all__."""
    for sym in sorted(CURATED_SYMBOLS):
        assert sym in flows_pkg.__all__, (
            f"Symbol missing from __all__: {sym!r}. "
            f"Add it to parrot/bots/flows/__init__.py"
        )


def test_demoted_symbols_not_in_all():
    """Demoted symbols are absent from parrot.bots.flows.__all__."""
    for sym in sorted(DEMOTED_SYMBOLS):
        assert sym not in flows_pkg.__all__, (
            f"Demoted symbol should NOT be in __all__: {sym!r}. "
            f"Remove from parrot/bots/flows/__init__.py"
        )


def test_smoke_import():
    """Package imports without errors and core symbols are accessible."""
    import parrot.bots.flows  # noqa: PLC0415
    assert hasattr(parrot.bots.flows, "AgentsFlow")
    assert hasattr(parrot.bots.flows, "FlowDefinition")
    assert hasattr(parrot.bots.flows, "DecisionFlowNode")


def test_demoted_not_importable_at_root():
    """Demoted symbols raise ImportError when imported from root package."""
    for sym in sorted(DEMOTED_SYMBOLS):
        # The symbol should NOT be accessible as an attribute on the root module.
        # (It may be importable from its submodule path, but NOT from root.)
        assert not hasattr(flows_pkg, sym), (
            f"Demoted symbol {sym!r} is still accessible at "
            f"parrot.bots.flows.{sym} — remove the root import."
        )

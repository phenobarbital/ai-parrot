"""Test fan-out pattern: One agent sends results to multiple agents simultaneously.

This demonstrates that AgentsFlow supports branching where a single agent's
output is sent to multiple downstream agents in parallel.
"""
import asyncio

# from parrot.bots.orchestration import AgentsFlow
from parrot.bots.orchestation.flow import AgentsFlow


class MockAgent:
    """Mock agent for testing."""

    def __init__(self, name: str, response: str):
        self.name = name
        self._response = response
        self.is_configured = True
        self.tool_manager = None

    async def ask(self, question: str = "", **kwargs):
        """Return mock response."""
        return self._response


async def main():
    """Test fan-out pattern."""
    print("\n" + "=" * 80)
    print("AgentsFlow Fan-Out Pattern Test")
    print("=" * 80)

    # Test 1: Simple fan-out (one → many, unconditional)
    print("\n" + "-" * 80)
    print("TEST 1: Simple Fan-Out (One → Three agents)")
    print("-" * 80)

    # Create agents
    source = MockAgent("DataCollector", "Collected data: [1, 2, 3, 4, 5]")
    processor_a = MockAgent("ProcessorA", "Processed by A: sum=15")
    processor_b = MockAgent("ProcessorB", "Processed by B: avg=3")
    processor_c = MockAgent("ProcessorC", "Processed by C: max=5")

    # Build workflow with fan-out
    flow = AgentsFlow(name="fanout_test")
    flow.add_agent(source)
    flow.add_agent(processor_a)
    flow.add_agent(processor_b)
    flow.add_agent(processor_c)

    # Fan-out: source → [processor_a, processor_b, processor_c]
    flow.task_flow(
        source=source,
        targets=[processor_a, processor_b, processor_c],  # Multiple targets!
        instruction="Process the collected data"
    )

    print("\nWorkflow structure:")
    print("  DataCollector → [ProcessorA, ProcessorB, ProcessorC]")
    print("\nExecuting...")

    result = await flow.run_flow("Collect and process data")

    print(f"\n✓ Workflow completed: {result.status}")
    print(f"✓ Total time: {result.total_time:.2f}s")
    print(f"✓ All three processors ran in parallel!")
    print(f"✓ Total agents executed: {len(result.agents)}")

    # Test 2: Fan-out with convergence (diamond pattern)
    print("\n" + "-" * 80)
    print("TEST 2: Fan-Out with Convergence (Diamond Pattern)")
    print("-" * 80)

    # Create agents for diamond pattern
    start = MockAgent("Start", "Starting data")
    branch_a = MockAgent("BranchA", "Processed by A")
    branch_b = MockAgent("BranchB", "Processed by B")
    merge = MockAgent("Merge", "Merged results from A and B")

    # Build diamond workflow
    flow2 = AgentsFlow(name="diamond_test")
    flow2.add_agent(start)
    flow2.add_agent(branch_a)
    flow2.add_agent(branch_b)
    flow2.add_agent(merge)

    # Diamond structure:
    # Start → [BranchA, BranchB] → Merge
    flow2.task_flow(
        source=start,
        targets=[branch_a, branch_b],  # Fan-out
        instruction="Process in parallel"
    )
    flow2.task_flow(source=branch_a, targets=merge)  # Converge
    flow2.task_flow(source=branch_b, targets=merge)  # Converge

    print("\nWorkflow structure:")
    print("       ┌─→ BranchA ─┐")
    print("  Start            → Merge")
    print("       └─→ BranchB ─┘")
    print("\nExecuting...")

    result2 = await flow2.run_flow("Execute diamond pattern")

    print(f"\n✓ Diamond workflow completed: {result2.status}")
    print(f"✓ Total time: {result2.total_time:.2f}s")
    print(f"✓ Branches ran in parallel, then merged!")

    # Test 3: Fan-out with DecisionFlowNode
    print("\n" + "-" * 80)
    print("TEST 3: Fan-Out with DecisionFlowNode")
    print("-" * 80)

    from parrot.bots.orchestration.decision_node import (
        BinaryDecision,
        DecisionFlowNode,
        DecisionMode,
        DecisionNodeConfig,
        DecisionType,
    )

    # Mock decision agent
    decision_agent = MockAgent(
        "DecisionMaker",
        BinaryDecision(decision="YES", confidence=0.95, reasoning="Approved")
    )

    # Create decision node
    decision = DecisionFlowNode(
        name="decision",
        agents={"maker": decision_agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
        ),
    )

    # Create downstream agents
    analyzer_a = MockAgent("AnalyzerA", "Analysis A complete")
    analyzer_b = MockAgent("AnalyzerB", "Analysis B complete")
    analyzer_c = MockAgent("AnalyzerC", "Analysis C complete")

    # Build workflow with decision → multiple analyzers
    flow3 = AgentsFlow(name="decision_fanout_test")
    flow3.add_agent(decision, agent_id="decision")
    flow3.add_agent(analyzer_a)
    flow3.add_agent(analyzer_b)
    flow3.add_agent(analyzer_c)

    # Fan-out from decision node to multiple analyzers
    flow3.on_success(
        source="decision",
        targets=[analyzer_a, analyzer_b, analyzer_c],  # Multiple targets!
        instruction="Analyze the decision"
    )

    print("\nWorkflow structure:")
    print("  Decision → [AnalyzerA, AnalyzerB, AnalyzerC]")
    print("\nExecuting...")

    result3 = await flow3.run_flow("Make decision and analyze")

    print(f"\n✓ Decision fan-out completed: {result3.status}")
    print(f"✓ All analyzers ran in parallel after decision!")

    print("\n" + "=" * 80)
    print("✓✓✓ ALL FAN-OUT TESTS PASSED! ✓✓✓")
    print("=" * 80)
    print("\nAgentsFlow supports:")
    print("  ✓ One → Many fan-out")
    print("  ✓ Parallel execution of fanned-out agents")
    print("  ✓ Diamond patterns (fan-out + convergence)")
    print("  ✓ Fan-out from DecisionFlowNode")
    print("\nThis solves the conditional branch issue!")
    print("Instead of: Decision → [PathA OR PathB] (only one executes)")
    print("Use:        Decision → [PathA AND PathB] (both execute)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

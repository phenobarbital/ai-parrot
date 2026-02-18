# DecisionFlowNode Usage Guide

## Overview

The `DecisionFlowNode` component enables multi-agent decision-making within AgentsFlow workflows. It supports three decision modes: CIO (single coordinator), Ballot (voting), and Consensus (deliberative).

## ✅ What Works Perfectly

- **All three decision modes**: CIO, Ballot, Consensus
- **Vote aggregation**: Equal, custom, seniority, and confidence-based weighting
- **Consensus levels**: UNANIMOUS, STRONG_MAJORITY, MAJORITY, DEADLOCK, DIVIDED
- **HITL escalation**: Automatic escalation on low confidence or split votes
- **FSM integration**: DecisionResult objects work in transition predicates
- **Standalone usage**: Works perfectly without AgentsFlow

## ⚠️ Known Limitation: Conditional Branches with Multiple Terminal Nodes

### The Issue

The AgentsFlow FSM currently expects **ALL terminal nodes** (nodes with no outgoing transitions) to complete, even when they're in mutually exclusive conditional branches.

**Example that fails:**
```python
# ❌ This will get stuck
flow.add_agent(decision_node)
flow.add_agent(admin_creator)   # Terminal node
flow.add_agent(simple_creator)  # Terminal node

flow.on_condition(
    source="decision",
    targets=admin_creator,
    predicate=lambda r: r.final_decision == "YES"
)
flow.on_condition(
    source="decision",
    targets=simple_creator,
    predicate=lambda r: r.final_decision == "NO"
)

# Only ONE path executes, but FSM waits for BOTH terminals to complete
```

### Why This Happens

The FSM's completion check (in `_is_workflow_complete()`):
```python
if terminal_nodes:
    return all(
        node.fsm.current_state == node.fsm.completed or
        (node.fsm.current_state == node.fsm.failed and not node.can_retry)
        for node in terminal_nodes
    )
```

This requires ALL terminal nodes to complete, but in conditional branches only ONE path executes.

## ✅ Solutions and Workarounds

### Solution 1: Single Terminal Node (Recommended)

Route both decision paths to a **single terminal node** that handles both cases:

```python
# ✅ This works perfectly
flow.add_agent(decision_node)
flow.add_agent(account_processor)  # Single terminal handles both cases

flow.task_flow(source=generator, targets="decision")

# Both paths route to same terminal
flow.on_success(
    source="decision",
    targets=account_processor,
    instruction="""Process based on decision:
    - If YES: create admin account
    - If NO: create standard account"""
)

# The processor agent handles both cases internally
```

**Example:** [examples/decision_simple_working.py](examples/decision_simple_working.py)

### Solution 2: Decision Node as Terminal

Make the decision node itself the terminal node - don't add further routing:

```python
# ✅ Decision node is terminal
flow.add_agent(generator)
flow.add_agent(decision_node)  # Terminal - no outgoing transitions

flow.task_flow(source=generator, targets=decision_node)

result = await flow.run_flow("Make decision")

# Access decision directly
decision = flow.nodes["decision_node"].result
if decision.final_decision == "YES":
    # Handle admin case
    pass
else:
    # Handle regular case
    pass
```

### Solution 3: Standalone Usage (No Workflow)

Use DecisionFlowNode directly without AgentsFlow:

```python
# ✅ Perfect for decision-only use cases
decision_node = DecisionFlowNode(
    name="approval_gate",
    agents={"checker": role_checker},
    config=DecisionNodeConfig(
        mode=DecisionMode.CIO,
        decision_type=DecisionType.BINARY,
        decision_schema=BinaryDecision,
    )
)

# Use directly
result = await decision_node.ask("Should we approve?")

if result.final_decision == "YES":
    # Take admin path
    await admin_creator.ask("Create admin account")
else:
    # Take simple path
    await simple_creator.ask("Create simple account")
```

**Example:** [test_decision_standalone.py](test_decision_standalone.py)

### Solution 4: Sequential Processing

Process decisions sequentially rather than in parallel branches:

```python
# ✅ Sequential approach
flow.add_agent(generator)
flow.add_agent(decision_node)
flow.add_agent(conditional_processor)  # Handles routing internally

flow.task_flow(source=generator, targets=decision_node)
flow.task_flow(source=decision_node, targets=conditional_processor)

# conditional_processor uses the decision to route internally
```

## 📖 Complete Examples

### Example 1: Single Terminal (Working)

```python
from parrot.bots import BasicAgent
from parrot.bots.orchestration import AgentsFlow
from parrot.bots.orchestration.decision_node import (
    DecisionFlowNode,
    DecisionMode,
    DecisionNodeConfig,
    DecisionType,
    BinaryDecision,
)

# Create agents
generator = BasicAgent(name="Generator", llm="google_genai:gemini-2.0-flash-exp", ...)
checker = BasicAgent(name="Checker", llm="google_genai:gemini-2.0-flash-exp", ...)
processor = BasicAgent(name="Processor", llm="google_genai:gemini-2.0-flash-exp", ...)

# Create decision node
decision = DecisionFlowNode(
    name="admin_gate",
    agents={"checker": checker},
    config=DecisionNodeConfig(
        mode=DecisionMode.CIO,
        decision_type=DecisionType.BINARY,
        decision_schema=BinaryDecision,
    )
)

# Build workflow
flow = AgentsFlow(name="registration")
flow.add_agent(generator)
flow.add_agent(decision, agent_id="decision")
flow.add_agent(processor)  # Single terminal

flow.task_flow(source=generator, targets="decision")
flow.on_success(source="decision", targets=processor)

# Execute
result = await flow.run_flow("Process registration")
```

### Example 2: Ballot Mode Voting

```python
# Multiple agents vote on approval
committee = {
    "risk": risk_agent,
    "compliance": compliance_agent,
    "finance": finance_agent,
}

approval_vote = DecisionFlowNode(
    name="approval_committee",
    agents=committee,
    config=DecisionNodeConfig(
        mode=DecisionMode.BALLOT,
        decision_type=DecisionType.APPROVAL,
        decision_schema=ApprovalDecision,
        vote_weight_strategy=VoteWeight.CUSTOM,
        custom_weights={"risk": 1.5, "compliance": 1.5, "finance": 1.0},
    )
)

result = await approval_vote.ask("Should we approve this investment?")

if result.final_decision == "APPROVE" and result.consensus_level == "UNANIMOUS":
    # Proceed with investment
    pass
```

### Example 3: Consensus Mode with HITL Escalation

```python
from parrot.bots.orchestration.decision_node import EscalationPolicy

# Deliberative decision with escalation
strategy_decision = DecisionFlowNode(
    name="strategy_consensus",
    agents={
        "analyst1": analyst1,
        "analyst2": analyst2,
        "coordinator": coordinator,
    },
    config=DecisionNodeConfig(
        mode=DecisionMode.CONSENSUS,
        decision_type=DecisionType.MULTI_CHOICE,
        coordinator_agent_name="coordinator",
        cross_pollination_rounds=2,
        escalation_policy=EscalationPolicy(
            enabled=True,
            on_low_confidence=0.7,
            on_split_vote=True,
            hitl_manager=hitl_manager,
            target_humans=["telegram:executive_team"],
            fallback_decision="maintain",
        ),
    )
)

result = await strategy_decision.ask("Which strategy should we pursue?")
```

## 🧪 Testing

### Run Standalone Tests
```bash
source .venv/bin/activate
python test_decision_standalone.py
```

### Run Working Workflow Example
```bash
source .venv/bin/activate
python examples/decision_simple_working.py
```

## 📝 API Reference

### DecisionFlowNode

```python
DecisionFlowNode(
    name: str,                              # Unique identifier
    agents: Dict[str, Agent],               # Agents participating in decision
    config: DecisionNodeConfig,             # Configuration
    shared_tool_manager: Optional[ToolManager] = None,
    default_question_template: Optional[str] = None,
)
```

### DecisionNodeConfig

```python
DecisionNodeConfig(
    mode: DecisionMode,                     # CIO, BALLOT, or CONSENSUS
    decision_type: DecisionType,            # BINARY, APPROVAL, MULTI_CHOICE, CUSTOM
    decision_schema: Optional[type[BaseModel]] = None,  # Pydantic model for output
    vote_weight_strategy: VoteWeight = VoteWeight.EQUAL,
    custom_weights: Optional[Dict[str, float]] = None,
    minimum_votes: Optional[int] = None,
    coordinator_agent_name: Optional[str] = None,  # For CONSENSUS mode
    cross_pollination_rounds: int = 1,
    escalation_policy: Optional[EscalationPolicy] = None,
    options: Optional[List[Dict[str, Any]]] = None,  # For MULTI_CHOICE
)
```

### Decision Modes

- **CIO**: Single coordinator agent makes decisions
  - Required: 1 agent
  - Can escalate to HITL
  - Fast execution

- **BALLOT**: Multiple agents vote, results aggregated
  - Required: 2+ agents
  - Supports vote weighting
  - Parallel execution
  - Consensus level calculation

- **CONSENSUS**: Agents deliberate with cross-pollination
  - Required: 3+ agents (including coordinator)
  - Multi-round refinement
  - Coordinator synthesizes final decision
  - Slowest but most thorough

### Vote Weighting Strategies

- **EQUAL**: All votes weight 1.0
- **CUSTOM**: User-defined weights per agent
- **SENIORITY**: First agent highest weight (1.0, 0.5, 0.33, ...)
- **CONFIDENCE**: Weight by agent's confidence score

### Consensus Levels

- **UNANIMOUS**: All agents agree (100%)
- **STRONG_MAJORITY**: 80%+ agreement
- **MAJORITY**: 60%+ agreement
- **DIVIDED**: <60% but not evenly split
- **DEADLOCK**: Evenly split (50/50)

## 🎯 Best Practices

1. **Use standalone for pure decision-making**
   - No workflow overhead
   - Direct access to DecisionResult
   - Simplest integration

2. **Use single terminal in workflows**
   - Avoids FSM limitation
   - Cleaner flow structure
   - Better performance

3. **Configure escalation policies**
   - Always set fallback decisions
   - Use appropriate confidence thresholds
   - Test escalation paths

4. **Choose the right mode**
   - **CIO**: Fast, simple decisions (90% of use cases)
   - **BALLOT**: Democratic voting on clear options
   - **CONSENSUS**: Complex strategic decisions requiring deliberation

5. **Leverage vote weighting**
   - Give domain experts more weight
   - Use CUSTOM for explicit control
   - Consider CONFIDENCE for dynamic weighting

## 🐛 Troubleshooting

### Workflow gets stuck

**Problem**: Workflow stuck with "No ready agents and no active agents"

**Cause**: Multiple terminal nodes in conditional branches

**Solution**: Use Solution 1 (single terminal) or Solution 3 (standalone)

### Quorum not met

**Problem**: "Quorum not met" error in BALLOT mode

**Cause**: Some agents failed, reducing vote count below `minimum_votes`

**Solution**:
- Handle agent failures gracefully
- Set appropriate `minimum_votes`
- Use `return_exceptions=True` pattern

### Invalid decision schema

**Problem**: Agent returns invalid decision format

**Cause**: LLM didn't follow structured output schema

**Solution**:
- Improve system prompts
- Use examples in prompts
- Add validation in custom schemas

## 🔗 Related Files

- [parrot/bots/orchestration/decision_node.py](parrot/bots/orchestration/decision_node.py) - Implementation
- [tests/test_decision_node.py](tests/test_decision_node.py) - Unit tests
- [test_decision_standalone.py](test_decision_standalone.py) - Standalone tests
- [examples/decision_simple_working.py](examples/decision_simple_working.py) - Working workflow example
- [examples/decision_workflow_example.py](examples/decision_workflow_example.py) - Full example (has conditional branch limitation)

## 📚 Further Reading

- See the approved plan: `.claude/plans/wise-sauteeing-cloud.md`
- AgentsFlow documentation: `parrot/bots/orchestration/fsm.py`
- HITL integration: `parrot/human/node.py`
- Consensus patterns: `parrot/finance/swarm.py`

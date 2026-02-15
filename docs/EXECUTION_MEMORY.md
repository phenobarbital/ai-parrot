# ExecutionMemory Integration Guide

## Overview

ExecutionMemory is a powerful feature in AgentsFlow that enables sophisticated agent collaboration by automatically storing and retrieving execution results. Agents can access previous results from any agent in the workflow, enabling context-aware decision making and eliminating manual result passing.

## Features

✅ **Automatic Result Storage**: Every agent execution is automatically stored
✅ **Agent Collaboration**: Agents can query previous results via ResultRetrievalTool
✅ **Semantic Search**: Optional FAISS-based vector search across all results
✅ **Execution Tracking**: Complete audit trail with timestamps and metadata
✅ **Memory Snapshot**: Full execution history included in CrewResult
✅ **Zero Configuration**: Enabled by default, works out-of-the-box

## Quick Start

### Basic Usage (No Configuration Required)

```python
from parrot.bots import BasicAgent
from parrot.bots.orchestration import AgentsFlow

# Create workflow - ExecutionMemory enabled by default
flow = AgentsFlow(name="my_workflow")

# Add agents
collector = BasicAgent(name="DataCollector", llm="openai:gpt-4o")
analyzer = BasicAgent(name="Analyzer", llm="openai:gpt-4o")

flow.add_agent(collector)
flow.add_agent(analyzer)
flow.task_flow(source=collector, targets=analyzer)

# Execute - results automatically stored
result = await flow.run_flow("Collect and analyze data")

# Access memory snapshot
memory = result.metadata["execution_memory"]
print(f"Executed agents: {memory['execution_order']}")
```

That's it! ExecutionMemory is working automatically.

## Configuration Options

### Disable ExecutionMemory

```python
flow = AgentsFlow(
    name="my_workflow",
    enable_execution_memory=False  # Disable for performance-critical workflows
)
```

### Enable Semantic Search

```python
# Requires: uv pip install sentence-transformers faiss-cpu

flow = AgentsFlow(
    name="my_workflow",
    enable_execution_memory=True,
    embedding_model="all-MiniLM-L6-v2",  # Enable vector search
    vector_dimension=384,
    vector_index_type="Flat"  # Or "FlatIP", "HNSW"
)
```

### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enable_execution_memory` | bool | `True` | Enable/disable ExecutionMemory |
| `embedding_model` | str \| None | `None` | Embedding model for semantic search |
| `vector_dimension` | int | `384` | Dimension of embedding vectors |
| `vector_index_type` | str | `"Flat"` | FAISS index type: "Flat", "FlatIP", "HNSW" |

## Agent Tool Usage

Every agent automatically receives the `execution_context_tool` which provides three actions:

### 1. List Available Agents

```python
# In agent's prompt or system message:
"""
Use the execution_context_tool to see which agents have executed:
{
    "action": "list_agents"
}
"""
```

**Returns:**
```
Agents with available results: DataCollector, Analyzer
```

### 2. Get Specific Agent Result

```python
# In agent's prompt:
"""
Get the DataCollector results:
{
    "action": "get_agent_result",
    "agent_id": "DataCollector"
}
"""
```

**Returns:**
```
Result for DataCollector:
[Full agent output including all details]
```

### 3. Semantic Search (Requires embedding_model)

```python
# In agent's prompt:
"""
Find information about revenue:
{
    "action": "search_results",
    "query": "revenue and financial metrics"
}
"""
```

**Returns:**
```
Match (Score: 0.92) from DataCollector:
Revenue: $125,000 from 890 transactions
---
Match (Score: 0.87) from Analyzer:
Revenue trend: +15% compared to previous period
---
```

## Use Cases

### 1. Data Pipeline with Context Sharing

```python
# Collector → Cleaner → Analyzer → Reporter
flow = AgentsFlow(name="data_pipeline")

collector = BasicAgent(
    name="Collector",
    system_prompt="Collect raw data from sources"
)

cleaner = BasicAgent(
    name="Cleaner",
    system_prompt="""Clean and validate data.
    Use execution_context_tool to get raw data from Collector."""
)

analyzer = BasicAgent(
    name="Analyzer",
    system_prompt="""Analyze cleaned data.
    Use execution_context_tool to access both raw and cleaned data."""
)

reporter = BasicAgent(
    name="Reporter",
    system_prompt="""Create report.
    Use execution_context_tool to search for key findings across all agents."""
)

# Define flow
flow.add_agent(collector)
flow.add_agent(cleaner)
flow.add_agent(analyzer)
flow.add_agent(reporter)

flow.task_flow(source=collector, targets=cleaner)
flow.task_flow(source=cleaner, targets=analyzer)
flow.task_flow(source=analyzer, targets=reporter)

# Execute
result = await flow.run_flow("Generate monthly report")
```

**Benefits:**
- Cleaner can validate against original data
- Analyzer has full context (raw + cleaned)
- Reporter can search across all stages
- No manual result passing required

### 2. Multi-Agent Research with Synthesis

```python
# Source → [Expert1, Expert2, Expert3] → Synthesizer

flow = AgentsFlow(name="research_synthesis")

source = BasicAgent(name="Source", llm="openai:gpt-4o")
expert1 = BasicAgent(name="TechnicalExpert", llm="openai:gpt-4o")
expert2 = BasicAgent(name="BusinessExpert", llm="openai:gpt-4o")
expert3 = BasicAgent(name="LegalExpert", llm="openai:gpt-4o")

synthesizer = BasicAgent(
    name="Synthesizer",
    llm="openai:gpt-4o",
    system_prompt="""Synthesize findings from all experts.
    Use execution_context_tool to:
    1. List all expert agents
    2. Get each expert's analysis
    3. Create comprehensive synthesis"""
)

flow.add_agent(source)
flow.add_agent(expert1)
flow.add_agent(expert2)
flow.add_agent(expert3)
flow.add_agent(synthesizer)

# Fan-out to experts
flow.task_flow(source=source, targets=[expert1, expert2, expert3])

# Converge to synthesizer
flow.task_flow(source=expert1, targets=synthesizer)
flow.task_flow(source=expert2, targets=synthesizer)
flow.task_flow(source=expert3, targets=synthesizer)

result = await flow.run_flow("Analyze AI regulation proposal")
```

**Benefits:**
- Synthesizer automatically accesses all expert opinions
- No complex result aggregation code
- Easy to add/remove experts

### 3. Iterative Refinement with History

```python
# Draft → Reviewer → Refiner (can reference original draft + review)

flow = AgentsFlow(
    name="content_refinement",
    embedding_model="all-MiniLM-L6-v2"  # Enable semantic search
)

drafter = BasicAgent(name="Drafter", llm="openai:gpt-4o")

reviewer = BasicAgent(
    name="Reviewer",
    llm="openai:gpt-4o",
    system_prompt="Review draft and provide feedback"
)

refiner = BasicAgent(
    name="Refiner",
    llm="openai:gpt-4o",
    system_prompt="""Refine content based on review.
    Use execution_context_tool to:
    - Get original draft from Drafter
    - Get feedback from Reviewer
    - Search for specific issues mentioned in review"""
)

# Define flow
flow.add_agent(drafter)
flow.add_agent(reviewer)
flow.add_agent(refiner)

flow.task_flow(source=drafter, targets=reviewer)
flow.task_flow(source=reviewer, targets=refiner)

result = await flow.run_flow("Write technical documentation")
```

**Benefits:**
- Refiner has full context (draft + review)
- Can search semantically for issues
- Preserves complete refinement history

## Direct Memory Access

### Access Memory from CrewResult

```python
result = await flow.run_flow("Execute workflow")

# Get memory snapshot
memory = result.metadata["execution_memory"]

print(f"Original query: {memory['original_query']}")
print(f"Execution order: {memory['execution_order']}")
print(f"Total executions: {memory['total_executions']}")

# Access specific result
for agent_id, agent_result in memory["results"].items():
    print(f"\n{agent_id}:")
    print(f"  Content: {agent_result['content']}")
    print(f"  Timestamp: {agent_result['timestamp']}")
    print(f"  Metadata: {agent_result['metadata']}")
```

### Access Memory During Workflow

```python
# After workflow execution
if flow.execution_memory:
    # Get execution order
    order = flow.execution_memory.execution_order

    # Get specific result
    result = flow.execution_memory.get_results_by_agent("AgentName")
    print(result.to_text())

    # Search semantically (if embedding_model configured)
    matches = flow.execution_memory.search_similar("revenue metrics", top_k=5)
    for chunk, agent_result, score in matches:
        print(f"Score: {score:.2f} - {agent_result.agent_name}")
        print(chunk)
```

## Performance Considerations

### Memory Footprint

- **Per Agent Result**: ~1-5KB (depends on result size)
- **FAISS Vector**: ~1.5KB per vector (384 dimensions)
- **100 Agents**: ~150-500KB total memory usage

### Execution Overhead

| Feature | Overhead | Notes |
|---------|----------|-------|
| Basic storage | <1% | Minimal impact |
| Without vectorization | <5% | Recommended for most workflows |
| With vectorization | <20% | Async, non-blocking |
| Semantic search | ~10-50ms | Per query, depends on index size |

### Optimization Tips

1. **Disable for Simple Workflows**
   ```python
   flow = AgentsFlow(enable_execution_memory=False)  # Maximum performance
   ```

2. **Skip Vectorization for Speed**
   ```python
   flow = AgentsFlow(
       enable_execution_memory=True,
       embedding_model=None  # Storage only, no search
   )
   ```

3. **Use Efficient Index Types**
   ```python
   flow = AgentsFlow(
       embedding_model="all-MiniLM-L6-v2",
       vector_index_type="HNSW"  # Faster search, more memory
   )
   ```

## Integration with DecisionFlowNode

ExecutionMemory works seamlessly with DecisionFlowNode:

```python
from parrot.bots.orchestration.decision_node import (
    DecisionFlowNode, DecisionMode, DecisionNodeConfig,
    DecisionType, BinaryDecision
)

flow = AgentsFlow(name="decision_workflow")

# Create decision node
decision = DecisionFlowNode(
    name="approval_gate",
    agents={"checker": approval_agent},
    config=DecisionNodeConfig(
        mode=DecisionMode.CIO,
        decision_type=DecisionType.BINARY,
        decision_schema=BinaryDecision
    )
)

# Add to flow
flow.add_agent(data_generator)
flow.add_agent(decision, agent_id="decision")
flow.add_agent(processor)

flow.task_flow(source=data_generator, targets="decision")
flow.task_flow(source="decision", targets=processor)

result = await flow.run_flow("Process with approval")

# Access decision history
decision_result = flow.execution_memory.get_results_by_agent("decision")
print(f"Decision: {decision_result.content}")
```

## Debugging and Monitoring

### View Complete Execution History

```python
result = await flow.run_flow("Execute")

snapshot = result.metadata["execution_memory"]

print("=" * 80)
print("EXECUTION HISTORY")
print("=" * 80)

for agent_id in snapshot["execution_order"]:
    agent_data = snapshot["results"][agent_id]
    print(f"\n[{agent_id}]")
    print(f"  Timestamp: {agent_data['timestamp']}")
    print(f"  Content: {agent_data['content'][:100]}...")
    print(f"  Metadata: {agent_data['metadata']}")
```

### Export Memory for Analysis

```python
import json

# Get memory snapshot
snapshot = flow.execution_memory.get_snapshot()

# Save to file
with open("execution_history.json", "w") as f:
    json.dump(snapshot, f, indent=2, default=str)
```

### Monitor Memory Usage

```python
# Check memory statistics
snapshot = flow.execution_memory.get_snapshot()

print(f"Total executions: {snapshot['total_executions']}")
print(f"Re-executions: {snapshot['reexecutions']}")
print(f"Agents executed: {len(snapshot['execution_order'])}")
print(f"Execution graph: {snapshot['execution_graph']}")
```

## API Reference

### AgentsFlow Configuration

```python
AgentsFlow(
    name: str = "AgentsFlow",
    enable_execution_memory: bool = True,
    embedding_model: Optional[str] = None,
    vector_dimension: int = 384,
    vector_index_type: str = "Flat",
    **kwargs
)
```

### ExecutionMemory Methods

```python
# Add result (internal, automatic)
memory.add_result(agent_result, vectorize=True)

# Retrieve by agent ID
result = memory.get_results_by_agent("agent_id")

# Search semantically
matches = memory.search_similar("query", top_k=5)

# Get execution context
context = memory.get_context_for_agent("current_agent_id")

# Get snapshot
snapshot = memory.get_snapshot()

# Clear memory
memory.clear(keep_query=False)
```

### ResultRetrievalTool Actions

```python
# List agents
{"action": "list_agents"}

# Get specific result
{"action": "get_agent_result", "agent_id": "AgentName"}

# Search results (requires embedding_model)
{"action": "search_results", "query": "search term"}
```

## Examples

### Complete Working Example

See [examples/execution_memory_demo.py](../examples/execution_memory_demo.py) for a complete demonstration of:
- Automatic result storage
- Agent collaboration via tool
- Memory snapshot access
- Direct memory queries

### Unit Tests

See [tests/test_execution_memory_integration.py](../tests/test_execution_memory_integration.py) for comprehensive test coverage.

## Troubleshooting

### Tool Not Registered with Agent

**Problem**: Agent doesn't have access to ResultRetrievalTool

**Solution**: Ensure agent has `register_tool()` method:
```python
class MyAgent:
    def register_tool(self, tool):
        self.tool_manager.add_tool(tool, tool.name)
```

### Semantic Search Not Working

**Problem**: Search returns empty results

**Causes**:
1. `embedding_model` not configured
2. `sentence-transformers` not installed
3. FAISS not installed

**Solution**:
```bash
uv pip install sentence-transformers faiss-cpu
```

```python
flow = AgentsFlow(
    name="my_flow",
    embedding_model="all-MiniLM-L6-v2"  # Required for search
)
```

### Memory Not Cleared Between Runs

**Problem**: Old results appear in new runs

**Cause**: ExecutionMemory is automatically cleared on each `run_flow()`

**Check**: Verify you're calling `run_flow()` not manually executing agents

### High Memory Usage

**Problem**: Memory grows with each execution

**Solutions**:
1. Disable vectorization:
   ```python
   flow = AgentsFlow(embedding_model=None)
   ```

2. Disable ExecutionMemory:
   ```python
   flow = AgentsFlow(enable_execution_memory=False)
   ```

3. Limit result storage size (truncate large outputs)

## Best Practices

1. **Use for Complex Workflows**: Most beneficial with 3+ agents
2. **Enable Search Selectively**: Only use `embedding_model` when needed
3. **Design Prompts for Tool Use**: Explicitly tell agents about the tool
4. **Monitor Performance**: Check overhead in production
5. **Export for Debugging**: Save snapshots for issue diagnosis

## Migration from Manual Result Passing

### Before (Manual)

```python
# OLD: Manual result passing
result1 = await agent1.ask("Task 1")
result2 = await agent2.ask(f"Task 2 using {result1}")
result3 = await agent3.ask(f"Task 3 using {result1} and {result2}")
```

### After (ExecutionMemory)

```python
# NEW: Automatic via ExecutionMemory
flow = AgentsFlow(name="auto_flow")
flow.add_agent(agent1)
flow.add_agent(agent2)
flow.add_agent(agent3)

# Agents automatically access previous results via tool
flow.task_flow(source=agent1, targets=agent2)
flow.task_flow(source=agent2, targets=agent3)

result = await flow.run_flow("Execute all tasks")
```

## Future Enhancements

Potential future features:
- Persistent memory across workflow runs
- Memory pruning/summarization for long workflows
- Custom vectorization strategies
- Memory export/import for debugging
- Historical performance weighting
- Cross-workflow memory sharing

## Related Documentation

- [AgentsFlow Guide](ORCHESTRATION.md)
- [DecisionFlowNode Usage](../DECISION_NODE_USAGE.md)
- [Tool Development](../parrot/tools/README.md)
- [Crew System](crew_summary.md)

## Support

For issues or questions:
- GitHub Issues: https://github.com/phenobarbital/ai-parrot/issues
- Documentation: https://github.com/phenobarbital/ai-parrot

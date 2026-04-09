# ExecutionMemory Integration into AgentsFlow - Implementation Plan

## Overview

Integrate the existing ExecutionMemory infrastructure (currently used in Crew) into AgentsFlow to enable:
- Automatic storage of all agent results
- Agent-to-agent result access via ResultRetrievalTool
- Semantic search across execution history
- Complete audit trail and debugging support

## Current State Analysis

### What Exists
- ✅ `ExecutionMemory` class with FAISS vector store ([parrot/bots/orchestration/storage/memory.py](parrot/bots/orchestration/storage/memory.py))
- ✅ `ResultRetrievalTool` for agent access ([parrot/bots/orchestration/tools.py](parrot/bots/orchestration/tools.py))
- ✅ Full integration in `Crew` class (proven working pattern)
- ✅ `AgentResult` model for structured storage

### What's Missing
- ❌ ExecutionMemory not initialized in AgentsFlow
- ❌ Results not automatically stored after agent execution
- ❌ ResultRetrievalTool not registered with agents
- ❌ No integration with run_flow() lifecycle

## Design Decisions

### 1. Optional vs. Required
**Decision**: Make ExecutionMemory **optional** with default **enabled**
- Parameter: `enable_execution_memory: bool = True`
- Rationale:
  - Most workflows benefit from memory
  - Advanced users can disable for performance
  - Backward compatible (doesn't break existing code)

### 2. Vectorization Strategy
**Decision**: Make vectorization **optional** based on embedding_model
- If `embedding_model` provided → enable semantic search
- If `None` → basic storage only (faster, lower overhead)
- Rationale:
  - Simple workflows don't need semantic search
  - Complex workflows get full FAISS benefits

### 3. Tool Registration Strategy
**Decision**: Register ResultRetrievalTool with **each agent** during `add_agent()`
- Check if agent has `register_tool()` method
- Gracefully skip if not supported
- Rationale:
  - Ensures all agents can access memory
  - DecisionFlowNode and other pseudo-agents won't break

### 4. Result Storage Timing
**Decision**: Store results **after successful execution** in `_execute_node()`
- Store only on FSM state = completed
- Include execution metadata (state, timestamp, execution_count)
- Rationale:
  - Failed executions not stored (cleaner history)
  - Retry logic works correctly

## Implementation Steps

### Step 1: Modify AgentsFlow.__init__()
**File**: `parrot/bots/orchestration/fsm.py`

**Changes**:
```python
def __init__(
    self,
    name: str,
    enable_execution_memory: bool = True,
    embedding_model: Optional[str] = None,
    vector_dimension: int = 384,
    vector_index_type: str = "Flat",
    **kwargs
):
    # ... existing initialization ...

    # Initialize ExecutionMemory
    self.enable_execution_memory = enable_execution_memory
    if enable_execution_memory:
        from .storage import ExecutionMemory
        from .tools import ResultRetrievalTool

        self.execution_memory = ExecutionMemory(
            embedding_model=embedding_model,
            dimension=vector_dimension,
            index_type=vector_index_type
        )
        self.retrieval_tool = ResultRetrievalTool(self.execution_memory)
        self.logger.debug(
            f"ExecutionMemory initialized (vectorization={'enabled' if embedding_model else 'disabled'})"
        )
    else:
        self.execution_memory = None
        self.retrieval_tool = None
```

**Location**: After line ~280 (after existing initialization)

### Step 2: Register Tool with Agents
**File**: `parrot/bots/orchestration/fsm.py`

**Changes**: Modify `add_agent()` method
```python
def add_agent(
    self,
    agent: Union[Agent, Any],
    agent_id: Optional[str] = None,
    dependencies: Optional[List[str]] = None,
    max_retries: int = 0,
    error_handling_strategy: str = "stop"
):
    # ... existing agent addition logic ...

    # NEW: Register retrieval tool if memory enabled
    if self.retrieval_tool:
        try:
            # Check if agent supports tool registration
            if hasattr(agent, 'register_tool') and callable(agent.register_tool):
                agent.register_tool(self.retrieval_tool)
                self.logger.debug(
                    f"Registered ResultRetrievalTool with agent '{node_name}'"
                )
        except Exception as e:
            self.logger.warning(
                f"Failed to register retrieval tool with '{node_name}': {e}"
            )

    # ... rest of existing code ...
```

**Location**: After line ~340 (after agent is added to nodes)

### Step 3: Store Results After Execution
**File**: `parrot/bots/orchestration/fsm.py`

**Changes**: Modify `_execute_node()` method
```python
async def _execute_node(self, node: FlowNode):
    """Execute a single node."""
    agent = node.agent
    node_name = node.name

    # ... existing execution logic ...

    try:
        # ... existing ask() call ...
        result = await agent.ask(question, **context)
        extracted_result = self._extract_result(result)
        node.result = extracted_result

        # NEW: Store in ExecutionMemory
        if self.execution_memory:
            await self._store_execution_result(node, extracted_result, execution_time)

        # Mark as completed
        node.fsm.mark_completed()

    except Exception as e:
        # ... existing error handling ...
```

**Location**: After line ~905 (after result extraction, before mark_completed)

### Step 4: Add Result Storage Helper Method
**File**: `parrot/bots/orchestration/fsm.py`

**New Method**:
```python
async def _store_execution_result(
    self,
    node: FlowNode,
    result: Any,
    execution_time: float
):
    """Store agent execution result in ExecutionMemory.

    Args:
        node: The executed FlowNode.
        result: The extracted result from the agent.
        execution_time: Time taken for execution in seconds.
    """
    from ...models.crew import AgentResult
    from datetime import datetime

    try:
        # Create AgentResult for storage
        agent_result = AgentResult(
            agent_id=node.name,
            agent_name=node.name,
            content=result if isinstance(result, str) else str(result),
            timestamp=datetime.now(),
            execution_id=f"{node.name}_{node.fsm.execution_count}",
            parent_execution_id=None,  # Could track re-executions in future
            metadata={
                "state": node.fsm.current_state,
                "execution_count": node.fsm.execution_count,
                "execution_time": execution_time,
                "dependencies": [dep for dep in node.dependencies if dep in self.nodes],
            },
            execution_time=execution_time
        )

        # Add to memory (vectorize if embedding model configured)
        self.execution_memory.add_result(
            agent_result,
            vectorize=True  # Will only vectorize if embedding_model exists
        )

        # Track execution order
        if node.name not in self.execution_memory.execution_order:
            self.execution_memory.execution_order.append(node.name)

        self.logger.debug(
            f"Stored result for '{node.name}' in ExecutionMemory "
            f"(execution_id={agent_result.execution_id})"
        )

    except Exception as e:
        # Don't fail the workflow if storage fails
        self.logger.warning(
            f"Failed to store result in ExecutionMemory for '{node.name}': {e}"
        )
```

**Location**: Add as new method around line ~1050 (near other helper methods)

### Step 5: Initialize Memory on Workflow Start
**File**: `parrot/bots/orchestration/fsm.py`

**Changes**: Modify `run_flow()` method
```python
async def run_flow(
    self,
    initial_input: str = "",
    context: Optional[Dict[str, Any]] = None,
    **kwargs
) -> CrewResult:
    """Execute the workflow."""

    # NEW: Initialize ExecutionMemory for this run
    if self.execution_memory:
        self.execution_memory.original_query = initial_input
        self.execution_memory.clear(keep_query=True)
        self.logger.debug(
            f"ExecutionMemory cleared for new workflow run: '{initial_input[:50]}...'"
        )

    # ... rest of existing run_flow logic ...
```

**Location**: At start of `run_flow()`, after line ~700

### Step 6: Add Memory Access to CrewResult
**File**: `parrot/bots/orchestration/fsm.py`

**Changes**: Modify CrewResult creation in `run_flow()`
```python
# Create final result
return CrewResult(
    output=final_output or last_output,
    responses=responses,
    agents=agents_info,
    errors=errors,
    execution_log=self.execution_log,
    total_time=end_time - start_time,
    status=status,
    metadata={
        "workflow_name": self.name,
        "total_agents": len(self.nodes),
        "executed_agents": len(executed_agents),
        "terminal_nodes": len(terminal_nodes),
        "initial_input": initial_input,
        # NEW: Add execution memory snapshot
        "execution_memory": (
            self.execution_memory.get_snapshot()
            if self.execution_memory
            else None
        ),
    }
)
```

**Location**: Line ~760-774 (final CrewResult creation)

## Testing Strategy

### Unit Tests
**File**: `tests/test_execution_memory_integration.py` (NEW)

Test cases:
1. **Test initialization**
   - Memory enabled by default
   - Memory can be disabled
   - Vectorization optional based on embedding_model

2. **Test tool registration**
   - Tool registered with BasicAgent
   - Gracefully skips pseudo-agents (DecisionFlowNode)
   - No errors if agent doesn't support tools

3. **Test result storage**
   - Results stored after successful execution
   - Execution order tracked correctly
   - Failed executions not stored

4. **Test agent access**
   - Agent can list previous agents
   - Agent can retrieve specific results
   - Agent can search semantically (if vectorization enabled)

5. **Test workflow lifecycle**
   - Memory cleared on each run_flow()
   - Original query preserved
   - Snapshot included in CrewResult

### Integration Test
**File**: `examples/execution_memory_demo.py` (NEW)

Demonstration workflow:
1. DataCollector → gathers data
2. Analyzer → analyzes using ResultRetrievalTool to access DataCollector result
3. Reporter → creates report using semantic search across all previous results

### Performance Test
**File**: `tests/test_memory_performance.py` (NEW)

Verify:
- Overhead with memory disabled: <5% slowdown
- Overhead with memory (no vectorization): <10% slowdown
- Overhead with full vectorization: <20% slowdown
- Memory usage scales linearly with agent count

## Migration Path for Existing Code

### Backward Compatibility
- ✅ All new parameters are optional with sensible defaults
- ✅ Existing AgentsFlow code works unchanged
- ✅ New feature opt-in via parameters

### Example Migration
```python
# OLD CODE (still works, memory enabled by default)
flow = AgentsFlow(name="my_flow")

# NEW CODE (explicit memory configuration)
flow = AgentsFlow(
    name="my_flow",
    enable_execution_memory=True,
    embedding_model="all-MiniLM-L6-v2"  # Enable semantic search
)

# NEW CODE (memory disabled for performance)
flow = AgentsFlow(
    name="my_flow",
    enable_execution_memory=False
)
```

## Documentation Updates

### 1. Update DECISION_NODE_USAGE.md
Add section on using ExecutionMemory with DecisionFlowNode to access decision history.

### 2. Create EXECUTION_MEMORY.md
Comprehensive guide:
- Overview and benefits
- Configuration options
- Tool usage patterns
- Semantic search examples
- Performance considerations

### 3. Update examples/
- Add `execution_memory_basic.py` - Simple demonstration
- Add `execution_memory_advanced.py` - Semantic search demo
- Update existing examples to show optional usage

## Edge Cases & Error Handling

### 1. Agent without register_tool() support
**Scenario**: DecisionFlowNode, custom pseudo-agents
**Handling**: Try-except with warning log, continue without error

### 2. Vectorization failure
**Scenario**: FAISS not installed, embedding model fails
**Handling**: Memory continues with basic storage, disable vectorization

### 3. Large result storage
**Scenario**: Agent returns huge output (>1MB)
**Handling**: ExecutionMemory already handles chunking (500 char chunks)

### 4. Memory storage failure
**Scenario**: Exception during add_result()
**Handling**: Log warning, don't fail workflow execution

### 5. Tool invocation during execution
**Scenario**: Agent tries to access result that hasn't executed yet
**Handling**: Tool returns "No result found for agent_id: X"

## Performance Considerations

### Memory Footprint
- Each AgentResult: ~1-5KB (depending on result size)
- FAISS index: ~1.5KB per vector (384 dimensions)
- 100 agents: ~150-500KB total

### Execution Overhead
- Storage: ~0.1-0.5ms per result
- Vectorization (async): ~5-50ms per result (non-blocking)
- Tool query: ~1-5ms for direct access, ~10-50ms for semantic search

### Optimization Strategies
1. Lazy vectorization (already implemented with asyncio.create_task)
2. Configurable chunking strategy
3. Optional memory (can be disabled)
4. FAISS index type selection (Flat vs HNSW)

## Success Criteria

- [ ] ExecutionMemory initialized in AgentsFlow.__init__()
- [ ] ResultRetrievalTool registered with all compatible agents
- [ ] Results automatically stored after successful execution
- [ ] Execution order tracked correctly
- [ ] Memory cleared on each run_flow() with original_query preserved
- [ ] Memory snapshot included in CrewResult metadata
- [ ] All unit tests pass
- [ ] Integration example demonstrates agent collaboration
- [ ] Performance overhead < 20% with full vectorization
- [ ] Backward compatible (existing code works unchanged)
- [ ] Documentation complete (EXECUTION_MEMORY.md)
- [ ] No errors with DecisionFlowNode or pseudo-agents

## Files to Modify

1. **parrot/bots/orchestration/fsm.py** (MODIFY)
   - Add ExecutionMemory initialization
   - Add tool registration in add_agent()
   - Add result storage in _execute_node()
   - Add _store_execution_result() helper
   - Update run_flow() to initialize memory
   - Update CrewResult to include snapshot

2. **tests/test_execution_memory_integration.py** (NEW)
   - Comprehensive unit tests

3. **examples/execution_memory_demo.py** (NEW)
   - Working demonstration of agent collaboration

4. **docs/EXECUTION_MEMORY.md** (NEW)
   - Complete usage guide

5. **DECISION_NODE_USAGE.md** (MODIFY)
   - Add section on ExecutionMemory integration

## Implementation Timeline

1. **Phase 1: Core Integration** (30 min)
   - Modify AgentsFlow.__init__()
   - Add result storage logic
   - Add helper methods

2. **Phase 2: Testing** (20 min)
   - Write unit tests
   - Create integration example
   - Verify with DecisionFlowNode

3. **Phase 3: Documentation** (15 min)
   - Create EXECUTION_MEMORY.md
   - Update existing docs
   - Add inline code comments

**Total Estimated Time**: ~65 minutes

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Performance degradation | Medium | Make memory optional, lazy vectorization |
| Memory leaks | High | Clear memory on each run, configurable retention |
| Tool registration failures | Low | Graceful error handling, continue without tools |
| FAISS dependency issues | Low | Degrade to basic storage without vectorization |
| Breaking changes | High | All new features opt-in, backward compatible |

## Next Steps After Implementation

1. Monitor performance in production workflows
2. Gather user feedback on tool effectiveness
3. Consider advanced features:
   - Result pruning/summarization for long workflows
   - Persistent memory across workflow runs
   - Memory export/import for debugging
   - Custom vectorization strategies
4. Integration with DecisionFlowNode for decision history tracking

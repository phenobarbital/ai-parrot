# Agent Orchestration System - Complete Guide

## Overview

The Agent Orchestration System allows you to coordinate multiple AI agents to work together on complex tasks. It supports:

- ✅ **Parallel Execution**: Multiple agents work simultaneously
- ✅ **Sequential Execution**: Agents work in a pipeline
- ✅ **Dependency-based Execution**: Tasks execute when dependencies are met
- ✅ **Orchestrator Pattern**: One agent coordinates specialists
- ✅ **Agent-as-Tool**: Agents can use other agents as tools

---

## Core Components

### 1. EnhancedAgentCrew

The main class for coordinating multiple agents.

```python
from parrot.bots.orchestration.crew import EnhancedAgentCrew

crew = EnhancedAgentCrew(
    name="MyResearchCrew",
    agents=[agent1, agent2, agent3],
    shared_tool_manager=tool_manager,  # Optional
    max_workers=3  # For parallel execution
)
```

### 2. OrchestratorAgent

An agent that can delegate tasks to specialist agents.

```python
from parrot.bots.orchestration.agent import OrchestratorAgent

orchestrator = OrchestratorAgent(
    name="Coordinator",
    use_llm='google',
    orchestration_prompt="Your coordination instructions..."
)
```

### 3. AgentTool

Wraps an agent as a tool that can be used by other agents.

```python
from parrot.tools.agent import AgentTool

# Convert agent to tool
tool = AgentTool(
    agent=specialist_agent,
    tool_name="specialist_tool",
    tool_description="Handles specific tasks"
)

# Or use the convenience method
specialist_agent.register_as_tool(
    orchestrator,
    tool_description="Specialist for X"
)
```

---

## Execution Patterns

### Pattern 1: Parallel Execution

Best for independent tasks that can run simultaneously.

```python
# Define parallel tasks
tasks = [
    {'agent_id': 'agent1', 'query': 'Task 1'},
    {'agent_id': 'agent2', 'query': 'Task 2'},
    {'agent_id': 'agent3', 'query': 'Task 3'}
]

# Execute in parallel
result = await crew.execute_parallel(tasks)

# Access results
for agent_id, output in result['results'].items():
    print(f"{agent_id}: {output}")
```

**Use Cases:**
- Web scraping from multiple sources
- Gathering different types of information
- Independent research tasks

**Advantages:**
- ⚡ Fastest execution time
- 🔄 Efficient resource use
- 📊 Clear result separation

### Pattern 2: Sequential Execution (Pipeline)

Best when each agent needs the previous agent's output.

```python
# Execute in sequence
result = await crew.execute_sequential(
    initial_query="Research product X",
    agent_sequence=['researcher', 'analyzer', 'reporter'],
    pass_full_context=True  # Include all previous results
)

# Get final result
final_output = result['final_result']
```

**Use Cases:**
- Data processing pipelines
- Iterative refinement
- Multi-stage analysis

**Advantages:**
- 🔗 Each agent builds on previous work
- 📈 Progressive refinement
- 🎯 Focused processing

### Pattern 3: Dependency-based Execution (DAG)

Best for complex workflows with dependencies.

```python
from parrot.bots.orchestration.crew import CrewTask

# Define tasks with dependencies
tasks = [
    CrewTask(
        task_id="gather_data",
        agent_name="data_agent",
        query="Gather data",
        dependencies=[]  # No deps, starts immediately
    ),
    CrewTask(
        task_id="analyze",
        agent_name="analysis_agent",
        query="Analyze data",
        dependencies=["gather_data"]  # Waits for data
    ),
    CrewTask(
        task_id="report",
        agent_name="report_agent",
        query="Create report",
        dependencies=["gather_data", "analyze"]  # Waits for both
    )
]

# Execute with dependencies
result = await crew.execute_with_dependencies(tasks)
```

**Use Cases:**
- Complex workflows
- Tasks with clear prerequisites
- Optimized parallel + sequential execution

**Advantages:**
- 🎯 Optimal execution order
- ⚡ Parallel when possible
- 🔗 Sequential when needed

### Pattern 4: Orchestrator Pattern

Best when you need intelligent delegation.

```python
# Create orchestrator
orchestrator = OrchestratorAgent(
    name="MainAgent",
    use_llm='google'
)

# Add specialists as tools
specialist1.register_as_tool(orchestrator)
specialist2.register_as_tool(orchestrator)

# The orchestrator decides which specialists to use
response = await orchestrator.conversation(
    question="Complex question requiring multiple specialists"
)
```

**Use Cases:**
- Complex queries requiring expertise
- Dynamic task delegation
- Adaptive workflows

**Advantages:**
- 🧠 Intelligent delegation
- 🔄 Automatic specialist selection
- 📊 Comprehensive responses

---

## Complete Example: Product Research

```python
import asyncio
from parrot.bots.agent import BasicAgent
from parrot.bots.orchestration.crew import EnhancedAgentCrew
from parrot.tools.websearch import WebSearchTool

async def research_product(product_name: str):
    """Complete product research workflow."""

    # 1. Create specialized agents
    info_agent = BasicAgent(
        name="InfoAgent",
        system_prompt="Find product specifications",
        use_llm='google'
    )

    price_agent = BasicAgent(
        name="PriceAgent",
        system_prompt="Find pricing information",
        use_llm='google'
    )

    review_agent = BasicAgent(
        name="ReviewAgent",
        system_prompt="Analyze product reviews",
        use_llm='google'
    )

    # 2. Add tools and configure
    web_tool = WebSearchTool()
    for agent in [info_agent, price_agent, review_agent]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # 3. Create crew
    crew = EnhancedAgentCrew(
        name="ProductResearch",
        agents=[info_agent, price_agent, review_agent]
    )

    # 4. Execute in parallel
    tasks = [
        {
            'agent_id': 'InfoAgent',
            'query': f"Find specs for {product_name}"
        },
        {
            'agent_id': 'PriceAgent',
            'query': f"Find prices for {product_name}"
        },
        {
            'agent_id': 'ReviewAgent',
            'query': f"Analyze reviews for {product_name}"
        }
    ]

    result = await crew.execute_parallel(tasks)

    # 5. Display results
    print(f"\n{'='*80}")
    print(f"PRODUCT RESEARCH: {product_name}")
    print(f"{'='*80}\n")

    for agent_id, output in result['results'].items():
        print(f"\n{agent_id}:")
        print("-" * 80)
        print(output)

    print(f"\n⏱️  Completed in: {result['total_execution_time']:.2f}s")

    return result

# Run
asyncio.run(research_product("iPhone 15 Pro"))
```

---

## Advanced Features

### 1. Shared Tools Across Agents

```python
# Create shared tool manager
from parrot.tools.manager import ToolManager

shared_tools = ToolManager()
shared_tools.add_tool(WebSearchTool())
shared_tools.add_tool(CalculatorTool())

# Create crew with shared tools
crew = EnhancedAgentCrew(
    agents=[agent1, agent2],
    shared_tool_manager=shared_tools
)

# All agents automatically get access to shared tools
```

### 2. Context Passing Between Agents

```python
# Full context mode (default)
result = await crew.execute_sequential(
    initial_query="Task",
    pass_full_context=True  # Each agent sees all previous results
)

# Simple mode
result = await crew.execute_sequential(
    initial_query="Task",
    pass_full_context=False  # Each agent only sees previous result
)
```

### 3. Custom Context Filtering

```python
def filter_context(context: AgentContext) -> AgentContext:
    """Filter sensitive data before passing to agent."""
    # Remove sensitive data
    context.shared_data.pop('api_key', None)
    return context

agent_tool = AgentTool(
    agent=specialist,
    context_filter=filter_context
)
```

### 4. Execution Monitoring

```python
# Execute with logging
result = await crew.execute_parallel(tasks)

# Check execution log
for log in result['execution_log']:
    print(f"Agent: {log['agent_name']}")
    print(f"Success: {log['success']}")
    print(f"Time: {log['execution_time']:.2f}s")
    if 'error' in log:
        print(f"Error: {log['error']}")

# Get summary
summary = crew.get_execution_summary()
print(f"Total agents: {summary['total_agents']}")
print(f"Successful: {summary['successful_agents']}")
print(f"Total time: {summary['total_execution_time']:.2f}s")
```

---

## Best Practices

### 1. Choose the Right Pattern

- **Parallel**: Independent tasks, speed is priority
- **Sequential**: Each step depends on previous
- **Dependencies**: Complex workflows
- **Orchestrator**: Intelligent delegation needed

### 2. Agent Design

```python
# ✅ Good: Focused, single-purpose agent
specialist = BasicAgent(
    name="PriceSpecialist",
    system_prompt="You ONLY find pricing information",
    role="Pricing Expert"
)

# ❌ Bad: Unfocused, multi-purpose agent
generalist = BasicAgent(
    name="DoEverything",
    system_prompt="You do everything"
)
```

### 3. Error Handling

```python
result = await crew.execute_parallel(tasks)

if result['success']:
    # All tasks succeeded
    process_results(result['results'])
else:
    # Some tasks failed
    for log in result['execution_log']:
        if not log['success']:
            print(f"Failed: {log['agent_name']}")
            print(f"Error: {log.get('error')}")
```

### 4. Performance Optimization

```python
# Limit parallel workers
crew = EnhancedAgentCrew(
    agents=agents,
    max_workers=5  # Don't overwhelm the system
)

# Use context wisely
result = await crew.execute_sequential(
    initial_query="Task",
    pass_full_context=False  # Faster, less token usage
)
```

---

## Common Patterns

### Pattern: Research + Analysis + Report

```python
async def research_analyze_report(topic: str):
    researcher = BasicAgent(name="Researcher", ...)
    analyzer = BasicAgent(name="Analyzer", ...)
    reporter = BasicAgent(name="Reporter", ...)

    crew = EnhancedAgentCrew(agents=[researcher, analyzer, reporter])

    return await crew.execute_sequential(
        initial_query=f"Research {topic}",
        pass_full_context=True
    )
```

### Pattern: Multi-Source Gathering

```python
async def gather_from_sources(query: str):
    web_agent = BasicAgent(name="WebSearch", ...)
    db_agent = BasicAgent(name="Database", ...)
    api_agent = BasicAgent(name="API", ...)

    crew = EnhancedAgentCrew(agents=[web_agent, db_agent, api_agent])

    tasks = [
        {'agent_id': 'WebSearch', 'query': f"Web search: {query}"},
        {'agent_id': 'Database', 'query': f"DB query: {query}"},
        {'agent_id': 'API', 'query': f"API call: {query}"}
    ]

    return await crew.execute_parallel(tasks)
```

### Pattern: Orchestrated Expertise

```python
async def expert_consultation(question: str):
    # Create specialists
    tech_expert = BasicAgent(name="TechExpert", ...)
    biz_expert = BasicAgent(name="BizExpert", ...)
    legal_expert = BasicAgent(name="LegalExpert", ...)

    # Create orchestrator
    coordinator = OrchestratorAgent(name="Coordinator", ...)

    # Register specialists
    tech_expert.register_as_tool(coordinator)
    biz_expert.register_as_tool(coordinator)
    legal_expert.register_as_tool(coordinator)

    # Ask question
    return await coordinator.conversation(question)
```

---

## Troubleshooting

### Issue: Agents not executing in parallel

**Solution**: Check max_workers setting

```python
crew = EnhancedAgentCrew(
    agents=agents,
    max_workers=10  # Increase if needed
)
```

### Issue: Context too large

**Solution**: Use simple context passing

```python
result = await crew.execute_sequential(
    initial_query="Task",
    pass_full_context=False  # Reduce context size
)
```

### Issue: Agent tools not available

**Solution**: Ensure tools are registered

```python
# Check tool registration
print(agent.tool_manager.list_tools())

# Re-register if needed
agent.tool_manager.add_tool(tool)
```

---

## API Reference

### EnhancedAgentCrew

```python
crew = EnhancedAgentCrew(
    name: str,
    agents: List[BasicAgent],
    shared_tool_manager: ToolManager,
    max_workers: int = 3
)

# Methods
await crew.execute_parallel(tasks, **kwargs)
await crew.execute_sequential(initial_query, **kwargs)
await crew.execute_with_dependencies(tasks, **kwargs)
crew.add_agent(agent, agent_id)
crew.remove_agent(agent_id)
crew.add_shared_tool(tool, tool_name)
crew.get_execution_summary()
```

### OrchestratorAgent

```python
orchestrator = OrchestratorAgent(
    name: str,
    orchestration_prompt: str,
    **kwargs
)

# Methods
orchestrator.add_agent(agent, tool_name, description)
orchestrator.remove_agent(agent_name)
orchestrator.list_agents()
orchestrator.get_orchestration_stats()
```

### BasicAgent Extensions

```python
# Convert agent to tool
tool = agent.as_tool(
    tool_name: str,
    tool_description: str,
    **kwargs
)

# Register as tool in another agent
agent.register_as_tool(
    target_agent: BasicAgent,
    tool_name: str,
    tool_description: str
)
```

---

## Next Steps

1. **Start Simple**: Begin with parallel or sequential execution
2. **Add Complexity**: Move to dependencies or orchestration as needed
3. **Monitor Performance**: Use execution logs to optimize
4. **Iterate**: Refine agent prompts and workflows based on results

For more examples, see the `examples/` directory in the repository.

# AI-Parrot Agent Orchestration Documentation

## Overview

AI-Parrot provides powerful agent orchestration capabilities through two main classes:
- **AgentCrew**: For sequential, parallel, and DAG-based task execution
- **AgentsFlow**: For finite state machine (FSM) workflows with error handling

## Table of Contents

1. [Core Concepts](#core-concepts)
2. [Data Structures](#data-structures)
3. [AgentCrew Usage](#agentcrew-usage)
4. [AgentsFlow Usage](#agentsflow-usage)
5. [OrchestratorAgent](#orchestratoragent)
6. [Best Practices](#best-practices)
7. [Complete Examples](#complete-examples)

---

## Core Concepts

### Execution Patterns

1. **Sequential (Pipeline)**: Agents execute one after another, each receiving the previous agent's output
2. **Parallel**: Multiple agents execute simultaneously with independent tasks
3. **Workflow (DAG)**: Complex dependency graphs where agents wait for their dependencies
4. **FSM**: State machine with transitions, branching, and error handlers

### Context Sharing

All orchestration patterns use `AgentContext` to share information:
- User and session identifiers
- Original query
- Results from previous agents
- Shared metadata

---

## Data Structures

### AgentExecutionInfo

```python
from dataclasses import dataclass
from typing import Optional, Literal

@dataclass
class AgentExecutionInfo:
    """Information about a single agent's execution in a workflow."""
    agent_name: str
    agent_id: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    execution_time: float = 0.0
    model: Optional[str] = None
    input_query: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    tool_calls: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
```

### CrewResult

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class CrewResult:
    """Comprehensive result from crew execution."""

    # Primary output
    output: str  # Final output from terminal agent
    content: str  # Alias for output (both work!)

    # Status
    status: str  # 'completed', 'failed', 'partial'
    success: bool

    # Execution info
    agents: List[AgentExecutionInfo]  # Detailed info for each agent
    total_time: float
    execution_order: List[str]  # Agent names in order executed

    # Results mapping
    agent_results: Dict[str, str]  # agent_id -> output

    # Error handling
    errors: Dict[str, str]  # agent_id -> error message

    # Metadata
    metadata: Dict[str, Any]  # workflow_type, session_id, etc.

    @property
    def final_agent(self) -> Optional[AgentExecutionInfo]:
        """Get the final agent that executed."""
        return self.agents[-1] if self.agents else None

    @property
    def failed_agents(self) -> List[AgentExecutionInfo]:
        """Get all agents that failed."""
        return [a for a in self.agents if a.status == "failed"]

    def get_agent_output(self, agent_name: str) -> Optional[str]:
        """Get output from a specific agent."""
        return self.agent_results.get(agent_name)
```

### FlowContext

```python
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class FlowContext:
    """Context passed through workflow execution."""
    user_id: str
    session_id: str
    original_query: str
    agent_results: Dict[str, Any] = field(default_factory=dict)
    shared_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_result(self, agent_name: str) -> Any:
        """Get result from a previous agent."""
        return self.agent_results.get(agent_name)

    def add_result(self, agent_name: str, result: Any):
        """Store an agent's result."""
        self.agent_results[agent_name] = result
```

---

## AgentCrew Usage

### 1. Parallel Execution

Execute multiple agents simultaneously for independent tasks.

```python
from parrot.bots.agent import BasicAgent
from parrot.bots.orchestration.crew import AgentCrew, CrewResult
from parrot.tools.google import GoogleSearchTool

async def parallel_research():
    """Run multiple research agents in parallel."""

    # Create specialized agents
    info_agent = BasicAgent(
        name="InfoAgent",
        system_prompt="You find product specifications and features.",
        use_llm='google'
    )

    price_agent = BasicAgent(
        name="PriceAgent",
        system_prompt="You find current product prices.",
        use_llm='google'
    )

    review_agent = BasicAgent(
        name="ReviewAgent",
        system_prompt="You analyze product reviews.",
        use_llm='google'
    )

    # Add tools
    web_tool = GoogleSearchTool()
    for agent in [info_agent, price_agent, review_agent]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(agents=[info_agent, price_agent, review_agent])

    # Define parallel tasks
    product = "iPhone 15 Pro"
    tasks = [
        {'agent_id': 'InfoAgent', 'query': f"Find specs for {product}"},
        {'agent_id': 'PriceAgent', 'query': f"Find prices for {product}"},
        {'agent_id': 'ReviewAgent', 'query': f"Find reviews for {product}"}
    ]

    # Execute in parallel
    result = await crew.run_parallel(tasks)

    # Access results
    print(f"✅ Completed in {result['total_execution_time']:.2f}s")
    for agent_id, output in result['results'].items():
        print(f"\n{agent_id}: {output[:200]}...")

    return result

# Run it
result = await parallel_research()
```

**Output Structure (run_parallel):**
```python
{
    'results': {
        'InfoAgent': 'specs output...',
        'PriceAgent': 'pricing output...',
        'ReviewAgent': 'reviews output...'
    },
    'execution_log': [
        {
            'agent_id': 'InfoAgent',
            'agent_name': 'InfoAgent',
            'input': 'Find specs...',
            'output': 'specs output...',
            'execution_time': 2.5,
            'success': True
        },
        # ... more logs
    ],
    'total_execution_time': 3.2,
    'success': True
}
```

### 2. Sequential Execution (Pipeline)

Execute agents in order, passing output from one to the next.

```python
async def sequential_pipeline():
    """Process through a pipeline of agents."""

    # Create pipeline agents
    researcher = BasicAgent(
        name="Researcher",
        system_prompt="You research products thoroughly.",
        use_llm='google'
    )

    analyzer = BasicAgent(
        name="Analyzer",
        system_prompt="You analyze research data and extract insights.",
        use_llm='google'
    )

    reporter = BasicAgent(
        name="Reporter",
        system_prompt="You create clear, concise reports.",
        use_llm='google'
    )

    # Add tools
    web_tool = GoogleSearchTool()
    for agent in [researcher, analyzer, reporter]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(agents=[researcher, analyzer, reporter])

    # Execute sequentially
    product = "MacBook Pro M3"
    result = await crew.run_sequential(
        initial_query=f"Research {product}",
        pass_full_context=True  # Include all previous outputs
    )

    # Access results
    print(f"✅ Final Report:\n{result['final_result']}")

    summary = crew.get_execution_summary()
    print(f"⏱️  Total time: {summary['total_execution_time']:.2f}s")

    return result

# Run it
result = await sequential_pipeline()
```

**Output Structure (run_sequential):**
```python
{
    'final_result': 'final output from last agent...',
    'execution_log': [
        {
            'agent_id': 'Researcher',
            'agent_name': 'Researcher',
            'agent_index': 0,
            'input': 'Research MacBook Pro M3',
            'output': 'research findings...',
            'full_output': 'complete research...',
            'execution_time': 3.1,
            'success': True
        },
        # ... more logs
    ],
    'agent_results': {
        'Researcher': 'research output...',
        'Analyzer': 'analysis output...',
        'Reporter': 'final report...'
    },
    'success': True
}
```

### 3. Workflow Execution (DAG)

Define complex workflows with dependencies.

```python
async def workflow_with_dependencies():
    """Execute a workflow with complex dependencies."""

    # Create agents
    writer = BasicAgent(
        name="writer",
        system_prompt="Draft a short paragraph on the given topic.",
        use_llm='google'
    )

    editor1 = BasicAgent(
        name="editor1",
        system_prompt="Edit for grammar and clarity.",
        use_llm='google'
    )

    editor2 = BasicAgent(
        name="editor2",
        system_prompt="Edit for style and tone.",
        use_llm='google'
    )

    final_reviewer = BasicAgent(
        name="final_reviewer",
        system_prompt="Consolidate edits into final version.",
        use_llm='google'
    )

    # Configure agents
    web_tool = GoogleSearchTool()
    for agent in [writer, editor1, editor2, final_reviewer]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(agents=[writer, editor1, editor2, final_reviewer])

    # Define workflow:
    # writer -> [editor1, editor2] -> final_reviewer
    crew.task_flow(writer, [editor1, editor2])  # Parallel after writer
    crew.task_flow(editor1, final_reviewer)     # Both editors must complete
    crew.task_flow(editor2, final_reviewer)     # before final reviewer

    # Validate workflow
    await crew.validate_workflow()

    # Visualize workflow
    print(crew.visualize_workflow())

    # Define callback for monitoring
    async def on_complete(agent_name: str, result: Any, context: FlowContext):
        print(f"✓ {agent_name} completed")

    # Run the workflow
    final_results = await crew.run_flow(
        initial_task="Write about climate change",
        on_agent_complete=on_complete
    )

    # Access results
    print("\nFinal Results:")
    print(final_results["results"]["final_reviewer"])

    return final_results

# Run it
results = await workflow_with_dependencies()
```

**Output Structure (run_flow):**
```python
{
    'results': {
        'writer': 'draft paragraph...',
        'editor1': 'grammar edits...',
        'editor2': 'style edits...',
        'final_reviewer': 'final consolidated version...'
    },
    'execution_log': [...],
    'success': True,
    'workflow_graph': {
        'nodes': ['writer', 'editor1', 'editor2', 'final_reviewer'],
        'edges': [
            ('writer', 'editor1'),
            ('writer', 'editor2'),
            ('editor1', 'final_reviewer'),
            ('editor2', 'final_reviewer')
        ]
    }
}
```

### 4. Research with Synthesis

Use the `task()` method for parallel research + LLM synthesis.

```python
from parrot.clients.google import GoogleClient

async def research_with_synthesis():
    """Research in parallel, then synthesize with LLM."""

    # Create agents (as before)
    info_agent = BasicAgent(
        name="InfoAgent",
        system_prompt="Find product information.",
        use_llm='google'
    )
    # ... create other agents ...

    # Create crew with LLM for synthesis
    crew = AgentCrew(
        agents=[info_agent, price_agent, review_agent],
        llm=GoogleClient()  # LLM for synthesis
    )

    # Execute: parallel research + synthesis
    result = await crew.task(
        task="Research iPhone 15 Pro",  # Same task for all
        synthesis_prompt="Create an executive summary of the findings."
    )

    # Result is AIMessage with synthesized content
    print(result.content)

    return result

# Or with custom tasks per agent:
result = await crew.task(
    task={
        'InfoAgent': 'Find specs for iPhone 15 Pro',
        'PriceAgent': 'Find prices for iPhone 15 Pro',
        'ReviewAgent': 'Summarize reviews for iPhone 15 Pro'
    },
    synthesis_prompt="Combine all findings into a buying guide."
)
```

---

## AgentsFlow Usage

`AgentsFlow` provides FSM-based workflows with error handling and state transitions.

### Basic FSM Setup

```python
from parrot.bots.orchestration.fsm import AgentsFlow
from parrot.bots.agent import BasicAgent

async def fsm_workflow():
    """Create a finite state machine workflow."""

    # Create FSM
    crew = AgentsFlow(name="ResearchCrew")

    # Create agents
    researcher = BasicAgent(
        name="Researcher",
        system_prompt="You research products thoroughly.",
        use_llm='google'
    )

    analyzer = BasicAgent(
        name="Analyzer",
        system_prompt="You analyze research data and extract insights.",
        use_llm='google'
    )

    writer = BasicAgent(
        name="Writer",
        system_prompt="You create clear, concise reports.",
        use_llm='google'
    )

    error_handler = BasicAgent(
        name="ErrorHandler",
        system_prompt="You fix errors in analysis and retry tasks.",
        use_llm='google'
    )

    # Add tools and configure
    web_tool = GoogleSearchTool()
    for agent in [researcher, analyzer, writer, error_handler]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()
        crew.add_agent(agent)

    # Define flow: researcher -> analyzer -> writer
    crew.task_flow(researcher, analyzer)
    crew.task_flow(analyzer, writer)

    # Add error handling: if analyzer fails, go to error_handler
    crew.on_error(analyzer, error_handler,
        instruction="Fix the error and retry"
    )
    crew.task_flow(error_handler, analyzer)  # Retry after fixing

    # Execute
    result: CrewResult = await crew.run_flow("Research AI trends in 2025")

    return result

# Run it
result = await fsm_workflow()
```

### Accessing FSM Results

```python
# After running an FSM workflow
result: CrewResult = await crew.run_flow("Research AI trends")

# Status information
print(f"Status: {result.status}")  # 'completed', 'failed', 'partial'
print(f"Success: {result.success}")  # True/False
print(f"Total Time: {result.total_time:.2f}s")

# Final output
print(f"Final Output:\n{result.output}")
# OR
print(f"Final Content:\n{result.content}")  # Both work!

# Execution order with detailed info
print("\n📋 EXECUTION ORDER:")
for i, agent_info in enumerate(result.agents, 1):
    status_icon = "✓" if agent_info.status == "completed" else "✗"
    print(f"{i}. {status_icon} {agent_info.agent_name}")
    print(f"   - Time: {agent_info.execution_time:.2f}s")
    print(f"   - Model: {agent_info.model or 'N/A'}")
    print(f"   - Status: {agent_info.status}")
    if agent_info.error:
        print(f"   - Error: {agent_info.error}")

# Get specific agent outputs
print(f"\nResearcher Output: {result.get_agent_output('Researcher')}")
print(f"Analyzer Output: {result.get_agent_output('Analyzer')}")

# Check completed agents
completed = len([a for a in result.agents if a.status == 'completed'])
total = len(result.agents)
print(f"\nCompleted: {completed}/{total} agents")

# Error handling
if result.errors:
    print("\n❌ ERRORS DETECTED:")
    for agent_id, error in result.errors.items():
        print(f"  {agent_id}: {error}")

# Failed agents
failed = result.failed_agents
if failed:
    print(f"\n⚠️  {len(failed)} agent(s) failed:")
    for agent in failed:
        print(f"  - {agent.agent_name}: {agent.error}")

# Metadata
print("\n📊 METADATA:")
for key, value in result.metadata.items():
    print(f"  {key}: {value}")
```

### Complete FSM Example with Error Handling

```python
async def complete_fsm_example():
    """Complete FSM workflow with error handling and monitoring."""

    crew = AgentsFlow(name="ContentPipeline")

    # Create agents
    drafter = BasicAgent(
        name="Drafter",
        system_prompt="Create initial draft of content.",
        use_llm='google'
    )

    fact_checker = BasicAgent(
        name="FactChecker",
        system_prompt="Verify all facts and claims.",
        use_llm='google'
    )

    editor = BasicAgent(
        name="Editor",
        system_prompt="Edit for clarity and style.",
        use_llm='google'
    )

    publisher = BasicAgent(
        name="Publisher",
        system_prompt="Format and finalize content.",
        use_llm='google'
    )

    error_fixer = BasicAgent(
        name="ErrorFixer",
        system_prompt="Fix errors and inconsistencies.",
        use_llm='google'
    )

    # Configure agents
    for agent in [drafter, fact_checker, editor, publisher, error_fixer]:
        await agent.configure()
        crew.add_agent(agent)

    # Define main flow
    crew.task_flow(drafter, fact_checker)
    crew.task_flow(fact_checker, editor)
    crew.task_flow(editor, publisher)

    # Error handling
    crew.on_error(fact_checker, error_fixer,
        instruction="Fix factual errors"
    )
    crew.on_error(editor, error_fixer,
        instruction="Fix editorial issues"
    )
    crew.task_flow(error_fixer, fact_checker)  # Retry after fix

    # Validation
    await crew.validate_workflow()

    # Visualize
    print(crew.visualize_workflow())

    # Execute with callback
    async def monitor_progress(agent_name: str, result: Any, context: FlowContext):
        print(f"✓ {agent_name} completed - {len(result)} chars output")

    result = await crew.run_flow(
        initial_task="Write an article about quantum computing",
        on_agent_complete=monitor_progress,
        max_retries=3  # Max retries for error recovery
    )

    # Process results
    print(f"\n{'='*80}")
    print("WORKFLOW EXECUTION SUMMARY")
    print(f"{'='*80}")

    print(f"\n✓ Status: {result.status}")
    print(f"✓ Total Time: {result.total_time:.2f}s")
    print(f"✓ Completed Agents: {len([a for a in result.agents if a.status == 'completed'])}/{len(result.agents)}")

    print(f"\n{'─'*80}")
    print("EXECUTION ORDER:")
    print(f"{'─'*80}")
    for i, agent_info in enumerate(result.agents, 1):
        status_icon = "✓" if agent_info.status == "completed" else "✗"
        print(f"{i}. {status_icon} {agent_info.agent_name}")
        print(f"   - Time: {agent_info.execution_time:.2f}s")
        print(f"   - Model: {agent_info.model or 'N/A'}")
        print(f"   - Status: {agent_info.status}")
        if agent_info.error:
            print(f"   - Error: {agent_info.error}")

    print(f"\n{'='*80}")
    print("FINAL ARTICLE:")
    print(f"{'='*80}")
    print(result.output)

    if result.errors:
        print(f"\n{'='*80}")
        print("ERRORS DETECTED:")
        print(f"{'='*80}")
        for agent_id, error in result.errors.items():
            print(f"❌ {agent_id}: {error}")

    return result

# Run it
result = await complete_fsm_example()
```

---

## OrchestratorAgent

`OrchestratorAgent` delegates tasks to specialist agents acting as tools.

```python
from parrot.bots.orchestration.agent import OrchestratorAgent

async def orchestrator_example():
    """Use OrchestratorAgent with specialist agents."""

    # Create specialist agents
    spec_agent = BasicAgent(
        name="TechSpecialist",
        agent_id="tech_specialist",
        role="Technical Specifications Expert",
        goal="Find detailed technical specifications and features",
        system_prompt="""You are a technical specifications expert.

Your specialty is finding detailed technical information about products including:
- Hardware specifications (processor, RAM, storage, display)
- Software features and capabilities
- Technical measurements (dimensions, weight, battery)
- Supported standards and compatibility

Always search the web for the most current and accurate information.""",
        use_llm='google'
    )

    price_agent = BasicAgent(
        name="PriceSpecialist",
        agent_id="price_specialist",
        role="Pricing Research Expert",
        goal="Find current market prices and pricing information",
        system_prompt="""You are a pricing research expert.

Your specialty is finding pricing information including:
- Current retail prices from major retailers
- Price ranges across different configurations
- Available discounts or promotions
- Historical price trends

Always search the web for current pricing.""",
        use_llm='google'
    )

    # Add tools
    web_tool = GoogleSearchTool()
    for agent in [spec_agent, price_agent]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create orchestrator
    orchestrator = OrchestratorAgent(
        name="ProductResearchCoordinator",
        agent_id="coordinator",
        use_llm='google',
        orchestration_prompt="""You are a Product Research Coordinator that delegates tasks to specialist agents.

**CRITICAL: You MUST use the specialist tools to answer questions. You cannot answer directly.**

Available Specialist Tools:
1. techspecialist - Technical specifications expert
   - Use for: product specs, features, technical details

2. pricespecialist - Pricing research expert
   - Use for: prices, costs, pricing information

**How to Answer Questions:**

Step 1: Identify what information is needed
Step 2: Call the appropriate specialist tool(s)
Step 3: Synthesize their responses into a complete answer

**IMPORTANT:**
- ALWAYS use tools - don't try to answer from your own knowledge
- If a question needs both specs and price, call BOTH tools
- Pass clear, specific questions to each specialist"""
    )

    await orchestrator.configure()

    # Register specialists as tools
    spec_agent.register_as_tool(
        orchestrator,
        tool_name="techspecialist",
        tool_description="Technical specifications expert. Use this to find detailed product specs, features, and technical information."
    )

    price_agent.register_as_tool(
        orchestrator,
        tool_name="pricespecialist",
        tool_description="Pricing research expert. Use this to find current product prices, costs, and pricing information from retailers."
    )

    # Test questions
    questions = [
        "What are the specs of the iPad Pro M2?",
        "How much does the iPad Pro M2 cost?",
        "Tell me about the iPhone 15 Pro - both specs and price"
    ]

    for question in questions:
        print(f"\n{'='*80}")
        print(f"QUESTION: {question}")
        print('='*80)

        response = await orchestrator.conversation(
            question=question,
            use_conversation_history=False
        )

        print(f"\n📝 Response:\n{response.content}")

        if response.tool_calls:
            print(f"\n✅ Tools used: {len(response.tool_calls)}")
            for tc in response.tool_calls:
                print(f"  - {tc.name}: {tc.arguments}")
        else:
            print("\n⚠️  WARNING: No tools were used!")

    return orchestrator

# Run it
orchestrator = await orchestrator_example()
```

---

## Best Practices

### 1. Agent Design

**DO:**
- Give agents clear, focused roles
- Use descriptive system prompts
- Provide context about their specialty

**DON'T:**
- Make agents too general-purpose
- Duplicate capabilities across agents
- Use vague instructions

```python
# ✅ GOOD
researcher = BasicAgent(
    name="MarketResearcher",
    system_prompt="You specialize in market research and competitor analysis. Focus on quantitative data and trends."
)

# ❌ BAD
agent = BasicAgent(
    name="Agent1",
    system_prompt="You help with stuff."
)
```

### 2. Tool Management

**Shared Tools:**
```python
# Share tools across all agents in crew
crew = AgentCrew(
    agents=[agent1, agent2],
    shared_tool_manager=ToolManager()
)
crew.add_shared_tool(GoogleSearchTool())
```

**Agent-Specific Tools:**
```python
# Give specific tools to specific agents
agent1.tool_manager.add_tool(GoogleSearchTool())
agent2.tool_manager.add_tool(CalculatorTool())
```

### 3. Error Handling

```python
# Always use try-except for crew operations
try:
    result = await crew.run_sequential(initial_query="Research topic")
    if not result['success']:
        print(f"Workflow partially failed: {result['errors']}")
except Exception as e:
    print(f"Workflow completely failed: {e}")
```

### 4. Context Management

```python
# Pass full context when agents need previous outputs
result = await crew.run_sequential(
    initial_query="Analyze this data",
    pass_full_context=True  # Each agent sees all previous outputs
)

# Pass only previous output for simple pipelines
result = await crew.run_sequential(
    initial_query="Process this text",
    pass_full_context=False  # Each agent only sees immediate previous output
)
```

### 5. Monitoring

```python
# Use callbacks to monitor progress
async def log_progress(agent_name: str, result: Any, context: FlowContext):
    logging.info(f"Agent {agent_name} completed: {len(result)} characters")

result = await crew.run_flow(
    initial_task="Task",
    on_agent_complete=log_progress
)
```

---

## Complete Examples

### Example 1: Research Pipeline

```python
async def research_pipeline():
    """Complete research pipeline with error handling."""

    # Create agents
    searcher = BasicAgent(
        name="Searcher",
        system_prompt="Search the web for information about the topic."
    )

    analyzer = BasicAgent(
        name="Analyzer",
        system_prompt="Analyze search results and extract key insights."
    )

    summarizer = BasicAgent(
        name="Summarizer",
        system_prompt="Create a concise summary of the analysis."
    )

    # Configure
    web_tool = GoogleSearchTool()
    for agent in [searcher, analyzer, summarizer]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(agents=[searcher, analyzer, summarizer])

    # Execute
    try:
        result = await crew.run_sequential(
            initial_query="Research the latest developments in quantum computing",
            pass_full_context=True
        )

        if result['success']:
            print("✅ Research completed successfully")
            print(f"\nFinal Summary:\n{result['final_result']}")

            summary = crew.get_execution_summary()
            print(f"\n⏱️  Statistics:")
            print(f"  - Total time: {summary['total_execution_time']:.2f}s")
            print(f"  - Agents executed: {summary['executed_agents']}")
            print(f"  - Success rate: {summary['successful_agents']}/{summary['executed_agents']}")
        else:
            print("❌ Research failed")
            for log in result['execution_log']:
                if not log['success']:
                    print(f"  - {log['agent_name']}: {log['error']}")

        return result

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        raise

# Run it
result = await research_pipeline()
```

### Example 2: Content Creation Workflow

```python
async def content_workflow():
    """Multi-stage content creation with parallel editing."""

    # Create agents
    writer = BasicAgent(
        name="Writer",
        system_prompt="Write engaging blog posts."
    )

    grammar_editor = BasicAgent(
        name="GrammarEditor",
        system_prompt="Edit for grammar and clarity."
    )

    style_editor = BasicAgent(
        name="StyleEditor",
        system_prompt="Edit for style and tone."
    )

    final_editor = BasicAgent(
        name="FinalEditor",
        system_prompt="Consolidate edits and finalize."
    )

    # Configure
    for agent in [writer, grammar_editor, style_editor, final_editor]:
        await agent.configure()

    # Create crew
    crew = AgentCrew(agents=[writer, grammar_editor, style_editor, final_editor])

    # Define workflow
    crew.task_flow(writer, [grammar_editor, style_editor])  # Parallel editing
    crew.task_flow(grammar_editor, final_editor)
    crew.task_flow(style_editor, final_editor)

    # Validate
    await crew.validate_workflow()

    # Execute
    result = await crew.run_flow(
        initial_task="Write a blog post about sustainable living",
        on_agent_complete=lambda name, output, ctx: print(f"✓ {name} done")
    )

    print(f"\n{'='*80}")
    print("FINAL BLOG POST")
    print(f"{'='*80}")
    print(result["results"]["FinalEditor"])

    return result

# Run it
result = await content_workflow()
```

### Example 3: FSM with Error Recovery

```python
async def fsm_with_retry():
    """FSM workflow with automatic error recovery."""

    crew = AgentsFlow(name="DataPipeline")

    # Create agents
    extractor = BasicAgent(
        name="Extractor",
        system_prompt="Extract data from sources."
    )

    validator = BasicAgent(
        name="Validator",
        system_prompt="Validate data integrity."
    )

    transformer = BasicAgent(
        name="Transformer",
        system_prompt="Transform data to required format."
    )

    loader = BasicAgent(
        name="Loader",
        system_prompt="Load data to destination."
    )

    error_handler = BasicAgent(
        name="ErrorHandler",
        system_prompt="Fix data errors and inconsistencies."
    )

    # Configure
    for agent in [extractor, validator, transformer, loader, error_handler]:
        await agent.configure()
        crew.add_agent(agent)

    # Define flow
    crew.task_flow(extractor, validator)
    crew.task_flow(validator, transformer)
    crew.task_flow(transformer, loader)

    # Error handling with retry
    crew.on_error(validator, error_handler,
        instruction="Fix validation errors in the data"
    )
    crew.on_error(transformer, error_handler,
        instruction="Fix transformation errors"
    )
    crew.task_flow(error_handler, validator)  # Retry from validation

    # Execute
    result: CrewResult = await crew.run_flow(
        initial_task="Process customer data from CSV file",
        max_retries=3
    )

    # Report
    print(f"Status: {result.status}")
    print(f"Success: {result.success}")

    if result.success:
        print(f"\n✅ Pipeline completed successfully in {result.total_time:.2f}s")
    else:
        print(f"\n❌ Pipeline failed")
        for agent in result.failed_agents:
            print(f"  - {agent.agent_name}: {agent.error}")

    return result

# Run it
result = await fsm_with_retry()
```

---

## Summary

### When to Use What

| Pattern | Use Case | Best For |
|---------|----------|----------|
| **Parallel** | Independent tasks that can run simultaneously | Research, data gathering, multi-source analysis |
| **Sequential** | Linear pipeline where each step depends on previous | Processing pipelines, staged workflows |
| **Workflow (DAG)** | Complex dependencies with branching/merging | Content creation, multi-stage processing |
| **FSM** | State-based workflows with error handling | Robust pipelines, retry logic, conditional branching |
| **Orchestrator** | Delegation to specialized agents | Complex queries needing multiple specialists |

### Key Takeaways

1. **AgentCrew** is perfect for straightforward sequential/parallel/workflow execution
2. **AgentsFlow** adds FSM capabilities with error handling and retry logic
3. **OrchestratorAgent** delegates to specialist agents as tools
4. All patterns return structured results with execution details
5. Use `CrewResult` for comprehensive result access
6. Monitor progress with callbacks
7. Always handle errors gracefully

---

## API Reference Summary

### AgentCrew

```python
class AgentCrew:
    def __init__(
        self,
        name: str = "AgentCrew",
        agents: List[Union[BasicAgent, AbstractBot]] = None,
        shared_tool_manager: ToolManager = None,
        max_parallel_tasks: int = 10,
        llm: Optional[AbstractClient] = None
    )

    async def run_parallel(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]
    async def run_sequential(self, initial_query: str, pass_full_context: bool = True) -> Dict[str, Any]
    async def run_flow(self, initial_task: str, on_agent_complete: Callable = None) -> Dict[str, Any]
    async def task(self, task: Union[str, Dict], synthesis_prompt: str = None) -> AIMessage

    def task_flow(self, from_agent: BasicAgent, to_agent: Union[BasicAgent, List[BasicAgent]])
    async def validate_workflow(self)
    def visualize_workflow(self) -> str
    def get_execution_summary(self) -> Dict[str, Any]
```

### AgentsFlow

```python
class AgentsFlow:
    def __init__(self, name: str = "AgentsFlow")

    def add_agent(self, agent: BasicAgent)
    def task_flow(self, from_agent: BasicAgent, to_agent: Union[BasicAgent, List[BasicAgent]])
    def on_error(self, agent: BasicAgent, error_handler: BasicAgent, instruction: str = None)

    async def run_flow(
        self,
        initial_task: str,
        on_agent_complete: Callable = None,
        max_retries: int = 3
    ) -> CrewResult

    async def validate_workflow(self)
    def visualize_workflow(self) -> str
```

### OrchestratorAgent

```python
class OrchestratorAgent(BasicAgent):
    def __init__(
        self,
        name: str,
        agent_id: str = None,
        orchestration_prompt: str = None,
        use_llm: str = 'google'
    )

    def add_agent(
        self,
        agent: BasicAgent,
        tool_name: str = None,
        description: str = None
    )

    async def conversation(
        self,
        question: str,
        use_conversation_history: bool = False
    ) -> AgentResponse
```

---

## Additional Resources

- **AI-Parrot Documentation**: [https://github.com/yourusername/ai-parrot](https://github.com/yourusername/ai-parrot)
- **Examples Directory**: `/examples/orchestration/`
- **Test Suite**: `/tests/test_orchestration.py`

---

**Version**: 1.0
**Last Updated**: October 2025
**Maintained by**: AI-Parrot Team

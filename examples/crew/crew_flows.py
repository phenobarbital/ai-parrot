"""
AgentCrew Usage Examples
=========================
Comprehensive examples demonstrating the three execution modes:
1. Sequential (Pipeline Pattern)
2. Parallel (Independent Concurrent Execution)
3. Flow (DAG-based with Automatic Parallelization)
"""

import asyncio
from typing import Dict, Any
from parrot.bots.orchestration import AgentCrew, FlowContext
from parrot.bots import BasicAgent
from parrot.tools.google import GoogleSearchTool


# ============================================================================
# EXAMPLE 1: Sequential Execution (Pipeline Pattern)
# ============================================================================

async def example_sequential_pipeline():
    """
    Sequential execution is like an assembly line - each agent refines
    the work of the previous agent in a linear pipeline.

    Use Case: Writing a blog post with multiple refinement stages

    Flow: Writer → Grammar Editor → Style Editor → SEO Optimizer → Publisher

    Each agent takes the output of the previous agent and improves it.
    The final result is a polished, optimized blog post.
    """
    print("\n" + "="*70)
    print("EXAMPLE 1: Sequential Pipeline")
    print("="*70 + "\n")

    # Create specialized agents for each stage of the pipeline
    writer = BasicAgent(
        name="content_writer",
        system_prompt="Write engaging blog content on the given topic. Focus on clear explanations.",
        use_llm='google'
    )

    grammar_editor = BasicAgent(
        name="grammar_editor",
        system_prompt="Edit the content for grammar, spelling, and clarity. Fix any errors.",
        use_llm='google'
    )

    style_editor = BasicAgent(
        name="style_editor",
        system_prompt="Improve the writing style, tone, and flow. Make it more engaging.",
        use_llm='google'
    )

    seo_optimizer = BasicAgent(
        name="seo_optimizer",
        system_prompt="Optimize for SEO by adding keywords naturally and improving structure.",
        use_llm='google'
    )

    # Create crew with all agents
    crew = AgentCrew(
        name="BlogPipeline",
        agents=[writer, grammar_editor, style_editor, seo_optimizer]
    )

    # Execute sequential pipeline
    # Each agent processes the output of the previous agent
    result = await crew.run_sequential(
        initial_query="Write a blog post about the benefits of async programming in Python",
        pass_full_context=True  # Each agent sees all previous work
    )

    print("Pipeline Execution Summary:")
    print(f"✓ Final result length: {len(result['final_result'])} characters")
    print(f"✓ Total agents executed: {len(result['execution_log'])}")
    print(f"✓ Success: {result['success']}")
    print(f"\nFinal blog post (first 500 chars):\n{result['final_result'][:500]}...")

    return result


# ============================================================================
# EXAMPLE 2: Parallel Execution (Independent Concurrent)
# ============================================================================

async def example_parallel_research():
    """
    Parallel execution runs multiple agents simultaneously on different tasks.
    Like having multiple researchers each investigating a different aspect
    of a topic at the same time.

    Use Case: Product research from multiple angles

    Agents running in parallel:
    - Features Agent (technical specifications)
    - Pricing Agent (cost analysis)
    - Reviews Agent (user feedback)
    - Competitors Agent (market comparison)

    All agents run simultaneously, then results are aggregated.
    Total time = time of slowest agent (not sum of all agents)
    """
    print("\n" + "="*70)
    print("EXAMPLE 2: Parallel Research")
    print("="*70 + "\n")

    # Create specialized research agents
    features_agent = BasicAgent(
        name="features_researcher",
        system_prompt="Research technical features and specifications of the product.",
        use_llm='google'
    )

    pricing_agent = BasicAgent(
        name="pricing_researcher",
        system_prompt="Research pricing, deals, and value proposition.",
        use_llm='google'
    )

    reviews_agent = BasicAgent(
        name="reviews_researcher",
        system_prompt="Research user reviews, ratings, and common feedback.",
        use_llm='google'
    )

    competitors_agent = BasicAgent(
        name="competitors_researcher",
        system_prompt="Research competing products and how they compare.",
        use_llm='google'
    )

    # Add web search tool to all agents
    web_tool = GoogleSearchTool()
    for agent in [features_agent, pricing_agent, reviews_agent, competitors_agent]:
        agent.tool_manager.add_tool(web_tool)
        await agent.configure()

    # Create crew
    crew = AgentCrew(
        name="ProductResearch",
        agents=[features_agent, pricing_agent, reviews_agent, competitors_agent]
    )

    # Execute all agents in parallel
    # Each agent gets its own specific task
    tasks = [
        {'agent_id': 'features_researcher', 'query': 'Research iPhone 15 Pro features'},
        {'agent_id': 'pricing_researcher', 'query': 'Research iPhone 15 Pro pricing and deals'},
        {'agent_id': 'reviews_researcher', 'query': 'Research iPhone 15 Pro user reviews'},
        {'agent_id': 'competitors_researcher', 'query': 'Compare iPhone 15 Pro to competitors'}
    ]

    result = await crew.run_parallel(tasks=tasks)

    print("Parallel Execution Summary:")
    print(f"✓ Agents executed: {len(result['results'])}")
    print(f"✓ Total execution time: {result['total_execution_time']:.2f} seconds")
    print(f"✓ Success: {result['success']}")

    print("\nResults from each agent:")
    for agent_id, agent_result in result['results'].items():
        print(f"\n{agent_id}:")
        print(f"  {agent_result[:200]}...")

    return result


# ============================================================================
# EXAMPLE 3: Flow-Based Execution (DAG with Auto-Parallelization)
# ============================================================================

async def example_complex_workflow():
    """
    Flow-based execution uses a Directed Acyclic Graph (DAG) to model
    complex workflows with both sequential dependencies and parallel branches.

    Use Case: Content creation with parallel editing and final review

    Workflow structure:

                    writer (initial)
                       |
            +----------+----------+
            |                     |
        editor1               editor2
        (grammar)             (style)
            |                     |
            +----------+----------+
                       |
                 final_reviewer

    Execution flow:
    1. Writer creates initial content (no dependencies)
    2. Editor1 and Editor2 run IN PARALLEL (both depend on writer)
    3. Final Reviewer waits for BOTH editors (depends on both)

    This demonstrates the power of flow-based execution:
    - Sequential where needed (writer must finish first)
    - Parallel where possible (editors can work simultaneously)
    - Synchronization (final reviewer waits for all inputs)
    """
    print("\n" + "="*70)
    print("EXAMPLE 3: Complex Workflow with Flow-Based Execution")
    print("="*70 + "\n")

    # Create agents for the workflow
    writer = BasicAgent(
        name="writer",
        system_prompt="Draft a comprehensive article on the given topic.",
        use_llm='google'
    )

    editor1 = BasicAgent(
        name="editor1",
        system_prompt="Edit for grammar, spelling, and sentence structure.",
        use_llm='google'
    )

    editor2 = BasicAgent(
        name="editor2",
        system_prompt="Edit for style, tone, and readability.",
        use_llm='google'
    )

    final_reviewer = BasicAgent(
        name="final_reviewer",
        system_prompt="""Consolidate both editors' feedback:
        - From editor1: Grammar and structure improvements
        - From editor2: Style and tone improvements
        Create the final polished version incorporating both sets of edits.""",
        use_llm='google'
    )

    # Create crew
    crew = AgentCrew(
        name="ContentWorkflow",
        agents=[writer, editor1, editor2, final_reviewer]
    )

    # Define the workflow using task_flow
    # This builds the dependency graph

    # Step 1: Writer produces initial content
    # (No task_flow call needed - writer has no dependencies, so it's the initial agent)

    # Step 2: Both editors depend on writer (this will enable parallel execution)
    crew.task_flow(writer, [editor1, editor2])

    # Step 3: Final reviewer depends on both editors (synchronization point)
    crew.task_flow(editor1, final_reviewer)
    crew.task_flow(editor2, final_reviewer)

    # Visualize the workflow before execution
    print("Workflow Structure:")
    print(crew.visualize_workflow())
    print()

    # Validate workflow (check for circular dependencies)
    await crew.validate_workflow()
    print("✓ Workflow validation passed\n")

    # Define a callback to monitor execution
    async def on_agent_complete(agent_name: str, result: Any, context: FlowContext):
        print(f"✓ Completed: {agent_name}")
        print(f"  Active tasks: {context.active_tasks}")
        print(f"  Completed tasks: {context.completed_tasks}\n")

    # Execute the flow-based workflow
    result = await crew.run_flow(
        initial_task="Write an article about the future of artificial intelligence",
        on_agent_complete=on_agent_complete
    )

    print("\nFlow Execution Summary:")
    print(f"✓ Completed agents: {len(result['completed'])}")
    print(f"✓ Execution order: {result['completed']}")
    print(f"✓ Errors: {len(result['errors'])}")

    print(f"\nFinal result (first 500 chars):")
    print(f"{result['results']['final_reviewer'][:500]}...")

    return result


# ============================================================================
# EXAMPLE 4: Advanced Flow - Complex Multi-Stage Pipeline
# ============================================================================

async def example_advanced_workflow():
    """
    This example shows a more complex workflow with multiple stages,
    parallel branches at different levels, and multiple synchronization points.

    Workflow structure:

                        research_coordinator
                               |
            +------------------+------------------+
            |                  |                  |
       research1          research2          research3
       (topic A)          (topic B)          (topic C)
            |                  |                  |
            +------------------+------------------+
                               |
                          synthesizer
                               |
            +------------------+------------------+
            |                  |                  |
      fact_checker        style_editor      seo_optimizer
            |                  |                  |
            +------------------+------------------+
                               |
                         final_publisher

    This demonstrates:
    - Multiple stages of parallel execution
    - Fan-out (1 → many) and fan-in (many → 1) patterns
    - Multiple synchronization points
    - Complex data flow through the pipeline
    """
    print("\n" + "="*70)
    print("EXAMPLE 4: Advanced Multi-Stage Workflow")
    print("="*70 + "\n")

    # Stage 1: Research Coordinator
    research_coordinator = BasicAgent(
        name="research_coordinator",
        system_prompt="Break down the topic into key research areas and provide direction.",
        use_llm='google'
    )

    # Stage 2: Parallel Researchers (fan-out from coordinator)
    researcher1 = BasicAgent(
        name="researcher1",
        system_prompt="Research historical context and background.",
        use_llm='google'
    )

    researcher2 = BasicAgent(
        name="researcher2",
        system_prompt="Research current trends and developments.",
        use_llm='google'
    )

    researcher3 = BasicAgent(
        name="researcher3",
        system_prompt="Research future predictions and implications.",
        use_llm='google'
    )

    # Stage 3: Synthesizer (fan-in from researchers)
    synthesizer = BasicAgent(
        name="synthesizer",
        system_prompt="Combine all research into a cohesive narrative.",
        use_llm='google'
    )

    # Stage 4: Parallel Refiners (fan-out from synthesizer)
    fact_checker = BasicAgent(
        name="fact_checker",
        system_prompt="Verify facts and add citations.",
        use_llm='google'
    )

    style_editor = BasicAgent(
        name="style_editor",
        system_prompt="Improve writing style and readability.",
        use_llm='google'
    )

    seo_optimizer = BasicAgent(
        name="seo_optimizer",
        system_prompt="Optimize for search engines.",
        use_llm='google'
    )

    # Stage 5: Final Publisher (fan-in from refiners)
    final_publisher = BasicAgent(
        name="final_publisher",
        system_prompt="Integrate all refinements and prepare final publication.",
        use_llm='google'
    )

    # Create crew with all agents
    crew = AgentCrew(
        name="AdvancedContentPipeline",
        agents=[
            research_coordinator, researcher1, researcher2, researcher3,
            synthesizer, fact_checker, style_editor, seo_optimizer, final_publisher
        ]
    )

    # Define the complex workflow

    # Stage 1 → Stage 2: Coordinator fans out to three researchers
    crew.task_flow(research_coordinator, [researcher1, researcher2, researcher3])

    # Stage 2 → Stage 3: All researchers feed into synthesizer
    crew.task_flow([researcher1, researcher2, researcher3], synthesizer)

    # Stage 3 → Stage 4: Synthesizer fans out to three refiners
    crew.task_flow(synthesizer, [fact_checker, style_editor, seo_optimizer])

    # Stage 4 → Stage 5: All refiners feed into final publisher
    crew.task_flow([fact_checker, style_editor, seo_optimizer], final_publisher)

    # Visualize and validate
    print("Advanced Workflow Structure:")
    print(crew.visualize_workflow())
    print()

    await crew.validate_workflow()
    print("✓ Complex workflow validation passed\n")

    # Execute with monitoring
    execution_stages = {}

    async def monitor_execution(agent_name: str, result: Any, context: FlowContext):
        stage = len(context.completed_tasks)
        if stage not in execution_stages:
            execution_stages[stage] = []
        execution_stages[stage].append(agent_name)
        print(f"Stage {stage}: {agent_name} completed")

    result = await crew.run_flow(
        initial_task="Create comprehensive content about quantum computing",
        on_agent_complete=monitor_execution
    )

    print("\nAdvanced Workflow Summary:")
    print(f"✓ Total stages: {len(execution_stages)}")
    for stage, agents in sorted(execution_stages.items()):
        print(f"  Stage {stage}: {', '.join(agents)}")

    print(f"\nExecution order: {result['completed']}")
    print(f"Final publication (first 300 chars):\n{result['results']['final_publisher'][:300]}...")

    return result


# ============================================================================
# EXAMPLE 5: Using all three modes together
# ============================================================================

async def example_hybrid_approach():
    """
    This example demonstrates using different execution modes for different
    parts of a larger workflow. This shows how the three modes can complement
    each other in a real-world application.

    Scenario: Market Research Report Generation

    Phase 1 (Parallel): Gather data from multiple sources simultaneously
    Phase 2 (Flow): Process and analyze data with dependencies
    Phase 3 (Sequential): Refine and format the final report
    """
    print("\n" + "="*70)
    print("EXAMPLE 5: Hybrid Approach Using All Three Modes")
    print("="*70 + "\n")

    # Phase 1: Parallel data gathering
    print("Phase 1: Parallel Data Gathering")
    print("-" * 50)

    data_agents = [
        BasicAgent(name="market_data", system_prompt="Gather market size and trends", use_llm='google'),
        BasicAgent(name="competitor_data", system_prompt="Research competitors", use_llm='google'),
        BasicAgent(name="customer_data", system_prompt="Analyze customer feedback", use_llm='google'),
        BasicAgent(name="financial_data", system_prompt="Collect financial metrics", use_llm='google')
    ]

    data_crew = AgentCrew(name="DataGathering", agents=data_agents)

    data_result = await data_crew.run_parallel(
        tasks=[
            {'agent_id': 'market_data', 'query': 'Research electric vehicle market'},
            {'agent_id': 'competitor_data', 'query': 'Research Tesla competitors'},
            {'agent_id': 'customer_data', 'query': 'Analyze Tesla customer feedback'},
            {'agent_id': 'financial_data', 'query': 'Get Tesla financial data'}
        ]
    )

    print(f"✓ Phase 1 complete: {len(data_result['results'])} datasets gathered\n")

    # Phase 2: Flow-based analysis with dependencies
    print("Phase 2: Flow-Based Analysis")
    print("-" * 50)

    analysis_agents = [
        BasicAgent(name="swot_analyzer", system_prompt="Perform SWOT analysis", use_llm='google'),
        BasicAgent(name="trend_analyzer", system_prompt="Identify key trends", use_llm='google'),
        BasicAgent(name="risk_analyzer", system_prompt="Assess risks", use_llm='google'),
        BasicAgent(name="opportunity_analyzer", system_prompt="Identify opportunities", use_llm='google'),
        BasicAgent(name="strategic_synthesizer", system_prompt="Synthesize strategic insights", use_llm='google')
    ]

    analysis_crew = AgentCrew(name="Analysis", agents=analysis_agents)

    # SWOT and Trend run in parallel on raw data
    # Risk and Opportunity run in parallel after SWOT
    # Strategic synthesizer waits for all analysis
    analysis_crew.task_flow(swot_analyzer, [risk_analyzer, opportunity_analyzer])
    analysis_crew.task_flow(
        [swot_analyzer, trend_analyzer, risk_analyzer, opportunity_analyzer],
        strategic_synthesizer
    )

    analysis_result = await analysis_crew.run_flow(
        initial_task=f"Analyze this data: {data_result['results']}"
    )

    print(f"✓ Phase 2 complete: Strategic insights generated\n")

    # Phase 3: Sequential refinement
    print("Phase 3: Sequential Report Refinement")
    print("-" * 50)

    report_agents = [
        BasicAgent(name="report_writer", system_prompt="Write executive report", use_llm='google'),
        BasicAgent(name="data_visualizer", system_prompt="Add charts and visualizations", use_llm='google'),
        BasicAgent(name="executive_editor", system_prompt="Polish for executives", use_llm='google'),
        BasicAgent(name="formatter", system_prompt="Final formatting", use_llm='google')
    ]

    report_crew = AgentCrew(name="ReportGeneration", agents=report_agents)

    report_result = await report_crew.run_sequential(
        initial_query=f"Create report from analysis: {analysis_result['results']['strategic_synthesizer']}",
        pass_full_context=True
    )

    print(f"✓ Phase 3 complete: Final report ready\n")

    print("\n" + "="*70)
    print("HYBRID WORKFLOW COMPLETE")
    print("="*70)
    print(f"\nPhase 1 (Parallel): {data_result['total_execution_time']:.2f}s")
    print(f"Phase 2 (Flow): Multiple stages with auto-parallelization")
    print(f"Phase 3 (Sequential): Pipeline refinement")
    print(f"\nFinal Report (first 400 chars):\n{report_result['final_result'][:400]}...")


# ============================================================================
# Main execution
# ============================================================================

async def main():
    """Run all examples to demonstrate the three execution modes."""

    print("\n" + "="*70)
    print("AgentCrew Execution Modes - Comprehensive Examples")
    print("="*70)

    # Run each example
    try:
        await example_sequential_pipeline()
        await example_parallel_research()
        await example_complex_workflow()
        await example_advanced_workflow()
        # await example_hybrid_approach()

        print("\n" + "="*70)
        print("ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("="*70 + "\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

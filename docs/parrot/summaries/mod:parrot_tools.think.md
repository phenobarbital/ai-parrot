---
type: Wiki Summary
title: parrot_tools.think
id: mod:parrot_tools.think
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ThinkTool - A metacognitive tool for explicit agent reasoning.
relates_to:
- concept: class:parrot_tools.think.DataAnalysisThinkTool
  rel: defines
- concept: class:parrot_tools.think.QueryPlanTool
  rel: defines
- concept: class:parrot_tools.think.RAGRetrievalThinkTool
  rel: defines
- concept: class:parrot_tools.think.ScrapingPlanTool
  rel: defines
- concept: class:parrot_tools.think.ThinkInput
  rel: defines
- concept: class:parrot_tools.think.ThinkTool
  rel: defines
- concept: func:parrot_tools.think.create_think_tool
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.think`

ThinkTool - A metacognitive tool for explicit agent reasoning.

This tool implements the "Thinking as a Tool" pattern, a simplified version
of the ReAct (Reasoning + Acting) paradigm. By converting the agent's internal
reasoning into an explicit, observable action, it forces Chain-of-Thought
reasoning and improves decision-making quality.

Key benefits:
- Forces explicit reasoning before complex actions
- Makes the decision-making process observable and auditable
- Prevents impulsive actions by requiring deliberation
- Improves response quality through structured thinking

Usage:
    from parrot.tools import ThinkTool, ToolManager

    # Basic usage
    think_tool = ThinkTool()

    # With custom context for specific domains
    data_think = ThinkTool(
        extra_context="Focus on data quality, transformations, and analysis strategy."
    )

    # With custom output handler
    def log_thoughts(input_data: ThinkInput) -> str:
        print(f"Agent thinking: {input_data.thoughts}")
        return "Reasoning recorded"

    think_tool = ThinkTool(output_handler=log_thoughts)

    # Register with ToolManager
    tool_manager = ToolManager()
    tool_manager.register_tool(think_tool)

Example agent interaction:
    Agent: think(thoughts="The user wants correlation analysis between sales and
                          temperature. I should first check data types, handle
                          missing values, then compute Pearson correlation...")
    Agent: execute_code("df[['sales', 'temperature']].dropna().corr()")

## Classes

- **`ThinkInput(AbstractToolArgsSchema)`** — Input schema for the ThinkTool.
- **`ThinkTool(AbstractTool)`** — A metacognitive tool that forces explicit reasoning before action.
- **`DataAnalysisThinkTool(ThinkTool)`** — Specialized thinking tool for data analysis tasks.
- **`ScrapingPlanTool(ThinkTool)`** — Specialized thinking tool for web scraping tasks.
- **`QueryPlanTool(ThinkTool)`** — Specialized thinking tool for database query planning.
- **`RAGRetrievalThinkTool(ThinkTool)`** — Specialized thinking tool for RAG retrieval strategy.

## Functions

- `def create_think_tool(domain: Optional[str]=None, name: Optional[str]=None, extra_context: str='', output_handler: Optional[Union[str, Callable[[ThinkInput], str]]]=None) -> ThinkTool` — Factory function to create domain-specific ThinkTool instances.

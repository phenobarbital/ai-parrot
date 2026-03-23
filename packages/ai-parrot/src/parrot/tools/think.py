"""
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
"""
from typing import Callable, Dict, Optional, Type, Union
from pydantic import Field
from .abstract import (
    AbstractTool,
    AbstractToolArgsSchema,
    ToolResult,
)


class ThinkInput(AbstractToolArgsSchema):
    """
    Input schema for the ThinkTool.

    The thoughts field captures the agent's reasoning process, including:
    - Problem analysis and clarification
    - Assumptions being made
    - Planned approach or strategy
    - Potential issues or edge cases to consider

    Note: A 'next_step' field was intentionally omitted as it tends to
    cause hallucinations and rigid behavior in practice.
    """
    thoughts: str = Field(
        ...,
        description=(
            "Describe your reasoning process: analyze the problem, "
            "clarify assumptions, identify potential issues, and "
            "outline your planned approach before taking action."
        ),
        min_length=10,  # Encourage substantive thinking
    )


class ThinkTool(AbstractTool):
    """
    A metacognitive tool that forces explicit reasoning before action.

    This tool implements the "Thinking as a Tool" pattern, which converts
    the agent's internal reasoning into an observable, recorded action.
    The primary value is in the process (forcing deliberation) rather
    than the output.

    Use cases:
    - Complex multi-step tasks requiring careful planning
    - Debugging agent decision-making processes
    - Improving response quality through deliberate thinking
    - Auditing and understanding agent reasoning

    When NOT to use:
    - Simple, straightforward tasks where it adds unnecessary latency
    - When using LLM's native extended_thinking (would be redundant)
    - Highly structured workflows with predetermined reasoning

    Attributes:
        name: Tool identifier ("think" by default)
        description: Tool description for the LLM
        args_schema: Pydantic model for input validation (ThinkInput)

    Example:
        >>> think_tool = ThinkTool()
        >>> result = await think_tool.execute(
        ...     thoughts="Analyzing the CSV structure: I see columns for date, "
        ...              "amount, and category. I should parse dates first, "
        ...              "then aggregate by category for the monthly report."
        ... )
        >>> print(result.status)
        'success'
    """

    name: str = "think"
    description: str = (
        "Use when you need to reason through a problem, clarify your "
        "assumptions, or plan your approach before acting. Think before "
        "complex operations, multi-step tasks, or when facing ambiguity."
    )
    args_schema: Type[AbstractToolArgsSchema] = ThinkInput

    def __init__(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        extra_context: str = "",
        output_handler: Optional[Union[str, Callable[[ThinkInput], str]]] = None,
        **kwargs
    ):
        """
        Initialize the ThinkTool.

        Args:
            name: Custom tool name (default: "think")
            description: Custom description (appends extra_context if provided)
            extra_context: Additional instructions appended to the description.
                          Useful for domain-specific thinking guidance.
            output_handler: Either a static string response or a callable that
                           receives ThinkInput and returns a string. The callable
                           can be used for logging, metrics, or custom processing.
            **kwargs: Additional arguments passed to AbstractTool

        Example:
            # Domain-specific thinking tool
            scraping_think = ThinkTool(
                name="plan_scraping",
                extra_context="Consider page structure, anti-bot measures, "
                             "and optimal selectors before scraping."
            )

            # With custom output processing
            def track_reasoning(input_data):
                metrics.record_thought(input_data.thoughts)
                return "Reasoning tracked"

            tracked_think = ThinkTool(output_handler=track_reasoning)
        """
        # Handle name override
        if name:
            self.name = name

        # Handle description with extra context
        if description:
            self.description = description
        if extra_context:
            self.description = f"{self.description} {extra_context}"

        # Set output handler (default: simple acknowledgment)
        self._output_handler: Union[str, Callable[[ThinkInput], str]] = (
            output_handler if output_handler is not None else "OK"
        )

        super().__init__(**kwargs)

    async def _execute(
        self,
        thoughts: str,
        **kwargs
    ) -> ToolResult:
        """
        Execute the think operation.

        The actual value of this tool is in the process of thinking,
        not in the execution result. The agent's thoughts are recorded
        in the tool call history, making the reasoning process observable.

        Args:
            thoughts: The agent's reasoning/thinking content
            **kwargs: Additional arguments (ignored)

        Returns:
            ToolResult with status and acknowledgment message
        """
        # Create input model for potential handler use
        input_data = ThinkInput(thoughts=thoughts)

        # Generate output based on handler type
        if callable(self._output_handler):
            try:
                output = self._output_handler(input_data)
            except Exception as e:
                self.logger.warning(f"Output handler failed: {e}")
                output = "OK"
        else:
            output = self._output_handler

        return ToolResult(
            status="success",
            result=output,
            metadata={
                "thought_length": len(thoughts),
                "tool_type": "metacognitive",
            }
        )


# =============================================================================
# Specialized Variants
# =============================================================================

class DataAnalysisThinkTool(ThinkTool):
    """
    Specialized thinking tool for data analysis tasks.

    Guides the agent to consider data quality, transformations,
    and analysis strategy before executing data operations.

    Example:
        >>> tool = DataAnalysisThinkTool()
        >>> result = await tool.execute(
        ...     thoughts="Dataset has 10k rows with 3 date columns. "
        ...              "I'll parse dates, check for nulls in the amount "
        ...              "column, then create a pivot table by month."
        ... )
    """

    name: str = "think_data_analysis"
    description: str = (
        "Use before data analysis operations. Reason about data quality, "
        "required transformations, potential issues (nulls, types, outliers), "
        "and your analysis strategy."
    )


class ScrapingPlanTool(ThinkTool):
    """
    Specialized thinking tool for web scraping tasks.

    Guides the agent to plan scraping strategy considering page structure,
    anti-bot measures, and selector reliability.

    Example:
        >>> tool = ScrapingPlanTool()
        >>> result = await tool.execute(
        ...     thoughts="Target page uses infinite scroll with lazy loading. "
        ...              "I'll use incremental scrolling with dynamic waits. "
        ...              "Product cards have consistent class 'product-item'."
        ... )
    """

    name: str = "plan_scraping"
    description: str = (
        "Use before web scraping operations. Plan your approach considering "
        "page structure (static/dynamic/SPA), anti-bot measures, pagination "
        "type, and selector strategy. Identify reliable selectors and "
        "potential failure points."
    )


class QueryPlanTool(ThinkTool):
    """
    Specialized thinking tool for database query planning.

    Guides the agent to consider query optimization, table relationships,
    and potential performance issues.

    Example:
        >>> tool = QueryPlanTool()
        >>> result = await tool.execute(
        ...     thoughts="Need to join orders with customers and products. "
        ...              "Orders table is large (~5M rows), should filter by "
        ...              "date range first. Index exists on order_date."
        ... )
    """

    name: str = "plan_query"
    description: str = (
        "Use before complex database queries. Consider table relationships, "
        "query optimization (indexes, filters), potential performance issues, "
        "and the best approach to retrieve the required data."
    )


class RAGRetrievalThinkTool(ThinkTool):
    """
    Specialized thinking tool for RAG retrieval strategy.

    Guides the agent to plan retrieval approach based on query type,
    expected document relevance, and retrieval method selection.

    Particularly useful for Adaptive Agentic RAG implementations.

    Example:
        >>> tool = RAGRetrievalThinkTool()
        >>> result = await tool.execute(
        ...     thoughts="User query is factual and specific. Dense retrieval "
        ...              "should work well. Will use top-5 chunks with "
        ...              "reranking. No need for hybrid search here."
        ... )
    """

    name: str = "plan_retrieval"
    description: str = (
        "Use before RAG retrieval operations. Analyze query type (factual, "
        "exploratory, comparative), decide on retrieval strategy (dense, "
        "sparse, hybrid), determine chunk count, and consider if reranking "
        "or query expansion is needed."
    )


# =============================================================================
# Factory Function
# =============================================================================

def create_think_tool(
    domain: Optional[str] = None,
    name: Optional[str] = None,
    extra_context: str = "",
    output_handler: Optional[Union[str, Callable[[ThinkInput], str]]] = None,
) -> ThinkTool:
    """
    Factory function to create domain-specific ThinkTool instances.

    Args:
        domain: Predefined domain ('data', 'scraping', 'query', 'rag')
                or None for generic ThinkTool
        name: Custom tool name (overrides domain default)
        extra_context: Additional context appended to description
        output_handler: Custom output handler

    Returns:
        Configured ThinkTool instance

    Example:
        # Using predefined domain
        data_tool = create_think_tool(domain='data')

        # Custom configuration
        custom_tool = create_think_tool(
            domain='scraping',
            name='plan_ecommerce_scrape',
            extra_context='Consider rate limiting for this e-commerce site.'
        )
    """
    domain_map: Dict[str, Type[ThinkTool]] = {
        'data': DataAnalysisThinkTool,
        'data_analysis': DataAnalysisThinkTool,
        'scraping': ScrapingPlanTool,
        'web_scraping': ScrapingPlanTool,
        'query': QueryPlanTool,
        'database': QueryPlanTool,
        'rag': RAGRetrievalThinkTool,
        'retrieval': RAGRetrievalThinkTool,
    }

    if domain and domain.lower() in domain_map:
        tool_class = domain_map[domain.lower()]
        tool = tool_class(
            name=name,
            extra_context=extra_context,
            output_handler=output_handler,
        )
    else:
        tool = ThinkTool(
            name=name,
            extra_context=extra_context,
            output_handler=output_handler,
        )

    return tool

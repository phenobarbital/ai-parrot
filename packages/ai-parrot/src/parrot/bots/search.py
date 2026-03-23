"""WebSearchAgent implementation for the ai-parrot framework."""
from string import Template
from typing import Optional, List, Any
from ..models.responses import AIMessage
# Import default tools
from ..tools.googlesearch import GoogleSearchTool
from ..tools.googlesitesearch import GoogleSiteSearchTool
from ..tools.ddgsearch import DdgSearchTool
from ..tools.bingsearch import BingSearchTool
from ..tools.serpapi import SerpApiSearchTool
from .agent import BasicAgent
from .middleware import PromptPipeline, PromptMiddleware

DEFAULT_CONTRASTIVE_PROMPT = """Based on following query: $query
Below are search results about its COMPETITORS. Analyze ONLY the competitors:

$search_results

Structure your response as:
**Market Category**: [category]
**Competitors Found**:
For each competitor:
- Name and key specs
- Price positioning
- Strengths vs the reference product
- Weaknesses

**Recommendation**: Which competitor stands out and why."""

DEFAULT_SYNTHESIZE_PROMPT = """Based on the following query: $query
Analyze and synthesize the following search results into a comprehensive summary:

$search_results

Provide:
- **Key Findings**: Main insights from the results
- **Analysis**: Critical evaluation of the information
- **Summary**: Concise synthesis of all findings
- **Sources Quality**: Assessment of information reliability"""


DEFAULT_COMPETITOR_TRANSFORM_PROMPT = """You are a query transformation engine.
Given a user query about a product or company, transform it into a competitor
research query. NEVER return a query about the original product itself.
Extract the product category, then generate a single search query focused
on direct COMPETITORS and ALTERNATIVES.

Respond ONLY with the transformed search query string. Nothing else."""


class WebSearchAgent(BasicAgent):
    """An agent specialized in performing web searches.

    By default, it is equipped with several search tools:
    - GoogleSearchTool
    - GoogleSiteSearchTool
    - DdgSearchTool
    - BingSearchTool
    - SerpApiSearchTool

    If `use_builtin_search` is True, it will fallback to using
    Gemini's built-in Google Search functionality via `tool_type='builtin_tools'`.

    If `contrastive_search` is True, performs a two-step search:
    first the original query, then a contrastive analysis of
    competitors/alternatives based on the initial results.

    If `synthesize` is True, an additional LLM call (with `use_tools=False`)
    analyzes and synthesizes the search results using a synthesis prompt.
    """

    def __init__(
        self,
        name: str = 'WebSearchAgent',
        agent_id: str = 'web_search_agent',
        use_llm: str = 'google',
        llm: str = 'google:gemini-3-flash',
        tools: Optional[List[Any]] = None,
        use_builtin_search: bool = False,
        contrastive_search: bool = False,
        contrastive_prompt: Optional[str] = None,
        synthesize: bool = False,
        synthesize_prompt: Optional[str] = None,
        competitor_search: bool = False,
        competitor_prompt: Optional[str] = None,
        **kwargs
    ):
        """Initialize the WebSearchAgent."""
        self.use_builtin_search = use_builtin_search
        self.contrastive_search = contrastive_search
        self.contrastive_prompt = contrastive_prompt or DEFAULT_CONTRASTIVE_PROMPT
        self.synthesize = synthesize
        self.synthesize_prompt = synthesize_prompt or DEFAULT_SYNTHESIZE_PROMPT
        self.competitor_search = competitor_search
        self._competitor_prompt = competitor_prompt or DEFAULT_COMPETITOR_TRANSFORM_PROMPT

        # setup competitor search middleware if enabled:
        if self.competitor_search:
            self._setup_competitor_pipeline()
        # Provide a default list of web search tools if none is provided
        if tools is None:
            tools = [
                GoogleSearchTool(),
                GoogleSiteSearchTool(),
                DdgSearchTool(),
                BingSearchTool(),
                SerpApiSearchTool()
            ]

        super().__init__(
            name=name,
            agent_id=agent_id,
            use_llm=use_llm,
            llm=llm,
            tools=tools,
            **kwargs
        )

    def _setup_competitor_pipeline(self):
        if not self._prompt_pipeline:
            self._prompt_pipeline = PromptPipeline()
        self._prompt_pipeline.add(PromptMiddleware(
            name="competitor_transform",
            priority=10,
            transform=self._as_competitor_query
        ))

    async def _as_competitor_query(
        self, query: str, context: dict
    ) -> str:
        """Use LLM without tools to pivot query toward competitors."""
        self.logger.info(f"Transforming query to competitor search: {query}")
        async with self._llm as client:
            response = await client.ask(
                prompt=query,
                system_prompt=self._competitor_prompt,
                use_tools=False,
            )
        transformed = self._extract_text(response).strip()
        self.logger.info(f"Transformed query: {transformed}")
        return transformed

    def _extract_text(self, response: AIMessage) -> str:
        """Extract text content from an AIMessage response."""
        try:
            if hasattr(response, 'to_text'):
                return response.to_text
            if hasattr(response, 'output') and isinstance(response.output, str):
                return response.output
            if hasattr(response, 'response') and response.response:
                return response.response
            return str(response)
        except Exception:
            return str(response)

    async def _do_search(self, question: str, **kwargs) -> AIMessage:
        """Execute a search using standard tools or builtin fallback."""
        if self.use_builtin_search:
            self.logger.info("Using built-in search tool due to use_builtin_search=True")
            kwargs['tool_type'] = 'builtin_tools'
            return await super().ask(question, **kwargs)

        try:
            self.logger.info("Asking with custom search tools...")
            return await super().ask(question, **kwargs)
        except Exception as e:
            self.logger.warning(
                f"Search tools failed with error: {e}. Falling back to Gemini built-in search."
            )
            kwargs['tool_type'] = 'builtin_tools'
            return await super().ask(question, **kwargs)

    async def _do_contrastive(
        self, question: str, search_results: str, **kwargs
    ) -> AIMessage:
        """Execute the contrastive analysis step.

        Uses the contrastive prompt template with the original query
        and initial search results to analyze competitors/alternatives.
        """
        tmpl = Template(self.contrastive_prompt)
        contrastive_query = tmpl.safe_substitute(
            query=question,
            search_results=search_results
        )
        self.logger.info("Running contrastive analysis step...")
        return await self._do_search(contrastive_query, **kwargs)

    async def _do_synthesize(
        self, question: str, search_results: str, **kwargs
    ) -> AIMessage:
        """Execute the synthesis step.

        Calls the LLM with `use_tools=False` to produce a structured
        synthesis of the search results.
        """
        tmpl = Template(self.synthesize_prompt)
        synthesis_query = tmpl.safe_substitute(
            query=question,
            search_results=search_results
        )
        self.logger.info("Running synthesis step (use_tools=False)...")
        kwargs['use_tools'] = False
        return await super().ask(synthesis_query, **kwargs)

    async def ask(self, question: str, **kwargs) -> AIMessage:
        """Override ask to support contrastive search and synthesis.

        Flow:
        1. If contrastive_search is False: normal search via _do_search.
           If True: two-step search (initial + contrastive analysis).
        2. If synthesize is True: additional LLM call (no tools) to
           synthesize the results.
        """
        if self.contrastive_search:
            # Step 1: Initial search
            initial_response = await self._do_search(question, **kwargs)
            initial_text = self._extract_text(initial_response)

            # Step 2: Contrastive analysis
            response = await self._do_contrastive(
                question, initial_text, **kwargs
            )

            # Store the initial results in metadata for traceability
            response.metadata['initial_search_results'] = initial_text
        else:
            response = await self._do_search(question, **kwargs)

        if self.synthesize:
            search_text = self._extract_text(response)
            # Store pre-synthesis results in metadata
            response_before = response
            response = await self._do_synthesize(
                question, search_text, **kwargs
            )
            response.metadata['pre_synthesis_results'] = self._extract_text(
                response_before
            )

        return response

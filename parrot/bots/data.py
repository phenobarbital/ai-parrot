"""
PandasAgent - Langchain-free implementation for AI-Parrot
A specialized agent for data analysis using pandas DataFrames.
"""
from pathlib import Path
from typing import Any, List, Dict, Union, Optional
from datetime import datetime, timezone, timedelta
import uuid
from string import Template
import redis.asyncio as aioredis
import pandas as pd
import numpy as np
from aiohttp import web
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from navconfig import BASE_DIR
from navconfig.logging import logging
from querysource.queries.qs import QS
from querysource.queries.multi import MultiQS
from ..tools import AbstractTool
from ..tools.pythonpandas import PythonPandasTool
from .agent import BasicAgent
from ..models.responses import AIMessage, AgentResponse
from ..conf import REDIS_HISTORY_URL, STATIC_DIR


def brace_escape(text: str) -> str:
    """Escape braces for string template formatting."""
    return text.replace('{', '{{').replace('}', '}}')


class PandasAgent(BasicAgent):
    """
    A specialized agent for data analysis using pandas DataFrames.

    Features:
    - Multi-dataframe support
    - Redis caching for data persistence
    - Automatic EDA (Exploratory Data Analysis)
    - DataFrame metadata generation
    - Query source integration
    - File loading (CSV, Excel)
    """

    PANDAS_SYSTEM_PROMPT = """You are a data analysis expert specializing in pandas DataFrames.

**Your Role:**
$description

**Available DataFrames:**
$df_info

**Your Capabilities:**
$capabilities

**Guidelines:**
1. Always reference DataFrames using their standardized keys (df1, df2, etc.)
2. Use the python_repl_pandas tool for all data operations
3. Create visualizations when helpful for understanding
4. Explain your analysis clearly
5. Store important results in execution_results dictionary
6. Save plots using save_current_plot() for sharing

**Today's Date:** $today_date

$backstory
"""

    def __init__(
        self,
        name: str = 'Pandas Agent',
        llm: Optional[str] = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        df: Union[list[pd.DataFrame], Dict[str, pd.DataFrame], pd.DataFrame] = None,
        query: Union[List[str], dict] = None,
        capabilities: str = None,
        generate_eda: bool = True,
        cache_expiration: int = 24,
        **kwargs
    ):
        """
        Initialize PandasAgent.

        Args:
            name: Agent name
            llm: LLM client name ('google', 'openai', 'claude')
            tools: Additional tools beyond default
            system_prompt: Custom system prompt
            df: DataFrame(s) to analyze
            query: QuerySource queries to execute
            capabilities: Agent capabilities description
            generate_eda: Generate exploratory data analysis
            cache_expiration: Cache expiration in hours
            **kwargs: Additional configuration
        """
        self._queries = query
        self._capabilities = capabilities
        self._generate_eda = generate_eda
        self._cache_expiration = cache_expiration

        # Initialize dataframes
        self.dataframes = self._define_dataframe(df) if df is not None else {}
        self.df_metadata = {}

        # Initialize base agent (AbstractBot will set chatbot_id)
        super().__init__(
            name=name,
            llm=llm,
            system_prompt=system_prompt,
            tools=tools,
            **kwargs
        )

        self.description = "A specialized agent for data analysis using pandas DataFrames"

    def _get_default_tools(self, tools: list) -> List[AbstractTool]:
        """Override to add PythonPandasTool with dataframes."""
        if not tools:
            tools = []

        report_dir = STATIC_DIR.joinpath(self.agent_id, 'documents')
        report_dir.mkdir(parents=True, exist_ok=True)

        # Build a description that includes DataFrame info
        df_summary = ", ".join([
            f"{df_key}: {df.shape[0]} rows × {df.shape[1]} cols"
            for df_key, df in self.dataframes.items()
        ]) if self.dataframes else "No DataFrames"

        tool_description = (
            f"Execute Python code with pandas DataFrames. "
            f"Available data: {df_summary}. "
            f"Use df1, df2, etc. to access DataFrames."
        )

        pandas_tool = PythonPandasTool(
            dataframes=self.dataframes,
            generate_guide=True,
            include_summary_stats=False,  # Disable to reduce token usage
            include_sample_data=False,     # Disable to reduce token usage
            sample_rows=2,
            report_dir=report_dir
        )

        # Override the tool description to include DataFrame info
        pandas_tool.description = tool_description

        tools.append(pandas_tool)

        return tools

    def _define_dataframe(
        self,
        df: Union[list[pd.DataFrame], Dict[str, pd.DataFrame], pd.DataFrame]
    ) -> Dict[str, pd.DataFrame]:
        """
        Normalize dataframe input to dictionary format.

        Args:
            df: DataFrame(s) in various formats

        Returns:
            Dictionary mapping names to DataFrames
        """
        _df = {}

        if isinstance(df, pd.DataFrame):
            _df['df1'] = df
        elif isinstance(df, pd.Series):
            _df['df1'] = pd.DataFrame(df)
        elif isinstance(df, list):
            for i, dataframe in enumerate(df):
                _df[f"df{i + 1}"] = dataframe.copy()
        elif isinstance(df, dict):
            _df = df
        else:
            raise ValueError(f"Expected pandas DataFrame, got {type(df)}")

        return _df

    def _generate_eda_summary(self, df: pd.DataFrame, df_key: str) -> str:
        """
        Generate exploratory data analysis summary for a DataFrame.

        Args:
            df: DataFrame to analyze
            df_key: DataFrame identifier

        Returns:
            EDA summary as markdown string
        """
        summary_parts = []

        # Basic statistics
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns

        summary_parts.append(f"**{df_key} EDA Summary:**")
        summary_parts.append(f"- Total rows: {len(df):,}")
        summary_parts.append(f"- Total columns: {len(df.columns)}")
        summary_parts.append(f"- Numeric columns: {len(numeric_cols)}")
        summary_parts.append(f"- Categorical columns: {len(categorical_cols)}")

        # Missing data
        missing = df.isnull().sum()
        if missing.sum() > 0:
            summary_parts.append(f"- Missing values: {missing.sum():,} ({missing.sum() / df.size * 100:.1f}%)")

        # Memory usage
        memory_mb = df.memory_usage(deep=True).sum() / 1024 / 1024
        summary_parts.append(f"- Memory usage: {memory_mb:.2f} MB")

        return "\n".join(summary_parts)

    def _generate_column_guide(self, df_key: str, df: pd.DataFrame) -> str:
        """
        Generate a concise guide for DataFrame columns.

        Args:
            df_key: DataFrame identifier
            df: DataFrame to document

        Returns:
            Column guide as markdown table
        """
        guide = f"\n**{df_key} Columns:**\n"
        guide += "| Column | Type | Sample | Nulls |\n"
        guide += "|--------|------|--------|-------|\n"

        for col in df.columns[:20]:  # Limit to first 20 columns
            dtype = str(df[col].dtype)
            try:
                sample = str(df[col].dropna().iloc[0])[:30] if len(df[col].dropna()) > 0 else "N/A"
            except:
                sample = "N/A"
            nulls = df[col].isnull().sum()
            guide += f"| {col} | {dtype} | {sample} | {nulls} |\n"

        if len(df.columns) > 20:
            guide += f"\n*... and {len(df.columns) - 20} more columns*\n"

        return guide

    def _build_dataframe_info(self) -> str:
        """
        Build comprehensive DataFrame information for system prompt.

        Returns:
            Formatted DataFrame information string
        """
        if not self.dataframes:
            return "No DataFrames loaded."

        df_info_parts = [f"**Total DataFrames:** {len(self.dataframes)}\n"]

        for i, (df_name, df) in enumerate(self.dataframes.items()):
            df_key = f"df{i + 1}"

            # Basic info
            df_info_parts.append(f"### {df_key} ('{df_name}')")
            df_info_parts.append(f"Shape: {df.shape[0]:,} rows × {df.shape[1]} columns\n")

            # EDA summary if enabled
            if self._generate_eda:
                df_info_parts.append(self._generate_eda_summary(df, df_key))
                df_info_parts.append("")

            # Column guide
            df_info_parts.append(self._generate_column_guide(df_key, df))

            # Sample data (first 3 rows)
            try:
                sample = brace_escape(df.head(3).to_markdown())
                df_info_parts.append(f"\n**Sample Data:**\n```\n{sample}\n```\n")
            except:
                df_info_parts.append("*Sample data unavailable*\n")

        return "\n".join(df_info_parts)

    def _define_prompt(self, prompt: str = None, **kwargs):
        """
        Define the system prompt with DataFrame context.

        This method is called by BasicAgent.configure() to build the system prompt.

        Args:
            prompt: Optional base prompt to extend
            **kwargs: Additional template variables
        """
        # Build DataFrame information
        df_info = self._build_dataframe_info()

        # Default capabilities if not provided
        capabilities = self._capabilities or """
- Perform complex data analysis and transformations
- Create visualizations (matplotlib, seaborn, plotly)
- Generate statistical summaries
- Export results to various formats
- Execute pandas operations efficiently
"""

        # Get backstory
        backstory = self.backstory or self.default_backstory()

        # Build prompt using string.Template (not f-strings for JSON compatibility)
        tmpl = Template(self.PANDAS_SYSTEM_PROMPT)
        self.system_prompt = tmpl.safe_substitute(
            description=self.description,
            df_info=df_info,
            capabilities=capabilities.strip(),
            today_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            backstory=backstory,
            **kwargs
        )

    async def configure(
        self,
        app: web.Application = None
    ) -> None:
        """
        Configure the PandasAgent.

        Args:
            df: Optional DataFrame(s) to load
            app: Optional aiohttp Application
        """
        # Load from queries if specified
        if self._queries and not self.dataframes:
            self.dataframes = await self.gen_data(
                query=self._queries,
                agent_name=self.chatbot_id,
                cache_expiration=self._cache_expiration
            )

        # Call parent configure (handles LLM, tools, memory, etc.)
        await super().configure(app=app)
        # Cache data after configuration
        if self.dataframes:
            await self._cache_data(
                self.chatbot_id,
                self.dataframes,
                cache_expiration=self._cache_expiration
            )

        self.logger.info(
            f"PandasAgent '{self.name}' configured with {len(self.dataframes)} DataFrame(s)"
        )

    async def invoke(
        self,
        question: str,
        **kwargs
    ) -> AgentResponse:
        """
        Ask the agent a question about the data.

        Args:
            question: Question to ask
            **kwargs: Additional parameters

        Returns:
            AgentResponse with answer and metadata
        """
        # Use the conversation method from BasicAgent
        response = await self.conversation(
            question=question,
            use_conversation_history=kwargs.get('use_conversation_history', True),
            **kwargs
        )
        if isinstance(response, AgentResponse):
            return response

        # Convert to AgentResponse if needed
        if isinstance(response, AIMessage):
            return AgentResponse(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                status='success',
                response=response,  # original AIMessage
                question=question,
                data=response.content,
                output=response.output,
                metadata=response.metadata,
                turn_id=response.turn_id
            )

        return response

    def default_backstory(self) -> str:
        """Return default backstory for the agent."""
        return (
            "You are a helpful data analysis assistant. "
            "You provide accurate insights and clear visualizations "
            "to help users understand their data."
        )

    # ===== Data Loading Methods =====

    @classmethod
    async def call_qs(cls, queries: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Execute QuerySource queries.

        Args:
            queries: List of query slugs

        Returns:
            Dictionary of DataFrames
        """
        dfs = {}
        for query in queries:
            if not isinstance(query, str):
                raise ValueError(f"Query {query} is not a string")

            try:
                qy = QS(slug=query)
                df, error = await qy.query(output_format='pandas')

                if error:
                    raise ValueError(f"Query {query} failed: {error}")

                if not isinstance(df, pd.DataFrame):
                    raise ValueError(f"Query {query} did not return a DataFrame")

                dfs[query] = df

            except Exception as e:
                raise ValueError(f"Error executing query {query}: {e}")

        return dfs

    @classmethod
    async def call_multiquery(cls, query: dict) -> Dict[str, pd.DataFrame]:
        """
        Execute MultiQuery queries.

        Args:
            query: Query configuration dict

        Returns:
            Dictionary of DataFrames
        """
        _queries = query.pop('queries', {})
        _files = query.pop('files', {})

        if not _queries and not _files:
            raise ValueError("Queries or files are required")

        try:
            qs = MultiQS(
                slug=[],
                queries=_queries,
                files=_files,
                query=query,
                conditions={},
                return_all=True
            )
            result, _ = await qs.execute()

        except Exception as e:
            raise ValueError(f"Error executing MultiQuery: {e}")

        if not isinstance(result, dict):
            raise ValueError("MultiQuery did not return a dictionary")

        return result

    @classmethod
    async def load_from_files(
        cls,
        files: Union[str, Path, List[Union[str, Path]]],
        **kwargs
    ) -> Dict[str, pd.DataFrame]:
        """
        Load DataFrames from CSV or Excel files.

        Args:
            files: File path(s) to load
            **kwargs: Additional pandas read options

        Returns:
            Dictionary of DataFrames
        """
        if isinstance(files, (str, Path)):
            files = [files]

        dfs = {}
        for file_path in files:
            path = Path(file_path)

            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            # Determine file type and load
            if path.suffix.lower() in ['.csv', '.txt']:
                df = pd.read_csv(path, **kwargs)
                dfs[path.stem] = df

            elif path.suffix.lower() in ['.xlsx', '.xls']:
                # Load all sheets
                excel_file = pd.ExcelFile(path)
                for sheet_name in excel_file.sheet_names:
                    df = pd.read_excel(path, sheet_name=sheet_name, **kwargs)
                    dfs[f"{path.stem}_{sheet_name}"] = df

            else:
                raise ValueError(f"Unsupported file type: {path.suffix}")

        return dfs

    @classmethod
    async def gen_data(
        cls,
        query: Union[list, dict],
        agent_name: str,
        refresh: bool = False,
        cache_expiration: int = 48,
        no_cache: bool = False
    ) -> Dict[str, pd.DataFrame]:
        """
        Generate DataFrames with Redis caching support.

        Args:
            query: Query configuration
            agent_name: Agent identifier for caching
            refresh: Force data regeneration
            cache_expiration: Cache duration in hours
            no_cache: Disable caching

        Returns:
            Dictionary of DataFrames
        """
        # Try cache first
        if not refresh and not no_cache:
            cached_dfs = await cls._get_cached_data(agent_name)
            if cached_dfs:
                logging.info(f"Using cached data for agent {agent_name}")
                return cached_dfs

        # Generate data
        dfs = await cls._execute_query(query)

        # Cache if enabled
        if not no_cache:
            await cls._cache_data(agent_name, dfs, cache_expiration)

        return dfs

    @classmethod
    async def _execute_query(cls, query: Union[list, dict]) -> Dict[str, pd.DataFrame]:
        """Execute query and return DataFrames."""
        if isinstance(query, dict):
            return await cls.call_multiquery(query)
        elif isinstance(query, (str, list)):
            if isinstance(query, str):
                query = [query]
            return await cls.call_qs(query)
        else:
            raise ValueError(f"Expected list or dict, got {type(query)}")

    # ===== Redis Caching Methods =====

    @classmethod
    async def _get_redis_connection(cls):
        """Get Redis connection."""
        return await aioredis.Redis.from_url(
            REDIS_HISTORY_URL,
            decode_responses=True
        )

    @classmethod
    async def _get_cached_data(cls, agent_name: str) -> Optional[Dict[str, pd.DataFrame]]:
        """
        Retrieve cached DataFrames from Redis.

        Args:
            agent_name: Agent identifier

        Returns:
            Dictionary of DataFrames or None
        """
        try:
            redis_conn = await cls._get_redis_connection()
            key = f"agent_{agent_name}"

            if not await redis_conn.exists(key):
                await redis_conn.close()
                return None

            # Get all dataframe keys
            df_keys = await redis_conn.hkeys(key)
            if not df_keys:
                await redis_conn.close()
                return None

            # Retrieve DataFrames
            dataframes = {}
            for df_key in df_keys:
                df_json = await redis_conn.hget(key, df_key)
                if df_json:
                    df_data = json_decoder(df_json)
                    dataframes[df_key] = pd.DataFrame.from_records(df_data)

            await redis_conn.close()
            return dataframes if dataframes else None

        except Exception as e:
            logging.error(f"Error retrieving cache: {e}")
            return None

    @classmethod
    async def _cache_data(
        cls,
        agent_name: str,
        dataframes: Dict[str, pd.DataFrame],
        cache_expiration: int
    ) -> None:
        """
        Cache DataFrames in Redis.

        Args:
            agent_name: Agent identifier
            dataframes: DataFrames to cache
            cache_expiration: Expiration time in hours
        """
        try:
            if not dataframes:
                return

            redis_conn = await cls._get_redis_connection()
            key = f"agent_{agent_name}"

            # Clear existing cache
            await redis_conn.delete(key)

            # Store DataFrames
            for df_key, df in dataframes.items():
                df_json = json_encoder(df.to_dict(orient='records'))
                await redis_conn.hset(key, df_key, df_json)

            # Set expiration
            expiration = timedelta(hours=cache_expiration)
            await redis_conn.expire(key, int(expiration.total_seconds()))

            logging.info(
                f"Cached data for agent {agent_name} "
                f"(expires in {cache_expiration}h)"
            )

            await redis_conn.close()

        except Exception as e:
            logging.error(f"Error caching data: {e}")

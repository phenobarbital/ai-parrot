"""
PandasAgent.
A specialized agent for data analysis using pandas DataFrames.
"""
from __future__ import annotations
from typing import Any, List, Dict, Tuple, Union, Optional
import ast
import asyncio
import inspect
import json
import re
import uuid
import contextlib
from pathlib import Path
from datetime import datetime, timezone
from string import Template
from pydantic import BaseModel, Field, ConfigDict, field_validator
import pandas as pd
from aiohttp import web
from datamodel.parsers.json import json_decoder  # pylint: disable=E0611 # noqa
from navconfig.logging import logging
from ..tools import AbstractTool
from ..tools.dataset_manager import DatasetManager
from ..tools.pythonpandas import PythonPandasTool
from ..tools.json_tool import ToJsonTool
from .agent import BasicAgent
from .mixins.intent_router import IntentRouterMixin
from ..registry.capabilities.models import IntentRouterConfig
from ..models.responses import AIMessage, AgentResponse
from ..models.outputs import OutputMode, StructuredOutputConfig, StructuredChartConfig
from ..memory.abstract import ConversationTurn
from ..conf import STATIC_DIR
from ..bots.prompts import OUTPUT_SYSTEM_PROMPT
from ..bots.prompts.builder import PromptBuilder
from ..bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from ..bots.prompts.domain_layers import DATAFRAME_CONTEXT_LAYER, STRICT_GROUNDING_LAYER
from parrot_tools.whatif import WhatIfTool, WHATIF_SYSTEM_PROMPT
from parrot_tools.prophetforecast import ProphetForecastTool

# FEAT-197: InfographicRenderResult is imported lazily inside the method
# to avoid circular imports at module load time.
_InfographicRenderResult: Optional[type] = None


def _get_infographic_result_class() -> Optional[type]:
    """Lazy import of InfographicRenderResult (avoids circular deps).

    Does NOT cache the class to avoid stale class-identity issues in test
    environments where sys.modules may be patched between test files.
    """
    try:
        from ..tools.infographic_toolkit import InfographicRenderResult as _cls
        return _cls
    except ImportError:
        return None


Scalar = Union[str, int, float, bool, None]

try:
    logger = logging.getLogger(__name__)
except Exception:
    logger = logging


class PandasTable(BaseModel):
    """Tabular data structure for PandasAgent responses."""
    columns: List[str] = Field(
        description="Column names, in order"
    )
    rows: List[List[Scalar]] = Field(
        description=(
            "Rows as lists of scalar values, aligned with `columns`. "
            "CRITICAL: All numeric values MUST be raw numbers without any formatting. "
            "Do NOT include currency symbols ($, €, £), percent signs (%), "
            "thousands separators (commas), or any other formatting characters. "
            "Correct: [764539.74, 85.3] | Wrong: ['$764,539.74', '85.3%']"
        )
    )

    @field_validator('rows')
    @classmethod
    def validate_rows_alignment(cls, v, info):
        """Ensure rows align with columns."""
        if 'columns' in info.data:
            num_cols = len(info.data['columns'])
            if num_cols == 0:
                return v
            fixed_rows = []
            mismatch_count = 0
            for i, row in enumerate(v):
                # Defensive: ensure row is a list
                if not isinstance(row, list):
                    row = [row]
                if len(row) != num_cols:
                    mismatch_count += 1
                    if len(row) < num_cols:
                        row = row + [None] * (num_cols - len(row))
                    else:
                        row = row[:num_cols]
                fixed_rows.append(row)
            if mismatch_count:
                logger.warning(
                    "PandasTable rows misaligned with columns: %d row(s) adjusted to %d columns.",
                    mismatch_count,
                    num_cols
                )
            return fixed_rows
        return v


class DatasetResult(BaseModel):
    """A single named dataset in a multi-dataset response.

    Used when a query involves multiple datasources and ``PandasAgentResponse``
    needs to return more than one result table.
    """

    name: str = Field(description="Dataset name or alias")
    variable: str = Field(description="Python variable name holding this DataFrame")
    data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Records (list of row dicts)",
    )
    shape: Tuple[int, int] = Field(description="(rows, columns)")
    columns: List[str] = Field(default_factory=list, description="Column names")


class SummaryStat(BaseModel):
    """Single summary statistic for a DataFrame column."""
    metric: str = Field(
        description="Name of the metric, e.g. 'mean', 'max', 'min', 'std'"
    )
    value: float = Field(
        description="Numeric value of this metric"
    )

class PandasMetadata(BaseModel):
    """Metadata information for PandasAgent responses."""
    model_config = ConfigDict(
        extra='allow',
    )
    shape: Optional[List[int]] = Field(
        default=None,
        description="(rows, columns) of the DataFrame"
    )
    columns: Optional[List[str]] = Field(
        default=None,
        description="List of DataFrame column names"
    )
    summary_stats: Optional[List[SummaryStat]] = Field(
        default=None,
        description=(
            "Summary statistics as a list of metric/value pairs. "
            "Example: [{'metric': 'mean', 'value': 12.3}, ...]"
        )
    )


class PandasAgentResponse(BaseModel):
    """Structured response for PandasAgent operations."""
    model_config = ConfigDict(
        extra='allow',
        json_schema_extra={
            "example": {
                "explanation": (
                    "Analysis of sales data shows 3 products exceeding "
                    "the $100 threshold. Product C leads with $150 in sales."
                    " Product A and D also perform well."
                ),
                "data": {
                    "columns": ["store_id", "revenue"],
                    "rows": [
                        ["TCTX", 801467.93],
                        ["OMNE", 587654.26]
                    ]
                },
                "metadata": {
                    "shape": [2, 2],
                    "columns": ["id", "value"],
                    "summary_stats": [
                        {"metric": "mean", "value": 550000},
                        {"metric": "max", "value": 1000000},
                        {"metric": "min", "value": 100000}
                    ]
                },
                "data_variable": None,
                "data_variables": None,
            }
        },
    )
    explanation: str = Field(
        description=(
            "Clear, text-based explanation of the analysis performed. "
            "Include insights, findings, and interpretation of the data."
            "If data is tabular, also generate a markdown table representation. "
        )
    )
    data: Optional[PandasTable] = Field(
        default=None,
        description=(
            "The resulting DataFrame in split format. "
            "Use this format: {'columns': [...], 'rows': [[...], [...], ...]}.\n"
            "Set to null if the response doesn't produce tabular data.\n"
            "CRITICAL: All numeric values in rows MUST be raw numbers. "
            "NEVER include currency symbols ($, €, £), percent signs (%), "
            "thousands separators (commas), or any other formatting. "
            "Return 764539.74 NOT '$764,539.74'. Return 85.3 NOT '85.3%'."
        )
    )
    data_variable: Optional[str] = Field(
        default=None,
        description="The variable name holding the result DataFrame (e.g. 'result_df'). Use this for large datasets instead of 'data'."
    )
    data_variables: Optional[List[str]] = Field(
        default=None,
        description=(
            "List of variable names holding result DataFrames when the response "
            "involves multiple datasets. Each variable is resolved and included "
            "as a separate entry in the response data. Use this instead of "
            "'data_variable' when 2 or more datasets are involved."
        ),
    )
    code: Optional[Union[str, Dict[str, Any]]] = Field(
        default=None,
        description="The Python code used for analysis OR the Code generated under request (e.g. JSON definition for a Altair/Vega Chart)."
    )

    @field_validator('data', mode='before')
    @classmethod
    def parse_data(cls, v):
        """Handle cases where LLM returns stringified JSON for data."""
        if isinstance(v, str):
            with contextlib.suppress(Exception):
                v = json_decoder(v)
        if isinstance(v, pd.DataFrame):
            return PandasTable(
                columns=[str(c) for c in v.columns.tolist()],
                rows=v.values.tolist()
            )
        return v

    def to_dataframe(self) -> Optional[pd.DataFrame]:
        if not self.data:
            return pd.DataFrame()
        return pd.DataFrame(
            self.data.rows,
            columns=self.data.columns
        )


# ── Pandas-specific prompt layer ────────────────────────────────
PANDAS_INSTRUCTIONS_LAYER = PromptLayer(
    name="pandas_instructions",
    priority=LayerPriority.CUSTOM,
    phase=RenderPhase.CONFIGURE,
    template="""<pandas_instructions>
## Decision Flow (FOLLOW THIS ORDER):

**Step 1 — Check what is already available:**
Look at the dataframe context above. If the dataset you need is listed
under loaded DataFrames, it is ALREADY in memory — go directly to Step 3.

**Step 2 — If unsure or dataset not listed, call `list_datasets`:**
This shows ALL datasets (loaded and unloaded) with their `python_variable`,
`python_alias`, and `loaded` status.
- If `loaded: true` → skip to Step 3, data is ready.
- If `loaded: false` → call `fetch_dataset(name='...')` to load it first.

**Step 3 — Use `python_repl_pandas` to answer the question:**
Write and execute Python code using the exact variable names from Steps 1/2.

**Do NOT call `get_metadata` or `fetch_dataset` for datasets that are already loaded.**

## Available Tools:
1. `list_datasets` — List all datasets with loaded status. Call this FIRST if unsure.
2. `python_repl_pandas` — Execute Python/pandas code for analysis (main tool).
3. `fetch_dataset` — Load an unloaded dataset into memory.
4. `get_metadata` — Get schema/EDA details for unfamiliar datasets.
5. `store_dataframe` — Save a NEW computed DataFrame to the catalog.
6. `get_dataframe` — Get DataFrame info and samples.
7. `database_query` — Query external databases if needed.

## DATASET ACCESS POLICY (STRICT — NO BYPASS):
`list_datasets` is the **authoritative allow-list** of data you may use.
If a dataset is not in `list_datasets` (and not already visible in the
dataframe context above), it does **not exist** for this agent.

- **Refusal protocol**: when the user asks about data that is not in the
  catalog, respond:
  **"That dataset is not available in this agent's catalog."**
  Then stop. Do not attempt to retrieve it through any other means, and
  do not suggest a "similar" dataset unless the user explicitly asks.

- **`python_repl_pandas` MUST NOT be used to load data from outside the
  catalog.** The following patterns are **forbidden** — even if they look
  reasonable, even if the user asks for them, even "just to check":
  • `pd.read_csv` / `read_excel` / `read_json` / `read_parquet` /
    `read_sql` / `read_html` / `read_clipboard` / `read_pickle`
  • `open(...)`, `pathlib.Path(...).read_*`, `glob`, `os.listdir`,
    any filesystem access
  • `requests`, `urllib`, `httpx`, `aiohttp`, any HTTP client
  • `sqlalchemy`, `psycopg`, `pymysql`, any direct DB driver
  • Hardcoded URLs, file paths, or credentials read from environment vars

- The **only** authorized way to bring new data into memory is
  `fetch_dataset(name=...)` for an entry that already appears in
  `list_datasets` (typically with `loaded: false`). `database_query` is
  permitted only when it is in your tool list and the query targets a
  configured database — never as a workaround to fetch arbitrary data.

- If the user insists on data outside the catalog, politely decline and
  suggest they register the dataset with the DatasetManager. Do not
  improvise an alternative source.

## TOOL FAILURE & RETRY POLICY (STRICT):
You have a **limited tool-calling budget**. If a tool returns an error,
an empty result, or otherwise does not give you what you need:

1. **DO NOT** re-invoke the same tool with the **same arguments** — it
   will produce the same outcome and burn the budget.
2. **DO** try ONE alternative on the next turn: different arguments, a
   different tool, or a different strategy. Vary the input meaningfully.
3. If the alternative also fails, **STOP CALLING TOOLS**. Reply to the
   user with a short explanation of what you tried and why you could not
   complete the request. **A clear failure message is a valid answer.**
4. **NEVER** call `fetch_dataset` for a dataset that is already shown as
   `loaded: true`. Re-fetching loaded data is the most common waste of
   budget — check the dataframe context above before fetching.

Repeated identical tool invocations indicate a stuck loop, not progress.

## DATA PROCESSING PROTOCOL:
When performing intermediate steps (filtering, grouping, cleaning):
1. ASSIGN the result to a meaningful variable name.
2. DO NOT print the dataframe content using `print(df)`.
3. INSTEAD, print a short confirmation with shape and preview: `print(f"Shape: {df.shape}"); print(df.head())`

## CRITICAL RESPONSE GUIDELINES:
1. **TRUST THE TOOL OUTPUT**: The tool output contains ACTUAL results.
2. **ALWAYS** use the ORIGINAL DataFrame names in your Python code.
3. Write and execute Python code using exact column names.
4. Before providing your final answer, verify it matches the tool output.
5. **DATA PASSTHROUGH (MANDATORY for >10 rows)**: Set `data_variable` to the variable
   name holding your result. The system retrieves the FULL DataFrame from memory and
   delivers it directly — you do NOT need to print, list, or repeat the rows.
   - If data is already in a loaded dataset variable (e.g., `kiosks_locations`), just set
     `data_variable='kiosks_locations'`. No pandas code needed.
   - If you computed a new result (e.g., `result_df = df[df['active'] == True]`), set
     `data_variable='result_df'`.
   - NEVER print() a large DataFrame — it wastes context tokens and may get truncated.

## USER-FACING PRESENTATION (MANDATORY):
Your `explanation` text is shown DIRECTLY to the end user. The user does NOT
know about datasets, variable names, aliases, column names, tool calls, or
any internal implementation detail. **Never expose these in your prose.**

Forbidden patterns in `explanation`:
- "Based on the `kiosks_locations` dataset..."
- "The `df1` DataFrame shows..."
- "Using the `sales_data` table..."
- "Column `store_id` contains..."
- "I queried `fetch_dataset`..."
- Any backtick-quoted variable name, dataset name, alias, or tool name.

Correct patterns:
- "There are 42 active kiosks across 5 states."
- "Total revenue for Q1 was $1.2M, a 15% increase over Q4."
- "The top 3 stores by sales volume are: ..."

Rule: answer the user's question in plain, natural language. Present the
RESULTS, not the process. Dataset names, aliases (`df1`), column names,
Python variables, tool names, and implementation details belong in your
CODE, never in `explanation`.

## ABSOLUTE DATA-RETURN REQUIREMENT:
If you called `python_repl_pandas`, `fetch_dataset`, or `database_query`
to answer the user's question, your structured response **MUST** populate
one of the following — not both, not neither:

- **`data`** — inline rows, ONLY when the result is ≤ 10 rows.
- **`data_variable`** — the name of the Python variable holding the
  final DataFrame (REQUIRED for > 10 rows).

The framework does **not** guess which variable to return on your behalf
when your code produces more than one DataFrame. If you created multiple
intermediate DataFrames (e.g. `raw`, `filtered`, `agg`, `result`), you
**must** name the final one in `data_variable` explicitly. Ambiguous
turns will return empty `data` to the user — that is a bug in YOUR
response, not the framework's job to fix.

Returning only an `explanation` describing data you computed, without
populating `data` or `data_variable`, is **incorrect**. The user will
see empty structured output.
</pandas_instructions>""",
)


def _build_pandas_prompt_builder() -> PromptBuilder:
    """Create a PromptBuilder for PandasAgent with domain layers."""
    builder = PromptBuilder.default()
    builder.add(DATAFRAME_CONTEXT_LAYER)
    builder.add(STRICT_GROUNDING_LAYER)
    builder.add(PANDAS_INSTRUCTIONS_LAYER)
    return builder


# --- Map intent detection -------------------------------------------------
# Phrase-based regex tuned to avoid false positives on "mapping", "id map",
# "column map", etc. The `\bmap\b` boundary excludes "mapping". The verb-
# prefix pattern uses a bounded-distance match (up to 40 non-sentence chars)
# so it survives intervening adjectives ("create a really cool map") without
# crossing sentence boundaries.
_MAP_PHRASES: Tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\b(create|show|draw|plot|render|visualize|display|generate|build|make)"
        r"\b[^.?!]{0,40}\bmap\b",
        r"\b(on|in)\s+(a\s+|an\s+|the\s+)?map\b",
    )
)

# Direct columns guarantee point-marker maps work without inference.
_DIRECT_GEO_COLS: frozenset[str] = frozenset({
    "lat", "latitude", "lon", "lng", "long", "longitude", "geometry", "geom",
})

# Indirect columns require >=2 hits to disambiguate from generic IDs.
_INDIRECT_GEO_COLS: frozenset[str] = frozenset({
    "country", "state", "region", "province", "county",
    "city", "town", "address", "street",
    "zip", "zipcode", "postal_code", "postcode",
})


def _detect_map_intent(question: str, df: Optional[pd.DataFrame]) -> bool:
    """Return True when the question phrases a map request AND the result
    DataFrame carries enough geographic signal to render one.

    Phrase match alone is not enough — we also require either a direct
    coordinate column (lat/lon) or at least two indirect geo columns
    (e.g. ``city`` + ``country``) to reduce false positives from columns
    named after generic IDs.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return False
    if not any(p.search(question) for p in _MAP_PHRASES):
        return False
    cols = {str(c).lower().strip() for c in df.columns}
    if cols & _DIRECT_GEO_COLS:
        return True
    return len(cols & _INDIRECT_GEO_COLS) >= 2


# --- Output-mode routing (FEAT-224) ---------------------------------------
# Default bilingual (EN/ES) phrase bank for PandasAgent's optional pre-LLM
# output-mode router. Maps user phrasing to the framework-agnostic STRUCTURED_*
# modes the agent already renders (chart: FEAT-215, table: FEAT-218,
# map: FEAT-221). The map route here supersedes the post-execution
# ``_detect_map_intent`` heuristic whenever the router is active.
DEFAULT_OUTPUT_MODE_ROUTES: Dict[str, List[str]] = {
    OutputMode.STRUCTURED_CHART.value: [
        "create a chart", "make a bar chart", "draw a line chart",
        "plot a pie chart", "show this as a graph", "visualize the trend",
        "haz una gráfica", "crea un gráfico de barras", "dibuja una gráfica de líneas",
        "muéstrame un gráfico de pastel", "grafica la tendencia",
    ],
    OutputMode.STRUCTURED_TABLE.value: [
        "show as a table", "display this in a table", "give me a table",
        "list the rows in a table", "tabular view",
        "muéstrame una tabla", "ponlo en una tabla", "dame una tabla",
        "lista los datos en una tabla", "vista tabular",
    ],
    OutputMode.STRUCTURED_MAP.value: [
        "show on a map", "plot these locations on a map", "map the results",
        "render a map", "display geographically",
        "muéstralo en un mapa", "ubica estos puntos en un mapa", "dibuja un mapa",
        "renderiza un mapa", "muéstralo geográficamente",
    ],
}


class PandasAgent(IntentRouterMixin, BasicAgent):
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

    METADATA_SAMPLE_ROWS = 3
    # Tighter tool-calling budget than the Google client's default (15).
    # PandasAgent benefits from failing fast when the LLM gets stuck
    # re-invoking the same fetch/query tool — see Task 2 in the
    # "Completed N tool calls" investigation.
    DEFAULT_MAX_ITERATIONS = 10
    queries: Union[List[str], dict] = None
    # Composable prompt builder with dataframe context layer
    _prompt_builder = _build_pandas_prompt_builder()

    def __init__(
        self,
        name: str = 'Pandas Agent',
        enable_scenarios: bool = False,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        df: Union[
            List[pd.DataFrame],
            Dict[str, Union[pd.DataFrame, pd.Series, Dict[str, Any]]],
            pd.DataFrame,
            pd.Series
        ] = None,
        query: Union[List[str], dict] = None,
        capabilities: str = None,
        generate_eda: bool = True,
        cache_expiration: int = 24,
        temperature: float = 0.0,
        max_iterations: Optional[int] = None,
        output_routing: bool = False,
        output_routing_config: Optional[IntentRouterConfig] = None,
        **kwargs
    ):
        """
        Initialize PandasAgent.

        Args:
            name: Agent name
            tools: Additional tools beyond default
            system_prompt: Custom system prompt
            df: DataFrame(s) to analyze
            query: QuerySource queries to execute
            capabilities: Agent capabilities description
            generate_eda: Generate exploratory data analysis
            cache_expiration: Cache expiration in hours
            output_routing: When True, activate the pre-LLM embedding-based
                output-mode router (FEAT-224) so the agent auto-selects
                STRUCTURED_CHART/TABLE/MAP from the user's phrasing. Opt-in
                because it lazy-loads a SentenceTransformer (``embeddings``
                extra) and encodes a phrase bank at ``configure()`` time.
            output_routing_config: Optional :class:`IntentRouterConfig` to
                override the default bilingual phrase bank / thresholds. When
                provided, it takes precedence over the ``output_routing`` flag's
                default config (and must set ``enable_output_mode_routing=True``
                to activate).
            **kwargs: Additional configuration
        """
        self._output_routing_enabled = output_routing
        self._output_routing_config = output_routing_config
        self._queries = query or self.queries
        self._capabilities = capabilities
        self._generate_eda = generate_eda
        self._cache_expiration = cache_expiration
        self._enable_scenarios = enable_scenarios
        self._max_iterations = (
            max_iterations
            if max_iterations is not None
            else self.DEFAULT_MAX_ITERATIONS
        )

        # Initialize DatasetManager (always create one)
        self._dataset_manager = DatasetManager()
        self._dataset_manager.set_on_change(self._sync_dataframes_from_dm)
        self._dataset_manager.set_repl_locals_getter(self._get_repl_locals)

        # Populate DatasetManager from df= parameter
        if df is not None:
            normalized_dfs, normalized_meta = self._define_dataframe(df)
            for df_name, dataframe in normalized_dfs.items():
                self._dataset_manager.add_dataframe(
                    df_name,
                    dataframe,
                    metadata=normalized_meta.get(df_name),
                    is_active=True  # Active by default
                )

        # Set references for backward compatibility
        self.dataframes = self._dataset_manager.get_active_dataframes()
        self.df_metadata = {
            name: self._build_metadata_entry(name, dataframe)
            for name, dataframe in self.dataframes.items()
        }

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            'PandasAgent initialized with DataFrames: %s', list(self.dataframes.keys())
        )
        # Initialize base agent (AbstractBot will set chatbot_id)
        super().__init__(
            name=name,
            system_prompt=system_prompt,
            tools=tools,
            temperature=temperature,
            dataframes=self.dataframes,
            **kwargs
        )
        self.description = "A specialized agent for data analysis using pandas DataFrames"

    def attach_dm(self, dm: DatasetManager) -> None:
        """
        Attach a DatasetManager to this agent.

        The DatasetManager provides the data catalog. Active datasets
        will be registered to PythonPandasTool when the agent is configured.

        Args:
            dm: DatasetManager instance
        """
        self._dataset_manager = dm
        # Auto-sync when DatasetManager mutates (fetch, activate, deactivate)
        dm.set_on_change(self._sync_dataframes_from_dm)
        dm.set_repl_locals_getter(self._get_repl_locals)
        # Sync current state
        self._sync_dataframes_from_dm()

    def _sync_dataframes_from_dm(self) -> None:
        """Sync active datasets from DatasetManager to PythonPandasTool and internal state."""
        if not self._dataset_manager:
            return

        active_dfs = self._dataset_manager.get_active_dataframes()

        # Diagnostic: surface exactly what is being synced into the REPL so an
        # empty/wrong-grain loaded frame (e.g. df10 with 0 rows) is visible in
        # the logs instead of silently misleading the LLM.
        if self.logger.isEnabledFor(logging.DEBUG):
            _alias = self._dataset_manager._get_alias_map()
            _summary = ", ".join(
                f"{name}(alias={_alias.get(name, '?')}, shape={df.shape})"
                for name, df in active_dfs.items()
            ) or "<none loaded>"
            self.logger.debug("Syncing %d active DataFrame(s) to REPL: %s", len(active_dfs), _summary)
            # Warn on loaded-but-empty frames — the prime suspect for the LLM
            # running pandas that returns nothing.
            for name, df in active_dfs.items():
                if df.empty:
                    self.logger.warning(
                        "Loaded dataset '%s' (alias=%s) is EMPTY (shape=%s) — "
                        "the LLM will get no data from it via the pandas tool.",
                        name, _alias.get(name, "?"), df.shape,
                    )

        # Update agent's dataframes reference
        self.dataframes = active_dfs

        # Rebuild metadata for active datasets
        self.df_metadata = {
            name: self._build_metadata_entry(name, df)
            for name, df in active_dfs.items()
        }

        # Get stable alias map from DatasetManager so REPL aliases
        # match what list_datasets advertises (based on registration
        # order of ALL datasets, not just loaded ones).
        alias_map = self._dataset_manager._get_alias_map()

        # Register to PythonPandasTool
        if pandas_tool := self._get_python_pandas_tool():
            pandas_tool.register_dataframes(active_dfs, alias_map=alias_map)

        # Sync ProphetForecastTool
        self._sync_prophet_tool()

        # Regenerate system prompt with updated DataFrame info
        self._define_prompt()

    def _get_default_tools(self, tools: list = None, use_tools: bool = True) -> List[AbstractTool]:
        """Return Agent-specific tools."""
        report_dir = STATIC_DIR.joinpath(self.agent_id, 'documents')
        report_dir.mkdir(parents=True, exist_ok=True)
        if not tools:
            tools = []

        # PythonPandasTool (dataframes will be registered via register_dataframes)
        pandas_tool = PythonPandasTool(
            dataframes=None,
            generate_guide=True,
            include_summary_stats=False,
            include_sample_data=False,
            sample_rows=2,
            report_dir=report_dir
        )

        # Prophet forecasting tool
        prophet_tool = ProphetForecastTool(
            dataframes=self.dataframes,
            alias_map=self._get_dataframe_alias_map(),
        )
        prophet_tool.description = (
            "Forecast future values for a time series using Facebook Prophet. "
            "Specify the dataframe, date column, value column, forecast horizon, and frequency."
        )
        if self._enable_scenarios:
            whatif_tool = WhatIfTool()
            whatif_tool.set_parent_agent(self)
            tools.append(whatif_tool)
            # append WHATIF_PROMPT to system prompt
            self.system_prompt_template += WHATIF_SYSTEM_PROMPT

        # Add core tools
        tools.extend([
            pandas_tool,
            prophet_tool,
            ToJsonTool()
        ])

        # Add DatasetManager tools (replaces MetadataTool)
        if self._dataset_manager:
            dm_tools = self._dataset_manager.get_tools()
            tools.extend(dm_tools)

        return tools

    def _define_dataframe(
        self,
        df: Union[
            List[pd.DataFrame],
            Dict[str, Union[pd.DataFrame, pd.Series, Dict[str, Any]]],
            pd.DataFrame,
            pd.Series
        ]
    ) -> tuple[Dict[str, pd.DataFrame], Dict[str, Dict[str, Any]]]:
        """
        Normalize dataframe input to dictionary format and build metadata.

        Returns:
            Tuple containing:
                - Dictionary mapping names to DataFrames
                - Dictionary mapping names to metadata dictionaries
        """
        dataframes: Dict[str, pd.DataFrame] = {}
        metadata: Dict[str, Dict[str, Any]] = {}

        if isinstance(df, pd.DataFrame):
            dataframes['df1'] = df
            metadata['df1'] = self._build_metadata_entry('df1', df)
        elif isinstance(df, pd.Series):
            dataframe = pd.DataFrame(df)
            dataframes['df1'] = dataframe
            metadata['df1'] = self._build_metadata_entry('df1', dataframe)
        elif isinstance(df, list):
            for i, dataframe in enumerate(df):
                dataframe = self._ensure_dataframe(dataframe)
                df_name = f"df{i + 1}"
                dataframes[df_name] = dataframe.copy()
                metadata[df_name] = self._build_metadata_entry(df_name, dataframe)
        elif isinstance(df, dict):
            for df_name, payload in df.items():
                dataframe, df_metadata = self._extract_dataframe_payload(payload)
                dataframes[df_name] = dataframe
                metadata[df_name] = self._build_metadata_entry(df_name, dataframe, df_metadata)
        else:
            raise ValueError(f"Expected pandas DataFrame or compatible structure, got {type(df)}")

        return dataframes, metadata

    def _extract_dataframe_payload(
        self,
        payload: Union[pd.DataFrame, pd.Series, Dict[str, Any]]
    ) -> tuple[pd.DataFrame, Optional[Dict[str, Any]]]:
        """Extract dataframe and optional metadata from payload."""
        metadata = None

        if isinstance(payload, dict) and 'data' in payload:
            dataframe = self._ensure_dataframe(payload['data'])
            metadata = payload.get('metadata')
        else:
            dataframe = self._ensure_dataframe(payload)

        return dataframe.copy(), metadata

    def _ensure_dataframe(self, value: Any) -> pd.DataFrame:
        """Ensure the provided value is converted to a pandas DataFrame."""
        if isinstance(value, pd.DataFrame):
            return value
        if isinstance(value, pd.Series):
            return value.to_frame()
        raise ValueError(f"Expected pandas DataFrame or Series, got {type(value)}")

    def _build_metadata_entry(
        self,
        name: str,
        df: pd.DataFrame,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build normalized metadata entry for a dataframe.

        KEY CHANGE: No longer generates EDA summary here.
        EDA is generated dynamically by MetadataTool when requested.
        """
        row_count, column_count = df.shape

        # Basic metadata structure - EDA removed
        entry: Dict[str, Any] = {
            'name': name,
            'description': '',
            'shape': {
                'rows': int(row_count),
                'columns': int(column_count)
            },
            'row_count': int(row_count),
            'column_count': int(column_count),
            'memory_usage_mb': float(df.memory_usage(deep=True).sum() / 1024 / 1024),
            'columns': {},
            'sample_data': self._build_sample_rows(df)
        }

        # Extract user-provided metadata
        provided_description = None
        provided_sample_data = None
        column_metadata: Dict[str, Any] = {}

        if isinstance(metadata, dict):
            provided_description = metadata.get('description')
            if isinstance(metadata.get('sample_data'), list):
                provided_sample_data = metadata['sample_data']

            if isinstance(metadata.get('columns'), dict):
                column_metadata = metadata['columns']
            else:
                column_metadata = {
                    key: value
                    for key, value in metadata.items()
                    if key in df.columns
                }

        # Build column metadata
        for column in df.columns:
            column_info = column_metadata.get(column)
            entry['columns'][column] = self._build_column_metadata(
                column,
                df[column],
                column_info
            )

        # Set description and samples
        entry['description'] = provided_description or f"Columns available in '{name}'"
        if provided_sample_data is not None:
            entry['sample_data'] = provided_sample_data

        return entry

    @staticmethod
    def _build_column_metadata(
        column_name: str,
        series: pd.Series,
        metadata: Optional[Union[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Normalize metadata for a single column."""
        if isinstance(metadata, str):
            column_meta: Dict[str, Any] = {'description': metadata}
        elif isinstance(metadata, dict):
            column_meta = metadata.copy()
        else:
            column_meta = {}

        column_meta.setdefault('description', column_name.replace('_', ' ').title())
        column_meta.setdefault('dtype', str(series.dtype))

        return column_meta

    def _build_sample_rows(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Return sample rows for metadata responses."""
        try:
            return df.head(self.METADATA_SAMPLE_ROWS).to_dict(orient='records')
        except Exception:
            return []

    def _build_dataframe_info(self) -> str:
        """
        Build DataFrame information for system prompt.

        Includes both loaded DataFrames (ready for analysis) and unloaded
        datasets registered in the DatasetManager catalog so the LLM knows
        they exist and can call ``fetch_dataset`` to materialize them.
        """
        alias_map = self._get_dataframe_alias_map()
        df_info_parts = []

        # Tool-level usage rules (owned by DatasetManager, shared by every agent
        # that drives one) go first so the LLM reads the decision rules before
        # the dataset listing.
        if self._dataset_manager:
            rules = self._dataset_manager.get_usage_rules()
            if rules and rules.strip():
                df_info_parts.extend([rules.strip(), ""])

        # A dataset can be marked loaded=True yet hold zero rows (a query that
        # returned nothing, or an eager empty df). Advertising such a frame under
        # "Loaded DataFrames" misleads the LLM into running pandas that silently
        # returns nothing, so partition empties out and surface them separately.
        loaded_nonempty = {n: df for n, df in self.dataframes.items() if not df.empty}
        loaded_empty = {n: df for n, df in self.dataframes.items() if df.empty}

        # ── Loaded DataFrames ─────────────────────────────────────────
        if loaded_nonempty:
            df_info_parts.extend([
                f"**Loaded DataFrames:** {len(loaded_nonempty)}",
                "",
            ])

            for df_name, df in loaded_nonempty.items():
                alias = alias_map.get(df_name, "")
                display_name = f"**{df_name}** (alias: `{alias}`)" if alias else f"**{df_name}**"
                desc = ""
                entry = None
                if self._dataset_manager and df_name in self._dataset_manager._datasets:
                    entry = self._dataset_manager._datasets[df_name]
                    if entry.description:
                        desc = f" — {entry.description}"
                df_info_parts.append(
                    f"- {display_name}: {df.shape[0]:,} rows × {df.shape[1]} columns{desc}"
                )

                # Include column schema so the LLM knows the data structure
                col_types = entry.column_types if entry and entry.column_types else {}
                columns_info = []
                for col in df.columns:
                    dtype = col_types.get(col, str(df[col].dtype))
                    col_info = f"    - `{col}` ({dtype})"
                    # For categorical/object columns, show unique values (max 10)
                    if dtype in ('categorical_text', 'text', 'object') or df[col].dtype == 'object':
                        try:
                            uniques = df[col].dropna().unique()
                            if len(uniques) <= 15:
                                vals = ', '.join(repr(v) for v in sorted(uniques))
                                col_info += f" — values: [{vals}]"
                            else:
                                sample = ', '.join(repr(v) for v in sorted(uniques)[:8])
                                col_info += f" — {len(uniques)} unique, e.g.: [{sample}, ...]"
                        except (TypeError, ValueError):
                            pass
                    columns_info.append(col_info)
                if columns_info:
                    df_info_parts.append("  Columns:")
                    df_info_parts.extend(columns_info)

            first_name = next(iter(loaded_nonempty))
            first_alias = alias_map.get(first_name, "df1")
            df_info_parts.extend([
                "  ```python",
                "  # Using original name (recommended):",
                f"  result = {first_name}.groupby('column').sum()",
                "  ```",
                "- Also works: Use aliases for brevity",
                "  ```python",
                "  # Using alias (convenience):",
                f"  result = {first_alias}.groupby('column').sum()",
                "  ```",
            ])

        # ── Unloaded datasets in the catalog ──────────────────────────
        if self._dataset_manager:
            unloaded = [
                (name, entry)
                for name, entry in self._dataset_manager._datasets.items()
                if not entry.loaded
            ]
            if unloaded:
                df_info_parts.extend([
                    "",
                    f"**Unloaded Datasets (call `fetch_dataset` to load):** {len(unloaded)}",
                ])
                for name, entry in unloaded:
                    desc = f": {entry.description}" if entry.description else ""
                    cols = entry.columns
                    row_est = getattr(entry.source, '_row_count_estimate', None)
                    size_hint = f", ~{row_est:,} rows" if row_est else ""
                    schema = getattr(entry.source, '_schema', {})
                    if schema:
                        # TableSource with prefetched schema: show all columns with types
                        col_list = [f"`{c}` ({t})" for c, t in schema.items()]
                        df_info_parts.append(
                            f"- **{name}**{desc} ({len(cols)} columns{size_hint})"
                        )
                        df_info_parts.append(f"  Columns: {', '.join(col_list)}")
                    elif cols:
                        col_hint = f" — columns: {', '.join(cols[:8])}"
                        if len(cols) > 8:
                            col_hint += f", ... ({len(cols)} total)"
                        df_info_parts.append(f"- `{name}`{desc}{col_hint}{size_hint}")
                    else:
                        df_info_parts.append(f"- `{name}`{desc}{size_hint}")

        # ── Loaded-but-empty datasets ─────────────────────────────────
        if loaded_empty:
            df_info_parts.extend([
                "",
                f"**⚠️ Empty datasets (registered but currently hold 0 rows — do NOT query directly):** {len(loaded_empty)}",
                "Running pandas on these returns nothing. Call `fetch_dataset(name=...)` to "
                "(re)populate them, or `get_metadata(name=...)` to inspect why they are empty.",
            ])
            for df_name, df in loaded_empty.items():
                alias = alias_map.get(df_name, "")
                display_name = f"**{df_name}** (alias: `{alias}`)" if alias else f"**{df_name}**"
                desc = ""
                if self._dataset_manager and df_name in self._dataset_manager._datasets:
                    entry = self._dataset_manager._datasets[df_name]
                    if entry.description:
                        desc = f" — {entry.description}"
                df_info_parts.append(
                    f"- {display_name}: 0 rows × {df.shape[1]} columns{desc}"
                )

        if not self.dataframes and not (self._dataset_manager and any(
            not e.loaded for e in self._dataset_manager._datasets.values()
        )):
            return "No DataFrames loaded. Use `add_dataframe` to register data."

        df_info_parts.extend([
            "",
            "**To get detailed information:**",
            "- Call `list_datasets()` to see all datasets with loaded status",
            "- Call `get_metadata(name='dataset_name')` for schema and EDA details",
            ""
        ])

        return "\n".join(df_info_parts)

    async def create_system_prompt(self, **kwargs):
        """Override to inject dataframe_schemas for the layer path."""
        if self._prompt_builder and "dataframe_schemas" not in kwargs:
            kwargs["dataframe_schemas"] = self._build_dataframe_info()
        return await super().create_system_prompt(**kwargs)

    def _define_prompt(self, prompt: str = None, **kwargs):
        """
        Define the system prompt with DataFrame context.

        KEY CHANGE: System prompt no longer includes EDA summaries.
        """
        # Build simplified DataFrame information
        df_info = self._build_dataframe_info()
        # Store for the PromptBuilder layer path
        self._dataframe_schemas = df_info

        # Default capabilities if not provided
        capabilities = self._capabilities or """
** Your Capabilities:**
- Perform complex data analysis and transformations
- Create visualizations (matplotlib, seaborn, plotly)
- Generate statistical summaries
- Export results to various formats
- Execute pandas operations efficiently
"""

        # Get backstory
        backstory = self.backstory or self.default_backstory()

        # Build prompt using string.Template
        tmpl = Template(self.system_prompt_template)
        pre_context = ''
        if self.pre_instructions:
            pre_context = "## IMPORTANT PRE-INSTRUCTIONS: \n" + "\n".join(
                f"- {a}." for a in self.pre_instructions
            )
        self.system_prompt_template = tmpl.safe_substitute(
            name=self.name,
            description=self.description,
            df_info=df_info,
            capabilities=capabilities.strip(),
            today_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            backstory=backstory,
            pre_context=pre_context,
            **kwargs
        )

    async def configure(
        self,
        app: web.Application = None,
        queries: Union[List[str], dict] = None,
    ) -> None:
        """
        Configure the PandasAgent.

        Args:
            app: Optional aiohttp Application
            queries: Optional query slugs to load data from
        """
        if queries is not None:
            # if queries provided, override existing
            self._queries = queries

        # Load from queries if specified and no dataframes loaded yet
        if self._queries and not self.dataframes:
            # Delegate loading to DatasetManager (handles caching + resilience)
            # dataframes are automatically added to DM by load_data
            await self._dataset_manager.load_data(
                query=self._queries,
                agent_name=self.chatbot_id,
                cache_expiration=self._cache_expiration
            )

        # Sync datasets from DatasetManager to tools
        self._sync_dataframes_from_dm()

        # Call parent configure (handles LLM, tools, memory, etc.)
        await super().configure(app=app)

        # FEAT-224: optionally activate the pre-LLM output-mode router so the
        # agent auto-selects STRUCTURED_CHART/TABLE/MAP from the user's phrasing
        # (e.g. "create a pie chart of Q1 sales"). Opt-in: loading the encoder
        # and encoding the phrase bank is CPU-bound, so it runs off the event
        # loop and only when explicitly enabled.
        if self._output_routing_enabled or self._output_routing_config is not None:
            router_cfg = self._output_routing_config or IntentRouterConfig(
                enable_output_mode_routing=True,
                output_mode_routes=DEFAULT_OUTPUT_MODE_ROUTES,
            )
            await asyncio.to_thread(self.configure_output_router, router_cfg)

        # Cache data after configuration


        # Regenerate system prompt with updated DataFrame info
        self._define_prompt()

        self.logger.info(
            f"PandasAgent '{self.name}' configured with {len(self.dataframes)} DataFrame(s)"
        )

    async def invoke(
        self,
        question: str,
        response_model: type[BaseModel] | None = None,
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
        response = await self.ask(
            question=question,
            **kwargs
        )
        if isinstance(response, AgentResponse):
            return response

        # Convert to AgentResponse if needed
        if isinstance(response, AIMessage):
            return self._agent_response(
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

    def _extract_last_infographic_result(
        self, tool_calls: Optional[List[Any]],
    ) -> Optional[Any]:
        """Return the last ``InfographicRenderResult`` from the tool calls list.

        When multiple ``infographic_render`` calls occurred in the same turn,
        only the LAST one is returned (spec §7 documents this design).

        Args:
            tool_calls: List of ``ToolCall`` objects from the AIMessage.

        Returns:
            The last ``InfographicRenderResult`` instance, or ``None`` when no
            infographic render was performed.
        """
        if not tool_calls:
            return None
        cls = _get_infographic_result_class()
        if cls is None:
            return None
        for tc in reversed(tool_calls):
            result = getattr(tc, "result", None)
            if isinstance(result, cls):
                return result
        return None

    def _finalize_infographic_response(
        self, response: Any, envelope: Any,
    ) -> Optional[str]:
        """Apply an ``InfographicRenderResult`` to the agent response in place.

        Splits the turn into two channels for the frontend (FEAT-197):

        - ``response.response`` keeps the LLM's natural-language explanation,
          used as the chat-bubble reply (preferred by ``AIMessage.to_text``).
        - ``response.output`` carries the infographic HTML (inline when small,
          otherwise the signed URL), opened separately in a canvas.

        The explanation MUST be captured before ``response.output`` is
        overwritten: ``AIMessage.content`` is a property alias for ``output``,
        and the client factory writes the LLM text into BOTH ``output`` and
        ``response``, so assigning the HTML to ``output`` would otherwise be the
        only remaining copy. The explanation is also mirrored into
        ``response.metadata['explanation']`` as an explicit, documented field.

        Args:
            response: The ``AIMessage`` to mutate in place.
            envelope: The ``InfographicRenderResult`` from the render tool.

        Returns:
            The captured explanation text (may be ``None`` when the LLM emitted
            no natural-language text alongside the render call).
        """
        explanation = getattr(response, "response", None)
        if not explanation and isinstance(response.output, str):
            explanation = response.output

        response.output = envelope.html_inline or envelope.html_url
        response.output_mode = OutputMode.INFOGRAPHIC
        response.artifact_id = envelope.artifact_id
        if explanation:
            response.response = explanation

        meta = dict(getattr(response, "metadata", None) or {})
        meta.update({
            "html_url": envelope.html_url,
            "html_inline_omitted": envelope.html_inline is None,
            "enhanced": envelope.enhanced,
            "template_name": envelope.template_name,
            "theme": envelope.theme,
            "explanation": explanation,
        })
        if hasattr(response, "metadata"):
            response.metadata = meta

        return explanation

    def _spatial_result_from_dataframe(
        self, df: pd.DataFrame,
    ) -> Optional[Any]:
        """Convert a result DataFrame into a ``SpatialResult`` for STRUCTURED_MAP.

        FEAT-224: replaces the deprecated Folium re-render path. The backend no
        longer generates map HTML — it builds the GeoJSON wire contract the
        ``StructuredMapRenderer`` consumes (via
        :meth:`SpatialResult.from_dataframe`), so the frontend renders the map.

        Args:
            df: The result DataFrame produced for the current question.

        Returns:
            A ``SpatialResult`` when the rows yield at least one feature, or
            ``None`` when no coordinates/geometry can be resolved (caller then
            falls through to the default output instead of an empty map).
        """
        try:
            from ..tools.dataset_manager.spatial.contracts import SpatialResult
        except ImportError:
            self.logger.debug(
                "SpatialResult unavailable; skipping STRUCTURED_MAP conversion."
            )
            return None
        try:
            result = SpatialResult.from_dataframe(df)
        except ValueError:
            # No geometry column and no lat/lon pair — not mappable.
            return None
        if not any(layer.features for layer in result.layers.values()):
            return None
        return result

    def _spatial_result_from_datasets(
        self, datasets: List[Dict[str, Any]],
    ) -> Optional[Any]:
        """Build a MULTI-layer ``SpatialResult`` from a multi-dataset payload.

        FEAT-221: :meth:`_spatial_result_from_dataframe` converts a single result
        DataFrame for the STRUCTURED_MAP fallback, but when the agent produces
        SEVERAL DataFrames in one turn (e.g. one layer per category so each can
        be colored differently), ``_inject_multi_data_from_variables`` sets
        ``response.data`` to a list of ``DatasetResult`` dicts. The map renderer
        then rejects the list (``response.data must be a SpatialResult``).

        This converts each dataset entry into its own layer and merges them into
        one multi-layer ``SpatialResult`` so the map renders. Entries with no
        resolvable geometry/lat-lon are skipped (not every layer in a multi-
        dataset turn need be mappable). As a fallback, a flat list of row dicts
        (not wrapped in ``DatasetResult``) is treated as a single layer.

        Args:
            datasets: ``response.data`` as a list — either ``DatasetResult``
                dicts (each with a ``data`` list of record dicts and a
                ``name``/``variable``) or a flat list of row dicts.

        Returns:
            A multi-layer ``SpatialResult`` with at least one feature, or
            ``None`` when no entry yields a mappable layer.
        """
        try:
            from ..tools.dataset_manager.spatial.contracts import SpatialResult
        except ImportError:
            self.logger.debug(
                "SpatialResult unavailable; skipping multi-dataset STRUCTURED_MAP "
                "conversion."
            )
            return None

        if not datasets:
            return None

        # Dataset-shaped entries carry a nested ``data`` list; a flat list of row
        # dicts does not. Treat the latter as a single anonymous layer.
        dataset_shaped = [
            e for e in datasets if isinstance(e, dict) and isinstance(e.get("data"), list)
        ]
        if not dataset_shaped:
            if all(isinstance(e, dict) for e in datasets):
                return self._spatial_result_from_dataframe(pd.DataFrame(datasets))
            return None

        merged_layers: Dict[str, Any] = {}
        for entry in dataset_shaped:
            rows = entry.get("data")
            if not rows:
                continue
            name = str(
                entry.get("name") or entry.get("variable") or f"layer_{len(merged_layers)}"
            )
            try:
                df = pd.DataFrame(rows)
            except Exception:  # noqa: BLE001
                continue
            if df.empty:
                continue
            try:
                layer_result = SpatialResult.from_dataframe(
                    df, dataset=name, layer=name,
                )
            except ValueError:
                # This dataset has no geometry/lat-lon pair — skip its layer.
                self.logger.debug(
                    "Multi-dataset STRUCTURED_MAP: dataset '%s' has no resolvable "
                    "coordinates/geometry — skipping layer.", name,
                )
                continue
            for layer_key, layer_val in layer_result.layers.items():
                # Guard against key collisions across datasets.
                key = (
                    layer_key
                    if layer_key not in merged_layers
                    else f"{layer_key}_{len(merged_layers)}"
                )
                merged_layers[key] = layer_val

        if not merged_layers:
            return None
        if not any(layer.features for layer in merged_layers.values()):
            return None
        return SpatialResult(version=2, layers=merged_layers)

    @staticmethod
    def _client_uses_split_structured_with_tools(client: Any) -> bool:
        """Return True when the LLM client splits a tool-using call and a
        structured-output call into two separate LLM invocations.

        Why: Gemini refuses to combine ``tools`` with ``response_schema``
        in a single ``generateContent`` call, so the Google client falls
        back to a two-phase flow — first the tool loop, then a reformat
        call to coerce the answer into the schema. The second call adds
        ~10s of latency. Detecting this lets PandasAgent ask the LLM to
        embed the structured JSON inline in the first answer, triggering
        the client's fast-path parser and skipping the reformat call.

        Other providers (OpenAI, Anthropic, Groq) accept tools +
        structured output in a single call and do not benefit from the
        in-band JSON hint.
        """
        return client.__class__.__name__ == 'GoogleGenAIClient'

    @staticmethod
    def _build_fast_path_json_addendum(output_type: type) -> Optional[str]:
        """Build a prompt addendum telling the LLM to append a
        ```json``` block matching ``output_type`` to the end of its
        response. Returns ``None`` if no usable skeleton can be built.

        The Google client's fast-path parser (``client.py:2334``) treats
        any response containing ``\\`\\`\\`json`` as a structured-output
        candidate and skips the second reformat LLM call when parsing
        succeeds. This addendum is best-effort: if the LLM ignores it,
        the existing two-call fallback still produces valid output.
        """
        skeleton: Optional[Dict[str, Any]] = None

        cfg = getattr(output_type, 'model_config', None)
        if isinstance(cfg, dict):
            example = (cfg.get('json_schema_extra') or {}).get('example')
            if isinstance(example, dict):
                skeleton = example

        if skeleton is None:
            fields = getattr(output_type, 'model_fields', None)
            if not fields:
                return None
            skeleton = {name: None for name in fields}

        try:
            skeleton_str = json.dumps(skeleton, indent=2, default=str)
        except (TypeError, ValueError):
            return None

        return (
            "\n\n"
            "## FINAL RESPONSE FORMAT — APPEND JSON BLOCK (CRITICAL):\n"
            "After your natural-language markdown explanation (including "
            "any markdown tables), append exactly ONE fenced ```json``` "
            "block at the very END of your response, matching this "
            "schema:\n\n"
            f"```json\n{skeleton_str}\n```\n\n"
            "RULES (STRICT):\n"
            "- The JSON block MUST be the LAST thing in your response.\n"
            "- The `explanation` field MUST contain the COMPLETE "
            "markdown explanation from above, verbatim — duplication "
            "is intentional; do NOT summarize or truncate.\n"
            "- For results with > 10 rows, set `data_variable` to the "
            "Python variable name holding the DataFrame and leave "
            "`data` as null. NEVER inline large tables.\n"
            "- For results with ≤ 10 rows, populate `data` with "
            "`{\"columns\": [...], \"rows\": [[...], ...]}` and leave "
            "`data_variable` null.\n"
            "- Numeric values in `rows` MUST be raw numbers — no "
            "currency symbols, no percent signs, no thousands "
            "separators.\n"
            "- Including this JSON block avoids a costly second LLM "
            "reformat call (~10s latency saved per query).\n"
        )

    # Meta / capability / descriptive questions that should be answered
    # directly in prose, WITHOUT forcing the PandasAgentResponse data schema
    # or a data-analysis tool loop. Kept deliberately specific (multi-word
    # phrases) so genuine analytical queries do not match.
    _CONVERSATIONAL_PATTERNS = re.compile(
        r"""(?:^|\b)(?:
            what\s+(?:can|are)\s+you\s+(?:do|able\s+to\s+do)        |
            what\s+do\s+you\s+do                                     |
            what\s+are\s+your\s+(?:capabilities|abilities|skills)    |
            what\s+can\s+you\s+help\s+(?:me\s+)?with                 |
            how\s+(?:can|do)\s+you\s+help                            |
            who\s+are\s+you                                          |
            what\s+(?:tools|datasets|data)\s+(?:do\s+you\s+have|are\s+available) |
            qu[eé]\s+(?:puedes|sabes)\s+hacer                        |
            qu[eé]\s+eres                                            |
            qui[eé]n\s+eres                                          |
            cu[aá]les\s+son\s+tus\s+(?:capacidades|habilidades)      |
            en\s+qu[eé]\s+(?:me\s+)?puedes\s+ayudar                  |
            para\s+qu[eé]\s+sirves                                   |
            qu[eé]\s+(?:herramientas|datasets|datos)\s+tienes
        )(?:\b|$)""",
        re.IGNORECASE | re.VERBOSE,
    )
    _GREETING_PATTERNS = re.compile(
        r"^\s*(?:hi|hello|hey|hola|buenas|buenos\s+d[ií]as|good\s+morning|"
        r"help|ayuda|ping|test)\b[\s!.?]*$",
        re.IGNORECASE,
    )

    def _is_conversational_query(self, question: str) -> bool:
        """Detect meta / capability / greeting questions answerable in prose.

        These should NOT be coerced into the ``PandasAgentResponse`` data
        schema or a data-analysis tool loop — doing so makes the model treat
        them as analysis tasks (dumping data or spiralling in tool calls).

        Args:
            question: The raw user question.

        Returns:
            ``True`` when the question is conversational / descriptive and
            should be answered directly without forced structured output.
        """
        if not question or not question.strip():
            return False
        q = question.strip()
        if self._GREETING_PATTERNS.match(q):
            return True
        return bool(self._CONVERSATIONAL_PATTERNS.search(q))

    async def ask(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        use_conversation_history: bool = True,
        memory: Optional[Any] = None,
        ctx: Optional[Any] = None,
        structured_output: Optional[Any] = None,
        output_mode: Any = None,
        format_kwargs: dict = None,
        return_structured: bool = True,
        **kwargs
    ) -> AIMessage:
        """
        Override ask() method to ensure PythonPandasTool is always used.

        This method is specialized for PandasAgent and differs from AbstractBot.ask():
        - Always uses tools (specifically PythonPandasTool)
        - Does NOT use vector search/knowledge base context
        - Returns AIMessage
        - Focuses on DataFrame analysis with the pre-loaded data

        Args:
            question: The user's question about the data
            session_id: Session identifier for conversation history
            user_id: User identifier
            use_conversation_history: Whether to use conversation history
            memory: Optional memory handler
            ctx: Request context
            structured_output: Structured output configuration or model
            return_structured: Whether to return a default structured output (PandasAgentResponse)
            output_mode: Output formatting mode
            format_kwargs: Additional kwargs for formatter
            **kwargs: Additional arguments (temperature, max_tokens, etc.)

        Returns:
            AIMessage with the analysis result
        """
        # Generate IDs if not provided
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or "anonymous"
        turn_id = str(uuid.uuid4())

        # Use default temperature of 0 if not specified
        if 'temperature' not in kwargs:
            kwargs['temperature'] = 0.0

        try:
            # Get conversation history (no vector search for PandasAgent)
            conversation_history = None
            conversation_context = ""
            memory = memory or self.conversation_memory

            if use_conversation_history and memory:
                conversation_history = await self.get_conversation_history(user_id, session_id) or await self.create_conversation_history(user_id, session_id)
                conversation_context = self.build_conversation_context(conversation_history)

            # Determine output mode
            if output_mode is None:
                output_mode = OutputMode.DEFAULT

            # FEAT-224: pre-LLM output-mode routing for data/viz queries (the
            # primary use case, e.g. "create a pie chart of Q1 sales"). Runs
            # after the None->DEFAULT normalization above and only when the
            # caller did not specify a mode (precedence: explicit > router >
            # default). No-op unless a routing mixin (IntentRouterMixin) is present.
            if output_mode == OutputMode.DEFAULT:
                _resolved_mode = await self._resolve_output_mode(question, ctx)
                if _resolved_mode is not None:
                    output_mode = _resolved_mode
                    if ctx is not None:
                        ctx.output_mode = _resolved_mode

            # Apply agent-level default (e.g. output_mode=TEXT in constructor)
            # when neither the caller nor the router resolved a specific mode.
            output_mode = self._apply_default_output_mode(output_mode)

            # Build context from different sources (no vector context for PandasAgent)
            vector_metadata = {'activated_kbs': []}

            # Get vector context (method handles use_vectors check internally)
            vector_context, vector_meta = await self._build_vector_context(
                question,
                use_vectors=False,  # NO vector context for PandasAgent
            )
            if vector_meta:
                vector_metadata['vector'] = vector_meta

            # Get user-specific context
            user_context = await self._build_user_context(
                user_id=user_id,
                session_id=session_id,
            )

            # Get knowledge base context
            kb_context, kb_meta = await self._build_kb_context(
                question,
                user_id=user_id,
                session_id=session_id,
                ctx=ctx,
            )
            if kb_meta.get('activated_kbs'):
                vector_metadata['activated_kbs'] = kb_meta['activated_kbs']

            # Pre-LLM: episodic / mixin-provided context
            episodic_context = ""
            try:
                episodic_context = await self._on_pre_ask(
                    question,
                    user_id=user_id,
                    session_id=session_id,
                )
            except Exception as _pre_exc:
                self.logger.debug("_on_pre_ask hook failed: %s", _pre_exc)

            if episodic_context:
                user_context = (
                    f"{user_context}\n\n{episodic_context}"
                    if user_context else episodic_context
                )

            # Build system prompt with DataFrame context (no vector context)
            # Create system prompt
            system_prompt = await self.create_system_prompt(
                kb_context=kb_context,
                vector_context=vector_context,
                conversation_context=conversation_context,
                metadata=vector_metadata,
                user_context=user_context,
                **kwargs
            )
            # Handle output mode in system prompt
            if output_mode != OutputMode.DEFAULT:
                _mode = output_mode if isinstance(output_mode, str) else getattr(output_mode, 'value', 'default')
                system_prompt += OUTPUT_SYSTEM_PROMPT.format(output_mode=_mode)
                # Get the Output Mode Prompt
                # For TABLE output, do NOT append GridJS system prompt (it conflicts with structured output).
                if output_mode != OutputMode.TABLE:
                    if system_prompt_addon := self.formatter.get_system_prompt(output_mode):
                        system_prompt += system_prompt_addon

                if output_mode == OutputMode.MSTEAMS:
                    system_prompt += (
                        "\nIMPORTANT: For MS Teams output:\n"
                        "1. Do NOT include markdown tables in your textual explanation.\n"
                        "2. Provide only a clear textual summary and analysis.\n"
                        "3. The data table will be displayed separately."
                    )
                elif output_mode == OutputMode.TEXT:
                    system_prompt += (
                        "\nPLAIN TEXT RULES:\n"
                        "- Do NOT use markdown tables (| col | col |), headers (#), "
                        "bold (**text**), or any markdown formatting.\n"
                        "- Present tabular facts as 'Label: value' lines, one per line.\n"
                        "- Use short sentences and paragraphs.\n"
                    )
                else:
                    system_prompt += (
                        "\nMARKDOWN FORMATTING RULES:\n"
                        "- If you include a markdown table in your response, you MUST precede it with TWO blank lines (\\n\\n).\n"
                        "- Do not attach tables directly to the previous paragraph.\n"
                    )

            # Configure LLM if needed
            if (new_llm := kwargs.pop('llm', None)):
                self.configure_llm(llm=new_llm, **kwargs.pop('llm_config', {}))

            # print(' :::: System Prompt:\n')
            # print(system_prompt)
            # print('\n:::: End System Prompt\n')
            # Make the LLM call with tools ALWAYS enabled
            async with self._llm as client:
                llm_kwargs = {
                    "prompt": question,
                    "system_prompt": system_prompt,
                    "model": kwargs.get('model', self._llm_model),
                    "temperature": kwargs.get('temperature', 0.0),
                    "user_id": user_id,
                    "session_id": session_id,
                    "use_tools": True,  # ALWAYS use tools for PandasAgent
                }

                # Forward max_iterations only when the active LLM client
                # advertises it (currently only the Google client). Other
                # backends (OpenAI, Groq, etc.) have no **kwargs on ask(),
                # so blindly forwarding would raise TypeError.
                try:
                    ask_params = inspect.signature(client.ask).parameters
                except (TypeError, ValueError):
                    ask_params = {}
                if 'max_iterations' in ask_params:
                    llm_kwargs["max_iterations"] = kwargs.get(
                        'max_iterations', self._max_iterations
                    )
                if 'stop_tools' in ask_params:
                    llm_kwargs["stop_tools"] = kwargs.get(
                        'stop_tools', {"to_json"}
                    )

                # Add max_tokens if specified
                max_tokens = kwargs.get('max_tokens', self._llm_kwargs.get('max_tokens'))
                if max_tokens is not None:
                    llm_kwargs["max_tokens"] = max_tokens

                # Conversational / meta questions (capabilities, greetings,
                # "what can you do") are answered directly in prose. Forcing
                # the PandasAgentResponse data schema on them makes the model
                # treat them as analysis tasks — either dumping data or
                # spiralling in a tool loop. Skip forced structured output so
                # the model replies naturally; the grounding layer's
                # descriptive-question carve-out keeps it from inventing data.
                if (
                    return_structured
                    and structured_output is None
                    and self._is_conversational_query(question)
                ):
                    self.logger.info(
                        "Conversational/meta query detected — skipping forced "
                        "structured output for: %r",
                        question[:80],
                    )
                    return_structured = False

                # Handle structured output
                if structured_output:
                    if isinstance(structured_output, type) and issubclass(structured_output, BaseModel):
                        llm_kwargs["structured_output"] = StructuredOutputConfig(
                            output_type=structured_output
                        )
                    elif isinstance(structured_output, StructuredOutputConfig):
                        llm_kwargs["structured_output"] = structured_output
                elif return_structured:
                    # FEAT-215: for STRUCTURED_CHART the structured output IS the
                    # chart config (mirrors the frontend AppChartConfig), not the
                    # generic PandasAgentResponse. Forcing PandasAgentResponse here
                    # made the model emit a prose-only {explanation} and omit the
                    # chart config; advertising StructuredChartConfig (incl. the
                    # fast-path JSON addendum below) makes it reliably emit the
                    # config + embedded data rows.
                    _forced_output_type = (
                        StructuredChartConfig
                        if output_mode == OutputMode.STRUCTURED_CHART
                        else PandasAgentResponse
                    )
                    llm_kwargs["structured_output"] = StructuredOutputConfig(
                        output_type=_forced_output_type
                    )

                # Fast-path optimization for clients that split tools +
                # structured_output into two LLM calls (currently only
                # Google's GenAI client). Asking the LLM to embed the
                # structured JSON inline lets the client's fast-path
                # parser skip the second reformat call.
                structured_cfg = llm_kwargs.get("structured_output")
                if (
                    structured_cfg is not None
                    and self._client_uses_split_structured_with_tools(client)
                ):
                    output_type = getattr(structured_cfg, 'output_type', None)
                    if (
                        isinstance(output_type, type)
                        and issubclass(output_type, BaseModel)
                    ):
                        addendum = self._build_fast_path_json_addendum(output_type)
                        if addendum:
                            llm_kwargs["system_prompt"] += addendum

                # Call the LLM
                response: AIMessage = await client.ask(**llm_kwargs)

                # Enhance response with conversation context metadata
                response.set_conversation_context_info(
                    used=bool(conversation_context),
                    context_length=len(conversation_context) if conversation_context else 0
                )

                # Transfer artifacts accumulated by DatasetManager
                # (e.g. executed SQL queries) onto the AIMessage.
                if self._dataset_manager:
                    response.artifacts.extend(
                        self._dataset_manager.drain_artifacts()
                    )

                response.session_id = session_id
                response.turn_id = getattr(response, 'turn_id', None) or turn_id
                data_response: Optional[PandasAgentResponse] = response.output \
                    if isinstance(response.output, PandasAgentResponse) else None

                # FEAT-221: in STRUCTURED_MAP mode the agent calls the spatial_filter
                # tool which returns a SpatialResult. Route the SpatialResult to
                # response.data so StructuredMapRenderer (table-style ownership) can
                # read it deterministically. Unlike STRUCTURED_CHART, we do NOT force
                # a structured_output type — the LLM emits the SpatialFilterSpec and
                # calls the tool; the renderer builds the config.
                if output_mode == OutputMode.STRUCTURED_MAP:
                    # Look for a SpatialResult in tool call results
                    spatial_result = self._extract_spatial_result_from_tools(
                        response.tool_calls
                    )
                    if spatial_result is not None:
                        response.data = spatial_result
                        self.logger.info(
                            "STRUCTURED_MAP: routed SpatialResult (%d layers) to response.data",
                            len(getattr(spatial_result, "layers", {})),
                        )
                    else:
                        self.logger.warning(
                            "STRUCTURED_MAP: no SpatialResult found in tool calls; "
                            "response.data may be empty for the renderer."
                        )
                    # Attach the originating SpatialFilterSpec so StructuredMapRenderer
                    # can build MapQuery.  This must be set BEFORE the renderer runs.
                    spec = self._extract_spatial_filter_spec_from_tools(response.tool_calls)
                    if spec is not None:
                        response.spatial_filter_spec = spec

                # FEAT-215: in STRUCTURED_CHART mode the structured output IS the
                # chart config (StructuredChartConfig), not a PandasAgentResponse, so
                # the branch below is skipped.
                # FEAT-224 (G3): response.code is NO LONGER populated with the config
                # here — the StructuredChartRenderer now reads its input config from
                # response.output / response.structured_output (TASK-1460). Only the
                # data_variable injection is kept so rows still land in response.data.
                if output_mode == OutputMode.STRUCTURED_CHART and data_response is None:
                    _cfg_out = response.output
                    _chart_data_var: Optional[str] = None
                    if isinstance(_cfg_out, StructuredChartConfig):
                        # response.code no longer set here (FEAT-224 G3)
                        _chart_data_var = _cfg_out.data_variable
                    elif isinstance(_cfg_out, dict):
                        # response.code no longer set here (FEAT-224 G3)
                        _chart_data_var = (
                            _cfg_out.get("data_variable")
                            or _cfg_out.get("dataVariable")
                        )
                    # The chart config may name the DataFrame variable to chart.
                    # Inject it explicitly: this disambiguates turns that produced
                    # multiple DataFrames, where blind inference refuses to guess
                    # (see _infer_data_variable_from_tools).
                    if _chart_data_var:
                        await self._inject_data_from_variable(
                            response, _chart_data_var
                        )

                missing_data_variables: List[str] = []
                if data_response:
                    # Extract the dataframe
                    response.data = data_response.to_dataframe()
                    # Extract the textual explanation
                    response.response = data_response.explanation
                    # requested code:
                    response.code = data_response.code if hasattr(data_response, 'code') else None
                    # declared as "is_structured" response
                    response.is_structured = True
                    # Anti-stale guard (cross-turn contamination): the REPL
                    # namespace persists across turns, so a DataFrame computed
                    # in a PRIOR turn is still resolvable. Conversation history
                    # can nudge the model to re-declare such a stale variable
                    # (e.g. a previous turn's map DataFrame), which would leak
                    # the old data into this response. Accept only variables
                    # produced this turn or naming a registered base dataset.
                    allowed_multi, stale_multi = self._filter_declared_variables(
                        data_response.data_variables, response.tool_calls
                    )
                    if stale_multi:
                        self.logger.warning(
                            "Ignoring stale/cross-turn data_variables not produced "
                            "this turn: %s (declared=%s)",
                            stale_multi,
                            data_response.data_variables,
                        )
                    allowed_single = data_response.data_variable
                    if allowed_single:
                        _ok_single, _stale_single = self._filter_declared_variables(
                            [allowed_single], response.tool_calls
                        )
                        if _stale_single:
                            self.logger.warning(
                                "Ignoring stale/cross-turn data_variable '%s' not "
                                "produced this turn.",
                                allowed_single,
                            )
                        allowed_single = _ok_single[0] if _ok_single else None
                    # If data is large and stored as a variable, pull it from the Python tool context.
                    # Multi-dataset path: data_variables (plural) with 2+ entries takes priority.
                    if len(allowed_multi) >= 2:
                        missing_data_variables = await self._inject_multi_data_from_variables(
                            response,
                            allowed_multi,
                        )
                    elif len(allowed_multi) == 1:
                        # Single surviving entry — treat same as data_variable
                        if (
                            response.data is None
                            or (isinstance(response.data, pd.DataFrame) and response.data.empty)
                        ):
                            await self._inject_data_from_variable(
                                response,
                                allowed_multi[0],
                            )
                    elif allowed_single:
                        if (
                            response.data is None
                            or (isinstance(response.data, pd.DataFrame) and response.data.empty)
                        ):
                            await self._inject_data_from_variable(
                                response,
                                allowed_single,
                            )
                elif isinstance(response.output, dict) and response.output.get("data_variable"):
                    await self._inject_data_from_variable(
                        response,
                        response.output.get("data_variable")
                    )
                # If we still don't have data, try to infer the variable
                # name from the current turn's tool calls.  Strict-mode
                # inference only populates data when the turn produced an
                # unambiguous single DataFrame candidate — it never
                # overrides an explicit choice the LLM made, and it never
                # falls back to unrelated DataFrames from previous turns.
                #
                # We also run inference even when ``response.data`` is
                # already populated, to guard against structured-output
                # reformatters (notably Google's two-phase Gemini path)
                # that may fabricate or truncate rows when extracting
                # tabular data from a markdown preview. When the current
                # turn produced exactly one live DataFrame candidate whose
                # shape disagrees with ``response.data``, we trust the
                # tool-local DataFrame and override.
                inferred_var = self._extract_saved_variable_from_tool_calls(
                    response.tool_calls
                )
                if not inferred_var:
                    # FEAT-215: in STRUCTURED_CHART mode the prompt asks the
                    # agent to place the final chart rows in a conventionally
                    # named DataFrame (`chart_data`). Prefer it when present so a
                    # multi-DataFrame turn still resolves instead of refusing.
                    _prefer = (
                        ("chart_data", "chart_df")
                        if output_mode == OutputMode.STRUCTURED_CHART
                        else ()
                    )
                    inferred_var = self._infer_data_variable_from_tools(
                        response.tool_calls,
                        prefer_names=_prefer,
                    )

                response_data_is_empty = (
                    response.data is None
                    or (isinstance(response.data, pd.DataFrame) and response.data.empty)
                )

                if inferred_var and response_data_is_empty:
                    self.logger.info(
                        "Injecting data from inferred variable '%s' "
                        "(response.data was %s)",
                        inferred_var,
                        'None' if response.data is None else 'empty',
                    )
                    await self._inject_data_from_variable(response, inferred_var)
                elif (
                    inferred_var
                    and isinstance(response.data, pd.DataFrame)
                    # FEAT-215: STRUCTURED_CHART routes data via cfg.data inside
                    # StructuredChartRenderer. Skipping the override guard here
                    # prevents the raw tool-local DataFrame (all columns, many
                    # rows) from replacing the aggregated DataFrame the LLM
                    # declared via data_variable. The renderer is responsible for
                    # setting response.data = cfg.data after validating the JSON.
                    # FEAT-218: STRUCTURED_TABLE has the same ownership contract —
                    # the StructuredTableRenderer sets response.data = cfg.data;
                    # the override guard must not clobber it with the raw DataFrame.
                    # FEAT-221: STRUCTURED_MAP has the same data-owned contract —
                    # the StructuredMapRenderer builds the config from response.data
                    # (SpatialResult); the override guard must not clobber it.
                    and output_mode != OutputMode.STRUCTURED_CHART
                    and output_mode != OutputMode.STRUCTURED_TABLE
                    and output_mode != OutputMode.STRUCTURED_MAP
                ):
                    # Override guard: when the reformatter populated
                    # ``response.data`` but the live tool-local DataFrame
                    # disagrees on shape or columns, prefer the tool's
                    # version. This catches reformatter hallucinations
                    # (fabricated rows) and truncations (missing rows
                    # from a ``head()`` preview) without clobbering
                    # legitimate small results.
                    pandas_tool = self._get_python_pandas_tool()
                    live_df = (
                        pandas_tool.locals.get(inferred_var)
                        if pandas_tool and hasattr(pandas_tool, 'locals')
                        else None
                    )
                    if (
                        isinstance(live_df, pd.DataFrame)
                        and not live_df.empty
                        and (
                            len(live_df) != len(response.data)
                            or list(live_df.columns) != list(response.data.columns)
                        )
                    ):
                        self.logger.warning(
                            "Overriding response.data (%d rows, cols=%s) with "
                            "tool-local DataFrame '%s' (%d rows, cols=%s) — "
                            "likely reformatter hallucination or truncation.",
                            len(response.data),
                            list(response.data.columns),
                            inferred_var,
                            len(live_df),
                            list(live_df.columns),
                        )
                        await self._inject_data_from_variable(response, inferred_var)

                # Post-response validation: if the turn executed data
                # operations but the response has no ``data`` and no
                # resolvable ``data_variable``, log a prominent warning.
                # We deliberately do NOT silently inject an arbitrary
                # DataFrame here — the LLM is responsible for declaring
                # the result variable in its structured response.
                if (
                    (
                        response.data is None
                        or (isinstance(response.data, pd.DataFrame) and response.data.empty)
                    )
                    and self._turn_has_data_operations(response.tool_calls)
                ):
                    self.logger.warning(
                        "PandasAgent response has no `data` and no "
                        "resolvable `data_variable`, but the turn "
                        "executed data operations (%s). The LLM must "
                        "set `data_variable` in the structured response "
                        "to deliver the full DataFrame to the caller. "
                        "Hallucinated/missing data_variables: %s",
                        [
                            getattr(tc, 'name', '?')
                            for tc in (response.tool_calls or [])
                        ],
                        missing_data_variables or "none",
                    )

                # Auto-switch to STRUCTURED_MAP when the caller did not
                # explicitly pick a mode but the question phrases a map request
                # AND the result DataFrame carries the geographic signal to back
                # it. Source DataFrames cannot be inspected for this — the
                # DatasetManager exposes dozens of datasets, many with lat/lon,
                # so the only honest signal is the result the LLM produced.
                #
                # FEAT-224: the backend no longer renders a Folium map (deprecated
                # — that made the backend produce a frontend artifact). It now
                # converts the result rows into a ``SpatialResult`` and emits a
                # framework-agnostic STRUCTURED_MAP config the frontend renders.
                # Complements the pre-LLM Intent Router (which routes clearly
                # phrased map requests to STRUCTURED_MAP up front); this is the
                # data-aware fallback. Skipped — falls through to the default
                # output — when the rows lack real coordinates/geometry (e.g.
                # city/country names only), since a map cannot be built without
                # geocoding.
                if (
                    output_mode == OutputMode.DEFAULT
                    and isinstance(response.data, pd.DataFrame)
                    and _detect_map_intent(question, response.data)
                ):
                    spatial_result = self._spatial_result_from_dataframe(
                        response.data
                    )
                    if spatial_result is not None:
                        feature_count = sum(
                            len(lyr.features)
                            for lyr in spatial_result.layers.values()
                        )
                        self.logger.info(
                            "Map intent detected — emitting STRUCTURED_MAP "
                            "config (%d feature(s))",
                            feature_count,
                        )
                        output_mode = OutputMode.STRUCTURED_MAP
                        response.data = spatial_result
                    else:
                        self.logger.debug(
                            "Map intent matched but result rows lack "
                            "coordinates/geometry; skipping STRUCTURED_MAP "
                            "auto-switch."
                        )

                # FEAT-221 fallback: in explicit STRUCTURED_MAP mode the agent is
                # expected to call the spatial_filter tool, which returns a
                # SpatialResult routed to response.data above. When it instead
                # produces the result as a plain DataFrame via python_repl_pandas
                # (no SpatialResult in tool calls), response.data is still a
                # DataFrame and StructuredMapRenderer rejects it ("response.data
                # must be a SpatialResult"). Convert the result rows here — the
                # same df->SpatialResult path the DEFAULT auto-switch uses — so the
                # map renders instead of surfacing a renderer error to the user.
                if (
                    output_mode == OutputMode.STRUCTURED_MAP
                    and isinstance(response.data, pd.DataFrame)
                ):
                    spatial_result = self._spatial_result_from_dataframe(
                        response.data
                    )
                    if spatial_result is not None:
                        feature_count = sum(
                            len(lyr.features)
                            for lyr in spatial_result.layers.values()
                        )
                        self.logger.info(
                            "STRUCTURED_MAP: converted result DataFrame to "
                            "SpatialResult (%d feature(s)) — agent returned rows "
                            "instead of calling the spatial_filter tool.",
                            feature_count,
                        )
                        response.data = spatial_result
                    else:
                        self.logger.warning(
                            "STRUCTURED_MAP: result DataFrame has no resolvable "
                            "coordinates/geometry; map cannot be rendered."
                        )
                # Multi-layer fallback: when the agent produced SEVERAL DataFrames
                # (e.g. one layer per category to color them separately),
                # response.data is the list of DatasetResult dicts assembled by
                # _inject_multi_data_from_variables. Merge them into one
                # multi-layer SpatialResult so the renderer accepts it instead of
                # rejecting the list ("response.data must be a SpatialResult").
                elif (
                    output_mode == OutputMode.STRUCTURED_MAP
                    and isinstance(response.data, list)
                    and response.data
                ):
                    spatial_result = self._spatial_result_from_datasets(
                        response.data
                    )
                    if spatial_result is not None:
                        feature_count = sum(
                            len(lyr.features)
                            for lyr in spatial_result.layers.values()
                        )
                        self.logger.info(
                            "STRUCTURED_MAP: converted %d dataset(s) to a "
                            "multi-layer SpatialResult (%d layer(s), %d feature(s)) "
                            "— agent returned multiple DataFrames instead of "
                            "calling the spatial_filter tool.",
                            len(response.data),
                            len(spatial_result.layers),
                            feature_count,
                        )
                        response.data = spatial_result
                    else:
                        self.logger.warning(
                            "STRUCTURED_MAP: multi-dataset result has no resolvable "
                            "coordinates/geometry; map cannot be rendered."
                        )

                # FEAT-197: Post-loop branch for InfographicRenderResult.
                # isinstance check on the last tool result → mutate response in
                # place → return early, bypassing the formatter and
                # structured-output reformat.
                infographic_envelope = self._extract_last_infographic_result(
                    response.tool_calls
                )
                if infographic_envelope is not None:
                    await self._inject_multi_data_from_variables(
                        response, infographic_envelope.data_variables,
                    )
                    explanation = self._finalize_infographic_response(
                        response, infographic_envelope,
                    )
                    self.logger.info(
                        "InfographicRenderResult detected — bypassing formatter: "
                        "artifact_id=%s enhanced=%s explanation_chars=%d",
                        infographic_envelope.artifact_id,
                        infographic_envelope.enhanced,
                        len(explanation or ""),
                    )
                    return response   # skip formatter + structured reformat

                # Interactive artifact: same early-return pattern, no data_variables.
                interactive_envelope = self._extract_last_interactive_result(
                    response.tool_calls
                )
                if interactive_envelope is not None:
                    explanation = self._finalize_interactive_response(
                        response, interactive_envelope,
                    )
                    self.logger.info(
                        "InteractiveRenderResult detected — bypassing formatter: "
                        "artifact_id=%s enhanced=%s explanation_chars=%d",
                        interactive_envelope.artifact_id,
                        interactive_envelope.enhanced,
                        len(explanation or ""),
                    )
                    return response   # skip formatter + structured reformat

                format_kwargs = format_kwargs or {}
                if output_mode != OutputMode.DEFAULT:
                    if pandas_tool := self._get_python_pandas_tool():
                        # Provide the tool for rendering if needed
                        format_kwargs['pandas_tool'] = pandas_tool
                    else:
                        self.logger.warning(
                            "PythonPandasTool not available for non-default output mode rendering"
                        )

                # Safe format handling
                content = None
                wrapped = None
                format_error: Optional[str] = None

                # Check for empty response/content before formatting
                if response and (response.content or response.output):
                     if output_mode in [OutputMode.TELEGRAM, OutputMode.MSTEAMS]:
                         # Skip formatting for specific modes
                         response.output_mode = output_mode
                     else:
                         try:
                            content, wrapped = await self.formatter.format(
                                output_mode, response, **format_kwargs
                            )
                         except Exception as e:
                            self.logger.error("Error extracting content on formatter: %s", e)
                            format_error = str(e)
                            content = f"Error extracting content: {e}"
                            wrapped = content
                else:
                    self.logger.warning("Agent response was empty or None - skipping formatting")
                    content = "No response generated"
                    wrapped = content

                # Structured renderers signal failure by returning
                # (None, error_message) instead of raising. Publishing that
                # message via response.response would surface an internal
                # renderer error as the user-visible reply — degrade to
                # DEFAULT instead, preserving the plain-text answer the LLM
                # already produced in response.response.
                _structured_modes = (
                    OutputMode.STRUCTURED_CHART,
                    OutputMode.STRUCTURED_MAP,
                    OutputMode.STRUCTURED_TABLE,
                )
                if output_mode in _structured_modes and (
                    content is None or format_error is not None
                ):
                    self.logger.warning(
                        "%s renderer failed (%s) — falling back to DEFAULT "
                        "text response",
                        output_mode.value if hasattr(output_mode, "value") else output_mode,
                        format_error or wrapped,
                    )
                    output_mode = OutputMode.DEFAULT
                    response.output_mode = OutputMode.DEFAULT

                if output_mode != OutputMode.DEFAULT and output_mode not in [OutputMode.TELEGRAM, OutputMode.MSTEAMS]:
                    response.output = content
                    response.response = wrapped
                    response.output_mode = output_mode

                # TEXT mode: also strip markdown from the structured
                # output's explanation so consumers reading the
                # PandasAgentResponse directly get clean plain text.
                if output_mode == OutputMode.TEXT and data_response is not None:
                    if data_response.explanation:
                        from ..outputs.formats.text import markdown_to_plain
                        data_response.explanation = markdown_to_plain(
                            data_response.explanation
                        )

                # FEAT-224 (G1): Build the canonical artifacts[] envelope for the
                # three structured output modes.  A typed artifact entry is appended to
                # response.artifacts and response.artifact_id is set to the minted id.
                # response.output is kept as a deprecated mirror (G6) so existing
                # consumers keep working during the migration window.
                _STRUCTURED_ARTIFACT_TYPE = {
                    OutputMode.STRUCTURED_CHART: "chart",
                    OutputMode.STRUCTURED_MAP:   "map",
                    OutputMode.STRUCTURED_TABLE: "table",
                }
                _art_type = _STRUCTURED_ARTIFACT_TYPE.get(output_mode)
                if _art_type and isinstance(content, dict) and content:
                    # output_mode may arrive as a plain str (not an OutputMode
                    # enum) — mirror the hasattr guard used in the log line below.
                    _mode_str = (
                        output_mode.value
                        if hasattr(output_mode, "value")
                        else output_mode
                    )
                    _art_id = f"{_mode_str}-{uuid.uuid4().hex[:8]}"
                    # G2 safety net: the renderer already excludes rows, but strip
                    # any stray `data` key defensively so the envelope definition
                    # never carries rows (rows live in response.data only).
                    # `datasets` (STRUCTURED_MAP per-layer GeoJSON payloads) is
                    # also stripped to keep the stored artifact lean.
                    _definition = {
                        _k: _v for _k, _v in content.items()
                        if _k not in ("data", "datasets")
                    }
                    response.artifacts.append({
                        "type": _art_type,
                        "artifactId": _art_id,
                        "definition": _definition,   # camelCase config, data excluded
                    })
                    response.artifact_id = _art_id
                    self.logger.info(
                        "FEAT-224: structured artifact envelope minted — mode=%s artifact_id=%s",
                        output_mode.value if hasattr(output_mode, "value") else output_mode,
                        _art_id,
                    )

                if output_mode == OutputMode.MSTEAMS:
                     # Suppress code output for MS Teams to avoid clutter in Adaptive Card
                     response.code = None


                # Return the final AIMessage response — serialize response.data for JSON output.
                if isinstance(response.data, pd.DataFrame):
                    # Single DataFrame → list of record dicts (existing/backward-compat behavior)
                    response.data = response.data.to_dict(orient='records')
                elif isinstance(response.data, list):
                    # Already serialized — either:
                    # - Multi-dataset: list of DatasetResult dicts (from _inject_multi_data_from_variables)
                    # - Single dataset: list of record dicts (from a prior path)
                    # - STRUCTURED_MAP: list of per-layer payload dicts (post-renderer)
                    # Leave as-is in both cases — no double-serialization.
                    pass
                elif output_mode == OutputMode.STRUCTURED_MAP and response.data is not None:
                    # FEAT-221: STRUCTURED_MAP carries a SpatialResult in response.data
                    # before the renderer runs; after the renderer it's a list of payloads.
                    # Either way — leave as-is; the formatter/renderer handles conversion.
                    pass
                elif response.data is not None:
                    self.logger.warning(
                        "PandasAgent response.data unexpected type: %s",
                        type(response.data),
                    )
                answer_text = getattr(response, 'response', None) or response.content

                # Ensures markdown table syntax: add double newline before tables if missing
                if answer_text:
                    answer_text = self._repair_markdown_table(str(answer_text))

                    if hasattr(response, 'response'):
                        response.response = answer_text
                    if hasattr(response, 'content'):
                        # Ensure content is also updated if it matches response
                        if response.content == getattr(response, 'response', None) or not response.content:
                             response.content = answer_text

                await self.answer_memory.store_interaction(
                    response.turn_id,
                    question,
                    answer_text,
                )

                # Persist the turn into conversation_memory so subsequent
                # questions in the same session see prior context. Without
                # this, build_conversation_context() always sees an empty
                # history because PandasAgent reads from conversation_memory
                # but ChatStorage writes to a separate Redis namespace.
                if use_conversation_history and memory:
                    try:
                        turn = ConversationTurn(
                            turn_id=response.turn_id or turn_id,
                            user_id=user_id,
                            user_message=question,
                            assistant_response=answer_text or "",
                            tools_used=[
                                t.name for t in (response.tool_calls or [])
                            ],
                            metadata={
                                'model': getattr(response, 'model', None),
                                'response_time': getattr(response, 'response_time', None),
                                'usage': getattr(response, 'usage', None),
                                'finish_reason': getattr(response, 'finish_reason', None),
                            },
                        )
                        await memory.add_turn(user_id, session_id, turn)
                    except Exception as _save_exc:
                        self.logger.debug(
                            "Failed to persist conversation turn: %s",
                            _save_exc,
                        )

                # Post-response: episodic / mixin-provided hook
                _post_q, _post_resp = question, response
                _post_uid, _post_sid = user_id, session_id

                async def _fire_post_ask() -> None:
                    try:
                        await self._on_post_ask(
                            _post_q, _post_resp,
                            user_id=_post_uid,
                            session_id=_post_sid,
                        )
                    except Exception as _post_exc:
                        self.logger.debug(
                            "_on_post_ask hook failed: %s", _post_exc
                        )

                asyncio.create_task(_fire_post_ask())

                return response

        except Exception as e:
            self.logger.error(
                f"Error in PandasAgent.ask(): {e}"
            )
            # Return error response
            raise

    def add_dataframe(
        self,
        name: str,
        df: pd.DataFrame,
        metadata: Optional[Dict[str, Any]] = None,
        regenerate_guide: bool = True
    ) -> str:
        """Add a new DataFrame to the agent's context via DatasetManager.

        Args:
            name: Name for the DataFrame
            df: The pandas DataFrame to add
            metadata: Optional column metadata dictionary
            regenerate_guide: Deprecated (handled by DatasetManager)

        Returns:
            Success message
        """
        if not isinstance(df, pd.DataFrame):
            raise ValueError("Object must be a pandas DataFrame")

        self._dataset_manager.add_dataframe(
            name, df, metadata=metadata, is_active=True
        )
        self._sync_dataframes_from_dm()
        return f"DataFrame '{name}' added successfully"

    async def add_query(self, query: str) -> Dict[str, pd.DataFrame]:
        """Register a new QuerySource slug and load its resulting DataFrame."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string")

        query = query.strip()

        if self._queries is None:
            self._queries = [query]
        elif isinstance(self._queries, str):
            if self._queries == query:
                return {}
            self._queries = [self._queries, query]
        elif isinstance(self._queries, list):
            if query in self._queries:
                return {}
            self._queries.append(query)
        else:
            raise ValueError(
                "add_query only supports simple query slugs configured as strings or lists"
            )

        new_dataframes = await self._dataset_manager.load_data(
            query=[query],
            agent_name=self.chatbot_id,
            refresh=True
        )
        self._sync_dataframes_from_dm()
        return new_dataframes

    async def refresh_data(self, cache_expiration: int = None, **kwargs) -> Dict[str, pd.DataFrame]:
        """Re-run the configured queries and refresh metadata/tool state."""
        if not self._queries:
            raise ValueError("No queries configured to refresh data")

        cache_expiration = cache_expiration or self._cache_expiration
        await self._dataset_manager.load_data(
            query=self._queries,
            agent_name=self.chatbot_id,
            cache_expiration=cache_expiration,
            refresh=True,
        )
        self._sync_dataframes_from_dm()
        return self.dataframes

    def delete_dataframe(self, name: str, regenerate_guide: bool = True) -> str:
        """Remove a DataFrame from the agent's context via DatasetManager.

        Args:
            name: Name of the DataFrame to remove
            regenerate_guide: Deprecated (handled by DatasetManager)

        Returns:
            Success message
        """
        resolved = self._dataset_manager._resolve_name(name)
        self._dataset_manager.remove(resolved)
        self._sync_dataframes_from_dm()
        return f"DataFrame '{resolved}' removed successfully"

    def _get_python_pandas_tool(self) -> Optional[PythonPandasTool]:
        """Get the registered PythonPandasTool instance if available."""
        return next(
            (
                tool
                for tool in self.tool_manager.get_tools()
                if isinstance(tool, PythonPandasTool)
            ),
            None,
        )

    def _get_repl_locals(self) -> Dict[str, Any]:
        """Return the REPL local variables from PythonPandasTool.

        Used by DatasetManager.store_dataframe() to look up computed
        DataFrames by variable name.
        """
        if pandas_tool := self._get_python_pandas_tool():
            return pandas_tool.locals
        return {}

    def _turn_has_data_operations(self, tool_calls: Optional[List[Any]]) -> bool:
        """Return True if the turn invoked any data-producing tool.

        Used by post-response validation to decide whether to warn about
        missing ``data_variable``. Data operations are tool calls that
        load or compute DataFrames (``python_repl_pandas``,
        ``fetch_dataset``, ``database_query``).
        """
        if not tool_calls:
            return False
        data_tools = {
            'python_repl_pandas',
            'fetch_dataset',
            'database_query',
        }
        return any(
            (getattr(tc, 'name', '') or '') in data_tools
            for tc in tool_calls
        )

    def _extract_saved_variable_from_tool_calls(self, tool_calls: List[Any]) -> Optional[str]:
        """Extract a saved variable name from python_repl_pandas tool output."""
        if not tool_calls:
            return None
        for tc in reversed(tool_calls):
            try:
                result = getattr(tc, "result", None)
                if result is None:
                    continue
                text = result if isinstance(result, str) else str(result)
                match = re.search(
                    r"(?:VARIABLE SAVED|RESULT READY):\s*['\"]([^'\"]+)['\"]",
                    text
                )
                if match:
                    return match.group(1)
            except Exception:
                continue
        return None

    def _extract_spatial_result_from_tools(
        self, tool_calls: Optional[List[Any]]
    ) -> Optional[Any]:
        """Extract a ``SpatialResult`` from tool call results (FEAT-221).

        Iterates the current turn's tool calls in reverse order, looking for
        a result that is (or can be parsed as) a ``SpatialResult``.  Used by
        the ``STRUCTURED_MAP`` branch to route the per-dataset spatial result to
        ``response.data`` for the ``StructuredMapRenderer``.

        Args:
            tool_calls: The current turn's tool calls (may be None or empty).

        Returns:
            The **most recent** (last) ``SpatialResult`` found in tool call results,
            or ``None``.
        """
        if not tool_calls:
            return None

        try:
            from ..tools.dataset_manager.spatial.contracts import SpatialResult
        except ImportError:
            return None

        for tc in reversed(tool_calls):
            try:
                result = getattr(tc, "result", None)
                if result is None:
                    continue
                if isinstance(result, SpatialResult):
                    return result
                # Accept a dict with 'version' + 'layers' keys (serialized shape)
                if isinstance(result, dict) and "layers" in result and "version" in result:
                    try:
                        return SpatialResult(**result)
                    except Exception:
                        pass
            except Exception:
                continue
        return None

    def _extract_spatial_filter_spec_from_tools(
        self, tool_calls: Optional[List[Any]]
    ) -> Optional[Any]:
        """Extract a ``SpatialFilterSpec`` from tool call arguments (FEAT-221).

        Iterates the current turn's tool calls in reverse order, looking for a
        ``spatial_filter`` tool call whose ``arguments`` contain a ``spec`` key
        that is (or can be parsed as) a ``SpatialFilterSpec``.  Used by the
        ``STRUCTURED_MAP`` branch to populate ``response.spatial_filter_spec``
        so that ``StructuredMapRenderer._extract_map_query`` can build the
        ``MapQuery``.

        Args:
            tool_calls: The current turn's tool calls (may be None or empty).

        Returns:
            The **most recent** (last) ``SpatialFilterSpec`` found in tool call
            arguments, or ``None``.
        """
        if not tool_calls:
            return None

        try:
            from ..tools.dataset_manager.spatial.contracts import SpatialFilterSpec
        except ImportError:
            return None

        for tc in reversed(tool_calls):
            try:
                tc_name = getattr(tc, "name", "") or ""
                if tc_name != "spatial_filter":
                    continue
                args = getattr(tc, "arguments", {}) or {}
                spec_raw = args.get("spec") if isinstance(args, dict) else None
                if spec_raw is None:
                    continue
                if isinstance(spec_raw, SpatialFilterSpec):
                    return spec_raw
                if isinstance(spec_raw, dict):
                    try:
                        return SpatialFilterSpec(**spec_raw)
                    except Exception:
                        pass
            except Exception:
                continue
        return None

    def _current_turn_variable_names(self, tool_calls: Optional[List[Any]]) -> set:
        """Collect variable names produced by THIS turn's tool calls.

        Inspects the current turn's ``fetch_dataset`` results (the
        ``python_variable``/``dataset`` they loaded) and the assignment
        targets in ``python_repl_pandas`` code (parsed via AST). Returns a
        deduplicated set of names — order is irrelevant for membership tests.

        This is the basis for the anti-stale guard: the ``PythonPandasTool``
        REPL namespace persists across conversation turns, so a DataFrame
        computed in a PREVIOUS turn is still resolvable. Only names in the
        set returned here (or registered base datasets, see
        :meth:`_filter_declared_variables`) were actually produced now.
        """
        candidates: set = set()
        if not tool_calls:
            return candidates
        for tc in tool_calls:
            tc_name = getattr(tc, 'name', '') or ''
            if tc_name == 'fetch_dataset':
                result = getattr(tc, 'result', None)
                if result is not None:
                    data = result if isinstance(result, dict) else getattr(result, 'result', None)
                    if isinstance(data, dict):
                        var = data.get('python_variable') or data.get('dataset')
                        if var:
                            candidates.add(var)
            elif tc_name == 'python_repl_pandas':
                args = getattr(tc, 'arguments', {}) or {}
                code = args.get('code', '') if isinstance(args, dict) else ''
                if not code:
                    continue
                try:
                    tree = ast.parse(code)
                except SyntaxError:
                    continue
                for node in tree.body:
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                candidates.add(target.id)
        return candidates

    def _filter_declared_variables(
        self, declared: Optional[List[str]], tool_calls: Optional[List[Any]]
    ) -> tuple:
        """Reject LLM-declared result variables that leak across turns.

        The ``PythonPandasTool`` REPL namespace is shared across all turns of
        a conversation, so a DataFrame computed in a PRIOR turn (e.g. a map
        DataFrame from an earlier "show … on a map" question) stays live and
        resolvable. When conversation history nudges the model to re-declare
        such a stale variable in ``data_variable``/``data_variables``, the
        explicit injection paths would otherwise resolve it and leak the
        previous turn's data into this turn's response.

        A declared variable is accepted only when it is EITHER:
          * produced in the current turn's tool calls
            (see :meth:`_current_turn_variable_names`), OR
          * the name (or alias) of a registered base dataset — these are
            legitimately referenced without any code this turn, per the
            prompt's "data already in a loaded dataset variable" guidance.

        Args:
            declared: The variable names the LLM declared (may be ``None``).
            tool_calls: The current turn's tool calls.

        Returns:
            ``(allowed, rejected)`` — two lists preserving the declared order.
        """
        if not declared:
            return [], []
        current = self._current_turn_variable_names(tool_calls)
        base: set = set(self.dataframes.keys())
        try:
            alias_map = self._get_dataframe_alias_map()
            base |= set(alias_map.keys())
            base |= set(alias_map.values())
        except Exception:  # pragma: no cover - defensive
            pass
        allowed: List[str] = []
        rejected: List[str] = []
        for var in declared:
            if var in current or var in base:
                allowed.append(var)
            else:
                rejected.append(var)
        return allowed, rejected

    def _infer_data_variable_from_tools(
        self, tool_calls: List[Any], prefer_names: tuple = ()
    ) -> Optional[str]:
        """Strict-mode inference of a ``data_variable`` from the current turn.

        Returns a variable name **only** when the current turn's tool
        calls produced **exactly one** live, non-empty DataFrame candidate.
        Ambiguous cases (zero or multiple candidates) return ``None`` —
        the LLM MUST set ``data_variable`` explicitly in those cases.

        Rationale: the previous "last assignment wins" heuristic silently
        picked preview/intermediate DataFrames over the intended result
        (e.g. a ``preview = result.head(5)`` assignment after ``result``
        would shadow it). Strict single-candidate mode eliminates that
        class of false positive and forces the LLM to be explicit
        whenever its code produces more than one DataFrame.

        Only variables created in THIS turn's ``python_repl_pandas`` or
        ``fetch_dataset`` tool calls are considered. DataFrames left
        over from previous turns are never returned.

        Returns:
            Variable name when there is exactly one live DataFrame
            candidate in the current turn, ``None`` otherwise.
        """
        if not tool_calls:
            return None

        pandas_tool = self._get_python_pandas_tool()
        if not pandas_tool or not hasattr(pandas_tool, 'locals'):
            return None

        # Collect candidate variable names produced by this turn's tool
        # calls (deduplicated; order is irrelevant since we require uniqueness).
        candidates: set = self._current_turn_variable_names(tool_calls)

        # Keep only candidates that are currently live, non-empty DataFrames.
        live_dataframes = [
            var for var in candidates
            if var in pandas_tool.locals
            and isinstance(pandas_tool.locals[var], pd.DataFrame)
            and not pandas_tool.locals[var].empty
        ]

        # Convention-aware preference: when the caller passes conventional names
        # (e.g. the structured_chart `chart_data` DataFrame), prefer the first
        # one that is live this turn. This breaks a multi-candidate tie WITHOUT
        # relaxing the anti-stale guard — we still only ever return a DataFrame
        # created and live in the current turn's REPL context.
        for name in prefer_names:
            if name in live_dataframes:
                return name

        # Strict disambiguation: return only when there is exactly one.
        if len(live_dataframes) == 1:
            return live_dataframes[0]

        if len(live_dataframes) > 1:
            self.logger.debug(
                "Refusing to infer `data_variable`: this turn produced "
                "%d DataFrame candidates (%s). The LLM must set "
                "`data_variable` explicitly to disambiguate.",
                len(live_dataframes),
                sorted(live_dataframes),
            )

        return None

    def _repair_markdown_table(self, text: str) -> str:
        """
        Repairs malformed markdown tables in text, specifically:
        1.  Ensures double newlines before table starts.
        2.  Fixes flattened tables where header/separator/rows are on the same line.
        """
        if not text:
            return text

        # 1. Ensure double newline before table start
        # Look for: (non-newline) -> newline -> (start of table row)
        # We look for a line that looks like a table row: | ... |
        # But we must be careful not to match inline code/math pipes if possible.
        # A simple heuristic: starts with | and contains another | and ends with |

        # Heuristic for table row: starts with |, has content, ends with |
        # We capture the preceding char to check for newline

        # Fix: Text\n| Table | -> Text\n\n| Table |
        text = re.sub(r'([^\n])\n(\|.*\|.*\|)', r'\1\n\n\2', text)
        # Fix: Text | Table | (inline) -> Text\n\n| Table |
        # Ensure we don't split an existing row by ensuring the line does not start with pipe
        text = re.sub(r'(?m)^([^|].*?)\s+(\|.+?\|.+?\|)', r'\1\n\n\2', text)

        # 2. Fix flattened rows: "| Header | |---| | Row |"
        # 2a. Split Header and Separator (looks for "| |-|" or "| |:|")
        # Pattern: pipe, optional whitespace, pipe, dashes/colons, pipe
        text = re.sub(r'(\|)\s*(\|[:\s-]+\|)', r'\1\n\2', text)

        # 2b. Split Separator and First Row
        # Pattern: separator row, optional whitespace, pipe
        text = re.sub(r'(\|[:\s-]+\|)\s*(\|)', r'\1\n\2', text)

        # 2c. Split Body Rows (The missing part)
        # Fix: "| Row 1 | Val 1 | | Row 2 | Val 2 |" -> "| Row 1 | Val 1 |\n| Row 2 | Val 2 |"
        # We look for a pattern where a pipe ends a row, followed by a space (optional) and another pipe starting a new row.
        # But we must be careful not to split empty cells "| |".
        # Heuristic: "| |" is ambiguous, but usually if it follows a confirmed table structure (header+sep),
        # and has text around it, it's a split.
        # However, a safer bet is looking for "| | CapitalLetter".
        # Most of our metadata tables have Capitalized keys in the first column.

        # Regex: (| optional_space) (pipe) (space) (CapitalLetter)
        # We replace the space between pipes with a newline

        # Matches: "| | C" -> "|\n| C"
        # Matches: "| | R" -> "|\n| R"

        # This handles the specific case: "|...| | Column Count |" -> "|...|\n| Column Count |"
        text = re.sub(r'(\|)\s*(\|\s*[A-Z])', r'\1\n\2', text)

        return text

    async def _inject_data_from_variable(self, response: AIMessage, data_variable: str) -> None:
        """
        Inject a DataFrame from the PythonPandasTool execution context
        into response.data using the provided variable name.
        """
        if not data_variable:
            return
        pandas_tool = self._get_python_pandas_tool()
        if not pandas_tool:
            self.logger.warning("PythonPandasTool not available to inject data from variable")
            return
        df = None
        # Check locals from the Python REPL tool context
        if hasattr(pandas_tool, "locals"):
            # 1. Check top-level locals
            if data_variable in pandas_tool.locals:
                df = pandas_tool.locals.get(data_variable)

            # 2. Check inside execution_results (common pattern for LLM outputs)
            if df is None and 'execution_results' in pandas_tool.locals:
                exec_results = pandas_tool.locals['execution_results']
                if isinstance(exec_results, dict) and data_variable in exec_results:
                    df = exec_results.get(data_variable)

        # Do NOT fall back to self.dataframes — those contain initial/stale
        # data from previous loads and can cause cross-turn contamination.

        if isinstance(df, pd.DataFrame):
            # Ensure columns are strings for JSON serialization compatibility
            # (Fixes ParserError when columns are Timestamps)
            df = df.copy() # Avoid modifying cached dataframe

            # Reset index to ensure index columns (often grouping keys) are included in output
            # This is critical for MultiIndex dataframes where meaningful labels are in the index.
            df.reset_index(inplace=True)

            df.columns = df.columns.astype(str)
            response.data = df
        else:
            self.logger.warning(
                f"Data variable '{data_variable}' not found or is not a DataFrame"
            )

    async def _inject_multi_data_from_variables(
        self,
        response: AIMessage,
        data_variables: List[str],
    ) -> List[str]:
        """Inject multiple DataFrames from PythonPandasTool context into response.data.

        When the LLM declares multiple result variables via ``data_variables``,
        this method resolves each variable, builds a :class:`DatasetResult` entry
        per DataFrame, and sets ``response.data`` to the assembled list.

        Variables that are not found or are not DataFrames are skipped with a
        warning; the remaining valid datasets are still returned. When NO
        variable resolves, ``response.data`` is reset to ``None`` so the
        downstream inferred-variable fallback can take over.

        Args:
            response: The :class:`~parrot.models.responses.AIMessage` whose
                ``data`` field will be populated.
            data_variables: Ordered list of Python variable names to resolve
                from the ``PythonPandasTool`` execution context.

        Returns:
            List of variable names that could not be resolved (hallucinated
            or never assigned). Empty when every variable was found.
        """
        pandas_tool = self._get_python_pandas_tool()
        if not pandas_tool:
            self.logger.warning(
                "PythonPandasTool not available for multi-dataset injection"
            )
            return list(data_variables)

        results: List[Dict[str, Any]] = []
        missing: List[str] = []
        for var_name in data_variables:
            df = None
            if hasattr(pandas_tool, "locals"):
                # 1. Check top-level locals
                if var_name in pandas_tool.locals:
                    df = pandas_tool.locals.get(var_name)

                # 2. Check inside execution_results (common LLM output pattern)
                if df is None and "execution_results" in pandas_tool.locals:
                    exec_results = pandas_tool.locals["execution_results"]
                    if isinstance(exec_results, dict) and var_name in exec_results:
                        df = exec_results.get(var_name)

            if isinstance(df, pd.DataFrame):
                df = df.copy()
                df.reset_index(inplace=True)
                df.columns = df.columns.astype(str)
                results.append(
                    DatasetResult(
                        name=var_name,
                        variable=var_name,
                        data=df.to_dict(orient="records"),
                        shape=(len(df), df.shape[1]),
                        columns=df.columns.tolist(),
                    ).model_dump()
                )
            else:
                missing.append(var_name)
                self.logger.warning(
                    "Multi-dataset injection: variable '%s' not found or not a DataFrame "
                    "— skipping.",
                    var_name,
                )

        if results:
            response.data = results
        else:
            # Hallucinated/missing variables only — clear the empty-DataFrame
            # stub from PandasAgentResponse.to_dataframe() so the downstream
            # inferred-variable fallback can populate response.data instead
            # of seeing a "non-empty" stub.
            response.data = None
            self.logger.warning(
                "Multi-dataset injection: none of the variables in %s could be resolved.",
                data_variables,
            )

        return missing

    def _get_prophet_tool(self) -> Optional[ProphetForecastTool]:
        """Get the ProphetForecastTool instance if registered."""
        return next(
            (
                tool
                for tool in self.tool_manager.get_tools()
                if isinstance(tool, ProphetForecastTool)
            ),
            None,
        )

    def _get_dataframe_alias_map(self) -> Dict[str, str]:
        """Return mapping of dataframe names to standardized dfN aliases."""
        if self._dataset_manager:
            return self._dataset_manager._get_alias_map()
        return {
            name: f"df{i + 1}"
            for i, name in enumerate(self.dataframes.keys())
        }

    def _sync_prophet_tool(self) -> None:
        """Synchronize ProphetForecastTool with current dataframes and aliases."""

        if prophet_tool := self._get_prophet_tool():
            prophet_tool.update_context(
                dataframes=self.dataframes,
                alias_map=self._get_dataframe_alias_map(),
            )
            self.logger.debug(
                f"Synced ProphetForecastTool with {len(self.dataframes)} DataFrames"
            )
        else:
            self.logger.warning(
                "ProphetForecastTool not found - skipping sync"
            )

    def list_dataframes(self) -> Dict[str, Dict[str, Any]]:
        """
        Get a list of all DataFrames loaded in the agent's context.

        Returns:
            Dictionary mapping standardized keys (df1, df2, etc.) to DataFrame info:
            - original_name: The original name of the DataFrame
            - standardized_key: The standardized key (df1, df2, etc.)
            - shape: Tuple of (rows, columns)
            - columns: List of column names
            - memory_usage_mb: Memory usage in megabytes
            - null_count: Total number of null values

        Example:
            >>> agent.list_dataframes()
            {
                'df1': {
                    'original_name': 'sales_data',
                    'standardized_key': 'df1',
                    'shape': (1000, 5),
                    'columns': ['date', 'product', 'quantity', 'price', 'region'],
                    'memory_usage_mb': 0.04,
                    'null_count': 12
                }
            }
        """
        result = {}
        for i, (df_name, df) in enumerate(self.dataframes.items()):
            df_key = f"df{i + 1}"
            result[df_key] = {
                'original_name': df_name,
                'standardized_key': df_key,
                'shape': df.shape,
                'columns': df.columns.tolist(),
                'memory_usage_mb': df.memory_usage(deep=True).sum() / 1024 / 1024,
                'null_count': df.isnull().sum().sum(),
            }
        return result

    def default_backstory(self) -> str:
        """Return default backstory for the agent."""
        return (
            "You are a helpful data analysis assistant. "
            "You provide accurate insights and clear visualizations "
            "to help users understand their data."
        )

    # ===== Data Loading Methods =====

    # ===== Data Loading Methods =====

    # Note: call_qs and call_multiquery moved to DatasetManager

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
            if path.suffix.lower() in {'.csv', '.txt'}:
                df = pd.read_csv(path, **kwargs)
                dfs[path.stem] = df

            elif path.suffix.lower() in {'.xlsx', '.xls'}:
                # Load all sheets
                excel_file = pd.ExcelFile(path)
                for sheet_name in excel_file.sheet_names:
                    df = pd.read_excel(path, sheet_name=sheet_name, **kwargs)
                    dfs[f"{path.stem}_{sheet_name}"] = df

            else:
                raise ValueError(
                    f"Unsupported file type: {path.suffix}"
                )

        return dfs

    # Note: gen_data and caching methods moved to DatasetManager

---
id: F001
query_id: Q001+Q005
type: grep+read
intent: Locate PandasAgent and understand its constructor/datasource contract.
executed_at: 2026-09-01T00:00:00Z
depth: 0
---

# F001 — PandasAgent lives in parrot/bots/data.py and already speaks QuerySource slugs

## Summary

`PandasAgent(IntentRouterMixin, BasicAgent)` is defined at `packages/ai-parrot/src/parrot/bots/data.py:379` (file is 2839 lines). Its constructor accepts `df=` (frames), `query=` (**QuerySource slugs**, list or dict), `output_routing=` (FEAT-224 embedding router that auto-selects STRUCTURED_CHART/TABLE/MAP), and always creates an internal `DatasetManager` (`self._dataset_manager`). Default tools: `PythonPandasTool`, `ProphetForecastTool`, `ToJsonTool`, plus all `DatasetManager` tools. `configure(queries=...)` loads slug data; `add_query(slug)` registers a slug at runtime; `refresh_data()` re-fetches (`data.py:2136-2174`).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/data.py`
  lines: 379-491
  symbol: `PandasAgent.__init__`
  excerpt: |
    def __init__(self, name="Pandas Agent", enable_scenarios=False, tools=None,
                 system_prompt=None, df=None, query=None, capabilities=None,
                 generate_eda=True, cache_expiration=24, temperature=0.0,
                 max_iterations=None, output_routing=False,
                 output_routing_config=None, **kwargs):
        ...
        self._dataset_manager = DatasetManager()
        self._dataset_manager.set_on_change(self._sync_dataframes_from_dm)

- path: `packages/ai-parrot/src/parrot/bots/data.py`
  lines: 494-560
  symbol: `attach_dm` / `_sync_dataframes_from_dm`
  excerpt: |
    def attach_dm(self, dm: DatasetManager) -> None: ...
    def _sync_dataframes_from_dm(self) -> None:  # syncs active datasets to REPL

- path: `packages/ai-parrot/src/parrot/bots/data.py`
  lines: 2136-2174
  symbol: `add_query` / `refresh_data`
  excerpt: |
    async def add_query(self, query: str) -> Dict[str, pd.DataFrame]:
        """Register a new QuerySource slug and load its resulting DataFrame."""
    async def refresh_data(self, cache_expiration=None, **kwargs) -> Dict[str, pd.DataFrame]:

- path: `packages/ai-parrot/src/parrot/bots/data.py`
  lines: 874-923
  symbol: `configure`
  excerpt: |
    async def configure(...):  # "queries: Optional query slugs to load data from"

## Notes

The ticket's "DatasSourceManager" is almost certainly `DatasetManager` (see F002). `output_routing=True` gives the A2UI structured-chart/map auto-selection the /widget skill wants.

---
type: Wiki Entity
title: PandasAgent
id: class:parrot.bots.data.PandasAgent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A specialized agent for data analysis using pandas DataFrames.
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
- concept: class:parrot.bots.mixins.intent_router.IntentRouterMixin
  rel: extends
---

# PandasAgent

Defined in [`parrot.bots.data`](../summaries/mod:parrot.bots.data.md).

```python
class PandasAgent(IntentRouterMixin, BasicAgent)
```

A specialized agent for data analysis using pandas DataFrames.

Features:
- Multi-dataframe support
- Redis caching for data persistence
- Automatic EDA (Exploratory Data Analysis)
- DataFrame metadata generation
- Query source integration
- File loading (CSV, Excel)

## Methods

- `def attach_dm(self, dm: DatasetManager) -> None` — Attach a DatasetManager to this agent.
- `async def create_system_prompt(self, **kwargs)` — Override to inject dataframe_schemas for the layer path.
- `async def configure(self, app: web.Application=None, queries: Union[List[str], dict]=None) -> None` — Configure the PandasAgent.
- `async def invoke(self, question: str, response_model: type[BaseModel] | None=None, **kwargs) -> AgentResponse` — Ask the agent a question about the data.
- `async def ask(self, question: str, session_id: Optional[str]=None, user_id: Optional[str]=None, use_conversation_history: bool=True, memory: Optional[Any]=None, ctx: Optional[Any]=None, structured_output: Optional[Any]=None, output_mode: Any=None, format_kwargs: dict=None, return_structured: bool=True, **kwargs) -> AIMessage` — Override ask() method to ensure PythonPandasTool is always used.
- `def add_dataframe(self, name: str, df: pd.DataFrame, metadata: Optional[Dict[str, Any]]=None, regenerate_guide: bool=True) -> str` — Add a new DataFrame to the agent's context via DatasetManager.
- `async def add_query(self, query: str) -> Dict[str, pd.DataFrame]` — Register a new QuerySource slug and load its resulting DataFrame.
- `async def refresh_data(self, cache_expiration: int=None, **kwargs) -> Dict[str, pd.DataFrame]` — Re-run the configured queries and refresh metadata/tool state.
- `def delete_dataframe(self, name: str, regenerate_guide: bool=True) -> str` — Remove a DataFrame from the agent's context via DatasetManager.
- `def list_dataframes(self) -> Dict[str, Dict[str, Any]]` — Get a list of all DataFrames loaded in the agent's context.
- `def default_backstory(self) -> str` — Return default backstory for the agent.
- `async def load_from_files(cls, files: Union[str, Path, List[Union[str, Path]]], **kwargs) -> Dict[str, pd.DataFrame]` — Load DataFrames from CSV or Excel files.

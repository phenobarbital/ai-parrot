---
type: Wiki Entity
title: PythonPandasTool
id: class:parrot.tools.pythonpandas.PythonPandasTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Python Pandas Tool with pre-loaded DataFrames and enhanced data science capabilities.
relates_to:
- concept: class:parrot.tools.pythonrepl.PythonREPLTool
  rel: extends
---

# PythonPandasTool

Defined in [`parrot.tools.pythonpandas`](../summaries/mod:parrot.tools.pythonpandas.md).

```python
class PythonPandasTool(PythonREPLTool)
```

Python Pandas Tool with pre-loaded DataFrames and enhanced data science capabilities.

Extends PythonREPLTool to provide:
- Automatic DataFrame binding with ORIGINAL names as primary identifiers
- Standardized aliases (df1, df2, etc.) as convenience references
- Integration with DatasetManager for catalog/metadata operations
- Enhanced data exploration utilities
- Safe DataFrame operations

All metadata, EDA, column categorization, and data quality
responsibilities are delegated to DatasetManager when available.

## Methods

- `def create_session_clone(self, dataset_manager: Optional['DatasetManager']=None) -> 'PythonPandasTool'` — Create a lightweight, session-isolated clone of this tool.
- `def dataset_manager(self) -> Optional['DatasetManager']` — Access the DatasetManager instance.
- `def dataset_manager(self, manager: 'DatasetManager') -> None` — Set or replace the DatasetManager and sync dataframes.
- `def df_guide(self) -> str` — Get the DataFrame guide from DatasetManager or cached value.
- `def df_guide(self, value: str) -> None` — Set guide cache for standalone mode.
- `def sync_from_manager(self) -> None` — Synchronize execution environment from DatasetManager's active datasets.
- `def add_dataframe(self, name: str, df: pd.DataFrame) -> str` — Add a new DataFrame to the execution environment.
- `def remove_dataframe(self, name: str) -> str` — Remove a DataFrame from the execution environment.
- `def register_dataframes(self, dataframes: Dict[str, pd.DataFrame], alias_map: Optional[Dict[str, str]]=None) -> None` — Register DataFrames to the tool execution environment.
- `def clear_dataframes(self) -> None` — Clear all registered DataFrames from the execution environment.
- `def get_dataframe_guide(self) -> str` — Get the current DataFrame guide.
- `def list_dataframes(self) -> Dict[str, Dict[str, Any]]` — List all available DataFrames with their info.
- `def get_dataframe_summary(self, df_key: str) -> Dict[str, Any]` — Get detailed summary for a specific DataFrame.
- `def get_environment_info(self) -> Dict[str, Any]` — Override to include DataFrame information.
- `def get_execution_state(self) -> Dict[str, Any]` — Extract current execution state for use by formatters.
- `def clear_execution_results(self)` — Clear execution_results dictionary for new queries.

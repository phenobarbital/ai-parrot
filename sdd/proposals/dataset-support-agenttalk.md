# Add support for DatasetManager to AgentTalk Handler


## Abstract
`DatasetManager` at `parrot/tools/dataset_manager.py` is a  Dataset Catalog and toolkit for managing DataFrames and Queries.
is like a ToolManager but for data (queries, dataframes).

Based on documentation:

As a Toolkit:
- Exposes tools to the LLM: list_available(), get_metadata(), get_active(), etc.

As a Catalog:
- Stores datasets (DataFrames or query slugs)
- Manages active/inactive state (defaults to active)
- Provides dataframes to PythonPandasTool on demand
- Replaces MetadataTool with get_metadata() functionality

As a Metadata Engine:
- Column type categorization (integer, float, datetime, categorical_text, text, etc.)
- Per-column metrics guide generation
- Comprehensive DataFrame info (shape, dtypes, memory, nulls, column types)
- Data quality checks (NaN detection, completeness, duplicates)

PythonPandasTool can receive a `DatasetManager` instance throug `dataset_manager` argument.

Also, `PandasAgent` can receive dataframes and be added into the internal dataset_manager:
```
# Initialize DatasetManager (always create one)
self._dataset_manager = DatasetManager()
```

## Motivation

Allow to user override, enable, disable datasets at `DatasetManager` from AgentTalk handler.
- Users can register own "DatasetManager" instance (exactly like own ToolManager instance) and register in the user's session.
User then can interact, add more datasets, enable or disable datasets, upload Excel files (converted as dataframes) and added into his own `DatasetManager`.
- User's `DatasetManager` will replace the existing `DatasetManager` in Agent exactly like we do for `ToolManager` using the method `attach_dm` of PandasAgent.

## Scope

- moving the current `_configure_tool_manager` (and related methods) to a new class `UserObjectsHandler` (to reduce the complexity of methods of AgentTalk), focused on managing ToolManager and DatasetManager instances.
- add a new `_configure_dataset_manager` with the same philosophy of configure_tool_manager (copy the existing datasetmanager of Agent and creates a new DatasetManager copying inside all datasets), saving this new dataset manager into user session.
- New handler `DatasetManagerHandler` (inherit from BaseView) for reading the dataset manager from user's session, return the existing datasets inside, dataset description (number of rows, columns) and a PATCH method to allow enable or disable datasets (using `activate` and `deactivate` methods), PUT method for upload new excel files, convert into pandas dataframes and adding those into the Dataset Manager.
- POST method to add new database queries (SQL) or new query slugs into dataset manager.
- a DELETE method for permanently delete a dataset from DatasetManager's instance.
- in GET option, a flag (passed in querystring) called `eda` to execute `get_metadata` with "include_eda=True".

## Architectural decisions

- Move from AgentTalk the configuration of ToolManager and DatasetManager to own Class `UserObjectsHandler` exposed via `/api/v1/agents/user_objects`
- AgentTalk only check if there are tool_manager or dataset_manager instances for current agent on user's session.
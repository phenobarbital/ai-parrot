---
type: Wiki Entity
title: WorkingMemoryToolkit
id: class:parrot.tools.working_memory.tool.WorkingMemoryToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Intermediate result store for long-running analytical operations.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# WorkingMemoryToolkit

Defined in [`parrot.tools.working_memory.tool`](../summaries/mod:parrot.tools.working_memory.tool.md).

```python
class WorkingMemoryToolkit(AbstractToolkit)
```

Intermediate result store for long-running analytical operations.

Every public async method is automatically exposed as an agent tool
by AbstractToolkit. Pydantic models validate inputs via @tool_schema.

The agent NEVER sees raw DataFrames — only compact summaries
(shape, dtypes, stats, small preview). Generic (non-DataFrame) entries
are also summarised in a type-aware manner.

An optional AnswerMemory bridge allows the agent to save and recall
Q&A interactions directly through the toolkit. Auto-injected by
BasicAgent.configure() when a WorkingMemoryToolkit is found registered.

Methods (agent-callable tools)
──────────────────────────────
store              : Store a DataFrame directly
store_result       : Store any Python object (text, dict, list, bytes, …)
drop_stored        : Remove a stored entry (any type)
get_stored         : Get summary of a stored DataFrame
get_result         : Get summary of a stored generic entry
search_stored      : Find entries by key/description substring or type
list_stored        : List all stored entries (all types)
compute_and_store  : Execute DSL operation and store result
merge_stored       : Merge multiple stored DataFrames into one
summarize_stored   : Aggregate multiple stored DataFrames
import_from_tool   : Bridge — import from PandasTool/REPLTool
list_tool_dataframes : Discover DataFrames in other tools
save_interaction   : Save Q&A pair to AnswerMemory (bridge)
recall_interaction : Recall Q&A pair from AnswerMemory (bridge)

## Methods

- `async def store(self, key: str, df: pd.DataFrame, description: str='', turn_id: Optional[str]=None) -> dict` — Store a DataFrame directly into working memory.
- `async def store_result(self, key: str, data: Any, data_type: str='auto', description: str='', metadata: Optional[dict]=None, turn_id: Optional[str]=None) -> dict` — Store any intermediate result (text, dict, list, AIMessage, bytes, etc.)
- `async def drop_stored(self, key: str) -> dict` — Remove a stored entry (DataFrame or generic) from working memory.
- `async def get_stored(self, key: str, max_rows: Optional[int]=None, max_cols: Optional[int]=None) -> dict` — Get a compact summary of a stored DataFrame (shape, stats, preview). The LLM uses this to inspect intermediate results without loading raw data.
- `async def get_result(self, key: str, max_length: int=500, include_raw: bool=False) -> dict` — Retrieve a stored generic result with a type-aware compact summary.
- `async def search_stored(self, query: str, entry_type: Optional[str]=None) -> dict` — Search stored entries by key or description substring, optionally filtered by type.
- `async def list_stored(self, turn_id: Optional[str]=None) -> dict` — List all entries in working memory with compact summaries (all types).
- `async def compute_and_store(self, spec: Union[OperationSpecInput, dict], turn_id: Optional[str]=None, description: str='') -> dict` — Execute a declarative data operation (DSL) and store the result.
- `async def merge_stored(self, keys: list[str], store_as: str, merge_on: Optional[str]=None, merge_how: str='outer', turn_id: Optional[str]=None) -> dict` — Merge multiple stored DataFrames into one. If merge_on is provided,
- `async def summarize_stored(self, keys: list[str], store_as: str, agg_rules: dict[str, str], group_by: Optional[list[str]]=None, merge_on: Optional[str]=None, turn_id: Optional[str]=None) -> dict` — Merge + aggregate stored DataFrames in one step.
- `async def import_from_tool(self, tool_name: str, variable_name: str, store_as: str, description: str='', turn_id: Optional[str]=None) -> dict` — Import a DataFrame from another tool's namespace (PythonPandasTool,
- `async def list_tool_dataframes(self, tool_name: Optional[str]=None) -> dict` — Discover DataFrames available in other registered tools'
- `async def save_interaction(self, turn_id: str, question: str, answer: str) -> dict` — Save a question/answer pair to the agent's AnswerMemory, keyed by turn_id.
- `async def recall_interaction(self, turn_id: Optional[str]=None, query: Optional[str]=None, import_as: Optional[str]=None) -> dict` — Recall a previous Q&A interaction from AnswerMemory.

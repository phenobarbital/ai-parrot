---
id: F008
queries: [user-followup-on-multi-dataset]
confidence: high
---

# Multi-dataset return ALREADY works for PandasAgent/DatabaseAgent via `data_variables`

Updates the earlier F006 finding ("AIMessage carries `artifacts` — no
first-class `datasets` field"). Multi-dataset envelope **does** exist —
it just piggybacks on `response.data: Any` and only fires for
PandasAgent / DatabaseAgent paths.

## The contract

`PandasAgentResponse` (bots/data.py:141-204) is the structured output the
LLM is asked to emit when `PandasAgent.ask()` runs with
`structured_output=PandasAgentResponse`. Three mutually-related slots:

- `data: Optional[PandasTable]` — singular embedded table
- `data_variable: Optional[str]` — name of ONE Python variable holding a
  DataFrame in the `PythonPandasTool` execution context
- `data_variables: Optional[List[str]]` — **list of variable names** for
  multi-dataset responses (line 196-204)

`DatasetResult` (bots/data.py:93-107) is the per-entry schema for the
multi-dataset payload:

```python
class DatasetResult(BaseModel):
    name: str
    variable: str
    data: List[Dict[str, Any]]    # records
    shape: Tuple[int, int]
    columns: List[str]
```

## The resolution path

In `PandasAgent.ask()` (`bots/data.py:1378-1414`), after the LLM returns:

```
if data_response.data_variables and len(data_response.data_variables) >= 2:
    missing = await self._inject_multi_data_from_variables(
        response, data_response.data_variables)
elif data_response.data_variables and len(...) == 1:
    # same path as singular
elif data_response.data_variable:
    # singular
```

`_inject_multi_data_from_variables` (`bots/data.py:2017-2099`) for each
variable name:
1. Reads `pandas_tool.locals[var_name]` (or
   `pandas_tool.locals["execution_results"][var_name]` — line 2059-2063).
2. If it is a `pd.DataFrame`, builds a `DatasetResult.model_dump()` and
   appends to `results`.
3. Sets `response.data = results` (line 2087) — the list of
   DatasetResult dicts.
4. Returns the list of unresolved names; line 1504-1513 logs a
   prominent warning if all are hallucinated.

## On-the-wire shape

`AgentTalk._format_response` (`handlers/agent.py:2168-2203`) puts
`response.data` directly in the JSON envelope: `"data": response.data`.
No double-serialization (`bots/data.py:1599-1607` confirms list values
are passed through verbatim).

So the frontend receives, in the `data` key of the JSON response:
- A `PandasTable` dict `{columns, rows}` for singular results, or
- A `List[DatasetResult]` for multi-dataset results.

## Caveats relevant to FEAT-194

- **LLM opt-in**: only fires when the LLM correctly sets `data_variables`
  with ≥2 entries. The hallucinated/missing variable warning at
  `bots/data.py:1500-1513` exists precisely because LLMs forget.
- **Agent-class specific**: PandasAgent has it; DatabaseAgent has the same
  `data_variables` field on its response (database/models.py:294). A
  generic `Agent` calling SQL via tool does NOT auto-populate
  `response.data` with multi-datasets.
- **Type erasure**: `AIMessage.data` is `Any` (no formal `datasets: List
  [DatasetResult]` field on AIMessage). Frontends must inspect to know
  whether they got 1 vs. N tables. This is a viable target for FEAT-194
  to formalise — promote `DatasetResult` to a typed envelope slot.

## Citations
- packages/ai-parrot/src/parrot/bots/data.py:93-107 — DatasetResult model
- packages/ai-parrot/src/parrot/bots/data.py:141-204 — PandasAgentResponse
  (data, data_variable, data_variables)
- packages/ai-parrot/src/parrot/bots/data.py:1389-1414 — multi-dataset
  routing in PandasAgent.ask()
- packages/ai-parrot/src/parrot/bots/data.py:1500-1513 — "Hallucinated/
  missing data_variables" warning
- packages/ai-parrot/src/parrot/bots/data.py:1599-1607 — serialization
  pass-through for List[DatasetResult]
- packages/ai-parrot/src/parrot/bots/data.py:2017-2099 —
  `_inject_multi_data_from_variables`
- packages/ai-parrot/src/parrot/bots/database/models.py:294 —
  DatabaseAgent's mirror of `data_variables`
- packages/ai-parrot/src/parrot/handlers/agent.py:2168-2203 — envelope
  serialization in AgentTalk._format_response

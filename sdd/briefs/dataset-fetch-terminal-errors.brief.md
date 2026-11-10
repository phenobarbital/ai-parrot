---
kind: brief
slug: dataset-fetch-terminal-errors
key: dataset-fetch-terminal-errors
base_branch: dev
source:
  type: text
  ref: "PandasAgent log 2026-11-10 23:15:41 — fetch_dataset 'financial_projection_detail'"
  url: null
jira_issue_key: null
ledger_issue: null
created: '2026-11-11'
---

# Brief: fetch_dataset reports failures as success and invites retries on unfixable errors

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

A `PandasAgent` running on `GoogleGenAIClient` spent four tool calls on
`fetch_dataset('financial_projection_detail')` before giving up. The dataset is a
`TableSource` whose table does not exist in the database, so no SQL the model writes can
ever succeed. Source log (verbatim):

```
[ERROR] 2026-11-10 23:15:41,845 parrot.tools.dataset_manager.tool(tool.py:3590) :: fetch_dataset 'financial_projection_detail' failed: TableSource query failed on 'troc.financial_projection_detail': Sentence Error: relation "troc.financial_projection_detail" does not exist
[INFO] 2026-11-10 23:15:41,845 dataset_fetch_dataset.Tool(abstract.py:1104) :: Tool dataset_fetch_dataset executed successfully
```

Two things are wrong for every agent that uses `DatasetManager`:

1. A failed fetch is logged, traced and returned as a **successful** tool call.
2. The model is told to rewrite its SQL for a failure it cannot fix, so it retries.

## Root cause

`DatasetManager.fetch_dataset` catches every exception from `materialize()` and returns a
bare `{"error": ..., "hint": ...}` dict
(`packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:3589-3625`). That dict has no
`status`/`result` keys, so `AbstractTool.execute` does not take the ToolResult-shaped-dict
branch (`packages/ai-parrot/src/parrot/tools/abstract.py:1090`) and falls into the final
`else`, which logs "executed successfully" and wraps the dict in
`ToolResult(status="success")` (`abstract.py:1103-1109`). The failure is therefore a
success for logging, `AfterToolCallEvent`, and the client.

Independently, the `TableSource` branch of the handler builds one hint for **every**
exception: "Your SQL query failed: … Do NOT fall back to SELECT * — fix the SQL instead.
The table MUST be referenced as '<table>' in your query", followed by a column list and a
dialect hint (`tool.py:3593-3614`). For a missing relation that *is* the registered table,
a permission error, or a connection failure, that text instructs the model to retry
something only an operator can fix.

Nothing remembers the failure either: `fetch_dataset` forces `force_refresh = True` for
table sources (`tool.py:3580`), so each retry is a new database round trip.

## Research findings

- **How an error reaches the model.** A `ToolResult(status="error")` makes
  `ToolManager.execute_tool` raise `ValueError(result.error)` (`tools/manager.py:2250`);
  `AbstractClient._execute_tool` does the same (`clients/base.py:1748`). The Google client
  collects it with `gather(return_exceptions=True)` and stores `tc.error = str(result)`
  (`packages/ai-parrot-client-google/src/parrot/clients/google/client.py:2301`). Only the
  **error string** survives — `ToolResult.metadata` is dropped. A machine-readable
  `retryable` flag alone would never reach the model; the instruction must be in the text.
- **A ToolResult-shaped dict is already a supported return.** `abstract.py:1090-1100`
  turns `{"status": ..., "result": ...}` dicts into a `ToolResult`. Returning that shape
  from `fetch_dataset` makes the failure real on the tool path without touching
  `abstract.py`.
- **Direct Python callers rely on the dict.** `infographic_recipes/runner.py:468-479`
  checks `result.get("error")`; `bots/mixins/infographic_authoring.py:245` calls
  `fetch_dataset` directly too. Raising from `fetch_dataset` would change their contract;
  keeping a dict with an `"error"` key does not.
- **Other early-return error dicts in `fetch_dataset`** (dataset not found at
  `tool.py:3393-3399`, TableSource without `sql`, SQL validation) are correctable by the
  model and out of scope.
- **Existing per-entry state**: `DatasetEntry.is_active` (`tool.py:169`), surfaced through
  `DatasetInfo.is_active` (`tool.py:114`) and `to_info()` (`tool.py:404-474`);
  `DatasetManager.activate()` at `tool.py:2296`.
- **Ledger**: `wikitoolkit ledger context` on `tool.py` and `abstract.py` returns only an
  unrelated wiki-lint issue (`issue:b84eabb5dc40`).
- **Tests**: `packages/ai-parrot/tests/tools/dataset_manager/` holds
  `test_policy_filtering.py`, `test_dataset_manager_config.py`,
  `test_replay_datasources.py`; none covers the failure path.

## Assumptions

No interview was run; these are the decisions research could not settle.

1. **Dict, not exception.** `fetch_dataset` keeps returning a dict on failure, now
   ToolResult-shaped (`status`, `result`, `success`, `error`), instead of raising a new
   `NonRetryableToolError`. Reason: two direct callers read `result["error"]`, and the
   dict shape already maps to a real `ToolResult(status="error")`. A typed exception with
   no raiser would be dead code; it is left for a follow-up if another toolkit needs it.
2. **Every `materialize()` failure becomes `status="error"`**, correctable ones included.
   The existing hint is appended to the `error` string, because only that string reaches
   the model.
3. **Terminal classification** covers: missing relation that matches the entry's own
   table, permission denied, and connection failures. A missing relation that is *not*
   the entry's table stays correctable (the model misnamed it).
4. **Only missing-table and permission-denied mark the dataset unavailable.** Connection
   failures get the do-not-retry text but are not remembered, since they can heal.
5. **`force_refresh=True` does not clear the unavailable mark** — otherwise the model
   could retry through it. `activate()` and re-registration clear it.
6. **Classification is by message pattern**, because asyncdb wraps driver errors into
   strings ("Sentence Error: relation … does not exist"); no driver exception type is
   available at this layer.

## Fix plan

- **HOTFIX-dataset-fetch-terminal-errors-1** — in `dataset_manager/tool.py`: classify
  `materialize()` failures, return ToolResult-shaped error dicts, emit a do-not-retry
  message for terminal failures, record `unavailable_reason` on the entry, short-circuit
  later `fetch_dataset` calls, and surface availability in `DatasetInfo`. Add
  `tests/tools/dataset_manager/test_fetch_terminal_errors.py`.

## Validation commands

- `pytest packages/ai-parrot/tests/tools/dataset_manager/test_fetch_terminal_errors.py -q`
- `pytest packages/ai-parrot/tests/tools/dataset_manager/test_policy_filtering.py -q`
- `pytest packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py -q`

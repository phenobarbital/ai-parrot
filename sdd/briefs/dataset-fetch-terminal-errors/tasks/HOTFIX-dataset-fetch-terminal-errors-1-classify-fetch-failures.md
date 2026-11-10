# HOTFIX-dataset-fetch-terminal-errors-1: Classify fetch_dataset failures and stop retries on terminal ones

**Feature**: dataset-fetch-terminal-errors (BRIEF-dataset-fetch-terminal-errors)
**Spec**: sdd/briefs/dataset-fetch-terminal-errors.brief.md
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`DatasetManager.fetch_dataset` turns every `materialize()` exception into a bare
`{"error", "hint"}` dict. `AbstractTool.execute` wraps that dict as a successful
`ToolResult`, and the TableSource hint tells the model to "fix the SQL" even when the
table does not exist. A PandasAgent burned four tool calls on one missing table. See the
brief's *Root cause* and *Assumptions* sections; the assumptions are binding decisions.

---

## Scope

- Add a module-level classifier that maps a `materialize()` exception to one of
  `"missing_table"`, `"permission_denied"`, `"connection"`, or `None` (correctable).
- In the `except Exception as exc:` handler of `fetch_dataset`, return a
  ToolResult-shaped dict for **every** failure: `status="error"`, `success=False`,
  `result=None`, `error=<text>`. Keep the `hint` key for correctable failures and also
  append the hint to `error` (only the `error` string reaches the model).
- For terminal failures: `error` states that the dataset is unavailable, that this is not
  a SQL problem, that the model must NOT retry or rewrite the query, and that it should
  tell the user the data is unavailable. No column list, no dialect hint, no `hint` key.
  Add `retryable: False` and `error_kind: <kind>` keys.
- Add `DatasetEntry.unavailable_reason: Optional[str]` (default `None`). Set it for
  `missing_table` and `permission_denied` only.
- At the top of `fetch_dataset`, right after the entry is resolved, return the terminal
  error dict immediately when `entry.unavailable_reason` is set — without calling
  `materialize()`, regardless of `force_refresh`.
- Clear `unavailable_reason` in `DatasetManager.activate()`.
- Add `available: bool` and `unavailable_reason: Optional[str]` to `DatasetInfo`, filled
  by `DatasetEntry.to_info()`, so `list_datasets` shows the dataset as unavailable.
- Write the tests in the Test Specification.

**NOT in scope**:
- `parrot/tools/abstract.py`, `parrot/tools/manager.py`, any client — no changes.
- A `NonRetryableToolError` exception class (brief Assumption 1).
- The other early-return error dicts in `fetch_dataset` (dataset not found, TableSource
  without `sql`, SQL validation) — they stay as they are.
- `load_data`, `apply_filters`, `spatial_filter` error paths.
- Schema-prefetch behaviour in `sources/table.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Classifier, error dict shape, unavailable mark, short-circuit, DatasetInfo fields |
| `packages/ai-parrot/tests/tools/dataset_manager/test_fetch_terminal_errors.py` | CREATE | Tests for the failure paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.tool import DatasetManager  # verified: tests/tools/dataset_manager/test_replay_datasources.py:25
from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetInfo  # verified: tool.py:129, tool.py:62
import re  # already imported in tool.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetInfo(BaseModel):                       # line 62
    is_active: bool = Field(default=True, ...)      # line 114

class DatasetEntry:                                 # line 129
    def __init__(self, ..., is_active: bool = True, ...)  # line 144
        self.is_active = is_active                  # line 169
    def to_info(self, alias: Optional[str] = None) -> DatasetInfo:  # line 404
        ...is_active=self.is_active,                # line 474
    # entry.source -> DataSource; TableSource has .table (str), .driver, ._schema

class DatasetManager(AbstractToolkit):              # line 499
    def activate(self, names: Union[str, List[str]]) -> List[str]:  # line 2296
        self._datasets[resolved].is_active = True   # line 2305
    async def fetch_dataset(self, name, sql=None, conditions=None, force_refresh=False) -> Dict[str, Any]:  # line 3330
        resolved = self._resolve_name(name); entry = self._datasets.get(resolved)
        if entry is None: return {...}              # line 3403
        ...
        try:
            df = await self.materialize(name, force_refresh=force_refresh, **params)  # line 3588
        except Exception as exc:                    # line 3589
            self.logger.error("fetch_dataset '%s' failed: %s", name, exc)  # line 3590
            ... builds `hint` (lines 3592-3621) ...
            return {"error": f"Error fetching dataset '{name}': {exc}", "hint": hint}  # lines 3622-3625
    async def materialize(self, name: str, force_refresh: bool = False, **params) -> pd.DataFrame:  # line 4167

# packages/ai-parrot/src/parrot/tools/abstract.py:1090 — a returned dict that has BOTH
# "status" and "result" keys is converted with ToolResult(**raw_result); unknown keys are ignored.
```

Observed error text to classify (asyncdb wraps driver errors as strings):
`TableSource query failed on 'troc.financial_projection_detail': Sentence Error: relation "troc.financial_projection_detail" does not exist`

### Does NOT Exist
- ~~`DatasetEntry.unavailable_reason`~~ — you add it
- ~~`DatasetInfo.available`~~ — you add it
- ~~`parrot.exceptions.NonRetryableToolError`~~ — do not create it
- ~~a typed "undefined table" exception at this layer~~ — only the message string is available

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/dataset_manager/test_fetch_terminal_errors.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetInfo",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetEntry",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager.fetch_dataset"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `fetch_dataset` must keep returning a **dict** on failure with an `"error"` key:
  `infographic_recipes/runner.py:471` reads `result.get("error")`.
- The dict must contain both `"status"` and `"result"` so `abstract.py:1090` builds a real
  error `ToolResult`.
- A missing relation counts as `missing_table` only when the relation named in the message
  equals the entry's own table (compare after stripping quotes/backticks, case-insensitive;
  also accept a match on the unqualified table name). Any other missing relation is
  correctable — the model misnamed a table.
- `connection` failures get the terminal message but do NOT set `unavailable_reason`.
- Non-TableSource entries: `missing_table` needs a `.table` attribute to compare against;
  without one, classify only `permission_denied` / `connection`.
- Keep the existing `self.logger.error(...)` line; add one `self.logger.warning` when an
  entry is marked unavailable.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:3587-3625` — handler to change
- `packages/ai-parrot/tests/tools/dataset_manager/test_replay_datasources.py:1-45` — the
  extension-stub preamble and fixture the new test module must copy verbatim

---

## Implementation Blueprint

### Steps (in order)
1. Add the classifier and message builder at module level — *why*: pure functions are testable without a database.
2. Add `unavailable_reason` to `DatasetEntry` and the two `DatasetInfo` fields — *why*: the mark must outlive one call and be visible in `list_datasets`.
3. Add the short-circuit after the `entry is None` check in `fetch_dataset` — *why*: a retry must not reach the database.
4. Rewrite the `except` handler's return — *why*: this is the defect.
5. Clear the mark in `activate()` — *why*: operators need a way to re-enable after fixing the source.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '^class DatasetInfo(BaseModel):' tool.py)
# BEFORE — insert above `class DatasetInfo(BaseModel):` (verified: tool.py:62)
_MISSING_RELATION_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r'relation "(?P<table>[^"]+)" does not exist', re.IGNORECASE),
    re.compile(r"Table '(?P<table>[^']+)' doesn't exist", re.IGNORECASE),
    re.compile(r"Not found: Table (?P<table>\S+)", re.IGNORECASE),
)
_PERMISSION_PATTERN: re.Pattern[str] = re.compile(r"permission denied|access denied", re.IGNORECASE)
_CONNECTION_PATTERN: re.Pattern[str] = re.compile(
    r"connection refused|could not connect|connection (?:was )?closed|timeout expired|name or service not known",
    re.IGNORECASE,
)


def _classify_fetch_failure(exc: BaseException, table: Optional[str]) -> Optional[str]:
    """Classify a materialize() failure the LLM cannot fix by rewriting its query.

    Args:
        exc: The exception raised while fetching the dataset.
        table: The entry's own table name, or None when the source has no table.

    Returns:
        "missing_table", "permission_denied" or "connection" for terminal failures;
        None when the failure is correctable by the caller.
    """
    # FILL IN: match str(exc) against the patterns above; "missing_table" only when the
    # captured table equals `table` (normalised, or equal on the unqualified name) —
    # bounded by Key Constraints. Treat ConnectionError/OSError instances as "connection".
    raise NotImplementedError


def _terminal_fetch_error(name: str, kind: str, detail: str) -> Dict[str, Any]:
    """Build the ToolResult-shaped error dict for a terminal fetch failure.

    Args:
        name: Dataset name as the caller passed it.
        kind: One of the kinds returned by ``_classify_fetch_failure``.
        detail: The underlying error text.

    Returns:
        A dict with status/result/success/error plus ``retryable`` and ``error_kind``.
    """
    # FILL IN: one sentence per kind for the cause; the message MUST contain
    # "Do NOT retry" and tell the model to inform the user the data is unavailable.
    raise NotImplementedError
```

```python
# occurrences: 1 (verified: grep -c '        self.is_active = is_active' tool.py)
# AFTER — insert below `        self.is_active = is_active` (verified: tool.py:169)
        self.unavailable_reason: Optional[str] = None
```

```python
# occurrences: 1 (verified: grep -c '    is_active: bool = Field(default=True, description="Whether dataset is currently active")' tool.py)
# AFTER — insert below that line (verified: tool.py:114)
    available: bool = Field(default=True, description="False when the source failed terminally; do not fetch")
    unavailable_reason: Optional[str] = Field(default=None, description="Why the dataset is unavailable")
```

```python
# occurrences: 1 (verified: grep -c '            is_active=self.is_active,' tool.py)
# AFTER — insert below `            is_active=self.is_active,` (verified: tool.py:474)
            available=self.unavailable_reason is None,
            unavailable_reason=self.unavailable_reason,
```

```python
# In fetch_dataset — AFTER the `if entry is None:` return block that ends at tool.py:3408
        if entry.unavailable_reason is not None:
            # FILL IN: return the same terminal dict built when the entry was marked
            # (store kind + detail, or the built message, on the entry) — no materialize().
```

```python
# In fetch_dataset — replace the return at tool.py:3622-3625 and branch before the hint is built
            table = getattr(entry.source, "table", None)
            kind = _classify_fetch_failure(exc, table)
            if kind is not None:
                # FILL IN: build via _terminal_fetch_error; set entry.unavailable_reason
                # for "missing_table"/"permission_denied" only; log a warning; return.
            # ... existing hint construction unchanged ...
            message = f"Error fetching dataset '{name}': {exc}"
            return {
                "status": "error",
                "success": False,
                "result": None,
                "error": f"{message} {hint}",
                "hint": hint,
            }
```

```python
# occurrences: 1 (verified: grep -c '                self._datasets\[resolved\].is_active = True' tool.py)
# AFTER — insert below that line (verified: tool.py:2305)
                self._datasets[resolved].unavailable_reason = None
```

**Why this shape**: the dict keeps the direct-caller contract (`result["error"]`) while
`status` + `result` route it through `abstract.py:1090` into a real error `ToolResult`.
The mark lives on the entry so the short-circuit works across calls and turns.

### FILL IN checklist
- [ ] `_classify_fetch_failure` — pattern matching and table comparison; bounded by Key Constraints
- [ ] `_terminal_fetch_error` — message wording; must contain "Do NOT retry"
- [ ] short-circuit in `fetch_dataset` — reuse the terminal dict
- [ ] terminal branch in the `except` handler — mark only two kinds

---

## Acceptance Criteria

- [ ] A `materialize()` failure whose message names the entry's own table as a missing
      relation returns a dict with `status == "error"`, `success is False`,
      `retryable is False`, `error_kind == "missing_table"`, an `error` containing
      "Do NOT retry", and no `hint` key.
- [ ] After that failure a second `fetch_dataset` call returns the same error without
      calling `materialize()`, including with `force_refresh=True`.
- [ ] `list_datasets()` reports that dataset with `available == False` and a reason.
- [ ] `activate(name)` clears the mark and the next fetch calls `materialize()` again.
- [ ] A missing relation for a *different* table, and a column error, return
      `status == "error"` with the existing hint text present in both `hint` and `error`,
      and do not mark the entry.
- [ ] A connection failure returns the do-not-retry error but does not mark the entry.
- [ ] Routed through the toolkit tool, the failure yields `ToolResult.status == "error"`.
- [ ] `ruff check` is clean on both files; the three validation commands pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/dataset_manager/test_fetch_terminal_errors.py -q`
- `pytest packages/ai-parrot/tests/tools/dataset_manager/test_policy_filtering.py -q`
- `pytest packages/ai-parrot/tests/tools/infographic_recipes/test_runner.py -q`

Run from the worktree with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/dataset_manager/test_fetch_terminal_errors.py
# Copy the extension-stub preamble + restore fixture from test_replay_datasources.py:1-45.
import pytest
from unittest.mock import AsyncMock

from parrot.tools.dataset_manager.tool import DatasetManager, _classify_fetch_failure

MISSING = (
    "TableSource query failed on 'troc.financial_projection_detail': Sentence Error: "
    'relation "troc.financial_projection_detail" does not exist'
)


class TestClassifier:
    def test_own_table_missing_is_terminal(self):
        assert _classify_fetch_failure(RuntimeError(MISSING), "troc.financial_projection_detail") == "missing_table"

    def test_other_table_missing_is_correctable(self):
        assert _classify_fetch_failure(RuntimeError(MISSING), "troc.sales") is None

    def test_column_error_is_correctable(self):
        assert _classify_fetch_failure(RuntimeError('column "x" does not exist'), "troc.sales") is None

    def test_permission_denied(self):
        assert _classify_fetch_failure(RuntimeError("permission denied for table sales"), "troc.sales") == "permission_denied"

    def test_connection(self):
        assert _classify_fetch_failure(ConnectionRefusedError("connection refused"), "troc.sales") == "connection"


class TestFetchDatasetFailures:
    # FILL IN: build a DatasetManager with one TableSource entry (bypass prefetch by
    # constructing the entry directly or with strict_schema=False and a mocked source),
    # patch `manager.materialize` with AsyncMock(side_effect=...), and cover every
    # Acceptance Criterion above — one test per criterion.
    ...
```

---

## Agent Instructions

1. Work in this brief's worktree (`fix-dataset-fetch-terminal-errors-dataset-fetch-terminal-errors`), never on `dev`.
2. Read `sdd/briefs/dataset-fetch-terminal-errors.brief.md`; its Assumptions are decisions.
3. Verify the Codebase Contract line anchors before editing.
4. Set this task `in-progress` in `sdd/briefs/dataset-fetch-terminal-errors.index.json` and commit that file.
5. Implement, complete every `# FILL IN:`, run the Validation Commands.
6. Commit only the two files listed, then close the task and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

# Feature Specification: Dataset Description for DatasetManager

**Feature ID**: FEAT-059
**Date**: 2026-03-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x

---

## 1. Motivation & Business Requirements

### Problem Statement

When datasets are registered with `DatasetManager` via `add_dataset`, `add_table_source`, or other registration methods, there is no first-class `description` parameter. Users must pass descriptions buried inside the `metadata` dict (`metadata={"description": "..."}`), which is:

1. **Not discoverable** — callers don't know the convention exists.
2. **Not surfaced automatically** — the agent's system prompt (`$df_info` / `get_guide()`) does not include a bullet-list summary of all datasets with their descriptions.
3. **Missing from `get_metadata()`** — descriptions are only available if the caller explicitly inspects `metadata["description"]`, and the LLM tool output doesn't highlight it.

As a result, agents cannot quickly understand *what* each dataset represents without loading and inspecting data — defeating the purpose of a data catalog.

### Goals

- Add an explicit `description: Optional[str]` parameter to every dataset registration method.
- Generate a **bullet-list summary** of all registered datasets (name + description) that is automatically injected into the agent's system prompt.
- Return the description prominently in `get_metadata()` responses.
- Backward-compatible: `metadata["description"]` still works as a fallback.

### Non-Goals (explicitly out of scope)

- Automated description generation (e.g., via LLM summarization of columns).
- Per-column descriptions (already supported via `metadata["columns"]`).
- UI or REST API changes for description management.

---

## 2. Architectural Design

### Overview

Add `description` as a first-class field on `DatasetEntry`, expose it through all registration methods, surface it in `DatasetInfo`, and generate a dataset summary block for system prompt injection.

### Component Diagram

```
Registration Methods ──→ DatasetEntry.description ──→ DatasetInfo.description
       (add_dataset,                                        │
        add_table_source,                                   ▼
        add_dataframe,        get_metadata() ◄── description field prominent
        add_query,                                          │
        add_sql_source,                                     ▼
        add_airtable_source,  get_datasets_summary() ──→ bullet-list string
        add_smartsheet_source)                              │
                                                            ▼
                                              _generate_dataframe_guide()
                                              (injected into system prompt)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatasetEntry` | modifies | Add `description` field |
| `DatasetInfo` | uses existing | `description` already exists, ensure populated |
| `DatasetManager.add_*` | modifies | Add `description` parameter to all registration methods |
| `DatasetManager.get_metadata` | modifies | Include description prominently in response |
| `DatasetManager._generate_dataframe_guide` | modifies | Prepend dataset summary section |
| `PandasAgent` system prompt | uses | Consumes the new summary via existing `$df_info` |

### Data Models

```python
# DatasetEntry gains a first-class description field
class DatasetEntry:
    def __init__(
        self,
        name: str,
        description: Optional[str] = None,  # NEW
        source: Optional[DataSource] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ...
    ):
        # Priority: explicit description > metadata["description"] > ""
        self.description = description or (metadata or {}).get("description", "")
```

```python
# New method on DatasetManager
class DatasetManager:
    def get_datasets_summary(self) -> str:
        """Generate bullet-list summary of all active datasets.

        Returns a markdown string like:
        - **us_census_data_2023**: Common integrated metrics for ethnicity
          and demographics for US Census 2023
        - **sales_q4**: Quarterly sales data by region and product category
        """
        ...
```

### New Public Interfaces

```python
# Updated registration signatures (all methods)
async def add_dataset(
    self,
    name: str,
    *,
    description: Optional[str] = None,  # NEW
    query_slug: Optional[str] = None,
    ...
) -> str:

async def add_table_source(
    self,
    name: str,
    table: str,
    driver: str,
    *,
    description: Optional[str] = None,  # NEW
    ...
) -> str:

def add_dataframe(
    self,
    name: str,
    df: pd.DataFrame,
    description: Optional[str] = None,  # NEW
    ...
) -> str:

def add_query(
    self,
    name: str,
    query_slug: str,
    description: Optional[str] = None,  # NEW
    ...
) -> str:

def add_sql_source(
    self,
    name: str,
    sql: str,
    driver: str,
    *,
    description: Optional[str] = None,  # NEW
    ...
) -> str:

# New summary method
def get_datasets_summary(self) -> str:
    """Bullet-list of active datasets with descriptions for system prompt."""
```

---

## 3. Module Breakdown

### Module 1: DatasetEntry description field
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: Add `description` parameter to `DatasetEntry.__init__`, resolve priority (explicit > metadata fallback), update `to_info()` to always populate `DatasetInfo.description`.
- **Depends on**: none

### Module 2: Registration methods — add `description` param
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: Add `description: Optional[str] = None` to `add_dataset`, `add_dataframe`, `add_query`, `add_table_source`, `add_sql_source`, `add_airtable_source`, `add_smartsheet_source`. Pass it through to `DatasetEntry`.
- **Depends on**: Module 1

### Module 3: `get_datasets_summary()` method
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: New method that iterates active datasets and produces a markdown bullet-list: `- **name**: description` (or `- **name**: (no description)` if empty). Exposed as a tool for the LLM.
- **Depends on**: Module 1

### Module 4: Surface description in `get_metadata()` and guide
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: Ensure `get_metadata()` returns `description` as a top-level key. Update `_generate_dataframe_guide()` to prepend an "Available Datasets" summary section with descriptions before the detailed per-dataset info.
- **Depends on**: Module 1, Module 3

### Module 5: Tests
- **Path**: `packages/ai-parrot/tests/tools/test_dataset_description.py`
- **Responsibility**: Unit tests for description propagation, summary generation, metadata output, and backward compatibility.
- **Depends on**: Module 1–4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_add_dataset_with_description` | Module 2 | `add_dataset(description="...")` stores description on entry |
| `test_add_dataframe_with_description` | Module 2 | `add_dataframe(description="...")` stores description on entry |
| `test_add_table_source_with_description` | Module 2 | `add_table_source(description="...")` stores description on entry |
| `test_description_fallback_from_metadata` | Module 1 | If no explicit description, falls back to `metadata["description"]` |
| `test_explicit_description_overrides_metadata` | Module 1 | Explicit description takes priority over `metadata["description"]` |
| `test_get_datasets_summary_format` | Module 3 | Summary returns markdown bullet-list with all active datasets |
| `test_get_datasets_summary_excludes_inactive` | Module 3 | Inactive datasets excluded from summary |
| `test_get_metadata_includes_description` | Module 4 | `get_metadata()` response has `description` key |
| `test_guide_includes_summary` | Module 4 | `_generate_dataframe_guide()` includes dataset summary section |
| `test_backward_compat_no_description` | Module 1 | Existing code without description param still works |

### Test Data / Fixtures

```python
@pytest.fixture
def dataset_manager():
    return DatasetManager()

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "region": ["East", "West", "North"],
        "sales": [100, 200, 150],
    })
```

---

## 5. Acceptance Criteria

- [ ] All registration methods accept an optional `description` parameter
- [ ] `DatasetEntry` stores description with fallback to `metadata["description"]`
- [ ] `get_datasets_summary()` returns markdown bullet-list of active datasets
- [ ] `get_metadata()` includes description as a top-level field in response
- [ ] `_generate_dataframe_guide()` prepends a summary section with dataset descriptions
- [ ] Backward compatible — existing code without `description` continues to work
- [ ] Unit tests pass
- [ ] No breaking changes to existing public API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Follow async-first design throughout
- Pydantic models for all structured data
- Google-style docstrings with type hints
- Use `self.logger` for logging

### Known Risks / Gotchas

- **Field name collision**: `DatasetInfo` already has a `description` field (defaulting to `""`). The change is additive — just ensure it's always populated from `DatasetEntry.description`.
- **Guide length**: If many datasets are registered, the summary section could grow large. Consider truncating descriptions to ~150 chars in the guide.

### External Dependencies

None — all changes are internal to existing modules.

---

## 7. Open Questions

- [ ] Should `get_datasets_summary()` be exposed as a LLM-callable tool, or only used internally for guide generation? — *Owner: Jesus*: both, it is a tool that can be used by the LLM to get the summary of the datasets and also used internally for guide generation, injected in the system prompt during the initialization of the agent.
- [ ] Maximum description length — should we enforce a character limit? — *Owner: Jesus*: Yes, 300 characters.

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- All 5 modules modify the same file or closely related files — no parallelization benefit.
- **Cross-feature dependencies**: None. This spec is self-contained.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-24 | Jesus Lara | Initial draft |

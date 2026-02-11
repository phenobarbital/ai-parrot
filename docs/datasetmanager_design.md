# DatasetManager Implementation Walkthrough

## Summary

Implemented a `DatasetManager` class that acts as a data catalog and toolkit for `PandasAgent`, replacing the standalone `MetadataTool` with integrated functionality.

---

## Changes Made (Session 2)

### Enhanced [dataset_manager.py](file:///home/jesuslara/proyectos/navigator/ai-parrot/parrot/tools/dataset_manager.py)

**New tools:**
- `get_dataframe(name)` — Retrieve DataFrame info and samples by name/alias
- `store_dataframe(name, description)` — Store computed DataFrames to catalog

**New features:**
- `generate_guide` config option (default: `True`)
- `include_summary_stats` config option (default: `False`)
- `_generate_dataframe_guide()` — Moved from `PythonPandasTool`
- `get_guide()` — Returns current DataFrame guide

**Guide auto-regenerates** on `add_dataframe()` when `generate_guide=True`.

---

### Updated [data.py](file:///home/jesuslara/proyectos/navigator/ai-parrot/parrot/bots/data.py) - System Prompt

Updated `PANDAS_SYSTEM_PROMPT` with new tool references:

| Old Tool | New Tool |
|----------|----------|
| `dataframe_metadata` | `get_metadata` |
| — | `store_dataframe` |
| — | `get_dataframe` |
| — | `list_available` |
| — | `get_active` |

render_diffs(file:///home/jesuslara/proyectos/navigator/ai-parrot/parrot/bots/data.py)

---

## Test Results

**39 tests passed** in `tests/test_dataset_manager.py`:

````carousel
```
Core Tests (23 tests)
✅ TestDatasetEntry (6)
✅ TestDatasetManager (11)
✅ TestDatasetManagerTools (9 - incl. get_metadata)
```
<!-- slide -->
```
New Tests (8 tests)
✅ TestDatasetManagerGuide
  - test_guide_generation_on_add
  - test_guide_includes_summary_stats
  - test_guide_excludes_summary_stats_by_default
  - test_get_guide_method

✅ TestDatasetManagerEnhancedTools
  - test_get_dataframe_success
  - test_get_dataframe_with_alias
  - test_get_dataframe_not_found
  - test_store_dataframe_returns_instructions
```
````

---

## Usage

### Guide Generation

```python
# With summary stats
dm = DatasetManager(
    generate_guide=True,
    include_summary_stats=True
)
dm.add_dataframe("sales", df)

# Get the guide
print(dm.get_guide())
```

### Storing Computed DataFrames (LLM Tool)

The `store_dataframe` tool allows the LLM to save computed results:

```
1. LLM creates DataFrame in python_repl_pandas
2. LLM calls store_dataframe to register it
3. DataFrame becomes available for future analysis
```

---

## Files Changed

| File | Changes |
|------|---------|
| `parrot/tools/dataset_manager.py` | Added tools, guide generation |
| `parrot/bots/data.py` | Updated system prompt |
| `tests/test_dataset_manager.py` | Added 8 new tests |
| `docs/datasetmanager_design.md` | Documentation |

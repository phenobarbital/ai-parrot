---
id: FW-004
query_id: Q003
type: wiki_page
intent: "Orient: WorkingMemory toolkit — how stored results / dataframes are held and referenced (handle-like keys, Arrow/Polars)."
executed_at: 2026-10-25T22:46:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FW-004 — WorkingMemoryToolkit is a per-session pandas key→entry store with compact summaries; no handle/descriptor/provenance type, no Arrow/Polars

## Summary

`tools/working_memory/tool.py::WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit)` (`name='working_memory'`, `tool_prefix='wm'`) stores DataFrames and generic objects under string keys via a `WorkingMemoryCatalog` of `CatalogEntry`/`GenericEntry` (`internals.py`); the LLM only ever sees compact summaries (shape, dtypes, stats, preview) — the same 'descriptor not payload' principle the parent spec wants (D3/D7). API: `store(key, df)` (Python-only, excluded from LLM), `store_result(key, data, data_type, description, metadata, turn_id)`, `get_stored`, `get_result(..., include_raw, max_rehydrate_bytes)`, `search_stored`, `list_stored`, `compute_and_store(spec)` (declarative DSL), `merge_stored`, `summarize_stored`, `import_from_tool`, `list_tool_dataframes`, `save_interaction/recall_interaction`, `from_runtime(runtime, scope)`, plus task-memory tools (FEAT-585). It is built on **pandas** (`import pandas as pd`), constructed with `session_id` (per-session scope), has a raw-read byte ceiling (`_resolve_raw_budget`, `_apply_raw_policy`). There is no handle type with content hash/media_type/provenance/affordances, no blob store, no Arrow/Polars, and no cross-agent sharing — entries are owned by one toolkit instance. The spec `sdd/specs/extending-workingmemorytoolkit.spec.md` is the governing design doc.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 1-45
  symbol: `WorkingMemoryToolkit (imports)`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/working_memory/tool.py (score=0.83)
  excerpt: |
    import pandas as pd
    from parrot.tools.toolkit import AbstractToolkit
    from .internals import (CatalogEntry, GenericEntry, OperationExecutor, ShapeLimit, WorkingMemoryCatalog, _detect_entry_type)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 48-110
  symbol: `WorkingMemoryToolkit`
  excerpt: |
    class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):
        name: str = 'working_memory'
        tool_prefix: str = 'wm'
        exclude_tools: tuple[str, ...] = ('store',)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: n/a (API outline)
  symbol: `WorkingMemoryToolkit.store_result / get_result / search_stored / list_stored / compute_and_store / import_from_tool / from_runtime`
- path: `packages/ai-parrot/src/parrot/tools/working_memory/models.py`
  lines: n/a
  symbol: `EntryType / StoreResultInput / GetResultInput`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/working_memory/models.py (score=0.37)
- path: `sdd/specs/extending-workingmemorytoolkit.spec.md`
  lines: n/a
  symbol: `Feature Specification: Extending WorkingMemoryToolkit`
  wiki_page_id: file:sdd/specs/extending-workingmemorytoolkit.spec.md (score=0.96)

## Notes

Parent-spec D5 ('remote results land in WorkingMemory as references') has a natural seam: `store_result(key, data, data_type, metadata)` + a new `EntryType` for handles. Zero-copy claim: see FW-014 (Arrow IPC exists only on the REPL worker boundary). `[cross-lane: type=read, intent=working_memory/internals.py CatalogEntry/GenericEntry fields — is there a metadata slot for provenance]`.

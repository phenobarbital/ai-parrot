---
id: F003
query: Q003, Q004
type: read
target: packages/ai-parrot/src/parrot/pageindex/__init__.py, schemas.py
---

# F003 — PageIndex API and Schemas Verification

**Status**: Confirmed, minor additions

## Public API (__all__)
Exact match with proposal: `build_page_index`, `md_to_tree`, `PageIndexRetriever`,
`PageIndexLLMAdapter`, `PageIndexNode`, `TreeSearchResult`, `TocItem`

## build_page_index
```python
async def build_page_index(
    doc: str | BytesIO,
    adapter: PageIndexLLMAdapter,
    options: dict | config | None = None,
) -> dict  # {"doc_name": str, "structure": list, "doc_description"?: str}
```

## md_to_tree
```python
async def md_to_tree(
    md_text: str,
    adapter: PageIndexLLMAdapter,
    options: dict | config | None = None,
    doc_name: str = "document.md",
) -> dict  # same shape
```

## PageIndexNode(BaseModel)
All expected fields confirmed: title, node_id, start_index, end_index, summary, text, line_num, nodes
**Extra field**: `prefix_summary: Optional[str] = None` (not in proposal)
`model_config = {"extra": "allow"}`

## TreeSearchResult(BaseModel)
Confirmed: `thinking: str`, `node_list: list[str]`

## Additional models not in proposal
- `PageIndexTree`: typed version of the tree dict (doc_name, doc_description, structure)
- `TocItem`, `TocDetectionResult`, `TocCompletionCheck`, etc. (internal LLM schema models)

## Note
Both `build_page_index` and `md_to_tree` require `PageIndexLLMAdapter` — the proposal
should mention this dependency for the loader-based extractor.

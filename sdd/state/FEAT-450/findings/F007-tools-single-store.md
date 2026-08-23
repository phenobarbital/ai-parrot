---
id: F007
query_id: Q012,Q018
type: read
intent: Confirm AbstractTool wrappers and their input models bind to one store
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F007 — Six AbstractTool wrappers take a BaseWikiStore; inputs have no namespace field

## Summary
Input models (tools.py:23-64): `WikiQueryInput(question, budget_tokens)`, `WikiPageInput(page_id)`,
`WikiRelatedInput(page_id)`, `WikiRememberInput`, `WikiNoteInput`, `WikiStatusInput` (empty).
`WikiQueryTool._execute` (84-87) calls `store.search_fts(question)` then `pack_results`;
`WikiPageTool._execute` (105), `WikiRelatedTool._execute` (130) call `get_page`/`neighbors`.
`create_wiki_tools(store, root, config)` (399-428) instantiates all six with the same store.
Consumers: `mcp_server.py:108`, tests `test_wiki_tools.py:37,169,179`. Adding an optional
`namespace` field + a federated store is sufficient; no tool rewrite.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 23-64
  symbol: `WikiQueryInput`, `WikiPageInput`, `WikiRelatedInput`, `WikiStatusInput`
  excerpt: |
    class WikiQueryInput(BaseModel):
        question: str = Field(...)
        budget_tokens: int = Field(default=DEFAULT_BUDGET_TOKENS)
    class WikiPageInput(BaseModel):
        page_id: str = Field(..., description="Page ID from wiki_query results")
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 67-135
  symbol: `WikiQueryTool`, `WikiPageTool`, `WikiRelatedTool`
  excerpt: |
    async def _execute(self, question, budget_tokens=DEFAULT_BUDGET_TOKENS) -> str:   # 84
        results = await self._store.search_fts(question)
        packed = pack_results(results, budget_tokens=budget_tokens)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 272-286
  symbol: `WikiStatusTool`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 399-428
  symbol: `create_wiki_tools`
- path: `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py`
  lines: 37, 168-179
- path: `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py`
  lines: 8, 25-44

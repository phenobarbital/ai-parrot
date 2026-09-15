---
id: F012
query_id: Q014
type: read
intent: Read the AbstractToolkit base and a modern exemplar (DatabaseQueryToolkit) for tool-generation, lifecycle and naming conventions.
executed_at: 2026-09-15T02:52:00Z
duration_ms: 2500
parent_id: null
depth: 0
---
# F012 — AbstractToolkit: public async methods become tools; tool_prefix, exclude_tools, auto_open, _prepare_kwargs/_pre_execute/_post_execute hooks
## Summary
`AbstractToolkit` (712 lines) auto-generates a `ToolkitTool` per public async method (args schema from the signature, docstring = description). Class knobs: `exclude_tools`, `tool_prefix` + `prefix_separator` (idempotent rewrite), `confirming_tools`, `llm_dependent_tools`, `credential_provider`, `auto_open` (FEAT-391 lazy `_open()/_close()`). Per-call hooks: `_prepare_kwargs(tool_name, kwargs)` (inject/override args before filtering — the natural place to force a tenant), `_pre_execute` (authorization; raising aborts), `_post_execute` (result shaping). `DatabaseQueryToolkit` is the reference implementation: `tool_prefix="dq"`, `exclude_tools`, docstring listing generated tool names, `_post_execute` → `model_dump()` for Pydantic results, conditional exclusion of tools when config is missing.
## Citations
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 206-320
  symbol: `AbstractToolkit`
  excerpt: |
    exclude_tools: tuple[str, ...] = ()
    tool_prefix: str | None = None ; prefix_separator: str = "_"
    llm_dependent_tools: frozenset = frozenset(); credential_provider: str | None = None
    auto_open: bool = False   # FEAT-391 lazy lifecycle → _open()/_close()/_ensure_open()
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 438-485
  symbol: `AbstractToolkit._prepare_kwargs`, `_pre_execute`, `_post_execute`
  excerpt: |
    async def _prepare_kwargs(self, tool_name, kwargs) -> dict:  # "the dict returned here IS the one forwarded to the bound method"
    async def _pre_execute(self, tool_name, /, **kwargs) -> None:  # raising aborts the call
    async def _post_execute(self, tool_name, result, /, **kwargs) -> Any
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 486-577, 637-690
  symbol: `get_tools`, `_generate_tools`, `_create_tool_from_method`
- path: `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py`
  lines: 115-200
  symbol: `DatabaseQueryToolkit`
  excerpt: |
    tool_prefix: Optional[str] = "dq"
    exclude_tools: tuple[str, ...] = ("get_source", "cleanup", "start", "stop")
    if self._output_dir is None: self.exclude_tools = self.exclude_tools + ("save_result",)
    async def _post_execute(...): return result.model_dump() if isinstance(result, BaseModel) else result

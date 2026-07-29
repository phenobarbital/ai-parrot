---
id: F003
query_id: Q003
type: read
intent: Understand AbstractTool / AbstractToolArgsSchema single-tool pattern
executed_at: 2026-07-13T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — AbstractTool single-tool pattern (Bloomberg/FRED)

## Summary

A single tool subclasses `AbstractTool`, declares class attrs `name`,
`description`, `args_schema` (an `AbstractToolArgsSchema`/`BaseModel`
subclass with `Field(description=...)`), and implements `async def
_execute(self, ...) -> Any | ToolResult`. `parrot_tools/abstract.py` just
re-exports `AbstractTool`, `AbstractToolArgsSchema`, `ToolResult` from the
canonical `parrot.tools.abstract`. FRED shows the HTTP + API-key + optional
`ToolCache` variant; config is read via `navconfig.config.get("...")`.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/abstract.py`
  lines: 1-7
  symbol: re-export
  excerpt: |
    from parrot.tools.abstract import (AbstractTool, AbstractToolArgsSchema, ToolResult)

- path: `packages/ai-parrot-tools/src/parrot_tools/bloomberg.py`
  lines: 7-46
  symbol: `BloombergToolArgsSchema / BloombergTool`
  excerpt: |
    class BloombergToolArgsSchema(AbstractToolArgsSchema):
        category: str = Field(default="markets", description="...")
    class BloombergTool(AbstractTool):
        name: str = "bloomberg_news"
        description: str = "..."
        args_schema: Type[AbstractToolArgsSchema] = BloombergToolArgsSchema
        async def _execute(self, category: str = "markets", limit: int = 5, **kwargs) -> Any:

- path: `packages/ai-parrot-tools/src/parrot_tools/fred_api.py`
  lines: 57-98
  symbol: `FredAPITool.__init__ / _execute`
  excerpt: |
    self.http_service = HTTPService(base_url=self.BASE_URL, **kwargs)
    self._cache = ToolCache(prefix="tool_cache", ttl=cache_ttl)
    api_key = api_key or config.get("FRED_API_KEY")
    # returns ToolResult(success=..., status=..., result=..., error=...)

## Notes

FRED wraps `HTTPService` as a member (`self.http_service`) rather than
inheriting it — the cleaner composition choice for a tool. `ToolResult`
is the structured return envelope.

---
id: F004
query_id: Q004
type: read
intent: Understand AbstractToolkit multi-method pattern via closest analog
executed_at: 2026-07-13T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — AbstractToolkit pattern & CompanyInfoToolkit analog

## Summary

`AbstractToolkit` (in core `parrot/tools/toolkit.py`) turns each public async
method into a tool: name = method name, description = docstring, schema from
type hints or `@tool_schema(Model)`. It supports `tool_prefix` (namespaces
every tool as `f"{tool_prefix}{prefix_separator}{method}"`, idempotent),
`exclude_tools`, and `confirming_tools`. `CompanyInfoToolkit` is the closest
analog: a company-information toolkit whose `__init__` takes config kwargs,
calls `super().__init__(**kwargs)`, and exposes one `@tool_schema`-decorated
async method per data source. This is the natural shape for LeadIQ's three
search types.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 207-261
  symbol: `AbstractToolkit`
  excerpt: |
    class AbstractToolkit(ABC):
        # public async methods -> tools; get_tools() collects them
        exclude_tools: tuple[str, ...] = ()
        tool_prefix: Optional[str] = None
        prefix_separator: str = "_"

- path: `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`
  lines: 75-82, 163-203
  symbol: `CompanyInput / CompanyInfoToolkit.__init__`
  excerpt: |
    class CompanyInput(BaseModel):
        company_name: str = Field(..., description="Name of the company to search for")
        return_json: bool = Field(False, description="...")
    class CompanyInfoToolkit(AbstractToolkit):
        def __init__(self, ...config kwargs..., **kwargs):
            super().__init__(**kwargs)

- path: `packages/ai-parrot-tools/src/parrot_tools/company_info/tool.py`
  lines: 428-429, 675-676
  symbol: `@tool_schema` methods
  excerpt: |
    @tool_schema(CompanyInput)
    async def scrape_zoominfo(self, company_name: str, ...): ...
    @tool_schema(CompanyInput)
    async def scrape_leadiq(self, company_name: str, ...): ...

- path: `packages/ai-parrot/src/parrot/tools/decorators.py`
  lines: 37
  symbol: `tool_schema`
  excerpt: |
    def tool_schema(schema: Type[BaseModel], description: Optional[str] = None):

## Notes

`tool_prefix = "leadiq"` would yield tool names `leadiq_search_company`,
etc., disambiguating from the existing scraping `scrape_leadiq` (F006).

---
id: F003
query_id: Q003
type: read
intent: Understand PlanNode and ForEach model schemas for delegate node design
executed_at: 2026-09-21T22:07:00Z
depth: 0
parent_id: null
---

# F003 — PlanNode model and ForEach fan-out

## Summary

PlanNode (models.py:L173-254) carries: id, tool, args, store_as, depends_on, when, for_each, facets, timeout, retry, description. ForEach (models.py:L111-170) carries: source, select, alias, max_items, max_concurrency, on_item_error, skip_existing. Fan-out happens INSIDE one DAG node (graph stays static, item count discovered at runtime). The proposal's delegate JSON shape closely mirrors PlanNode but replaces `tool`+`args` with `instruction`+`facts`+`tools` (list) and adds `min_confidence` and `on_reject`.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/plan/models.py`
  lines: 173-254
  symbol: `PlanNode`
  excerpt: |
    class PlanNode(BaseModel):
        model_config = ConfigDict(extra="forbid")
        id: str
        tool: str
        args: Dict[str, Any] = Field(default_factory=dict)
        store_as: str
        depends_on: List[str] = Field(default_factory=list)
        when: Optional[str] = None
        for_each: Optional[ForEach] = None
        facets: FacetSpec = Field(default_factory=FacetSpec)
        timeout: Optional[float] = None
        retry: RetryPolicy = Field(default_factory=RetryPolicy)
        description: Optional[str] = None

- path: `packages/ai-parrot/src/parrot/bots/flows/plan/models.py`
  lines: 111-170
  symbol: `ForEach`
  excerpt: |
    class ForEach(BaseModel):
        source: str
        select: Optional[str] = None
        alias: str = Field(default="item", alias="as")
        max_items: int  # hard ceiling
        max_concurrency: int
        on_item_error: Literal["fail", "collect", "skip"]
        skip_existing: bool

## Notes

The delegate node would reuse ForEach unchanged (same fan-out semantics) but needs a different node model — DelegateNode — that carries `instruction`, `tools` (list of tool names), `facts`, `min_confidence`, `on_reject` instead of PlanNode's single `tool`+`args`. Both share `id`, `store_as`, `depends_on`, `when`, `for_each`, `facets`, `timeout`, `retry`.

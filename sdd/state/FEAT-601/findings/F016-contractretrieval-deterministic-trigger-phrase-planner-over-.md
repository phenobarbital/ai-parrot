---
id: F016
query_id: Q016
type: read
intent: ContractRetrieval models, deps, method signatures; how plan picks a traversal pattern (LLM or not)
executed_at: 2026-09-24T23:21:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F016 — ContractRetrieval: deterministic trigger-phrase planner over 10 allowlisted patterns

## Summary
`retrieval.py` defines the request and plan models, plus a `ContractRetrieval` class whose constructor takes keyword-only dependencies: catalog, graph_store, tenant_context, ontology, authorization, today and ranker. `plan()` first checks `is_interpretation`, then `classify()`. `classify` normalizes the question and returns the first pattern in the ordered `_TRIGGERS` tuple whose trigger phrase is a substring; with no match it returns a Clarification (fails closed). After that, `plan` authorizes and binds values per pattern. No LLM is involved anywhere; the module docstring says so explicitly, and `ranker` is documented as "never an LLM". Graph execution runs only the ontology's allowlisted `query_template` for patterns in `PATTERNS`, and `_validate_projection` checks the projected `card_revision` against the SQL catalog.

## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 1-6
  symbol: `module docstring`
  excerpt: |
    Everything in this module is **LLM-free**. It classifies a question against
    ten explicit patterns, resolves entities against the *authorized* catalog,
    binds every AQL/SQL value itself and executes only allowlisted YAML
    patterns. There is no dynamic AQL, no LLM fallback and no client.
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 66-86
  symbol: `PATTERNS`, `_TRIGGERS`
  excerpt: |
    PATTERNS: tuple[str, ...] = (
        "contracts_requiring_standard",
        "notice_deadlines_within",
        ...
    _TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("contracts_requiring_standard",
         ("require", "requires", "required", "compliance requirement", "certified")),
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 142-214
  symbol: `RequestContext`, `AuthorizationDenied`, `Clarification`, `PatternPlan`, `RetrievalResult`
  excerpt: |
    class RequestContext(BaseModel):  # user_id, roles, tenant_id, employee_id,
        # employee_graph_id, department, confirmed: bool
    class AuthorizationDenied(PermissionError):
        def __init__(self, reason: str, *, pattern: Optional[str] = None)
    class Clarification(BaseModel): reason; pattern; candidates: list[str]
    class PatternPlan(BaseModel): pattern; binds; entities; interpretation_required: bool
    class RetrievalResult(BaseModel): pattern; cards; obligations; rows; binds; used_graph; notes
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 222-243
  symbol: `classify`, `is_interpretation`
  excerpt: |
    normalized = _normalize(question)
    for pattern, triggers in _TRIGGERS:
        for trigger in triggers:
            if _normalize(trigger) in normalized:
                return pattern
    return None
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 261-278
  symbol: `ContractRetrieval.__init__`
  excerpt: |
    def __init__(self, *, catalog: ContractCatalogStore, graph_store: Any = None,
                 tenant_context: Any = None, ontology: Any = None,
                 authorization: Any = None, today: Any = None, ranker: Any = None) -> None:
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 282-319
  symbol: `ContractRetrieval.authorize`
  excerpt: |
    def authorize(self, context: RequestContext, *, pattern: Optional[str] = None,
                  owner_only: bool = False) -> None:
        if not context.authenticated:
            raise AuthorizationDenied("no authenticated principal", pattern=pattern)
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 323-413
  symbol: `ContractRetrieval.resolve_contract`, `ContractRetrieval.resolve_party`
  excerpt: |
    async def resolve_contract(self, question: str, context: RequestContext) -> str | Clarification:
    async def resolve_party(self, question: str, context: RequestContext) -> str | Clarification:
        # exact id/name, then title/alias, then normalized fuzzy (FUZZY_THRESHOLD=0.85)
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 431-494
  symbol: `ContractRetrieval.plan`
  excerpt: |
    async def plan(self, question: str, context: RequestContext) -> PatternPlan | Clarification:
        if is_interpretation(question):
            return PatternPlan(pattern="interpretation", interpretation_required=True)
        pattern = classify(question)
        if pattern is None:
            return Clarification(reason="the question does not match a supported pattern")
        self.authorize(context, pattern=pattern)
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 535-629
  symbol: `ContractRetrieval.retrieve`, `ContractRetrieval.execute`
  excerpt: |
    async def retrieve(self, question: str, context: RequestContext) -> RetrievalResult | Clarification:
        plan = await self.plan(question, context)
    async def execute(self, plan: PatternPlan, context: RequestContext) -> RetrievalResult:
        """Execute a bound plan against SQL (always) or the graph."""
        self.authorize(context, pattern=plan.pattern)
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 681-725
  symbol: `ContractRetrieval.aql_for`, `ContractRetrieval.execute_graph`
  excerpt: |
    def aql_for(self, pattern: str) -> str:
        if pattern not in PATTERNS: raise AuthorizationDenied(...)
        declared = self.ontology.traversal_patterns.get(pattern)
        return declared.query_template
    async def execute_graph(self, plan, context, *, collection_binds=None) -> list[dict]:
        rows = await self.graph_store.execute_traversal(self.tenant_context, aql,
            bind_vars=dict(plan.binds), collection_binds=collection_binds or {})
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py`
  lines: 727-745
  symbol: `ContractRetrieval._validate_projection`
  excerpt: |
    async def _validate_projection(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...
        card = await self.catalog.get(contract_id)
        if card is None or card.revision != revision:
            raise AuthorizationDenied(f"graph projection of {contract_id!r} is stale ...")

## Notes
- The claim that patterns are chosen without an LLM is TRUE: pattern choice is ordered substring matching, and the order of `_TRIGGERS` decides ties. That makes it brittle for field-technician phrasing; ProcedureRetrieval will need its own trigger table.
- `_validate_projection` expects rows shaped like `row["contract"]` with `contract_id` and `card_revision`. It is specific to contracts and has to be rewritten for procedures, not copied as-is.
- Values are bound by pattern-specific branches in `plan` (L456-492). There is no generic binder.


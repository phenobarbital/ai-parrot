---
id: F002
query_id: Q010, Q011, Q012
type: read
intent: "Public surface, layering statement and contract names of parrot.semantic as it exists on dev."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 0
lane_ids: [FC-001, FC-002, FC-004, FC-005, FW-001, FW-005, FW-006]
---

# F002 — `parrot.semantic` today: 4 exports, a README that already reserves the accounting extension, and contract names an accounting layer would collide with

## Summary

*(FC-001)* `parrot.semantic.__init__` eagerly imports `SemanticLayerToolkit` (and through it the whole governed
stack), so `import parrot.semantic.accounting` executes that import chain first — the old spec's
"`__init__.py` exports only `__version__`" no longer holds. The README has a **Layering** section that
names "the future accounting extension" and requires it to "remain independently importable".
`models.py` already defines `Grain` (8 values, second…year), `SemanticQuery`, `CompiledQuery`
(pre-governance: sql, dialect, members, tables, cache_key), `GovernedQuery`, `SemanticQueryResult`,
`Limits` (default 1000 / max 10000) and `ModelMember` (kind: metric | dimension | time_dimension | entity).
`CompiledQuery` exists as the old spec anticipated, so `CompiledMetricQuery` stays a non-colliding name;
`Grain` and a top-level `Metric` (in `model.py`) would collide if re-declared at the same level.

*(FC-002)* `parrot.semantic.engines.compile(query, model, dialect, *, cache)` is the single entry point; it
instantiates `NativeCompiler(model)` directly inside `asyncio.to_thread` — no registry, no dispatch
("Sole native SQL AST compiler; no warehouse connection or engine dispatch"). The compiler builds sqlglot
`exp.*` nodes from a `LoadedModel` + `SemanticQuery`: metrics, dimensions, time-dimension grains, joins,
WHERE/HAVING filters, ORDER BY. Aggregations are a closed tuple (`sum, count, count_distinct, avg, min,
max`). Nothing in it expresses account sets (`SUM(CASE WHEN account IN (...))`), sign normalisation,
effective-dated membership, cumulative window totals or reconciliation assertions. An accounting compiler
therefore cannot be "an engine of" the existing entry point without changing it; it is a parallel
compiler that can share sqlglot, the dialect names and the `to_thread` + compile-cache pattern.

*(FC-004)* `parrot/semantic/audit.py` ships `SemanticAuditEntry` (schema_version, entry_id, identity fields,
`subject_digest`, model + `model_digest` + `policy_digest`, tool, `structured_query`, `compiled_sql`,
`governed_sql`, dialect, driver, rls/mask lists, pbac outcome, outcome, row_count, duration, signature)
with `canonical_bytes()` = sorted-key compact JSON excluding `signature`, and `SemanticAuditLedger(signer,
storage, max_entries)`: signs with `AbstractKMSSigner` (default `LocalHMACSigner`), keeps a bounded deque,
forwards `entry.model_dump_json()` to an async `storage` callable, and with `append(..., required=True)`
raises `SemanticExecutionError("audit_unavailable")` when the sink is missing or fails. A Postgres sink
(`postgres_audit_storage`, table `semantic_audit_events`, DDL shipped as package data) exists. The mechanics
match the old M7 one for one; the differences are the entry fields (no `model_hash`/`snapshot_hash`/
`sql_hash`/`lineage_ref`/`assertion_status`/`target`, and it stores raw `user_id` plus SQL text, which the
old spec's entry deliberately did not) and the mode switch (`required` bool per call vs `FINANCE_AUDIT_MODE`).

*(FC-005)* `SemanticModelLoader(models_dir, driver=)` loads every model document in one **flat** directory, requires a
`<name>.policy.yaml` side-file per model (`missing_policy` otherwise), validates the whole graph and
publishes an immutable snapshot of `LoadedModel` (model, related_models, policy, members, schema,
`model_digest`, `policy_digest`, `compiler_version`); `reload_if_changed()` swaps atomically. There is no
`<models_dir>/<tenant>/` level. `ModelPolicy` carries `governed`, `connection`, `limits`, per-role
`RoleGrant` (metrics / dimensions / usage), `masks`, `rls`, `saved_queries`, `allowed_functions`.
`PbacGate` wraps core `DataPlanePolicyGuard.authorize_source(ctx, PhysicalResources)` with resources named
`<driver>:<table>` and fails closed on missing context, missing evaluator or evaluator error; `governed:
false` returns early. `SemanticLayerToolkit` (`tool_prefix = "sl"`) refuses to construct governed models
without a guard, requires a bound `PermissionContext` matching the supplied one in `_pre_execute`, and its
`_run_governed` is the single path: authorize manifest → expand saved query → check rights → compile →
govern → execute → audit → retain result handle.

*(FW-001)* The wiki directory page lists 21 entries under `packages/ai-parrot-semantic/src/parrot/semantic`: `engines/` (sole `NativeCompiler`, no dispatch), `governance/` (pbac, lineage, rls, masking, guard, pipeline), `schemas/`, `sql/`, plus `audit`, `bootstrap`, `cache`, `catalog`, `context`, `errors`, `execution`, `handoff`, `loader`, `model`, `models`, `ossie`, `policy`, `results`, `toolkit`, `version`. The package `__init__` exports only `__version__`, `SemanticQuery`, `SemanticQueryResult`, `SemanticLayerToolkit` and imports the toolkit eagerly. `SemanticLayerToolkit` (`tool_prefix = "sl"`) takes `models_dir`, `dialect`, `dataplane_guard`, `rls_registry`, `database_toolkit`, `signer`, `audit_storage`, `audit_required`, `allow_raw_sql`, `dataset_manager_factory` and funnels every query through `_run_governed`. The names `CompiledQuery`, `GovernedQuery`, `Limits`, `Grain` are taken in `models.py`.

*(FW-005)* `parrot/semantic/audit.py` defines `SemanticAuditEntry` (schema_version, entry_id, created_at, user/tenant/channel/agent, `subject_digest`, roles, model, `model_digest`, `policy_digest`, `engine: Literal["native"]`, tool, structured_query, raw_sql, compiled_sql, governed_sql, dialect, driver, rls_applied, masked_columns, pbac, outcome, error_code, row_count, duration_ms, signature) and `SemanticAuditLedger(signer, storage, max_entries)`: a bounded in-memory deque, signer defaulting to `LocalHMACSigner`, `append(entry, *, required=False)` that raises when a required sink is missing or fails, `verify()`, and `postgres_audit_storage(dsn_or_pool)` writing to the table created by `sql/semantic_audit_events.sql`. It reuses only `AbstractKMSSigner` / `LocalHMACSigner` from `parrot.security`; the core `AuditLedger` stays credential-invocation shaped. The entry has no `snapshot_hash`, `sql_hash`, `lineage_ref`, `assertion_status` or `target` field, and `engine` is a one-value Literal.

*(FW-006)* FEAT-704 rev2 (proposal of 2026-10-25, spec rev 0.3/0.4) dropped sidemantic entirely — "no dependency, no code reference" — and made the native sqlglot compiler the only engine, so FEAT-713's stated reason for being standalone ("FEAT-704 is paused until its AGPL dependency is migrated away") no longer exists. The semantic-layer spec resolves U6 (owner, 2026-10-25): "FEAT-704 rev 0.3 creates the skeleton (M1); FEAT-713's M1 becomes 'extend'", and states this resolves FEAT-713 §8 Q10, the edit to be made "the next time FEAT-713's spec is touched". The shipped README carries a Layering section: the generic layer and "the future accounting extension share this namespace" and "the accounting extension must remain independently importable". The same rev2 decision block says the first native compiler was to be "without joins in v1" (later U4 kept one-to-many joins), keeps the governance stack as ai-parrot code "with any engine", stages SemaFlow (MIT) for the Rust/PyO3 phase under reserved FEAT-742 (TASK-4701 pending, a manual research follow-up), and narrows the Ibis NO-GO. The user-facing doc `wiki/tools/semantic-layer.md` mentions DuckDB only as a dialect/driver and the guarded hand-off; it has no accounting section.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py`
  lines: 1-7
  symbol: `__all__`
  excerpt: |
    """Governed semantic queries using the native sqlglot compiler."""
    from .version import __version__
    from .models import SemanticQuery, SemanticQueryResult
    from .toolkit import SemanticLayerToolkit
    __all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]

- path: `packages/ai-parrot-semantic/README.md`
  lines: 6-9
  symbol: `Layering`
  excerpt: |
    ## Layering
    Generic semantic queries and the future accounting extension share this namespace.
    The accounting extension must remain independently importable.

- path: `packages/ai-parrot-semantic/README.md`
  lines: 19-22
  symbol: `Governance`
  excerpt: |
    The current native compiler supports declared metrics, dimensions, time grains,
    declared one-to-many joins with fan-out rejection, filtered measures, and
    derived metrics. The `duckdb` extra provides the local execution backend; the
    `bigquery` extra provides BigQuery integration.

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 12-12
  symbol: `Grain`
  excerpt: |
    Grain = Literal["second", "minute", "hour", "day", "week", "month", "quarter", "year"]

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 102-137
  symbol: `SemanticQuery`
  excerpt: |
    class SemanticQuery(BaseModel):
        model_config = ConfigDict(extra="forbid")
        model: str
        metrics: list[str] = Field(default_factory=list)
        dimensions: list[str] = Field(default_factory=list)
        time_dimensions: list[TimeDimension] = Field(default_factory=list)
        filters: FilterGroup | None = None
        order_by: list[OrderBy] = Field(default_factory=list)
        limit: int | None = None
        def canonical_json(self) -> str:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 192-199
  symbol: `CompiledQuery`
  excerpt: |
    class CompiledQuery(BaseModel, frozen=True):
        """Pre-governance compiler output without subject-derived content."""
        sql: str
        dialect: str
        members: tuple[str, ...]
        tables: tuple[str, ...]
        cache_key: str

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 202-214
  symbol: `GovernedQuery`
  excerpt: |
    class GovernedQuery(BaseModel, frozen=True):
        sql: str
        dialect: str
        driver: str
        tables: tuple[str, ...]
        rls_applied: tuple[str, ...]
        masked_columns: tuple[str, ...]
        limit: int
        subject_digest: str

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 217-227
  symbol: `SemanticQueryResult`
  excerpt: |
    class SemanticQueryResult(BaseModel):
        columns: list[str]
        rows: list[dict[str, Any]]
        row_count: int
        truncated: bool
        duration_ms: int
        compiled_sql: str
        audit_id: str
        result_id: str | None = None

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 230-234
  symbol: `Limits`
  excerpt: |
    class Limits(BaseModel):
        default: int = 1000
        max: int = 10000

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 244-251
  symbol: `ModelMember`
  excerpt: |
    class ModelMember(BaseModel):
        name: str
        kind: Literal["metric", "dimension", "time_dimension", "entity"]

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`
  lines: 14-26
  symbol: `_cache_key`
  excerpt: |
    return json.dumps(
        [model.model_digest, model.policy_digest, query.canonical_json(), dialect,
         model.compiler_version, model.policy.connection],
        separators=(",", ":"),
    )

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`
  lines: 29-46
  symbol: `compile`
  excerpt: |
    async def compile(query: SemanticQuery, model: LoadedModel, dialect: str, *,
                      cache: CompileCache | None = None) -> CompiledQuery:
        """Compile under to_thread, or return immutable pre-governance cache output."""
        ...
        compiled = await asyncio.to_thread(NativeCompiler(model).compile, query, dialect)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 1-20
  symbol: `NATIVE_AGGREGATIONS`
  excerpt: |
    """Sole native SQL AST compiler; no warehouse connection or engine dispatch."""
    from sqlglot import exp
    NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")
    _FILTER_DIALECTS = frozenset({"duckdb", "postgres"})

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 45-54
  symbol: `NativeCompiler`
  excerpt: |
    class NativeCompiler:
        """Compile the closed semantic grammar to deterministic dialect SQL."""
        def __init__(self, model: LoadedModel) -> None:
            self.model = model
            self._graph: dict[str, SemanticModel] = {model.name: model.model, **model.related_models}

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 72-129
  symbol: `NativeCompiler.compile`
  excerpt: |
    def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:
        if query.model != self.model.name:
            raise SemanticValidationError("unknown_model", ...)
        if query.timezone is not None:
            raise SemanticValidationError("unsupported_query", "Timezone conversion is not supported ...")
        ...
        select = exp.select(*projections).from_(self._table_expr(plan.base, plan))
        if query.metrics and groups:
            select.set("group", exp.Group(expressions=groups))

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 14-14
  symbol: `imports`
  excerpt: |
    from parrot.security import AbstractKMSSigner, LocalHMACSigner

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 23-67
  symbol: `SemanticAuditEntry`
  excerpt: |
    class SemanticAuditEntry(BaseModel):
        schema_version: int = 1
        entry_id: str
        user_id: str
        tenant_id: str
        subject_digest: str
        model_digest: str
        policy_digest: str
        engine: Literal["native"] = "native"
        compiled_sql: str | None
        def canonical_bytes(self) -> bytes:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 70-93
  symbol: `SemanticAuditLedger`
  excerpt: |
    def __init__(self, signer: AbstractKMSSigner | None = None,
                 storage: Callable[[str], Awaitable[None]] | None = None,
                 max_entries: int = 10_000) -> None:
        self.signer: AbstractKMSSigner = signer or LocalHMACSigner()
        self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)
    @property
    def durable(self) -> bool:
        return self.storage is not None

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 95-124
  symbol: `SemanticAuditLedger.append`
  excerpt: |
    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:
        entry.signature = await self.signer.sign(entry.canonical_bytes())
        self.entries.append(entry)
        if self.storage is None:
            if required:
                raise SemanticExecutionError("audit_unavailable", "Audit storage is not configured", ...)
        try:
            await self.storage(entry.model_dump_json())
        except Exception as exc:
            if required:
                raise SemanticExecutionError("audit_unavailable", "Audit storage failed", ...) from exc

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 126-137
  symbol: `SemanticAuditLedger.verify`
  excerpt: |
    async def verify(self, entry: SemanticAuditEntry) -> bool:
        if not entry.signature:
            return False
        return await self.signer.verify(entry.canonical_bytes(), entry.signature)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 158-206
  symbol: `postgres_audit_storage`
  excerpt: |
    def postgres_audit_storage(dsn_or_pool: str | Any, *, table: str = "semantic_audit_events"
    ) -> Callable[[str], Awaitable[None]]:
        sql = (f"INSERT INTO {quoted} (entry_id, created_at, user_id, tenant_id, model, outcome, payload, signature) "
               "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, $8)")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 91-93
  symbol: `SemanticLayerToolkit.__init__`
  excerpt: |
    self._ledger = SemanticAuditLedger(signer=signer, storage=audit_storage)
    self._audit_required = self._ledger.durable if audit_required is None else bool(audit_required)
    self.logger.info("semantic audit_required=%s (durable sink=%s)", ...)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 54-67
  symbol: `LoadedModel`
  excerpt: |
    class LoadedModel(BaseModel):
        name: str
        model: SemanticModel
        related_models: dict[str, SemanticModel]
        policy: ModelPolicy
        members: list[ModelMember]
        schema: PhysicalSchema
        model_digest: str
        policy_digest: str
        compiler_version: str

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 70-95
  symbol: `SemanticModelLoader`
  excerpt: |
    class SemanticModelLoader:
        """Publish an immutable, completely validated model-directory snapshot."""
        def __init__(self, models_dir: Path, *, driver: str) -> None:
        def load(self) -> dict[str, LoadedModel]:
        def reload_if_changed(self) -> bool:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 97-133
  symbol: `SemanticModelLoader._build_snapshot`
  excerpt: |
    policy_path = self.models_dir / f"{name}.policy.yaml"
    if not policy_path.is_file():
        raise SemanticPolicyError("missing_policy", "Each semantic model requires a policy side-file", ...)
    policy = load_policy(policy_path, members, tables, columns)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 28-34
  symbol: `PhysicalSchema`
  excerpt: |
    class PhysicalSchema(BaseModel):
        driver: str
        tables: dict[str, dict[str, str]]

- path: `packages/ai-parrot-semantic/src/parrot/semantic/policy.py`
  lines: 26-33
  symbol: `RoleGrant`
  excerpt: |
    class RoleGrant(BaseModel):
        metrics: list[str] | Literal["*"] = Field(default_factory=list)
        dimensions: list[str] | Literal["*"] = Field(default_factory=list)
        usage: list[str] | Literal["*"] = Field(default_factory=list)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/policy.py`
  lines: 58-75
  symbol: `ModelPolicy`
  excerpt: |
    class ModelPolicy(BaseModel):
        governed: bool = True
        connection: str = ""
        limits: Limits = Field(default_factory=Limits)
        roles: dict[str, RoleGrant] = Field(default_factory=dict)
        masks: dict[str, MaskRule] = Field(default_factory=dict)
        rls: list[RlsRule] = Field(default_factory=list)
        saved_queries: list[SavedQuery] = Field(default_factory=list)
        allowed_functions: list[str] = Field(default_factory=list)
        def digest(self) -> str:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/policy.py`
  lines: 77-93
  symbol: `ModelPolicy.allowed_members`
  excerpt: |
    def allowed_members(self, roles: frozenset[str], members: list[ModelMember]) -> set[str]:
        """Return the union of matching role projection grants."""

- path: `packages/ai-parrot-semantic/src/parrot/semantic/policy.py`
  lines: 114-120
  symbol: `load_policy`
  excerpt: |
    def load_policy(path: Path, members: list[ModelMember], tables: set[str],
                    columns: dict[str, set[str]] | None = None) -> ModelPolicy:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py`
  lines: 11-13
  symbol: `imports`
  excerpt: |
    from parrot.auth import DataPlanePolicyGuard, PermissionContext
    from parrot.auth.exceptions import AuthorizationRequired
    from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py`
  lines: 24-61
  symbol: `PbacGate.authorize_manifest`
  excerpt: |
    class PbacGate:
        """Fail-closed adapter around the core data-plane policy guard."""
        async def authorize_manifest(self, ctx: PermissionContext | None, model: LoadedModel) -> PhysicalResources:
            manifest = PhysicalResources(driver=model.schema.driver,
                tables={f"{model.schema.driver}:{table}" for table in model.schema.tables})
            await self.authorize(ctx, manifest, governed=model.policy.governed)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py`
  lines: 63-100
  symbol: `PbacGate.authorize`
  excerpt: |
    if not governed:
        return
    if ctx is None:
        raise SemanticAccessError("no_subject", "A governed query requires a permission context")
    if not self.available or self.guard is None:
        raise SemanticAccessError("pbac_unavailable", "The PBAC evaluator is unavailable")
    ...
    await self.guard.authorize_source(ctx, resources)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py`
  lines: 103-120
  symbol: `resources_from_ast`
  excerpt: |
    def resources_from_ast(tree: exp.Expression, driver: str) -> PhysicalResources:
        """Resolve physical tables from a qualified AST, excluding CTE aliases."""

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 38-41
  symbol: `SemanticLayerToolkit`
  excerpt: |
    class SemanticLayerToolkit(AbstractToolkit):
        tool_prefix = "sl"

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 110-116
  symbol: `SemanticLayerToolkit._pre_execute`
  excerpt: |
    supplied = kwargs.get("_permission_context")
    bound = current_pctx()
    if supplied is None or bound is None or supplied != bound:
        raise SemanticAccessError("context_required", "A matching trusted semantic context is required")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 289-328
  symbol: `SemanticLayerToolkit._run_governed`
  excerpt: |
    await self._pbac.authorize_manifest(context, loaded)
    expanded = self._catalog.expand_saved_query(query)
    self._catalog.check_query_rights(expanded, roles)
    compiled = await compile_query_sql(expanded, loaded, self._dialect, cache=self._cache)
    governed = await self._pipeline.govern(compiled.sql, model=loaded, ctx=context, roles=roles)
    rows, row_count, truncated, duration_ms, columns = await self._executor.run_with_columns(
        governed, connection=loaded.policy.connection)
    audit_id = await self._audit(loaded, expanded, governed, compiled_sql, "ok", None, started, row_count)

- wiki: `dir:packages/ai-parrot-semantic/src/parrot/semantic` (Q001 score=0.26) — directory overview, 21 entries

- wiki: `file:packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` (Q001 score=0.60)

- wiki: `dir:packages/ai-parrot-semantic/src/parrot/semantic/governance` (follow-up of Q007) — 7 entries

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 546
  symbol: `SemanticLayerToolkit.save_result_as_dataset`
  excerpt: |
    async def save_result_as_dataset(self, result_id: str, name: str, description: str | None = None) -> dict:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py`
  lines: 136-152
  symbol: `GovernancePipeline.govern`
  excerpt: |
    class GovernancePipeline:      # "Fixed-order request-local governance with exact provenance."
        async def govern(

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pbac.py`
  lines: 24-63
  symbol: `PbacGate`
  excerpt: |
    class PbacGate:                # module doc: "Two-phase PBAC gate over DataPlanePolicyGuard — never reaches its fail-open branch."
        async def authorize(

- wiki: `file:packages/ai-parrot-semantic/src/parrot/semantic/audit.py` (Q005 score=1.00)

- wiki: `sym:packages/ai-parrot-semantic/src/parrot/semantic/audit.py#SemanticAuditLedger` (Q005 score=0.93)

- wiki: `file:sdd/tasks/completed/TASK-4474-semantic-audit-ledger.md` (Q005 score=0.97)

- wiki: `file:sdd/state/FEAT-746/findings/.audit/FW-007-audit-ledger-exists.md` (Q005 score=0.94)

- wiki: `file:packages/ai-parrot-semantic/tests/test_audit.py` (Q005 score=0.41)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 14
  symbol: import
  excerpt: |
    from parrot.security import AbstractKMSSigner, LocalHMACSigner

- wiki: `file:sdd/proposals/semantic-layer-rev2.proposal.md` (Q006 score=0.69; Q001 score=0.31)

- wiki: `file:sdd/state/FEAT-704/rev2/findings/F011-feat-713-coupling.md` (follow-up query score=0.28)

- wiki: `file:sdd/tasks/active/TASK-4701-semantic-rust-proposal.md` (Q006 score=0.11)

- wiki: `file:packages/ai-parrot-semantic/README.md` (Q001 score=0.99)

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 1254
  symbol: `U6`
  excerpt: |
    - [x] U6 Who creates `packages/ai-parrot-semantic/` first, FEAT-704 or FEAT-713? — *Resolved 2026-10-25 (owner)*: **FEAT-704 rev 0.3 creates the skeleton (M1)**; FEAT-713's M1 becomes "extend" (resolves `accounting-metrics-layer.spec.md` §8 Q10 — that edit is out of scope for this spec and must be made the next time FEAT-713's spec is touched).

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 1315-1319
  symbol: `Cross-feature dependencies`
  excerpt: |
    - **Cross-feature dependencies**: **FEAT-713** (`accounting-metrics-layer`, draft spec, not yet
      decomposed) extends the skeleton this feature creates (U6, 2026-10-25) — its own spec's §8 Q10 needs
      a follow-up edit (out of scope here) once this spec lands. **FEAT-742** (Rust/PyO3 phase, reserved
      2026-10-25) depends on this feature's IR/compiler shape but is not implemented by it.

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 166-169
  symbol: `rev 0.3 resolutions`
  excerpt: |
    **(rev 0.3)** additionally resolved: no sidemantic dependency or reference (clean-room);
    single compiler with no dispatch; branch is salvage-only; one-to-many joins kept in v1 (U4); FEAT-704
    rev 0.3 creates the satellite skeleton, FEAT-713 extends it (U6); Rust phase gets its own reserved
    FEAT-742 (U3); Ibis NO-GO scope-narrowed to connections (U5).

- path: `sdd/proposals/semantic-layer-rev2.proposal.md`
  lines: null
  symbol: `§0 Origin (decision block 2026-10-21)`
  excerpt: |
    - **sidemantic queda descartado** del todo: ni dependencia, ni referencia de código.
    - **Implementación propia** [...]: un único compilador Pydantic → IR → sqlglot con gramática cerrada [...]
    - La gobernanza (RLS desde PBAC, allowlist por rol, guard sqlglot positivo, AuditLedger) es código de ai-parrot con cualquier motor

- path: `sdd/tasks/active/TASK-4701-semantic-rust-proposal.md`
  lines: null
  symbol: `Scope`
  excerpt: |
    - Preserve the owner-requested research follow-up: invoke sdd-proposal for already reserved FEAT-742 after the final Python compiler/IR lands. No Rust code/crate, dependency or THIRD_PARTY file is implemented by FEAT-704.

- path: `wiki/tools/semantic-layer.md`
  lines: 38
  symbol: (doc)
  excerpt: |
    SQL for DuckDB, Postgres, and BigQuery; compilation is CPU work and runs off

- path: `wiki/tools/semantic-layer.md`
  lines: 100-109
  symbol: `Guarded dataset hand-off`
  excerpt: |
    A bare `DatasetManager`, dataframe, or plain manager factory is rejected.

## Notes

*(FC-001)*
- Results are `list[dict]` rows, not Arrow tables; there is no Decimal handling in the contracts.
- "Independently importable" in the README is not enforced by code: any `parrot.semantic.accounting`
  import runs `parrot/semantic/__init__.py`, which imports `toolkit.py` (and with it `parrot.auth`,
  `parrot.tools.databasequery`, `jsonschema` via `ossie`). No test asserts the independence.
- Package module list (from the parent's tree listing): `audit, bootstrap, cache, catalog, context, errors,
  execution, handoff, loader, model, models, ossie, policy, results, toolkit, version`, sub-packages
  `engines/`, `governance/`, `schemas/`, `sql/`. No `accounting/` directory.
*(FC-002)*
- `_FILTER_DIALECTS = {"duckdb", "postgres"}` — the native compiler's typed filters target these two
  dialects; the old spec's golden set was duckdb / postgres / bigquery.
- Only lines 1-140 of `native.py` were read; window functions or `CASE` handling beyond line 140 were not
  inspected.
- [cross-lane: type=git_log, intent=confirm when the sidemantic engine was replaced by NativeCompiler and whether a FEAT-742 Rust compiler branch touches engines/]
*(FC-004)*
- The ledger is typed to `SemanticAuditEntry`; an accounting entry would need either a generic/duck-typed
  ledger (anything with `canonical_bytes()`, `signature`, `entry_id`, `model_dump_json()`), a subclass, or
  extra optional fields on the existing entry. `postgres_audit_storage` reads `user_id`, `tenant_id`,
  `model`, `outcome` out of the payload, so an accounting entry reusing that sink must carry those keys.
- The default policy differs: semantic audit is required only when a durable sink is configured
  (`audit_required=None` ⇒ `ledger.durable`); the old FEAT-713 spec defaulted to `required` always.
- The in-memory deque retains entries (bounded 10 000); the old spec said "no in-memory retention".
*(FC-005)*
- The old FEAT-713 spec's PBAC semantics were "no guard configured ⇒ allow (same as DatasetManager)" with
  dataset-typed resource names `accounting:<tenant>:<model>:<metric>` through `DatasetPolicyGuard`. The
  shipped semantic layer is the opposite posture: fail-closed, table-level resources, member-level rights
  from the policy side-file. A revised accounting layer in the same package has to pick one.
- Toolkit tool methods seen in the outline (lines 123-206, 451, 546): `list_models`, `list_metrics`,
  `get_dimensions`, `get_dimension_values`, `search_data_model`, `list_saved_queries`, `compile_query`,
  `query_metrics`, `reload`, `run_sql` (host opt-in), `save_result_as_dataset` (needs a sink factory).
  An accounting toolkit named `list_metrics` under prefix `finance` does not collide (`finance_list_metrics`
  vs `sl_list_metrics`).
- `loader.py` lines 141+ and `toolkit.py` lines 141-284 / 329+ were not read in full (outline only);
  `GovernancePipeline.govern` internals were not opened by this lane.
- Tenant handling in the loader: none observed in lines 1-140 (flat directory, `driver` only).
*(FW-001)*
- Native compiler API outline (wiki): `_derived_expr` "Lower the closed arithmetic grammar; division returns NULL for a zero denominator"; `_grain_expr` "DATE_TRUNC expression for the requested grain"; `_plan` "only many-to-one hops from the measure model". The generic layer already has a closed arithmetic grammar for derived metrics, zero-denominator NULL and grain bucketing — three things the old FEAT-713 spec planned to build from scratch (M3, M5). It has no account sets, sign normalisation, effective-dated membership, assertions or cumulative windows (none appear in any API outline).
- The PBAC gate is over `DataPlanePolicyGuard`; the old FEAT-713 spec named `DatasetPolicyGuard`.
- Line numbers come from a `grep -n` of definitions (1 grep), not from the wiki pages, which carry no line numbers.
- [cross-lane: type=read, intent=confirm that importing parrot.semantic.accounting would trigger parrot/semantic/__init__.py and therefore the eager SemanticLayerToolkit import (jsonschema, DatabaseQueryToolkit) — relevant to the README rule "accounting must remain independently importable"]
*(FW-005)*
- The old spec's M7 (`AccountingAuditEntry` + `AccountingAuditLedger`, `FINANCE_AUDIT_MODE=required`) duplicates the ledger mechanics that now exist. Open design point for the revision: a second entry type on the same ledger class, an extension of `SemanticAuditEntry`, or a separate ledger — the existing ledger is typed to `SemanticAuditEntry` and its Postgres sink to one table.
- The semantic ledger keeps SQL text in the entry (`compiled_sql`, `governed_sql`); the old accounting design stored hashes plus a `lineage_ref` and rebuilt lineage, "never inline".
- Line numbers from one `grep -n` of definitions; field list from the wiki page content.
*(FW-006)*
- Consequences for the revision: (1) old M1, AC2 and Q10 are closed by a recorded owner decision, not merely by the merge; (2) the "standalone, never imports parrot.semantic.* outside itself" rule is now backed only by the README sentence "independently importable" — whether accounting may *reuse* the audit ledger, executor, PBAC gate or loader conventions is not decided anywhere in the graph; (3) a new accounting compiler is a second compiler in a package whose spec says "single compiler with no dispatch", and FEAT-742 will replace the generic one — the revision must say whether the accounting compiler is in or out of FEAT-742's scope.
- No decision, lesson or memory about a DuckDB-backed dataset store or about `parrot.semantic.accounting` exists beyond the FEAT-713 and FEAT-880 documents (queries Q003 and the follow-up "accounting extension independently importable" return only those).
- `sdd/specs/semantic-layer.spec.md` passages were read directly (1 file read, lines 164-170, 1254, 1313-1320); proposal and task excerpts come from wiki page content, hence no line numbers.
- [cross-lane: type=git_log, intent=check whether FEAT-742 has a branch or proposal yet (sdd/proposals/semantic-layer-rust-compiler.proposal.md does not appear in the graph)]

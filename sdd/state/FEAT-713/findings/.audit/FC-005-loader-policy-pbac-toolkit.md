---
id: FC-005
query_id: Q017, Q018, Q019, Q020
type: read
intent: "Model loading conventions, governed run path, PBAC gate and policy schema of the semantic layer — what an accounting layer would follow, reuse or diverge from."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-005 — Loader is a flat models directory with a mandatory `<model>.policy.yaml`; PBAC is `DataPlanePolicyGuard` over physical tables (fail-closed), not `DatasetPolicyGuard`; the toolkit prefix is `sl`

## Summary

`SemanticModelLoader(models_dir, driver=)` loads every model document in one **flat** directory, requires a
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

## Citations

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
  lines: 74-108
  symbol: `SemanticLayerToolkit.__init__`
  excerpt: |
    self._loader = SemanticModelLoader(models_dir, driver=dialect)
    self._models = self._loader.load()
    if any(model.policy.governed for model in self._models.values()) and dataplane_guard is None:
        raise SemanticPolicyError("guard_required", "Governed semantic models require a data-plane guard")
    self._pbac = PbacGate(dataplane_guard)
    self._pipeline = GovernancePipeline(pbac=self._pbac, rls=RlsPushdown(self._rls_registry), ...)
    self._cache = CompileCache()
    self._executor = Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver())

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

## Notes

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

---
id: F006
query_id: Q006
type: read
intent: "Measure how deeply the branch loader depends on the sidemantic object graph"
executed_at: 2026-10-25T10:30:00Z
duration_ms: 5000
parent_id: null
depth: 0
---

# F006 — `loader.py` (386 lines) is the coupling point: `LoadedModel.layer: Any` is a sidemantic `SemanticLayer`

## Summary

`SemanticModelLoader.load()` imports `sidemantic.SemanticLayer` and `sidemantic.loaders.load_from_directory`, stages the models dir in a temp copy, imports Ossie documents through sidemantic's importer (with a compatibility shim `_make_ossie_importer_compatible` that patches Ossie primary keys into fields), rejects `security:` blocks, and then derives everything the rest of the satellite needs — `PhysicalSchema.tables`, `ModelMember` list, member→column map, table scoping per policy — by walking `layer.graph.models`. `LoadedModel` stores `layer: Any` plus `policy`, `members`, `schema`, `model_digest`, `policy_digest`, `engine_version`. Four helpers (`_members`, `_scope_tables`, `_member_columns`, `_physical_tables`) are the only readers of the sidemantic graph in this file.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 58-70
  symbol: `LoadedModel` (branch)
  excerpt: |
    class LoadedModel(BaseModel):
        name: str
        layer: Any
        policy: ModelPolicy
        members: list[ModelMember]
        schema: PhysicalSchema
        model_digest: str
        policy_digest: str
        engine_version: str

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 83-96
  symbol: `SemanticModelLoader.load` (branch)
  excerpt: |
    def load(self) -> dict[str, LoadedModel]:
        from sidemantic import SemanticLayer, __version__
        from sidemantic.loaders import load_from_directory
        ...
        layer = SemanticLayer(dialect=self.driver, auto_register=False, engine="python")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 209-216
  symbol: `_make_ossie_importer_compatible` (branch)
  excerpt: |
    """Add fields implied by Ossie primary keys for sidemantic 0.12.0 lowering. [...] Sidemantic 0.12.0 requires that repetition."""

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 258-359
  symbol: `_members`, `_scope_tables`, `_member_columns`, `_physical_tables` (branch)
  excerpt: |
    def _members(layer: Any) -> list[ModelMember]:
        """Derive the public member catalog from the loaded sidemantic graph."""
        for model in layer.graph.models.values():
            for dimension in model.dimensions: ...

- path: `packages/ai-parrot-semantic/src/parrot/semantic/loader.py`
  lines: 40-56
  symbol: `PhysicalSchema.sqlglot_schema` (branch)
  excerpt: |
    def sqlglot_schema(self) -> dict[str, dict[str, dict[str, str]]]:
        """Return the nested mapping accepted by ``sqlglot`` qualification."""

## Notes

`PhysicalSchema`, `LoadedModel` (minus the `layer` type), digests and the policy binding are engine-neutral and reusable; only the graph source changes. The file was written by ai-parrot authors (calls the sidemantic API, contains no sidemantic code) — reading it does not breach the clean-room rule, but its sidemantic-API glue is not worth keeping.

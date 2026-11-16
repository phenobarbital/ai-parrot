---
id: FW-001
query_id: Q001
type: wiki_query
intent: "Orient: what the semantic layer package is today (modules, public surface, compiler engine). Includes Q007 (wiki_page of the toolkit and sibling modules)."
executed_at: 2026-11-11T22:40:00Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-001 — `parrot.semantic` on dev is a complete governed layer (21 entries): one native sqlglot compiler, a fixed-order governance pipeline, an executor, a signed audit ledger and a guarded dataset hand-off; there is no `accounting` subpackage

## Summary

The wiki directory page lists 21 entries under `packages/ai-parrot-semantic/src/parrot/semantic`: `engines/` (sole `NativeCompiler`, no dispatch), `governance/` (pbac, lineage, rls, masking, guard, pipeline), `schemas/`, `sql/`, plus `audit`, `bootstrap`, `cache`, `catalog`, `context`, `errors`, `execution`, `handoff`, `loader`, `model`, `models`, `ossie`, `policy`, `results`, `toolkit`, `version`. The package `__init__` exports only `__version__`, `SemanticQuery`, `SemanticQueryResult`, `SemanticLayerToolkit` and imports the toolkit eagerly. `SemanticLayerToolkit` (`tool_prefix = "sl"`) takes `models_dir`, `dialect`, `dataplane_guard`, `rls_registry`, `database_toolkit`, `signer`, `audit_storage`, `audit_required`, `allow_raw_sql`, `dataset_manager_factory` and funnels every query through `_run_governed`. The names `CompiledQuery`, `GovernedQuery`, `Limits`, `Grain` are taken in `models.py`.

## Citations

- wiki: `dir:packages/ai-parrot-semantic/src/parrot/semantic` (Q001 score=0.26) — directory overview, 21 entries
- wiki: `file:packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py` (Q001 score=0.60)
- wiki: `dir:packages/ai-parrot-semantic/src/parrot/semantic/governance` (follow-up of Q007) — 7 entries

- path: `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py`
  lines: 1-7
  symbol: `__all__`
  excerpt: |
    from .version import __version__
    from .models import SemanticQuery, SemanticQueryResult
    from .toolkit import SemanticLayerToolkit
    __all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 38-41
  symbol: `SemanticLayerToolkit`
  excerpt: |
    class SemanticLayerToolkit(AbstractToolkit):
        """Catalog, compile and metric query surface over one governance pipeline."""
        tool_prefix = "sl"

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 289
  symbol: `SemanticLayerToolkit._run_governed`
  excerpt: |
    async def _run_governed(self, query: SemanticQuery, *, execute: bool) -> SemanticQueryResult | dict:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 546
  symbol: `SemanticLayerToolkit.save_result_as_dataset`
  excerpt: |
    async def save_result_as_dataset(self, result_id: str, name: str, description: str | None = None) -> dict:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`
  lines: 29-46
  symbol: `compile`
  excerpt: |
    async def compile(query: SemanticQuery, model: LoadedModel, dialect: str, *, cache: CompileCache | None = None) -> CompiledQuery:
        """Compile under to_thread, or return immutable pre-governance cache output."""
        compiled = await asyncio.to_thread(NativeCompiler(model).compile, query, dialect)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 45-72
  symbol: `NativeCompiler`
  excerpt: |
    class NativeCompiler:   # "Compile the closed semantic grammar to deterministic dialect SQL."
        def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 192-244
  symbol: `CompiledQuery`
  excerpt: |
    class CompiledQuery(BaseModel, frozen=True):      # 192 — pre-governance compiler output
    class GovernedQuery(BaseModel, frozen=True):      # 202
    class SemanticQueryResult(BaseModel):             # 217
    class Limits(BaseModel):                          # 230
    class ModelMember(BaseModel):                     # 244

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 102
  symbol: `SemanticQuery`
  excerpt: |
    class SemanticQuery(BaseModel):   # validate_structure, canonical_json, validate_against

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

## Notes

- Native compiler API outline (wiki): `_derived_expr` "Lower the closed arithmetic grammar; division returns NULL for a zero denominator"; `_grain_expr` "DATE_TRUNC expression for the requested grain"; `_plan` "only many-to-one hops from the measure model". The generic layer already has a closed arithmetic grammar for derived metrics, zero-denominator NULL and grain bucketing — three things the old FEAT-713 spec planned to build from scratch (M3, M5). It has no account sets, sign normalisation, effective-dated membership, assertions or cumulative windows (none appear in any API outline).
- The PBAC gate is over `DataPlanePolicyGuard`; the old FEAT-713 spec named `DatasetPolicyGuard`.
- Line numbers come from a `grep -n` of definitions (1 grep), not from the wiki pages, which carry no line numbers.
- [cross-lane: type=read, intent=confirm that importing parrot.semantic.accounting would trigger parrot/semantic/__init__.py and therefore the eager SemanticLayerToolkit import (jsonschema, DatabaseQueryToolkit) — relevant to the README rule "accounting must remain independently importable"]

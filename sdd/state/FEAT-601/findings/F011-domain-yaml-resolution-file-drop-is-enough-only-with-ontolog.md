---
id: F011
query_id: Q011
type: read
intent: How TenantOntologyManager.resolve locates domain YAML; is a new defaults/domains/procedures.ontology.yaml sufficient; any domain registry
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F011 — Domain YAML resolution: file drop is enough only with ontology_dir=defaults

## Summary
`resolve(tenant_id, domain)` builds a chain of base, then `{ontology_dir}/{domains_dir}/{domain}.ontology.yaml`, then `{ontology_dir}/clients/{tenant}.ontology.yaml`, and merges it with `OntologyMerger`. Only the **base** file falls back to `OntologyParser.get_defaults_dir()`. The domain file is only looked up under `ontology_dir`, which defaults to `conf.ONTOLOGY_DIR` = `BASE_DIR/ontologies`. So a packaged `procedures.ontology.yaml` is found only when the manager is built with `ontology_dir=OntologyParser.get_defaults_dir()`. Both `ContractGraphLoader._default_tenant_manager` and `parrot_tools/legal/wiki_store.py` do exactly that. There is no enum or registry of domains; the file name is the domain key. The resolve cache is keyed by `tenant_id` only, so a later `resolve(t, domain="procedures")` on a shared manager returns whatever domain was cached first.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
  lines: 48-90
  symbol: `TenantOntologyManager.__init__`
  excerpt: |
    def __init__(self, ontology_dir=None, base_file=None, domains_dir=None, clients_dir=None,
                 db_template=None, pgvector_schema_template=None,
                 concept_catalog_service=None, schema_overlay_service=None)
    self._ontology_dir = Path(ontology_dir) if ontology_dir else ONTOLOGY_DIR
    self._domains_dir = domains_dir or ONTOLOGY_DOMAINS_DIR or "domains"
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
  lines: 92-106
  symbol: `TenantOntologyManager.resolve (cache)`
  excerpt: |
    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext:
        if tenant_id in self._cache:
            return self._cache[tenant_id]
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
  lines: 107-131
  symbol: `TenantOntologyManager.resolve (chain)`
  excerpt: |
    base_path = self._ontology_dir / self._base_file
    if base_path.exists(): chain.append(base_path)
    else:  defaults_dir = OntologyParser.get_defaults_dir() ...
    if domain:
        domain_path = (self._ontology_dir / self._domains_dir / f"{domain}.ontology.yaml")
        if domain_path.exists(): chain.append(domain_path)
        else: logger.debug("Domain ontology '%s' not found at %s", ...)
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
  lines: 280-310
  symbol: `TenantOntologyManager._build_yaml_chain`
  excerpt: |
    (same logic, used by resolve_with_overlay; domain path has no defaults fallback)
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/parser.py`
  lines: 29-62
  symbol: `OntologyParser.load`
  excerpt: |
    raw = yaml.safe_load(f) or {}
    definition = OntologyDefinition.model_validate(raw)
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/parser.py`
  lines: 93-99
  symbol: `OntologyParser.get_defaults_dir`
  excerpt: |
    @staticmethod
    def get_defaults_dir() -> Path:
        return _DEFAULTS_DIR
- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 125-135
  symbol: `ONTOLOGY_DIR / ONTOLOGY_DOMAINS_DIR`
  excerpt: |
    ONTOLOGY_DIR = Path(config.get("ONTOLOGY_DIR", fallback=BASE_DIR.joinpath("ontologies")))
    ONTOLOGY_DOMAINS_DIR = config.get("ONTOLOGY_DOMAINS_DIR", fallback="domains")
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 215-245
  symbol: `ContractGraphLoader._default_tenant_manager / context`
  excerpt: |
    return TenantOntologyManager(
        ontology_dir=Path(ontology_dir) if ontology_dir else OntologyParser.get_defaults_dir())
    ctx = self._tenant_manager.resolve(self.catalog.tenant_id, domain=self.domain)
    missing = {"Contract", "Obligation", "Party"} - set(ctx.ontology.entities)
    if missing: raise ContractsDomainNotLoaded(...)

## Notes
- The brainstorm assumption that dropping the file in `defaults/domains/` makes `resolve(domain="procedures")` work is only true with a dedicated manager (`ontology_dir=get_defaults_dir()`). The contracts module copies this pattern and also checks that the expected entities are present (`ContractsDomainNotLoaded`). FEAT-601 should do the same, e.g. `ProceduresDomainNotLoaded` if `{Procedure, Step}` is missing.
- A missing domain file is only logged at debug level, so the failure is silent: the result is just the base ontology.
- `OntologyMerger` lives in `merger.py` (18.7K). I did not read it in this lane.


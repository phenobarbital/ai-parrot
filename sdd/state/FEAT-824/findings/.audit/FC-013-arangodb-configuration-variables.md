---
id: FC-013
query_id: Q013
type: grep
intent: "Which configuration variables drive ArangoDB today?"
executed_at: 2026-11-06T13:46:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-013 — No central ARANGO* constants in conf.py; connection settings are resolved ad hoc by each consumer under the `ARANGODB_` prefix

## Summary

`grep -rnE "ARANGO[A-Z_]*|ONTOLOGY_(DB_TEMPLATE|PGVECTOR_SCHEMA_TEMPLATE|GRAPH_BACKEND|BACKEND)|WIKI_BACKEND|GRAPHINDEX_BACKEND" packages/ai-parrot/src/parrot/conf.py` matches only the two ontology templates — `conf.py` defines **no** `ARANGODB_*` constant and no backend-selector variable (`ONTOLOGY_BACKEND`, `WIKI_BACKEND`, `GRAPHINDEX_BACKEND` do not exist there). Distinct names across all `src` trees (`grep -rhoE "\bARANGO[A-Z_]+\b"`): `ARANGODB_HOST` (7), `ARANGODB` (6, the env *prefix*), `ARANGODB_PASSWORD` (4), `ARANGODB_USERNAME` (2), `ARANGODB_PORT` (2), `ARANGODB_DATABASE` (2), `ARANGODB_PROTOCOL` (1). They are read in three places: the wiki project config (configurable credential prefix, default `ARANGODB`), the GraphIndex loader (`resolve_setting("ARANGODB_HOST", ...)`), and the `arangodbsearch` tool (`config.get('ARANGODB_HOST', 'localhost')`). The Postgres plane, by contrast, has a proper settings resolver (`GRAPHINDEX_PG_DSN / _PG_SCHEMA / _EMBEDDING_DIM / _ANN_INDEX_KIND`, FC-010).

## Citations

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 151-154
  symbol: `ONTOLOGY_DB_TEMPLATE` / `ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE`
  excerpt: |
    151:ONTOLOGY_DB_TEMPLATE = config.get("ONTOLOGY_DB_TEMPLATE", fallback="{tenant}_ontology")
    154:ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE = config.get("ONTOLOGY_PGVECTOR_SCHEMA_TEMPLATE", fallback="{tenant}")

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 610-936
  symbol: wiki namespace credential prefix / `resolve_arango_params`
  excerpt: |
    610:            credentials (e.g. ``ARANGODB`` -> ``ARANGODB_HOST``,
    650:        description=("Env var prefix for credentials (e.g. ARANGODB -> " "ARANGODB_HOST, ARANGODB_PASSWORD)"),
    909:        key: Full variable name, e.g. ``"ARANGODB_HOST"``.
    936:        Connection params dict for ``AsyncDB("arangodb", params=...)``:

- path: `packages/ai-parrot/src/parrot/loaders/graphindex.py`
  lines: 291-296
  symbol: ArangoDB host resolution in the GraphIndex loader
  excerpt: |
    291:        resolved_host = resolve_setting("ARANGODB_HOST", explicit=base.get("host") or host)
    295:                "Missing required ArangoDB setting: ARANGODB_HOST (pass arango_host=... / arango={'host': ...} "
    296:                "or set ARANGODB_HOST; an explicit 127.0.0.1 is accepted)"

- path: `packages/ai-parrot-tools/src/parrot_tools/arangodbsearch.py`
  lines: 171-171
  symbol: tool-level Arango config
  excerpt: |
    171:            "host": config.get('ARANGODB_HOST', 'localhost'),

## Notes

- The draft's §8.3 navconfig block (`ONTOLOGY_BACKEND`, `ONTOLOGY_PG_DSN`, `ONTOLOGY_SNAPSHOT_DIR`, `KNOWLEDGE_BACKEND`, `KNOWLEDGE_SURREAL_URL`, `KNOWLEDGE_NAMESPACE`, `KNOWLEDGE_SYNC_ENDPOINT`) introduces seven new variables; none exists today. Backend selection today is per call/instance (`create_wiki_store(backend=...)`, `WikiNamespaceConfig.backend`, GraphIndex loader `backend=`), not global env.
- Wiki backend selection lives in the per-repo project config (`project.py:228` help text begins `'sqlite', 'memory', 'arangodb'. Also accepts a name ` — the rest of the line was not read, so whether it mentions `postgres` is unverified).

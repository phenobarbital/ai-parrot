---
id: FC-012
query_id: Q012
type: grep
intent: "Which distributions declare ArangoDB dependencies/extras, and is surrealdb / rdflib / pyshacl / pgvector declared anywhere?"
executed_at: 2026-11-06T13:45:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-012 — ArangoDB enters through two declarations only; `surrealdb`, `rdflib`, `pyshacl` are declared nowhere

## Summary

`grep -nE "arango|surreal|rdflib|pyshacl|pgvector|asyncdb|asyncpg|networkx|sqlite-vec|aiosqlite" pyproject.toml packages/*/pyproject.toml`. ArangoDB drivers are pulled in by exactly two declarations: `ai-parrot[db]` → `asyncdb[...,arangodb,...]` (the driver the ontology store, the wiki store and the GraphIndex loader actually use, via `AsyncDB("arangodb", ...)`), and `ai-parrot-embeddings[arango]` → `python-arango-async==1.2.0` (the Arango *vector store*, also part of that package's `all` extra). Core `ai-parrot` already depends on `asyncdb>=2.16.2` (asyncpg, aiosqlite, pgvector), `networkx>=3.0`, `aiosqlite>=0.17`; the Postgres graph/wiki plane has its own extra `graphindex-postgres = ["asyncpg>=0.29", "pgvector>=0.2"]`. **No `surrealdb`, `rdflib` or `pyshacl`** in any `pyproject.toml`, and no `surreal` string in any `src` tree. The GraphIndex registry names an install extra `"arangodb"` for its Arango backend, but no extra called `arangodb` exists in `packages/ai-parrot/pyproject.toml` (the comment at L396-397 says the `arango` extra moved to `ai-parrot-embeddings`).

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 233-239
  symbol: `[project.optional-dependencies] db`
  excerpt: |
    # Database / query tools (querysource, psycopg, advanced asyncdb extras)
    db = [
        "querysource>=5.1.2",
        "psycopg-binary>=3.2.12",
        "jq==1.7.0",
        "asyncdb[bigquery,mongodb,arangodb,influxdb,boto3,sqlalchemy]>=2.16.2",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 294-299
  symbol: `graphindex-postgres` extra
  excerpt: |
    # GraphIndex Postgres backend (FEAT-520) — bitemporal graph + wiki plane over
    # asyncpg. Zero SQLAlchemy (U4/D8); PgVectorStore is explicitly excluded.
    graphindex-postgres = [
        "asyncpg>=0.29",
        "pgvector>=0.2",
    ]

- path: `packages/ai-parrot/pyproject.toml`
  lines: 132-205
  symbol: core dependencies
  excerpt: |
    132:    # Async DB — base only (asyncpg, aiosqlite, pandas, pgvector)
    133:    "asyncdb>=2.16.2",
    203:    "networkx>=3.0",
    205:    "aiosqlite>=0.17",

- path: `packages/ai-parrot/pyproject.toml`
  lines: 396-397
  symbol: removed `arango` extra note
  excerpt: |
    396:# ArangoDB graph database — MOVED to ai-parrot-embeddings[arango]
    397:# arango extra removed in FEAT-201; use ai-parrot-embeddings[arango] instead

- path: `packages/ai-parrot-embeddings/pyproject.toml`
  lines: 63-99
  symbol: `pgvector` / `arango` / `all` extras
  excerpt: |
    63:pgvector = [
    64:    "pgvector==0.4.1",
    70:arango = [
    71:    "python-arango-async==1.2.0",
    99:    "ai-parrot-embeddings[huggingface,google,openai,pgvector,milvus,arango,bigquery,faiss,chroma,lancedb,reranker-local,reranker-llm,multimodal]",

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py`
  lines: 248-251
  symbol: `arangodb` backend spec extra
  excerpt: |
    249:        name="arangodb",
    251:        extra="arangodb",

## Notes

- `grep -rli "surreal" packages/*/src packages/*/pyproject.toml pyproject.toml` (run by the parent during planning) returned nothing.
- Root `pyproject.toml` only carries `asyncdb>=2.16.2` (L198) and comments about asyncdb pins; `packages/parrot-formdesigner/pyproject.toml:39` also depends on `asyncdb>=2.16.2`.
- The licence exposure is therefore: (a) the ArangoDB **server** users deploy, and (b) two client drivers (`asyncdb[arangodb]` → its Arango driver; `python-arango-async`). ai-parrot ships no ArangoDB binary. Removing the drivers means dropping `arangodb` from the `db` extra and the `arango` extra from `ai-parrot-embeddings` (+ its `all`).
- A `surrealdb` SDK would be a brand-new dependency (and a new extra); `asyncdb` driver support for SurrealDB was not checked.
- [cross-lane: type=wiki_query, intent=does asyncdb ship a SurrealDB driver (project convention is to go through asyncdb.AsyncDB rather than raw SDKs)]

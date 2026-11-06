---
id: F032
query_id: Q032
type: read
intent: "User-supplied evidence for the licence and engine premises: what does the research note say about ArangoDB's licence, the candidate engines and SurrealDB?"
executed_at: 2026-11-06T15:20:00Z
duration_ms: 0
parent_id: F021
depth: 1
---

# F032 — The graph-database research note documents the ArangoDB licence terms and compares ten engines; it ranks PostgreSQL + AGE first, FalkorDB second and SurrealDB-server third

## Summary

`sdd/proposals/Grafos open source para ai-parrot.md` (68 lines, untracked when read, dated "noviembre de 2026") is the research behind the draft. Read in full after the user pointed to it. (1) **ArangoDB licence**, with links to ArangoDB's own pages: since 3.12 the source is BUSL-1.1 and the prebuilt binaries / Docker images carry an "ArangoDB Community License" that grants no commercial-use, distribution or embedding rights, caps a cluster at 100 GiB with a technical shutdown, and adds registration and audit clauses; the note calls the source BUSL itself "benigno para uso interno" — the exposure is the binary licence. (2) **Engine matrix**: ten engines compared on licence, single-container deployment, free multi-graph, multi-process writers, in-engine vector + full-text, asyncio driver, RDF support and GraphRAG ecosystem. JanusGraph is excluded because it needs Cassandra/Scylla/HBase and delegates text to Elasticsearch; NebulaGraph CE because it needs 9 containers. (3) **SurrealDB 3.3.4**: BSL 1.1 (source-available, not OSI; SDKs Apache/MIT), unlimited namespaces/databases, multi-process in server mode, embedded mode single-process, HNSW/DiskANN + BM25 + RRF — "la única pila con BM25 real" — but SDK 3.x still beta and transactions only over WebSocket. (4) **HelixDB**: the Python client `helix-py` is GPL-3.0, "que un proyecto MIT no puede vendorizar ni declarar como dependencia dura", and its embedded mode documents no multi-process access. (5) **No embedded engine supports several writer processes** on one file; a shared local graph needs a daemon, ideally the same engine as the central server. (6) **Recommendation of the note**: PostgreSQL 17/18 + Apache AGE + pgvector as the reference backend in both modes, FalkorDB as the lighter second implementation, "SurrealDB servidor en ambos modos" as the third-best complete architecture, and ArangoDB kept as an optional legacy adapter. (7) The note is the origin of the draft's ontology projection (class hierarchies, SKOS and closures materialised at ingest, the OWL/SHACL master kept as Turtle in git) and of the `Document → Section → Chunk` lexical schema.

## Citations

- path: `sdd/proposals/Grafos open source para ai-parrot.md`
  lines: 3-9
  symbol: `ArangoDB ya no es una apuesta open-source segura`
  excerpt: |
    desde 3.12 (marzo 2024) el código es BUSL-1.1 y los binarios/imágenes Docker Community llevan una
    "ArangoDB Community License" que prohíbe el uso comercial en producción, limita a 100 GiB con
    apagado técnico y añade cláusulas de auditoría
    ...
    El BUSL del código fuente es benigno para uso interno (solo prohíbe ofrecer ArangoDB como DBaaS a terceros)

- path: `sdd/proposals/Grafos open source para ai-parrot.md`
  lines: 11-17
  symbol: `Solo seis candidatos son OSI y aptos para Docker, y ninguno lo tiene todo`
  excerpt: |
    Son *source-available*, no OSI: ... **SurrealDB** (BSL 1.1 con reversión a Apache-2.0 a cuatro años; SDKs Apache/MIT)
    ...
    El único conflicto directo detectado es **helix-py (GPL-3.0)**, que un proyecto MIT no puede vendorizar ni declarar como dependencia dura
    ...
    JanusGraph requiere Cassandra/Scylla/HBase y delega texto en Elasticsearch

- path: `sdd/proposals/Grafos open source para ai-parrot.md`
  lines: 19-34
  symbol: `engine comparison table`
  excerpt: |
    | **SurrealDB** 3.3.4 (4.0-beta.1) | BSL 1.1 | `surrealdb/surrealdb`; también embebido (mono-proceso) | Sí: namespaces/databases ilimitados | Servidor sí; embebido 1 proceso; transacciones solo por WebSocket | HNSW/DiskANN + BM25 + RRF | `AsyncSurreal` (SDK 3.x aún beta) | No | Escaso |
    ...
    la única pila con BM25 real es SurrealDB (`FULLTEXT` BM25 + `search::rrf`) y, por la vía SQL, el `ts_rank`/pg_trgm de PostgreSQL

- path: `sdd/proposals/Grafos open source para ai-parrot.md`
  lines: 36-42
  symbol: `Ningún motor embebido sirve para varios procesos: el modo local exige un demonio`
  excerpt: |
    SurrealDB embebido: "Embedded databases are accessed by a single process"
    HelixDB ... no documenta bloqueo de ficheros ni acceso multi-proceso y su arquitectura cloud es explícitamente de "single writer process"
    si el modo local va a requerir un demonio de todos modos, **ese demonio debería ser el mismo motor que el servidor central**

- path: `sdd/proposals/Grafos open source para ai-parrot.md`
  lines: 44-52
  symbol: `Ontologías y GraphRAG no caben en un solo motor open-source`
  excerpt: |
    lo que el router ontológico de ai-parrot necesita (jerarquías de clases, esquemas SKOS, cierre de `subPropertyOf`,
    relaciones transitivas, validación de forma) se **proyecta sin pérdida a un property graph** ... cierre materializado
    en ingesta, y el OWL/SHACL maestro guardado como Turtle en el repo y validado en cliente
    capa léxica `Document → Section → Chunk` con `NEXT_CHUNK`, capa de dominio con `__Entity__`

- path: `sdd/proposals/Grafos open source para ai-parrot.md`
  lines: 54-62
  symbol: `Arquitectura recomendada: un motor de referencia, dos despliegues y un log de deltas`
  excerpt: |
    La recomendación es **PostgreSQL 17/18 con Apache AGE + pgvector + tsvector/pg_trgm como backend de referencia en los dos modos**,
    con FalkorDB como segunda implementación ... y ArangoDB mantenido como adaptador opcional heredado
    ...
    "SurrealDB servidor en ambos modos" la tercera (un solo dialecto SurrealQL, BM25 real, namespaces ilimitados,
    pero BSL, SDK 3.x aún beta y transacciones solo por WebSocket)

## Notes

- The note's own recommendation is PostgreSQL + AGE. **It does not say AGE cannot be installed on Amazon RDS**; that exclusion comes from the draft (§1, D1) and from the user's statement of 2026-11-06, together with the selection criteria the user gave then: only open-source, non-enterprise editions; no paid SaaS; fewer moving parts (JanusGraph needs Cassandra and Elasticsearch).
- FalkorDB (second in the note) is SSPLv1, serialises writes per graph, has no multi-statement transactions and TF-IDF rather than BM25; the draft's D4 passes over it for those reasons.
- The external links in the note (ArangoDB licence pages, SurrealDB licence and docs, helix-py) were **not re-fetched** in this research; the note is the evidence, the links are its sources.
- The note reads "PostgreSQL + AGE … conserva la arquitectura L0/L1/L2" — the L0/L1/L2 vocabulary of the draft comes from here and from `parrot.knowledge.retrieval` (F029).
- The note recommends keeping ArangoDB as an optional legacy adapter ("barato y razonable"); the draft §9.5 keeps it only until parity; the user chose removal from the whole workspace (U2).
- SDK status in the note: `surrealdb` 3.0.0b10 on PyPI — a beta; the draft's spike G1 is the gate for it.
- The file was untracked (`??`) when read, so the citation resolves only in a checkout that has it.
- User statement of 2026-11-06, consistent with lines 36-42 of the note: HelixDB is single-writer — it serves multiple readers but not multiple writers, whereas SQLite (WAL) lets several processes write, serialised. This is the reason HelixDB was discarded, in addition to the `helix-py` licence.

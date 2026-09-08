---
kind: file
jira_key: null
source_file: sdd/proposals/claude_brainstorm-graphindex-postgres.md
fetched_at: 2026-09-03T00:00:00Z
summary_oneline: Postgres backend for GraphIndex with native bitemporal plane (tstzrange) and one-pass hybrid retrieval (graph + KNN + BM25 + reranking)
---

# Brainstorm — FEAT-XXX-graphindex-postgres

> Backend Postgres para GraphIndex con plano temporal nativo y retrieval híbrido
> one-pass (graph + vector + BM25 + re-ranking). Documento de entrada para
> `/sdd-brainstorm` formal. Todo import path no verificado lleva `⚠️ VERIFY`.

## 0. Contexto y motivación

GraphIndex (usado por LLMwiki y OntoGraph) tiene hoy backends SQLite y ArangoDB.
Se propone un tercer backend sobre PostgreSQL con dos objetivos que los otros
dos no pueden cumplir:

1. **Temporalidad como propiedad del motor, no del código.** `tstzrange` +
   exclusion constraints hacen imposible a nivel de base de datos que dos
   versiones del mismo concepto se solapen. En Arango la invariante es
   disciplina de ingesta; en Postgres la rechaza el motor. Conecta directamente
   con el modelo bitemporal ya acordado (hilo "Versionamiento temporal en
   grafos de conocimiento") y con OQ5 del cerebro jurídico.
2. **Retrieval híbrido cuádruple en el mismo snapshot transaccional:** grafo
   temporal + KNN pgvector + BM25 + re-ranking, con las tres primeras patas en
   un solo roundtrip SQL.

Referencias externas estudiadas (acuerdo: robar ideas, no código):

- **Utopia** (deeplethe/utopia, Rust+Postgres, Apache-2.0): valida en producción
  el modelo facts append-only con `valid_from/valid_to`, corrección = cerrar
  versión anterior, evidence rows por arista. Su híbrido es Tantivy (índice en
  disco, fuera de Postgres) + pgvector fusionados con RRF **en código de
  aplicación** — no es one-pass. v0.1, un mantenedor, schema inestable: no es
  dependencia, sus `migrations/` sí son referencia de modelo de datos.
- **zvec-grep** (zvec-ai, TypeScript sobre zvec de Alibaba): unifica
  ripgrep + BM25 + vector con RRF. **No tiene grafo.** Aporta la forma de la
  interfaz: una llamada con `query` semántica + `fts` léxicos elegidos por el
  agente + `fuse`, y evidencia con offsets exactos a fichero.

Ninguna referencia externa implementa la pata de grafo temporal: ahí este
backend va por delante, no por detrás.

## 1. Inventario de lo que existe (Codebase Contract preliminar)

| Pieza | Ubicación | Estado |
|---|---|---|
| Contrato de store del wiki | `parrot/knowledge/wiki/store.py::BaseWikiStore` (`upsert_pages`, `add_edges`, `replace_source_slice`, `search_fts`, `neighbors`, `broken_edges`) | Verificado en diseños previos |
| Backend SQLite | `parrot/knowledge/wiki/store.py` (`WIKI_SCHEMA_SQL`, `SCHEMA_VERSION`, patrón `_MIGRATION_COLUMNS`) | Verificado; **punto de partida del port**, no Arango |
| Backend Arango | `parrot/knowledge/wiki/arango_store.py` (`wiki_pages`/`wiki_edges` + view BM25) | Verificado |
| GraphIndex core | `parrot/knowledge/graphindex/` (`schema.py::EdgeKind`, `upsert_nodes`, `traverse`, `ground_claim`, `find_references`) | ⚠️ VERIFY firma exacta del contrato de backend de graphindex (¿comparte seam con `BaseWikiStore` o tiene el suyo propio?) |
| BM25 + re-ranking existente | Implementación sobre PgVector con modelo de embedding elegible desde HuggingFace | ⚠️ VERIFY módulo y seam exactos (¿`parrot/stores/pgvector/…`?) — el backend debe **enchufarse aquí**, no duplicar ranking |
| Contenido markdown | En disco (GraphIndex referencia, no embebe) | Confirmado por Jesús — el re-ranker lee el chunk completo de disco |
| Router ontológico | Diseño legal wiki (`legal:core` / `legal:{materia}`) | Los *seeds* de la pata de grafo salen de aquí |
| asyncpg | Estándar del proyecto (no SQLAlchemy) | Invariante |

### Lo que NO existe (no asumir)

- No existe backend Postgres de GraphIndex ni de `BaseWikiStore`.
- No existe soporte temporal en ningún backend actual (SQLite/Arango): ni en
  vértices ni en aristas.
- No existe `hybrid_search()` como método del contrato de store.
- No existe columna/campo `evidence` en aristas; hoy solo `provenance`
  (`extracted`/`inferred`) y `asserted_by`.
- No existe parametrización de idioma en el FTS de ningún backend.

## 2. Decisiones cerradas

**D1 — Temporalidad en vértices y aristas con `tstzrange`.**
`validity tstzrange NOT NULL DEFAULT tstzrange(now(), null)` en versiones de
nodo **y en aristas**. Exclusion constraint en versiones de nodo:
`EXCLUDE USING gist (concept_id WITH =, validity WITH &&)`. La invariante de
no-solapamiento la garantiza el motor. Que las aristas lleven validez es la
prueba de la temporalidad de las operaciones: "X aplica a Y" puede dejar de ser
cierto sin que cambien X ni Y.

**D2 — Bitemporal completo, append-only.**
`validity` = tiempo de validez (mundo); `tx_from timestamptz NOT NULL DEFAULT now()`
= tiempo de transacción (cuándo lo supo el grafo). Corregir = cerrar el rango
de la fila anterior + insertar; nunca UPDATE del contenido. Responde tanto
"¿qué era verdad en t?" como "¿qué creíamos en t?".

**D3 — El camino actual no paga coste temporal.**
Índice parcial `WHERE upper_inf(validity)` sobre versiones y aristas vigentes.
`t = now()` es el default y el 95% de las consultas no tocan el GiST temporal.

**D4 — Evidence y provenance en la arista.**
FK opcional de arista a chunk fuente (evidencia: de qué frase salió), más
columnas `provenance` (`extracted`/`inferred`/`derived`) y `derived boolean`.
El `derived=true` de CELLAR (versiones por diff de consolidados) vive aquí
además de en `versions[]`. Nada entra al grafo sin origen trazable.

**D5 — API temporal como contrato, degradación explícita.**
`as_of(t)`, `history(concept_id)`, `diff(concept_id, t1, t2)` entran al
contrato del store como métodos deterministas. Backends sin soporte temporal
(SQLite actual) lanzan `NotImplementedError` o sirven solo `t=now()`; el
toolkit las expone como **tools separadas** (regla de tools mono-propósito),
nunca como parámetros modales de una tool genérica.

**D6 — Retrieval híbrido one-pass como método del store, no como tool.**
`hybrid_search(query_embedding, fts_terms, seeds, as_of, weights, limit)`:

1. *Candidatos en paralelo* (CTEs de la misma query): BM25 (seam existente
   sobre pgvector), KNN pgvector, expansión de grafo temporal (CTE recursivo
   con `validity @> $as_of`) desde `seeds` del router ontológico. La pata de
   grafo aporta lo que las otras no pueden: candidatos estructuralmente
   relevantes aunque léxica/semánticamente lejanos (el artículo que *modifica*
   al que matcheó, la sentencia que lo *aplica*).
2. *Fusión RRF en SQL*: `Σ 1/(60 + rank_i)` por pata; `depth` del CTE de grafo
   como señal ponderada, no como filtro.
3. *Filtro temporal transversal*: `as_of` se aplica a las **tres** patas antes
   de fusionar (los embeddings por versión llevan metadata temporal; el KNN
   nunca devuelve redacciones derogadas).
4. *Re-ranking*: cross-encoder de HuggingFace sobre el top-k fusionado, fuera
   de SQL, en el seam existente; lee el markdown completo de disco, no la fila.

Las tools del toolkit (`legal_search`, `article_in_force`, `find_references`,
`kb_diff`, …) llaman a `hybrid_search` con configuración fija cada una. El
agente elige tools; nunca pesos ni modos.

**D7 — Idioma paramétrico en FTS.**
Columna `lang` por nodo, poblada al ingestar según namespace (`legal:*` →
`spanish`; `sym:` y código → `simple` + `pg_trgm`). Postgres no admite
regconfig variable en columnas generadas → el `tsvector` se puebla en el
upsert desde asyncpg (el store ya es el único seam de escritura). El regconfig
por namespace es configuración declarativa (navconfig), no heurística.

**D8 — asyncpg nativo, schema propio, migración idempotente.**
Pool asyncpg dedicado o compartido con schema `graphindex.*` separado del de
PgVector (que `okf-migrate` y los índices vectoriales no se pisen). Migración
estilo `_MIGRATION_COLUMNS` (idempotente, versionada con `SCHEMA_VERSION`).
Sin SQLAlchemy.

## 3. Esquema propuesto (borrador)

```sql
CREATE SCHEMA IF NOT EXISTS graphindex;

-- Identidad: una fila por concepto (concept_id estable, desacoplado de node_id)
CREATE TABLE graphindex.nodes (
  concept_id   text PRIMARY KEY,
  namespace    text NOT NULL,               -- 'legal:core', 'legal:laboral', …
  category     text NOT NULL,
  node_id      text,                        -- posición volátil, nullable
  lang         text NOT NULL DEFAULT 'simple',
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- Estado: versiones append-only con validez de mundo y de transacción
CREATE TABLE graphindex.node_versions (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  concept_id   text NOT NULL REFERENCES graphindex.nodes(concept_id) ON DELETE CASCADE,
  validity     tstzrange NOT NULL DEFAULT tstzrange(now(), null),
  tx_from      timestamptz NOT NULL DEFAULT now(),
  title        text NOT NULL,
  summary      text DEFAULT '',
  body_ref     text,                        -- ruta al markdown en disco; el texto NO se embebe
  content_hash text NOT NULL,
  fts          tsvector,                    -- poblado en upsert con to_tsvector(nodes.lang, …)
  provenance   text NOT NULL DEFAULT 'extracted',
  derived      boolean NOT NULL DEFAULT false,
  EXCLUDE USING gist (concept_id WITH =, validity WITH &&)
);
CREATE INDEX nv_current  ON graphindex.node_versions (concept_id) WHERE upper_inf(validity);
CREATE INDEX nv_validity ON graphindex.node_versions USING gist (validity);
CREATE INDEX nv_fts      ON graphindex.node_versions USING gin (fts);

CREATE TABLE graphindex.edges (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  src          text NOT NULL,
  dst          text NOT NULL,
  rel          text NOT NULL,               -- EdgeKind como text
  validity     tstzrange NOT NULL DEFAULT tstzrange(now(), null),
  tx_from      timestamptz NOT NULL DEFAULT now(),
  provenance   text NOT NULL DEFAULT 'extracted',
  derived      boolean NOT NULL DEFAULT false,
  evidence_ref text,                        -- ⚠️ VERIFY destino: ¿chunk_id de PgVector? ¿(body_ref, offset)?
  source_id    text                         -- para replace_source_slice atómico
);
CREATE INDEX e_src ON graphindex.edges (src, rel) WHERE upper_inf(validity);
CREATE INDEX e_dst ON graphindex.edges (dst, rel) WHERE upper_inf(validity);
CREATE INDEX e_validity ON graphindex.edges USING gist (validity);
-- Embeddings: viven en la implementación PgVector existente, con
-- (concept_id, version_id) como metadata para el filtro temporal pre-top-k.
```

Notas:
- `replace_source_slice(source_id)` = una transacción asyncpg que cierra/borra
  versiones y aristas del `source_id` y reingesta. Atómico de verdad, mejor
  que en Arango.
- `neighbors(direction)` = JOIN sobre índices parciales. `traverse`/expansión
  de grafo = `WITH RECURSIVE` acotado por depth (≤5), con el filtro
  `validity @> $as_of` en cada salto.
- `diff(concept_id, t1, t2)` = operaciones de rango (`&&`, `-|-`) sobre
  `node_versions` + aristas entrantes/salientes que cambian entre t1 y t2.
  Salida estructurada para el LLM, nunca "compara estos dos textos".

## 4. Open questions

- **OQ1** — ¿GraphIndex y `BaseWikiStore` comparten el mismo backend Postgres
  (un solo contrato ampliado) o son dos stores sobre el mismo schema?
  Condiciona dónde vive `postgres_store.py`. → decisión de arquitectura antes
  del spec.
- **OQ2** — Destino exacto de `evidence_ref`: ¿FK a chunk de PgVector,
  `(body_ref, byte_offset)` estilo zg, o ambos? → cerrar con la firma real de
  `ground_claim`.
- **OQ3** — Rendimiento del KNN filtrado por subconjunto de grafo: pgvector
  ≥0.8 con iterative index scan lo mitiga; para `hood` pequeño (depth ≤3) el
  scan exacto basta. → spike con corpus BOE realista y las dos direcciones
  (grafo→semántica y semántica→grafo).
- **OQ4** — ¿Los tests del contrato de store están parametrizados por backend?
  Si no, es prerequisito del Sprint 1 (⚠️ VERIFY estado actual de la suite).
- **OQ5 (heredada del legal wiki)** — Extracción de `valid_from` en fuentes que
  no lo dan explícito. El modelo ya sabe dónde guardarlo (D1/D4); falta el
  spike de extracción. Sin resolver → `valid_from = tx_from` marcado
  `derived=true`, nunca sin provenance.
- **OQ6** — Migración de grafos existentes en Arango al backend Postgres:
  ¿herramienta de export/import o se arranca solo con ingestas nuevas?

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| KNN sobre subconjunto grande de grafo ignora HNSW | OQ3 (spike); invertir orden de CTEs según cardinalidad; iterative scan pgvector ≥0.8 |
| `ts_rank_cd` no es BM25 | Irrelevante para top-k de contexto; si algún día importa, ParadeDB `pg_search` como opción, no como default |
| Exclusion constraint rechaza ingestas con rangos mal derivados (CELLAR) | El rechazo es la feature: error explícito en ingesta > grafo mentiroso; cola de revisión para conflictos |
| Doble fuente de verdad temporal (`versions[]` embebido vs `node_versions`) | En el backend Postgres, `node_versions` ES la fuente; `versions[]` queda como proyección de lectura para compatibilidad de API |
| Deriva de contrato entre 3 backends | Suite de tests parametrizada por backend obligatoria (OQ4) antes de mergear |

## 6. Roadmap tentativo

1. **Sprint 1 — Store base.** `postgres_store.py` con paridad funcional contra
   SQLite (sin temporalidad expuesta): upsert/edges/replace_source_slice/
   search_fts (D7)/neighbors. Suite parametrizada verde en los 3 backends.
2. **Sprint 2 — Plano temporal.** D1–D5: schema temporal, `as_of`/`history`/
   `diff`, tools separadas en el toolkit. Spike OQ3 en paralelo.
3. **Sprint 3 — Híbrido.** D6: `hybrid_search` con las tres patas + RRF en SQL
   + re-ranking en el seam existente. Tools de consumo (`legal_search`, …).
4. **Sprint 4 — Evidence + ingesta legal.** D4 completo (OQ2 cerrada), conexión
   con el pipeline BOE/CELLAR y el marcado `derived`.

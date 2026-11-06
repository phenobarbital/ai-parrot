# SPEC — Backend de Ontology sobre PostgreSQL + SurrealDB

**Proyecto:** ai-parrot · **Subsistema:** `parrot.ontology` (+ `parrot.knowledge`) · **Estado:** Draft v0.1 · **Fecha:** 2026-11-06
**Sustituye a:** backends ArangoDB (remoto) y SQLite per-repo (local) para ontología, wikitoolkit, Bookstore y caché L1 de GraphIndex.

---

## 0. Alcance y lectura del término "Ontology"

Este spec define el backend del subsistema **Ontology** entendido como dos almacenes con responsabilidades disjuntas y una costura explícita entre ellos:

| Almacén | Motor | Responsabilidad | Escritura | Lectura |
|---|---|---|---|---|
| **OntologyStore** | PostgreSQL (RDS central; snapshot SQLite en local) | Ontologías por dominio: clases, propiedades, individuos, SKOS, jerarquías, clausuras, versiones | Solo central, por publicación versionada | Central y local (snapshot read-only) |
| **KnowledgeStore** | SurrealDB (servidor en ECS/EC2 central; servidor local por usuario) | Wiki OKF (wikitoolkit), Bookstore, entidades extraídas, caché de síntesis L1 de GraphIndex | Central y local, multi-proceso | Híbrida BM25 + vector + grafo |

Si en el código `parrot.ontology` denota solo el grafo de conceptos, las secciones 5, 7 y 8 se extraen a `SPEC_knowledge_store_surrealdb.md` sin cambios en el resto.

**Fuera de alcance:** L0 de GraphIndex (grafo estructural de código; sigue en SQLite per-repo local + tablas Postgres centrales, spec aparte), razonamiento OWL DL, UI de edición de ontologías.

---

## 1. Contexto y motivación

- ArangoDB Community pasó a BUSL-1.1 + "Community License" (uso comercial en producción prohibido, tope 100 GiB con apagado técnico). Incompatible con la distribución MIT de ai-parrot para uso comercial.
- Apache AGE descartado: el Postgres de producción corre en Amazon RDS y AWS no permite la extensión.
- Ningún motor embebido (LadybugDB, DuckDB, CozoDB, SurrealDB embebido, HelixDB) admite varios procesos escritores sobre el mismo fichero. Un grafo compartido entre consolas exige un proceso servidor local.
- Las dos cargas son opuestas: la ontología es pequeña, read-mostly, autoritativa y compartida; la wiki es documental, de alta escritura, y su retrieval es híbrido (BM25 + vector + grafo). No tiene por qué ser la misma base de datos.

---

## 2. Objetivos y no-objetivos

**Objetivos**
1. Un único contrato Python (`OntologyStore`, `KnowledgeStore`) usado por el router ontológico, wikitoolkit, Bookstore, Domain Experts y GraphIndex L1/L2.
2. Modo central compartido (varias personas, muchos agentes concurrentes) y modo local (varios repos y consolas en paralelo en una máquina) con **el mismo código de acceso**.
3. Ontología con fidelidad RDF: importable/exportable como Turtle, validable con SHACL, versionada, sin borrados destructivos.
4. Retrieval híbrido en el KnowledgeStore con filtro por conceptos ontológicos expandidos.
5. Local funcional sin red (ontología desde snapshot, wiki desde servidor local).

**No-objetivos**
- Razonamiento OWL completo (si hace falta, se añade Fuseki/Oxigraph como capa aparte alimentada desde el Turtle maestro).
- Réplica bidireccional transparente entre Surreal local y central (se usa git como fuente de verdad para páginas y un log de deltas solo para datos no derivados de git).
- Consultas Cypher/SPARQL libres por parte de agentes contra los motores.

---

## 3. Decisiones (ADR resumidas)

| ID | Decisión | Alternativas descartadas | Motivo |
|---|---|---|---|
| D1 | Ontología en PostgreSQL relacional con clausura materializada | AGE, Oxigraph, Fuseki, TypeDB | RDS ya existe; AGE no instalable; almacenes RDF OSS sin vector y sin backends GraphRAG; el router necesita JOINs, trgm y pgvector, no traversals |
| D2 | La ontología es **append-only + versionada**; nunca se borra un IRI, se depreca (`deprecated`, `replaced_by`) | Borrado físico | Integridad referencial entre almacenes por convención; permite propagación determinista |
| D3 | Local lee la ontología desde un **snapshot SQLite read-only** por `(ontology_id, version)` | Servidor Postgres local | Read-mostly; elimina un demonio local; funciona offline |
| D4 | Wiki/Bookstore/L1 en **SurrealDB modo servidor** en ambos modos | Postgres plano, FalkorDB, Memgraph | Único motor evaluado con BM25 real + HNSW + fusión + aristas con propiedades + namespaces ilimitados; mismo SurrealQL local y central |
| D5 | Los bundles OKF viven en **git**; Surreal es índice + grafo derivado. Solo entidades, síntesis y anotaciones no derivables de git usan log de deltas | Surreal como fuente de verdad de páginas | Conflictos de páginas se resuelven en git; la reingesta es idempotente por `(path, commit)` |
| D6 | Costura entre almacenes por **IRI como string** en Surreal; retrieval en dos pasos (expandir en ontología → filtrar en Surreal) | FK cruzadas, copia de jerarquía en Surreal | No hay JOIN entre motores; la expansión devuelve decenas de IRIs, filtro barato |
| D7 | Contratos por **operaciones semánticas**, no por dialecto de consulta | Adaptador basado en Cypher | Permite FalkorDB u otro motor como implementación futura sin tocar L2 |
| D8 | Versiones fijadas: PostgreSQL 17 (RDS) con `vector`, `pg_trgm`, `ltree` opcional; SurrealDB **3.3.x** servidor; SDK Python `surrealdb` 3.x tras gate de spike (ver §11) | SurrealDB 4.0-beta | 4.0 lleva una semana en beta; el adaptador aísla el SDK |

---

## 4. OntologyStore — PostgreSQL

### 4.1 Modelo de datos

Todo es proyectable a triples para round-trip Turtle. `ontology_id` actúa como grafo nombrado.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE SCHEMA ontology;

CREATE TABLE ontology.ontology (
  ontology_id   text PRIMARY KEY,            -- p.ej. 'legal_es', 'parrot_core'
  base_iri      text NOT NULL,
  title         text,
  current_version int NOT NULL DEFAULT 0
);

CREATE TABLE ontology.version (
  ontology_id   text REFERENCES ontology.ontology,
  version       int  NOT NULL,
  released_at   timestamptz NOT NULL DEFAULT now(),
  checksum      text NOT NULL,               -- sha256 del Turtle canónico
  turtle_uri    text,                        -- s3://.../legal_es/v12.ttl
  notes         text,
  PRIMARY KEY (ontology_id, version)
);

-- Identidad estable, independiente de los atributos versionados.
CREATE TABLE ontology.concept_identity (
  ontology_id   text NOT NULL REFERENCES ontology.ontology,
  iri           text NOT NULL,
  PRIMARY KEY (ontology_id, iri)
);

CREATE TABLE ontology.concept (
  ontology_id   text NOT NULL,
  iri           text NOT NULL,
  kind          text NOT NULL CHECK (kind IN ('class','object_property','datatype_property','individual','concept_scheme','skos_concept')),
  pref_label    text,                        -- etiqueta preferida en idioma por defecto (desnormalizada para trgm)
  definition    text,
  deprecated    boolean NOT NULL DEFAULT false,
  replaced_by   text,                        -- IRI
  since_version int NOT NULL,
  until_version int,                         -- NULL = vigente
  embedding     vector(1024),                -- del texto "pref_label + definition + altLabels"
  extra         jsonb NOT NULL DEFAULT '{}', -- anotaciones RDF no modeladas (rdfs:seeAlso, dc:source...)
  PRIMARY KEY (ontology_id, iri, since_version),
  FOREIGN KEY (ontology_id, iri) REFERENCES ontology.concept_identity,
  FOREIGN KEY (ontology_id, since_version) REFERENCES ontology.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES ontology.version,
  CHECK (until_version IS NULL OR until_version > since_version)
);

CREATE TABLE ontology.label (
  ontology_id   text NOT NULL,
  iri           text NOT NULL,
  lang          text NOT NULL DEFAULT 'es',
  kind          text NOT NULL CHECK (kind IN ('pref','alt','hidden')),   -- SKOS
  text          text NOT NULL,
  since_version int NOT NULL,
  until_version int,
  PRIMARY KEY (ontology_id, iri, lang, kind, text, since_version),
  FOREIGN KEY (ontology_id, iri) REFERENCES ontology.concept_identity,
  FOREIGN KEY (ontology_id, since_version) REFERENCES ontology.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES ontology.version,
  CHECK (until_version IS NULL OR until_version > since_version)
);

CREATE TABLE ontology.relation (
  ontology_id   text NOT NULL,
  subject_iri   text NOT NULL,
  predicate     text NOT NULL,   -- IRI completo: rdfs:subClassOf, rdfs:subPropertyOf, skos:broader, rdfs:domain, rdfs:range, owl:inverseOf, rdf:type, parrot:partOf...
  object_iri    text NOT NULL,
  since_version int NOT NULL,
  until_version int,
  PRIMARY KEY (ontology_id, subject_iri, predicate, object_iri, since_version),
  FOREIGN KEY (ontology_id, since_version) REFERENCES ontology.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES ontology.version,
  CHECK (until_version IS NULL OR until_version > since_version)
);

-- Clausura transitiva materializada por familia de predicado
CREATE TABLE ontology.closure (
  ontology_id    text NOT NULL,
  version        int NOT NULL,
  family         text NOT NULL,  -- 'subclass' | 'subproperty' | 'broader' | 'partof'
  ancestor_iri   text NOT NULL,
  descendant_iri text NOT NULL,
  depth          int  NOT NULL,  -- 0 = reflexivo
  PRIMARY KEY (ontology_id, version, family, descendant_iri, ancestor_iri),
  FOREIGN KEY (ontology_id, version) REFERENCES ontology.version
);

-- Triples con literal u objetos no modelados (fidelidad RDF)
CREATE TABLE ontology.statement (
  ontology_id   text NOT NULL,
  subject_iri   text NOT NULL,
  predicate     text NOT NULL,
  object        jsonb NOT NULL,  -- {"value":..., "datatype":..., "lang":...} | {"iri":...}
  since_version int NOT NULL,
  until_version int,
  FOREIGN KEY (ontology_id, since_version) REFERENCES ontology.version,
  FOREIGN KEY (ontology_id, until_version) REFERENCES ontology.version,
  CHECK (until_version IS NULL OR until_version > since_version)
);

CREATE UNIQUE INDEX concept_current ON ontology.concept (ontology_id, iri)
  WHERE until_version IS NULL;
CREATE UNIQUE INDEX label_current ON ontology.label (ontology_id, iri, lang, kind, text)
  WHERE until_version IS NULL;
CREATE UNIQUE INDEX relation_current ON ontology.relation (ontology_id, subject_iri, predicate, object_iri)
  WHERE until_version IS NULL;
CREATE INDEX ON ontology.label USING gin (text gin_trgm_ops);
CREATE INDEX ON ontology.concept USING gin (pref_label gin_trgm_ops);
CREATE INDEX ON ontology.concept USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON ontology.relation (ontology_id, predicate, subject_iri);
CREATE INDEX ON ontology.relation (ontology_id, predicate, object_iri);
CREATE INDEX ON ontology.closure (ontology_id, version, family, ancestor_iri);
```

Notas:
- Los intervalos son semiabiertos: una fila es visible en `v` si `since_version <= v AND (until_version IS NULL OR v < until_version)`. Conceptos, etiquetas, relaciones y statements conservan sus filas históricas. Cambiar atributos cierra la fila vigente e inserta otra; nunca sobrescribe su contenido. Una relación eliminada y reintroducida recibe otro `since_version`.
- El publicador es el único escritor y serializa por ontología con `SELECT ... FOR UPDATE` sobre `ontology.ontology`. Valida intervalos no solapados por identidad lógica; los índices parciales impiden duplicar filas vigentes. La identidad de un statement incluye sujeto, predicado y objeto RDF completo (tipo, idioma y valor).
- La clausura se calcula y conserva por versión; no se reemplazan versiones anteriores. Incluye el reflexivo (`depth 0`). Medir coste de construcción y retención en los benchmarks.
- Cada operación captura una versión publicada para todas sus lecturas, incluidas etiquetas y clausura. `get`/`export(as_of=v)` rechazan versiones inexistentes; sin `as_of` usan la versión capturada. Un snapshot de `v` contiene solo las filas visibles en `v` y su clausura, declara esa versión y rechaza otro `as_of`.
- Los inversos (`owl:inverseOf`) se materializan como relaciones adicionales en publicación, no en consulta.
- `ltree` queda como optimización opcional para jerarquías estrictamente arbóreas; la clausura cubre DAGs con herencia múltiple.

### 4.2 Pipeline de publicación (solo central)

```
Turtle (git, PR)  →  parse (rdflib)  →  validate (pyshacl + reglas parrot)  →  diff vs versión vigente
                  →  preparar embeddings y clausura de la versión candidata
                  →  TX: bloquear ontología, verificar versión base, insertar version,
                         cerrar/insertar filas, insertar clausura(version), actualizar current_version
                  →  export Turtle canónico → S3 → emitir evento OntologyPublished(ontology_id, version, diff)
```

Reglas de validación propias (además de SHACL): IRIs dentro de `base_iri`; ningún IRI desaparece (solo `owl:deprecated true` + `dcterms:isReplacedBy`); sin ciclos en `subClassOf`/`broader`; toda clase con al menos un `skos:prefLabel`.

Si la versión base cambió durante la preparación, se recalcula el candidato antes de publicar. El diff publicado alimenta la propagación al KnowledgeStore (§7.3).

### 4.3 Snapshot local

- Artefacto: fichero SQLite `~/.parrot/ontology/{ontology_id}/v{version}.sqlite` con el mismo esquema lógico (sin `vector`): `embedding` como BLOB float32; tabla FTS5 sobre `label.text`.
- Generado por `parrot ontology snapshot {ontology_id}` (lo construye el central y se descarga como blob) o localmente desde el Turtle.
- Similitud vectorial local: numpy en proceso (brute force; para ≤ 10⁵ conceptos × 1024 dims es < 50 ms). No se introduce sqlite-vec.
- Refresco: al arrancar, si hay red, `GET /ontology/{id}/version` y descarga si difiere; si no hay red, se usa el último snapshot y se marca `stale=True` en las respuestas.

### 4.4 Contrato

```python
class ConceptRef(TypedDict):
    iri: str; ontology_id: str; kind: str; pref_label: str | None
    deprecated: bool; replaced_by: str | None

class Resolution(TypedDict):
    concept: ConceptRef; score: float; matched_by: Literal['exact','trgm','vector']

class OntologyStore(Protocol):
    async def version(self, ontology_id: str) -> int: ...
    async def get(self, ontology_id: str, iri: str, *, as_of: int | None = None) -> ConceptRef | None: ...
    async def resolve(self, ontology_id: str, term: str, *, lang: str = 'es',
                      k: int = 10, kinds: Sequence[str] | None = None) -> list[Resolution]: ...
    async def expand(self, ontology_id: str, iris: Sequence[str], *,
                     family: str = 'subclass', direction: Literal['down','up','both'] = 'down',
                     max_depth: int | None = None, include_deprecated: bool = False) -> set[str]: ...
    async def neighbors(self, ontology_id: str, iri: str, predicate: str | None = None) -> list[tuple[str, str]]: ...
    async def canonical(self, ontology_id: str, iris: Sequence[str]) -> dict[str, str]: ...   # sigue replaced_by hasta vigente
    async def export(self, ontology_id: str, fmt: Literal['turtle','jsonld'], *, as_of: int | None = None) -> bytes: ...

class OntologyPublisher(Protocol):          # solo implementación Postgres
    async def publish(self, ontology_id: str, turtle: bytes, *, notes: str = '') -> PublishResult: ...
```

`resolve` es híbrido: exacto sobre `label.text` (cualquier `kind`) → trgm (`similarity > 0.45`) → vector; se fusiona por RRF y se devuelve con `matched_by` para que el router aplique sus políticas deterministas.

Implementaciones: `PostgresOntologyStore` (asyncpg vía asyncdb) y `SnapshotOntologyStore` (aiosqlite + numpy). Ambas pasan la misma suite de contrato.

---

## 5. KnowledgeStore — SurrealDB

### 5.1 Topología lógica

- `NAMESPACE` = tenant/equipo (`troc`, `navigator`, `local`).
- `DATABASE` = dominio de conocimiento (`legal`, `parrot_code`, `fieldsync`). Un dominio ≈ una o varias ontologías.
- Aislamiento de permisos por namespace/database; los agentes acceden a través de la API de ai-parrot, nunca con credenciales directas en central.

### 5.2 Esquema (SurrealQL, ilustrativo; verificar sintaxis exacta contra la doc de 3.3.x)

```sql
DEFINE TABLE bundle SCHEMAFULL;
DEFINE FIELD repo        ON bundle TYPE string;
DEFINE FIELD path        ON bundle TYPE string;          -- ruta del bundle OKF en el repo
DEFINE FIELD commit      ON bundle TYPE string;          -- SHA del que deriva el contenido
DEFINE FIELD frontmatter ON bundle TYPE object FLEXIBLE;
DEFINE FIELD updated_at  ON bundle TYPE datetime;
DEFINE INDEX bundle_key  ON bundle FIELDS repo, path UNIQUE;

DEFINE TABLE document SCHEMAFULL;                         -- página dentro del bundle
DEFINE FIELD bundle      ON document TYPE record<bundle>;
DEFINE FIELD path        ON document TYPE string;
DEFINE FIELD title       ON document TYPE string;
DEFINE FIELD content_hash ON document TYPE string;
DEFINE FIELD frontmatter ON document TYPE object FLEXIBLE;
DEFINE INDEX document_key ON document FIELDS bundle, path UNIQUE;

DEFINE TABLE section SCHEMAFULL;
DEFINE FIELD document    ON section TYPE record<document>;
DEFINE FIELD heading     ON section TYPE string;
DEFINE FIELD level       ON section TYPE int;
DEFINE FIELD ordinal     ON section TYPE int;

DEFINE TABLE chunk SCHEMAFULL;
DEFINE FIELD section     ON chunk TYPE record<section>;
DEFINE FIELD document    ON chunk TYPE record<document>;  -- desnormalizado para filtros
DEFINE FIELD ordinal     ON chunk TYPE int;
DEFINE FIELD text        ON chunk TYPE string;
DEFINE FIELD tokens      ON chunk TYPE int;
DEFINE FIELD span        ON chunk TYPE object;            -- {start, end} en el markdown fuente
DEFINE FIELD embedding   ON chunk TYPE array<float>;
DEFINE FIELD concept_iris ON chunk TYPE array<string>;    -- IRIs de entidades mencionadas (desnormalizado para filtro)

DEFINE ANALYZER es_text TOKENIZERS class FILTERS lowercase, snowball(spanish);
DEFINE INDEX chunk_fts  ON chunk FIELDS text SEARCH ANALYZER es_text BM25;
DEFINE INDEX chunk_vec  ON chunk FIELDS embedding HNSW DIMENSION 1024 DIST COSINE;
DEFINE INDEX chunk_iris ON chunk FIELDS concept_iris;

DEFINE TABLE entity SCHEMAFULL;
DEFINE FIELD name        ON entity TYPE string;
DEFINE FIELD kind        ON entity TYPE string;           -- etiqueta de dominio (Norma, Articulo, Modulo, Persona...)
DEFINE FIELD concept_iri ON entity TYPE option<string>;   -- COSTURA con OntologyStore (string, no record)
DEFINE FIELD ontology_version ON entity TYPE option<int>; -- versión con la que se etiquetó
DEFINE FIELD embedding   ON entity TYPE array<float>;
DEFINE FIELD aliases     ON entity TYPE array<string>;
DEFINE INDEX entity_fts  ON entity FIELDS name, aliases SEARCH ANALYZER es_text BM25;
DEFINE INDEX entity_vec  ON entity FIELDS embedding HNSW DIMENSION 1024 DIST COSINE;
DEFINE INDEX entity_iri  ON entity FIELDS concept_iri;

-- Aristas (tablas de relación con propiedades)
DEFINE TABLE next_chunk TYPE RELATION FROM chunk TO chunk;
DEFINE TABLE mentions   TYPE RELATION FROM chunk TO entity;
DEFINE FIELD spans      ON mentions TYPE array<object>;
DEFINE FIELD confidence ON mentions TYPE float;
DEFINE FIELD source     ON mentions TYPE string;          -- 'llm:<model>' | 'rule:<id>' | 'human'
DEFINE TABLE related    TYPE RELATION FROM entity TO entity;
DEFINE FIELD predicate  ON related TYPE string;           -- IRI de propiedad ontológica
DEFINE FIELD evidence   ON related TYPE array<record<chunk>>;

-- Caché de síntesis L1 de GraphIndex
DEFINE TABLE synth SCHEMAFULL;
DEFINE FIELD repo           ON synth TYPE string;
DEFINE FIELD qualified_name ON synth TYPE string;
DEFINE FIELD content_hash   ON synth TYPE string;         -- hash del código fuente del símbolo
DEFINE FIELD summary        ON synth TYPE string;
DEFINE FIELD model          ON synth TYPE string;
DEFINE FIELD embedding      ON synth TYPE array<float>;
DEFINE FIELD created_at     ON synth TYPE datetime;
DEFINE INDEX synth_key      ON synth FIELDS repo, qualified_name, content_hash UNIQUE;
DEFINE INDEX synth_fts      ON synth FIELDS summary SEARCH ANALYZER es_text BM25;
DEFINE INDEX synth_vec      ON synth FIELDS embedding HNSW DIMENSION 1024 DIST COSINE;

-- Bookstore: documentos no-OKF (PDF, DOCX, URLs) reutilizan document/section/chunk con bundle = NONE
-- y un campo source en document: {kind:'pdf'|'url'|'docx', uri, sha256}
```

### 5.3 Contrato

```python
class KnowledgeStore(Protocol):
    # ingesta (idempotente por claves naturales)
    async def upsert_bundle(self, ns: Scope, bundle: BundleIn) -> BundleRef: ...
    async def upsert_document(self, ns: Scope, doc: DocumentIn, sections: list[SectionIn], chunks: list[ChunkIn]) -> DocumentRef: ...
    async def upsert_entities(self, ns: Scope, entities: list[EntityIn]) -> list[EntityRef]: ...
    async def relate(self, ns: Scope, edges: list[EdgeIn]) -> None: ...          # mentions / related
    async def tombstone_document(self, ns: Scope, repo: str, path: str) -> None: ...
    # retrieval
    async def search(self, ns: Scope, q: Query) -> list[Hit]: ...                 # híbrido con filtros
    async def neighbors(self, ns: Scope, entity: EntityRef, *, predicate: str | None, depth: int = 1) -> Subgraph: ...
    async def chunks_for(self, ns: Scope, entity_iris: Sequence[str], *, limit: int) -> list[Hit]: ...
    # L1
    async def get_synth(self, ns: Scope, repo: str, qname: str, content_hash: str) -> Synth | None: ...
    async def put_synth(self, ns: Scope, s: SynthIn) -> None: ...
    # sync
    async def apply_delta(self, ns: Scope, ops: list[DeltaOp]) -> AppliedRange: ...
    async def subscribe(self, ns: Scope, tables: Sequence[str]) -> AsyncIterator[ChangeEvent]: ...   # LIVE SELECT

@dataclass(frozen=True)
class Query:
    text: str
    embedding: list[float] | None
    concept_iris: frozenset[str] = frozenset()   # ya expandidos por OntologyStore
    repos: frozenset[str] = frozenset()
    k: int = 20
    mode: Literal['hybrid','bm25','vector'] = 'hybrid'
```

Implementación: `SurrealKnowledgeStore` (SDK `surrealdb`, `AsyncSurreal` sobre WebSocket; las transacciones multi-sentencia solo existen por WS). Una conexión por namespace/database en pool propio.

### 5.4 Consulta híbrida (ilustrativa)

```sql
LET $bm25 = SELECT id, search::score(1) AS s FROM chunk
            WHERE text @1@ $q AND ($iris = [] OR concept_iris CONTAINSANY $iris)
            ORDER BY s DESC LIMIT $k2;
LET $vec  = SELECT id, vector::distance::knn() AS d FROM chunk
            WHERE embedding <|$k2, COSINE|> $emb AND ($iris = [] OR concept_iris CONTAINSANY $iris)
            ORDER BY d LIMIT $k2;
RETURN search::rrf([$bm25, $vec], $k);   -- o fusión RRF en cliente si la función no está disponible en 3.3.x
```

La fusión RRF **se implementa también en cliente** (determinista, `k=60`) para no depender de la función del motor y para poder añadir el score ontológico (boost por profundidad del concepto en la expansión).

---

## 6. Flujo de retrieval ontológico (dos pasos)

```
consulta → QueryClassifier (L2)
        → OntologyStore.resolve(term)        → conceptos candidatos
        → OntologyStore.expand(iris, down)   → conjunto cerrado de IRIs (decenas)
        → KnowledgeStore.search(Query(text, emb, concept_iris=IRIs))
        → ranking final (RRF cliente + boost ontológico) → chunks + entidades + procedencia
```

Garantías: el paso 2 es determinista dado `(ontology_id, version)`; la respuesta incluye `ontology_version` y `stale` para trazabilidad. Si `resolve` no devuelve nada por encima del umbral, se consulta sin filtro y se marca `unscoped=True`.

---

## 7. Costura, consistencia y sincronización

### 7.1 Regla de la costura
- Surreal guarda `concept_iri` como **string**, junto con `ontology_version` del momento del etiquetado. Nunca copia jerarquías.
- Toda lectura pasa `concept_iri` por `OntologyStore.canonical()` cuando `ontology_version < current_version`.

### 7.2 Fuente de verdad por tipo de dato

| Dato | Fuente de verdad | Surreal es… | Sync |
|---|---|---|---|
| Páginas OKF, frontmatter, secciones, chunks | git | índice derivado por `(repo, path, commit)` | reingesta (central: rama principal por hook/CI; local: working tree por hook) |
| Entidades extraídas, `mentions`, `related` | Surreal | primario | log de deltas |
| Síntesis L1 | Surreal | primario (regenerable, caro) | log de deltas, LWW por `content_hash` |
| Anotaciones humanas | Surreal | primario | log de deltas |
| Ontología | git (Turtle) + Postgres (publicado) | consumidor | snapshot por versión |

### 7.3 Propagación de cambios de ontología
Al evento `OntologyPublished(diff)`: job asíncrono que, por cada `replaced_by` nuevo, ejecuta en Surreal `UPDATE entity SET concept_iri = $new, ontology_version = $v WHERE concept_iri = $old` y reescribe `chunk.concept_iris`. Idempotente; registra en `ontology.propagation_log(ontology_id, version, ns, db, applied_at)`.

### 7.4 Outbox transaccional (datos no derivados de git)
- Cada mutación local confirma en **una transacción SurrealDB** los datos, una operación inmutable en `sync_outbox` y el incremento del contador de su stream. No se escribe un fichero como segunda fuente de verdad. JSONL queda como formato de exportación/importación del outbox confirmado.
- Identidad de operación: `(origin, ns, db, seq)`. `origin` identifica la instalación persistente; `seq` es monótono por `(origin, ns, db)`. Todas las consolas comparten el contador en la base local; conflictos transaccionales se reintentan con límite. Cada petición conserva un `request_id` único durante reintentos y reconexiones: un commit de resultado incierto se consulta por esa clave antes de volver a mutar. Su unicidad se exige en la base y su recibo se conserva durante todo el periodo de reintentos admitido, incluso si se compacta el payload del outbox.
- El registro contiene `{origin, ns, db, seq, request_id, op, key, payload, ts}`. Datos, contador y outbox se confirman juntos o ninguno. G1 debe demostrar esta atomicidad y la unicidad bajo concurrencia con el motor/SDK elegidos; si no puede, la sincronización queda bloqueada.
- Un worker envía operaciones confirmadas, en orden por stream, a `POST /knowledge/{ns}/{db}/deltas`. El central confirma en una transacción la mutación, su recibo único por identidad de operación y el registro de cambios para descarga. Un reenvío devuelve el recibo previo sin repetir efectos; una identidad repetida con otro payload se rechaza. El ACK solo sale después del commit.
- El worker marca el ACK local después de recibirlo. Si cae antes de guardarlo, reenvía la misma operación. No se purgan operaciones sin ACK; la retención de recibos debe cubrir todos los reintentos admitidos. Un stream con huecos no avanza su cursor contiguo hasta recuperar las operaciones pendientes.
- Central → local: `subscribe()` (LIVE SELECT) notifica novedades; el registro durable y `GET /knowledge/.../deltas?since=` permiten recuperar desconexiones. Aplicar un lote y avanzar su cursor local es atómico, con deduplicación y sin generar otra operación saliente. Un cursor expirado requiere snapshot completo con su cursor de corte y replay posterior.
- Conflictos: no hay merge de páginas (git); entidades usan LWW con desempate determinista `(ts, origin, seq)`; síntesis se identifican también por `content_hash`; `related` une evidencias. Deduplicación de transporte y resolución de conflictos son reglas distintas.

---

## 8. Despliegue

### 8.1 Central (AWS)
- **PostgreSQL 17 en RDS** con `vector`, `pg_trgm`. Esquema `ontology`. Rol `ontology_rw` solo para el publicador; `ontology_ro` para la API.
- **SurrealDB 3.3.x** en ECS (Fargate o EC2 con EBS gp3), un nodo, `rocksdb://` o `surrealkv://` sobre volumen persistente, `--bind 0.0.0.0:8000` solo en red privada; TLS terminado en ALB; credenciales root en Secrets Manager; acceso de agentes solo vía API ai-parrot. TiKV **no** en v1.
- Backups: snapshots RDS + `surreal export` diario a S3 + snapshot EBS.
- Imagen fijada por digest, no `latest`.

### 8.2 Local (desarrollador)
- Ontología: snapshot SQLite (§4.3). Sin Postgres local.
- Surreal: binario único `surreal` gestionado por `parrot knowledge daemon`:
  - arranque perezoso por la primera consola; lock file `~/.parrot/knowledge/daemon.lock` con PID y puerto; socket `127.0.0.1:{puerto libre}`; almacenamiento `rocksdb://~/.parrot/knowledge/data`;
  - opcionalmente servicio de usuario (systemd `--user` / launchd) para evitar el arranque perezoso;
  - todas las consolas y repos comparten ese servidor; namespace `local`, database por dominio.
- El modo embebido de Surreal **no se usa** (mono-proceso).

### 8.3 Configuración (navconfig)

```
ONTOLOGY_BACKEND=postgres|snapshot
ONTOLOGY_PG_DSN=...
ONTOLOGY_SNAPSHOT_DIR=~/.parrot/ontology
KNOWLEDGE_BACKEND=surreal
KNOWLEDGE_SURREAL_URL=ws://127.0.0.1:8000/rpc | wss://knowledge.internal/rpc
KNOWLEDGE_NAMESPACE=local|troc
KNOWLEDGE_SYNC_ENDPOINT=https://api.../knowledge
```

---

## 9. Migración

1. **Ontología** (ArangoDB → Postgres): exportar colecciones de conceptos/aristas a Turtle con un script one-shot (mapeo de etiquetas Arango → clases, aristas → `subClassOf`/`broader`/propiedades); publicar como v1 por el pipeline normal. El Turtle pasa a vivir en git.
2. **Wiki OKF**: reingesta desde git a Surreal central (CI) y local (hook) para contenido reconstruible; exportación/importación explícita de páginas y metadatos existentes que no estén en git, con identidades preservadas.
3. **Entidades/síntesis existentes** (SQLite per-repo, ArangoDB): script `parrot knowledge import --from sqlite|arango` que emite el log de deltas y lo aplica; entidades reetiquetadas por `canonical()` contra la ontología v1.
4. **Bookstore**: reingesta desde los ficheros fuente (S3/local); ids estables por `sha256`.
5. **Ensayo de migración y paridad**: mantener adaptadores, dependencias, configuración y entorno ArangoDB operativos. Inventariar todos los tenants y planos (incluidos GraphIndex y vectores), asignar destino, exportar/copiar de forma reanudable y verificar recuentos, identidades, relaciones, permisos y consultas. Exportar también páginas y metadatos wiki que no sean reconstruibles desde git. La migración del grafo de instancias depende de resolver su destino en FEAT-824; no se convierte implícitamente todo a RDF.
6. **Cutover reversible**: congelar escrituras en origen, aplicar el delta final, verificar paridad y cambiar lectores con un checkpoint registrado. Durante la ventana de rollback mantener escrituras pausadas; ante fallo volver al origen sin cambios. Reabrir escrituras en destino solo tras aceptar el cutover y un ensayo de restauración. Un rollback posterior requiere congelar destino y reconciliar sus nuevas escrituras mediante un procedimiento probado; nunca basta cambiar la configuración.
7. **Retirada posterior**: solo después de migrar todos los tenants/planos, pasar §10 y cerrar la ventana de rollback, retirar backends, extras, herramientas, Docker y pruebas ArangoDB en una entrega posterior. Conservar exportaciones verificadas y evidencia de restauración según la política de retención.

---

## 10. Pruebas y aceptación

- **Suite de contrato** compartida: `OntologyStore` contra Postgres (testcontainers) y Snapshot; `KnowledgeStore` contra Surreal (testcontainers, imagen fijada). Mismos casos, mismos resultados.
- **Golden Turtle**: fixtures por dominio; propiedades: `expand` es cerrado y reflexivo, publicar dos veces el mismo Turtle no cambia `version`, deprecar propaga a Surreal.
- **Historia temporal**: publicar v1, cambiar etiquetas/atributos/relaciones en v2 y reintroducir una relación en v3; `get` y Turtle `as_of=v1` conservan el contenido original, cada snapshot conserva su clausura y versiones inexistentes fallan explícitamente. Publicaciones concurrentes no generan intervalos solapados ni mezclan versiones.
- **Concurrencia local**: 8 procesos escribiendo entidades y síntesis; verificar unicidad de `request_id` y `(origin, ns, db, seq)`, orden por stream y correspondencia exacta entre mutaciones confirmadas y outbox.
- **Recuperación de sync**: inyectar caída antes del commit local, después del commit antes del envío, después del commit central antes del ACK y después del ACK antes de guardarlo. Reiniciar y reenviar debe converger sin pérdida ni efectos duplicados; comprobar también respuesta de commit incierta, huecos y reconexión de descargas.
- **Migración y rollback**: ensayo por cada plano/tenant con checksums/recuentos y equivalencia de consultas/permisos, migración reanudable, delta final bajo pausa de escrituras y restauración al origen. Ninguna retirada antes de aprobar paridad, benchmarks y cutover.
- **Retrieval**: conjunto de consultas del wiki jurídico y de `parrot_code` con juicios de relevancia; criterio de aceptación: recall@10 del híbrido con filtro ontológico ≥ SQLite FTS5 actual + 15 puntos, latencia p95 < 300 ms en central.
- **Offline**: suite completa de lectura con red deshabilitada usando snapshot y Surreal local.

---

## 11. Riesgos y preguntas abiertas

| Riesgo | Mitigación / decisión pendiente |
|---|---|
| SDK Python `surrealdb` 3.x aún en beta; 4.0 en beta | **Spike (gate G1):** validar `AsyncSurreal` 3.x contra servidor 3.3.x: BM25 + HNSW + `CONTAINSANY`, LIVE SELECT, transacciones WS, reconexión y atomicidad del outbox/contador/recibos con 8 procesos (§7.4). Si falla, evaluar SDK 2.0.0 estable o cliente HTTP propio sobre `/sql`; cualquier alternativa debe pasar los mismos gates antes de continuar. |
| Disponibilidad y firma de `search::rrf` / analizador `snowball(spanish)` en 3.3.x | Verificar en G1; RRF en cliente es obligatorio de todos modos. |
| Rendimiento de Surreal con `CONTAINSANY` sobre arrays grandes de IRIs | Limitar expansión a ≤ 200 IRIs; si se supera, filtrar por `kind`/`repo` y post-filtrar en cliente. Medir en G1. |
| Licencia BSL 1.1 de SurrealDB para usuarios que lo ofrezcan como servicio | Documentar en README del adaptador; SDK Apache/MIT; ai-parrot no redistribuye el binario. |
| Deriva entre `concept_iri` y ontología vigente | `canonical()` en lectura + job de propagación + métrica de entidades con `ontology_version < current`. |
| Tamaño de embeddings (1024 dims) en RDS y Surreal | Parametrizable; evaluar 768/512 con Matryoshka si el coste de HNSW en Surreal es alto. |
| Lecturas de larga duración en Postgres durante publicación | Preparar embeddings y clausura fuera de la TX; validar versión base bajo bloqueo e insertar la clausura con su versión, sin sustituir historia. |
| ¿L0 de GraphIndex central va a Postgres o se difiere? | Fuera de alcance aquí; spec aparte. Este diseño no lo bloquea. |

---

## 12. Corte de tareas v1

| # | Tarea | Depende de | Entregable |
|---|---|---|---|
| T0 | Spike G1 SurrealDB 3.3.x + SDK (BM25, HNSW, LIVE, WS tx, CONTAINSANY) | — | informe go/no-go + versión de SDK fijada |
| T1 | Esquema `ontology` en Postgres + migraciones | — | DDL versionado |
| T2 | Loader Turtle (rdflib) + validador (pyshacl + reglas) + builder de clausura + `publish` | T1 | `OntologyPublisher` |
| T3 | `PostgresOntologyStore` + `SnapshotOntologyStore` + suite de contrato | T1 | paquete `parrot.ontology.stores` |
| T4 | Generación/descarga de snapshot y refresco por versión | T3 | CLI `parrot ontology snapshot` |
| T5 | Esquema Surreal + `SurrealKnowledgeStore` + suite de contrato | T0 | paquete `parrot.knowledge.stores` |
| T6 | Ingesta OKF → Surreal (bundle/document/section/chunk, embeddings) con hook git y job CI | T5 | `parrot knowledge ingest` |
| T7 | Extracción de entidades + `mentions`/`related` con etiquetado por `OntologyStore.resolve` | T3, T6 | pipeline |
| T8 | Búsqueda híbrida + RRF cliente + filtro ontológico; integración en L2 (QueryClassifier) | T3, T5 | `search()` |
| T9 | Caché L1 (`synth`) y uso desde GraphIndex | T5 | adaptador L1 |
| T10 | Daemon local `parrot knowledge daemon` (lock, puerto, servicio de usuario) | T0 | CLI |
| T11 | Outbox transaccional, contadores, recibos idempotentes, recuperación y rehidratación (§7.4) | T5, T10 | sync v1 + pruebas de caída |
| T12 | Job de propagación de deprecaciones ontología → Surreal | T2, T5 | worker |
| T13 | Scripts de migración (Arango → Turtle; SQLite/Arango → deltas) | T2, T11 | CLI |
| T14 | Benchmarks, historia temporal, concurrencia, recuperación y paridad de migración (§10) | T2, T4, T7, T8, T9, T11, T12, T13 | informe de aceptación |
| T15 | Despliegue central (RDS roles, ECS Surreal, backups) + docs de operación | T5 | IaC en el repo de infraestructura |
| T16 | Cutover y ensayo de rollback por tenant/plano (§9), tras portar todos los consumidores de FEAT-824 | T14, T15 | checkpoints y evidencia de restauración |
| T17 | Retirada ArangoDB tras cierre de ventana de rollback, en entrega posterior | T16 | eliminación de backends, extras y entorno heredado |

Orden sugerido: T0 ∥ T1 → T2, T3 → T4 → T5 → T6 → T8 → T7, T9 → T10 → T11 → T12 → T13 → T14 → T15 → T16 → T17. T16 también exige resolver y migrar el grafo de instancias y todos los consumidores inventariados en FEAT-824; las tareas del borrador no sustituyen ese port.

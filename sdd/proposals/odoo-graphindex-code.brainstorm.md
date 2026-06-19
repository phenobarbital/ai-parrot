# SPEC — GraphIndex Odoo-aware + backend SQLite (extractor + reader)

> **Estado:** propuesto · **Metodología:** SDD · **Destino:** `packages/ai-parrot/src/parrot/knowledge/graphindex`
> **Objetivo de implementación:** Claude Code

---

## 1. Resumen

Dar acceso navegable y buscable a un repositorio de código Odoo **sin vectorización semántica**, reutilizando el pipeline existente de GraphIndex (Extract → Embed → Assemble → Resolve → Persist → Analyze). Se añaden tres capacidades:

1. **`SQLitePersistence`** — backend de persistencia **par** al de ArangoDB, que materializa el grafo en un artefacto SQLite por tenant (ya entregado; incluido aquí como contrato de referencia).
2. **`OdooCodeExtractor`** — subclase de `CodeExtractor` que captura semántica Odoo (`_name`/`_inherit`/`_inherits`, `fields.*`, `@api.*`) y emite aristas `EXTENDS` hacia nodos de modelo canónicos.
3. **`SQLiteGraphReader`** — lado de lectura: topología **HOT** en `rustworkx` al arrancar, cuerpos de fuente **COLD** bajo demanda (LRU acotado, lectura desde disco por rango de líneas), y búsqueda léxica vía FTS5/BM25.

El caso de uso guía: *descubrir qué añade un módulo third-party a un modelo del core (p. ej. `res.partner`) sin leer el código a mano.* Esto se resuelve como recorrido determinista del grafo, no como similitud difusa.

### No-objetivos (v1)
- Sin embeddings ni `embedding_ref` poblado por esta ruta.
- Sin exposición MCP (descopada, como en el resto de GraphIndex v1).
- Sin parseo de vistas XML / OWL JS (posible v2 vía tree-sitter multi-lenguaje).
- Sin resolución de `_name`/`_inherit` dinámicos (f-strings, concatenación): degradan, no rompen.

---

## 2. Prerrequisitos (cambios mínimos fuera de los módulos nuevos)

### 2.1 `schema.py` — añadir `EdgeKind.EXTENDS`

```python
class EdgeKind(str, Enum):
    CONTAINS = "contains"
    REFERENCES = "references"
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"
    EXTENDS = "extends"   # NUEVO: herencia Odoo (_inherit / _inherits)
```

### 2.2 `meta_ontology.py` — paridad para el backend Arango

Añadir la colección de aristas y su `RelationDef` (solo necesario si el backend Arango debe persistir `EXTENDS`; **el backend SQLite no lo necesita**, sus aristas son filas con columna `kind`):

```python
EDGE_KIND_TO_COLLECTION: dict[str, str] = {
    "contains": "gi_contains",
    "references": "gi_references",
    "defines": "gi_defines",
    "mentions": "gi_mentions",
    "explains": "gi_explains",
    "extends": "gi_extends",   # NUEVO
}
# Añadir también un RelationDef("extends", ...) en _RELATION_DEFS.
```

### 2.3 `projection.py` — mapeo OKF (DECISIÓN ABIERTA)

`EDGE_KIND_TO_RELATION_TYPE` necesita una entrada para `EdgeKind.EXTENDS`. Dos opciones:
- **(a)** Añadir `RelationType.EXTENDS` a la ontología OKF y mapear 1:1 (preferido si los sidecars deben reflejar herencia con fidelidad).
- **(b)** Mapear `EXTENDS → RelationType.REFERENCES` temporalmente (cero cambios en OKF, pierde semántica en el sidecar).

> **Acción Claude Code:** implementar (a) si `RelationType` admite extensión trivial; si no, (b) con un `# TODO` enlazando a este spec.

### 2.4 `extractors/code.py` (base `CodeExtractor`) — estampar metadatos

Tres adiciones, todas backward-compatible:

1. **`extract()` acepta `mtime`** y estampa `sha1`+`mtime` en el nodo módulo:

```python
import hashlib

async def extract(
    self, file_path: str, source: str, *, mtime: Optional[float] = None
) -> tuple[list[UniversalNode], list[UniversalEdge]]:
    ...
    sha1 = hashlib.sha1(source_bytes).hexdigest()
    module_node = UniversalNode(
        ...,
        domain_tags={
            "symbol_type": "module",
            "sha1": sha1,
            **({"mtime": mtime} if mtime is not None else {}),
            **({"parse_error": True} if has_error else {}),
        },
        ...
    )
```

2. **`_extract_class` y `_extract_function` estampan el rango de líneas** (para que `get_source` funcione sobre cualquier símbolo):

```python
# en ambos, al construir domain_tags:
"lineno": node.start_point[0] + 1,
"end_lineno": node.end_point[0] + 1,
```

### 2.5 `builder.py` / `loader.py` — cableado

- Al leer cada fichero, calcular `mtime = os.stat(path).st_mtime` y pasarlo a `extract(..., mtime=mtime)`.
- Permitir seleccionar `SQLitePersistence` como backend (junto a Arango/Null). Mismo contrato → inyección directa.
- En builds incrementales, consultar `await persistence.is_stale(ctx, source_uri, mtime, sha1)` para saltar ficheros sin cambios antes de extraer.

---

## 3. Contrato del artefacto SQLite (referencia — ya implementado en `persist_sqlite.py`)

Esquema autoritativo que el reader asume:

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE files (
    source_uri  TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    sha1        TEXT NOT NULL,
    indexed_at  TEXT NOT NULL
);

CREATE TABLE nodes (
    node_id       TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    source_uri    TEXT NOT NULL,
    parent_id     TEXT,
    summary       TEXT,
    content_ref   TEXT,
    embedding_ref TEXT,
    provenance    TEXT NOT NULL,
    domain_tags   TEXT             -- JSON: symbol_type, model_name, inherit, fields, lineno...
);
CREATE INDEX idx_nodes_source_uri ON nodes(source_uri);
CREATE INDEX idx_nodes_parent     ON nodes(parent_id);
CREATE INDEX idx_nodes_kind       ON nodes(kind);

CREATE TABLE edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    confidence  REAL,
    source_uri  TEXT,
    PRIMARY KEY (source_id, target_id, kind)   -- kind en la PK: clase recibe CONTAINS y DEFINES
);
CREATE INDEX idx_edges_kind       ON edges(kind, source_id);
CREATE INDEX idx_edges_source_uri ON edges(source_uri);

CREATE VIRTUAL TABLE nodes_fts USING fts5(
    node_id UNINDEXED, title, summary, tokenize = 'unicode61'
);
```

**Superficie del backend** (paridad estricta con `GraphIndexPersistence`):
- `async persist_graph(ctx, nodes, edges) -> {"nodes_persisted", "edges_persisted"}`
- `async replace_document_slice(ctx, document_uri, nodes, edges) -> {"nodes_replaced", "edges_replaced"}`
- `async is_stale(ctx, source_uri, mtime, sha1) -> bool` (adición read-side)

**Invariantes:**
- Un `.db` por tenant (`<tenant_id>.db`) = aislamiento.
- `mtime`/`sha1` se cosechan del `domain_tags` del nodo módulo (no ensucian la firma).
- `replace_document_slice` hace DELETE+INSERT en **una transacción** = atomicidad real por documento.
- Las aristas se estampan con el `source_uri` del nodo origen, para purga por slice.

---

## 4. Convención de nodos/aristas Odoo

### Modelo de dos capas

| Capa | `symbol_type` | `source_uri` | Propósito |
|------|---------------|--------------|-----------|
| Clase | `odoo_model_class` | fichero real | La clase Python concreta; mantiene jerarquía `CONTAINS` |
| Modelo canónico | `odoo_model` | `odoo-model://<name>` | Agregador por nombre de modelo; punto de anclaje de `EXTENDS` |
| Campo | `odoo_field` | fichero real | `fields.X(...)`; hijo `CONTAINS` de la clase |
| Método | `function` (base) | fichero real | Con `decorators` en `domain_tags` si `@api.*` |

### Aristas
- Clase **`DEFINES`** modelo canónico — cuando hay `_name`.
- Clase **`EXTENDS`** modelo canónico — una por cada nombre en `_inherit` / claves de `_inherits`.
- Clase **`CONTAINS`** campo/método — estructural.

### Invariante crítico del nodo canónico
Su `source_uri` es **sintético** (`odoo-model://res.partner`). Razón: si fuese un fichero real, `replace_document_slice` lo borraría al refrescar ese fichero y dejaría huérfanas las `EXTENDS` de otros módulos. Con URI sintético ningún slice lo toca y `_upsert_files` no le crea fila (solo mira nodos `module`). Coste asumido en v1: nodos canónicos huérfanos no se recolectan; analytics puede marcarlos después.

---

## 5. Componente: `OdooCodeExtractor`

**Ruta:** `extractors/odoo_code.py`

```python
"""Odoo-aware code extractor for GraphIndex.

Subclasses CodeExtractor to capture Odoo model semantics — _name / _inherit /
_inherits, fields.* declarations and @api.* decorators — emitting EXTENDS edges
to canonical model nodes. All Odoo specifics live in domain_tags; the only
schema-level addition is EdgeKind.EXTENDS.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from parrot.knowledge.graphindex.extractors.code import (
    CodeExtractor,
    _get_node_text,
    _make_node_id,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)

_ODOO_BASES: set[str] = {"Model", "TransientModel", "AbstractModel"}

_FIELD_KWARGS: set[str] = {
    "comodel_name", "compute", "related", "store", "required", "readonly",
    "string", "default", "selection", "inverse", "search", "tracking",
    "ondelete", "domain", "groups", "company_dependent",
}

_API_DECORATORS: set[str] = {
    "depends", "onchange", "constrains", "model", "model_create_multi",
    "returns", "depends_context", "ondelete", "autovacuum",
}

_ModelRef = Union[str, list[str], dict[str, str], None]


def _model_node_id(model_name: str) -> str:
    """Stable, file-independent node id for a canonical Odoo model."""
    return _make_node_id("__odoo_model__", model_name)


def _strip_quotes(raw: str) -> str:
    for q in ('"""', "'''", '"', "'"):
        if raw.startswith(q) and raw.endswith(q) and len(raw) >= 2 * len(q):
            return raw[len(q):-len(q)]
    return raw


def _literal_value(node, source_bytes: bytes) -> _ModelRef:
    """Best-effort evaluation of a string / list / dict literal node.

    Returns None for non-literal expressions so callers skip canonical linking.
    """
    if node is None:
        return None
    if node.type in ("string", "concatenated_string"):
        return _strip_quotes(_get_node_text(node, source_bytes))
    if node.type == "list":
        out: list[str] = []
        for child in node.children:
            if child.type in ("string", "concatenated_string"):
                out.append(_strip_quotes(_get_node_text(child, source_bytes)))
        return out or None
    if node.type == "dictionary":
        out_d: dict[str, str] = {}
        for pair in node.children:
            if pair.type != "pair":
                continue
            key = pair.child_by_field_name("key")
            val = pair.child_by_field_name("value")
            if key is not None and key.type == "string":
                k = _strip_quotes(_get_node_text(key, source_bytes))
                v = (_strip_quotes(_get_node_text(val, source_bytes))
                     if val is not None and val.type == "string" else "")
                out_d[k] = v
        return out_d or None
    return None


class OdooCodeExtractor(CodeExtractor):
    """Extract Odoo model structure on top of the generic code extractor.

    Only _extract_class is overridden. Non-Odoo classes defer to the base, so
    mixing Odoo and plain Python in one repo is transparent.
    """

    def _extract_class(self, node, file_path, source_bytes, parent_id, nodes, edges) -> str:
        name_node = node.child_by_field_name("name")
        class_name = _get_node_text(name_node, source_bytes) if name_node else "__unknown_class__"
        bases = self._extract_bases(node, source_bytes)
        meta = self._extract_model_meta(node, source_bytes)
        is_odoo = bool(
            meta["name"] or meta["inherit"] or meta["inherits"]
            or (_ODOO_BASES & set(bases))
        )
        if not is_odoo:
            return super()._extract_class(node, file_path, source_bytes, parent_id, nodes, edges)

        class_id = _make_node_id(file_path, class_name)
        docstring = self._get_docstring(node, source_bytes)
        class_node = UniversalNode(
            node_id=class_id,
            kind=NodeKind.SYMBOL,
            title=class_name,
            source_uri=file_path,
            summary=docstring,
            parent_id=parent_id,
            domain_tags={
                "symbol_type": "odoo_model_class",
                "model_name": meta["name"],
                "inherit": meta["inherit"],
                "inherits": meta["inherits"],
                "bases": bases,
                **self._span(node),
            },
        )
        nodes.append(class_node)
        edges.append(UniversalEdge(source_id=parent_id, target_id=class_id, kind=EdgeKind.CONTAINS))
        edges.append(UniversalEdge(source_id=parent_id, target_id=class_id, kind=EdgeKind.DEFINES))

        self._link_model(class_id, meta, nodes, edges)
        self._walk_model_body(node, file_path, source_bytes, class_id, class_name, nodes, edges)
        return class_id

    def _link_model(self, class_id, meta, nodes, edges) -> None:
        seen: set[str] = set()

        def ensure(model_name: str) -> str:
            mid = _model_node_id(model_name)
            if model_name not in seen:
                seen.add(model_name)
                nodes.append(UniversalNode(
                    node_id=mid,
                    kind=NodeKind.SYMBOL,
                    title=model_name,
                    source_uri=f"odoo-model://{model_name}",
                    domain_tags={"symbol_type": "odoo_model", "model_name": model_name},
                ))
            return mid

        if meta["name"]:
            edges.append(UniversalEdge(source_id=class_id, target_id=ensure(meta["name"]), kind=EdgeKind.DEFINES))

        inherited: list[str] = []
        if isinstance(meta["inherit"], str):
            inherited.append(meta["inherit"])
        elif isinstance(meta["inherit"], list):
            inherited.extend(meta["inherit"])
        if isinstance(meta["inherits"], dict):
            inherited.extend(meta["inherits"].keys())

        for model_name in inherited:
            if model_name and model_name != meta["name"]:
                edges.append(UniversalEdge(source_id=class_id, target_id=ensure(model_name), kind=EdgeKind.EXTENDS))

    def _walk_model_body(self, node, file_path, source_bytes, class_id, class_name, nodes, edges) -> None:
        body = node.child_by_field_name("body")
        if body is None:
            return
        for child in body.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "assignment":
                        self._maybe_extract_field(sub, file_path, source_bytes, class_id, class_name, nodes, edges)
            elif child.type == "function_definition":
                self._extract_function(child, file_path, source_bytes, class_id, nodes, edges)
            elif child.type == "decorated_definition":
                decorators = self._extract_decorators(child, source_bytes)
                for sub in child.children:
                    if sub.type == "function_definition":
                        func_id = self._extract_function(sub, file_path, source_bytes, class_id, nodes, edges)
                        if decorators:
                            self._annotate_decorators(func_id, decorators, nodes)

    def _maybe_extract_field(self, assign, file_path, source_bytes, class_id, class_name, nodes, edges) -> None:
        left = assign.child_by_field_name("left")
        right = assign.child_by_field_name("right")
        if left is None or right is None or left.type != "identifier" or right.type != "call":
            return
        func = right.child_by_field_name("function")
        if func is None or func.type != "attribute":
            return
        obj = func.child_by_field_name("object")
        attr = func.child_by_field_name("attribute")
        if obj is None or attr is None or _get_node_text(obj, source_bytes) != "fields":
            return
        field_name = _get_node_text(left, source_bytes)
        field_type = _get_node_text(attr, source_bytes)
        kwargs = self._extract_field_kwargs(right, source_bytes)
        field_id = _make_node_id(file_path, f"{class_name}.{field_name}")
        nodes.append(UniversalNode(
            node_id=field_id,
            kind=NodeKind.SYMBOL,
            title=field_name,
            source_uri=file_path,
            summary=kwargs.get("string"),
            parent_id=class_id,
            domain_tags={"symbol_type": "odoo_field", "field_type": field_type, **kwargs, **self._span(assign)},
        ))
        edges.append(UniversalEdge(source_id=class_id, target_id=field_id, kind=EdgeKind.CONTAINS))

    def _extract_field_kwargs(self, call_node, source_bytes) -> dict[str, str]:
        out: dict[str, str] = {}
        args = call_node.child_by_field_name("arguments")
        if args is None:
            return out
        first_positional_used = False
        for arg in args.children:
            if arg.type == "keyword_argument":
                key_node = arg.child_by_field_name("name")
                val_node = arg.child_by_field_name("value")
                if key_node is None:
                    continue
                key = _get_node_text(key_node, source_bytes)
                if key in _FIELD_KWARGS and val_node is not None:
                    out[key] = _strip_quotes(_get_node_text(val_node, source_bytes))
            elif arg.type == "string" and not first_positional_used:
                first_positional_used = True
                out.setdefault("comodel_name", _strip_quotes(_get_node_text(arg, source_bytes)))
        return out

    def _extract_decorators(self, decorated_node, source_bytes) -> list[dict]:
        found: list[dict] = []
        for child in decorated_node.children:
            if child.type != "decorator":
                continue
            expr = next((c for c in child.children if c.type in ("call", "attribute", "identifier")), None)
            if expr is None:
                continue
            call_node = expr if expr.type == "call" else None
            attr_node = call_node.child_by_field_name("function") if call_node else expr
            if attr_node is None or attr_node.type != "attribute":
                continue
            obj = attr_node.child_by_field_name("object")
            name = attr_node.child_by_field_name("attribute")
            if obj is None or name is None or _get_node_text(obj, source_bytes) != "api":
                continue
            deco_name = _get_node_text(name, source_bytes)
            if deco_name not in _API_DECORATORS:
                continue
            args: list[str] = []
            if call_node is not None:
                arglist = call_node.child_by_field_name("arguments")
                if arglist is not None:
                    args = [_strip_quotes(_get_node_text(a, source_bytes))
                            for a in arglist.children if a.type == "string"]
            found.append({"name": deco_name, "args": args})
        return found

    @staticmethod
    def _annotate_decorators(func_id, decorators, nodes) -> None:
        for n in nodes:
            if n.node_id == func_id:
                n.domain_tags["decorators"] = decorators
                return

    @staticmethod
    def _span(node) -> dict:
        return {"lineno": node.start_point[0] + 1, "end_lineno": node.end_point[0] + 1}

    @staticmethod
    def _extract_bases(class_node, source_bytes) -> list[str]:
        supers = class_node.child_by_field_name("superclasses")
        if supers is None:
            return []
        names: list[str] = []
        for child in supers.children:
            if child.type == "attribute":
                attr = child.child_by_field_name("attribute")
                if attr is not None:
                    names.append(_get_node_text(attr, source_bytes))
            elif child.type == "identifier":
                names.append(_get_node_text(child, source_bytes))
        return names

    def _extract_model_meta(self, class_node, source_bytes) -> dict:
        meta: dict = {"name": None, "inherit": None, "inherits": None}
        body = class_node.child_by_field_name("body")
        if body is None:
            return meta
        for child in body.children:
            if child.type != "expression_statement":
                continue
            for sub in child.children:
                if sub.type != "assignment":
                    continue
                left = sub.child_by_field_name("left")
                right = sub.child_by_field_name("right")
                if left is None or left.type != "identifier":
                    continue
                key = _get_node_text(left, source_bytes)
                if key == "_name":
                    val = _literal_value(right, source_bytes)
                    meta["name"] = val if isinstance(val, str) else None
                elif key == "_inherit":
                    meta["inherit"] = _literal_value(right, source_bytes)
                elif key == "_inherits":
                    val = _literal_value(right, source_bytes)
                    meta["inherits"] = val if isinstance(val, dict) else None
        return meta
```

---

## 6. Componente: `SQLiteGraphReader`

**Ruta:** `sqlite_reader.py`
**Dependencias:** `aiosqlite`, `orjson`, `rustworkx`.

**Contrato de uso:** llamar `await reader.load()` una vez al arrancar; tras ello, la navegación síncrona (`find_model`, `who_extends`, `children`) es instantánea sobre el grafo en memoria. `search_symbols` y `get_source` son async (tocan SQLite/disco).

```python
"""SQLiteGraphReader — read side of the SQLite GraphIndex artefact.

HOT: graph topology loaded into an in-memory rustworkx DiGraph for instant,
deterministic navigation. COLD: source bodies resolved on demand from disk via
line spans, bounded by an LRU. Lexical search runs over FTS5/BM25. No embeddings.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import aiosqlite
import orjson
import rustworkx as rx

logger = logging.getLogger(__name__)


def _loads_tags(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        return orjson.loads(raw)
    except Exception:
        return {}


class SQLiteGraphReader:
    """Read-only navigator over a per-tenant SQLite GraphIndex artefact.

    Args:
        db_path: Path to the ``<tenant_id>.db`` artefact.
        repo_root: Root the node ``source_uri`` paths are relative to; required
            for ``get_source`` to read live source. When ``None``, ``get_source``
            falls back to the stored summary.
        body_cache_size: Max entries in the COLD source-body LRU.
    """

    def __init__(self, db_path, *, repo_root=None, body_cache_size: int = 256) -> None:
        self._db_path = Path(db_path)
        self._repo_root = Path(repo_root) if repo_root else None
        self._conn: Optional[aiosqlite.Connection] = None
        self._g = rx.PyDiGraph()
        self._idx_by_id: dict[str, int] = {}
        self._payload_by_id: dict[str, dict] = {}
        self._model_index: dict[str, str] = {}   # model_name -> canonical node_id
        self._loaded = False
        self._body_cache: "OrderedDict[str, str]" = OrderedDict()
        self._body_cache_size = body_cache_size

    # --- lifecycle ---

    async def load(self) -> None:
        """Load topology (nodes + edges) into the in-memory rustworkx graph."""
        if self._loaded:
            return
        self._conn = await aiosqlite.connect(f"file:{self._db_path}?mode=ro", uri=True)
        self._conn.row_factory = aiosqlite.Row

        async with self._conn.execute(
            "SELECT node_id, kind, title, source_uri, parent_id, summary, "
            "content_ref, provenance, domain_tags FROM nodes"
        ) as cur:
            async for row in cur:
                tags = _loads_tags(row["domain_tags"])
                payload = {
                    "node_id": row["node_id"], "kind": row["kind"],
                    "title": row["title"], "source_uri": row["source_uri"],
                    "parent_id": row["parent_id"], "summary": row["summary"],
                    "content_ref": row["content_ref"], "provenance": row["provenance"],
                    "domain_tags": tags,
                }
                idx = self._g.add_node(row["node_id"])
                self._idx_by_id[row["node_id"]] = idx
                self._payload_by_id[row["node_id"]] = payload
                if tags.get("symbol_type") == "odoo_model" and tags.get("model_name"):
                    self._model_index[tags["model_name"]] = row["node_id"]

        async with self._conn.execute("SELECT source_id, target_id, kind FROM edges") as cur:
            async for row in cur:
                u = self._idx_by_id.get(row["source_id"])
                v = self._idx_by_id.get(row["target_id"])
                if u is not None and v is not None:
                    self._g.add_edge(u, v, row["kind"])

        self._loaded = True
        logger.info("Loaded %d nodes / %d edges from %s",
                    self._g.num_nodes(), self._g.num_edges(), self._db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _require_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError("SQLiteGraphReader.load() must be awaited before navigation")

    # --- HOT navigation (sync, in-memory) ---

    def get_node(self, node_id: str) -> Optional[dict]:
        return self._payload_by_id.get(node_id)

    def list_models(self) -> list[str]:
        self._require_loaded()
        return sorted(self._model_index)

    def children(self, node_id: str, *, symbol_type: Optional[str] = None) -> list[dict]:
        """CONTAINS children of a node, optionally filtered by symbol_type."""
        self._require_loaded()
        idx = self._idx_by_id.get(node_id)
        if idx is None:
            return []
        out: list[dict] = []
        for (_u, v, kind) in self._g.out_edges(idx):
            if kind != "contains":
                continue
            payload = self._payload_by_id[self._g[v]]
            if symbol_type and payload["domain_tags"].get("symbol_type") != symbol_type:
                continue
            out.append(payload)
        return out

    def who_extends(self, model_name: str, *, include_definers: bool = False) -> list[dict]:
        """Classes whose EXTENDS (and optionally DEFINES) point at the model."""
        self._require_loaded()
        canon_id = self._model_index.get(model_name)
        if canon_id is None:
            return []
        idx = self._idx_by_id[canon_id]
        wanted = {"extends"} | ({"defines"} if include_definers else set())
        out: list[dict] = []
        for (u, _v, kind) in self._g.in_edges(idx):
            if kind not in wanted:
                continue
            payload = dict(self._payload_by_id[self._g[u]])
            payload["relation"] = kind
            payload["module"] = self._module_of(payload["source_uri"])
            out.append(payload)
        return out

    def find_model(self, model_name: str) -> Optional[dict]:
        """Aggregate view: canonical node + all contributing classes' fields/methods."""
        self._require_loaded()
        canon_id = self._model_index.get(model_name)
        if canon_id is None:
            return None
        contributors = self.who_extends(model_name, include_definers=True)
        fields: list[dict] = []
        methods: list[dict] = []
        for c in contributors:
            module = self._module_of(c["source_uri"])
            for child in self.children(c["node_id"]):
                st = child["domain_tags"].get("symbol_type")
                entry = {**child, "module": module}
                if st == "odoo_field":
                    fields.append(entry)
                elif st == "function":
                    methods.append(entry)
        return {
            "model_name": model_name,
            "canonical_id": canon_id,
            "contributors": contributors,
            "fields": fields,
            "methods": methods,
        }

    # --- COLD / lexical (async, I/O) ---

    async def search_symbols(self, query: str, *, limit: int = 20) -> list[dict]:
        """FTS5/BM25 lexical search over title + summary."""
        await self.load()
        sql = (
            "SELECT n.node_id, n.kind, n.title, n.source_uri, n.summary, "
            "n.domain_tags, bm25(nodes_fts) AS score "
            "FROM nodes_fts JOIN nodes n ON n.node_id = nodes_fts.node_id "
            "WHERE nodes_fts MATCH ? ORDER BY score LIMIT ?"
        )
        out: list[dict] = []
        async with self._conn.execute(sql, (query, limit)) as cur:
            async for row in cur:
                out.append({
                    "node_id": row["node_id"], "kind": row["kind"],
                    "title": row["title"], "source_uri": row["source_uri"],
                    "summary": row["summary"], "score": row["score"],
                    "domain_tags": _loads_tags(row["domain_tags"]),
                })
        return out

    async def get_source(self, node_id: str) -> Optional[str]:
        """Resolve a symbol's source slice from disk (COLD), LRU-cached."""
        payload = self._payload_by_id.get(node_id)
        if payload is None:
            return None
        if node_id in self._body_cache:
            self._body_cache.move_to_end(node_id)
            return self._body_cache[node_id]

        tags = payload["domain_tags"]
        lineno, end = tags.get("lineno"), tags.get("end_lineno")
        body: Optional[str] = None
        if self._repo_root and lineno and end:
            path = self._repo_root / payload["source_uri"]
            body = await asyncio.to_thread(self._read_span, path, lineno, end)
        if body is None:
            body = payload.get("summary")

        if body is not None:
            self._body_cache[node_id] = body
            self._body_cache.move_to_end(node_id)
            if len(self._body_cache) > self._body_cache_size:
                self._body_cache.popitem(last=False)
        return body

    # --- helpers ---

    @staticmethod
    def _read_span(path: Path, lineno: int, end: int) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return None
        return "".join(lines[lineno - 1:end])

    @staticmethod
    def _module_of(source_uri: str) -> str:
        """Heuristic Odoo module = top path segment; empty for synthetic URIs."""
        if not source_uri or source_uri.startswith("odoo-model://"):
            return ""
        parts = Path(source_uri).parts
        return parts[0] if parts else ""
```

---

## 7. Superficie de toolkit (siguiente capa, fuera de este spec)

El reader es el motor; un `OdooGraphToolkit` (patrón ai-parrot, `WorkingMemoryToolkit`/`DeterministicGuard`) envolvería estos métodos como herramientas con contrato cerrado:

- `list_models()` · `find_model(name)` · `who_extends(name)` · `describe_module(uri)`
- `get_source(node_id)` · `search_symbols(query)`

Esto convierte la "búsqueda guiada" en llamadas a herramientas deterministas, no navegación libre. **Descopado de este spec.**

---

## 8. Criterios de aceptación

### Extractor
1. Una clase con `_name = 'x.y'` produce: nodo `odoo_model_class`, nodo canónico `odoo_model` (title `x.y`, `source_uri` `odoo-model://x.y`), y arista `DEFINES` clase→canónico.
2. Una clase con `_inherit = 'res.partner'` (sin `_name`) produce arista `EXTENDS` clase→canónico(`res.partner`), y **no** `DEFINES`.
3. `_inherit` como lista y `_inherits` como dict generan una `EXTENDS` por cada nombre.
4. `name = fields.Many2one('res.partner', string='Cliente')` produce nodo `odoo_field` (`field_type=Many2one`, `comodel_name=res.partner`, `string=Cliente`, summary=`Cliente`) e arista `CONTAINS` clase→campo.
5. `@api.depends('a', 'b')` sobre un método deja `domain_tags["decorators"] == [{"name": "depends", "args": ["a", "b"]}]`.
6. Una clase Python normal (sin señales Odoo) produce exactamente lo mismo que `CodeExtractor` base (fallback verificado).
7. `_name = f"x.{var}"` (dinámico) no rompe: la clase se emite sin enlaces canónicos.
8. Todo nodo de símbolo lleva `lineno`/`end_lineno` en `domain_tags`.

### Persistence (regresión)
9. `replace_document_slice` sobre un fichero no borra el nodo canónico de un modelo que ese fichero extiende.
10. `is_stale` devuelve `False` cuando `mtime` coincide; `True` cuando el `sha1` difiere.

### Reader
11. Tras `load()`, `who_extends('res.partner')` lista todas las clases con `EXTENDS` al canónico, cada una con su `module`.
12. `find_model('res.partner')` agrega `fields` y `methods` de **todos** los contribuyentes (definidor + extensores).
13. `search_symbols('reconcile')` devuelve resultados ordenados por BM25 ascendente (mejor primero).
14. `get_source(node_id)` con `repo_root` y span devuelve el slice exacto de líneas; sin `repo_root` devuelve el summary.
15. El LRU de cuerpos no excede `body_cache_size`.

### Tests sugeridos
- `tests/graphindex/test_odoo_extractor.py` — fixtures con un módulo `_name`, un módulo extensor `_inherit`, campos relacionales y decoradores.
- `tests/graphindex/test_sqlite_reader.py` — construir artefacto en `tmp_path` vía `SQLitePersistence`, luego validar navegación/búsqueda/`get_source`.

---

## 9. Decisiones abiertas

- **OKF RelationType para `EXTENDS`** (§2.3): opción (a) preferida; (b) como fallback con TODO.
- **Recolección de nodos canónicos huérfanos**: descopada en v1; candidata a un paso de `analytics`.
- **COLD via disco vs tabla de cuerpos**: este spec asume lectura desde disco por span (artefacto pequeño, requiere el repo presente para `get_source`). Si se necesita portabilidad total (p. ej. Cloud Run sin repo), añadir tabla `node_bodies(node_id, body)` poblada en persist y resolver `get_source` desde ahí.
```

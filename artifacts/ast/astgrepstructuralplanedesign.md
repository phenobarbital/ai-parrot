# Structural Plane — ast-grep sobre el LLM Wiki de ai-parrot

> Diseño para: (1) un backend estructural declarativo (reglas YAML sobre ast-grep) que sustituye los walkers a mano de `wiki/languages/*`; (2) símbolos como nodos de primera clase en el wiki plane; (3) las tools `ast_grep` / `ast_edit` (+ `symbol_lookup`, `blast_radius`, `code_outline`) expuestas por `wikitoolkit mcp` a Claude Code y como `AbstractToolkit` a cualquier agente; (4) su uso en `dev_loop` / `dev_flow`.
>
> Todo lo que sigue está anclado en `main` (verificado 2026-09-02) y en pruebas reales contra `ast-grep-py 0.45.3` en sandbox (§1.2). Complementa `claude/handle-only-execution-design.md` (mismo principio: determinista donde se pueda, LLM donde aporte).

## 0. Decisiones

1. **Sin `code_ast`.** Es un wrapper de investigación (28 commits, "se actualiza según necesidad"); su valor histórico (autocompilar gramáticas) quedó deprecado con tree-sitter ≥0.22, versión que ya fijamos. `languages/treesitter.py` ya cubre ese seam.
2. **`ast-grep-py` como extra opcional `wiki-structural`**, no como dependencia core. Degradación en dos niveles: sin `ast-grep-py` → scanners actuales (tree-sitter o heurística); sin nada → heurística stdlib. Nada de lo existente se rompe.
3. **No se persiste el AST.** El AST es la fuente; reparsear es más barato que deserializar y ast-grep sólo corre sobre código. Se persisten **hechos derivados**: `SymbolRecord` (kind, qualname, rango, firma, doc, padre) y aristas `defines` / `references` / `calls`.
4. **Dos niveles en cada consulta.** El grafo/FTS responde *dónde* (ficheros y símbolos candidatos, callers transitivos, blast radius); ast-grep responde *exactamente qué* y *reescribe* in situ sólo en ese conjunto. Es lo que oh-my-pi no tiene: sus `ast_grep`/`ast_edit` barren el repo entero en cada llamada.
5. **`ast_edit` es dry-run por defecto**, atómica al aplicar, y hace el upsert síncrono de los ficheros que tocó. El hook `post-commit` pasa a ser backstop; la invariante de frescura la da un hash por página de fichero con *read-repair* (§6).
6. **El outline renderizado se conserva** (byte-parity con los scanners actuales) pero pasa a ser una *proyección* de `symbols`, no la fuente de verdad.

## 1. Estado actual y hallazgos

### 1.1 Lo que existe en el repo (resumen operativo)

| Pieza | Dónde | Relevante para este diseño |
|---|---|---|
| Página por fichero | `wiki/repo_scan.py` → `FileSlice`, `build_file_slice()`; ids `file:<relpath>` / `dir:<relpath>` | Body = `# relpath` + `## API outline` (líneas de texto) + `## Content` (head). **No hay hash por página**; `updated_at` sólo. |
| Scanners | `wiki/languages/{python,javascript,php,rust,perl}.py` sobre `base.LanguageScanner` (`outline`, `build_reference_index`, `resolve_import`, `mode`) | `LanguageOutline(summary, outline: list[str], imports: list[str])`. Walk manual sobre `node.children` (nunca `tree_sitter.Query`). Registro explícito en `languages/__init__.py`. |
| Seam tree-sitter | `wiki/languages/treesitter.py::get_parser(lang) -> Parser | None` | Cache por proceso; nunca lanza. Wheels individuales del extra `wiki-languages`. |
| Store | `wiki/store.py::BaseWikiStore` (`upsert_pages`, `add_edges`, `replace_source_slice`, `search_fts`, `neighbors`, …); `WikiPageRecord` en `store.py:224`; aristas = tuplas `(src, dst, rel[, provenance])` | `EdgeKind` (`CONTAINS/REFERENCES/DEFINES/MENTIONS/…`) vive en `graphindex/schema.py`, no en el wiki. Backends: SQLite (FTS5), ArangoDB (`wiki_pages`/`wiki_edges` + view BM25), InMemory/OKF. |
| Frescura | `wiki/sources.py::SourceCollectionManager` (`file_hash` SHA-1 + `mtime`, `is_stale`) | Es *por fuente*; `wikitoolkit upsert --changed` usa `git diff-tree … HEAD` (`cli.py:1335`) y `scan_repository(rel_paths=…)`. |
| Tools MCP | `wiki/tools.py` (`AbstractTool` explícitos: `wiki_query`, `wiki_page`, `wiki_related`, `wiki_remember`, `wiki_note`, `wiki_status`, `vault_ingest`) → `create_wiki_tools()` | `wiki/mcp_server.py::create_wiki_mcp_server()` sobre `parrot.mcp.local_server.StdioMCPServer`; `MCPToolAdapter` añade `confirm` obligatorio si `routing_meta["requires_confirmation"]`. |
| Toolkit agente | `wiki/toolkit.py::LLMWikiToolkit(AbstractToolkit)`, `tool_prefix="wiki"` | Un método `async` público = una tool; args schema derivado de la firma. `ToolManager.register_toolkit()`; sharing entre agentes vía `_auto_wire_toolkit`. |
| Claude Code | `wiki/claude_code/{installer,assets,hook}.py` | `.mcp.json` → `wikitoolkit mcp`; PreToolUse nudge; git `post-commit` → `upsert --changed`. |
| dev_loop / dev_flow | `flows/dev_loop/` (AgentsFlow; nodos `research → development → qa → …`), `flows/dev_flow/` (reusa todo) | Edición actual = `Edit/Write` de Claude Code vía `ClaudeCodeDispatchProfile.allowed_tools`; `strict_mcp_config=True`; `ClaudeAgentRunOptions.mcp_servers` existe pero el dispatcher **no lo rellena**. `DevLoopWikiSearch.build_research_context()` ya inyecta contexto del wiki al nodo research. |

### 1.2 Verificado contra `ast-grep-py 0.45.3` (sandbox)

Estos son los hechos que condicionan la implementación; no son suposiciones.

- **Lenguajes built-in que necesitamos**: `python`, `javascript`, `typescript`, `tsx`, `php`, `rust` (además `go, java, c, cpp, csharp, ruby, kotlin, swift, scala, html, css, json, yaml, bash, lua, elixir, haskell, nix, solidity`). **No** están `perl`, `sql`, `svelte`.
- **Perl funciona por registro dinámico** usando el `.so` que ya instala el wheel `tree-sitter-perl` del extra `wiki-languages` (exporta `tree_sitter_perl`): `register_dynamic_language({"perl": {"library_path": <…/_binding.abi3.so>, "language_symbol": "tree_sitter_perl", "extensions": ["pl","pm","t"]}})`. Reglas por `kind` funcionan (`package_statement`, `use_statement`, `subroutine_declaration_statement`); los *patterns* (`sub $NAME { $$$ }`) devolvieron vacío → para Perl sólo reglas `kind`.
- **Svelte**: se sigue extrayendo el `<script>` con `_extract_script_blocks()` (ya existe) y se parsea como `javascript`/`typescript`.
- **Un lenguaje no soportado hace *panic* en pyo3**: `SgRoot("x", "perl")` sin registro lanza `PanicException`, que hereda de `BaseException` — **un `except Exception` no lo captura**. Hay que validar el lenguaje contra una whitelist *antes* de construir `SgRoot`.
- **API**: `SgRoot(src, lang).root()`; `find_all(pattern=…)`, `find_all(kind=…)` o `find_all({"rule": {...}, "constraints": …})` — un dict posicional **debe** llevar la clave `rule` (`Config`), pasar la regla pelada falla con `missing field 'rule'`. `SgNode`: `kind() text() range() field(name) parent() ancestors() prev() next() find() find_all() get_match(v) get_multiple_matches(v) is_named() replace(text) -> Edit`; `root.commit_edits(list[Edit]) -> str`. `Edit` expone `start_pos`, `end_pos`, `inserted_text` (offsets de byte).
- **`$$$VAR` incluye nodos anónimos** (comas): al reconstruir argumentos hay que filtrar `is_named()`. Verificado: `helper($$$ARGS)` no matchea `obj.helper(3)` (bien: el matching es estructural).
- Reglas YAML por `kind` con `inside/has/not/any` + extractores fijos reproducen **exactamente** las líneas de outline de los cinco scanners (§4.4 muestra la salida).
- `transform` funciona desde Python: `find({"rule": {"pattern": "console.log($X)"}, "transform": {"SNAKE": {"convert": {"source": "$X", "toCase": "snakeCase"}}}}).get_transformed("SNAKE")` → `user_name`. Un `kind` inexistente para la gramática lanza `RuntimeError: cannot get matcher` (excepción normal, capturable).
- Kinds verificados que usan las tablas de §4.3: Python `call` (`field: function`), `class_definition` (`field: superclasses`); TS `class_heritage`, `extends_clause`, `implements_clause`, `call_expression`; PHP `namespace_definition`, `namespace_use_declaration`, `base_clause`, `class_interface_clause`, `function_call_expression`, `member_call_expression`, `scoped_call_expression`; Rust `impl_item` (`field: trait`), `call_expression`; Perl `package_statement`, `class_statement`, `role_statement`, `method_declaration_statement`, `subroutine_declaration_statement`, `require_expression`, `use_statement`, `variable_declaration` (para `field $x`).

## 2. Arquitectura

```
                    ┌──────────────────────────── wiki plane (persistente) ────────────────────────────┐
                    │  pages: file:<rel>   dir:<rel>   sym:<rel>#<qualname>          + symbols table    │
                    │  edges: contains | references | defines | calls | extends | implements            │
                    │  file pages llevan content_hash (blob sha1) ── read-repair al consultar          │
                    └───────────────▲──────────────────────────────────────────▲───────────────────────┘
                                    │ upsert (build / --changed / síncrono)     │ lookup (FTS + neighbors)
   ┌────────────────────────────────┴───────────────┐         ┌────────────────┴──────────────────────┐
   │  EXTRACCIÓN (determinista, sin LLM)             │         │  TOOLS (parrot.knowledge.wiki.structural)│
   │  languages/astgrep.py  ← rules/<lang>.yaml      │         │  symbol_lookup   blast_radius  code_outline│
   │  StructuralBackend.extract(src, lang)           │         │  ast_grep  (scope ← grafo)  ast_edit      │
   │    → SymbolRecord[] + refs + imports            │         │     dry_run → EditPlan(token) → apply     │
   │  fallback: scanners tree-sitter / heurística    │         │     atómico + upsert síncrono             │
   └────────────────────────────────────────────────┘         └───┬──────────────────────┬─────────────┘
                                                                   │                      │
                                          ┌────────────────────────▼───┐   ┌──────────────▼──────────────┐
                                          │ wikitoolkit mcp (Stdio)     │   │ CodeStructuralToolkit         │
                                          │ Claude Code / Codex / Gemini│   │ (AbstractToolkit, prefix code)│
                                          └────────────┬───────────────┘   │ cualquier agente ai-parrot    │
                                                       │                   └──────────────┬──────────────┘
                                          ┌────────────▼──────────────────────────────────▼──────────────┐
                                          │ dev_loop / dev_flow: research(symbol_lookup) · development    │
                                          │ (ast_grep+ast_edit vía MCP) · qa (ast_grep read-only) · sync  │
                                          └───────────────────────────────────────────────────────────────┘
```

Módulos nuevos (todos bajo `packages/ai-parrot/src/parrot/knowledge/wiki/`):

| Módulo | Responsabilidad |
|---|---|
| `languages/astgrep.py` | Seam opcional: `is_available()`, `supported_language(name) -> bool` (whitelist + registro dinámico Perl), `parse(src, lang) -> SgRoot`, `RuleSet.load(lang)`, `extract(src, lang, rel_path) -> StructuralOutline`. Nunca lanza (captura `BaseException` sólo alrededor de `SgRoot`). |
| `languages/rules/<lang>.yaml` | Reglas declarativas por lenguaje (§4). Empaquetadas como package data. |
| `languages/render.py` | `render_outline(symbols) -> list[str]`: proyección a las líneas de outline actuales (byte-parity). |
| `symbols.py` | `SymbolRecord`, `SymbolRef`, `sym_concept_id()`, `qualname()`; helpers para páginas `sym:` y aristas. |
| `structural/service.py` | `StructuralService`: orquesta store + astgrep; `search()`, `plan_edit()`, `apply_edit()`, `blast_radius()`, `outline()`. Único punto que toca disco. |
| `structural/tools.py` | `AstGrepTool`, `AstEditTool`, `SymbolLookupTool`, `BlastRadiusTool`, `CodeOutlineTool` (`AbstractTool`, mismo patrón que `wiki/tools.py`) → `create_structural_tools(store, root, config)`. |
| `structural/toolkit.py` | `CodeStructuralToolkit(AbstractToolkit)`, `tool_prefix="code"`, `confirming_tools={"ast_edit"}`. |
| `structural/edit_plan.py` | `EditPlan` persistido en `.parrot/edit_plans/<token>.json` con TTL; hash de cada fichero en el momento del dry-run. |

Cambios en módulos existentes: `languages/base.py` (`LanguageOutline.symbols`, `LanguageOutline.refs`), `repo_scan.py` (páginas `sym:`, aristas `defines`/`calls`, `content_hash`), `store.py` + `arango_store.py` + `file_store.py` (tabla/colección `symbols`, columna `content_hash`), `mcp_server.py` (`create_structural_tools`), `claude_code/assets.py` (hooks adicionales, permisos `mcp__wikitoolkit__ast_*`), `flows/dev_loop/dispatchers/claude.py` (`mcp_servers`), `flows/dev_loop/nodes/*.py` (`allowed_tools`), `_subagent_data/*.md` (instrucciones).

## 3. Modelo de datos

### 3.1 `SymbolRecord`

```python
# parrot/knowledge/wiki/symbols.py
class SymbolKind(str, Enum):
    MODULE = "module"; CLASS = "class"; INTERFACE = "interface"; TRAIT = "trait"
    ENUM = "enum"; STRUCT = "struct"; IMPL = "impl"; FUNCTION = "function"
    METHOD = "method"; CONST = "const"; TYPE = "type"; PACKAGE = "package"
    ROLE = "role"; FIELD = "field"; ATTRIBUTE = "attribute"; MOD = "mod"

class SymbolRecord(BaseModel):
    rel_path: str                      # POSIX, relativo al root
    language: str                      # nombre del scanner: python|javascript|php|rust|perl
    kind: SymbolKind
    name: str                          # identificador local
    qualname: str                      # "UserService.get_user", "App\\Models\\User::getFullName", "Parser::new"
    parent: str | None = None          # qualname del contenedor (clase/impl/package)
    signature: str = ""                # texto de la firma (params + retorno) tal como aparece
    doc: str = ""                      # primera línea de docstring / doc-comment
    exported: bool = False             # export / pub / visibilidad pública
    is_async: bool = False
    start_line: int; end_line: int     # 1-based, inclusivo
    start_byte: int; end_byte: int     # offsets de byte en el fichero (para ast_edit)
    node_kind: str                     # kind de tree-sitter que lo produjo (para reglas)
    decorators: list[str] = []         # @decorators / #[attrs] / modifiers, opcional
    content_hash: str                  # sha1 del texto del nodo → detecta símbolos sin cambios

class SymbolRef(BaseModel):
    """Referencia saliente desde un símbolo: llamada, herencia, implementación."""
    src_qualname: str
    rel: Literal["calls", "extends", "implements", "uses"]
    target_text: str                   # nombre tal como aparece ("BaseService", "helper", "self.repo.get")
    line: int

class StructuralOutline(BaseModel):
    summary: str = ""
    symbols: list[SymbolRecord] = []
    refs: list[SymbolRef] = []
    imports: list[str] = []            # mismo contrato que hoy: specs crudos → resolve_import()
```

`LanguageOutline` (base.py) gana `symbols: list[SymbolRecord] = []` y `refs: list[SymbolRef] = []` con default vacío: los scanners actuales siguen válidos sin tocar una línea, y `outline: list[str]` se rellena con `render_outline(symbols)` cuando `symbols` no está vacío.

### 3.2 Identidad y páginas

- `sym_concept_id(rel_path, qualname) -> f"sym:{rel_path}#{qualname}"`. Estable entre re-scans mientras no cambie el qualname; una renombración produce delete + insert, que es lo correcto (las aristas entrantes de otros ficheros quedan colgando hasta su propio upsert → `broken_edges()` ya existe para detectarlas).
- Página `sym:` = `WikiPageRecord(concept_id=sym_id, node_id=rel_path, title=qualname, category="symbol", summary=doc, body=<firma + doc + rango + texto del nodo hasta N chars>, source_id=<el de la fuente file>)`. Van en el **mismo `replace_source_slice()`** que la página `file:`, así el borrado y la re-ingesta siguen siendo atómicos por fuente.
- Página `file:`: sin cambios de forma; gana `content_hash` (ver 3.4) y el `## API outline` sale de `render_outline`.
- `context.py::_ID_KINDS` ya contempla `func|class`; se añade `sym` para que `split_namespaced_id`/`stub_line` lo traten como id de página.

### 3.3 Aristas

| Arista | src → dst | Provenance | Origen |
|---|---|---|---|
| `defines` | `file:<rel>` → `sym:<rel>#<q>` | extracted | siempre |
| `contains` | `sym:<rel>#<Parent>` → `sym:<rel>#<Parent.child>` | extracted | `parent` |
| `references` | `file:` → `file:` | extracted | import resolution (sin cambios) |
| `calls` | `sym:` → `sym:` | extracted / **inferred** | `SymbolRef(rel="calls")` resuelto por `SymbolResolver` (3.5) |
| `extends` / `implements` | `sym:` → `sym:` | extracted / inferred | `SymbolRef` |

Se reutilizan los nombres de `graphindex/schema.py::EdgeKind` (`CONTAINS`, `REFERENCES`, `DEFINES`, `EXTENDS`) para que el mirror a GraphIndex sea 1:1; `calls` e `implements` se añaden a ese enum.

### 3.4 Persistencia

SQLite (`store.py::WIKI_SCHEMA_SQL`, `SCHEMA_VERSION → "2"`, migración idempotente vía `_MIGRATION_COLUMNS` como ya se hace con `origin`/`asserted_by`):

```sql
ALTER TABLE pages ADD COLUMN content_hash TEXT;          -- sha1 del fichero para file:, del nodo para sym:
CREATE TABLE IF NOT EXISTS symbols (
  concept_id TEXT PRIMARY KEY,        -- sym:<rel>#<qualname>
  rel_path TEXT NOT NULL, language TEXT NOT NULL, kind TEXT NOT NULL,
  name TEXT NOT NULL, qualname TEXT NOT NULL, parent TEXT,
  signature TEXT DEFAULT '', doc TEXT DEFAULT '', exported INTEGER DEFAULT 0,
  start_line INTEGER, end_line INTEGER, start_byte INTEGER, end_byte INTEGER,
  node_kind TEXT, content_hash TEXT, source_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(rel_path);
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(concept_id UNINDEXED, name, qualname, doc, signature, tokenize='unicode61');
```

ArangoDB: colección `wiki_symbols` (+ índices `name`, `rel_path`, `qualname`) y el view BM25 existente extendido con `wiki_symbols`. InMemory/OKF: página `sym:` con el `SymbolRecord` en frontmatter (`_write_page_file` ya serializa YAML). `BaseWikiStore` gana:

```python
async def upsert_symbols(self, symbols: list[SymbolRecord]) -> int
async def symbols_for(self, rel_path: str) -> list[SymbolRecord]
async def find_symbols(self, name: str | None = None, qualname_prefix: str | None = None,
                       kind: str | None = None, language: str | None = None,
                       limit: int = 50) -> list[SymbolRecord]
async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]
async def page_hashes(self, concept_ids: list[str]) -> dict[str, str | None]
```

`replace_source_slice()` borra también las filas de `symbols` del `source_id` (misma transacción).

### 3.5 Resolución de referencias (`calls`, `extends`)

`SymbolResolver` corre en `build_import_edges()` (donde ya hay el índice por lenguaje) y resuelve `SymbolRef.target_text` en tres pasos deterministas: (1) mismo fichero por `qualname`/`name`; (2) ficheros alcanzables por las aristas `references` del fichero origen (imports resueltos) por `name`; (3) índice global por `name` *sólo si es único* en el repo. Los pasos 1–2 producen `provenance="extracted"`; el 3, `"inferred"`. Sin candidato único → no se crea arista (mejor un grafo incompleto que uno mentiroso, y `ast_grep` cubre el hueco en vivo). No se intenta resolución por tipos: eso es trabajo de LSP, no de este plano.

## 4. Backend estructural: mapeo scanner → reglas YAML

### 4.1 Esquema del fichero de reglas

Las reglas son **puramente declarativas** (sin código en el YAML). Todo lo que necesita lógica — extraer un doc-comment, saltar `#[derive]`, leer el primer docstring — se expresa como el nombre de un *extractor* fijo implementado en `astgrep.py`. Así las reglas se validan con `sg test` y se revisan como datos.

```yaml
# packages/ai-parrot/src/parrot/knowledge/wiki/languages/rules/<lang>.yaml
language: python                 # nombre ast-grep; typescript/tsx/javascript comparten fichero via `aliases`
aliases: []                      # p.ej. [tsx, javascript] en typescript.yaml
summary: module_docstring        # extractor para LanguageOutline.summary
symbols:
  - id: class                    # → SymbolKind
    rule: { kind: class_definition }          # regla ast-grep (Rule), evaluada con find_all({"rule": ...})
    name: { field: name }        # cómo obtener el nombre: field | path (lista de kinds) | text
    signature: { field: parameters }          # opcional; para class: superclasses
    doc: first_docstring         # extractor: first_docstring | leading_comment | leading_doc_comment | pod_head2 | none
    parent: { ancestor: class_definition, name: { field: name } }   # opcional: cómo calcular `parent`
    exported: { inside: export_statement }    # opcional: inside <kind> | has <kind> | always | never
    async: { has: async }        # opcional: token hijo
refs:
  - rel: calls
    rule: { kind: call, not: { inside: { kind: decorator } } }
    target: { field: function }
    scope: { ancestor: [function_definition, class_definition] }   # qué símbolo es el src
  - rel: extends
    rule: { kind: class_definition, has: { field: superclasses } }
    target: { field: superclasses, each: identifier }
imports:
  - { rule: { kind: import_statement } }
  - { rule: { kind: import_from_statement } }
  # el spec crudo se normaliza con el mismo regex/AST que hoy (no cambia el contrato de `imports`)
```

Extractores disponibles (implementados una vez, compartidos por todos los lenguajes): `first_docstring` (Python: primer `expression_statement/string` del `body`), `leading_comment` (comentario `/** */` inmediatamente anterior; si el nodo está dentro de `export_statement`, mira antes del wrapper), `leading_doc_comment` (como el anterior pero salta `attribute_item` — Rust `#[derive]`), `pod_head2` (Perl: mapa `=head2 <name>` → texto, ya implementado en `perl.py::_head2_docs`), `module_docstring`, `first_heading_comment`.

### 4.2 Loader y ejecución

```python
# languages/astgrep.py (esqueleto)
_BUILTIN = frozenset({"python","javascript","typescript","tsx","php","rust", ...})
_DYNAMIC: dict[str, str] = {"perl": "tree_sitter_perl"}     # nombre → símbolo C del wheel

def supported_language(lang: str) -> bool:
    if lang in _BUILTIN: return True
    return _register_dynamic(lang)      # localiza <site-packages>/tree_sitter_<lang>/_binding*.so; cachea True/False

def parse(src: str, lang: str) -> "SgRoot | None":
    if not is_available() or not supported_language(lang): return None
    try:
        return SgRoot(src, lang)
    except BaseException:               # pyo3 PanicException hereda de BaseException
        logger.warning("ast-grep panicked parsing %s", lang); return None

def extract(src: str, lang: str, rel_path: str) -> StructuralOutline | None:
    root = parse(src, lang);  rules = RuleSet.load(lang)
    if root is None or rules is None: return None
    node = root.root(); out = StructuralOutline(summary=EXTRACTORS[rules.summary](node))
    for spec in rules.symbols:
        for m in node.find_all({"rule": spec.rule}):
            out.symbols.append(_to_symbol(m, spec, rel_path, lang))
    for spec in rules.refs: ...
    for spec in rules.imports: ...
    return out
```

Integración en cada scanner (idéntica para los cinco), manteniendo la cadena de degradación:

```python
def outline(self, source, rel_path):
    so = astgrep.extract(source, "php", rel_path)        # 1º ast-grep + reglas YAML
    if so is not None:
        return LanguageOutline(summary=so.summary, outline=render_outline(so.symbols),
                               imports=so.imports, symbols=so.symbols, refs=so.refs)
    parser = get_parser("php")                             # 2º tree-sitter walker actual
    return self._outline_treesitter(parser, source) if parser else self._outline_heuristic(source)
```

`PythonScanner` es el único caso donde **la fuente de verdad sigue siendo `ast`** (más fiel para firmas, decoradores, `async`, imports relativos); ast-grep sólo le añade `start_byte/end_byte` y los `refs` de llamadas. Razón: `ast` ya está, es exacto y gratis.

### 4.3 Tablas de mapeo por lenguaje

Cada fila es: lo que el scanner actual extrae → `kind` de tree-sitter/ast-grep que lo captura → regla → línea de outline que debe reproducir (parity test).

**Python** (`python.py`, `mode="ast"`; hoy sólo nivel superior + métodos de clase)

| Construcción | `kind` | Regla | Outline |
|---|---|---|---|
| clase | `class_definition` | `{kind: class_definition}` | `class X: <doc>` |
| función top-level | `function_definition` | `{kind: function_definition, not: {inside: {kind: class_definition, stopBy: end}}}` | `def f(a, b): <doc>` |
| método | `function_definition` | `{kind: function_definition, inside: {kind: class_definition, stopBy: end}}`, `parent: {ancestor: class_definition}` | `    def m(self, x): <doc>` |
| import | `import_statement`, `import_from_statement` | — | `imports` (sólo absolutos, como hoy) |
| llamada (nuevo) | `call` | `target: {field: function}` | arista `calls` |
| herencia (nuevo) | `class_definition` + `field: superclasses` | — | arista `extends` |

**JavaScript / TypeScript / TSX / Svelte** (`javascript.py`; grammar por sufijo y `lang` del `<script>`)

| Construcción | `kind` | Regla | Outline |
|---|---|---|---|
| clase | `class_declaration` | `exported: {inside: export_statement}` | `export class X: <doc>` |
| función | `function_declaration` | idem | `export function f(a, b): <doc>` |
| método | `method_definition` | `{kind: method_definition, inside: {kind: class_body}}`, `parent: {ancestor: class_declaration}` | `    method(...)` (nuevo nivel, hoy no se emite) |
| interface (TS) | `interface_declaration` | idem exported | `export interface I: <doc>` |
| type alias (TS) | `type_alias_declaration` | idem | `export type T` |
| const exportada | `lexical_declaration` | `{kind: lexical_declaration, inside: {kind: export_statement}}`, `name: {path: [variable_declarator, name]}` | `export const C: <doc>` |
| import | `import_statement` | — | `imports` (se siguen leyendo del **raw** para Svelte, como hoy) |
| llamada | `call_expression` | `target: {field: function}` | `calls` |
| herencia | `class_heritage` | — | `extends` / `implements` |

**PHP** (`php.py`)

| Construcción | `kind` | Regla | Outline |
|---|---|---|---|
| class / interface / trait / enum | `class_declaration`, `interface_declaration`, `trait_declaration`, `enum_declaration` | `{kind: …}` con `doc: leading_comment` | `class User: <doc>` / `interface I` / `trait T` / `enum E` |
| método | `method_declaration` | `parent: {ancestor: [class_declaration, trait_declaration, enum_declaration]}` | `    def getFullName($prefix = ''): <doc>` |
| función | `function_definition` | — | `function helper($a, $b): <doc>` |
| use | `namespace_use_declaration` | — | `imports` (`A\B`, grupos expandidos como hoy) |
| namespace (nuevo) | `namespace_definition` | prefijo del `qualname` (`App\Models\User`) | — |
| llamada | `function_call_expression`, `member_call_expression`, `scoped_call_expression` | `target: {field: function|name}` | `calls` |
| herencia | `base_clause`, `class_interface_clause` | — | `extends` / `implements` |

**Rust** (`rust.py`; sólo `pub` salvo dentro de `impl`)

| Construcción | `kind` | Regla | Outline |
|---|---|---|---|
| struct / enum / trait / mod | `struct_item`, `enum_item`, `trait_item`, `mod_item` | `{kind: …, has: {kind: visibility_modifier}}`, `doc: leading_doc_comment` | `pub struct Parser: <doc>` |
| impl | `impl_item` | `name: {field: type}` | `impl Parser:` |
| fn | `function_item` | `{kind: function_item, any: [{has: {kind: visibility_modifier}}, {inside: {kind: impl_item, stopBy: end}}]}`, `parent: {ancestor: impl_item, name: {field: type}}` | `    pub fn new(config: Config) -> Self: <doc>` |
| use / mod | `use_declaration`, `mod_item` | — | `imports` (`a::b`, `mod:<name>`) |
| llamada | `call_expression` (no existe `method_call_expression`: `a.b()` es `call_expression` cuya `function` es un `field_expression`) | `target: {field: function}` | `calls` |
| trait impl | `impl_item` con `field: trait` (verificado: `impl Display for X` → `Display`) | — | `implements` |

**Perl** (`perl.py`; vía `register_dynamic_language`, **sólo reglas `kind`**)

| Construcción | `kind` | Regla | Outline |
|---|---|---|---|
| package / class / role | `package_statement`, `class_statement`, `role_statement` | `doc: pod_head2` (fallback `leading_comment`) | `package Foo::Bar` / `class Point: <doc>` |
| sub / method | `subroutine_declaration_statement`, `method_declaration_statement` | `parent: {ancestor: [package_statement…]}` — nota: en Perl el "padre" es *el último `package` que precede*, no un ancestro → extractor `preceding_package` | `    sub bar($self, $x): <doc>` |
| has / field | `expression_statement` con llamada `has`; `variable_declaration` con `field` | reglas `has: {regex: ^has$}` / `_is_field_decl` se traslada como `{kind: expression_statement, has: {kind: function, regex: '^(has|field)$'}}` | `    has name: Str` / `    field $x` |
| use / require | `use_statement`, `require_expression` | — | `imports` (filtro de pragmas como hoy) |

Si el registro dinámico falla (wheel ausente, símbolo no exportado), Perl cae al walker actual sin ruido: es exactamente el mismo `Parser | None` que ya maneja `treesitter.py`.

### 4.4 Evidencia de paridad (salida real del prototipo en sandbox)

```
=== typescript
  class     UserService      parent=None         exp=True  L2-5   doc='Main service class.'
  method    createUser       parent=UserService  exp=False L4-4   doc='Create a user.'
  function  createUser       parent=None         exp=True  L7-7   doc='Create a new user.'
  function  internalHelper   parent=None         exp=False L8-8   doc=''
  interface UserRecord       parent=None         exp=True  L10-10 doc='Shape of a user row.'
  const     DEFAULT_TIMEOUT  parent=None         exp=True  L12-12 doc='Request timeout in ms.'
=== php
  class     User             L5-8   doc='Represents an application user.'
  method    getFullName      parent=User  doc='Get the full name.'
  interface Serializable · trait HasTimestamps · enum Status · function helper_function doc='Utility helper.'
=== rust
  struct Parser doc='A document parser.' (saltando #[derive]) · impl Parser · fn new parent=Parser doc='Create a parser.'
  fn private_helper parent=Parser (no-pub dentro de impl, como hoy) · trait Visitor · mod utils · enum Kind · [fn not_pub omitido]
=== perl (dinámico)  package_statement Foo::Bar · use_statement · subroutine_declaration_statement bar
```

Los tests de paridad reutilizan los fixtures de `tests/knowledge/wiki/languages/test_{php,rust,perl,javascript}_plugin.py`: se ejecuta `outline()` con y sin `ast-grep-py` (monkeypatch `astgrep.is_available`) y se exige `outline` idéntico. Es el mismo enfoque que `test_subagent_parity.py`.

## 5. Contratos de las tools

Todas son `AbstractTool` en `structural/tools.py` con `args_schema` Pydantic (mismo patrón que `wiki/tools.py`), devuelven `ToolResult` (`tools/abstract.py:250`) con `result` = modelo serializado, y se registran en `wikitoolkit mcp` vía `create_structural_tools()`. `CodeStructuralToolkit` las reexpone como `code_<name>` para agentes ai-parrot delegando en el mismo `StructuralService`, así hay **una** implementación y dos superficies.

Principios comunes: rutas siempre relativas al root del proyecto (`load_effective_config(root)`), nunca fuera de él (`Path.resolve()` + `is_relative_to`); los ficheros `.parrot/`, `.git/` y los `DEFAULT_EXCLUDE_DIRS` de `repo_scan.py` están vedados; presupuesto de tokens en salida (`context.pack_results` / `truncate_to_tokens`), nunca volcar ficheros enteros.

### 5.1 `symbol_lookup` — "¿dónde está X?"

```python
class SymbolLookupInput(BaseModel):
    query: str = Field(..., description="Nombre, qualname o texto libre (FTS sobre name/qualname/doc/signature)")
    kind: SymbolKind | None = None
    language: str | None = None
    path_prefix: str | None = None       # restringir a un subárbol
    limit: int = Field(20, le=100)
    namespace: str | None = None         # federación, como wiki_query

class SymbolHit(BaseModel):
    symbol_id: str; rel_path: str; qualname: str; kind: SymbolKind
    signature: str; doc: str; start_line: int; end_line: int; exported: bool
    score: float; stale: bool = False    # stale=True si el read-repair detectó hash distinto y reescaneó
class SymbolLookupOutput(BaseModel):
    hits: list[SymbolHit]; total: int; repaired_files: list[str] = []
```

Orden: match exacto de `qualname` → exacto de `name` → FTS. Antes de responder, `StructuralService` hace read-repair de los ficheros de los hits (§6).

### 5.2 `code_outline` — outline de un fichero o símbolo con rango exacto

```python
class CodeOutlineInput(BaseModel):
    target: str = Field(..., description="'file:<rel>' | 'sym:<rel>#<qualname>' | ruta relativa")
    depth: int = Field(2, ge=1, le=4)
    include_source: bool = False         # incluir el texto del nodo (cap 4000 chars) — para sym: únicamente
class CodeOutlineOutput(BaseModel):
    target: str; language: str; symbols: list[SymbolHit]; source: str | None = None; truncated: bool = False
```

### 5.3 `blast_radius` — "¿qué se rompe si toco X?"

```python
class BlastRadiusInput(BaseModel):
    symbol: str = Field(..., description="sym: id o qualname (se resuelve con symbol_lookup exacto)")
    relations: list[Literal["calls","extends","implements","references","contains"]] = ["calls","extends","implements"]
    depth: int = Field(2, ge=1, le=5)
    include_inferred: bool = True         # provenance=inferred marcado, no ocultado
    include_tests: bool = True
class BlastRadiusOutput(BaseModel):
    root: SymbolHit
    impacted: list[ImpactedSymbol]         # {symbol: SymbolHit, via: rel, distance: int, provenance: str}
    files: list[str]                       # conjunto de ficheros — es el `scope` que espera ast_grep/ast_edit
    truncated: bool
```

Implementación: `store.neighbors(direction="in")` iterativo sobre `sym:` con las `relations` pedidas, sin LLM. Es la tool que da el *scope* a las dos siguientes.

### 5.4 `ast_grep` — búsqueda estructural acotada

```python
class AstGrepInput(BaseModel):
    language: str = Field(..., description="python|javascript|typescript|tsx|php|rust|perl")
    pattern: str | None = Field(None, description="Patrón ast-grep con metavariables ($X, $$$ARGS). Perl: no soportado, usar rule.")
    rule: dict | None = Field(None, description="Regla ast-grep (Rule) en YAML/JSON: kind/has/inside/regex/… Excluyente con pattern.")
    constraints: dict | None = None      # ast-grep `constraints` (regex/kind por metavariable)
    scope: list[str] | None = Field(None, description="Ficheros/directorios relativos. Si se omite: candidatos del wiki (symbol_lookup/FTS sobre el texto del patrón) — NUNCA el repo entero salvo scope=['.'] explícito")
    max_files: int = Field(200, le=2000)
    max_matches: int = Field(200, le=1000)
    context_lines: int = Field(0, ge=0, le=5)
    metavars: bool = True                 # devolver capturas de metavariables

class AstMatch(BaseModel):
    rel_path: str; start_line: int; end_line: int; start_byte: int; end_byte: int
    text: str                              # cap 500 chars
    enclosing_symbol: str | None           # sym: id que lo contiene (join por rango con `symbols`)
    metavars: dict[str, str] = {}          # $X → texto; $$$ → lista unida sólo con nodos is_named()
class AstGrepOutput(BaseModel):
    matches: list[AstMatch]; files_scanned: int; files_considered: int
    scope_source: Literal["explicit","wiki_candidates","full_repo"]
    truncated: bool; elapsed_ms: int
```

Resolución de scope cuando no viene explícito: (1) identificadores del patrón (`helper`, `console.log` → `console`, `log`) → `find_symbols(name=…)` + `search_fts` sobre páginas `file:`; (2) unión de `rel_path` de los hits; (3) si queda vacío, `scope_source="full_repo"` limitado por `max_files` y sufijos del lenguaje. Siempre se informa qué scope se usó para que el agente pueda ampliar deliberadamente.

Validación de reglas: `rule` se valida contra un JSON Schema del `Rule` de ast-grep antes de ejecutar (ahorra el `RuntimeError: cannot get matcher` con `kind` inexistente; el error devuelve los `kind` válidos más parecidos usando la lista de kinds vista en el último scan de ese lenguaje).

### 5.5 `ast_edit` — reescritura estructural con plan, preview y aplicación atómica

Dos fases con **token**: sin `apply`, la tool sólo planifica; con `apply=True` + `plan_token`, aplica exactamente lo previsualizado. A través de MCP, `MCPToolAdapter` añade además el argumento `confirm` obligatorio (la tool declara `routing_meta["requires_confirmation"]=True`), igual que los `obsidian_*` destructivos.

```python
class AstEditInput(BaseModel):
    language: str
    pattern: str | None = None; rule: dict | None = None; constraints: dict | None = None
    fix: str = Field(..., description="Plantilla de reemplazo con las mismas metavariables ($X, $$$ARGS)")
    transform: dict | None = Field(None, description="ast-grep `transform` (substring/replace/convert) aplicado a metavariables antes de `fix`")
    scope: list[str] | None = None        # mismas reglas que ast_grep; se recomienda pasar blast_radius.files
    max_files: int = Field(50, le=500); max_edits: int = Field(200, le=2000)
    apply: bool = False
    plan_token: str | None = Field(None, description="Obligatorio con apply=True; obtenido en el dry-run")
    justification: str | None = Field(None, description="Una línea; obligatoria con apply=True (queda en el execution wiki)")

class FileEditPreview(BaseModel):
    rel_path: str; edits: int; unified_diff: str          # diff n=2, cap por fichero
    content_hash_before: str                              # sha1 del fichero en el dry-run
    touched_symbols: list[str]                            # sym: ids cuyo rango intersecta con algún edit
class AstEditPlan(BaseModel):
    plan_token: str; expires_at: str
    files: list[FileEditPreview]; total_edits: int; truncated: bool
    syntax_ok: bool                                       # cada fichero reparseado tras aplicar en memoria: sin nodos ERROR nuevos
    warnings: list[str]                                   # p.ej. "3 matches en tests/", "match dentro de string literal"
class AstEditApplied(BaseModel):
    plan_token: str; files_written: list[str]; total_edits: int
    wiki_upserted: list[str]; wiki_symbols_changed: list[str]
    verification: dict                                    # {"syntax_ok": bool, "reparsed_files": n}
```

Algoritmo de `apply`:

1. Cargar `EditPlan` por token (`.parrot/edit_plans/<token>.json`, TTL 30 min). Token desconocido/caducado → error, nunca reejecutar la búsqueda.
2. Para cada fichero: sha1 actual == `content_hash_before`, si no → **abortar todo** con la lista de ficheros que cambiaron (el agente vuelve a planificar). Nada se ha escrito aún.
3. Reconstruir `Edit`s con `SgRoot` sobre el contenido verificado, `commit_edits`, reparsear el resultado y comprobar que el número de nodos `ERROR` (`find_all({"rule": {"kind": "ERROR"}})`) no crece respecto al original (`syntax_ok`). Es *best-effort*: la recuperación de errores de tree-sitter no siempre emite `ERROR` (verificado: `def f(:` pasa limpio), así que para Python se añade `ast.parse()` y para los demás lenguajes el checker nativo si está en PATH (`php -l`, `rustfmt --check`, `tsc --noEmit` sólo sobre los ficheros tocados) es un paso opcional configurable, no bloqueante por defecto.
4. Escritura atómica por fichero (`tmp + os.replace`) sobre la lista completa; si falla una, se restauran las anteriores desde su contenido original en memoria (todo o nada).
5. `scan_repository(root, rel_paths=files_written)` + `_ingest_files(force=True)` — el mismo camino que `upsert --changed` — de forma **síncrona** antes de responder. El wiki nunca queda detrás de una edición propia.
6. Registrar en el execution wiki (`enable_execution_wiki`) `{plan_token, justification, files, total_edits}`.

Plantilla `fix`: se resuelve en Python con `get_match(name).text()` y, para `$$$`, `", ".join(n.text() for n in get_multiple_matches(name) if n.is_named())` (verificado: el join ingenuo mete las comas como nodos anónimos). `transform` se pasa a `Config` y se lee con `get_transformed()`.

### 5.6 Ejemplo de flujo (Claude Code vía MCP)

```
symbol_lookup {query: "helper", kind: "function"}            → sym:parrot/utils.py#helper (L11-13)
blast_radius  {symbol: "sym:parrot/utils.py#helper"}        → files: [parrot/utils.py, parrot/service.py, tests/test_utils.py]
ast_edit      {language: "python", pattern: "helper($$$ARGS)", fix: "utility_helper($$$ARGS)",
               scope: <files>, apply: false}                → plan_token=…, 3 ficheros, 5 edits, syntax_ok, diff
ast_edit      {…, apply: true, plan_token: "…", confirm: true, justification: "rename per FEAT-512"}
                                                            → files_written=3, wiki_upserted=3
ast_grep      {language: "python", pattern: "helper($$$)", scope: <files>}  → matches: []   (verificación)
```

## 6. Frescura y consistencia

- **Hash por página `file:`** (`content_hash` = sha1 del contenido, el mismo que `SourceCollectionManager._compute_hash`). `StructuralService._ensure_fresh(rel_paths)`: compara hash en disco vs. `page_hashes()`; los distintos se reescanean con `scan_repository(rel_paths=…)` + `replace_source_slice` antes de responder (*read-repair*). Coste: un sha1 por fichero candidato, no por repo.
- **Hooks git**: además de `post-commit`, `assets.git_hook_block()` se instala también en `post-checkout`, `post-merge` y `post-rewrite` (mismo bloque marcado; `_changed_files_from_git` gana un modo `--since <old_head>` leyendo `$1`/`ORIG_HEAD`). Con read-repair activo, un hook perdido degrada latencia, no corrección.
- **Working tree sucio**: `wikitoolkit upsert --dirty` (opcional, `git status --porcelain -z`) para agentes que trabajan sin commitear. `ast_edit` no lo necesita: hace su propio upsert.
- **Aristas colgantes** tras renombrar símbolos: `broken_edges()` ya existe; `wikitoolkit lint` las reporta y el siguiente `upsert` de los ficheros dependientes las cierra. `blast_radius` marca `provenance` para que el agente sepa qué es sólido.
- **Concurrencia**: worktrees de `dev_loop` tienen cada uno su `.parrot/` (ya es así: `WORKTREE_BASE_PATH`); los planes de edición viven por worktree.

## 7. Integración en dev_loop / dev_flow

Lo que cambia es *qué tools tiene cada nodo y con qué contexto arranca*; la topología del `AgentsFlow` no se toca.

**Dispatcher.** `ClaudeCodeDispatcher._resolve_run_options()` rellena `ClaudeAgentRunOptions.mcp_servers={"wikitoolkit": assets.mcp_json_entry(root)}` cuando el proyecto tiene wiki construido (`DevLoopWikiSearch.from_project(root) is not None`), y añade a `allowed_tools` los nombres `mcp__wikitoolkit__<tool>` que correspondan al nodo. Con `strict_mcp_config=True` esto es la única forma de que el subproceso vea el servidor; hoy no se pasa nada.

| Nodo | Hoy (`allowed_tools`) | Añadir | Postura |
|---|---|---|---|
| `research` | Read Grep Glob Bash Write SlashCommand | `mcp__wikitoolkit__{wiki_query,symbol_lookup,code_outline,blast_radius,ast_grep}` | read-only; el brief ya lleva `build_research_context()` → se le añade un bloque "Símbolos afectados" (`symbol_lookup` sobre `affected_component`) y el `blast_radius.files` |
| `planner` | idem research | los mismos read-only | el plan cita `sym:` ids, no rutas sueltas |
| `development` | Read Edit Write Bash Grep Glob | `+ ast_grep, ast_edit` (con `confirm`) | `Edit/Write` siguen disponibles para cambios no estructurales; la instrucción en `sdd-worker.md`: "para renombrados, cambios de firma o sustituciones repetidas usa `ast_edit` con el `scope` de `blast_radius`; nunca `sed`" |
| `synthesis` | Read Grep Glob Bash Write Edit | `+ ast_grep, code_outline` | — |
| `qa` | Read Bash (`# NEVER Edit/Write`) | `+ ast_grep, symbol_lookup, blast_radius` | verificación estructural: "no quedan llamadas al símbolo antiguo", "todos los callers del blast radius tienen test" — sigue sin escribir |
| `qa` (repair) | Read Edit Write Bash Grep Glob | `+ ast_edit` | — |
| `feedback_router` | Read | `+ blast_radius` | evalúa riesgo del cambio por tamaño del radio |

**Brief enricher.** `DevLoopToolkit.brief_enricher` es el seam previsto para "un caller con índice de código": la implementación por defecto pasa a rellenar `affected_component` con los `sym:` de `symbol_lookup` y a adjuntar `blast_radius.files` como `suggested_scope`.

**Sync tras el nodo.** Al terminar `development` (y `qa` repair), el runner llama `wikitoolkit upsert --dirty` en el worktree antes de dispatchar `qa`, de modo que QA consulta un wiki que refleja el trabajo del worker aunque éste haya usado `Edit` en vez de `ast_edit`. Es la misma llamada que hoy hace el hook, sólo que en el punto del flow donde importa.

**Métrica.** `dev_loop` ya persiste resultados por nodo; se añade a `DevelopmentResult` un contador `{ast_edits, ast_edit_files, plain_edits}` para medir cuánto del cambio fue estructural — es el dato que justifica (o no) la inversión.

**Codex / Gemini.** `coding_agents.py` instala los hooks y la skill; el MCP se registra igual (`.codex/config.toml` / `.gemini/settings.json` con el mismo `mcp_json_entry`). Los `*CodeDispatcher` correspondientes replican el mapa de `allowed_tools` en su propia nomenclatura.

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| `PanicException` de pyo3 tumba el proceso MCP | `parse()` captura `BaseException` sólo alrededor de `SgRoot`; whitelist previa; test que fuerza un lenguaje inválido |
| Rewrites sintácticos sin tipos (nombres sombreados, strings) | `scope` de `blast_radius` + `warnings` en el plan (match en string/comentario, en tests) + reparse `syntax_ok` + `qa` con `ast_grep` de verificación; nunca `apply` sin token |
| Deriva entre reglas YAML y scanners | Tests de paridad obligatorios por lenguaje; los scanners antiguos no se borran hasta que el extra `wiki-structural` lleve dos releases estable |
| `kind` inexistente → `cannot get matcher` | Validación contra JSON Schema + sugerencia de kinds vistos |
| Perl dinámico: `.so` ausente o símbolo distinto | `supported_language()` cachea `False` y cae al walker; log a nivel debug, no warning en cada fichero |
| Tamaño de la tabla `symbols` en monorepos | Sólo símbolos con `exported=True` o de nivel ≤2 por defecto (`config.symbol_depth`); FTS sobre `symbols` es opcional en Arango |
| Race entre dry-run y apply | Hash por fichero en el plan; abort total si cambia; TTL 30 min |
| Coste de read-repair en consultas amplias | Se aplica sólo a los ficheros de los hits (≤ `limit`), nunca al repo |

## 9. Roadmap incremental

1. **Sprint 1 — Backend + símbolos (sin tools).** `symbols.py`, `languages/astgrep.py`, `rules/{typescript,php,rust}.yaml`, `render.py`, `LanguageOutline.symbols`, migración `SCHEMA_VERSION=2` (SQLite + Arango + OKF), páginas `sym:` y aristas `defines/contains` en `repo_scan`, `content_hash`. Tests de paridad. Extra `wiki-structural = ["ast-grep-py>=0.45"]`. Entregable: `wikitoolkit build` produce símbolos; nada cambia para quien no instala el extra.
2. **Sprint 2 — Lookup y grafo.** `find_symbols`/`search_symbols_fts`, `SymbolResolver` (`calls/extends/implements`), tools `symbol_lookup`, `code_outline`, `blast_radius` en `wikitoolkit mcp` y `CodeStructuralToolkit`. `rules/python.yaml` (refs) y `rules/perl.yaml` (dinámico). Read-repair.
3. **Sprint 3 — `ast_grep` y `ast_edit`.** `StructuralService.search/plan_edit/apply_edit`, `EditPlan`, atomicidad, upsert síncrono, `confirm` vía `MCPToolAdapter`, hooks `post-checkout/merge/rewrite`, permisos en `assets.PERMISSION_RULES` (`mcp__wikitoolkit__ast_*`). E2E: renombrado cross-file en el propio repo de ai-parrot con verificación por `ast_grep`.
4. **Sprint 4 — dev_loop / dev_flow.** `mcp_servers` en el dispatcher, `allowed_tools` por nodo, `sdd-*.md` (con parity test), brief enricher, `upsert --dirty` entre nodos, métrica `ast_edits`. Medir sobre 10 FEATs reales: tokens, turnos y fallos de QA antes/después.

Fuera de alcance deliberado: resolución por tipos (LSP), reglas generadas por LLM en caliente (las reglas son datos revisados), y persistir árboles.

## Fuentes externas

- ast-grep Python API: https://astgrep.com/guide/api-usage/py-api · referencia de reglas: https://ast-grep.github.io/reference/rule.html · rewrite: https://ast-grep.github.io/guide/rewrite-code.html · `ast-grep-py` en PyPI: https://pypi.org/project/ast-grep-py/
- oh-my-pi (`ast_grep` / `ast_edit` con preview y aplicación atómica): https://github.com/can1357/oh-my-pi
- code_ast (descartado): https://github.com/cedricrupb/code_ast

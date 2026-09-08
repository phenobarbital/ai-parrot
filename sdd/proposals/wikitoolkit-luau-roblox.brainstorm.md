---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Soporte Luau/Roblox en wikitoolkit — scanner de código + plano de API

**Date**: 2026-09-06
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

Un agente de asistencia de código para Roblox no tiene hoy ninguna base de
conocimiento utilizable en este repositorio. `wikitoolkit build` solo produce
outline profundo y aristas `references` para ficheros reclamados por un
`LanguageScanner` registrado (`repo_scan.py`); no hay ninguno para Luau, y
`.luau`/`.lua` ni siquiera están en `CODE_SUFFIXES` (`repo_scan.py:68`), así
que un proyecto Roblox se indexa hoy como **cero páginas**.

El problema tiene dos mitades que suelen confundirse:

1. **El código del proyecto.** Dónde vive cada `ModuleScript`, qué exporta, qué
   tipos define, y —crítico— **quién requiere a quién**. En Roblox los
   `require` no son rutas de fichero (`require(script.Parent.Foo)`,
   `require(game.ReplicatedStorage.Shared.Util)`), así que sin resolución
   específica el grafo queda sin aristas y el KB se reduce a una lista de
   ficheros sueltos.

2. **La API de Roblox.** Un agente que no sabe qué es `Players`,
   `:GetPlayerFromCharacter(character)` o `RunService.Heartbeat` no puede
   asistir aunque conozca el código del usuario a la perfección. Ese
   conocimiento no está en el repositorio del usuario: son 682 clases y 351
   enums que vive fuera, en la plataforma.

**Afectados**: desarrolladores Roblox usando agentes de ai-parrot; y el propio
wikitoolkit, cuyo plano de lenguajes queda incompleto para un ecosistema
grande.

---

## Constraints & Requirements

- **El contrato de `LanguageScanner` es sagrado**: `outline()` debe ser
  determinista, offline y **no lanzar nunca** (`base.py:66`). Cualquier fallo
  de parseo degrada a `LanguageOutline` vacío y a página superficial.
- **Nada de dumps vendorizados en el repo.** El conocimiento de la API se
  descarga desde su fuente (`--refresh`), no se commitea.
- **`wikitoolkit build` sigue siendo offline.** La descarga de la API vive en
  un comando aparte, nunca dentro del build.
- **Sin ast-grep para Luau en v1** (ver Options): el plano estructural `sym:`
  queda vacío y el scanner reporta `mode="tree-sitter"`, exactamente igual que
  cuando falta el extra opcional.
- **Robustez frente a ficheros patológicos** (medido, ver Code Context): la
  recuperación de errores de tree-sitter es superlineal. Un `.lua` que no sea
  Luau puede colgar el build. Hace falta un guard duro.
- Grammar disponible solo como wheel con `language()` simple — encaja con
  `_DEFAULT_GRAMMAR_CALLABLES` (`treesitter.py:61`) sin tocar el resolutor.
- Python 3.10+ / async donde toque; el scanner en sí es síncrono como todos
  los demás, la adquisición HTTP con `aiohttp` (nunca `requests`/`httpx`).

---

## Options Explored

### Option A: Un solo plano — scanner + páginas de API en el store del repo

`LuauScanner` registrado en `languages/__init__.py`, y un comando
`wikitoolkit ingest roblox-api` que escribe las ~1.000 páginas de clases y
enums **en el mismo store del proyecto**, junto a las páginas `file:` del
código.

Todo se consulta con un único `wikitoolkit query`, sin configuración extra.

✅ **Pros:**
- Cero configuración: un `query` ve código y API a la vez.
- Las aristas código→API son locales, así que `related` las sigue sin
  ceremonia y `broken_edges()` no se queja.
- Es la ruta más corta a algo demostrable.

❌ **Cons:**
- ~1.000 páginas de API **diluyen el ranking** del plano del repo: BM25 sobre
  un store donde el 90% de las páginas son API de plataforma hará que
  preguntas sobre el código propio compitan contra `Instance`, `BasePart` y
  compañía.
- Cada proyecto Roblox re-descarga y re-genera exactamente las mismas 1.000
  páginas. El coste se multiplica por número de repos.
- Mezcla dos ciclos de vida distintos: el código cambia por commit, la API
  cambia por versión de Roblox.
- Riesgo de interacción con `replace_source_slice()` (`store.py:1176`) y el
  rebuild: hay que garantizar que un `build` no borre las páginas de API.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tree-sitter` | Runtime del parser | ya en `wiki-languages` (`>=0.23`); probado con 0.26.0 |
| `tree-sitter-luau` | Gramática Luau | 1.2.0, wheels abi3 (linux/mac/win), ABI 14, expone `language()` |
| `aiohttp` | Descarga del dump y de creator-docs | ya es dependencia del proyecto |
| `PyYAML` | Parseo de los YAML de creator-docs | verificar si ya está en el árbol de deps |

🔗 **Existing Code to Reuse:**
- `languages/perl.py:211` — `PerlScanner` es el molde exacto de un scanner
  tree-sitter con fallback heurístico.
- `languages/php.py:123` — resolución de imports leyendo un fichero auxiliar
  del repo (`composer.json`) vía `get_scan_root()`; es el patrón literal para
  `sourcemap.json`.
- `store.py:1134` `upsert_pages()` / `store.py:1154` `add_edges()` — escritura
  determinista de páginas y aristas sin pasar por el pipeline LLM.

---

### Option B: Scanner local + plano Roblox como namespace federado ★

Dos planos con ciclos de vida separados, unidos por la federación que **ya
existe** (FEAT-450):

- **Plano del repo**: `LuauScanner` produce páginas `file:` con outline,
  tipos exportados y aristas `require` resueltas vía `sourcemap.json`.
- **Plano Roblox**: `wikitoolkit ingest roblox-api` construye un store
  **independiente** (fuera del proyecto, en `PARROT_HOME`), con una página por
  clase y por enum, fusionando el API dump oficial (estructura) con
  creator-docs (prosa). Se declara como namespace `roblox` con
  `WikiNamespaceConfig` (`project.py:175`), que ya soporta `store:` (directorio
  pre-construido), `weight:` (peso en el ranking) y apertura **read-only**.

El mismo plano Roblox sirve a todos los proyectos Roblox de la máquina, y se
refresca cuando cambia la versión de Roblox, no cuando cambia tu código.

✅ **Pros:**
- **Separa los dos ciclos de vida** que el problema tiene de verdad: código
  (por commit) y plataforma (por versión de Roblox).
- Se descarga y genera **una vez por máquina**, no una vez por repo.
- `weight` permite bajar el peso de la API para que no ahogue al código propio
  en el ranking — el problema central de la Option A, resuelto por
  configuración en vez de por heurística.
- Aprovecha maquinaria existente y probada (federación, read-only, `NamespaceSkip`
  para plano ausente) en lugar de inventar aislamiento nuevo.
- Un plano ausente **no rompe nada**: se registra como `NamespaceSkip` y el
  resto responde. Degradación limpia si el usuario nunca ejecuta el ingest.

❌ **Cons:**
- **Las aristas código→API cruzan namespaces**, y eso tiene un problema
  verificado: `broken_edges()` (`store.py`) reporta como rota toda arista cuyo
  `dst` no sea página ni source **local**. Una arista a `roblox::class/Players`
  aparecería en `wikitoolkit status` como rota. No rompe funcionalidad, pero
  ensucia el informe de salud — hay que decidir mitigación (ver Open Questions).
- Requiere que el usuario declare el namespace (un paso de configuración más
  que la Option A), aunque el comando de ingest puede hacerlo por él.
- Más superficie: dos artefactos de datos en vez de uno.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `tree-sitter` + `tree-sitter-luau` | Outline del código Luau | ver Option A |
| `aiohttp` | Descarga del dump + 625 YAML de creator-docs | ~5,6 MB medidos; concurrencia acotada |
| `PyYAML` | Parseo de creator-docs | 625 ficheros, uno por clase |

🔗 **Existing Code to Reuse:**
- `federation.py` — `FederatedWikiStore`, `resolve_namespaces()`, `NamespaceSkip`;
  toda la composición multi-plano ya está hecha.
- `project.py:175` — `WikiNamespaceConfig` con `store`, `weight`, `description`.
- `languages/php.py:123` — patrón de fichero auxiliar para `sourcemap.json`.
- `languages/perl.py:211` — molde del scanner tree-sitter.
- `store.py:299` — `WikiPageRecord`, el registro que hay que emitir por clase.

---

### Option C: Plano dirigido por el DataModel, no por el sistema de ficheros

La opción no obvia. En vez de calcar el árbol de ficheros, las páginas del
plano de código **espejan el árbol de instancias de Roblox** que describe
`sourcemap.json`: `ReplicatedStorage/Shared/Util`, `ServerScriptService/Main`,
etc., con la ruta de fichero como metadato en vez de como identidad.

La justificación: un desarrollador Roblox —y por tanto el agente que le
asiste— **piensa en rutas del DataModel, no en rutas de disco**. Pregunta "qué
hay en ReplicatedStorage.Shared", no "qué hay en src/shared". Y `sourcemap.json`
da esa correspondencia gratis (`name`, `className`, `filePaths[]`, `children[]`).

✅ **Pros:**
- El KB habla el idioma del dominio; las consultas del agente aterrizan sin
  traducción mental.
- Los `require` se vuelven casi triviales de resolver: ya estás en el espacio
  de nombres en el que están escritos.
- Captura información que el árbol de ficheros pierde: `className`
  (`ModuleScript` vs `LocalScript` vs `Script`) determina **dónde se ejecuta**
  el código — cliente, servidor o ambos —, que es la distinción más importante
  de la arquitectura Roblox y es invisible en la ruta de disco.

❌ **Cons:**
- Rompe la convención `file:<rel_path>` que usa **todo** el resto del wiki
  (`repo_scan.py:323`): nueva gramática de ids, y las herramientas que asumen
  `file:` (export, sync, coding agents) necesitarían saber de este caso.
- **Depende por completo de `sourcemap.json`.** Sin él no hay plano, mientras
  que el enfoque por ficheros siempre produce *algo*.
- Un fichero puede contribuir a varias instancias y una instancia a varios
  ficheros (`filePaths` es una lista): la correspondencia no es 1:1 y hay que
  decidir la identidad canónica.

📊 **Effort:** High

📦 **Libraries / Tools:** las mismas que B, más una capa de modelo del DataModel.

🔗 **Existing Code to Reuse:**
- `symbols.py:56` — `SymbolRecord` ya tiene `rel_path` + `qualname`, así que
  parte del dualismo ruta/nombre ya está modelado.

---

### Option D: creator-docs por el pipeline de ingesta LLM existente

Reutilizar `wikitoolkit ingest` tal cual (`ingest.py`): apuntar el
`DocumentAcquirer` a los YAML de creator-docs y dejar que `PageIndexToolkit`
/ `TwoStepIngester` resuma cada clase con un LLM en páginas del wiki.

✅ **Pros:**
- Cero código nuevo para el plano de API: el pipeline ya existe y ya sabe
  deduplicar (`replace_source_slice`), registrar fuentes y sincronizar grafo.
- Las páginas quedan en prosa homogénea con el resto del wiki.

❌ **Cons:**
- **Coste y no-determinismo**: 625 clases por un LLM, y el resultado cambia
  entre ejecuciones. Para datos que ya vienen perfectamente estructurados
  (`Parameters`, `ReturnType`, `Security`, `Superclass`) resumir con un LLM
  **destruye estructura para producir prosa**.
- Se pierden las firmas exactas, que es justo lo que el agente necesita citar.
- No hay forma fiable de derivar las aristas de herencia y de referencia
  (`Class.X` en el texto) de una salida generada.

📊 **Effort:** Low (pero con coste recurrente por LLM y calidad peor)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | Ninguna nueva | usa `ingest.py` tal cual |

🔗 **Existing Code to Reuse:**
- `ingest.py` — orquestador completo de ingesta.
- `documents.py:154` `resolve_sources()` — acepta fichero, directorio o URL http(s).

---

## Recommendation

**Option B**, con la Option C degradada a *enriquecimiento* en vez de a
arquitectura.

El argumento decisivo contra A es de ranking, no de elegancia: meter ~1.000
páginas de plataforma en el mismo store BM25 que las ~decenas o centenares de
páginas del proyecto del usuario hace que el plano de API **ahogue** al plano
que de verdad se está consultando. La federación resuelve eso con un `weight`
configurable, y de paso convierte el trabajo de descarga en un coste único por
máquina en vez de por repositorio. Que la maquinaria ya exista y esté probada
(read-only, `NamespaceSkip`, ids cualificados) es lo que hace que este
aislamiento salga casi gratis.

Contra D el argumento es de fidelidad: el API dump ya es estructura pura, y
pasarlo por un LLM la degrada a prosa. Se usa creator-docs **como
complemento** —de ahí sale el *por qué* de cada miembro, y sus referencias
`Class.X` se convierten directamente en aristas— pero la estructura se toma
del dump, deterministamente.

De C se adopta lo barato y valioso —registrar `className` y la ruta DataModel
como **metadatos** de la página `file:`, y usar el árbol de `sourcemap.json`
para resolver requires— sin pagar el precio de romper la convención `file:`
que usa el resto del sistema. Se conserva la identidad por fichero y se gana
el vocabulario del dominio.

Lo que se sacrifica conscientemente: **no hay tipos resueltos**. El KB sabrá
que `add(a: number, b: number): number` está anotada así, pero no inferirá el
tipo de una expresión. Eso exigiría `luau-lsp` dentro del build, lo que rompe
el contrato determinista/offline de `LanguageScanner` y no tiene dónde
almacenarse hoy (`SymbolRecord.signature` guarda la firma *tal como está
escrita*). Es una feature posterior, no un recorte accidental.

---

## Feature Description

### User-Facing Behavior

Para el plano de código, nada nuevo que aprender:

```bash
wikitoolkit build              # ahora indexa .luau y .lua
wikitoolkit query "cómo se inicializa el inventario del jugador"
wikitoolkit related file:src/shared/Inventory.luau
```

Para el plano de API, un comando nuevo:

```bash
wikitoolkit ingest roblox-api            # construye el plano si falta
wikitoolkit ingest roblox-api --refresh  # re-descarga desde la CDN y regenera
```

El comando descarga el API dump de la CDN de Roblox y los YAML de creator-docs,
genera el store del namespace `roblox` y lo declara. A partir de ahí,
`wikitoolkit query` responde con ambos planos, y una consulta sobre
`GetPlayerFromCharacter` devuelve la página de la clase con su firma exacta,
su descripción oficial y las aristas a las clases relacionadas.

El estado se ve en `wikitoolkit status`, incluida la versión de Roblox con la
que se generó el plano.

### Internal Behavior

**Plano de código — `LuauScanner`:**

1. Se registra en `_SCANNERS` (`languages/__init__.py:32`) reclamando
   `.luau` y `.lua`; ambos se añaden a `CODE_SUFFIXES` (`repo_scan.py:68`).
2. `treesitter.py` gana una entrada `"luau": "tree_sitter_luau"` en
   `_GRAMMAR_MODULES` (`treesitter.py:30`). No necesita entrada en
   `_GRAMMAR_CALLABLES`: el wheel expone `language()` a secas, que es el
   candidato por defecto.
3. `outline()` recorre el árbol y emite: comentario de cabecera como `summary`;
   `function_declaration`, `type_definition` (con `export`), y las asignaciones
   a la tabla del módulo como outline; y los argumentos de cada `require(...)`
   como `imports` en crudo.
4. `build_reference_index()` construye el índice de resolución en cascada:
   `sourcemap.json` si existe → `default.project.json` parseado directamente si
   no → solo requires por string relativos (`./mod`) como último recurso. El
   fichero auxiliar se localiza vía `get_scan_root()` (`languages/__init__.py:101`),
   igual que PHP hace con `composer.json`.
5. `resolve_import()` traduce `script.Parent.Foo`,
   `game.ReplicatedStorage.Shared.Util` y `"./sibling"` a rutas relativas del
   repo, o `None` si no resuelve (la arista se descarta, nunca queda colgando).
6. `mode` devuelve `"tree-sitter"` cuando la gramática cargó, `"heuristic"`
   si no.

**Plano de API — `wikitoolkit ingest roblox-api`:**

1. Resuelve la versión: `GET https://setup.rbxcdn.com/versionQTStudio`.
2. Descarga `https://setup.rbxcdn.com/<version>-API-Dump.json` (~4 MB) y los
   625 YAML de clase de creator-docs (~5,6 MB) con `aiohttp`.
3. Fusiona por nombre de clase: el dump aporta miembros, tipos de parámetro y
   retorno, `Security`, `ThreadSafety` y `Superclass`; creator-docs aporta
   `summary`/`description` de la clase y de cada miembro. Las 57 clases del
   dump sin YAML correspondiente generan página igualmente, solo que sin prosa.
4. Emite un `WikiPageRecord` (`store.py:299`) por clase y por enum vía
   `upsert_pages()`, y aristas vía `add_edges()`: `extends` hacia el superclass,
   y `references` derivadas de los enlaces `Class.X` del texto de creator-docs.
5. Guarda la versión de Roblox como procedencia del plano, que es lo que
   `--refresh` compara para decidir si hay que regenerar.

**Enlace entre planos:** el `LuauScanner` reconoce
`game:GetService("Players")` y las anotaciones de tipo que nombran clases
conocidas, y emite aristas `references` hacia los ids del namespace `roblox`.

### Edge Cases & Error Handling

- **Fichero patológico** — el caso que descubrí midiendo, y el más peligroso:
  la recuperación de errores de tree-sitter es superlineal (20 KB → 0,017 s;
  40 KB → 0,181 s; un fichero de 842 KB que no encaja con la gramática superó
  los **120 s** sin terminar). Un `.lua` de otro ecosistema, o un fichero
  generado, puede colgar `wikitoolkit build`. Mitigación obligatoria: cota
  dura de tamaño por fichero antes de parsear, y bailout por densidad de
  nodos `ERROR` que degrade a extracción heurística.
- **Sin `sourcemap.json` ni `default.project.json`**: outline completo, cero
  aristas `require` salvo las relativas por string. Se reporta, no se falla.
- **`sourcemap.json` obsoleto** respecto al árbol de ficheros: un `filePath`
  que ya no existe resuelve a `None` y la arista se descarta.
- **Grammar ausente** (sin el extra `wiki-languages`): `get_parser()` devuelve
  `None` y el scanner cae a heurística, igual que PHP/JS/Rust/Perl.
- **Huecos conocidos de la gramática**: *generic type packs*
  (`type Fn<T...> = (T...) -> ()`) y atributos (`@native`, `@checked`) generan
  nodos `ERROR`. Como tree-sitter es tolerante, las declaraciones siguientes sí
  se parsean; se pierde localmente ese símbolo, no el fichero.
- **CDN de Roblox inaccesible** en `ingest roblox-api`: el plano existente se
  conserva intacto; sin plano previo, el comando falla con mensaje claro y
  `wikitoolkit query` sigue funcionando solo con el plano local.
- **Namespace `roblox` declarado pero no construido**: `NamespaceSkip`, el
  plano local responde igual.
- **`.lua` que no es Luau** (Neovim, OpenResty): parsea como Lua 5.1 —Luau es
  superset— así que produce outline razonable; los constructos ajenos caen en
  el guard de errores.

---

## Capabilities

### New Capabilities
- `luau-language-scanner`: scanner de Luau para el plano de lenguajes de
  wikitoolkit, con resolución de `require` estilo Roblox.
- `roblox-api-plane`: generación determinista de un plano wiki federado con la
  API de la plataforma Roblox, desde el API dump oficial + creator-docs.

### Modified Capabilities
- `wikitoolkit-language-plugins`: se añade una entrada al registro de scanners
  y dos sufijos a `CODE_SUFFIXES`.
- `wikitoolkit-ingest-documents`: gana un subcomando hermano de generación
  determinista (no pasa por el pipeline LLM).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `knowledge/wiki/languages/__init__.py` | modifies | una entrada en `_SCANNERS` (línea 32) |
| `knowledge/wiki/languages/luau.py` | creates | el scanner nuevo |
| `knowledge/wiki/languages/treesitter.py` | modifies | una entrada en `_GRAMMAR_MODULES` (línea 30) |
| `knowledge/wiki/repo_scan.py` | modifies | `.luau` y `.lua` a `CODE_SUFFIXES` (línea 68) |
| `knowledge/wiki/roblox/` | creates | adquisición + fusión dump/creator-docs + generación de páginas |
| `knowledge/wiki/cli.py` | modifies | subcomando `ingest roblox-api` (CLI basada en `click`) |
| `packages/ai-parrot/pyproject.toml` | modifies | `tree-sitter-luau>=1.2` en el extra `wiki-languages` |
| `knowledge/wiki/store.py` | depends on | `upsert_pages()`, `add_edges()` — sin cambios |
| `knowledge/wiki/federation.py` | depends on | namespace `roblox`; posible ajuste en `broken_edges()` |

Sin cambios incompatibles: todo lo nuevo es aditivo. Un repo sin ficheros Luau
se comporta exactamente igual que hoy.

---

## Code Context

### User-Provided Code

Ninguno. El usuario aportó una referencia externa —la gramática
`tree-sitter-grammars/tree-sitter-luau`— y el language server
`JohnnyMorganz/luau-lsp` como posible fuente de tipado.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:23
class LanguageOutline(BaseModel):
    summary: str = ""
    outline: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    symbols: list[SymbolRecord] = Field(default_factory=list)
    refs: list[SymbolRef] = Field(default_factory=list)

# From packages/ai-parrot/src/parrot/knowledge/wiki/languages/base.py:48
class LanguageScanner(ABC):
    name: ClassVar[str]                      # line 61
    suffixes: ClassVar[frozenset[str]]       # line 63
    def outline(self, source: str, rel_path: str) -> LanguageOutline: ...        # line 66
    def build_reference_index(self, rel_paths: Iterable[str]) -> Any: ...        # line 83
    def resolve_import(self, spec: str, from_file: str, index: Any) -> str | None: ...  # line 100
    @property
    def mode(self) -> str: ...               # line 118  -> "ast" | "tree-sitter" | "heuristic"

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py:299
class WikiPageRecord(BaseModel):
    concept_id: str = Field(..., min_length=1)   # line 334
    node_id: Optional[str] = None
    title: str = ""
    category: str = "concept"
    summary: str = ""
    body: str = ""
    source_id: Optional[str] = None
    token_count: int = Field(default=0, ge=0)
    origin: str = "ingest"
    asserted_by: Optional[str] = None
    updated_at: Optional[str] = None
    content_hash: Optional[str] = None

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1134 / :1154
async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...
async def add_edges(self, edges: list[tuple]) -> int:
    """(src, dst, rel) or (src, dst, rel, provenance); rel is an open string."""

# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py:175
class WikiNamespaceConfig(BaseModel):
    path: str | None          # another wiki project root
    store: str | None         # pre-built store directory
    backend: str
    description: str = ""
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
```

#### Verified Imports

```python
# Confirmados en el árbol actual:
from parrot.knowledge.wiki.languages.base import LanguageOutline, LanguageScanner
from parrot.knowledge.wiki.languages import get_scan_root, set_scan_root   # __init__.py:91,101
from parrot.knowledge.wiki.languages import treesitter                     # treesitter.py:64 get_parser()
from parrot.knowledge.wiki.store import WikiPageRecord                     # store.py:299 (NO en models.py)
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolRef          # symbols.py:56,105
from parrot.knowledge.wiki.project import WikiNamespaceConfig              # project.py:175
```

#### Key Attributes & Constants

- `_GRAMMAR_MODULES` → `dict[str, str]` (`languages/treesitter.py:30`) — mapea
  lenguaje → módulo del wheel. Falta `"luau"`.
- `_GRAMMAR_CALLABLES` → `dict[str, tuple[str, ...]]` (`treesitter.py:52`) —
  **no** hace falta entrada para luau; `_DEFAULT_GRAMMAR_CALLABLES = ("language",)`
  (`treesitter.py:61`) ya acierta.
- `_SCANNERS` → `dict[str, LanguageScanner]` (`languages/__init__.py:32`) —
  registro explícito, sin descubrimiento por entry-points.
- `CODE_SUFFIXES` (`repo_scan.py:68`) — **no contiene** `.lua` ni `.luau`.
- Convención de id de página: `f"file:{PurePosixPath(rel_path)}"` (`repo_scan.py:323`).
- `PerlScanner` (`languages/perl.py:211`) y `PhpScanner` (`languages/php.py:123`)
  — los dos moldes a seguir.
- `SymbolKind` (`symbols.py:31`) ya incluye `TYPE`, `FUNCTION`, `METHOD`,
  `MODULE`, `CONST` — suficiente para Luau sin ampliar el enum.

#### Hechos externos verificados en esta sesión

```
tree-sitter 0.26.0 + tree_sitter_luau 1.2.0 -> Language(L.language()), ABI 14, parseo OK
  cubre: generics, string interpolation (`{x}`), compound assign, continue,
         if-expr, exported types, OOP con metatablas, typeof, requires
  falla:  generic type packs (`type Fn<T...> = (T...) -> ()`), atributos (`@native`)

Roblox API dump — https://setup.rbxcdn.com/<version>-API-Dump.json
  4.070.157 bytes | 682 clases | 351 enums
  miembro de ejemplo (Players.GetPlayerFromCharacter):
    MemberType=Function, Parameters=[{Name:character, Type:{Category:Class, Name:Model}}],
    ReturnType={Category:Class, Name:Player}, Security=None, ThreadSafety=Unsafe

creator-docs — github.com/Roblox/creator-docs
  content/en-us/reference/engine/classes/*.yaml -> 625 ficheros, 5.551.749 bytes (5,6 MB)
  por clase: name, type, summary, description, inherits[], tags[], properties[]/methods[]/events[]
  referencias cruzadas en el texto con la sintaxis `Class.Players:BanAsync()|BanAsync()`

Escalado de recuperación de errores (fichero que NO encaja con la gramática):
   5.000 bytes -> 0,000 s (sin error)
  10.000 bytes -> 0,000 s (sin error)
  20.000 bytes -> 0,017 s (con error)
  40.000 bytes -> 0,181 s (con error)
 842.890 bytes -> >120 s SIN TERMINAR  ← requiere guard de tamaño/densidad
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.wiki.languages.luau`~~ / ~~`.lua`~~ — no existe ningún
  scanner de Lua o Luau todavía.
- ~~`WikiPageRecord` en `models.py`~~ — está en **`store.py:299`**, no en
  `models.py`. `models.py` define `WikiPageCategory` (línea 25) y `WikiConfig`.
- ~~`.lua` / `.luau` en `CODE_SUFFIXES`~~ — no están (`repo_scan.py:68`); hoy
  esos ficheros no se escanean en absoluto.
- ~~`tree_sitter_luau.language_luau()`~~ — el wheel expone **solo** `language()`
  (más `HIGHLIGHTS_QUERY`, `INJECTIONS_QUERY`, `LOCALS_QUERY`).
- ~~Registro de Luau en ast-grep vía el wheel~~ — **verificado imposible**: el
  `_binding.abi3.so` de `tree-sitter-luau` no exporta el símbolo. Probado con
  `ast-grep-py 0.45.3`:
  `RuntimeError: dlsym failed: undefined symbol: tree_sitter_luau`.
  (El wheel de Perl **sí** lo exporta — `nm -D` muestra `T tree_sitter_perl` —
  y por eso `_register_perl_dynamic_language()` (`languages/astgrep.py:104`)
  funciona. No es replicable para Luau sin compilar la gramática aparte.)
- ~~`globalTypes.d.luau` de luau-lsp como fuente parseable por la gramática~~ —
  **verificado imposible**: es el dialecto de ficheros de definición del LSP
  (`declare extern type X with ... end`, `declare debug: {...}`), no Luau. Una
  rebanada de 78 líneas produce 7 nodos `ERROR`. Descartada la idea de tratar
  la API como "otro fichero Luau más".
- ~~Paquete `luau-lsp` en PyPI~~ — no existe (404). Integrarlo exigiría un
  binario externo.
- ~~`wikitoolkit ingest roblox-api`~~ — no existe; `ingest.py` es hoy un
  pipeline de documentos basado en LLM (PageIndex/TwoStepIngester).
- ~~Aristas cross-namespace tratadas como válidas~~ — `broken_edges()`
  (`store.py`) reporta como rota **toda** arista cuyo `dst` no esté en las
  tablas `pages`/`sources` **locales**. Una arista a `roblox::class/Players`
  saldría listada como rota.

---

## Parallelism Assessment

- **Internal parallelism**: alta. Los dos planos son independientes hasta la
  tarea final de enlace. El `LuauScanner` (scanner + resolución de requires) no
  comparte ningún fichero con el generador del plano Roblox (adquisición +
  fusión + emisión de páginas). Solo `cli.py` y `pyproject.toml` son puntos de
  contacto, y en zonas distintas del fichero.
- **Cross-feature independence**: el riesgo está en `wikitoolkit-perl-scanner`
  y `ast-grep-for-wikitoolkit`, que tocan `languages/__init__.py`,
  `languages/treesitter.py` y `repo_scan.py`. Son ediciones de una o dos líneas
  en tablas de registro — conflictos triviales de resolver, pero conviene no
  ejecutarlas simultáneamente sobre las mismas líneas.
- **Recommended isolation**: `mixed`.
- **Rationale**: el plano de código y el plano de API pueden desarrollarse en
  worktrees separados sin tocarse, y solo la tarea de enlace código→API depende
  de ambos. Forzar secuencialidad total desperdiciaría esa independencia; pero
  las tareas dentro de cada plano sí son secuenciales (el scanner necesita
  existir antes de resolver requires, y las páginas antes de las aristas).

---

## Open Questions

- [x] ¿Tipo de flujo y rama base? — *Owner: Jesus Lara*: `feature` sobre `dev`.
- [x] ¿Alcance de v1? — *Owner: Jesus Lara*: código **y** API de Roblox, los dos planos.
- [x] ¿Qué sufijos reclama el scanner? — *Owner: Jesus Lara*: `.luau` y `.lua`.
- [x] ¿Cómo se resuelven los `require`? — *Owner: Jesus Lara*: `sourcemap.json`
      con fallback a `default.project.json` y a requires relativos por string;
      nunca invocando binarios.
- [x] ¿Plano estructural `sym:` en v1? — *Owner: Jesus Lara*: no; degradar a
      `mode="tree-sitter"` (además está verificado que ast-grep no puede
      registrar Luau desde el wheel).
- [x] ¿Fuente del conocimiento de la API? — *Owner: Jesus Lara*: API dump
      oficial **+** creator-docs.
- [x] ¿Dump vendorizado o descargado? — *Owner: Jesus Lara*: descargado desde la
      CDN con `--refresh`; nada de dumps alojados localmente en el repo.
- [x] ¿Granularidad de las páginas de API? — *Owner: Jesus Lara*: una página por
      clase y por enum.
- [x] ¿Se enlazan los dos planos? — *Owner: Jesus Lara*: sí, con aristas
      `references` desde el código hacia las páginas de la API.
- [ ] **Aristas cross-namespace y `broken_edges()`**: ¿se extiende
      `broken_edges()` para ignorar destinos cualificados con `ns::`, o el
      plano local escribe páginas-stub para las clases que referencia?
      La primera es más limpia pero toca código compartido de federación.
      — *Owner: Jesus Lara*
- [ ] **Umbral del guard de robustez**: ¿cota de tamaño por fichero (¿256 KB?),
      densidad de nodos `ERROR`, timeout de parseo, o combinación? Hay que fijar
      un número defendible a partir de la curva medida. — *Owner: Jesus Lara*
- [ ] **Adquisición de creator-docs**: 625 peticiones a `raw.githubusercontent`
      (verificado que funciona) frente a un tarball del repo o un clon
      sparse-checkout. ¿Cuál, y con qué concurrencia y política de caché?
      — *Owner: Jesus Lara*
- [ ] **Invalidación del plano Roblox**: la versión de Studio (`versionQTStudio`)
      cambia con frecuencia. ¿`--refresh` compara versión, o hay además una
      caducidad temporal? ¿Se avisa en `wikitoolkit status` cuando el plano
      está desfasado? — *Owner: Jesus Lara*
- [ ] **Ámbito del enlace código→API**: ¿solo `game:GetService("X")` y
      anotaciones de tipo explícitas, o también accesos encadenados
      (`workspace.Terrain`)? Cuanto más agresiva la heurística, más aristas
      falsas. — *Owner: Jesus Lara*

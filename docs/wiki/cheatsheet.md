# wikitoolkit — Cheatsheet

Referencia rápida de los comandos más útiles del **LLM Wiki** de AI-Parrot
(`wikitoolkit` ≡ `parrot wiki`), de los toolkits MCP (`parrot toolkits`), de la
integración con Claude Code / Codex / Gemini y de la biblioteca **Bookstore**.

> Guías completas: `docs/guides/llm-wiki-guide.md`,
> `docs/runbooks/jira-issues-namespace.md`, `docs/bookstore-graph.md`,
> `docs/bookstore-codex.md`, `docs/guides/wiki-adr-decisions.md`.
>
> Nota: `wikitoolkit export` escribe **por defecto** en `docs/wiki/`. Si exportas
> el bundle markdown aquí, usa `-o` con otra carpeta para no mezclarlo con
> este archivo.

Siempre dentro del venv del repo:

```bash
source .venv/bin/activate
```

---

## 0. Instalación

| Qué | Comando |
|---|---|
| Wiki + loaders (PDF/DOCX/EPUB/MOBI) | `uv pip install 'ai-parrot[wiki]'` |
| Extractor de Jira | `uv pip install -e 'packages/ai-parrot[jira]'` |
| Bookstore + servidor MCP | `uv pip install 'ai-parrot[bookstore,mcp]'` |
| Comunidades Leiden (opcional) | `uv pip install leidenalg python-igraph` |
| Verificar | `wikitoolkit --help` · `parrot --help` |

---

## 1. Ciclo básico: construir y consultar

```bash
wikitoolkit build                    # grafo completo del repo (offline, sin LLM)
wikitoolkit build --force            # re-ingesta todo, ignora staleness
wikitoolkit build -q --no-graph      # sin graph.html/graph.json
wikitoolkit build --no-export        # sin bundle OKF markdown
wikitoolkit build --backend arangodb # plano compartido en ArangoDB

wikitoolkit status                   # estadísticas, namespaces, staleness
wikitoolkit status --json

wikitoolkit upsert path/a/archivo.py path/b/otro.py   # re-ingesta puntual
wikitoolkit upsert --changed --quiet                    # lo que tocó el último commit (git hook)
```

### Consultas (progressive disclosure)

```bash
wikitoolkit query "cómo funciona el pipeline de ingest"        # stubs rankeados, presupuesto en tokens
wikitoolkit query "compaction budget" -n 20 --budget 2000        # más resultados / más tokens
wikitoolkit query "memory render" --category module --table      # tabla Rich para humanos
wikitoolkit query "graphindex" -b                                # + cuerpo de la página top
wikitoolkit query "..." --json

wikitoolkit page file:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
wikitoolkit page dir:packages/ai-parrot/src/parrot/memory --max-tokens 800
wikitoolkit related file:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
wikitoolkit related dir:packages/ai-parrot/src/parrot/memory --rel contains --direction out
```

Ids de página: `file:<rel>`, `dir:<rel>`, `sym:<rel>#<qualname>`, `tag:<tag>`,
`book:<id>`, `issue:<hash>`, `spec:<FEAT>`, `task:<TASK>`. Los de un namespace
ajeno vienen calificados: `issues::file:NAV-9372.md`.

**Disciplina de query**: busca la *cosa* (nombre del símbolo/módulo), no tu
hipótesis sobre ella; si el primer resultado apunta a un padre, sigue con
`page`/`related` antes de caer a `grep`.

### Plano estructural de símbolos (FEAT-498)

```bash
wikitoolkit symbols lookup AbstractBot                 # por nombre o qualname
wikitoolkit symbols lookup render_history --kind function --path-prefix packages/ai-parrot
wikitoolkit symbols outline packages/ai-parrot/src/parrot/bots/abstract.py --depth 2
wikitoolkit symbols outline "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.ask" --source
wikitoolkit symbols blast AbstractBot.get_client       # quién depende (calls/extends/implements)
wikitoolkit symbols blast save_conversation_turn --depth 3 --no-tests --json
```

Ejecuta `symbols blast` **antes** de tocar una función/clase muy usada.

### Comunidades y grounding

```bash
wikitoolkit communities                 # Leiden/Louvain sobre el store actual
wikitoolkit communities --inter         # meta-grafo entre comunidades
wikitoolkit communities --graph-kinds module,document --json
wikitoolkit ground "AbstractBot es el único escritor del historial"   # requiere .parrot/graph/ (sync_graph)
```

---

## 2. Integración con asistentes de código

### Claude Code (`parrot claude`)

```bash
parrot claude install            # 7 pasos idempotentes (ver tabla)
parrot claude install --no-git-hook --no-build --no-compaction
parrot claude install --tool-guards                # guard PreToolUse de lecturas grandes (FEAT-543)
parrot claude install --typesafe-api-key $KEY      # para el plugin fast-jev-compaction
parrot claude status [--json]
parrot claude uninstall          # quita la integración, conserva el plano
```

| Paso | Artefacto |
|---|---|
| 1 | `.parrot/wiki.json` (config del proyecto) |
| 2 | Sección gestionada en `CLAUDE.md` (preferir `wikitoolkit query` a grep) |
| 3 | Hook PreToolUse en `.claude/settings.json` (`wikitoolkit claude hook`) |
| 4 | Permisos `Bash(wikitoolkit:*)` / `Bash(parrot wiki:*)` en `settings.local.json` |
| 5 | Entrada `wikitoolkit` en `.mcp.json` (servidor MCP stdio) |
| 6 | Slash command `/parrotwiki` (`.claude/commands/parrotwiki.md`) |
| 7 | Git `post-commit` → `wikitoolkit upsert --changed --quiet` |

Flags: `--bookstore/--no-bookstore` (instala el MCP de Bookstore si hay
biblioteca indexada), `--approve-mcp`, `--plugin-cli`, `--gitignore`.

Slash command dentro de Claude Code:

```
/parrotwiki query <pregunta>      /parrotwiki remember <hecho>
/parrotwiki page <id>             /parrotwiki note <id> <texto>
/parrotwiki related <id>          /parrotwiki link <src> <dst>
/parrotwiki status                /parrotwiki memories
/parrotwiki build                 /parrotwiki audit
/parrotwiki --wiki [dir]          # exporta bundle markdown legible
```

Herramientas MCP nativas (servidor `wikitoolkit mcp`): `wiki_query`, `wiki_page`,
`wiki_related`, `wiki_remember`, `wiki_note`, `wiki_status`, `wiki_symbol_lookup`,
`wiki_code_outline`, `wiki_blast_radius`, `wiki_decision_why`,
`wiki_decisions_for_symbol`, `ledger_open/claim/close/ready/context`.

### Codex y Gemini / Antigravity

```bash
parrot codex install [--no-build] [--tool-guards]     # MCP + skills de wiki y bookstore para Codex
parrot codex status --json · parrot codex uninstall
parrot gemini install · parrot gemini status · parrot gemini uninstall
```

### Hook de git a mano

```sh
#!/bin/sh
# .git/hooks/post-commit
wikitoolkit upsert --changed --quiet
```

---

## 3. Toolkits MCP locales (`parrot toolkits`)

```bash
parrot toolkits list                         # estado, hosts, drift, dependencias
parrot toolkits status [--host claude]       # rutas de config y salud por host
parrot toolkits install browsing scraping --yes          # siembra .parrot/mcp-toolkits.yaml + registra
parrot toolkits install lsp --host claude --host codex
parrot toolkits enable memory --yes
parrot toolkits disable sdd-coder --yes      # desregistra pero conserva la config
parrot toolkits uninstall lsp --yes
```

Toolkits disponibles hoy: `bounded-source`, `browsing`, `database-query`, `lsp`,
`memory`, `querysource`, `scraping`, `sdd-coder`, `targeted-writer`.
Hosts: `claude | codex | google` (por defecto, todos los detectados).

---

## 4. Memoria persistente (el agente olvida, el grafo no)

```bash
wikitoolkit remember "El watermark del sweep vive en .parrot/jira_sync.json" \
  --category decision --title "Jira watermark" \
  --link file:packages/ai-parrot/src/parrot/knowledge/wiki/jira_sync.py --rel about
wikitoolkit remember "..." --category lesson --source "https://..." --by human:jlara
wikitoolkit remember "..." --category concept --extract   # + extracción LLM a .parrot/graph (WIKI_EXTRACT_LLM)

wikitoolkit note file:packages/.../cli.py "ingest-jira nunca registra namespaces"
wikitoolkit link file:a.py file:b.py --rel references        # arista afirmada, mismo plano
wikitoolkit memories [--category decision] [--limit 20]
wikitoolkit audit [--limit 50]                              # log de escrituras atribuidas
```

Categorías de memoria: `note | decision | lesson | concept` (las de página del repo:
`module`, `symbol`, `document`, `overview`, `config`, ...). El id es hash de
título+categoría, así que re-recordar lo mismo **actualiza** en vez de duplicar.

### Sincronizar conocimiento autorado con un plano compartido (FEAT-461)

```bash
wikitoolkit sync push --env dev [--dry-run]    # memorias/notas/aristas locales → plano dev
wikitoolkit sync pull --env dev [--all]        # excluye lo tuyo (human:<user>) salvo --all
```

---

## 5. Ledger de trabajo SDD (`wikitoolkit ledger`)

Plano compartido en `<main>/.parrot/ledger/` (`events.jsonl` append-only +
`ledger.db` índice reconstruible). Lo alimentan `/sdd-codereview`, `/sdd-done`
y los seats de sdd-coder; lo drena `/sdd-fix`.

```bash
wikitoolkit ledger open --kind bug --severity major \
  --discovered-from review:TASK-3115 \
  --about packages/ai-parrot/src/parrot/memory/render.py \
  --title "render_history ignora el budget" --body "..."

wikitoolkit ledger ready [--kind bug]                  # abiertas y sin reclamar (orden por severidad)
wikitoolkit ledger claim issue:5944887877e1 --actor human:jlara
wikitoolkit ledger unclaim issue:5944887877e1 --reason "no reproducible aquí"
wikitoolkit ledger close issue:5944887877e1 --reason "fixed" --resolved-by commit:<sha>
wikitoolkit ledger close issue:... --reason "..." --resolved-by task:TASK-3120

wikitoolkit ledger context packages/ai-parrot/src/parrot/memory/render.py --max-tokens 800
wikitoolkit ledger blockers FEAT-585                   # críticas sin acknowledge que bloquean el merge
wikitoolkit ledger acknowledge issue:... --reason "..." --actor human:jlara   # sólo humanos
wikitoolkit ledger plan-fix [--severity major] [--lane fast|sdd] --json   # lote para /sdd-fix

wikitoolkit ledger ingest-sdd        # specs + índices de tareas → nodos spec:/task:
wikitoolkit ledger sync              # aplica eventos pendientes al índice
wikitoolkit ledger rebuild           # reconstruye desde el log (re-ejecuta ingest-sdd después)
wikitoolkit ledger audit · wikitoolkit ledger export --dest <dir> · wikitoolkit ledger compact
```

Kinds: `bug | tech_debt | feature_gap | vulnerability`. Severidades:
`critical | major | minor | low`. `--discovered-from`: `spec:<FEAT>`,
`task:<TASK>`, `review:<TASK>`.

---

## 6. Namespaces: federar varios wikis

`ns add` es el **único** escritor de namespaces; ni `build` ni `ingest-jira`
se auto-registran.

| Kind | Flag | Apunta a |
|---|---|---|
| `path` | `--project <dir>` | otro proyecto con `.parrot/wiki.json` |
| `store` | `--store <dir>` | store pre-construido (`wiki.db` dentro) |
| `database` | `--database <db>` | ArangoDB (`--backend arangodb`) o backend satélite (`--backend ontology_legal`) |
| `vault` | `--vault <dir>` | vault de Obsidian (requiere `.obsidian/`) |

```bash
wikitoolkit ns add asyncdb --project ~/proyectos/asyncdb --description "AsyncDB codebase"
wikitoolkit ns add issues  --store ~/.parrot/wikis/issues/.parrot/wiki --global --description "Jira"
wikitoolkit ns add notes   --vault ~/vaults/work-notes --global --weight 0.8
wikitoolkit ns add legal   --database legal_db --backend ontology_legal --credentials-env LEGAL_ARANGO
wikitoolkit ns list [--json]
wikitoolkit ns remove notes --global
```

- Sin `--global` → `.parrot/wiki.json` del repo; con `--global` →
  `${PARROT_HOME:-~/.parrot}/wikis.json`. El repo gana en colisión de nombre.
- Nombres: `^[A-Za-z0-9][A-Za-z0-9_.:-]*$`; `all` y `local` están reservados.

```bash
wikitoolkit query "tenant en la URL"                 # todos los namespaces (default si hay alguno)
wikitoolkit query --ns issues "tenant en la URL"
wikitoolkit query --ns "issues,notes" "..."
wikitoolkit query --ns local "..."                   # sólo el wiki del repo
wikitoolkit page issues::file:NAV-9372.md
wikitoolkit related notes::file:Retro.md
wikitoolkit query --store docs/parrot "..."          # un store cualquiera, sin registrarlo
```

Las escrituras van siempre al plano local; los planos ajenos se abren
read-only y **no hay aristas entre namespaces** (`link` las rechaza).

---

## 7. Plano de tickets Jira (`ingest-jira`, FEAT-454)

Determinista y sin LLM: cada ticket del JQL se vuelve un markdown en
`${PARROT_HOME}/wikis/issues` (fuera del repo, G8) y se construye el plano.

```bash
# credenciales (las de JiraToolkit): JIRA_INSTANCE, JIRA_AUTH_TYPE (sin default), JIRA_USERNAME,
# JIRA_API_TOKEN | JIRA_SECRET_TOKEN | JIRA_OAUTH_*; opcional JIRA_WIKI_JQL, JIRA_WIKI_AC_FIELD

wikitoolkit ingest-jira --project NAV --backfill          # primera carga: --force + concurrencia 16 + check de completitud
wikitoolkit ingest-jira                                   # incremental desde el watermark (cron diario)
wikitoolkit ingest-jira --jql 'project in (NAV, FORMS) AND updated >= -30d'
wikitoolkit ingest-jira --since 2026-09-01T00:00:00 --dry-run --json
wikitoolkit ingest-jira --force                           # re-renderiza todo el scope
wikitoolkit ingest-jira --no-build                        # sólo documentos

# UNA vez, a mano, tras el primer sweep:
wikitoolkit ns add issues \
  --store "${PARROT_HOME:-$HOME/.parrot}/wikis/issues/.parrot/wiki" \
  --global --description "Jira ticket corpus"

wikitoolkit query --ns issues "forms tenant"
wikitoolkit page issues::file:NAV-9372.md
```

```cron
17 6 * * *  cd /ruta/checkout && /ruta/.venv/bin/wikitoolkit ingest-jira --quiet >> /var/log/parrot/jira-ingest.log 2>&1
```

Todo lo escrito bajo `<!-- jira-sync:end -->` en un documento sobrevive a cada
re-sync. Un run `partial` (errores) sale ≠ 0 y **no** avanza el watermark.
Comentarios y adjuntos no se sincronizan en v1.

---

## 8. Obsidian

### Vault → wiki (el vault como fuente)

```bash
wikitoolkit build --path ~/vaults/work-notes          # auto-detecta .obsidian/
wikitoolkit build --vault --path ~/carpeta/markdown   # fuerza modo vault
wikitoolkit ns add notes --vault ~/vaults/work-notes --global   # consultable desde el repo
```

Extrae: notas → `file:` (category `document`), `[[wikilink]]` → `references`,
`![[embed]]` → `embeds`, `#tag` → `tagged` + página `tag:`, carpetas →
`contains`, frontmatter YAML indexado en FTS. Con `vault_dir` en
`.parrot/wiki.json` el MCP expone `vault_ingest`.

### Wiki → vault (`sync obsidian`, espejo one-way)

```bash
wikitoolkit sync obsidian --dry-run -v
wikitoolkit sync obsidian --vault ~/vaults/work-notes --ns local
wikitoolkit sync obsidian --ns all --category decision --category lesson --prune
```

Config en `.parrot/wiki.json` (los flags la sobreescriben por ejecución):

```json
"obsidian_sync": {
  "vault_dir": "~/vaults/work-notes",
  "root_folder": "LLM Wiki",
  "categories": ["decision", "lesson", "note", "document"],
  "folders": { "decision": "Decisions", "lesson": "Lessons" },
  "namespaces": ["local", "issues"],
  "prune": false
}
```

Cada nota lleva frontmatter `wiki_sync` / `wiki_scope` / `wiki_id`; `--prune`
sólo borra notas con ese marcador. Las aristas entre páginas sincronizadas se
vuelven `[[wikilinks]]` en una sección `## Related` (visible en el graph view).

---

## 9. Bookstore: biblioteca indexada (PageIndex)

Biblioteca de proyecto en `.parrot/library`, global en `~/.parrot/library`
(o `PARROT_LIBRARY_DIR`). LLM opcional: `PARROT_BOOKSTORE_LLM="provider:model"`
(+ `PARROT_BOOKSTORE_LLM_LIGHT`). Sin LLM la búsqueda in-book necesita `bm25s`.

### Parsear y catalogar libros

```bash
parrot bookstore locations                                # dónde está cada biblioteca y su estado
parrot bookstore add libro.pdf                            # pdf/md/txt/epub/mobi/docx → índice + ficha
parrot bookstore add libro.epub --global --title "..." --author "..." --topic "..."
parrot bookstore add notas.md --no-llm                    # sin carding/resúmenes LLM
parrot bookstore add libro.pdf --relate --llm anthropic:claude-haiku-4-5
parrot bookstore add-folder ~/libros -r --dry-run
parrot bookstore add-folder ~/libros -r --global --relate
parrot bookstore card <book_id> --refresh --llm anthropic:claude-haiku-4-5   # rehacer la ficha
parrot bookstore remove <book_id> --yes
```

### Consultar

```bash
parrot bookstore list [--json] [--by-community]
parrot bookstore show <book_id> [--json]                  # ficha completa
parrot bookstore toc <book_id>                            # tabla de contenidos con node ids
parrot bookstore search "aislamiento transaccional"       # cross-book
parrot bookstore search "..." --book <book_id>            # dentro de un libro
parrot bookstore search "..." --catalog-only              # sólo fichas
```

### Grafo de libros (FEAT-533)

```bash
parrot bookstore relate --all --no-llm          # Stage 1: same_author / shares_topic / same_era ... (sin LLM)
parrot bookstore relate --all                   # + Stage 2 LLM (influenced_by, responds_to, parallels, contrasts_with), 1 prompt por libro
parrot bookstore relate --communities-only      # sólo Stage 3 (Leiden/Louvain)
parrot bookstore relate <id1> <id2> --force     # re-juzgar pares ya registrados
parrot bookstore related <book_id> --rel same_author --depth 2 --json
parrot bookstore communities [--json]
```

### Libros como plano del wiki

```bash
parrot bookstore export-wiki                    # <library>/wiki + registra namespace `bookstore` en .parrot/wiki.json
parrot bookstore export-wiki --global           # biblioteca global → ~/.parrot/wikis.json
parrot bookstore export-wiki --out ~/wikis/books --no-register

wikitoolkit query --ns bookstore "estoicismo y deber"
wikitoolkit page bookstore::book:<book_id>
wikitoolkit related bookstore::book:<book_id>
parrot bookstore communities                    # comunidades del grafo; graph.html queda en <library>/wiki
```

Una página por libro (`category=book`), una arista por relación; `wiki.db` se
reconstruye entero en cada export. Un namespace `bookstore` previo con otro
store se rechaza: `wikitoolkit ns remove bookstore` primero.

### Servidor MCP y skill

```bash
parrot bookstore mcp                            # stdio: bookstore_catalog_search, get_toc, search_book,
                                                #   read_section, search, related_books, communities, ...
parrot claude install                           # lo registra si existe library.db (--no-bookstore para omitir)
parrot codex install --no-build                 # idem para Codex ($bookstore en el prompt)
```

Embudo de investigación: `catalog_search` → `related_books`/`communities` →
`get_toc` → `search_book`/`search` → `read_section`; cita el `origin` de cada
relación (`deterministic` / `llm` + confianza / `community`).

---

## 10. Ingesta supervisada de documentos (`ingest`, FEAT-402)

Para corpus de PDF/DOCX/PPTX/XLSX/HTML/EPUB/MD/TXT con control editorial: un
charter YAML (`.parrot/charter.yaml`, ejemplo en
`sdd/state/FEAT-402-supervised-wiki-ingestion/references/charter.example.yaml`)
define scope, audiencia y umbrales; un modelo ligero triage y sólo la zona gris
escala al modelo pesado. Exactamente **un** modo por ejecución.

```bash
export WIKI_LIGHTWEIGHT_MODEL=anthropic:claude-haiku-4-5
export WIKI_MODEL=anthropic:claude-sonnet-5

wikitoolkit ingest ~/docs/specs/ --dry-run                     # manifest, no ingesta nada
wikitoolkit ingest ~/docs/specs/ --review .parrot/wiki/ingest-manifest.jsonl   # aplica decisiones editadas
wikitoolkit ingest ~/docs/specs/ --interactive                 # pregunta por documento
wikitoolkit ingest ~/docs/specs/ --auto --audit-rate 0.2       # umbrales del charter deciden
wikitoolkit ingest https://example.com/paper.pdf --interactive --fetch-timeout 60
wikitoolkit ingest ~/docs --no-recursive --charter otro/charter.yaml --manifest /tmp/m.jsonl
wikitoolkit ingest roblox-api [--refresh]                      # plano federado de la API de Roblox (FEAT-532)
```

---

## 11. Decisiones arquitectónicas (`adr`)

```bash
wikitoolkit adr sync [paths...]                    # refresca ADRs (docs/adr, docs/adrs, docs/decisions); sin LLM
wikitoolkit adr lookup AbstractBot.save_conversation_turn --budget 2000
wikitoolkit adr why "por qué los clientes no cargan historial" --include-history
wikitoolkit adr generate sym:packages/.../abstract.py#AbstractBot   # candidatos (requiere generation_enabled + modelo)
wikitoolkit adr review <decision_id> --action accept --expected-revision 1 --actor human:jlara --reason "..."
wikitoolkit adr review <decision_id> --action link --documented-id <adr_id> --expected-revision 2 --actor human:jlara
wikitoolkit adr export <decision_id>
```

---

## 12. Exportar el wiki como markdown

```bash
wikitoolkit export -o docs/knowledge-base        # una .md por página + index.md (añade el dir a exclude_dirs)
/parrotwiki --wiki docs/knowledge-base           # lo mismo desde Claude Code
```

---

## 13. Configuración y entornos

- `.parrot/wiki.json` — config base (`wiki_name`, `storage_dir`, `backend`,
  `exclude_dirs`, `namespaces`, `vault_dir`, `obsidian_sync`, `sync_graph`,
  `claude.nudge_cooldown_seconds`, `decisions.*`, `symbol_depth`).
- `.parrot/wiki.<env>.json` — overlay parcial por entorno, sin credenciales.
  Resolución: `WIKI_ENV > ENV > "local"`. Este repo commitea
  `wiki.local.json = {"backend": "sqlite"}` (offline, sin VPN).
- `${PARROT_HOME:-~/.parrot}/wikis.json` — registro global de namespaces.
- Variables útiles: `WIKI_STORE`, `WIKI_STORE_BACKEND`, `WIKI_ENV`,
  `WIKI_MODEL`, `WIKI_LIGHTWEIGHT_MODEL`, `WIKI_EXTRACT_LLM`,
  `PARROT_HOME`, `PARROT_LIBRARY_DIR`, `PARROT_BOOKSTORE_LLM`,
  `JIRA_WIKI_JQL`, `JIRA_WIKI_ISSUES_DIR`, `ARANGODB_*`.

---

## 14. Troubleshooting rápido

| Síntoma | Causa probable | Fix |
|---|---|---|
| `query --ns issues` / `--ns bookstore` no devuelve nada | namespace no registrado | `wikitoolkit ns add ...` (o `export-wiki` sin `--no-register`) y `ns list` |
| Resultados viejos / archivo nuevo no aparece | plano stale | `wikitoolkit upsert <paths>` o `wikitoolkit build` |
| Git hook no corre | `core.hooksPath` apunta a una ruta inexistente | revisar `.git/config` |
| `ingest-jira` marca `partial` con 0 fetched | auth silenciosa de Jira Cloud / `JIRA_AUTH_TYPE` sin definir | rotar credenciales, definir `JIRA_AUTH_TYPE` |
| `ledger rebuild` perdió specs/tasks | esos nodos no son event-sourced | `wikitoolkit ledger ingest-sdd` |
| `link` rechaza la arista | páginas en planos distintos | no hay aristas cross-namespace; usa `query` |
| `bookstore mcp` no arranca | no hay `library.db` | `parrot bookstore locations`, indexar un libro |
| `wikitoolkit mcp` cae en Claude Code | wiki no construido en ese repo | `wikitoolkit build` |

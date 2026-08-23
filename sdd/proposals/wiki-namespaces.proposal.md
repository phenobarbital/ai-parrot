---
id: FEAT-450
title: Namespaces for wikitoolkit — federate N wiki stores (repos, Obsidian vaults, brains) behind ns::id with explicit + broadcast routing
slug: wiki-namespaces
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-08-23
  summary_oneline: Namespaces for wikitoolkit — federate N wiki stores (sibling repos, non-code brains, ArangoDB dbs) behind ns::id with explicit + broadcast routing
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-450/
created: 2026-08-23
updated: 2026-08-23
deltas:
  - id: 1
    date: 2026-08-23
    summary: "`obsidian` namespace kind — a vault registers as `{vault: <path>}`, plane inside the vault, `_prune_removed` scoping fixed in-feature"
    evidence: F017
---

# FEAT-450 — Namespaces for wikitoolkit (multi-wiki federation)

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — design discussion + three user decisions (2026-08-23)
> **Audit**: [`sdd/state/FEAT-450/`](../state/FEAT-450/)

---

## 0. Origin

The original request, preserved verbatim (full text at `sdd/state/FEAT-450/source.md`).

> Today each LLM Wiki is a single plane per repo (`.parrot/wiki.json` → `storage_dir/wiki.db`);
> `query`/`page`/`related` and the MCP tools read exactly one store. ai-parrot depends on sibling
> personal repos (navigator, asyncdb, navconfig, querysource) whose knowledge is invisible to the
> wiki. Beyond code, the same mechanism should let a user compose multiple "brains" (e.g. a lawyer
> with graphs for legislation, jurisprudence, own cases — built via `wikitoolkit ingest`) and query
> all of them or a specific one.
>
> **Goal**: wikitoolkit can register named namespaces, each pointing at a distinct wiki store
> (another repo's `.parrot/wiki` plane, an arbitrary store dir, or an ArangoDB database), and
> route query/page/related/status either explicitly to one namespace or broadcast to all with
> merged ranking. CLI, `AbstractTool` wrappers and the MCP server all inherit the behaviour.

**Decisions already taken by the user** (fixed constraints for this proposal and the spec):

1. **Id scheme `ns::id`** — e.g. `asyncdb::file:README.md`. The router prefixes on the way out and
   strips on the way in; underlying stores are untouched. Unprefixed ids resolve to the local
   namespace.
2. **Configuration in both places** — per-repo `.parrot/wiki.json` (`namespaces` map) **and** a
   global user registry `~/.parrot/wikis.json`; repo entries override global ones on clash.
3. **v1 routing = explicit + broadcast** (`--ns <name>` / `--ns all`), per-namespace min-max +
   merge/dedup. Automatic intent/LLM routing is a **v2 follow-up**, documented, not built.
4. **`obsidian` is a namespace kind** — *Delta 1, 2026-08-23, after synthesis*. A vault registers
   as `{"vault": "<path>"}`; its plane lives **inside the vault** (`<vault>/.parrot/wiki/wiki.db`)
   and is built by the existing vault-aware `wikitoolkit build --path <vault>`. Registration is
   `ns add --vault` only (consistent with U1); `vault_dir` is not auto-promoted. The
   `_prune_removed` blast radius is fixed **inside this feature**. Full rationale and the four
   sub-decisions (D4.1-D4.4): `sdd/state/FEAT-450/source.md` § "Delta 1".

> **Delta 1 in one line**: "query my Obsidian vault too" is not an ingestion problem — the vault
> scanner already exists and already emits this feature's exact plane shape (F017); it is the
> routing problem this proposal already solves. The only alternative (repo scan + vault in one
> plane) is unsafe today and stays out of scope.

**Initial signals** (extracted, not interpreted):
- Verbs: register, route, broadcast, federate → additive capability (enrichment)
- Named entities: `wikitoolkit`, `FederatedWikiStore`, `ns::id`, `WikiProjectConfig`,
  `~/.parrot/wikis.json`, `--ns`, `IntentRouterMixin`
- Acceptance criteria provided: no (three design decisions instead)

---

## 1. Synthesis Summary

The request is to let one `wikitoolkit` invocation read several independently-built wiki planes
under stable names. The codebase already has every structural piece: a single backend-agnostic
contract (`BaseWikiStore`, `store.py:289-385`) behind which all consumers sit; a read resolver that
can already open an arbitrary store directory (`cli.py:_resolve_read_store`, 199-251); per-group
min-max + dedup merge helpers (`search.py:473-530`); a tools factory and an MCP server that are
bound to *one* injected store (`tools.py:399-428`, `mcp_server.py:66-146`); and an explicit
"multi-wiki dispatch would go here" placeholder in `toolkit.py:1205-1228`. What is missing is a
**`FederatedWikiStore`** that implements the contract over `{name: store}`, prefixes ids with
`ns::`, routes by prefix, merges on broadcast and sends each write to exactly one namespace
(local by default, or the one named by `--ns`, per U2) — plus a
`namespaces` config model, a global registry loader, a `--ns` selector and an explicit read-only
open path for foreign SQLite planes (today `_connect` migrates on open, `store.py:565`). No
competing design exists: the `KnowledgeRouter` cited by FEAT-449 is not in source, and
`MultiStoreSearchToolkit` (FEAT-379) federates *kinds* of stores for agents, not wiki planes for
`wikitoolkit`. **Delta 1** adds a fourth namespace kind at no architectural cost: `vault_scan.py`
already turns an Obsidian vault into the identical `RepoScan` shape (same `file:`/`dir:` ids,
`references`/`embeds`/`tagged` edges, `category="document"`/`"tag"`, zero LLM) and
`wikitoolkit build` already auto-detects `.obsidian/`, so a vault namespace is config +
registration only — plus two bounded fixes the shared-store path makes unavoidable
(`_prune_removed` scoping, `.parrot` exclusion inside a vault). Recommendation: go straight to
`/sdd-spec`.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-450/findings/`. No fabricated paths or symbols.

### 2.1 Localization

Paths below are relative to `packages/ai-parrot/src/parrot/knowledge/wiki/` unless absolute.

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `cli.py` | `_resolve_read_store` | 199-251 | single-store read resolver (`--store`/`WIKI_STORE`); becomes the federation entry point | F002 |
| 2 | `cli.py` | `_store_options`, `query`, `page`, `related`, `status` | 255-272, 1075-1288 | read commands that gain `--ns` | F002, F011 |
| 3 | `cli.py` | `_resolve_write_store` | 1488-1493 | authoring resolver — gains `--ns <name>` (single namespace, read-write; U2) | F002 |
| 4 | `store.py` | `BaseWikiStore` | 289-385 | contract the federated store implements (15 abstract methods) | F003 |
| 5 | `store.py` | `create_wiki_store` | 1217-1274 | factory used to open each namespace (sqlite / memory / arangodb) | F003 |
| 6 | `store.py` | `SQLiteWikiStore._connect`, `_connect_readonly` | 514-655 | write-first open running `_migrate`; read-only ladder only as error fallback | F004 |
| 7 | `search.py` | `_merge_groups`, `_apply_weight`, `_store_row_to_wiki` | 229-268, 473-530 | per-group min-max + weight + dedup — the broadcast merge | F005 |
| 8 | `context.py` | `_ID_PREFIX_RE`, `pack_results` | 27-30, 105-190 | id-prefix parsing that must skip a leading `ns::` | F010 |
| 9 | `repo_scan.py` | `file_concept_id`, `dir_concept_id` | 249-256 | repo-relative ids that collide across namespaces | F010 |
| 10 | `project.py` | `WikiProjectConfig`, `find_project_root`, `load_project_config` | 125-366 | config model gaining `namespaces`; global registry loader lives here | F009 |
| 11 | `tools.py` | `WikiQueryInput`, `WikiPageInput`, `WikiRelatedInput`, `create_wiki_tools` | 23-64, 399-428 | tool inputs gaining optional `namespace`; factory bound to one store | F007 |
| 12 | `mcp_server.py` | `create_wiki_mcp_server` | 66-146 | MCP store injection point (lines 105/108) | F008 |
| 13 | `toolkit.py` | `LLMWikiToolkit._config_for`, `list_wikis` | 1205-1228, 499-516 | explicit multi-wiki dispatch placeholder ("future iteration") | F006 |
| 14 | `arango_store.py` | `ArangoDBWikiStore.__init__` | 160-175 | `database or f"wiki_{wiki_name}"` — per-database isolation = arangodb namespace | F015 |
| 15 | `claude_code/hook.py` | `build_nudge` | 175-215 | unaffected consumer of `WikiProjectConfig` | F013 |
| 16 | `vault_scan.py` | `scan_vault`, `is_obsidian_vault`, `VAULT_EXCLUDE_DIRS` | 50, 55, 111 | vault → `RepoScan` (same ids/edges as `repo_scan`); the `vault` namespace needs no new scanner | F017 |
| 17 | `cli.py` | `build` (`--vault/--no-vault`) | 759-815, 842 | auto-detects `.obsidian/`; `build --path <vault>` already builds a vault plane | F017 |
| 18 | `tools.py` | `VaultIngestInput`, `VaultIngestTool` | 49, 288, 360-368 | shared-store vault ingest — calls `_prune_removed` on the project's own store | F017 |
| 19 | `cli.py` | `_prune_removed` | 390-423 | global page/source prune; must become scan-root/namespace scoped (D4.4) | F017, F010 |
| 20 | `project.py` | `vault_dir`, `resolve_vault_dir` | 177-186, 245-285 | existing vault pointer for the MCP `ObsidianToolkit` — kept, *not* promoted to a namespace (D4.3) | F017 |
| 21 | `bookkeeper.py` | `WikiBookkeeper.LOG_FILENAME`, `log_operation` | 45, 201 | writes `index.md`/`log.md` into the storage dir → self-ingestion if the plane sits in the vault | F017 |

### 2.2 Constraints Discovered

- **Full contract, not a search helper.** Every consumer (search, ingest, toolkit, export, tools,
  MCP) talks only to `BaseWikiStore`. *Implication*: `FederatedWikiStore` must implement all 15
  methods (lint/dump ones may raise `NotImplementedError` explicitly). *Evidence*: F003
- **SQLite opens write-first.** `_connect` replays schema and calls `_migrate` (565); the
  read-only ladder engages only on a readonly-environment `OSError` (573-576). *Implication*: a
  read of a sibling repo's `wiki.db` could migrate it — an explicit `read_only=True` constructor
  flag that goes straight to `_connect_readonly` (and skips `mkdir`) is required. *Evidence*: F004
- **Scores are corpus-relative.** `search_fts` returns `-bm25`, "NOT normalised — callers
  normalise". *Implication*: broadcast must min-max per namespace before merging (reuse
  `_apply_weight` / `cli._normalize_scores`). *Evidence*: F003, F005
- **Ids collide; few parsers.** `file:<relpath>` / `dir:<relpath>` are identical across repos.
  Only `_ID_PREFIX_RE` (context.py:30, title elision at 124) and `cli._prune_removed`
  (417-420, local build only) parse prefixes. *Implication*: `ns::` prefixing at the federation
  boundary is safe; `_ID_PREFIX_RE` must tolerate a leading `<ns>::`. *Evidence*: F010
- **`project.py` stays dependency-light** (stdlib + pydantic) because the PreToolUse hook imports
  it. *Implication*: `WikiNamespaceConfig` and the `~/.parrot/wikis.json` loader must not import
  store/search modules; stores are opened only in cli/mcp. *Evidence*: F009, F013
- **Precedence is tested.** `--store > --path > WIKI_STORE > project`, and an ambient env must
  never redirect a `--path`-scoped call (test_cli.py:212-214). *Implication*: `--ns` layers on
  top without changing this order. *Evidence*: F002, F012
- **Adjacent designs.** `MultiStoreSearchToolkit` (FEAT-379) already does origin-attributed
  multi-*kind* search with BM25 rerank at the agent layer; FEAT-449 (in-flight, plan stage) names
  GraphIndex namespaces `legal:core`, `legal:civil`. *Implication*: stay at the wikitoolkit/store
  layer; the `::` separator lets a wiki namespace mirror a GraphIndex namespace name that contains
  `:`. *Evidence*: F001
- **Low conflict risk.** 25 commits in 45 days on the package; none touch resolution, ids or
  merge helpers (`b5893f4e4` touched `cli.py` — rebase only). *Evidence*: F014
- **[Δ1] One plane per corpus is forced, not preferred.** `_prune_removed` (cli.py:390-423) deletes
  every `file:`/`dir:` page and every source URI outside the current scan, store-wide;
  `VaultIngestTool` calls it against the project's own store (tools.py:367). Repo pages + vault
  notes in one plane therefore annihilate each other on alternating builds, on top of the F010 id
  collision (`file:README.md` in both). *Implication*: the vault gets its own plane behind a
  namespace, and `_prune_removed` gains a scope argument (D4.4). *Evidence*: F017, F010
- **[Δ1] A vault-hosted plane self-ingests.** `scan_vault` rglobs `*.md` filtering only
  `VAULT_EXCLUDE_DIRS` (vault_scan.py:50) — no exclude argument, no `config.exclude_dirs` — while
  `WikiBookkeeper` writes `index.md`/`log.md` into the storage dir (bookkeeper.py:45, 201).
  *Implication*: D4.2 requires `.parrot` in `VAULT_EXCLUDE_DIRS` (or `scan_vault` honouring
  `config.exclude_dirs`). *Evidence*: F017

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched area |
|--------|------|--------|---------|--------------|
| `b5893f4e4` | 2026-08-21 | Jesus | fix(bedrock,wiki): … wire the PageIndex plane | `cli.py` (rebase risk only) |
| `c51372341` | 2026-08-20 | Javier León | fix(wiki): make the ArangoDB backend usable, searchable in two languages | `arango_store.py` |
| `861ab2110` | 2026-08-16 | Claude | feat(wiki): expose the Obsidian vault through the wikitoolkit MCP server | `mcp_server.py` |
| `3c8f713b8` | 2026-08-03 | Jesus | feat(mcp-local-server-wikitoolkit): TASK-2081 — WikiToolkit MCP server + CLI command | `mcp_server.py`, `cli.py` |
| `216bd0c1f` | 2026-08-02 | Jesus Lara | feat(supervised-wiki-ingestion): TASK-2075 — `wikitoolkit ingest` CLI | `cli.py`, `ingest.py` |

FEAT-449 (Legal LLM Wiki) is at `phase: plan_drafted`, untracked — no code landed. *Evidence*: F001, F014

---

## 3. Probable Scope

### What's New

- **`federation.py` — `FederatedWikiStore(BaseWikiStore)`**: holds `{name: BaseWikiStore}` and the
  local namespace name. Reads (`search_fts`, `search_vector`, `list_pages`) fan out with
  `asyncio.gather`, prefix ids `ns::`, merge via per-namespace min-max + dedup (`_merge_groups`
  shape). `get_page` / `neighbors` route by prefix (unprefixed → local) and re-prefix neighbour ids.
  Writes (`upsert_pages`, `add_edges`, `replace_source_slice`, `delete_page`, `upsert_embedding`)
  go to exactly one namespace: the local one by default, or the single namespace selected by an
  explicit `--ns <name>` / `namespace` argument (U2) — that store is opened read-write for the
  call; `--ns all` is never a write target. `stats` returns `{"namespaces": {name: stats}}`. A
  namespace that is unbuilt/unreachable is skipped with a note, never fails the whole call
  (FEAT-379 degradation pattern).
- **`project.py` — `WikiNamespaceConfig`** (`path` | `store`+`backend` | arangodb `database`,
  optional `description`), `WikiProjectConfig.namespaces: dict[str, WikiNamespaceConfig]`,
  `load_global_registry()` for `~/.parrot/wikis.json`, and `merge_namespaces(repo, global)`
  (repo wins). Resolution into opened stores lives in cli/mcp (keeps project.py light).
- **`cli.py`** — `--ns <name|all>` on `query` / `page` / `related` / `status`; `--ns <name>`
  (single namespace only) on `remember` / `note` / `link` (U2); new group
  `wikitoolkit ns list|add|remove [--global]` — `ns add` is the **only** way a namespace enters
  either registry (U1).
- **`tools.py`** — optional `namespace` field on `WikiQueryInput` / `WikiPageInput` /
  `WikiRelatedInput`; `wiki_status` lists namespaces. MCP inherits via the injected store.
- **Docs** — "Namespaces" section in `documentation/parrot-wiki-cli.md` (next to the existing
  `--store` section, lines 424-451) and a note in `docs/wiki-claude-code.md`.
- **[Δ1] `vault` namespace kind** — `WikiNamespaceConfig.vault: str | None` (mutually exclusive
  with `path` / `store` / `database`), resolving to `<vault>/.parrot/wiki` on the sqlite backend,
  opened read-only for reads like any foreign namespace. Registered by
  `wikitoolkit ns add <name> --vault <path> [--global]`; detection at registration time is a cheap
  `(<path>/.obsidian).is_dir()` probe, **not** a `scan_vault` import (`project.py` must stay
  dependency-light — F009). An unbuilt vault plane is skipped with the standard note plus a
  `wikitoolkit build --path <vault>` hint. No new build path: the vault is a wiki project.
- **Tests** — `tests/knowledge/wiki/test_federation.py` (two temp sqlite stores: id round-trip,
  merge ordering, write routing, read-only guarantee, skip-on-missing) and `--ns` cases in
  `test_cli.py` following the existing `--store` harness (197-245). **[Δ1]** a temp vault
  (`.obsidian/` + two linked notes) registered as a namespace and queried end-to-end; a regression
  test that `_prune_removed` scoped to one root leaves another root's pages intact; a test that a
  plane at `<vault>/.parrot/wiki` is not re-ingested on rebuild.

### What Changes

- **`cli.py`::`_resolve_read_store`** — when namespaces resolve and `--store` is not given, return
  a `FederatedWikiStore` (local + configured); `--ns <name>` narrows to one store, `--ns all` is
  the broadcast. *Evidence*: F002
- **`store.py`::`SQLiteWikiStore.__init__` / `_connect`** — `read_only: bool = False`; when set,
  skip `mkdir`/schema replay/`_migrate` and use `_connect_readonly` directly. Foreign namespaces
  are opened with `read_only=True` for reads; an authoring command with `--ns <name>` re-opens
  that one namespace read-write (U2). *Evidence*: F004
- **`cli.py`::`_resolve_write_store`** — accept `--ns <name>`; resolve that single namespace
  (repo map, then global registry) and open it read-write; reject `all`. *Evidence*: F002
- **`context.py`::`_ID_PREFIX_RE`** — strip an optional leading `<ns>::` before the kind prefix so
  stub title elision keeps working. *Evidence*: F010
- **`mcp_server.py`::`create_wiki_mcp_server`** — open namespaces (read-only) and inject the
  federated store at the `create_wiki_store` / `create_wiki_tools` calls (105/108). *Evidence*: F008
- **`tools.py`::`Wiki*Input`, `create_wiki_tools`** — thread the optional `namespace` argument.
  *Evidence*: F007
- **`cli.py`::`status`** — per-namespace block (plane stats; staleness where a
  `SourceCollectionManager` can be opened for a sqlite namespace). *Evidence*: F011
- **[Δ1] `cli.py`::`_prune_removed`** — take the scan scope explicitly (scan root / namespace) and
  delete only pages and sources belonging to it, so no ingest can wipe another corpus. Callers:
  `build` (cli.py:842) and `VaultIngestTool` (tools.py:367). *Evidence*: F017
- **[Δ1] `vault_scan.py`::`VAULT_EXCLUDE_DIRS`** — add `.parrot` (or honour
  `config.exclude_dirs`), so a vault-hosted plane's `index.md`/`log.md` are not scanned back in.
  *Evidence*: F017
- **[Δ1] `project.py`::`WikiNamespaceConfig`** — the `vault` kind and its resolution rule
  (`<vault>/.parrot/wiki`, sqlite). *Evidence*: F017, F009
- **`toolkit.py`::`LLMWikiToolkit._config_for` / `list_wikis`** — *optional*: accept an injected
  federated store and enumerate namespaces; otherwise untouched. *Evidence*: F006

### What's Untouched (Non-Goals)

- `repo_scan.py` id builders and the `build` / `upsert` / `ingest` pipelines — each namespace is
  built by its own project (`wikitoolkit build --path ../asyncdb` already works).
- `claude_code/hook.py` — single-root nudge, no store access.
- SQLite schema; ArangoDB / InMemory backend internals.
- `MultiStoreSearchToolkit` (FEAT-379) and FEAT-449 GraphIndex namespaces.
- **[Δ1] `vault_dir` semantics** — unchanged: it keeps pointing the MCP server at the vault whose
  `ObsidianToolkit` note-CRUD tools get registered (`mcp_server.py:111-146`). It is *not*
  auto-promoted to a namespace (D4.3, consistent with U1: `ns add` is the only registration path).
- **[Δ1] Obsidian write-back** — turning `remember` / `note` output into vault notes via
  `ObsidianToolkit`, and cross-namespace edges between a vault note and a code page: v2.
- **[Δ1] FEAT-392** (`llmwiki-obsidian-plugin`, vault → PageIndex/GraphIndex) — a different plane;
  untouched by this feature.
- **v2 follow-ups (documented, not built)**: automatic intent routing over namespace
  `description`s (candidate: `IntentRouterMixin`, `parrot/bots/mixins/intent_router.py:123` —
  agent layer, not the dependency-light CLI path); RRF instead of min-max; cross-namespace edges;
  broadcast/multi-target writes (v1 writes target exactly one namespace).

### Patterns to Follow

- `_resolve_read_store` precedence and `ClickException` messaging for missing stores. *Evidence*: F002
- `_merge_groups` / `_apply_weight` per-group min-max + dedup by `node_id`. *Evidence*: F005
- `create_wiki_store` backend switch with lazy backend imports. *Evidence*: F003
- CliRunner tests that build temp repos, then `query`/`page`/`related --store`. *Evidence*: F012
- Graceful per-origin degradation (log + note, never fail the whole search). *Evidence*: F001

### Integration Risks

- **Foreign `wiki.db` mutated by a read** → silent schema drift in a sibling repo. *Mitigation*:
  explicit `read_only` flag + a test asserting no write/migration on a foreign plane. *Evidence*: F004
- **Large planes × N namespaces** (ai-parrot's `wiki.db` ≈ 311 MB) → broadcast latency.
  *Mitigation*: lazy open, concurrent `gather`, per-namespace `top_k`, WAL `mode=ro`. *Evidence*: F003, F004
- **`ns::` noise in ids** breaking stub rendering / CLAUDE.md examples. *Mitigation*:
  `_ID_PREFIX_RE` update; local namespace stays unprefixed (see U3). *Evidence*: F010
- **Heavy imports leaking into the hook path** via the registry loader. *Mitigation*: loader is
  stdlib + pydantic; stores are opened only in cli/mcp. *Evidence*: F009, F013
- **[Δ1] `.parrot/` inside a synced vault** — Dropbox / iCloud / Obsidian Sync will carry
  `wiki.db` (and its WAL) between machines, which can corrupt a SQLite file mid-write.
  *Mitigation*: document it; the plane is derived and rebuildable (`build --path <vault>`), and
  users who sync can exclude `.parrot/` or register the vault with an explicit `store` instead.
  *Evidence*: F017 (accepted cost of D4.2)
- **[Δ1] Prune scoping regression** — `_prune_removed` is the mechanism that keeps a plane in sync
  with its source tree; a wrong scope silently stops pruning deletions. *Mitigation*: the
  two-root regression test above, plus an assertion that a normal single-root `build` still prunes.
  *Evidence*: F017
- **Unreachable ArangoDB namespace** stalling a broadcast. *Mitigation*: eager `initialize()` with
  timeout (as the `--backend arangodb` path does) and skip-with-note. *Evidence*: F002, F015

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Read commands resolve exactly one store via `_resolve_read_store` with `--store`/`WIKI_STORE` precedence | F002 | high | function body + docstring read |
| C2 | `BaseWikiStore` is the only consumer surface; `create_wiki_store` builds sqlite/memory/arangodb | F003 | high | abstract methods + factory read |
| C3 | `_connect` runs `_migrate` on open; read-only engages only on a readonly-env error | F004 | high | lines 565 / 573-576 read |
| C4 | `_merge_groups` / `_apply_weight` do per-group min-max + weight + dedup, reusable for namespaces | F005 | high | bodies read |
| C5 | `LLMWikiToolkit` reserves an explicit multi-wiki dispatch point | F006 | high | docstring text |
| C6 | Tools and MCP bind six tools to one store; no `namespace` in inputs | F007, F008 | high | models + factory read |
| C7 | Ids are repo-relative and collide; only two sites parse prefixes | F010 | high | builders read + package grep |
| C8 | No `KnowledgeRouter` exists in source | F001 | high | grep over `packages/` empty; FEAT-449 marks it VERIFY |
| C9 | `MultiStoreSearchToolkit` federates origin kinds for agents, not wiki planes for wikitoolkit | F001 | medium | outline + brainstorm read; adapters not read line-by-line |
| C10 | ArangoDB namespaces map onto the existing `database` constructor arg | F015 | high | constructor read |
| C11 | `ns::` is unambiguous against single-colon kind prefixes and inner-colon ids | F010 | medium | inferred from regex + comment; no corpus scan |
| C12 | Per-namespace staleness needs one `SourceCollectionManager` per sqlite namespace | F011, F002 | medium | status code read; shape inferred |
| C13 | Recent commits do not conflict with the touched areas | F014 | high | 45-day git log |
| C14 | The hook is unaffected if `project.py` stays dependency-light | F009, F013 | high | hook only calls `is_built` / `storage_path` |
| C15 | [Δ1] `scan_vault` emits the same `RepoScan` shape/ids as `repo_scan`, so a vault plane needs no new scanner or build path | F017 | high | module docstring + `build --vault` branch read |
| C16 | [Δ1] `_prune_removed` is store-wide and `VaultIngestTool` calls it on the project's own store — repo + vault in one plane destroys both | F017 | high | both bodies read (cli.py:390-423, tools.py:367) |
| C17 | [Δ1] A plane at `<vault>/.parrot/wiki` self-ingests unless `.parrot` is excluded | F017 | high | `VAULT_EXCLUDE_DIRS` (50) + bookkeeper `log.md` path (201) read |
| C18 | [Δ1] Registering a vault needs only an `.obsidian/` probe in `project.py`, keeping the hook path dependency-light | F017, F009 | medium | `is_obsidian_vault` is a one-line `is_dir()` check, but its module imports `parrot.interfaces.obsidian` — the probe must be inlined, not imported |

Distribution: **14** high, **4** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase — user decisions, 2026-08-23)

- [x] **Id scheme for namespaced pages?** — *Resolved*: `ns::id`. *Resolves*: C7, C11
- [x] **Where is namespace config declared?** — *Resolved*: both per-repo `.parrot/wiki.json` and
  global `~/.parrot/wikis.json`; repo overrides global. *Resolves*: C14
- [x] **Routing strategy for v1?** — *Resolved*: explicit `--ns <name>` + broadcast `--ns all`;
  intent router deferred to v2 as a documented follow-up. *Resolves*: C4, C9

- [x] **U1 — How do entries reach `~/.parrot/wikis.json`?** — *Resolved (user, 2026-08-23)*:
  **only via `wikitoolkit ns add`** (with `--global` for the user registry). `build` never
  self-registers. *Resolves*: C12
- [x] **U2 — Are `remember/note/link --ns <foreign>` writes allowed in v1?** — *Resolved (user,
  2026-08-23)*: **yes — required in v1.** An explicit `--ns <name>` on an authoring command opens
  *that single* namespace read-write and writes there; without `--ns` writes go to the local
  namespace. Reads of foreign namespaces stay read-only; broadcast (`--ns all`) is never a write
  target. *Resolves*: C3
- [x] **U3 — In broadcast output, is the local namespace unprefixed?** — *Resolved (user,
  2026-08-23)*: **yes.** Local ids stay `file:x` / `dir:x`; only foreign ids carry `ns::`.
  *Resolves*: C11

### Resolved (delta 1 — user decisions, 2026-08-23)

- [x] **D4.1 — Is Obsidian a namespace kind or a second corpus in the local plane?** — *Resolved*:
  a namespace kind (`{"vault": "<path>"}`), routed like every other namespace. *Resolves*: C15, C16
- [x] **D4.2 — Where does a vault namespace's plane live?** — *Resolved*: **inside the vault**,
  `<vault>/.parrot/wiki/wiki.db`, built by the existing `wikitoolkit build --path <vault>`; the
  vault becomes a self-contained wiki project shared by every repo that registers it. Accepted
  cost: a `.parrot/` directory inside a possibly-synced vault. *Resolves*: C15, C17
- [x] **D4.3 — Does `vault_dir` auto-register as a namespace?** — *Resolved*: no. `ns add --vault`
  only (consistent with U1); `vault_dir` keeps its MCP `ObsidianToolkit` job. *Resolves*: C18
- [x] **D4.4 — Where does the `_prune_removed` blast-radius fix belong?** — *Resolved*: **inside
  FEAT-450**, since v1 already namespace-scopes writes. Not deferred to a hotfix. *Resolves*: C16

### Unresolved (defer to spec / implementation)

- None.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-450`** — *Rationale*: localization and reuse points are high-confidence, the
three architectural decisions are fixed, and U1–U3 are resolved by the user. No open question
remains; no fork to brainstorm.

### Alternatives

- **`/sdd-brainstorm FEAT-450`** — not needed; all design choices are closed.
- **Manual review** — not needed; research was not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-450/state.json` |
| Source (raw) | `sdd/state/FEAT-450/source.md` |
| Research plan | `sdd/state/FEAT-450/research_plan.json` (28 queries) |
| Findings (digests) | `sdd/state/FEAT-450/findings/F001-*.md` … `F016-*.md`, `F017-*.md` (delta 1) |
| Synthesis (JSON) | `sdd/state/FEAT-450/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 18 / 40 · Grep calls: 9 / 25 · Git calls: 1 / 10 · Wall time: ~240s / 300s
- Truncated: **no**

**Mode determination**: `auto` → `enrichment` (additive verbs: register, route, federate).

**Delta 1 (2026-08-23)**: added after synthesis, on the user's request, before approval — an
`obsidian` namespace kind. Grounded in one new finding (`F017`, 6 files read, 1 grep) verified
against source in the same session; no re-run of the research phase. Budget line below covers the
original run only.

**Gate note**: the Phase-1 plan gate was not shown interactively — the user pre-approved the
research direction and fixed the three design decisions in the preceding conversation. Phase-5
Q&A: U1–U3 answered by the user on 2026-08-23 (3/3). `status: review` pending an explicit
"accept".

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara / Claude Fable 5 |

---
kind: inline
jira_key: null
fetched_at: 2026-08-23T02:05:00Z
summary_oneline: "Namespaces for wikitoolkit — federate N wiki stores (sibling repos, Obsidian vaults, non-code brains, ArangoDB dbs) behind ns::id with explicit + broadcast routing"
---

# wiki-namespaces — Namespaces (multi-wiki federation) for wikitoolkit / LLM Wiki

## Problem

Today each LLM Wiki is a single plane per repo (`.parrot/wiki.json` -> `storage_dir/wiki.db`);
`query`/`page`/`related` and the MCP tools read exactly one store. ai-parrot depends on sibling
personal repos (navigator, asyncdb, navconfig, querysource) whose knowledge is invisible to the
wiki. Beyond code, the same mechanism should let a user compose multiple "brains" (e.g. a lawyer
with graphs for legislation, jurisprudence, own cases — built via `wikitoolkit ingest`) and query
all of them or a specific one.

## Goal

wikitoolkit can register named namespaces, each pointing at a distinct wiki store (another repo's
`.parrot/wiki` plane, an Obsidian vault's plane, an arbitrary store dir, or an ArangoDB database), and route
query/page/related/status either explicitly to one namespace or broadcast to all with merged
ranking. CLI, `AbstractTool` wrappers (`tools.py`) and the MCP server (`mcp_server.py`) all
inherit the behaviour.

## Decisions already taken by the user (fixed constraints)

1. **Namespaced page id scheme: `ns::id`** (e.g. `asyncdb::file:README.md`). The router prefixes
   ids on the way out and strips the prefix on the way in; underlying stores are untouched.
   Unprefixed ids resolve to the local/default namespace.
2. **Namespace configuration lives in BOTH places**: per-repo `.parrot/wiki.json` (`namespaces`
   map: entries with `path` (another wiki project root -> reuse its `load_project_config`/backend),
   or `store`+`backend`, or arangodb `database`) AND a global user registry `~/.parrot/wikis.json`
   for brains that are not repositories. Per-repo entries override global ones on name clash.
3. **v1 routing = explicit** (`--ns <name>` / `namespace` tool argument) **+ broadcast** (`--ns all`
   or default when namespaces are configured) with per-namespace min-max normalisation +
   merge/dedup. An intent/LLM-based automatic router (reusing `IntentRouterMixin`) is OUT OF
   SCOPE for v1 — document it as a v2 follow-up.
4. **`obsidian` is a namespace kind** (delta, 2026-08-23 — see "Delta 1" below). An Obsidian
   vault registers as `{"vault": "<path>"}`; its plane lives **inside the vault**
   (`<vault>/.parrot/wiki/wiki.db`), built by the existing vault-aware `wikitoolkit build`.
   `wikitoolkit query` then reaches vault notes through the same broadcast/`--ns` routing as any
   other namespace. The `_prune_removed` blast radius that makes today's shared-store
   `vault_ingest` unsafe is fixed **inside this feature**.

## Proposed shape (to validate against the code, not redesign)

- New `parrot/knowledge/wiki/federation.py`: `FederatedWikiStore(BaseWikiStore)` holding
  `{name: BaseWikiStore}` + the local namespace name. Read methods fan out with
  `asyncio.gather`, prefix ids `ns::`, merge via existing min-max/dedup helpers;
  `get_page`/`neighbors` route by id prefix; write methods delegate to the local namespace only.
  `stats` reports per namespace.
- `project.py`: `WikiNamespaceConfig` (kinds: `path` | `store`+`backend` | `database` | **`vault`**)
  + `namespaces` on `WikiProjectConfig`; global registry
  loader for `~/.parrot/wikis.json`; resolver producing opened read-only stores (skip/report
  unbuilt namespaces instead of failing the whole query).
- `cli.py`: `--ns` on query/page/related/status; `wikitoolkit ns list|add|remove`;
  `_resolve_read_store` returns the federated store when namespaces resolve.
- `tools.py` / `mcp_server.py`: optional `namespace` arg; `wiki_status` lists namespaces.
- Docs: `documentation/parrot-wiki-cli.md` section + `docs/wiki-claude-code.md` note.
- Tests under `tests/knowledge/wiki/`.
- v2 follow-up (document only): automatic intent router over namespace descriptions, RRF
  instead of min-max, cross-namespace edges.

## Prior research claims to verify (from the preceding conversation)

`cli.py:_resolve_read_store` (`--store`/`WIKI_STORE`), `BaseWikiStore`/`create_wiki_store`,
`WikiCombinedSearch._merge_groups`/`_apply_weight`, `LLMWikiToolkit._config_for` TODO,
`create_wiki_tools`/`create_wiki_mcp_server` single-store binding, `concept_id = file:<relpath>`
collisions, `_ID_PREFIX_RE`, `SQLiteWikiStore._connect` running `_migrate` on open,
ArangoDB `wiki_{name}` database isolation, supervised `ingest`, no `.parrot/` in sibling repos,
SQLite ATTACH rejected. NEW since the conversation: an in-flight FEAT-449 (Legal LLM Wiki)
references a `KnowledgeRouter` (FEAT-200) with namespaced `concept_id`, and a brainstorm
`multistoresearchtool-parrotwiki` exists — both must be checked for overlap.

---

## Delta 1 (user, 2026-08-23, after research/synthesis) — `obsidian` as a namespace kind

### Request

> "If we have a toolkit for integration with Obsidian, can Obsidian be converted into a sub-part
> of our wikitoolkit? That means when `wikitoolkit query` runs and an Obsidian vault is configured,
> Obsidian is also queried for extracting data — wikitoolkit can interact with Obsidian as a new
> ingest data source."
>
> Follow-up: *"add in current FEAT-450 as delta before it is approved, as a new kind of namespace
> (obsidian)."*

### Why it belongs here and not in its own feature

The vault **scanner already exists** and produces exactly the plane this feature federates:
`vault_scan.py` mirrors `repo_scan.py`'s output shape (same `file:`/`dir:` ids, same `contains`
dir pages), `wikitoolkit build` auto-detects `.obsidian/` and routes to it, notes/tags land as
`category="document"` / `category="tag"` pages with `references` / `embeds` / `tagged` edges — no
LLM, no embeddings (F017). So "query my vault too" is not an ingestion problem; it is exactly the
routing problem FEAT-450 already solves.

The alternative — one plane holding both the repo scan and the vault — is already half-built via
`VaultIngestTool` and is **unsafe**: `_prune_removed` (cli.py:390-423) is global over the store, so
ingesting a vault into a repo's plane deletes every codebase page, and the next `build` deletes the
vault notes back; ids collide besides (`file:README.md` in both). That is the same collision class
F010 found across repos. One plane per corpus + `ns::` at the boundary is the answer for vaults for
the same reason it is the answer for sibling repos.

### Decisions taken with this delta (user, 2026-08-23)

- **D4.1 — Namespace kind.** A namespace entry may declare `vault: <path>`. It resolves to that
  vault's own wiki plane and is otherwise an ordinary namespace: `--ns <name>`, broadcast, `ns::id`
  prefixing, read-only foreign opens, `remember/note/link --ns <name>` writes (U2) all unchanged.
- **D4.2 — Plane location: inside the vault.** A vault namespace's store is
  `<vault>/.parrot/wiki/wiki.db` — the vault becomes a self-contained wiki project, so the existing
  `wikitoolkit build --path <vault>` (vault auto-detection) builds it with **no new build plumbing**,
  and every repo that registers the same vault shares one plane. Accepted cost: a `.parrot/`
  directory inside the vault (invisible to Obsidian, but carried by Dropbox / iCloud / Obsidian Sync).
- **D4.3 — Registration stays `ns add` only** (consistent with U1):
  `wikitoolkit ns add <name> --vault <path> [--global]`. `vault_dir` is **not** auto-promoted to a
  namespace; it keeps its current, separate job — telling the MCP server which vault to expose
  through `ObsidianToolkit`'s note-CRUD tools.
- **D4.4 — Fix `_prune_removed` inside FEAT-450.** Scope pruning to the scan root / namespace that
  produced the scan, so no ingest can delete another corpus's pages. In scope for this feature
  because v1 already namespace-scopes writes; not deferred to a separate hotfix.

### Consequences for the proposed shape

- `project.py`: `WikiNamespaceConfig` gains the `vault` kind (mutually exclusive with
  `path` / `store` / `database`); resolution = `<vault>/.parrot/wiki`, sqlite backend, opened
  read-only for reads. `project.py` stays dependency-light — no `vault_scan` import (it pulls
  `parrot.interfaces.obsidian`), so vault *detection* at registration time is a cheap
  `(<path>/.obsidian).is_dir()` check, not a `scan_vault` call.
- `cli.py`: `ns add --vault`; `--ns` routing unchanged; `status` shows a vault namespace with its
  note/tag counts. If the vault plane is not built, the namespace is skipped with the same
  "unbuilt namespace" note as any other (never fails the broadcast) and `ns add` prints the
  `wikitoolkit build --path <vault>` hint.
- `tools.py` / `mcp_server.py`: unchanged beyond the generic `namespace` argument. `VaultIngestTool`
  and the `ObsidianToolkit` tools stay as they are (the vault write surface), with `_prune_removed`
  scoped per D4.4.
- Non-goal (v2): writing wiki `remember`/`note` output *back* into the vault as Obsidian notes via
  `ObsidianToolkit`, and cross-namespace edges between a vault note and a code page.

### Required by D4.2 — verified, not speculative

Putting the plane inside the vault creates a **self-ingestion loop today**: `scan_vault`
(vault_scan.py:111-137) rglobs every `*.md` under the vault and filters only
`VAULT_EXCLUDE_DIRS = {.obsidian, .trash, .git, .hg, .svn}` (line 50) — it takes no exclude
argument and never reads `config.exclude_dirs` — while `WikiBookkeeper` writes `index.md` and
`log.md` **into the storage dir** (bookkeeper.py:45, 201). So `<vault>/.parrot/wiki/log.md` would
be ingested as a vault note, and grow with every build. D4.2 therefore requires: add `.parrot` to
`VAULT_EXCLUDE_DIRS` (or teach `scan_vault` to honour `config.exclude_dirs`, as `repo_scan` does —
this repo's own `.parrot/wiki.json` already carries `exclude_dirs: [".parrot/wiki"]`).

### Claims to verify at spec time

`scan_vault(root, body_max_chars, max_file_bytes)` is the whole signature — a vault namespace
inherits the *vault's own* `wiki.json` caps, not the registering repo's; `find_project_root` does
not mis-detect the vault's `.parrot/` when the CLI runs inside a repo that registers it.


---

## Delta 2 (user, 2026-08-23, at acceptance) — `vault` resolution via `load_project_config`

The `vault` namespace kind resolves its plane through `load_project_config(<vault>)` exactly like the `path` kind: the vault's own `.parrot/wiki.json` (when present) decides `storage_dir`, backend and scan caps; when absent, defaults apply (`<vault>/.parrot/wiki/wiki.db`, sqlite). `vault` = `path` + `.obsidian/` probe + `wikitoolkit build --path <vault>` hint. Supersedes the hard-coded `<vault>/.parrot/wiki` rule in D4.2. Proposal accepted by the user at this point (`status: accepted`).

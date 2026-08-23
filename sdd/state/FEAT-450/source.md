---
kind: inline
jira_key: null
fetched_at: 2026-08-23T02:05:00Z
summary_oneline: "Namespaces for wikitoolkit — federate N wiki stores (sibling repos, non-code brains, ArangoDB dbs) behind ns::id with explicit + broadcast routing"
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
`.parrot/wiki` plane, an arbitrary store dir, or an ArangoDB database), and route
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

## Proposed shape (to validate against the code, not redesign)

- New `parrot/knowledge/wiki/federation.py`: `FederatedWikiStore(BaseWikiStore)` holding
  `{name: BaseWikiStore}` + the local namespace name. Read methods fan out with
  `asyncio.gather`, prefix ids `ns::`, merge via existing min-max/dedup helpers;
  `get_page`/`neighbors` route by id prefix; write methods delegate to the local namespace only.
  `stats` reports per namespace.
- `project.py`: `WikiNamespaceConfig` + `namespaces` on `WikiProjectConfig`; global registry
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

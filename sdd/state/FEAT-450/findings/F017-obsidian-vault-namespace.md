---
id: F017
query_id: DELTA-1
type: read
intent: Delta (user, 2026-08-23) — can an Obsidian vault be a namespace kind? Verify the existing vault scan/ingest surface and what breaks when a vault shares a repo's plane
executed_at: 2026-08-23T12:00:00Z
depth: 0
---
# F017 — A vault is already a buildable wiki plane; only the *shared-store* path is unsafe

## Summary
The vault side of "Obsidian as a namespace" is already built and needs **no new scanner**.
`vault_scan.py` turns a vault into the same `RepoScan` shape as `repo_scan.py` — same
`file:<relpath>` / `dir:<relpath>` concept ids, same `contains` dir pages — with zero LLM
calls and zero embeddings; `[[wikilinks]]` → `references`, `![[embeds]]` → `embeds`,
`#tags` → first-class tag pages (`tagged` edges). `wikitoolkit build` auto-detects
`.obsidian/` (`--vault/--no-vault`, cli.py:759-815) and routes there, so
`wikitoolkit build --path <vault>` **already produces a complete, queryable plane today**.
Notes carry `category="document"` (vault_scan.py:159) and tags `category="tag"` (203), so the
existing `query --category` filter already discriminates vault pages from code pages.

What is *not* safe is the second, newer path: `VaultIngestTool` (tools.py:288) ingests the
configured vault into **the project's own store** and then calls `_prune_removed`
(tools.py:367). `_prune_removed` (cli.py:390-423) is global over the store: it deletes every
`file:`/`dir:` page not present in *this* scan and every source whose `source_uri` is not in
`expected_uris`. Ingesting a vault into a repo's plane therefore deletes the entire codebase
wiki, and the next `wikitoolkit build` deletes the vault notes back. Ids compound the problem:
both scanners emit paths relative to their own root, so a vault's `file:README.md` overwrites
the repo's (F010).

This is the same collision class F010 already identified across repos, which is why the vault
belongs on the namespace path (one plane per corpus, `ns::` at the boundary) rather than as a
second corpus inside one plane.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py`
  lines: 1-30, 50, 55, 111, 159, 203
  symbol: `is_obsidian_vault`, `scan_vault`, `VAULT_EXCLUDE_DIRS`, `VaultScanStats`
  excerpt: |
    The scanner mirrors :mod:`parrot.knowledge.wiki.repo_scan`'s conventions
    exactly — same :class:`RepoScan` result shape, same ``file:<relpath>`` concept
    ids, same ``contains`` directory pages — so the whole build pipeline
    (incremental staleness, pruning, OKF export, graph.html) works unchanged;
    ``wikitoolkit build`` auto-detects vaults and routes here.
    ...
    category="document"     # 159 (notes)
    category="tag"          # 203 (tag pages)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 759-815, 842
  symbol: `build` (`--vault/--no-vault`)
  excerpt: |
    if vault_mode is None:
        vault_mode = is_obsidian_vault(root)     # 810-811
    if vault_mode:
        scan, vault_stats = scan_vault(...)      # 812-815
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 390-423
  symbol: `_prune_removed`
  excerpt: |
    for entry in await asyncio.to_thread(sources.list_sources):
        if entry.source_uri not in expected_uris:      # global over the store
            ...
    if cid.startswith("file:") and cid not in expected_files:
        if await store.delete_page(cid): removed += 1
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 49, 288, 322, 360-368
  symbol: `VaultIngestInput`, `VaultIngestTool`
  excerpt: |
    counts = await _ingest_files(self._store, sources, vault, scan, force=force)
    await self._store.upsert_pages(scan.dir_records)
    removed = await _prune_removed(self._store, sources, vault, scan)   # 367
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 177-186, 245-285
  symbol: `WikiProjectConfig.vault_dir`, `resolve_vault_dir`
  excerpt: |
    vault_dir: Optional[str]  # "Obsidian vault directory served by the wiki MCP
                              #  server; absolute, or relative to the project root."
    Precedence: explicit ``override`` > ``config.vault_dir`` > root itself if a vault
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`
  lines: 111-146
  symbol: `create_wiki_mcp_server` (vault block)
  excerpt: |
    vault = resolve_vault_dir(root, config)
    if vault is not None:
        toolkit = ObsidianToolkit(vault_path=vault)
        vault_tools = list(toolkit.get_tools_sync())
        vault_tools.append(VaultIngestTool(store, root=root, config=config))
- path: `sdd/specs/llmwiki-obsidian-plugin.spec.md`
  lines: 1-40
  symbol: FEAT-392
  excerpt: |
    Obsidian vault ingestion into PageIndex/GraphIndex (a different plane from the
    wikitoolkit retrieval store) — prior art, not a competing namespace design.

## Self-ingestion hazard for a vault-hosted plane (D4.2)
`scan_vault` (vault_scan.py:111-137) rglobs `*.md` under the vault and filters **only**
`VAULT_EXCLUDE_DIRS = {".obsidian", ".trash", ".git", ".hg", ".svn"}` (line 50). It takes no
exclude argument and never consults `WikiProjectConfig.exclude_dirs` (unlike `repo_scan`, which
this repo already configures with `exclude_dirs: [".parrot/wiki"]`). `WikiBookkeeper` writes
`index.md` and `log.md` **into the wiki storage dir** (bookkeeper.py:45 `LOG_FILENAME = "log.md"`,
201 `log_path = Path(wiki_dir) / self.LOG_FILENAME`). Consequence: a plane at
`<vault>/.parrot/wiki` is re-ingested into itself on every build. Fix required by D4.2 — add
`.parrot` to `VAULT_EXCLUDE_DIRS`, or have `scan_vault` honour `config.exclude_dirs`.

## Notes
`ObsidianToolkit` (`packages/ai-parrot/src/parrot/tools/obsidian.py`) is the *write* side
(vault note CRUD) and is orthogonal to namespaces; it is already registered by the MCP server
when a vault resolves (commit `861ab2110`, already in the proposal's history table).
Implication for FEAT-450: a `vault` namespace kind is a **config + registration** delta, not a
new ingest pipeline — plus the `_prune_removed` scoping fix, which the namespace work needs
anyway once writes are namespace-scoped.

---
id: F006
query_id: Q006
type: read
intent: Verify whether WikiToolkit and ObsidianToolkit exist as agent-callable toolkits
executed_at: 2026-08-23T09:27:00Z
depth: 0
parent_id: null
---

# F006 — Both the wiki tools and the ObsidianToolkit exist and are complete

## Summary

Neither "brain" component needs to be built. `parrot/knowledge/wiki/tools.py`
(FEAT-403 Module 5) exposes seven `AbstractTool` wrappers — `wiki_query`,
`wiki_page`, `wiki_related`, `wiki_remember`, `wiki_note`, `wiki_status`,
`vault_ingest` — with a `create_wiki_tools()` factory and namespace scoping
helpers (`_scoped_store`, `_reject_foreign_id`, `_unknown_namespace_error`).
`parrot/tools/obsidian.py` is a 20-tool `ObsidianToolkit(AbstractToolkit)` with
full vault CRUD (`create_note`, `update_note`, `append_note`, `delete_note`,
`move_note`), search (`search_notes`, `search_by_tag`, `search_with_backlinks`),
link-graph traversal (`get_backlinks`, `get_outgoing_links`), and OKF frontmatter
tooling. It uses the FEAT-391 lazy-lifecycle hooks (`_open`/`_close`).

`vault_ingest` is the seam that makes the "local LLM wiki mirrored in Obsidian"
bidirectional: notes written to the vault get ingested back into the wiki plane.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 155-541
  symbol: "wiki tool classes + factory"
  excerpt: |
    class WikiQueryTool(AbstractTool):    name = "wiki_query"      # 155
    class WikiPageTool(AbstractTool):     name = "wiki_page"       # 190
    class WikiRelatedTool(AbstractTool):  name = "wiki_related"    # 225
    class WikiRememberTool(AbstractTool): name = "wiki_remember"   # 257
    class WikiNoteTool(AbstractTool):     name = "wiki_note"       # 344
    class WikiStatusTool(AbstractTool):   name = "wiki_status"     # 409
    class VaultIngestTool(AbstractTool):  name = "vault_ingest"    # 425
    def create_wiki_tools(...)                                     # 541

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 23-95
  symbol: `_scoped_store`, `_reject_foreign_id`, `_unknown_namespace_error`

- path: `packages/ai-parrot/src/parrot/tools/obsidian.py`
  lines: 78-702
  symbol: `ObsidianToolkit`
  excerpt: |
    class ObsidianToolkit(AbstractToolkit):                     # 78
        async def _open/_close/_post_execute                    # 189/194/199
        async def read_note/read_notes/list_notes/get_note_metadata
        async def search_notes/search_by_tag/search_with_backlinks
        async def get_backlinks/get_outgoing_links/catalog_notes
        async def create_note/update_note/append_note/delete_note/move_note
        async def get_okf_metadata/validate_okf_frontmatter/classify_note
        async def apply_okf_frontmatter

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/vault_scan.py`
  lines: 1-1
  symbol: "Obsidian vault scanning for the wikitoolkit build pipeline (Phase E)"

- path: `packages/ai-parrot/src/parrot/interfaces/obsidian/`
  lines: 1-1
  symbol: "shared vault interface"
  excerpt: |
    models.py  index.py (wikilink resolution, backlinks, tags, aliases)
    parser.py  okf.py

## Notes

`wikitoolkit status` on this repo reports the plane live: 10683 pages, 17310
edges, and a registered `notes` namespace (kind=store, backend=sqlite) — the
FEAT-450 federation machinery is running, not just specified.

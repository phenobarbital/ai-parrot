---
id: F005
query_id: Q008
type: read
executed_at: 2026-09-14T00:05:00Z
duration_ms: 100
parent_id: null
depth: 0
---

# F005 — Existing wiki tools support one asserted link and post-commit structural refresh

## Summary

`wiki_remember` deterministically creates a memory page, optionally adds one asserted edge, and logs successful operations to the existing bookkeeper trail. The toolkit factory returns a fixed six-tool set. The managed Claude hook currently installs a post-commit `wikitoolkit upsert --changed --quiet` command and does not add a post-merge hook.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 130-135
  symbol: `WikiRememberInput`
  excerpt: |
    link_page_id: str | None = Field(default=None, description="Page to link to")
    rel: str | None = Field(default="references", description="Relation type")
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 272-327
  symbol: `WikiRememberTool._execute`
  excerpt: |
    page_id = "mem-" + hashlib.sha1(...).hexdigest()[:12]
    await self._store.add_edges([(page_id, link_page_id, rel or "references", "asserted")])
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 544-570
  symbol: `create_wiki_tools`
  excerpt: |
    The six `AbstractTool` instances: wiki_query, wiki_page, wiki_related,
    wiki_remember, wiki_note, wiki_status.
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py`
  lines: 166-181
  symbol: `git_hook_block`, `git_hook_new_file`
  excerpt: |
    "Build the `post-commit` hook block with an absolute path."
    f"{wt_bin} upsert --changed --quiet >/dev/null 2>&1 || true\n"

## Notes

The current remember schema has no dedicated `derived_from` or `about` parameters. Any provenance rule therefore changes an existing public tool input contract.

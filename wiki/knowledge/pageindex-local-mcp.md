---
title: PageIndex Local MCP Toolkit
summary: Serve per-repository PageIndex trees to Claude Code, Codex and Antigravity over stdio with `parrot mcp-local pageindex`; deterministic by default, LLM tools when `llm:` is set.
---

# PageIndex Local MCP Toolkit

## Purpose

`PageIndexToolkit` can be served to a coding agent as a local stdio MCP server, through the generic
`parrot toolkits` / `parrot mcp-local` machinery and a packaged `pageindex` template. Nothing PageIndex-specific
runs in the server: it lists whatever `PageIndexToolkit.get_tools()` returns, so tools added by later slices appear
automatically.

Trees live **per repository** under `.parrot/pageindex/` (git-ignored through `.parrot/*`); the directory is created
on first use. The default mode needs **no LLM**: tree management, markdown and ebook ingest, node edits, BM25 search
and body retrieval are all deterministic. Adding an `llm:` line to the section enables the tools that need a model.

## Public API

- [`PageIndexToolkit`](ref:parrot.knowledge.pageindex.toolkit) — the toolkit the server exposes

## Configuration & Parameters

### Install

```bash
parrot toolkits install pageindex          # seeds .parrot/mcp-toolkits.yaml and registers `parrot-pageindex` in the detected hosts
parrot self add pageindex                  # installs the extra it needs: ai-parrot[bookstore] (bm25s, pymupdf)
parrot toolkits list                       # reports which distributions each template needs and whether they are present
```

### The seeded section

```yaml
toolkits:
  pageindex:
    class: parrot.knowledge.pageindex.toolkit.PageIndexToolkit
    kwargs:
      storage_dir: <repo>/.parrot/pageindex
      max_result_chars: 24000
    # llm: anthropic:claude-haiku-5-5
    # llm_kwargs: {}
    exclude: [pageindex_agentic_retrieve]
    env: {}
```

### Constructor options

| Option | Default | Effect |
|---|---|---|
| `storage_dir` | required | Where trees, bodies and generations are stored (`ValueError` when missing). |
| `llm_client` | `None` | An `AbstractClient`; `parrot mcp-local` passes it when the section has `llm:`. It is wrapped into `PageIndexLLMAdapter(client=llm_client, model=model)`. Mutually exclusive with `adapter` (passing both raises `ValueError`). |
| `adapter` | `None` | An existing `PageIndexLLMAdapter`; unchanged behaviour for in-process callers. |
| `max_result_chars` | `None` | Upper bound on the text `retrieve` returns. Only `retrieve` is bounded. `None` keeps the output unbounded. |

`PageIndexToolkit.has_llm` is `True` when an adapter is configured.

### What is served

Without `llm:` the server serves every tool except the six that need a model, which the factory hides through
`PageIndexToolkit.llm_dependent_tools`:

- `pageindex_insert_content`
- `pageindex_import_file`
- `pageindex_import_folder`
- `pageindex_search_documents_scoped`
- `pageindex_agentic_retrieve`

Everything else works with no model: `pageindex_list_trees`, `create_tree`, `delete_tree`, `rename_tree`, `get_tree`,
`get_generation`, `vacuum_tree`, `search` (BM25), `retrieve`, `insert_markdown`, `insert_ebook`, `tag_node`,
`add_node`, `update_node`, `update_node_content`, `delete_node`, plus the read tools of the segment store
(`outline`, `list_documents`, `read_pages`, `read_segments`) and `pageindex_import_pdf` (structure from the PDF's
bookmarks or printed headings, no summaries; see [PageIndex Layout Structure](pageindex-layout-structure.md)). With
`llm:` set, the hidden tools appear (the agentic tool only once it is removed from `exclude:`) and
`search` / `retrieve` also run the LLM tree walk.

A search that asks only for the LLM walk (`use_bm25=False, use_llm_walk=True`) with no model raises
`ValueError("LLM walk requested but no LLM is configured for this toolkit")`; a default `search` degrades to BM25.

### The `exclude:` opt-in slot

`exclude:` in the template is the agreed place to switch tools off. The shipped template lists
`pageindex_agentic_retrieve` there, so the internal agentic retrieval tool is opt-in: it stays hidden even when `llm:`
is set. To expose it, set `llm:` and remove the name from the list (`exclude: []`). See
[PageIndex Agentic Retrieval and Citations](pageindex-agentic-retrieval.md) for what the tool does and its budgets.
Without `llm:` it is hidden regardless, because it is LLM-dependent.

## Usage Examples

```bash
parrot toolkits install pageindex
parrot mcp-local pageindex --config examples/pageindex-mcp.yaml     # same section with an active `llm:` line
```

A typical agent flow, as tool calls:

1. `pageindex_create_tree(tree_name="docs")`
2. `pageindex_insert_markdown(tree_name="docs", markdown="# Guide\n\n## Install\n...")`
3. `pageindex_search(tree_name="docs", query="install")` — ranked node ids, titles and summaries
4. `pageindex_retrieve(tree_name="docs", query="install", top_k=3)` — the bodies, bounded by `max_result_chars`

## Gotchas

- **No-LLM trees are plainer.** With no model, `insert_markdown` builds the structure offline: no node summaries and
  no document description are generated, and on OKF-enriched trees new nodes are typed `Section` instead of being
  classified by a model. BM25 therefore indexes titles and bodies only. Setting `llm:` adds summaries on later ingests.
- **`retrieve` truncation.** When the joined bodies exceed `max_result_chars`, whole sections are kept while they
  fit and the text ends with `[truncated: N more characters in K further sections — lower top_k or narrow the query]`.
  When the first section itself is cut, the marker reads `[truncated: N more characters in this section and K further
  sections — lower top_k or narrow the query]` (`in this section — …` when nothing else was dropped).
  The bound applies to the kept text: the marker (about 90 characters) is added on top, and a title line longer than
  the bound is kept whole. An oversized first section is cut at a paragraph break, never inside its `## title` line. The MCP wrapper appends
  its own `Metadata:` trailer after the tool text.
- **`vacuum_tree` never sweeps below the grace.** A `max_age_s` smaller than the configured `generation_grace_s` is
  raised to it, so a reader of the previous generation keeps its bodies; the result reports `removed` (body blobs),
  `revisions_removed` (document revision files) and the effective `max_age_s`.
- **`get_tree` is unbounded.** To browse a large tree use `pageindex_outline` (bounded to `max_chars=6000` by default)
  and read pages or segments from there.
- **Two writers are safe.** Writes take a per-tree `flock` and readers reload on a generation signature change
  (see [Generation Publication](pageindex-generation-publication.md)), so two hosts (for example Claude Code and
  Codex) on one repository, or a server next to an in-process toolkit, see each other's writes.
- **`bm25s` missing.** `parrot toolkits list` reports the missing distribution; install `ai-parrot[bookstore]`
  (`parrot self add pageindex`). Without it `search` cannot run BM25.
- **Template drift.** A section you already configured without the `exclude` key is reported as drift from the
  template. It is informational: it points at the opt-in slot above.
- **stdout stays pure while the scorer loads.** The prompt-injection scorer used by the segment store
  (`scan_injection`, on by default) resolves its model with stdout redirected to stderr, so the model-loading banner it
  prints on the first ingest never reaches the JSON-RPC channel; the server also binds its output stream when it
  starts, so no later redirect can misroute a frame. (Formerly `issue:70f18da2a8d5`, fixed by FEAT-844.)

## Related

- [PageIndex](pageindex.md) — the document-tree plane
- [Generation Publication](pageindex-generation-publication.md) — storage layout, locks, two-writer safety
- [Segment Store](pageindex-segment-store.md) — the read tools served next to the ones above
- [Local MCP toolkits](../tools/mcp-local-toolkits.md) — the generic `parrot mcp-local` / `parrot toolkits` machinery

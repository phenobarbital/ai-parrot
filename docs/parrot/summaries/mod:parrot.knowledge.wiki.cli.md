---
type: Wiki Summary
title: parrot.knowledge.wiki.cli
id: mod:parrot.knowledge.wiki.cli
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: '``wikitoolkit`` — machine-first CLI over the LLM Wiki retrieval plane.'
relates_to:
- concept: func:parrot.knowledge.wiki.cli.build
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.claude_hook
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.export
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.main
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.page
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.query
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.related
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.status
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.upsert
  rel: defines
- concept: func:parrot.knowledge.wiki.cli.wiki
  rel: defines
- concept: mod:parrot.knowledge.wiki.claude_code.hook
  rel: references
- concept: mod:parrot.knowledge.wiki.context
  rel: references
- concept: mod:parrot.knowledge.wiki.export
  rel: references
- concept: mod:parrot.knowledge.wiki.project
  rel: references
- concept: mod:parrot.knowledge.wiki.repo_scan
  rel: references
- concept: mod:parrot.knowledge.wiki.sources
  rel: references
- concept: mod:parrot.knowledge.wiki.store
  rel: references
---

# `parrot.knowledge.wiki.cli`

``wikitoolkit`` — machine-first CLI over the LLM Wiki retrieval plane.

Gives agents (and humans) scoped, token-budgeted access to a codebase
knowledge base built from the current repository — fully offline: the
build path is deterministic (:mod:`parrot.knowledge.wiki.repo_scan`)
and queries run on the SQLite FTS5/BM25 plane (FEAT-260).

Exposed two ways:

- ``wikitoolkit <command>`` — standalone console script, so coding
  assistants can run ``wikitoolkit query "<question>"`` cheaply;
- ``parrot wiki <command>`` — subcommand of the main parrot CLI.

Commands:
    build    Generate/refresh the KB graph from the repository.
    upsert   Incrementally re-ingest specific/changed files.
    query    Scoped question → token-budgeted context pack.
    page     Read one wiki page (progressive disclosure).
    related  Follow typed edges from a page.
    status   Plane statistics + staleness report.
    export   Export the wiki as a human-readable markdown bundle.

## Functions

- `def wiki() -> None` — LLM Wiki — codebase knowledge base for agents (FEAT-260).
- `def build(path_: Optional[str], name: Optional[str], backend: Optional[str], force: bool, no_git: bool, quiet: bool) -> None` — Generate (or refresh) the KB graph from the current repository.
- `def upsert(paths: tuple[str, ...], path_: Optional[str], changed: bool, quiet: bool) -> None` — Incrementally re-ingest specific files (or last-commit changes).
- `def query(question: str, path_: Optional[str], top_k: int, budget: int, category: Optional[str], store_opt: Optional[str], backend_opt: Optional[str], as_table: bool, show_body: bool, as_json: bool) -> None` — Scoped question against the codebase KB (lexical BM25 search).
- `def page(page_id: str, path_: Optional[str], max_tokens: Optional[int], store_opt: Optional[str], backend_opt: Optional[str], as_json: bool) -> None` — Read one wiki page in full (progressive disclosure).
- `def related(page_id: str, path_: Optional[str], rel: Optional[str], direction: str, store_opt: Optional[str], backend_opt: Optional[str], as_json: bool) -> None` — List pages linked to PAGE_ID by typed edges.
- `def status(path_: Optional[str], as_json: bool) -> None` — Show wiki plane statistics and source staleness.
- `def export(path_: Optional[str], output: str) -> None` — Export the wiki as a human-readable markdown bundle.
- `def claude_hook() -> None` — Claude Code PreToolUse hook runtime (reads stdin JSON).
- `def main() -> None` — Console-script entry point for ``wikitoolkit``.

---
description: Query or maintain the repository LLM-wiki knowledge graph (wikitoolkit)
argument-hint: [query <question> | page <id> | related <id> | status | build | --wiki [dir]]
allowed-tools: Bash(wikitoolkit:*)
---

# /parrotwiki — codebase knowledge graph

Arguments: `$ARGUMENTS`

This repository has an LLM-wiki knowledge base built from the source
tree (see the "Codebase Knowledge Graph" section of CLAUDE.md).
Interpret the arguments as one of the following actions and run the
matching `wikitoolkit` command with Bash:

- `query <question>` — run `wikitoolkit query "<question>"`. Read the
  most promising results with `wikitoolkit page <id>` and answer the
  question citing page ids. Prefer this over grepping raw files.
- `page <id>` — run `wikitoolkit page <id>` and summarise it.
- `related <id>` — run `wikitoolkit related <id>` and explain how the
  neighbours connect.
- `status` — run `wikitoolkit status` and report plane health.
- `build` — run `wikitoolkit build` and report what changed.
- `--wiki [dir]` — build a human-readable markdown wiki from the
  graph: run `wikitoolkit export -o <dir>` (default `docs/wiki`) and
  list what was written.
- no arguments — run `wikitoolkit status` and briefly explain the
  available actions above.

If `wikitoolkit` reports the wiki is not built yet, run
`wikitoolkit build` first, then retry the requested action.
